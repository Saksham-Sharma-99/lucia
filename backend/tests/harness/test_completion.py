from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import (
    AgentRun,
    AgentRunStep,
    Conversation,
    Episode,
    Message,
    RunTask,
    StepResult,
)
from lucia.harness import worker
from lucia.harness.completion import CompletionVerdict, JudgeVerdict, NextTask, check_run, confirm
from lucia.harness.keys import TargetRef
from lucia.harness.steps import add_step
from lucia.llm.fake import FakeLLM
from tests.world import VOICE_CONFIG, World, make_leased_run, make_task, make_world


async def _done(db: AsyncSession, recurring: bool = False) -> tuple[World, AgentRun, AgentRunStep]:
    config = {**VOICE_CONFIG, "recurrence": {"every_days": 14}} if recurring else VOICE_CONFIG
    w = await make_world(db, config=config)
    run = await make_leased_run(
        db, w, goal="Check in with Jane", completion_criteria="A completed call"
    )
    step = await add_step(
        db,
        run,
        kind="tool",
        tool="vapi.place_call",
        status="SUCCEEDED",
        idempotency_key="k1",
        epoch=1,
    )
    await make_task(
        db,
        w,
        run,
        status="DONE",
        output={"summary": "Reached Jane", "evidence_step_ids": [str(step.id)]},
    )
    return w, run, step


def _met(*ids: str, met: bool = True, nxt: list[NextTask] | None = None) -> CompletionVerdict:
    return CompletionVerdict(
        met=met, reason="Jane was reached", evidence_step_ids=list(ids), next=nxt or []
    )


