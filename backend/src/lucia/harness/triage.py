"""Triage: a run-wide Episode (a message, a hand-back) decides which tasks to create, update
or cancel (RUNTIME_SPEC §5). Recurrence Episodes create the next cycle's task without the model."""

import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.db.models import Agent, AgentRun, Episode, RunTask, SubjectContact
from lucia.db.models.run import TERMINAL_TASK
from lucia.harness import context
from lucia.harness.agent_view import AgentView, load
from lucia.harness.attention import raise_attention
from lucia.harness.intake import EpisodeSpec, insert_episode
from lucia.harness.journal import recent
from lucia.harness.keys import TargetRef, kind_vocabulary, similar_open_task, slug, task_key
from lucia.harness.steps import add_step, call_llm
from lucia.notifications.updates import post_run_update
from lucia.scheduling import scheduler

INSTRUCTIONS = """You triage new input for an agent's run on one subject.
Decide which tasks the run needs: update an existing task when the input is about the same
work (always check the open tasks first), create a task only for new work, cancel a task the
user no longer wants. A task has a short verb_noun kind (reuse the kinds listed when they fit)
and a target: a contact (ref = contact_id from the subject), a document, a period, an external
record, or the run itself. List parts of the request this agent cannot do in out_of_scope.
If the trigger's brief and message disagree, the message wins. On the first triage of a run,
write its goal and plain-language completion criteria; later, set them only if they change.
Criteria describe outcomes the task outputs can show (who was reached, what was learned or
received), never compliance: consent, quiet hours and recipients are enforced by the platform.
When the goal shows `recurs_every_days`, the run repeats: its goal is the ongoing purpose across
all cycles (e.g. keep the firm informed of the client's wellbeing while the matter is open),
never one occurrence; each cycle's task does one round.
Reply with one or two short sentences for the user. The reply describes only the ops you
return: with none, say nothing changed and why. Never claim an action you did not return (you
cannot end or close the run; a person does that from the run or its attention items)."""


class TriageOp(BaseModel):
    op: Literal["create", "update", "cancel"]
    task_id: str | None
    kind: str | None
    target: TargetRef | None
    title: str | None
    goal: str | None
    input_note: str | None
    depends_on_keys: list[str]
    reason: str


class OutOfScope(BaseModel):
    request: str
    reason: str


class TriageResult(BaseModel):
    ops: list[TriageOp]
    out_of_scope: list[OutOfScope]
    goal: str | None
    criteria: str | None
    reply: str


class SameTask(BaseModel):
    same: bool


async def run_triage(session: AsyncSession, run: AgentRun, episode: Episode, epoch: int) -> None:
    view = await load(session, run)
    if episode.source == "recurrence":
        await create_cycle_task(session, run, episode)
        return
    message = await _packet(session, view, episode)
    result = await _ask(session, view, episode, epoch, message)
    errors = await _apply(session, view, episode, epoch, result)
    if errors:
        retry = f"{message}\n\n## errors in your last answer\n" + "\n".join(errors)
        result = await _ask(session, view, episode, epoch, retry)
        await _apply(session, view, episode, epoch, result, final=True)
    await session.commit()


async def _packet(session: AsyncSession, view: AgentView, episode: Episode) -> str:
    summary, entries = await recent(session, view.run.id)
    return context.packet(
        "triage",
        {
            "system_prompt": view.instructions,
            "goal": {
                "goal": view.run.goal,
                "criteria": view.run.completion_criteria,
                "recurs_every_days": view.config.recurrence and view.config.recurrence.every_days,
            },
            "subject": await context.subject_snapshot(session, view.subject),
            "timeline": await context.timeline(session, view.subject.id),
            "tasks": await context.tasks_overview(session, view.run.id),
            "kinds": await kind_vocabulary(session, view.run),
            "episodes": await context.episodes_timeline(session, view.run.id),
            "journal": {"summary": summary, "recent": entries},
            "conversation": await context.conversation_context(
                session, episode.metadata_.get("conversation_id")
            ),
            "trigger": await context.trigger(session, episode),
        },
    )


async def _ask(
    session: AsyncSession, view: AgentView, episode: Episode, epoch: int, message: str
) -> TriageResult:
    result = await call_llm(
        session,
        view.run,
        role="triage",
        model=view.config.models.loop,
        instructions=INSTRUCTIONS,
        message=message,
        output_type=TriageResult,
        epoch=epoch,
        episode_id=episode.id,
    )
    return result


