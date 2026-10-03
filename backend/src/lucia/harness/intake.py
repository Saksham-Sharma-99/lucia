"""The only way work enters a run: create the (agent, subject) run or fold into the live one,
then store the trigger as an Episode (RUNTIME_SPEC §3)."""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.db.models import AgentRun, CompiledAgentFirmMapping, Episode, StepResult
from lucia.db.models.run import CLAIMABLE, LIVE, LIVE_PREDICATE
from lucia.worker.dispatch import send

M = CompiledAgentFirmMapping


class TargetUnavailable(Exception):
    """The agent has no active, non-killed mapping at this firm."""


@dataclass(frozen=True)
class EpisodeSpec:
    trigger_type: str
    dedup_key: str
    metadata: dict[str, Any] = field(default_factory=dict)
    task_id: uuid.UUID | None = None
    source: str | None = None  # scheduled Episodes say why (DATA_MODEL §3.8)


@dataclass(frozen=True)
class IntakeResult:
    run_id: uuid.UUID
    episode_id: uuid.UUID | None  # None: a replay of an episode we already have
    created_run: bool
    deferred: bool


async def insert_episode(
    session: AsyncSession, run: AgentRun, spec: EpisodeSpec
) -> uuid.UUID | None:
    """Pending on a claimable run, deferred on a held one; None when the dedup key exists."""
    status = "pending" if run.status in CLAIMABLE else "deferred"
    return await session.scalar(
        insert(Episode)
        .values(
            firm_id=run.firm_id,
            run_id=run.id,
            task_id=spec.task_id,
            trigger_type=spec.trigger_type,
            source=spec.source,
            status=status,
            metadata={**spec.metadata, "agent_prompt_id": str(run.agent_prompt_id)},
            dedup_key=spec.dedup_key,
            queued_at=get_clock().now(),
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(Episode.id)
    )


async def create_or_fold(
    session: AsyncSession,
    *,
    firm_id: uuid.UUID,
    agent_id: uuid.UUID,
    subject_id: uuid.UUID,
    origin: str,
    spec: EpisodeSpec,
) -> IntakeResult:
    mapping = await session.scalar(
        select(M).where(
            M.firm_id == firm_id, M.agent_id == agent_id, M.status == "active", ~M.kill_switch
        )
    )
    if mapping is None:
        raise TargetUnavailable
    new_id = await session.scalar(
        insert(AgentRun)
        .values(
            firm_id=firm_id,
            mapping_id=mapping.id,
            agent_id=agent_id,
            agent_prompt_id=mapping.agent_prompt_id,
            subject_id=subject_id,
            origin=origin,
        )
        .on_conflict_do_nothing(
            index_elements=["agent_id", "subject_id"], index_where=text(LIVE_PREDICATE)
        )
        .returning(AgentRun.id)
    )
    run = await session.scalar(
        select(AgentRun)
        .where(AgentRun.agent_id == agent_id, AgentRun.subject_id == subject_id)
        .where(AgentRun.status.in_(LIVE))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert run is not None
    episode_id = await insert_episode(session, run, spec)
    if episode_id and run.status == "AWAITING_CONFIRMATION":  # a new ask: it isn't done after all
        run.status = "ACTIVE"
        await session.execute(
            update(StepResult)
            .where(
                StepResult.run_id == run.id,
                StepResult.kind == "confirm_completion",
                StepResult.status == "open",
            )
            .values(status="resolved_by_system")
        )
    deferred = run.status not in CLAIMABLE
    await session.commit()
    if episode_id and not deferred:
        send("harness.advance_run", run.id)
    return IntakeResult(run.id, episode_id, new_id is not None, deferred)
