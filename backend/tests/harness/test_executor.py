import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AgentRun, AgentRunStep, Episode, JournalEntry, RunTask, StepResult
from lucia.harness.exec import tool_executor
from lucia.harness.executor import execute_task, resume_task
from lucia.harness.planner import PlanDraft, PlanItemDraft
from lucia.harness.tools.base import ToolContext, ToolResult
from lucia.harness.tools.registry import IMPLS
from lucia.llm.fake import FakeLLM
from tests.world import World, item, make_leased_run, make_task, make_world


class FakeTool:
    def __init__(self, *results: ToolResult) -> None:
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        self.calls.append(args)
        return self.results.pop(0)


@pytest.fixture
def tool(monkeypatch: pytest.MonkeyPatch) -> FakeTool:
    """Executor tests drive tool results directly, so the fake replaces the outboxed Vapi tool."""
    fake = FakeTool()
    monkeypatch.delitem(tool_executor.OUTBOX, "vapi.place_call")
    monkeypatch.setitem(IMPLS, "vapi.place_call", fake)
    return fake


async def _setup(
    db: AsyncSession, plan: list[dict[str, Any]], **task: Any
) -> tuple[World, AgentRun, RunTask]:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    return w, run, await make_task(db, w, run, plan=plan, **task)


async def _episode(db: AsyncSession, w: World, run: AgentRun, task: RunTask, **kw: Any) -> Episode:
    fields: dict[str, Any] = {
        "trigger_type": "user_input",
        "status": "running",
        "lease_epoch": 1,
        **kw,
    }
    ep = Episode(
        firm_id=w.firm.id,
        run_id=run.id,
        task_id=task.id,
        dedup_key=f"x:{len(str(kw))}:{id(kw)}",
        **fields,
    )
    db.add(ep)
    await db.commit()
    return ep


def _ok(summary: str = "Called Jane", **out: Any) -> ToolResult:
    return ToolResult(status="SUCCEEDED", summary=summary, output={"reached": True, **out})


