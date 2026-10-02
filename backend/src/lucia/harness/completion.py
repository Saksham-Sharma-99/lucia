"""Is the run done? (RUNTIME_SPEC §11.2, D22, D58). The model decides and must cite the steps
that prove it; the harness checks the citations; a judge model confirms; then a person does.
Recurring runs ask about the whole goal each cycle; an unmet goal just closes the cycle."""

import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.db.models import AgentRun, AgentRunStep, Episode, RunTask, StepResult
from lucia.db.models.run import TERMINAL_TASK
from lucia.harness import context
from lucia.harness.agent_view import AgentView, load
from lucia.harness.attention import raise_attention
from lucia.harness.intake import EpisodeSpec, insert_episode
from lucia.harness.journal import recent
from lucia.harness.keys import TargetRef, task_key
from lucia.harness.lease import fence
from lucia.harness.steps import call_llm
from lucia.harness.triage import new_task
from lucia.scheduling import scheduler
from lucia.scheduling.durations import duration

Outcome = Literal["continued", "awaiting_confirmation", "asked", "cycle_closed", "superseded"]
DECIDE = """Decide whether this run's whole goal is met, from the task outputs, journal and
episodes. If it is, cite the step ids that prove it. If not, list the next tasks it needs, or
none if nothing more can be done."""
JUDGE = """Independently check this claim that the run's goal is met. Agree only if the task
outputs support it. Consent, quiet hours and recipient rules are enforced by the platform on
every send, so don't require evidence of them."""


class NextTask(BaseModel):
    kind: str
    target: TargetRef
    title: str
    goal: str


class CompletionVerdict(BaseModel):
    met: bool
    reason: str
    evidence_step_ids: list[str]
    next: list[NextTask]


class JudgeVerdict(BaseModel):
    agree: bool
    reason: str


async def _packet(session: AsyncSession, view: AgentView) -> str:
    summary, entries = await recent(session, view.run.id)
    return context.packet(
        "completion",
        {
            "system_prompt": view.config.system_prompt,
            "goal": {"goal": view.run.goal, "criteria": view.run.completion_criteria},
            "timeline": await context.timeline(session, view.subject.id),
            "tasks": await context.tasks_overview(session, view.run.id),
            "episodes": await context.episodes_timeline(session, view.run.id),
            "journal": {"summary": summary, "recent": entries},
        },
    )


async def _cited_ok(session: AsyncSession, run: AgentRun, ids: list[str]) -> bool:
    try:
        wanted = {uuid.UUID(i) for i in ids}
    except ValueError:
        return False
    found = set(
        await session.scalars(
            select(AgentRunStep.id).where(
                AgentRunStep.id.in_(wanted),
                AgentRunStep.run_id == run.id,
                AgentRunStep.status.in_(("SUCCEEDED", "AWAITING_CALLBACK")),
            )
        )
    )
    return bool(wanted) and found == wanted


async def check_run(session: AsyncSession, run: AgentRun, epoch: int, key: str) -> Outcome:
    """`key` fingerprints the run state being checked (worker._check_key); a replay of the same
    check raises nothing new. Each model call confirms the run is still ours (steps.call_llm)."""
    view = await load(session, run)
    message = await _packet(session, view)
    verdict = await _decide(session, view, epoch, message)
    if verdict.met and not await _cited_ok(session, run, verdict.evidence_step_ids):
        retry = message + "\n\n## your evidence ids were not steps of this run that succeeded"
        verdict = await _decide(session, view, epoch, retry)
    if verdict.met and not await _cited_ok(session, run, verdict.evidence_step_ids):
        return await _ask(
            session, run, key, "The goal looks met, but the evidence doesn't check out."
        )
    if not verdict.met:
        nxt = {task_key(t.kind, t.target): t for t in verdict.next}  # the model may repeat one
        for t in nxt.values():
            created = await new_task(
                session, run, kind=t.kind, target=t.target, title=t.title, goal=t.goal
            )
            if created is None:  # the run already has that task: it does the work again
                await _reopen(session, run, t, key)
        if nxt:
            await session.commit()
            return "continued"
        if view.config.recurrence is not None:
            return await _close_cycle(session, view)
        return await _ask(session, run, key, f"Goal not met and no next step: {verdict.reason}")
    judge = await call_llm(
        session,
        run,
        role="completion_judge",
        model=view.config.models.judge,
        instructions=JUDGE,
        message=f"{message}\n\n## claim\n{verdict.reason}",
        output_type=JudgeVerdict,
        epoch=epoch,
    )
    if not judge.agree:
        why = f"Done? The agent says yes; the check says: {judge.reason}"
        return await _ask(session, run, key, why)
    await fence(session, run.id, epoch)  # FOR SHARE until our commit: intake waits on it
    if await _new_work(session, run):
        return "superseded"  # it's answered once that work is done: its triage re-checks
    run.status, run.substatus = "AWAITING_CONFIRMATION", None
    await raise_attention(
        session,
        run,
        kind="confirm_completion",
        summary=f"I think this is done: {verdict.reason}",
        dedup_key=f"sr:{run.id}:confirm:{key}",
        data={"evidence_step_ids": verdict.evidence_step_ids},
        options=[
            {"value": "confirm", "label": "Confirm complete"},
            {"value": "reopen", "label": "Reopen"},
        ],
    )
    await session.commit()  # raise_attention posted it to the chats, with the confirm buttons
    return "awaiting_confirmation"