async def test_met_with_evidence_and_judge_waits_for_confirmation(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, run, step = await _done(db)
    fake_llm.on("completion", _met(str(step.id)))
    fake_llm.on("completion_judge", JudgeVerdict(agree=True, reason="yes"))
    assert await check_run(db, run, 1, "t") == "awaiting_confirmation"
    await db.refresh(run)
    item = await db.scalar(select(StepResult))
    assert run.status == "AWAITING_CONFIRMATION"
    assert item is not None and (item.kind, item.blocking) == ("confirm_completion", True)


async def test_a_message_that_arrived_during_the_check_wins_over_done(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w, run, step = await _done(db)
    db.add(
        Episode(
            firm_id=w.firm.id,
            run_id=run.id,
            trigger_type="user_input",
            status="pending",
            dedup_key="msg:forms",  # "also send her the forms", sent while the model judged
        )
    )
    await db.commit()
    fake_llm.on("completion", _met(str(step.id)))
    fake_llm.on("completion_judge", JudgeVerdict(agree=True, reason="yes"))
    assert await check_run(db, run, 1, "k") == "superseded"
    await db.refresh(run)
    assert run.status == "ACTIVE" and await db.scalar(select(StepResult.id)) is None


async def test_the_same_next_task_twice_is_created_once(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, run, _ = await _done(db)
    nxt = NextTask(
        kind="send_summary", target=TargetRef(type="run", ref=None), title="S", goal="Write it up"
    )
    fake_llm.on("completion", _met(met=False, nxt=[nxt, nxt]))
    assert await check_run(db, run, 1, "k") == "continued"
    keys = list(await db.scalars(select(RunTask.key).where(RunTask.key == "send-summary:run")))
    assert keys == ["send-summary:run"]


async def test_the_confirmation_is_posted_to_the_chat_once(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w, run, step = await _done(db)
    conv = Conversation(firm_id=w.firm.id, channel="playground", subject_id=w.subject.id)
    db.add(conv)
    await db.flush()
    db.add(
        Episode(
            firm_id=w.firm.id,
            run_id=run.id,
            trigger_type="user_input",
            status="completed",
            dedup_key="msg:c",
            metadata_={"conversation_id": str(conv.id)},
        )
    )
    await db.commit()
    fake_llm.on("completion", _met(str(step.id)))
    fake_llm.on("completion_judge", JudgeVerdict(agree=True, reason="yes"))
    await check_run(db, run, 1, "t")
    (posted,) = await db.scalars(select(Message).where(Message.conversation_id == conv.id))
    assert posted.blocks[0]["type"] == "run_confirm" and "Jane was reached" in posted.body


async def test_citing_another_runs_step_is_retried_then_asked(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _w, run, _ = await _done(db)
    other = await make_world(db, slug="other-firm", handle="other")
    foreign = await add_step(
        db,
        await make_leased_run(db, other),
        kind="tool",
        tool="x",
        status="SUCCEEDED",
        idempotency_key="k9",
        epoch=1,
    )
    fake_llm.on("completion", _met(str(foreign.id)), _met("not-a-uuid"))
    assert await check_run(db, run, 1, "t") == "asked"
    assert "evidence" in fake_llm.calls[1][1]
    assert await db.scalar(select(StepResult.kind)) == "question"


async def test_rechecking_the_same_cause_asks_once(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, run, step = await _done(db)
    no = JudgeVerdict(agree=False, reason="call was voicemail")
    fake_llm.on("completion", _met(str(step.id)), _met(str(step.id)))
    fake_llm.on("completion_judge", no, no)
    clock.advance(timedelta(seconds=1))
    await check_run(db, run, 1, "task:x")
    clock.advance(timedelta(seconds=1))
    await check_run(db, run, 1, "task:x")  # e.g. the unit replayed after a crash
    assert len(list(await db.scalars(select(StepResult)))) == 1


async def test_judge_disagreement_asks_a_person(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, run, step = await _done(db)
    fake_llm.on("completion", _met(str(step.id)))
    fake_llm.on("completion_judge", JudgeVerdict(agree=False, reason="call was voicemail"))
    assert await check_run(db, run, 1, "t") == "asked"
    item = await db.scalar(select(StepResult))
    assert item is not None and "call was voicemail" in item.summary


async def test_not_met_with_next_tasks_continues(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, run, _ = await _done(db)
    nxt = NextTask(
        kind="send_summary",
        target=TargetRef(type="run", ref=None),
        title="Summarize",
        goal="Write it up",
    )
    fake_llm.on("completion", _met(met=False, nxt=[nxt]))
    assert await check_run(db, run, 1, "t") == "continued"
    keys = set(await db.scalars(select(RunTask.key)))
    assert "send-summary:run" in keys


async def test_a_next_step_that_is_an_existing_task_reopens_it(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    """e.g. "not met: check in with Jane again": that task exists, so it's reopened with the
    goal as a note, never dropped (the run would sit idle, every task done)."""
    _, run, _ = await _done(db)
    again = NextTask(
        kind="checkin",
        target=TargetRef(type="run", ref=None),
        title="Check in again",
        goal="Ask about her next appointment",
    )
    fake_llm.on("completion", _met(met=False, nxt=[again]))
    assert await check_run(db, run, 1, "k") == "continued"
    (task,) = await db.scalars(select(RunTask))
    note = await db.scalar(select(Episode).where(Episode.task_id == task.id))
    assert task.status == "IN_PROGRESS" and note is not None
    assert (note.trigger_type, note.metadata_["note"]) == ("user_input", again.goal)


async def test_not_met_and_nothing_next_asks(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, run, _ = await _done(db)
    fake_llm.on("completion", _met(met=False))
    assert await check_run(db, run, 1, "t") == "asked"


async def test_recurring_cycle_closes_silently_and_schedules_the_next(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, run, _ = await _done(db, recurring=True)
    fake_llm.on("completion", _met(met=False))
    assert await check_run(db, run, 1, "t") == "cycle_closed"
    wake = await db.scalar(select(Episode).where(Episode.source == "recurrence"))
    assert wake is not None and wake.metadata_["cycle"] == 2
    assert await db.scalar(select(StepResult)) is None


async def test_confirm_completes_and_reopen_resumes(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, run, step = await _done(db)
    fake_llm.on("completion", _met(str(step.id)))
    fake_llm.on("completion_judge", JudgeVerdict(agree=True, reason="yes"))
    await check_run(db, run, 1, "t")
    item = await db.scalar(select(StepResult))
    assert item is not None
    await confirm(db, run, item, choice="reopen", text="Also ask about her PT")
    await db.refresh(run)
    assert run.status == "ACTIVE"
    reopened = await db.scalar(select(Episode).where(Episode.trigger_type == "user_input"))
    assert reopened is not None and reopened.metadata_["instruction"] == "Also ask about her PT"
    run.status = "AWAITING_CONFIRMATION"
    await db.commit()
    await confirm(db, run, item, choice="confirm", text=None)
    await db.refresh(run)
    assert (run.status, run.ended_reason) == ("COMPLETED", "confirmed")


async def test_worker_checks_completion_once_all_tasks_are_done(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, monkeypatch: Any
) -> None:
    _, run, _step = await _done(db)
    calls: list[str] = []

    async def fake_check(session: AsyncSession, r: AgentRun, epoch: int, cause: str) -> str:
        calls.append("check")
        return "asked"

    monkeypatch.setattr(worker, "check_run", fake_check)
    task = await db.scalar(select(RunTask))
    assert task is not None
    task.status = "IN_PROGRESS"
    await db.commit()

    async def execute(session: AsyncSession, r: AgentRun, t: RunTask, epoch: int) -> None:
        t.status = "DONE"
        await session.commit()

    monkeypatch.setattr(worker, "execute_task", execute)
    run.lease_expires_at = None
    await db.commit()
    assert await worker.advance_run(db, run.id, owner="t") == "executed"
    assert calls == [], "queued as its own unit, so a crash in it is redone"
    assert await worker.advance_run(db, run.id, owner="t") == "asked"
    assert calls == ["check"]


async def test_the_completion_prompt_shows_citable_step_ids(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, run, step = await _done(db)
    fake_llm.on("completion", _met(met=False))
    await check_run(db, run, 1, "t")
    assert str(step.id) in fake_llm.calls[0][1]
