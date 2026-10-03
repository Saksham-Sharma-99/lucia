"""Human controls over runs (RUNTIME_SPEC §13.2, §13.3): kill switch, takeover, hand-back, end.
Each bumps the lease epoch, so a worker mid-step is fenced out."""

import uuid
from datetime import datetime

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.audit import audit
from lucia.core.clock import get_clock
from lucia.db.models import (
    Agent,
    AgentRun,
    CompiledAgentFirmMapping,
    Episode,
    RunTask,
    StepResult,
)
from lucia.db.models.run import CLAIMABLE, TERMINAL_TASK
from lucia.harness.intake import EpisodeSpec, insert_episode
from lucia.harness.journal import append
from lucia.harness.steps import settle_callback
from lucia.notifications.updates import post_run_update
from lucia.scheduling import scheduler
from lucia.worker.dispatch import send


class ControlError(Exception):
    """The run isn't in a state that allows this action."""


async def _hold(session: AsyncSession, run_ids: list[uuid.UUID], on: bool) -> None:
    """Park a held run's pending Episodes as deferred, or put them back in the queue."""
    src, dst = ("pending", "deferred") if on else ("deferred", "pending")
    await session.execute(
        update(Episode)
        .where(Episode.run_id.in_(run_ids), Episode.status == src)
        .values(status=dst, queued_at=Episode.queued_at if on else get_clock().now())
    )


async def set_kill(session: AsyncSession, mapping_id: uuid.UUID, on: bool) -> list[uuid.UUID]:
    """Pause (or resume) every live run on a mapping in the caller's transaction. Returns the
    runs; on resume the caller enqueues them once it has committed."""
    if on:
        where = and_(AgentRun.mapping_id == mapping_id, AgentRun.status.in_(CLAIMABLE))
        values = {"status": "PAUSED", "substatus": "kill_switch"}
    else:
        where = and_(
            AgentRun.mapping_id == mapping_id,
            AgentRun.status == "PAUSED",
            AgentRun.substatus == "kill_switch",
        )
        values = {"status": "ACTIVE", "substatus": None}
    run_ids = list(
        await session.scalars(
            update(AgentRun)
            .where(where)
            .values(**values, lease_epoch=AgentRun.lease_epoch + 1, lease_expires_at=None)
            .returning(AgentRun.id)
            .execution_options(synchronize_session=False)
        )
    )
    await _hold(session, run_ids, on)
    return run_ids


async def pause_for_subject(session: AsyncSession, run: AgentRun) -> None:
    run.status, run.substatus = "PAUSED", "subject_closed"
    await _hold(session, [run.id], True)


async def resume_for_subject(session: AsyncSession, subject_id: uuid.UUID) -> list[uuid.UUID]:
    """The subject reopened: its paused runs carry on. The caller commits, then enqueues."""
    run_ids = list(
        await session.scalars(
            update(AgentRun)
            .where(
                AgentRun.subject_id == subject_id,
                AgentRun.status == "PAUSED",
                AgentRun.substatus == "subject_closed",
            )
            .values(status="ACTIVE", substatus=None)
            .returning(AgentRun.id)
            .execution_options(synchronize_session=False)
        )
    )
    await _hold(session, run_ids, False)
    return run_ids


async def sweep_killed(session: AsyncSession) -> int:
    """Beat backstop: runs still claimable on a killed mapping."""
    killed = await session.scalars(
        select(CompiledAgentFirmMapping.id).where(CompiledAgentFirmMapping.kill_switch)
    )
    paused = sum([len(await set_kill(session, mapping_id, True)) for mapping_id in killed])
    await session.commit()
    return paused


async def takeover(
    session: AsyncSession, run: AgentRun, *, user_id: uuid.UUID, remarks: str
) -> None:
    await _lock(session, run)
    stuck = (run.status, run.substatus) == ("PAUSED", "repeated_failure")  # hand-back resumes it
    if run.status not in CLAIMABLE and not stuck:
        raise ControlError(f"A {run.status} run can't be taken over")
    now = get_clock().now()
    run.status, run.substatus = "TAKEN_OVER", None
    run.takeover = {"by": str(user_id), "remarks": remarks, "at": now.isoformat()}
    run.lease_epoch += 1
    run.lease_expires_at = None
    await scheduler.supersede(session, run_id=run.id, reason="takeover")
    await _hold(session, [run.id], True)
    await _note(session, run, user_id, "run.takeover", f"Taken over: {remarks}")


