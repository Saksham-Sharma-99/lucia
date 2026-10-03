"""Crash between send and save (HLD sequence B): the next worker never sends twice."""

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AgentRun, AgentRunStep, Episode, RunTask, StepResult
from lucia.harness import executor, worker
from lucia.harness.exec import tool_executor
from lucia.harness.exec.guardrail import GuardrailVerdict
from lucia.harness.exec.reconcile import reconcile_orphans
from lucia.harness.executor import execute_task, resume_task
from lucia.harness.lease import claim
from lucia.llm.fake import FakeLLM
from tests.harness.outbox_fakes import FakeCall
from tests.world import World, item, make_leased_run, make_task, make_world

OK = GuardrailVerdict(ok=True, reasons=[])


@pytest.fixture
def call(monkeypatch: pytest.MonkeyPatch) -> FakeCall:
    fake = FakeCall()
    monkeypatch.setitem(tool_executor.OUTBOX, "vapi.place_call", fake)
    return fake


async def _crashed(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> tuple[World, AgentRun, RunTask, AgentRunStep]:
    """Worker A placed the call, then died before saving the result."""
    w = await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run, plan=[item(1, "tool")], status="IN_PROGRESS")
    fake_llm.on(
        "executor", {"to_contact_id": str(w.jane_link.id), "script": "s", "first_message": "hi"}
    )
    fake_llm.on("guardrail", OK)

    async def die(*_: Any, **__: Any) -> None:
        raise SystemExit("worker killed")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tool_executor, "_settle", die)
        with pytest.raises(SystemExit):
            await execute_task(db, run, task, 1)
    await db.rollback()  # the dead worker's session; reload what the test uses
    for row in (run, task, w.jane_link):
        await db.refresh(row)
    step = await db.scalar(select(AgentRunStep).where(AgentRunStep.kind == "tool"))
    assert step is not None and step.status == "PENDING" and len(call.sent) == 1
    clock.advance(timedelta(minutes=5))
    run.lease_expires_at = clock.now() - timedelta(seconds=1)  # worker A's lease ran out
    await db.commit()
    return w, run, task, step