async def _new_work(session: AsyncSession, run: AgentRun) -> bool:
    """Work that arrived while the model judged. The caller holds the fence, so a message lands
    either before this, and wins, or after our commit, and reopens the run."""
    return bool(
        await session.scalar(
            select(Episode.id).where(
                Episode.run_id == run.id,
                Episode.status.in_(("pending", "running")),
                Episode.metadata_["unit"].astext.is_distinct_from("completion"),
            )
        )
    )


async def _reopen(session: AsyncSession, run: AgentRun, t: NextTask, key: str) -> None:
    """Like a triage update: the task opens again and its planner adds what the goal needs."""
    task = await session.scalar(
        select(RunTask).where(RunTask.run_id == run.id, RunTask.key == task_key(t.kind, t.target))
    )
    assert task is not None and task.status in TERMINAL_TASK  # every task is, at a check
    task.status, task.ended_at = "IN_PROGRESS", None
    await insert_episode(
        session,
        run,
        EpisodeSpec(
            trigger_type="user_input",
            dedup_key=f"completion:{key}:{task.id}",
            metadata={"note": t.goal},
            task_id=task.id,
        ),
    )


async def _decide(
    session: AsyncSession, view: AgentView, epoch: int, message: str
) -> CompletionVerdict:
    return await call_llm(
        session,
        view.run,
        role="completion",
        model=view.config.models.loop,
        instructions=DECIDE,
        message=message,
        output_type=CompletionVerdict,
        epoch=epoch,
    )


async def _ask(session: AsyncSession, run: AgentRun, key: str, question: str) -> Outcome:
    await raise_attention(
        session,
        run,
        kind="question",
        summary=question,
        dedup_key=f"sr:{run.id}:completion:{key}",
    )
    await session.commit()
    return "asked"


async def _close_cycle(session: AsyncSession, view: AgentView) -> Outcome:
    run = view.run
    assert view.config.recurrence is not None
    cycle = max(run.cycle, 1) + 1
    await scheduler.schedule(
        session,
        run,
        source="recurrence",
        due_at=get_clock().now() + duration(view.config.recurrence.every_days, "days"),
        dedup_key=f"recurrence:{run.id}:{cycle}",
        reason=f"cycle {cycle}",
        metadata={"cycle": cycle},
    )
    await session.commit()
    return "cycle_closed"


async def confirm(
    session: AsyncSession, run: AgentRun, item: StepResult, *, choice: str, text: str | None
) -> None:
    """A person's answer to confirm_completion: complete the run, or reopen it with an ask."""
    if choice == "confirm":
        run.status, run.ended_at, run.ended_reason = "COMPLETED", get_clock().now(), "confirmed"
        await scheduler.supersede(session, run_id=run.id, reason="run_ended")
    else:
        run.status = "ACTIVE"
        await insert_episode(
            session,
            run,
            EpisodeSpec(
                trigger_type="user_input",
                dedup_key=f"answer:{item.id}:reopen",
                metadata={"instruction": text or "Reopened"},
            ),
        )
    await session.commit()