async def test_plans_then_runs_items_to_done(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    w, run, task = await _setup(db, [])
    fake_llm.on(
        "planner",
        PlanDraft(
            items=[
                PlanItemDraft(
                    title="Call Jane",
                    kind="tool",
                    tool="vapi.place_call",
                    input_hint="",
                    expected_output="",
                    uses=[],
                    wait_seconds=None,
                    wait_until=None,
                )
            ]
        ),
    )
    fake_llm.on(
        "executor", {"to_contact_id": str(w.jane_link.id), "script": "s", "first_message": "hi"}
    )
    tool.results.append(_ok())
    assert await execute_task(db, run, task, 1) == "done"
    await db.refresh(task)
    assert task.status == "DONE" and task.plan[0]["status"] == "DONE"
    assert task.output is not None and task.output["summary"] == "Called Jane"
    assert tool.calls == [
        {"to_contact_id": str(w.jane_link.id), "script": "s", "first_message": "hi"}
    ]
    assert await db.scalar(select(JournalEntry.text)) == "Call Jane: Called Jane"


async def test_a_markdown_summary_starts_its_own_journal_paragraph(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    w, run, task = await _setup(db, [])
    fake_llm.on(
        "planner",
        PlanDraft(
            items=[
                PlanItemDraft(
                    title="Call Jane",
                    kind="tool",
                    tool="vapi.place_call",
                    input_hint="",
                    expected_output="",
                    uses=[],
                    wait_seconds=None,
                    wait_until=None,
                )
            ]
        ),
    )
    fake_llm.on(
        "executor", {"to_contact_id": str(w.jane_link.id), "script": "s", "first_message": "hi"}
    )
    tool.results.append(_ok("## Reached\n- **Mood:** good"))
    assert await execute_task(db, run, task, 1) == "done"
    assert await db.scalar(select(JournalEntry.text)) == (
        "Call Jane:\n\n## Reached\n- **Mood:** good"
    )


async def test_async_tool_waits_then_the_callback_finishes_it(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    w, run, task = await _setup(db, [item(1, "tool")])
    fake_llm.on("executor", {"to_contact_id": "x", "script": "s", "first_message": "hi"})
    tool.results.append(ToolResult(status="AWAITING_CALLBACK", summary="Call placed"))
    assert await execute_task(db, run, task, 1) == "waiting"
    await db.refresh(task)
    assert (task.status, task.plan[0]["status"]) == ("WAITING", "WAITING")
    ep = await _episode(
        db,
        w,
        run,
        task,
        trigger_type="external_response",
        metadata_={"plan_item_id": "i1", "summary": "Jane is doing well", "reached": True},
    )
    await resume_task(db, run, task, ep, 1)
    await db.refresh(task)
    assert task.status == "DONE" and task.plan[0]["output"]["summary"] == "Jane is doing well"


async def test_deferred_send_is_rescheduled_and_refilled_on_wake(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    _, run, task = await _setup(db, [item(1, "tool")])
    later = clock.now() + timedelta(hours=10)
    fake_llm.on(
        "executor",
        {"to_contact_id": "x", "script": "v1", "first_message": "hi"},
        {"to_contact_id": "x", "script": "v2", "first_message": "hi"},
    )
    tool.results.extend(
        [ToolResult(status="DEFERRED", resume_at=later, reason="quiet_hours"), _ok()]
    )
    assert await execute_task(db, run, task, 1) == "waiting"
    wake = await db.scalar(select(Episode).where(Episode.source == "deferral"))
    assert wake is not None and wake.due_at == later and wake.task_id == task.id
    wake.status = "running"
    wake.lease_epoch = 1
    await db.commit()
    await resume_task(db, run, task, wake, 1)
    assert [c["script"] for c in tool.calls] == ["v1", "v2"]
    await db.refresh(task)
    assert task.status == "DONE"


@pytest.mark.parametrize("source", ["deferral", "retry", "plan_wait", "reconcile"])
async def test_a_wake_for_an_item_that_moved_on_does_nothing(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool, source: str
) -> None:
    """e.g. quiet hours deferred the call, then the client said "email instead": the call
    item was superseded, and tomorrow's deferral wake must not place it."""
    w, run, task = await _setup(
        db,
        [item(1, "tool", status="SUPERSEDED"), item(2, "tool", status="WAITING")],
        status="WAITING",
    )
    meta = {"plan_item_id": "i1", "step_id": str(uuid.uuid4())}
    ep = await _episode(db, w, run, task, trigger_type="scheduled", source=source, metadata_=meta)
    await resume_task(db, run, task, ep, 1)
    await db.refresh(task)
    assert tool.calls == [] and task.plan[0]["status"] == "SUPERSEDED"


async def test_an_item_that_keeps_killing_the_worker_is_given_to_a_person(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    """e.g. it runs the worker out of memory: nothing to catch, so resumes are counted."""
    _, run, task = await _setup(db, [item(1, "tool", status="RUNNING", attempts=1, resumes=3)])
    assert await execute_task(db, run, task, 1) == "blocked"
    await db.refresh(task)
    assert tool.calls == [] and task.plan[0]["status"] == "FAILED"
    assert await db.scalar(select(StepResult.kind)) == "item_failed"


async def test_a_resumed_item_counts_the_resume_before_it_runs(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    _, run, task = await _setup(db, [item(1, "tool", status="RUNNING", attempts=1)])
    fake_llm.on("executor", {"to_contact_id": "x", "script": "s", "first_message": "hi"})

    async def die(*_: Any) -> Any:
        raise SystemExit("killed mid-item")

    tool.results.append(_ok())
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tool_executor, "run", die)
        with pytest.raises(SystemExit):
            await execute_task(db, run, task, 1)
    await db.rollback()
    await db.refresh(task)
    assert task.plan[0]["resumes"] == 1, "committed before the crash, so the count survives"


async def test_try_again_on_a_failed_task_carries_on_with_its_plan(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    w, run, task = await _setup(
        db,
        [item(1, "tool", status="DONE"), item(2, "wait", wait={"seconds": 60})],
        status="BLOCKED",
    )
    asked = StepResult(
        firm_id=w.firm.id,
        run_id=run.id,
        task_id=task.id,
        type="attention",
        kind="item_failed",
        urgency="P1",
        summary="kept failing",
        summary_public="x",
        status="answered",
        dedup_key="sr:t",
        data={"item_id": None},
    )
    db.add(asked)
    await db.commit()
    meta = {"step_result_id": str(asked.id), "answer": {"choice": "retry"}}
    ep = await _episode(db, w, run, task, trigger_type="user_response", metadata_=meta)
    await resume_task(db, run, task, ep, 1)
    await db.refresh(task)
    assert [i["status"] for i in task.plan] == ["DONE", "WAITING"], "the plan is kept"


async def test_skip_on_a_failed_task_skips_its_open_items(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    w, run, task = await _setup(
        db, [item(1, "tool", status="DONE"), item(2, "tool", status="RUNNING")], status="BLOCKED"
    )
    asked = StepResult(
        firm_id=w.firm.id,
        run_id=run.id,
        task_id=task.id,
        type="attention",
        kind="item_failed",
        urgency="P1",
        summary="kept failing",
        summary_public="x",
        status="answered",
        dedup_key="sr:skip",
        data={"item_id": None},
    )
    db.add(asked)
    await db.commit()
    meta = {"step_result_id": str(asked.id), "answer": {"choice": "skip"}}
    ep = await _episode(db, w, run, task, trigger_type="user_response", metadata_=meta)
    await resume_task(db, run, task, ep, 1)
    await db.refresh(task)
    assert task.status == "SKIPPED" and [i["status"] for i in task.plan] == ["DONE", "SKIPPED"]


@pytest.mark.parametrize(
    ("waiting", "status"),
    [
        (item(1, "tool", status="WAITING"), "WAITING"),
        (item(1, "human", status="WAITING"), "BLOCKED"),
    ],
)
async def test_running_a_task_with_an_item_still_waiting_does_not_finish_it(
    db: AsyncSession, clock: FrozenClock, waiting: dict[str, Any], status: str
) -> None:
    """e.g. a person's note while the call is live, or while their question is open."""
    _, run, task = await _setup(db, [waiting], status=status)
    assert await execute_task(db, run, task, 1) == status.lower()
    await db.refresh(task)
    assert task.status == status and task.plan[0]["status"] == "WAITING"


async def test_a_task_finishes_only_once_its_waiting_items_settle(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    _, run, task = await _setup(
        db, [item(1, "tool", status="WAITING"), item(2, "tool")], status="WAITING"
    )
    fake_llm.on("executor", {"to_contact_id": "x", "script": "s", "first_message": "hi"})
    tool.results.append(_ok())
    assert await execute_task(db, run, task, 1) == "waiting"
    await db.refresh(task)
    assert task.status == "WAITING" and task.plan[1]["status"] == "DONE"


async def test_a_send_deferred_twice_gets_a_second_wake(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    _, run, task = await _setup(db, [item(1, "tool")])
    first, second = clock.now() + timedelta(hours=10), clock.now() + timedelta(hours=34)
    args = {"to_contact_id": "x", "script": "s", "first_message": "hi"}
    fake_llm.on("executor", args, args)
    tool.results.extend(
        [
            ToolResult(status="DEFERRED", resume_at=first, reason="quiet_hours"),
            ToolResult(status="DEFERRED", resume_at=second, reason="org_daily_cap"),
        ]
    )
    await execute_task(db, run, task, 1)
    wake = await db.scalar(select(Episode).where(Episode.source == "deferral"))
    assert wake is not None
    wake.status, wake.lease_epoch = "running", 1
    await db.commit()
    await resume_task(db, run, task, wake, 1)
    wakes = await db.scalars(
        select(Episode.due_at).where(Episode.source == "deferral").order_by(Episode.due_at)
    )
    assert list(wakes) == [first, second]


async def test_policy_block_skips_the_item_and_asks_for_an_alternative(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    _, run, task = await _setup(db, [item(1, "tool")])
    fake_llm.on("executor", {"to_contact_id": "x", "script": "s", "first_message": "hi"})
    tool.results.append(ToolResult(status="BLOCKED_BY_POLICY", reason="consent_required"))
    fake_llm.on(
        "planner",
        PlanDraft(
            items=[
                PlanItemDraft(
                    title="Ask for consent",
                    kind="human",
                    tool=None,
                    input_hint="Get voice consent",
                    expected_output="",
                    uses=[],
                    wait_seconds=None,
                    wait_until=None,
                )
            ]
        ),
    )
    assert await execute_task(db, run, task, 1) == "blocked"
    await db.refresh(task)
    assert [(i["id"], i["status"]) for i in task.plan] == [("i1", "SKIPPED"), ("i2", "WAITING")]
    kinds = set(await db.scalars(select(StepResult.kind)))
    assert kinds == {"escalation", "question"}


async def test_retryable_failures_back_off_then_block(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    _, run, task = await _setup(db, [item(1, "tool")])
    for _ in range(3):
        fake_llm.on("executor", {"to_contact_id": "x", "script": "s", "first_message": "hi"})
        tool.results.append(ToolResult(status="FAILED", retryable=True, reason="vapi_500"))
    assert await execute_task(db, run, task, 1) == "waiting"
    retries = list(
        await db.scalars(select(Episode).where(Episode.source == "retry").order_by(Episode.due_at))
    )
    assert [(r.due_at - clock.now()).total_seconds() for r in retries if r.due_at] == [60]
    for _ in range(2):
        wake = retries[-1]
        wake.status, wake.lease_epoch = "running", 1
        await db.commit()
        await resume_task(db, run, task, wake, 1)
        wake.status = "completed"  # the worker closes the Episode after the unit
        await db.commit()
        retries = list(
            await db.scalars(
                select(Episode).where(Episode.source == "retry").order_by(Episode.created_at)
            )
        )
    assert len(retries) == 2
    await db.refresh(task)
    assert task.status == "BLOCKED" and task.plan[0]["status"] == "FAILED"
    assert await db.scalar(select(StepResult.kind)) == "item_failed"


async def test_a_retried_item_that_fails_again_asks_again(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    w, run, task = await _setup(db, [item(1, "tool")])
    for _ in range(2):
        fake_llm.on("executor", {"to_contact_id": "x", "script": "s", "first_message": "hi"})
        tool.results.append(ToolResult(status="FAILED", reason="bad_number"))
    assert await execute_task(db, run, task, 1) == "blocked"
    asked = await db.scalar(select(StepResult).where(StepResult.kind == "item_failed"))
    assert asked is not None
    meta = {"step_result_id": str(asked.id), "answer": {"choice": "retry"}}
    ep = await _episode(db, w, run, task, trigger_type="user_response", metadata_=meta)
    await resume_task(db, run, task, ep, 1)
    await db.refresh(task)
    asks = list(await db.scalars(select(StepResult).where(StepResult.kind == "item_failed")))
    assert len(asks) == 2 and task.status == "BLOCKED"
    assert task.plan[0]["attempts"] == 2, "attempts never reset: they key the outbox"
    assert task.plan[0]["resumes"] == 0


async def test_human_item_asks_and_the_answer_completes_it(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w, run, task = await _setup(db, [item(1, "human", input_hint="Which number should I call?")])
    assert await execute_task(db, run, task, 1) == "blocked"
    question = await db.scalar(select(StepResult))
    assert question is not None and (question.kind, question.summary) == (
        "question",
        "Which number should I call?",
    )
    ep = await _episode(
        db,
        w,
        run,
        task,
        trigger_type="user_response",
        metadata_={"step_result_id": str(question.id), "answer": {"text": "Her mobile"}},
    )
    await resume_task(db, run, task, ep, 1)
    await db.refresh(task)
    assert task.status == "DONE" and task.plan[0]["output"]["summary"] == "Her mobile"
    # the answer is a human step on the item: evidence the completion check can cite
    step = await db.scalar(select(AgentRunStep).where(AgentRunStep.kind == "human"))
    assert step is not None and (step.status, step.actor, step.summary) == (
        "SUCCEEDED",
        "human",
        "Her mobile",
    )
    assert task.plan[0]["step_ids"] == [str(step.id)]


async def test_an_answer_for_a_superseded_item_changes_nothing(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w, run, task = await _setup(db, [item(1, "human")])
    await execute_task(db, run, task, 1)
    question = await db.scalar(select(StepResult))
    assert question is not None
    task.plan = [{**task.plan[0], "status": "SUPERSEDED"}]  # relevance replaced it meanwhile
    await db.commit()
    meta = {"step_result_id": str(question.id), "answer": {"text": "Her mobile"}}
    ep = await _episode(db, w, run, task, trigger_type="user_response", metadata_=meta)
    await resume_task(db, run, task, ep, 1)
    await db.refresh(task)
    assert task.plan[0]["status"] == "SUPERSEDED"


async def test_wait_item_schedules_a_wake_up(db: AsyncSession, clock: FrozenClock) -> None:
    _, run, task = await _setup(db, [item(1, "wait", wait={"seconds": 3600})])
    assert await execute_task(db, run, task, 1) == "waiting"
    wake = await db.scalar(select(Episode).where(Episode.source == "plan_wait"))
    assert wake is not None and wake.due_at == clock.now() + timedelta(hours=1)
    wake.status, wake.lease_epoch = "running", 1
    await db.commit()
    await resume_task(db, run, task, wake, 1)
    await db.refresh(task)
    assert task.status == "DONE"


async def test_a_wait_until_wakes_at_that_instant(db: AsyncSession, clock: FrozenClock) -> None:
    until = clock.now() + timedelta(hours=8)
    _, run, task = await _setup(db, [item(1, "wait", wait={"until": until.isoformat()})])
    assert await execute_task(db, run, task, 1) == "waiting"
    wake = await db.scalar(select(Episode).where(Episode.source == "plan_wait"))
    assert wake is not None and wake.due_at == until


async def test_llm_call_cap_blocks_the_task(
    db: AsyncSession,
    clock: FrozenClock,
    fake_llm: FakeLLM,
    tool: FakeTool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lucia.core.config import get_settings

    monkeypatch.setattr(get_settings(), "task_llm_call_cap", 1)
    _, run, task = await _setup(db, [item(1, "tool"), item(2, "tool")])
    fake_llm.on("executor", {"to_contact_id": "x", "script": "s", "first_message": "hi"})
    tool.results.append(_ok())
    assert await execute_task(db, run, task, 1) == "blocked"
    assert await db.scalar(select(StepResult.kind)) == "plan_cap"


async def test_a_journal_note_after_an_unanswered_call_still_moves_the_ladder(
    db: AsyncSession, clock: FrozenClock
) -> None:
    from tests.world import VOICE_CONFIG

    rungs = [
        {"channel": "voice", "wait_hours": 0, "attempts": 1},
        {"channel": "voice", "wait_hours": 48, "attempts": 1},
    ]
    w = await make_world(
        db, config={**VOICE_CONFIG, "follow_up": {"mode": "fixed_ladder", "ladder": rungs}}
    )
    run = await make_leased_run(db, w)
    voicemail = item(1, "tool", status="DONE", output={"summary": "", "data": {"reached": False}})
    note = item(2, "tool", tool="harness.journal_append", status="DONE", output={"summary": ""})
    task = await make_task(db, w, run, plan=[voicemail, note], status="IN_PROGRESS")
    assert await execute_task(db, run, task, 1) == "waiting"
    assert await db.scalar(select(Episode.rung).where(Episode.source == "ladder")) == 1


async def test_not_reached_schedules_the_next_ladder_rung(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    from tests.world import VOICE_CONFIG

    ladder = {
        **VOICE_CONFIG,
        "follow_up": {
            "mode": "fixed_ladder",
            "ladder": [
                {"channel": "voice", "wait_hours": 0, "attempts": 1},
                {"channel": "voice", "wait_hours": 48, "attempts": 1},
                {"action": "flag", "wait_hours": 0, "attempts": 1, "urgency": "P2"},
            ],
        },
    }
    w = await make_world(db, config=ladder)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run, plan=[item(1, "tool")])
    fake_llm.on("executor", {"to_contact_id": "x", "script": "s", "first_message": "hi"})
    tool.results.append(
        ToolResult(status="SUCCEEDED", summary="Voicemail", output={"reached": False})
    )
    assert await execute_task(db, run, task, 1) == "waiting"
    rung = await db.scalar(select(Episode).where(Episode.source == "ladder"))
    assert rung is not None and (rung.rung, rung.due_at) == (1, clock.now() + timedelta(hours=48))
    await db.refresh(task)
    assert task.status == "WAITING" and task.follow_up == {"rung": 1, "attempt": 1}
    # the rung fires: the planner adds the retry, it doesn't reach Jane again, the ladder flags
    rung.status, rung.lease_epoch = "running", 1
    await db.commit()
    fake_llm.on(
        "planner",
        PlanDraft(
            items=[
                PlanItemDraft(
                    title="Call Jane again",
                    kind="tool",
                    tool="vapi.place_call",
                    input_hint="",
                    expected_output="",
                    uses=[],
                    wait_seconds=None,
                    wait_until=None,
                )
            ]
        ),
    )
    fake_llm.on("executor", {"to_contact_id": "x", "script": "s", "first_message": "hi"})
    tool.results.append(
        ToolResult(status="SUCCEEDED", summary="No answer", output={"reached": False})
    )
    await resume_task(db, run, task, rung, 1)
    await db.refresh(task)
    assert (
        task.status == "DONE" and task.output is not None and task.output["outcome"] == "unreached"
    )
    flag = await db.scalar(select(StepResult).where(StepResult.kind == "escalation"))
    assert flag is not None and flag.urgency == "P2"


async def test_task_summary_skips_trailing_harness_notes(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    _, run, task = await _setup(
        db, [item(1, "tool"), item(2, "tool", tool="harness.journal_append")]
    )
    fake_llm.on("executor", {"to_contact_id": "x", "script": "s", "first_message": "hi"})
    fake_llm.on("executor", {"text": "noted it"})
    tool.results.append(_ok("Jane is doing well"))
    assert await execute_task(db, run, task, 1) == "done"
    await db.refresh(task)
    assert task.output is not None and task.output["summary"] == "Jane is doing well"


async def test_a_finished_call_is_posted_to_the_chat(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    from lucia.db.models import Conversation, Message

    w, run, task = await _setup(db, [item(1, "tool", status="WAITING", attempts=1)])
    conv = Conversation(firm_id=w.firm.id, channel="playground")
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
    ep = await _episode(
        db,
        w,
        run,
        task,
        trigger_type="external_response",
        metadata_={"plan_item_id": "i1", "summary": "Jane started PT", "reached": True},
    )
    await resume_task(db, run, task, ep, 1)
    posted = await db.scalar(select(Message.body).where(Message.conversation_id == conv.id))
    assert posted == "item 1: Jane started PT"


async def test_a_callback_for_an_item_that_isnt_waiting_is_ignored(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    w, run, task = await _setup(
        db, [item(1, "tool", status="FAILED", attempts=1)], status="BLOCKED"
    )
    ep = await _episode(
        db,
        w,
        run,
        task,
        trigger_type="external_response",
        metadata_={"plan_item_id": "i1", "summary": "stray", "reached": True},
    )
    await resume_task(db, run, task, ep, 1)
    await db.refresh(task)
    assert (task.status, task.plan[0]["status"]) == ("BLOCKED", "FAILED")


async def test_an_answer_rechecks_the_items_it_makes_moot(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    """Staff said the packet arrived: the planned 'call to confirm receipt' is skipped."""
    from lucia.harness.relevance import ItemVerdict, Relevance

    w, run, task = await _setup(
        db, [item(1, "human", status="WAITING"), item(2, "tool", status="PENDING")]
    )
    asked = StepResult(
        firm_id=w.firm.id,
        run_id=run.id,
        task_id=task.id,
        type="attention",
        kind="question",
        urgency="P1",
        summary="Did the records arrive?",
        summary_public="x",
        status="answered",
        dedup_key="sr:moot",
        data={"item_id": "i1"},
    )
    db.add(asked)
    await db.commit()
    fake_llm.on(
        "relevance",
        Relevance(
            verdicts=[ItemVerdict(item_id="i2", verdict="skip", reason="already received")],
            append_needed=False,
            append_reason="",
        ),
    )
    meta = {"step_result_id": str(asked.id), "answer": {"text": "Yes, all 212 pages arrived"}}
    ep = await _episode(db, w, run, task, trigger_type="user_response", metadata_=meta)
    await resume_task(db, run, task, ep, 1)
    await db.refresh(task)
    assert [i["status"] for i in task.plan] == ["DONE", "SKIPPED"]
    assert tool.calls == []


async def test_a_note_at_the_plan_cap_blocks_the_task_instead_of_failing(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    w, run, task = await _setup(db, [item(1, "tool", status="DONE")], plan_appends=5)
    ep = await _episode(db, w, run, task, metadata_={"note": "try their fax line"})
    await resume_task(db, run, task, ep, 1)  # no CapHit escapes: the episode completes
    await db.refresh(task)
    assert task.status == "BLOCKED"
    kinds = await db.scalars(select(StepResult.kind).where(StepResult.task_id == task.id))
    assert list(kinds) == ["plan_cap"]


async def test_the_executor_sees_what_earlier_calls_learned(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, tool: FakeTool
) -> None:
    """A check-in's script can open with last time's topics: the journal and past findings."""
    from lucia.harness.journal import append as journal_append

    w, run, task = await _setup(db, [item(1, "tool")])
    await journal_append(
        db, run, text="Call Jane: back pain, MRI on Oct 20", source="harness", key="j1"
    )
    db.add(
        StepResult(
            firm_id=w.firm.id,
            run_id=run.id,
            type="finding",
            kind="treatment",
            urgency="P2",
            summary="Jane has an MRI on Oct 20",
            summary_public="x",
            status="open",
            dedup_key="sr:prior",
        )
    )
    await db.commit()
    fake_llm.on("executor", {"to_contact_id": "x", "script": "s", "first_message": "hi"})
    tool.results.append(_ok())
    await execute_task(db, run, task, 1)
    packet = next(msg for role, msg, *_ in fake_llm.calls if role == "executor")
    assert "back pain, MRI on Oct 20" in packet  # journal
    assert "Jane has an MRI on Oct 20" in packet  # timeline
    assert "episodes" in packet  # e.g. what the firm said when it reopened the run


@pytest.mark.parametrize("needed", [True, False])
async def test_a_human_item_asks_what_its_inputs_call_for(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, needed: bool
) -> None:
    """Planned before the call as 'only if the review finds something, ask the firm'."""
    from lucia.harness.executor import HumanQuestion

    review = item(
        1,
        "subagent",
        status="DONE",
        output={"summary": "Doe asked if changing doctors is a concern"},
    )
    asks = item(2, "human", uses=["i1"], input_hint="Only if needed, ask the firm")
    _, run, task = await _setup(db, [review, asks])
    question = "Doe asked whether changing doctors could hurt the case. What should we tell Doe?"
    fake_llm.on("asker", HumanQuestion(needed=needed, question=question if needed else ""))
    outcome = await execute_task(db, run, task, 1)
    await db.refresh(task)
    asked = await db.scalar(select(StepResult))
    if needed:
        assert outcome == "blocked" and asked is not None and asked.summary == question
    else:
        assert asked is None and task.plan[1]["status"] == "SKIPPED"
