"""Run a task's plan items in order until one has to wait (RUNTIME_SPEC §6).

Each item ends DONE, SKIPPED or FAILED, or WAITING on a webhook, a timer or a person; the
next Episode for the task resumes it here."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.core.config import get_settings
from lucia.db.models import AgentRun, AgentRunStep, Episode, RunTask, StepResult
from lucia.harness import context, relevance
from lucia.harness.agent_view import AgentView, load
from lucia.harness.attention import raise_attention
from lucia.harness.exec import tool_executor
from lucia.harness.followup import next_rung
from lucia.harness.journal import append as journal
from lucia.harness.journal import recent
from lucia.harness.lease import ensure_lease
from lucia.harness.plan import item, set_item
from lucia.harness.planner import CapHit, append, plan_task
from lucia.harness.steps import add_step, call_llm, settle_callback
from lucia.harness.subagent import run_subagent
from lucia.harness.tools.base import ToolContext, ToolResult
from lucia.notifications.updates import post_run_update
from lucia.scheduling import scheduler
from lucia.scheduling.durations import duration

RETRY_BACKOFF = (timedelta(seconds=60), timedelta(seconds=300))  # then a person (HLD §16)
RUNNABLE = ("PENDING", "RUNNING")  # an item the executor can work on now
MAX_ITEM_RESUMES = 3  # crashed attempts of one item before a person decides
EXECUTOR = """Fill in the arguments for this one tool call from the item, its inputs and the
subject. Use only contacts listed on the subject. Anything said to a person outside the firm
(a call script, a message) must not repeat clinical details from the record (diagnoses,
treatment, how they have been feeling): ask open questions instead ("How have you been?").
A first message names no case or reference number: only the firm, until the person has
confirmed who they are."""


async def _end_item(
    session: AsyncSession,
    view: AgentView,
    task: RunTask,
    it: dict[str, Any],
    status: str,
    summary: str,
    data: dict[str, Any] | None = None,
    step_id: uuid.UUID | None = None,
) -> None:
    steps = [*it["step_ids"], str(step_id)] if step_id else it["step_ids"]
    output = {"summary": summary, "data": data or {}} if status == "DONE" else it["output"]
    set_item(
        task,
        it["id"],
        status=status,
        output=output,
        step_ids=steps,
        reason=None if status == "DONE" else summary,
        ended_at=get_clock().now().isoformat(),
    )
    sep = "\n\n" if "\n" in summary else " "  # a markdown block starts its own paragraph
    await journal(
        session,
        view.run,
        text=f"{it['title']}:{sep}{summary}",
        source="harness",
        key=f"{task.id}:{it['id']}:{it['attempts']}:{status}",
        task_id=task.id,
    )


async def _block(
    session: AsyncSession,
    view: AgentView,
    task: RunTask,
    it: dict[str, Any] | None,
    kind: str,
    why: str,
) -> str:
    task.status = "BLOCKED"
    where = it["id"] if it else "task"
    await raise_attention(
        session,
        view.run,
        kind=kind,
        summary=f"{task.title}: {why}",
        dedup_key=f"sr:{task.id}:{where}:{kind}:{it['attempts'] if it else task.plan_appends}",
        task_id=task.id,
        data={"item_id": it["id"] if it else None},
        options=[{"value": "retry", "label": "Try again"}, {"value": "skip", "label": "Skip it"}],
    )
    await session.commit()
    return "blocked"


async def execute_task(session: AsyncSession, run: AgentRun, task: RunTask, epoch: int) -> str:
    """Returns "done", "waiting" or "blocked"."""
    view = await load(session, run)
    if not task.plan and not await plan_task(session, view, task, epoch):
        return "blocked"
    held = task.status  # what a still-waiting item keeps the task at
    if any(i["status"] in RUNNABLE for i in task.plan):
        task.status = "IN_PROGRESS"
        task.started_at = task.started_at or get_clock().now()
    cap = get_settings().task_llm_call_cap
    while it := next((i for i in task.plan if i["status"] in RUNNABLE), None):
        await ensure_lease(session, run.id, epoch)
        if await _llm_calls(session, task, epoch) >= cap:
            return await _block(session, view, task, it, "plan_cap", "too many model calls")
        # An attempt starts PENDING → RUNNING. A RUNNING item is a crashed attempt being resumed:
        # it keeps its count and its recorded arguments, so its key, and the outbox adopts the
        # earlier send instead of making another.
        resumed = it["status"] == "RUNNING"
        if resumed:  # counted and committed first: a crash that kills the worker can't be caught
            if it.get("resumes", 0) >= MAX_ITEM_RESUMES:
                await _end_item(session, view, task, it, "FAILED", "kept crashing the worker")
                why = f"{it['title']} kept crashing the worker"
                return await _block(session, view, task, item(task, it["id"]), "item_failed", why)
            set_item(task, it["id"], resumes=it.get("resumes", 0) + 1)
            await session.commit()
        it = set_item(task, it["id"], status="RUNNING", attempts=it["attempts"] + (not resumed))
        outcome = await _run_item(session, view, task, it, epoch, resumed=resumed)
        await session.commit()
        if outcome != "next":
            return outcome
    if any(i["status"] == "WAITING" for i in task.plan):  # a call or a person still to answer
        task.status = held if held in ("WAITING", "BLOCKED") else "WAITING"
        await session.commit()
        return task.status.lower()
    return await _finish(session, view, task)


async def _llm_calls(session: AsyncSession, task: RunTask, epoch: int) -> int:
    return (
        await session.scalar(
            select(func.count()).where(
                AgentRunStep.task_id == task.id,
                AgentRunStep.kind == "llm",
                AgentRunStep.lease_epoch == epoch,
            )
        )
        or 0
    )


async def _run_item(
    session: AsyncSession,
    view: AgentView,
    task: RunTask,
    it: dict[str, Any],
    epoch: int,
    *,
    resumed: bool,
) -> str:
    """Runs one item; "next" moves on, anything else is the task's outcome for now."""
    ctx = ToolContext(session, view, task, it, epoch)
    if it["kind"] == "wait":
        await scheduler.schedule(
            session,
            view.run,
            task_id=task.id,
            source="plan_wait",
            due_at=_wait_due(it["wait"]),
            dedup_key=f"plan_wait:{task.id}:{it['id']}",
            reason=it["title"],
            metadata={"plan_item_id": it["id"]},
        )
        return _wait(task, it)
    if it["kind"] == "human":
        await raise_attention(
            session,
            view.run,
            kind="question",
            summary=it["input_hint"] or it["title"],
            dedup_key=f"sr:{task.id}:{it['id']}:question:{it['attempts']}",
            task_id=task.id,
            data={"item_id": it["id"]},
        )
        _wait(task, it)
        task.status = "BLOCKED"
        return "blocked"
    if it["kind"] == "subagent":
        result = await run_subagent(ctx)
    elif resumed and (sent := await _sent_by_crashed_attempt(session, task, it)):
        # the same arguments, so the same key: the outbox returns or re-checks that send
        result = await tool_executor.run(ctx, it["tool"], sent.input)
    else:
        args = await call_llm(
            session,
            view.run,
            role="executor",
            model=view.config.models.loop,
            instructions=EXECUTOR,
            message=await _executor_packet(session, view, task, it),
            tool=(it["tool"], view.tools[it["tool"]].input_schema),
            epoch=epoch,
            task_id=task.id,
            plan_item_id=it["id"],
        )
        result = await tool_executor.run(ctx, it["tool"], args)
    return await _apply(session, view, task, it, result, epoch)