async def _apply(
    session: AsyncSession,
    view: AgentView,
    episode: Episode,
    epoch: int,
    result: TriageResult,
    *,
    final: bool = False,
) -> list[str]:
    """Validates every op first (reads only). With errors the model gets one retry; on the
    final pass invalid ops are dropped and the rest is applied. Any model call (is a new task
    the same as an existing one?) comes before the first write."""
    checked = [(op, await _problem(session, view.run, op)) for op in result.ops]
    errors = [f"{op.op} {op.kind or op.task_id}: {problem}" for op, problem in checked if problem]
    if errors and not final:
        return errors
    valid = [op for op, problem in checked if not problem]
    targets = [await _target(session, view, episode, epoch, op) for op in valid]
    for op, task in zip(valid, targets, strict=True):
        await _apply_op(session, view.run, episode, op, task)
    run = view.run
    await _set_goal(session, run, result, epoch)
    for i, item in enumerate(result.out_of_scope):
        await raise_attention(
            session,
            run,
            kind="out_of_scope",
            urgency="P1",
            summary=f"Out of scope: {item.request} ({item.reason})",
            dedup_key=f"sr:{episode.id}:out_of_scope:{i}",
            data={"request": item.request, "reason": item.reason},
        )
    await post_run_update(session, run, body=result.reply, source_id=f"triage:{episode.id}")
    return []


async def _problem(session: AsyncSession, run: AgentRun, op: TriageOp) -> str | None:
    if op.op == "create":
        if not (op.kind and op.target and op.title and op.goal and slug(op.kind)):
            return "create needs kind, target, title and goal"
        if op.target.type == "contact" and not await _is_subject_contact(session, run, op.target):
            return f"{op.target.ref} is not a contact on this subject"
        return None
    if await _own_task(session, run, op.task_id) is None:
        return f"task {op.task_id} is not one of this run's tasks"
    return None


async def _set_goal(session: AsyncSession, run: AgentRun, result: TriageResult, epoch: int) -> None:
    if not run.goal:
        run.goal = result.goal or ""
        run.completion_criteria = result.criteria or ""
    elif result.criteria and result.criteria != run.completion_criteria:
        await add_step(
            session,
            run,
            kind="system",
            tool="harness.run.amend_criteria",
            status="SUCCEEDED",
            idempotency_key=f"criteria:{run.id}:{uuid.uuid4()}",
            epoch=epoch,
            actor="system",
            input={"old": run.completion_criteria, "new": result.criteria},
        )
        run.completion_criteria = result.criteria


async def _target(
    session: AsyncSession, view: AgentView, episode: Episode, epoch: int, op: TriageOp
) -> RunTask | None:
    """The existing task an op acts on: its own for update/cancel; for create, the task with the
    same key or one the model confirms is the same (then the create is an update)."""
    run = view.run
    if op.op != "create":
        return await _own_task(session, run, op.task_id)
    assert op.kind and op.target
    key = task_key(op.kind, op.target)
    return await session.scalar(
        select(RunTask).where(RunTask.run_id == run.id, RunTask.key == key)
    ) or await _confirm_similar(session, view, episode, epoch, key, op)


async def _apply_op(
    session: AsyncSession, run: AgentRun, episode: Episode, op: TriageOp, task: RunTask | None
) -> None:
    if op.op == "cancel":
        assert task is not None  # checked by _problem
        await cancel_task(session, task, op.reason)
        return
    if task is not None:
        await _update(session, run, episode, task, op)
        return
    assert op.kind and op.target and op.title and op.goal
    known = set(await session.scalars(select(RunTask.key).where(RunTask.run_id == run.id)))
    await new_task(
        session,
        run,
        kind=op.kind,
        target=op.target,
        title=op.title,
        goal=op.goal,
        input={"brief": episode.metadata_.get("brief"), "notes": _notes(op)},
        origin_episode_id=episode.id,
        depends_on=[k for k in op.depends_on_keys if k in known],  # an unknown key never ends
    )


