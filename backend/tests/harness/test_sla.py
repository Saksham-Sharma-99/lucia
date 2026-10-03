from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AppUser, Notification, StepResult
from lucia.firms.schemas import FirmSettings
from lucia.harness import control
from lucia.harness.attention import raise_attention
from lucia.notifications.sla import due_at, sweep
from tests.world import make_leased_run, make_world

NY_FRI_5PM = datetime(2026, 10, 2, 21, 0, tzinfo=UTC)  # Friday 17:00 in New York
SETTINGS = FirmSettings().model_dump(mode="json")


@pytest.mark.parametrize(
    ("urgency", "expected"),
    [
        ("P0", NY_FRI_5PM + timedelta(hours=1)),
        ("P1", datetime(2026, 10, 5, 21, 0, tzinfo=UTC)),
        ("P2", None),
    ],
)
def test_due_at(urgency: str, expected: datetime | None) -> None:
    assert due_at(urgency, NY_FRI_5PM, "America/New_York", SETTINGS) == expected


async def _item(db: AsyncSession, clock: FrozenClock) -> StepResult:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    item_id = await raise_attention(
        db, run, kind="question", summary="q", dedup_key="sr:sla", urgency="P1"
    )
    await db.commit()
    return await db.get_one(StepResult, item_id)


async def test_raise_sets_the_sla(db: AsyncSession, clock: FrozenClock) -> None:
    item = await _item(db, clock)
    assert item.sla_due_at is not None and item.sla_due_at > clock.now()


async def test_overdue_items_escalate_once(db: AsyncSession, clock: FrozenClock) -> None:
    item = await _item(db, clock)
    clock.advance(timedelta(days=5))
    assert await sweep(db) == 1
    await db.refresh(item)
    assert (item.urgency, item.data["escalated"]) == ("P0", True)
    assert await sweep(db) == 0


async def test_answered_items_are_left_alone(db: AsyncSession, clock: FrozenClock) -> None:
    item = await _item(db, clock)
    item.status = "answered"
    await db.commit()
    clock.advance(timedelta(days=5))
    assert await sweep(db) == 0


async def test_escalation_rings_the_bell_again(
    db: AsyncSession, clock: FrozenClock, user: AppUser
) -> None:
    item = await _item(db, clock)
    db.add(
        Notification(
            firm_id=item.firm_id,
            step_result_id=item.id,
            run_id=item.run_id,
            channel="in_app",
            target=str(user.id),
            status="sent",
            read_at=clock.now(),
        )
    )
    await db.commit()
    clock.advance(timedelta(days=5))
    await sweep(db)
    bell = await db.scalar(select(Notification))
    assert bell is not None and bell.read_at is None


async def test_takeover_pauses_the_clock(db: AsyncSession, clock: FrozenClock) -> None:
    item = await _item(db, clock)
    before = item.sla_due_at
    assert before is not None
    from lucia.db.models import AgentRun

    run = await db.get_one(AgentRun, item.run_id)
    await control.takeover(db, run, user_id=run.id, remarks="I'll handle it myself")
    clock.advance(timedelta(hours=3))
    await control.handback(db, run, user_id=run.id, remarks="Back to you, agent")
    await db.refresh(item)
    assert item.sla_due_at == before + timedelta(hours=3)