async def _sent_by_crashed_attempt(
    session: AsyncSession, task: RunTask, it: dict[str, Any]
) -> AgentRunStep | None:
    """The outbox row the crashed attempt wrote, if it got that far (one that may have sent)."""
    return await session.scalar(
        select(AgentRunStep)
        .where(
            AgentRunStep.task_id == task.id,
            AgentRunStep.plan_item_id == it["id"],
            AgentRunStep.kind == "tool",
            AgentRunStep.status.in_(tool_executor.MAYBE_SENT),
        )
        .order_by(AgentRunStep.seq.desc())
        .limit(1)
    )


def _wait(task: RunTask, it: dict[str, Any]) -> str:
    set_item(task, it["id"], status="WAITING")
    task.status = "WAITING"
    return "waiting"


def _wait_due(wait: dict[str, Any]) -> datetime:
    """A clock time is already an instant; a span counts from now (dev scale applies)."""
    if until := wait.get("until"):
        return datetime.fromisoformat(until)
    return get_clock().now() + duration(wait["seconds"], "seconds")


async def _executor_packet(
    session: AsyncSession, view: AgentView, task: RunTask, it: dict[str, Any]
) -> str:
    subject = await context.subject_snapshot(session, view.subject)
    summary, entries = await recent(session, view.run.id)
    return context.packet(
        "executor",
        {
            "system_prompt": view.instructions,
            "now": context.clock(subject),
            "subject": subject,
            # what earlier calls and cycles learned, so a call can pick up from last time
            "timeline": await context.timeline(session, view.subject.id),
            "journal": {"summary": summary, "recent": entries},
            "task": {"title": task.title, "goal": task.goal, "input": task.input},
            "item": {k: it[k] for k in ("title", "input_hint", "expected_output", "tool")},
            "inputs": {u: (item(task, u)["output"] or {}).get("summary") for u in it["uses"]},
            "policies": [p.rule for p in view.policies],
        },
    )


