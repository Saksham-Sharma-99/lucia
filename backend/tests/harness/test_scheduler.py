from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock, get_clock
from lucia.db.models import AgentRun, Episode
from lucia.scheduling import scheduler
from tests.world import make_run, make_world


async def _schedule(db: AsyncSession, run: AgentRun, minutes: int, key: str) -> Episode:
    eid = await scheduler.schedule(
        db,
        run,
        source="ladder",
        due_at=get_clock().now() + timedelta(minutes=minutes),
        dedup_key=key,
        reason="follow up",
    )
    await db.commit()
    assert eid is not None
    return await db.get_one(Episode, eid)


async def test_schedule_inserts_once_and_tracks_next_wake(
    db: AsyncSession, clock: FrozenClock
) -> None:
    run = await make_run(db, await make_world(db))
    later = await _schedule(db, run, 90, "ladder:a")
    soon = await _schedule(db, run, 30, "ladder:b")
    assert later.status == soon.status == "scheduled"
    assert (
        await scheduler.schedule(
            db, run, source="ladder", due_at=clock.now(), dedup_key="ladder:a", reason="x"
        )
        is None
    )
    await db.refresh(run)
    assert run.next_wake_at == soon.due_at


async def test_arm_only_within_the_horizon(db: AsyncSession, clock: FrozenClock) -> None:
    run = await make_run(db, await make_world(db))
    near = await _schedule(db, run, 30, "ladder:near")
    await _schedule(db, run, 120, "ladder:far")
    armed = await scheduler.arm_due(db)
    assert [a[0] for a in armed] == [near.id]
    await db.refresh(near)
    assert near.status == "armed"
    assert await scheduler.arm_due(db) == []  # not re-armed while on time


async def test_overdue_armed_rows_are_refired(db: AsyncSession, clock: FrozenClock) -> None:
    run = await make_run(db, await make_world(db))
    ep = await _schedule(db, run, 1, "ladder:x")
    await scheduler.arm_due(db)
    clock.advance(timedelta(minutes=5))
    assert [a[0] for a in await scheduler.arm_due(db)] == [ep.id]


async def test_fire_moves_to_pending_and_returns_the_run(
    db: AsyncSession, clock: FrozenClock
) -> None:
    run = await make_run(db, await make_world(db))
    ep = await _schedule(db, run, 1, "ladder:x")
    ((_, guard, _),) = await scheduler.arm_due(db)
    assert await scheduler.fire(db, ep.id, guard) == run.id
    await db.refresh(ep)
    assert (ep.status, ep.queued_at) == ("pending", clock.now())
    assert await scheduler.fire(db, ep.id, guard) is None  # duplicate delivery


async def test_fire_with_a_stale_guard_is_a_no_op(db: AsyncSession, clock: FrozenClock) -> None:
    run = await make_run(db, await make_world(db))
    ep = await _schedule(db, run, 1, "ladder:x")
    ((_, guard, _),) = await scheduler.arm_due(db)
    await scheduler.supersede(db, run_id=run.id, reason="takeover")
    await db.commit()
    assert await scheduler.fire(db, ep.id, guard) is None
    await db.refresh(ep)
    assert ep.status == "superseded" and ep.metadata_["supersede"]["reason"] == "takeover"


async def test_fire_on_a_held_run_defers(db: AsyncSession, clock: FrozenClock) -> None:
    run = await make_run(db, await make_world(db))
    ep = await _schedule(db, run, 1, "ladder:x")
    ((_, guard, _),) = await scheduler.arm_due(db)
    run.status = "TAKEN_OVER"
    await db.commit()
    assert await scheduler.fire(db, ep.id, guard) is None
    await db.refresh(ep)
    assert ep.status == "deferred"


async def test_supersede_for_a_task_clears_next_wake(db: AsyncSession, clock: FrozenClock) -> None:
    run = await make_run(db, await make_world(db))
    await _schedule(db, run, 10, "ladder:x")
    await scheduler.supersede(db, run_id=run.id, reason="run_ended")
    await db.commit()
    await db.refresh(run)
    assert run.next_wake_at is None


async def test_reap_finds_runs_with_work_and_no_live_lease(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    stuck = await make_run(
        db, w, status="ACTIVE", lease_expires_at=clock.now() - timedelta(seconds=1)
    )
    db.add(
        Episode(
            firm_id=w.firm.id,
            run_id=stuck.id,
            trigger_type="user_input",
            status="pending",
            dedup_key="msg:1",
        )
    )
    other = await make_world(db, slug="other-firm", handle="other")
    held = await make_run(db, other, status="TAKEN_OVER")
    db.add(
        Episode(
            firm_id=other.firm.id,
            run_id=held.id,
            trigger_type="user_input",
            status="pending",
            dedup_key="msg:2",
        )
    )
    await db.commit()
    assert await scheduler.reap(db) == [stuck.id]


async def test_reap_finds_a_run_whose_worker_died_mid_task(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    crashed = await make_run(
        db,
        w,
        status="ACTIVE",
        substatus="RUNNING",
        lease_expires_at=clock.now() - timedelta(seconds=1),
    )
    other = await make_world(db, slug="other-firm", handle="other")
    await make_run(db, other, status="ACTIVE", substatus="WAITING")  # idle, nothing to do
    assert await scheduler.reap(db) == [crashed.id]
