"""Every future wake-up is an Episode row (status=scheduled, due_at). Beat arms rows due
within the horizon; `fire` moves an armed row to pending under its guard (HLD §10)."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.db.models import AgentRun, Episode
from lucia.db.models.run import CLAIMABLE

HORIZON = timedelta(hours=1)
REFIRE_GRACE = timedelta(seconds=60)


async def refresh_next_wake(session: AsyncSession, run_id: uuid.UUID) -> None:
    earliest = (
        select(func.min(Episode.due_at))
        .where(Episode.run_id == run_id, Episode.status.in_(("scheduled", "armed")))
        .scalar_subquery()
    )
    await session.execute(
        update(AgentRun).where(AgentRun.id == run_id).values(next_wake_at=earliest)
    )


async def schedule(
    session: AsyncSession,
    run: AgentRun,
    *,
    source: str,
    due_at: datetime,
    dedup_key: str,
    reason: str,
    task_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    rung: int | None = None,
    attempt: int | None = None,
) -> uuid.UUID | None:
    """Adds a scheduled Episode (None if the dedup key exists); the caller commits."""
    episode_id = await session.scalar(
        insert(Episode)
        .values(
            firm_id=run.firm_id,
            run_id=run.id,
            task_id=task_id,
            trigger_type="scheduled",
            status="scheduled",
            source=source,
            metadata={**(metadata or {}), "agent_prompt_id": str(run.agent_prompt_id)},
            dedup_key=dedup_key,
            due_at=due_at,
            reason=reason,
            rung=rung,
            attempt=attempt,
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(Episode.id)
    )
    await refresh_next_wake(session, run.id)
    return episode_id


async def supersede(
    session: AsyncSession,
    *,
    reason: str,
    run_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
) -> None:
    """Cancel future wake-ups of a run (or one task): bump the guard so in-flight fires no-op."""
    stmt = (
        update(Episode)
        .where(Episode.run_id == run_id, Episode.status.in_(("scheduled", "armed")))
        .values(
            status="superseded",
            guard_version=Episode.guard_version + 1,
            metadata=Episode.metadata_.op("||")(
                func.jsonb_build_object("supersede", func.jsonb_build_object("reason", reason))
            ),
        )
        .execution_options(synchronize_session=False)
    )
    if task_id is not None:
        stmt = stmt.where(Episode.task_id == task_id)
    await session.execute(stmt)
    await refresh_next_wake(session, run_id)


async def restore(session: AsyncSession, *, reason: str, run_id: uuid.UUID) -> None:
    """Undo `supersede(reason=...)`: the wake-ups come back at their original times (a past
    one fires on the next arm). The guard moves again, so nothing armed before still fires."""
    await session.execute(
        update(Episode)
        .where(
            Episode.run_id == run_id,
            Episode.status == "superseded",
            Episode.metadata_["supersede"]["reason"].astext == reason,
        )
        .values(
            status="scheduled",
            guard_version=Episode.guard_version + 1,
            metadata=Episode.metadata_.op("-")("supersede"),
        )
        .execution_options(synchronize_session=False)
    )
    await refresh_next_wake(session, run_id)


async def arm_due(session: AsyncSession) -> list[tuple[uuid.UUID, int, datetime]]:
    """Arms rows due within the horizon, and re-arms armed rows whose fire never came."""
    t = get_clock().now()
    rows = await session.execute(
        update(Episode)
        .where(
            or_(
                (Episode.status == "scheduled") & (Episode.due_at < t + HORIZON),
                (Episode.status == "armed") & (Episode.due_at < t - REFIRE_GRACE),
            )
        )
        .values(status="armed")
        .returning(Episode.id, Episode.guard_version, Episode.due_at)
        .execution_options(synchronize_session=False)
    )
    armed = [(i, guard, due) for i, guard, due in rows.all() if due]  # narrows due_at
    await session.commit()
    return armed


async def fire(
    session: AsyncSession, episode_id: uuid.UUID, guard_version: int
) -> uuid.UUID | None:
    """armed → pending (claimable run) or deferred (held run); returns the run to advance."""
    run_status = select(AgentRun.status).where(AgentRun.id == Episode.run_id).scalar_subquery()
    row = await session.execute(
        update(Episode)
        .where(
            Episode.id == episode_id,
            Episode.guard_version == guard_version,
            Episode.status == "armed",
        )
        .values(
            status=case((run_status.in_(CLAIMABLE), "pending"), else_="deferred"),
            queued_at=get_clock().now(),
        )
        .returning(Episode.run_id, Episode.status)
        .execution_options(synchronize_session=False)
    )
    fired = row.first()
    await session.commit()
    return fired[0] if fired and fired[1] == "pending" else None


async def reap(session: AsyncSession) -> list[uuid.UUID]:
    """Claimable runs with waiting work, or left RUNNING, and no live lease (a crashed or lost
    worker)."""
    t = get_clock().now()
    work = (
        select(Episode.id)
        .where(Episode.run_id == AgentRun.id, Episode.status.in_(("pending", "running")))
        .exists()
    )
    return list(
        await session.scalars(
            select(AgentRun.id).where(
                AgentRun.status.in_(CLAIMABLE),
                or_(AgentRun.lease_expires_at.is_(None), AgentRun.lease_expires_at < t),
                or_(work, AgentRun.substatus == "RUNNING"),  # a worker died mid-unit
            )
        )
    )