async def _apply(
    session: AsyncSession,
    view: AgentView,
    task: RunTask,
    it: dict[str, Any],
    result: ToolResult,
    epoch: int,
) -> str:
    match result.status:
        case "SUCCEEDED":
            await _end_item(
                session, view, task, it, "DONE", result.summary, result.output, result.step_id
            )
            return "next"
        case "AWAITING_CALLBACK":
            if result.step_id and str(result.step_id) not in it["step_ids"]:
                set_item(task, it["id"], step_ids=[*it["step_ids"], str(result.step_id)])
            return _wait(task, it)
        case "DEFERRED":
            assert result.resume_at is not None
            await scheduler.schedule(
                session,
                view.run,
                task_id=task.id,
                source="deferral",
                due_at=result.resume_at,
                dedup_key=f"deferral:{task.id}:{it['id']}:{result.resume_at.isoformat()}",
                reason=f"deferred: {result.reason}",
                metadata={"plan_item_id": it["id"]},
            )
            set_item(task, it["id"], attempts=it["attempts"] - 1)  # a deferral isn't an attempt
            return _wait(task, it)
        case "BLOCKED_BY_POLICY":
            await _end_item(session, view, task, it, "SKIPPED", f"policy_deny:{result.reason}")
            await raise_attention(
                session,
                view.run,
                kind="escalation",
                summary=f"{it['title']} was blocked by policy ({result.reason})",
                dedup_key=f"sr:{task.id}:{it['id']}:policy",
                task_id=task.id,
                data={"item_id": it["id"], "rule": result.reason, "source": "policy_deny"},
            )
            try:
                await append(
                    session,
                    view,
                    task,
                    reason=f"{it['tool']} was blocked by policy: {result.reason}",
                    new_info="Plan another way to reach the goal, or ask a person.",
                    epoch=epoch,
                )
            except CapHit:
                return "blocked"
            return "next"
        case "SKIPPED":
            await _end_item(session, view, task, it, "SKIPPED", result.reason or "skipped")
            return "next"
        case "NEEDS_HUMAN":
            set_item(task, it["id"], status="WAITING", draft={"summary": result.summary})
            task.status = "BLOCKED"
            return "blocked"
        case "BLOCKED_BY_GUARDRAIL":
            await _end_item(session, view, task, it, "FAILED", result.reason or "guardrail")
            task.status = "BLOCKED"
            return "blocked"
        case "FAILED" if result.retryable and _tries(it) <= len(RETRY_BACKOFF):
            await scheduler.schedule(
                session,
                view.run,
                task_id=task.id,
                source="retry",
                due_at=get_clock().now() + RETRY_BACKOFF[_tries(it) - 1],
                dedup_key=f"retry:{task.id}:{it['id']}:{it['attempts']}",
                reason=f"retry after {result.reason}",
                metadata={"plan_item_id": it["id"]},
            )
            return _wait(task, it)
        case _:
            await _end_item(session, view, task, it, "FAILED", result.reason or result.summary)
            return await _block(
                session,
                view,
                task,
                item(task, it["id"]),
                "item_failed",
                f"{it['title']} failed: {result.reason or result.summary}",
            )


