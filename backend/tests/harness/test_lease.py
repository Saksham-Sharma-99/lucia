from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AgentRun, Episode
from lucia.harness.lease import LeaseLost, claim, ensure_lease, fence, release
from tests.world import make_run, make_world


async def test_claim_is_exclusive_and_activates_the_run(
    db: AsyncSession, clock: FrozenClock
) -> None:
    run = await make_run(db, await make_world(db))
    assert await claim(db, run.id, "w1") == 1
    assert await claim(db, run.id, "w2") is None
    await db.refresh(run)
    assert (run.status, run.lease_owner, run.started_at) == ("ACTIVE", "w1", clock.now())


async def test_expired_lease_is_reclaimed_and_the_old_holder_is_fenced(
    db: AsyncSession, clock: FrozenClock
) -> None:
    run = await make_run(db, await make_world(db))
    assert await claim(db, run.id, "w1") == 1
    clock.advance(timedelta(seconds=91))
    assert await claim(db, run.id, "w2") == 2
    with pytest.raises(LeaseLost):
        await fence(db, run.id, 1)
    await fence(db, run.id, 2)


async def test_ensure_lease_extends_only_a_live_lease(db: AsyncSession, clock: FrozenClock) -> None:
    run = await make_run(db, await make_world(db))
    epoch = await claim(db, run.id, "w1")
    assert epoch is not None
    clock.advance(timedelta(seconds=60))
    await ensure_lease(db, run.id, epoch)
    clock.advance(timedelta(seconds=60))  # 120s after claim, 60s after the extension
    assert await claim(db, run.id, "w2") is None
    clock.advance(timedelta(seconds=31))
    with pytest.raises(LeaseLost):
        await ensure_lease(db, run.id, epoch)


@pytest.mark.parametrize("status", ["TAKEN_OVER", "COMPLETED", "ENDED"])
async def test_held_or_finished_runs_are_not_claimable(
    db: AsyncSession, clock: FrozenClock, status: str
) -> None:
    run = await make_run(db, await make_world(db), status=status)
    assert await claim(db, run.id, "w1") is None


async def test_release_reports_pending_work(db: AsyncSession, clock: FrozenClock) -> None:
    w = await make_world(db)
    run = await make_run(db, w)
    epoch = await claim(db, run.id, "w1")
    assert epoch is not None
    assert await release(db, run.id, epoch) is False
    db.add(
        Episode(
            firm_id=w.firm.id,
            run_id=run.id,
            trigger_type="user_input",
            status="pending",
            dedup_key="msg:x",
        )
    )
    await db.commit()
    epoch = await claim(db, run.id, "w1")
    assert epoch is not None
    assert await release(db, run.id, epoch) is True
    fresh = await db.get(AgentRun, run.id, populate_existing=True)
    assert fresh is not None and fresh.lease_expires_at is None
