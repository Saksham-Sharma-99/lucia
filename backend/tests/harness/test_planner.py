from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import StepResult
from lucia.harness.agent_view import load
from lucia.harness.planner import CapHit, PlanDraft, PlanItemDraft, append, plan_task, validate
from lucia.llm.fake import FakeLLM
from tests.world import item, make_leased_run, make_task, make_world


def _draft(*items: dict[str, Any]) -> PlanDraft:
    base = {
        "tool": None,
        "input_hint": "",
        "expected_output": "",
        "uses": [],
        "wait_seconds": None,
        "wait_until": None,
    }
    return PlanDraft(items=[PlanItemDraft(**{**base, **i}) for i in items])


SCRIPT = {"title": "Draft the call script", "kind": "subagent"}
CALL = {"title": "Call Jane", "kind": "tool", "tool": "vapi.place_call", "uses": ["i1"]}


async def test_plan_is_stored_with_ids_in_order(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run)
    fake_llm.on("planner", _draft(SCRIPT, CALL))
    assert await plan_task(db, await load(db, run), task, 1)
    await db.refresh(task)
    assert [(i["id"], i["kind"], i["status"], i["uses"]) for i in task.plan] == [
        ("i1", "subagent", "PENDING", []),
        ("i2", "tool", "PENDING", ["i1"]),
    ]
    assert "## tools" in fake_llm.calls[0][1] and "vapi.place_call" in fake_llm.calls[0][1]


@pytest.mark.parametrize(
    ("bad", "error"),
    [
        (
            {"title": "Email", "kind": "tool", "tool": "gmail.send_email"},
            "not one of this agent's tools",
        ),
        ({"title": "Wait", "kind": "wait", "wait_seconds": 0}, "wait_seconds"),
        ({"title": "Wait", "kind": "wait"}, "either wait_seconds or wait_until"),
        (
            {
                "title": "Wait",
                "kind": "wait",
                "wait_seconds": 60,
                "wait_until": "2026-10-01T18:00:00-04:00",
            },
            "either wait_seconds or wait_until",
        ),
        ({"title": "Wait", "kind": "wait", "wait_until": "6pm"}, "ISO 8601"),
        ({"title": "Wait", "kind": "wait", "wait_until": "2026-10-01T18:00:00"}, "UTC offset"),
        (
            {"title": "Wait", "kind": "wait", "wait_until": "2026-10-01T09:00:00-04:00"},
            "in the past",
        ),
        ({"title": "Wait", "kind": "wait", "wait_until": "2027-10-01T09:00:00-04:00"}, "within"),
        ({"title": "Tool-less", "kind": "tool"}, "needs a tool"),
        ({"title": "Bad ref", "kind": "subagent", "uses": ["i9"]}, "uses i9"),
        ({"title": "Zero ref", "kind": "subagent", "uses": ["i0"]}, "uses i0"),  # ids start at i1
    ],
)
async def test_validation_errors(
    db: AsyncSession, clock: FrozenClock, bad: dict[str, Any], error: str
) -> None:
    w = await make_world(db)
    view = await load(db, await make_leased_run(db, w))
    errors = validate(_draft(bad), view, existing=[])
    assert len(errors) == 1 and error in errors[0]


async def test_too_many_items_is_an_error(db: AsyncSession) -> None:
    w = await make_world(db)
    view = await load(db, await make_leased_run(db, w))
    assert "at most 20" in validate(_draft(*[SCRIPT] * 21), view, existing=[])[0]


async def test_invalid_twice_blocks_the_task(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run)
    bad = {"title": "Email", "kind": "tool", "tool": "gmail.send_email"}
    fake_llm.on("planner", _draft(bad), _draft(bad))
    assert not await plan_task(db, await load(db, run), task, 1)
    await db.refresh(task)
    assert task.status == "BLOCKED" and task.plan == []
    assert await db.scalar(select(StepResult.kind)) == "item_failed"
    assert "not one of this agent's tools" in fake_llm.calls[1][1]


async def test_append_continues_ids_and_links_superseded_items(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run, plan=[item(1, status="DONE"), item(2, "tool")])
    fake_llm.on(
        "planner",
        _draft({"title": "Retry call in two days", "kind": "wait", "wait_seconds": 172800}, CALL),
    )
    new = await append(
        db,
        await load(db, run),
        task,
        reason="voicemail",
        new_info="voicemail",
        epoch=1,
        supersede=["i2"],
    )
    await db.refresh(task)
    assert new == ["i3", "i4"]
    assert '"new_items_start_at": "i3"' in fake_llm.calls[0][1]  # the planner needn't count
    assert task.plan[1]["status"] == "SUPERSEDED" and task.plan[1]["superseded_by"] == ["i3", "i4"]
    assert [i["added_in"] for i in task.plan[2:]] == [1, 1]
    assert task.plan_appends == 1


async def test_append_cap(db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run, plan=[item(1)], plan_appends=5)
    with pytest.raises(CapHit):
        await append(db, await load(db, run), task, reason="r", new_info="x", epoch=1)
    assert fake_llm.calls == []


async def test_a_clock_time_wait_is_stored_in_server_time(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    """ "Call me at 6 pm" in the contact's zone becomes one UTC instant; the model does no math."""
    w = await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run)
    wait = {"title": "Wait for 6 pm", "kind": "wait", "wait_until": "2026-10-01T18:00:00-04:00"}
    fake_llm.on("planner", _draft(wait, {**CALL, "uses": []}))
    assert await plan_task(db, await load(db, run), task, 1)
    await db.refresh(task)
    assert task.plan[0]["wait"] == {"until": "2026-10-01T22:00:00+00:00"}


async def test_the_planner_sees_the_server_time_and_each_contacts_local_time(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run)
    fake_llm.on("planner", _draft(SCRIPT))
    await plan_task(db, await load(db, run), task, 1)
    packet = fake_llm.calls[0][1]
    assert "## now" in packet and "2026-10-01T14:00:00+00:00" in packet
    assert '"Jane Doe": "2026-10-01T10:00:00-04:00"' in packet


def test_bare_numbers_in_uses_are_item_ids() -> None:
    draft = _draft(SCRIPT, {**CALL, "uses": ["1", " i1 "]})
    assert draft.items[1].uses == ["i1", "i1"]


WAIT = {"title": "Wait a day", "kind": "wait", "wait_seconds": 86400}


async def test_using_a_new_wait_is_an_error(db: AsyncSession, clock: FrozenClock) -> None:
    w = await make_world(db)
    view = await load(db, await make_leased_run(db, w))
    errors = validate(_draft(WAIT, {**SCRIPT, "uses": ["i1"]}), view, existing=[])
    assert errors == ["item i2 (Draft the call script) uses i1, a wait, which has no output"]


async def test_using_an_existing_wait_is_an_error(db: AsyncSession, clock: FrozenClock) -> None:
    """The planner numbered its new items one short: the extract pointed at the wait."""
    w = await make_world(db)
    view = await load(db, await make_leased_run(db, w))
    plan = [item(1, "tool", status="DONE"), item(2, "wait", status="DONE")]
    errors = validate(_draft({**SCRIPT, "uses": ["i2"]}), view, existing=plan)
    assert errors == ["item i3 (Draft the call script) uses i2, a wait, which has no output"]
