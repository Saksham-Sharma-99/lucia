"""One worker advances a run at a time: a lease with a fencing epoch (HLD §9.0, Appendix B).
Time comes from the injected Clock, so tests can expire a lease."""

import uuid
from datetime import timedelta

from sqlalchemy import case, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.db.models import AgentRun, Episode, RunTask
from lucia.db.models.run import CLAIMABLE

LEASE_TTL = timedelta(seconds=90)
RENEW_BELOW = timedelta(seconds=45)


class LeaseLost(Exception):
    """Another worker holds the run now; stop before writing anything else."""


async def claim(session: AsyncSession, run_id: uuid.UUID, owner: str) -> int | None:
    now = get_clock().now()
    epoch = await session.scalar(
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status.in_(CLAIMABLE),
            or_(AgentRun.lease_expires_at.is_(None), AgentRun.lease_expires_at < now),
        )
        .values(
            lease_owner=owner,
            lease_epoch=AgentRun.lease_epoch + 1,
            lease_expires_at=now + LEASE_TTL,
            status=case((AgentRun.status == "CREATED", "ACTIVE"), else_=AgentRun.status),
            started_at=func.coalesce(AgentRun.started_at, now),
        )
        .returning(AgentRun.lease_epoch)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return epoch


async def ensure_lease(session: AsyncSession, run_id: uuid.UUID, epoch: int) -> None:
    """Called between steps: raises LeaseLost unless the run is still ours (same epoch, lease
    live, status claimable: a takeover, kill switch or end since the last check is caught),
    and extends the lease when it runs low."""
    now = get_clock().now()
    row = (
        await session.execute(
            select(AgentRun.lease_expires_at, AgentRun.status).where(
                AgentRun.id == run_id, AgentRun.lease_epoch == epoch
            )
        )
    ).one_or_none()
    if row is None or row.lease_expires_at is None or row.lease_expires_at <= now:
        raise LeaseLost
    if row.status not in CLAIMABLE:
        raise LeaseLost
    expires = row.lease_expires_at
    if expires - now < RENEW_BELOW:
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.lease_epoch == epoch)
            .values(lease_expires_at=now + LEASE_TTL)
            .execution_options(synchronize_session=False)
        )
        await session.commit()


async def fence(session: AsyncSession, run_id: uuid.UUID, epoch: int) -> None:
    """Inside a write transaction: FOR SHARE blocks a re-claim or a human control until this
    transaction ends."""
    row = (
        await session.execute(
            select(AgentRun.lease_epoch, AgentRun.status)
            .where(AgentRun.id == run_id)
            .with_for_update(read=True)
        )
    ).one()
    if row.lease_epoch != epoch or row.status not in CLAIMABLE:
        raise LeaseLost


async def has_work(session: AsyncSession, run_id: uuid.UUID, *, tasks: bool = True) -> bool:
    work = exists().where(Episode.run_id == run_id, Episode.status.in_(("pending", "running")))
    if tasks:
        todo = RunTask.status.in_(("TODO", "IN_PROGRESS"))
        work = work | exists().where(RunTask.run_id == run_id, todo)
    return bool(await session.scalar(select(work)))


async def release(
    session: AsyncSession, run_id: uuid.UUID, epoch: int, *, tasks: bool = True
) -> bool:
    """Drops the lease; True when work is waiting, so the caller enqueues the run again.
    `tasks=False` counts only Episodes: open tasks that just proved unrunnable don't count."""
    await session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.lease_epoch == epoch)
        .values(
            lease_expires_at=None,
            lease_owner=None,
            # the unit ended: RUNNING would read as a dead worker to the reaper
            substatus=case((AgentRun.substatus == "RUNNING", "WAITING"), else_=AgentRun.substatus),
        )
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return await has_work(session, run_id, tasks=tasks)