def uncount_resumes(task: RunTask) -> None:
    """`resumes` counts killed workers; a caught failure or a person's retry starts it over."""
    for i in task.plan:
        if i.get("resumes"):
            set_item(task, i["id"], resumes=0)


def _tries(it: dict[str, Any]) -> int:
    """Attempts since a person last said "try again"; `attempts` itself never goes back."""
    return it["attempts"] - it.get("retry_from", 0)


async def _finish(session: AsyncSession, view: AgentView, task: RunTask) -> str:
    """All items are done or skipped. Not reaching anyone moves the follow-up ladder."""
    outbound = [
        i
        for i in task.plan
        if i["status"] == "DONE" and i["kind"] == "tool" and not i["tool"].startswith("harness.")
    ]
    reached = (
        (outbound[-1]["output"] or {}).get("data", {}).get("reached", True) if outbound else True
    )
    if not reached and view.config.follow_up.mode == "fixed_ladder":
        nxt = next_rung(view.config, task.follow_up)
        if nxt and nxt[2].channel:
            rung, attempt, step = nxt
            await scheduler.schedule(
                session,
                view.run,
                task_id=task.id,
                source="ladder",
                due_at=get_clock().now() + duration(step.wait_hours, "hours"),
                dedup_key=f"ladder:{view.run.id}:{task.id}:{rung}:{attempt}",
                reason=f"follow-up on {step.channel}",
                rung=rung,
                attempt=attempt,
            )
            task.follow_up = {"rung": rung, "attempt": attempt}
            task.status = "WAITING"
            await session.commit()
            return "waiting"
        if nxt:  # an escalate/flag rung ends the ladder
            await raise_attention(
                session,
                view.run,
                kind="escalation",
                urgency=nxt[2].urgency or "P2",
                summary=f"{task.title}: no one was reached after every follow-up",
                dedup_key=f"sr:{task.id}:ladder_end",
                task_id=task.id,
                data={"source": "ladder"},
            )
    done = [i for i in task.plan if i["status"] == "DONE"]
    # The task's result is its last real work, not a trailing journal note.
    work = [i for i in done if not (i.get("tool") or "").startswith("harness.")] or done
    task.status, task.ended_at = "DONE", get_clock().now()
    task.output = {
        "summary": (work[-1]["output"] or {}).get("summary") if work else "Nothing to do",
        "outcome": "done" if reached else "unreached",
        "evidence_step_ids": [s for i in done for s in i["step_ids"]],
    }
    await session.commit()
    return "done"


async def resume_task(
    session: AsyncSession, run: AgentRun, task: RunTask, episode: Episode, epoch: int
) -> None:
    """Apply what the Episode brings to the waiting item, then carry on (RUNTIME_SPEC §6.5)."""
    view = await load(session, run)
    meta = episode.metadata_
    item_id: str = meta.get("plan_item_id") or ""
    match (episode.trigger_type, episode.source):
        case ("user_input" | "handback", _):
            try:
                await relevance.check(session, view, task, episode, epoch)
            except CapHit:  # the task is BLOCKED with a plan_cap item for a person
                return
        case ("external_response" | "scheduled", _) if (
            item_id and item(task, item_id)["status"] != "WAITING"
        ):
            return  # a late report or a stale wake for an item that moved on (skipped, superseded)
        case ("external_response", _):
            await settle_callback(session, meta)
            it = item(task, item_id)
            await post_run_update(
                session,
                run,
                body=f"{it['title']}: {meta.get('summary', '')}",
                source_id=f"item:{task.id}:{item_id}:{it['attempts']}",
            )
            await _end_item(
                session,
                view,
                task,
                it,
                "DONE",
                meta.get("summary", ""),
                {k: v for k, v in meta.items() if k not in ("plan_item_id", "agent_prompt_id")},
            )
            if any(i["status"] == "PENDING" for i in task.plan):
                await relevance.check(session, view, task, episode, epoch)
        case ("user_response", _):
            await _answer(session, view, task, meta, epoch)
            # what a person said can make the planned items moot, like a call report can
            said = (meta.get("answer") or {}).get("text")
            if said and any(i["status"] == "PENDING" for i in task.plan):
                try:
                    await relevance.check(session, view, task, episode, epoch)
                except CapHit:
                    return
        case ("scheduled", "plan_wait"):
            await _end_item(session, view, task, item(task, item_id), "DONE", "waited")
        case ("scheduled", "reconcile"):
            # reconcile_orphans ran at claim: re-run only once the send is settled
            step = await session.get_one(AgentRunStep, uuid.UUID(meta["step_id"]))
            if step.status == "SUCCEEDED" or (step.error or {}).get("class") == "not_sent":
                set_item(task, item_id, status="RUNNING")
        case ("scheduled", "deferral" | "retry") if item_id:
            set_item(task, item_id, status="PENDING")
        case ("scheduled", "ladder" | "dynamic"):
            try:
                await append(
                    session,
                    view,
                    task,
                    reason=f"Follow-up attempt {task.follow_up.get('attempt', 1)} on rung "
                    f"{task.follow_up.get('rung', 0)}: the last attempt reached no one",
                    new_info=episode.reason or "",
                    epoch=epoch,
                )
            except CapHit:
                return
        case _:
            pass
    await session.commit()
    if task.status not in ("DONE", "SKIPPED", "FAILED"):
        await execute_task(session, run, task, epoch)


