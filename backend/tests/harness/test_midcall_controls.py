"""A takeover, kill switch or end that commits while a unit waits on the model wins: the unit
raises LeaseLost before it writes anything (RUNTIME_SPEC §13). One test per unit type."""

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AgentRun, Episode, Message, StepResult
from lucia.harness import worker
from lucia.harness.completion import CompletionVerdict, check_run
from lucia.harness.exec import tool_executor
from lucia.harness.executor import execute_task, resume_task
from lucia.harness.lease import LeaseLost
from lucia.harness.planner import PlanDraft, PlanItemDraft
from lucia.harness.relevance import ItemVerdict, Relevance
from lucia.harness.subagent import Review, SubBrief
from lucia.harness.triage import TriageResult, run_triage
from lucia.llm.client import LLMError
from lucia.llm.fake import FakeLLM
from tests.harness.midcall import CONTROLS, land_during
from tests.harness.outbox_fakes import FakeCall
from tests.world import World, item, make_leased_run, make_run, make_task, make_world

pytestmark = pytest.mark.parametrize("control", CONTROLS)


async def _nothing_written(db: AsyncSession, run: AgentRun, control: dict[str, Any]) -> None:
    await db.rollback()
    await db.refresh(run)
    assert run.status == control["status"]
    assert await db.scalar(select(func.count(StepResult.id))) == 0
    assert await db.scalar(select(func.count(Message.id)).where(Message.actor == "agent")) == 0


async def _world(db: AsyncSession) -> tuple[World, AgentRun]:
    w = await make_world(db)
    return w, await make_leased_run(db, w)


async def test_triage(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, monkeypatch: Any, control: Any
) -> None:
    w, run = await _world(db)
    ep = Episode(
        firm_id=w.firm.id,
        run_id=run.id,
        trigger_type="user_input",
        status="running",
        lease_epoch=1,
        dedup_key="msg:1",
    )
    db.add(ep)
    await db.commit()
    fake_llm.on(
        "triage",
        TriageResult(ops=[], out_of_scope=[], goal="g", criteria="c", reply="I'll call Jane now."),
    )
    land_during(monkeypatch, fake_llm, db, run.id, "triage", control)
    with pytest.raises(LeaseLost):
        await run_triage(db, run, ep, 1)
    await _nothing_written(db, run, control)


async def test_planner(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, monkeypatch: Any, control: Any
) -> None:
    w, run = await _world(db)
    task = await make_task(db, w, run)
    plan = PlanItemDraft(
        title="Call Jane",
        kind="tool",
        tool="vapi.place_call",
        input_hint="",
        expected_output="",
        uses=[],
        wait_seconds=None,
    )
    fake_llm.on("planner", PlanDraft(items=[plan]))
    land_during(monkeypatch, fake_llm, db, run.id, "planner", control)
    with pytest.raises(LeaseLost):
        await execute_task(db, run, task, 1)
    await _nothing_written(db, run, control)
    await db.refresh(task)
    assert task.plan == []


async def test_executor_never_sends(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, monkeypatch: Any, control: Any
) -> None:
    w, run = await _world(db)
    call = FakeCall()
    monkeypatch.setitem(tool_executor.OUTBOX, "vapi.place_call", call)
    task = await make_task(db, w, run, plan=[item(1, "tool")])
    draft = {"to_contact_id": str(w.jane_link.id), "script": "s", "first_message": "hi"}
    fake_llm.on("executor", draft)
    land_during(monkeypatch, fake_llm, db, run.id, "executor", control)
    with pytest.raises(LeaseLost):
        await execute_task(db, run, task, 1)
    assert call.sent == []
    await _nothing_written(db, run, control)