async def new_task(
    session: AsyncSession,
    run: AgentRun,
    *,
    kind: str,
    target: TargetRef,
    title: str,
    goal: str,
    created_by: str = "triage",
    input: dict[str, object] | None = None,
    origin_episode_id: uuid.UUID | None = None,
    depends_on: list[str] | None = None,
) -> RunTask | None:
    """Adds a task under its harness-built key; None if the run already has that key."""
    key = task_key(kind, target)
    if await session.scalar(select(RunTask.id).where(RunTask.run_id == run.id, RunTask.key == key)):
        return None
    task = RunTask(
        firm_id=run.firm_id,
        run_id=run.id,
        key=key,
        kind=slug(kind).replace("-", "_"),
        target=target.model_dump(),
        title=title,
        goal=goal,
        input=input or {},
        created_by=created_by,
        origin_episode_id=origin_episode_id,
        depends_on=depends_on or [],
    )
    session.add(task)
    await session.flush()
    return task


async def _is_subject_contact(session: AsyncSession, run: AgentRun, target: TargetRef) -> bool:
    try:
        contact_id = uuid.UUID(target.ref or "")
    except ValueError:
        return False
    found = await session.scalar(
        select(SubjectContact.id).where(
            SubjectContact.id == contact_id, SubjectContact.subject_id == run.subject_id
        )
    )
    return found is not None


async def _confirm_similar(
    session: AsyncSession, view: AgentView, episode: Episode, epoch: int, key: str, op: TriageOp
) -> RunTask | None:
    near = await similar_open_task(session, view.run.id, key)
    if near is None:
        return None
    answer = await call_llm(
        session,
        view.run,
        role="triage",
        model=view.config.models.loop,
        instructions="Answer whether the new work is the same task as the existing one.",
        message=(
            f"## existing task\n{near.title}: {near.goal}\n\n## new work\n{op.title}: {op.goal}"
        ),
        output_type=SameTask,
        epoch=epoch,
        episode_id=episode.id,
    )
    return near if answer.same else None


async def _own_task(session: AsyncSession, run: AgentRun, task_id: str | None) -> RunTask | None:
    try:
        task = await session.get(RunTask, uuid.UUID(task_id or ""))
    except ValueError:
        return None
    return task if task is not None and task.run_id == run.id else None


def _notes(op: TriageOp) -> list[str]:
    return [op.input_note] if op.input_note else []


async def _update(
    session: AsyncSession, run: AgentRun, episode: Episode, task: RunTask, op: TriageOp
) -> None:
    if op.goal:
        task.goal = op.goal
    task.input = {**task.input, "notes": [*task.input.get("notes", []), *_notes(op)]}
    if task.status in TERMINAL_TASK:
        task.status, task.ended_at = "IN_PROGRESS", None
    if task.plan:  # the plan predates this input: check what's still needed (§7.2)
        await insert_episode(
            session,
            run,
            EpisodeSpec(
                trigger_type="user_input",
                dedup_key=f"{episode.dedup_key}:{task.id}",
                metadata={**episode.metadata_, "note": op.input_note},
                task_id=task.id,
            ),
        )


async def cancel_task(session: AsyncSession, task: RunTask, reason: str) -> None:
    task.status, task.ended_at = "SKIPPED", get_clock().now()
    task.output = {"summary": f"Cancelled: {reason}", "outcome": "skipped", "evidence_step_ids": []}
    task.plan = [
        {**i, "status": "SUPERSEDED", "reason": reason}
        if i.get("status") in ("PENDING", "WAITING", "RUNNING")
        else i
        for i in task.plan
    ]
    await scheduler.supersede(session, run_id=task.run_id, task_id=task.id, reason="task_cancelled")


async def create_cycle_task(session: AsyncSession, run: AgentRun, episode: Episode) -> None:
    cycle = int(episode.metadata_.get("cycle", run.cycle + 1))
    agent_kind = await session.scalar(
        select(RunTask.kind)
        .where(RunTask.run_id == run.id, RunTask.created_by == "recurrence")
        .order_by(RunTask.created_at.desc())
        .limit(1)
    )
    handle = agent_kind or (await session.get_one(Agent, run.agent_id)).handle
    await session.execute(
        insert(RunTask)
        .values(
            firm_id=run.firm_id,
            run_id=run.id,
            key=f"{slug(handle)}:cycle-{cycle}",
            kind=handle,
            target={"type": "run", "ref": None},
            title=f"Cycle {cycle}",
            goal=run.goal,
            created_by="recurrence",
            origin_episode_id=episode.id,
        )
        .on_conflict_do_nothing(index_elements=["run_id", "key"])  # a replayed Episode
    )
    run.cycle = cycle
    await session.commit()