async def _settle_uncertain(
    session: AsyncSession,
    view: AgentView,
    task: RunTask,
    it: dict[str, Any],
    asked: StepResult,
    choice: str | None,
) -> None:
    """ "It was sent" adopts the step; "it was not sent" resends under the same key."""
    step = await session.get_one(AgentRunStep, uuid.UUID(asked.data["step_id"]))
    if choice == "sent":
        asynchronous = view.tools[step.tool or ""].is_async
        step.status = "AWAITING_CALLBACK" if asynchronous else "SUCCEEDED"
        step.output = {**step.output, "adopted": True}
        if asynchronous:
            set_item(task, it["id"], status="WAITING")
        else:
            await _end_item(session, view, task, it, "DONE", "sent (confirmed by a person)")
    else:
        step.status, step.error = "FAILED", {"class": "not_sent", "reason": "confirmed_by_person"}
        set_item(task, it["id"], status="RUNNING")


async def _answer(
    session: AsyncSession, view: AgentView, task: RunTask, meta: dict[str, Any], epoch: int
) -> None:
    asked = await session.get_one(StepResult, uuid.UUID(meta["step_result_id"]))
    answer = meta.get("answer") or {}
    item_id = asked.data.get("item_id")
    choice, text = answer.get("choice"), answer.get("text") or ""
    if item_id is None:  # about the whole task (e.g. it couldn't be planned)
        if choice == "skip":
            task.status = "SKIPPED"
            for i in task.plan:
                if i["status"] in (*RUNNABLE, "WAITING"):
                    set_item(task, i["id"], status="SKIPPED", reason="skipped by a person")
        else:  # carry on from where the plan is (none yet: plan it)
            task.status = "IN_PROGRESS" if task.plan else "TODO"
            uncount_resumes(task)
        return
    it = item(task, item_id)
    if it["status"] in ("DONE", "SKIPPED", "SUPERSEDED"):
        return  # the item moved on while the question was open
    if asked.kind == "uncertain_send":
        await _settle_uncertain(session, view, task, it, asked, choice)
    elif asked.kind == "question":
        said = text or choice or ""
        # a human step, so what the person told us is evidence the run can cite (like a call)
        step = await add_step(
            session,
            view.run,
            kind="human",
            status="SUCCEEDED",
            idempotency_key=f"human:{asked.id}",
            epoch=epoch,
            task_id=task.id,
            plan_item_id=item_id,
            actor="human",
            input={"question": asked.summary},
            output={"answer": answer},
            summary=said,
        )
        await _end_item(session, view, task, it, "DONE", said, step_id=step.id)
    elif choice == "skip":
        await _end_item(session, view, task, it, "SKIPPED", "skipped by a person")
    elif choice == "accept":
        await _end_item(
            session, view, task, it, "DONE", (it.get("draft") or {}).get("summary", text)
        )
    else:
        set_item(task, item_id, status="PENDING", retry_from=it["attempts"], resumes=0)
    task.status = "IN_PROGRESS"