async def test_subagent(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, monkeypatch: Any, control: Any
) -> None:
    w, run = await _world(db)
    task = await make_task(db, w, run, plan=[item(1, "subagent", title="Draft the script")])
    brief = SubBrief(
        in_scope=True,
        scope_reason="fits",
        what="Write a call script",
        why="To check in",
        inputs_used=[],
        output_format="plain text",
        quality_bar="Warm",
    )
    low = Review(score=0.2, issues=["too long"], improve_instructions="Shorter")
    fake_llm.on("sub_planner", brief)
    fake_llm.on("sub_executor", "v1")
    fake_llm.on("sub_reviewer", low)  # would replan, then ask a person
    land_during(monkeypatch, fake_llm, db, run.id, "sub_reviewer", control)
    with pytest.raises(LeaseLost):
        await execute_task(db, run, task, 1)
    assert [r for r, _ in fake_llm.calls] == ["sub_planner", "sub_executor", "sub_reviewer"]
    await _nothing_written(db, run, control)


async def test_relevance(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, monkeypatch: Any, control: Any
) -> None:
    w, run = await _world(db)
    task = await make_task(db, w, run, plan=[item(1, "tool")], status="IN_PROGRESS")
    ep = Episode(
        firm_id=w.firm.id,
        run_id=run.id,
        task_id=task.id,
        trigger_type="user_input",
        status="running",
        lease_epoch=1,
        dedup_key="note:1",
        metadata_={"note": "Don't call, she asked for email"},
    )
    db.add(ep)
    await db.commit()
    skip = ItemVerdict(item_id="i1", verdict="skip", reason="email instead")
    fake_llm.on("relevance", Relevance(verdicts=[skip], append_needed=False, append_reason=""))
    land_during(monkeypatch, fake_llm, db, run.id, "relevance", control)
    with pytest.raises(LeaseLost):
        await resume_task(db, run, task, ep, 1)
    await _nothing_written(db, run, control)
    await db.refresh(task)
    assert task.plan[0]["status"] == "PENDING"


async def test_completion_check(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, monkeypatch: Any, control: Any
) -> None:
    w, run = await _world(db)
    await make_task(db, w, run, status="DONE")
    fake_llm.on(
        "completion",
        CompletionVerdict(met=False, reason="not yet", evidence_step_ids=[], next=[]),
    )
    land_during(monkeypatch, fake_llm, db, run.id, "completion", control)
    with pytest.raises(LeaseLost):
        await check_run(db, run, 1, "k")
    await _nothing_written(db, run, control)


async def test_a_failing_unit_leaves_the_control_alone(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, monkeypatch: Any, control: Any
) -> None:
    """The model fails after the control landed: the retry and escalation path must not write
    (e.g. a third failure would pause a taken-over run, or revive an ended one)."""
    w = await make_world(db)
    run = await make_run(db, w)
    db.add(
        Episode(
            firm_id=w.firm.id,
            run_id=run.id,
            trigger_type="user_input",
            status="pending",
            dedup_key="msg:1",
            metadata_={"retry_count": 2},  # this is its last try
        )
    )
    await db.commit()
    fake_llm.on("triage", LLMError("timeout", retryable=True))
    land_during(monkeypatch, fake_llm, db, run.id, "triage", control)
    assert await worker.advance_run(db, run.id, owner="t") == "lease_lost"
    await _nothing_written(db, run, control)
    assert await db.scalar(select(Episode.status)) == "running", "resumed after a hand-back"


async def test_a_failing_task_run_leaves_the_control_alone(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, monkeypatch: Any, control: Any
) -> None:
    """The task path's failure builds a retry Episode: not once the run is no longer ours."""
    w = await make_world(db)
    run = await make_run(db, w)
    await make_task(db, w, run, plan=[item(1, "tool")])
    fake_llm.on("executor", LLMError("timeout", retryable=True))
    land_during(monkeypatch, fake_llm, db, run.id, "executor", control)
    assert await worker.advance_run(db, run.id, owner="t") == "lease_lost"
    await _nothing_written(db, run, control)
    assert await db.scalar(select(func.count(Episode.id))) == 0, "no retry Episode"
