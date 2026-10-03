import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AgentRun, Episode, StepResult
from lucia.harness.intake import EpisodeSpec, TargetUnavailable, create_or_fold
from tests.world import World, make_run, make_world


def _spec(key: str = "msg:1") -> EpisodeSpec:
    return EpisodeSpec(trigger_type="user_input", dedup_key=key, metadata={"message_id": "m1"})


async def _intake(db: AsyncSession, w: World, key: str = "msg:1"):
    return await create_or_fold(
        db,
        firm_id=w.firm.id,
        agent_id=w.agent.id,
        subject_id=w.subject.id,
        origin="playground",
        spec=_spec(key),
    )


async def test_creates_a_run_and_a_pending_episode(
    db: AsyncSession, clock: FrozenClock, sent: list[tuple[str, tuple[str, ...]]]
) -> None:
    w = await make_world(db)
    r = await _intake(db, w)
    assert r.created_run and not r.deferred and r.episode_id
    run = await db.get_one(AgentRun, r.run_id)
    ep = await db.get_one(Episode, r.episode_id)
    assert (run.status, run.agent_prompt_id, run.mapping_id) == (
        "CREATED",
        w.version.id,
        w.mapping.id,
    )
    assert (ep.status, ep.task_id, ep.metadata_["agent_prompt_id"]) == (
        "pending",
        None,
        str(w.version.id),
    )
    assert sent == [("harness.advance_run", (str(run.id),))]


async def test_folds_into_the_live_run_and_dedups_replays(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    first = await _intake(db, w, "msg:1")
    second = await _intake(db, w, "msg:2")
    replay = await _intake(db, w, "msg:2")
    assert second.run_id == first.run_id and not second.created_run
    assert replay.episode_id is None
    assert await db.scalar(select(func.count()).select_from(Episode)) == 2


async def test_held_run_defers_the_episode_without_enqueueing(
    db: AsyncSession, clock: FrozenClock, sent: list[tuple[str, tuple[str, ...]]]
) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="TAKEN_OVER")
    r = await _intake(db, w)
    assert r.run_id == run.id and r.deferred
    ep = await db.get_one(Episode, r.episode_id)
    assert ep.status == "deferred" and sent == []


async def test_awaiting_confirmation_folds_back_to_active(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="AWAITING_CONFIRMATION")
    item = StepResult(
        firm_id=w.firm.id,
        run_id=run.id,
        type="attention",
        kind="confirm_completion",
        urgency="P1",
        summary="Confirm",
        summary_public="Confirm",
        blocking=True,
        status="open",
        dedup_key="sr:c",
    )
    db.add(item)
    await db.commit()
    await _intake(db, w)
    await db.refresh(run)
    await db.refresh(item)
    assert (run.status, item.status) == ("ACTIVE", "resolved_by_system")


async def test_a_replayed_ask_does_not_reopen_a_run_awaiting_confirmation(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    await _intake(db, w, "msg:1")
    run = await db.scalar(select(AgentRun))
    assert run is not None
    run.status = "AWAITING_CONFIRMATION"
    await db.commit()
    await _intake(db, w, "msg:1")  # e.g. Slack redelivering the same event
    await db.refresh(run)
    assert run.status == "AWAITING_CONFIRMATION"


async def test_finished_run_gets_a_new_one(db: AsyncSession, clock: FrozenClock) -> None:
    w = await make_world(db)
    old = await make_run(db, w, status="COMPLETED")
    r = await _intake(db, w)
    assert r.created_run and r.run_id != old.id


@pytest.mark.parametrize("change", [{"kill_switch": True}, {"status": "inactive"}])
async def test_unavailable_mapping_is_refused(
    db: AsyncSession, clock: FrozenClock, change: dict[str, object]
) -> None:
    w = await make_world(db)
    for k, v in change.items():
        setattr(w.mapping, k, v)
    await db.commit()
    with pytest.raises(TargetUnavailable):
        await _intake(db, w)