async def test_found_call_is_adopted_and_never_placed_again(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    _w, run, task, step = await _crashed(db, clock, fake_llm, call)
    call.lookup = "found"
    before = len(fake_llm.calls)
    await worker.advance_run(db, run.id, owner="worker-b")
    assert fake_llm.calls[before:] == [], "the model isn't asked again"
    await db.refresh(step)
    await db.refresh(task)
    assert step.status == "AWAITING_CALLBACK" and step.output["adopted"] is True
    assert len(call.sent) == 1, "the call must not be placed twice"
    assert task.plan[0]["status"] == "WAITING" and task.plan[0]["attempts"] == 1


async def test_confirmed_absent_old_call_is_resent_under_the_same_key(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    w, run, _task, step = await _crashed(db, clock, fake_llm, call)
    call.lookup = "absent"
    fake_llm.on(
        "executor", {"to_contact_id": str(w.jane_link.id), "script": "s", "first_message": "hi"}
    )
    fake_llm.on("guardrail", OK)
    await worker.advance_run(db, run.id, owner="worker-b")
    assert call.sent == [step.idempotency_key, step.idempotency_key]
    await db.refresh(step)
    assert step.status == "AWAITING_CALLBACK"


async def test_absent_but_recent_waits_for_a_reconcile_episode(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    _w, run, _task, step = await _crashed(db, clock, fake_llm, call)
    clock.advance(timedelta(minutes=-4))  # only 60s after the send
    run.lease_expires_at = clock.now() - timedelta(seconds=1)
    await db.commit()
    epoch = await claim(db, run.id, "worker-b")
    assert epoch is not None
    await reconcile_orphans(db, run, epoch)
    await db.refresh(step)
    assert step.status == "PENDING"
    wake = await db.scalar(select(Episode).where(Episode.source == "reconcile"))
    assert wake is not None and wake.dedup_key == f"reconcile:{step.id}"


async def test_unknown_asks_a_person_and_not_sent_resends(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    w, run, task, step = await _crashed(db, clock, fake_llm, call)
    call.lookup = "unknown"
    epoch = await claim(db, run.id, "worker-b")
    assert epoch is not None
    await reconcile_orphans(db, run, epoch)
    await db.refresh(step)
    assert step.status == "FAILED" and step.error is not None and step.error["class"] == "uncertain"
    question = await db.scalar(select(StepResult).where(StepResult.kind == "uncertain_send"))
    assert question is not None and {o["value"] for o in question.options} == {"sent", "not_sent"}
    ep = Episode(
        firm_id=run.firm_id,
        run_id=run.id,
        task_id=task.id,
        trigger_type="user_response",
        status="running",
        lease_epoch=epoch,
        dedup_key="answer:u",
        metadata_={"step_result_id": str(question.id), "answer": {"choice": "not_sent"}},
    )
    db.add(ep)
    await db.commit()
    fake_llm.on(
        "executor", {"to_contact_id": str(w.jane_link.id), "script": "s", "first_message": "hi"}
    )
    fake_llm.on("guardrail", OK)
    await resume_task(db, run, task, ep, epoch)
    assert call.sent == [step.idempotency_key, step.idempotency_key]


async def test_answer_sent_adopts_the_step(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    _w, run, task, step = await _crashed(db, clock, fake_llm, call)
    call.lookup = "unknown"
    epoch = await claim(db, run.id, "worker-b")
    assert epoch is not None
    await reconcile_orphans(db, run, epoch)
    question = await db.scalar(select(StepResult).where(StepResult.kind == "uncertain_send"))
    assert question is not None
    ep = Episode(
        firm_id=run.firm_id,
        run_id=run.id,
        task_id=task.id,
        trigger_type="user_response",
        status="running",
        lease_epoch=epoch,
        dedup_key="answer:s",
        metadata_={"step_result_id": str(question.id), "answer": {"choice": "sent"}},
    )
    db.add(ep)
    await db.commit()
    await resume_task(db, run, task, ep, epoch)
    await db.refresh(step)
    await db.refresh(task)
    assert step.status == "AWAITING_CALLBACK" and len(call.sent) == 1
    assert task.plan[0]["status"] == "WAITING"


async def test_unknown_send_is_never_retried_by_the_worker(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    """Through advance_run: reconcile asks a person, and the item must not run again."""
    _, run, task, _step = await _crashed(db, clock, fake_llm, call)
    call.lookup = "unknown"
    await worker.advance_run(db, run.id, owner="worker-b")
    await worker.advance_run(db, run.id, owner="worker-b")
    assert len(call.sent) == 1
    await db.refresh(task)
    assert task.status == "BLOCKED" and task.plan[0]["status"] == "WAITING"


async def test_recent_absent_send_waits_for_the_recheck_not_the_worker(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    w, run, task, step = await _crashed(db, clock, fake_llm, call)
    clock.advance(timedelta(minutes=-4))  # 60s after the send
    run.lease_expires_at = clock.now() - timedelta(seconds=1)
    await db.commit()
    await worker.advance_run(db, run.id, owner="worker-b")
    assert len(call.sent) == 1
    await db.refresh(task)
    assert task.plan[0]["status"] == "WAITING"
    # the recheck fires 2 minutes after the send: now it's confirmed absent → resend, same key
    clock.advance(timedelta(minutes=2))
    wake = await db.scalar(select(Episode).where(Episode.source == "reconcile"))
    assert wake is not None
    wake.status = "pending"
    run.lease_expires_at = None
    await db.commit()
    fake_llm.on(
        "executor", {"to_contact_id": str(w.jane_link.id), "script": "s", "first_message": "hi"}
    )
    fake_llm.on("guardrail", OK)
    await worker.advance_run(db, run.id, owner="worker-c")
    assert call.sent == [step.idempotency_key, step.idempotency_key]


async def test_a_crash_after_a_guardrail_block_leaves_nothing_half_saved(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run, plan=[item(1, "tool")], status="IN_PROGRESS")
    draft = {"to_contact_id": str(w.jane_link.id), "script": "s", "first_message": "hi"}
    fake_llm.on("executor", draft)
    fake_llm.on("guardrail", GuardrailVerdict(ok=False, reasons=["medical advice"]))

    async def die(*_: Any, **__: Any) -> None:
        raise SystemExit("worker killed before saving the item")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(executor, "_apply", die)
        with pytest.raises(SystemExit):
            await execute_task(db, run, task, 1)
    await db.rollback()
    assert await db.scalar(select(StepResult.id)) is None, "the block commits with the item"
    assert await db.scalar(select(AgentRunStep.id).where(AgentRunStep.kind == "guardrail")) is None
