from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import Episode
from lucia.harness.agent_view import load
from lucia.harness.planner import PlanDraft, PlanItemDraft
from lucia.harness.relevance import ItemVerdict, Relevance, check
from lucia.llm.fake import FakeLLM
from tests.world import item, make_leased_run, make_task, make_world


def _rel(*verdicts: tuple[str, str], append: bool = False) -> Relevance:
    return Relevance(
        verdicts=[ItemVerdict(item_id=i, verdict=v, reason="because") for i, v in verdicts],  # type: ignore[arg-type]
        append_needed=append,
        append_reason="new channel" if append else "",
    )


async def _setup(db: AsyncSession, plan: list[dict[str, Any]]) -> tuple[Any, Any, Episode]:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run, plan=plan)
    ep = Episode(
        firm_id=w.firm.id,
        run_id=run.id,
        task_id=task.id,
        trigger_type="user_input",
        status="running",
        lease_epoch=1,
        dedup_key="msg:r",
        metadata_={"note": "they only take fax"},
    )
    db.add(ep)
    await db.commit()
    return run, task, ep


async def test_keep_and_skip(db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM) -> None:
    run, task, ep = await _setup(db, [item(1, status="DONE"), item(2), item(3)])
    fake_llm.on("relevance", _rel(("i2", "keep"), ("i3", "skip")))
    await check(db, await load(db, run), task, ep, 1)
    await db.refresh(task)
    assert [i["status"] for i in task.plan] == ["DONE", "PENDING", "SKIPPED"]
    assert task.plan[2]["reason"] == "because"


async def test_supersede_asks_the_planner_to_append(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    run, task, ep = await _setup(db, [item(1, status="DONE"), item(2, "tool")])
    fake_llm.on("relevance", _rel(("i2", "supersede"), append=True))
    fake_llm.on(
        "planner",
        PlanDraft(
            items=[
                PlanItemDraft(
                    title="Ask how to send by fax",
                    kind="human",
                    tool=None,
                    input_hint="",
                    expected_output="",
                    uses=[],
                    wait_seconds=None,
                )
            ]
        ),
    )
    await check(db, await load(db, run), task, ep, 1)
    await db.refresh(task)
    assert [(i["id"], i["status"]) for i in task.plan] == [
        ("i1", "DONE"),
        ("i2", "SUPERSEDED"),
        ("i3", "PENDING"),
    ]
    assert "they only take fax" in fake_llm.calls[1][1]


async def test_no_pending_items_goes_straight_to_the_planner(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    run, task, ep = await _setup(db, [item(1, status="DONE")])
    fake_llm.on(
        "planner",
        PlanDraft(
            items=[
                PlanItemDraft(
                    title="Follow up",
                    kind="subagent",
                    tool=None,
                    input_hint="",
                    expected_output="",
                    uses=[],
                    wait_seconds=None,
                )
            ]
        ),
    )
    await check(db, await load(db, run), task, ep, 1)
    assert [r for r, _ in fake_llm.calls] == ["planner"]


async def test_unknown_item_ids_are_ignored(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    run, task, ep = await _setup(db, [item(1)])
    fake_llm.on("relevance", _rel(("i7", "skip")))
    await check(db, await load(db, run), task, ep, 1)
    await db.refresh(task)
    assert task.plan[0]["status"] == "PENDING"