async def handback(
    session: AsyncSession, run: AgentRun, *, user_id: uuid.UUID, remarks: str
) -> uuid.UUID:
    """Resume a taken-over run; the remarks run first, as a hand-back Episode for triage."""
    await _lock(session, run)
    if run.status != "TAKEN_OVER" or run.takeover is None:
        raise ControlError("Only a taken-over run can be handed back")
    now = get_clock().now()
    taken = run.takeover
    run.status = "ACTIVE"
    run.takeover = {
        **taken,
        "handback": {"by": str(user_id), "remarks": remarks, "at": now.isoformat()},
    }
    await _hold(session, [run.id], False)
    await scheduler.restore(session, run_id=run.id, reason="takeover")
    # The SLA clock doesn't run while a person holds the run (ADR-HN-10).
    paused = now - datetime.fromisoformat(taken["at"])
    await session.execute(
        update(StepResult)
        .where(
            StepResult.run_id == run.id,
            StepResult.status == "open",
            StepResult.sla_due_at.is_not(None),
        )
        .values(sla_due_at=StepResult.sla_due_at + paused)
    )
    episode_id = await insert_episode(
        session,
        run,
        EpisodeSpec(
            trigger_type="handback",
            dedup_key=f"handback:{run.id}:{taken['at']}",
            metadata={"remarks": remarks, "by": str(user_id)},
        ),
    )
    await _note(session, run, user_id, "run.handback", f"Handed back: {remarks}")
    send("harness.advance_run", run.id)
    assert episode_id is not None
    return episode_id


async def _lock(session: AsyncSession, run: AgentRun) -> None:
    """Re-read under FOR UPDATE: a claim since the caller's read would otherwise keep its epoch."""
    await session.refresh(run, with_for_update=True)


ENDED_BECAUSE = {
    "max_duration": "it reached its maximum duration",
    "max_steps": "it reached its step limit",
    "subject_closed": "the case was closed",
    "closed_by_person": "a person closed it",
}
OPEN_ITEM = ("PENDING", "RUNNING", "WAITING")


async def end_run(session: AsyncSession, run: AgentRun, reason: str) -> None:
    """Nothing more runs: reports already in settle their calls (keeping the transcript), the
    rest of the pending input is dropped, open tasks and their unfinished items are skipped, and
    the run's chats are told."""
    now = get_clock().now()
    run.status, run.substatus = "ENDED", None
    run.ended_at, run.ended_reason = now, reason
    await scheduler.supersede(session, run_id=run.id, reason="run_ended")
    pending = await session.scalars(
        select(Episode).where(Episode.run_id == run.id, Episode.status.in_(("pending", "deferred")))
    )
    for episode in pending:
        if episode.trigger_type == "external_response":
            await settle_callback(session, episode.metadata_)
        episode.status = "superseded"
    why = f"Run ended ({reason})"
    tasks = await session.scalars(
        select(RunTask).where(RunTask.run_id == run.id, RunTask.status.not_in(TERMINAL_TASK))
    )
    for task in tasks:
        task.status, task.ended_at = "SKIPPED", now
        task.plan = [
            {**it, "status": "SKIPPED", "reason": why} if it["status"] in OPEN_ITEM else it
            for it in task.plan
        ]
    handle = await session.scalar(select(Agent.handle).where(Agent.id == run.agent_id))
    await post_run_update(
        session,
        run,
        body=f"@{handle}'s run ended: {ENDED_BECAUSE.get(reason, reason)}.",
        source_id="ended",
    )
    await session.commit()


async def _note(
    session: AsyncSession, run: AgentRun, user_id: uuid.UUID, action: str, text: str
) -> None:
    await append(
        session, run, text=text, source="human", key=f"{action}:{get_clock().now().isoformat()}"
    )
    await audit(
        session,
        action=action,
        entity_type="agent_run",
        entity_id=run.id,
        firm_id=run.firm_id,
        actor_type="user",
        actor_id=str(user_id),
        data={"text": text},
    )
    await session.commit()
