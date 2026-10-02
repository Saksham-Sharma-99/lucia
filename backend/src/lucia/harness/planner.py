"""Plan-then-execute: the Planner writes a task's items up front and appends later; items are
never edited or removed (RUNTIME_SPEC §6.1, §7). Plans are validated deterministically."""

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.config import get_settings
from lucia.db.models import AgentRunStep, RunTask
from lucia.harness import context
from lucia.harness.agent_view import AgentView
from lucia.harness.attention import raise_attention
from lucia.harness.journal import recent
from lucia.harness.steps import call_llm

INSTRUCTIONS = """You plan one task for an agent. Write the items that finish it, in order.
Item kinds:
- tool: one call of one of the agent's tools (set `tool`). Arguments are filled in later.
- subagent: thinking work that produces text: draft, review, summarize, extract.
- wait: pause before the next item (set `wait_seconds`).
- human: ask a person for something only they can give.
`uses` lists the ids of earlier items whose output this item needs. New items get ids after
the existing ones. Respect the policies, consent and opt-outs shown. Keep plans short."""


class PlanItemDraft(BaseModel):
    title: str
    kind: Literal["tool", "subagent", "wait", "human"]
    tool: str | None
    input_hint: str
    expected_output: str
    uses: list[str]
    wait_seconds: int | None


class PlanDraft(BaseModel):
    items: list[PlanItemDraft]


class CapHit(Exception):
    """The task reached its item or append cap; a human has to look."""


def validate(draft: PlanDraft, view: AgentView, existing: int) -> list[str]:
    cap = get_settings().plan_item_cap
    if existing + len(draft.items) > cap:
        return [f"a task has at most {cap} items"]
    max_wait = view.config.end_conditions.max_duration_days * 86400
    errors: list[str] = []
    for n, it in enumerate(draft.items, start=existing + 1):
        where = f"item i{n} ({it.title})"
        if it.kind == "tool":
            if not it.tool:
                errors.append(f"{where} needs a tool")
            elif it.tool not in view.tools or not view.tools[it.tool].input_schema:
                errors.append(f"{where}: {it.tool} is not one of this agent's tools")
        if it.kind == "wait" and not (it.wait_seconds and 0 < it.wait_seconds <= max_wait):
            errors.append(f"{where}: wait_seconds must be between 1 and {max_wait}")
        errors += [
            f"{where} uses {u}, which is not an earlier item"
            for u in it.uses
            if not u.startswith("i") or not u[1:].isdigit() or int(u[1:]) >= n
        ]
    return errors


def _stored(draft: PlanDraft, start: int, added_in: int) -> list[dict[str, Any]]:
    return [
        {
            "id": f"i{n}",
            "ordinal": n,
            "title": it.title,
            "kind": it.kind,
            "tool": it.tool if it.kind == "tool" else None,
            "input_hint": it.input_hint,
            "expected_output": it.expected_output,
            "uses": it.uses,
            "wait": {"seconds": it.wait_seconds} if it.kind == "wait" else None,
            "status": "PENDING",
            "attempts": 0,
            "step_ids": [],
            "output": None,
            "reason": None,
            "superseded_by": [],
            "added_in": added_in,
        }
        for n, it in enumerate(draft.items, start=start)
    ]


async def _packet(
    session: AsyncSession, view: AgentView, task: RunTask, new_info: str | None
) -> str:
    deps = await session.scalars(
        select(RunTask).where(RunTask.run_id == task.run_id, RunTask.key.in_(task.depends_on))
    )
    attempts = await session.scalars(
        select(AgentRunStep.summary)
        .where(AgentRunStep.task_id == task.id, AgentRunStep.kind != "llm")
        .order_by(AgentRunStep.seq)
    )
    summary, entries = await recent(session, view.run.id)
    return context.packet(
        "planner",
        {
            "system_prompt": view.config.system_prompt,
            "goal": {"goal": view.run.goal, "criteria": view.run.completion_criteria},
            "subject": await context.subject_snapshot(session, view.subject),
            "timeline": await context.timeline(session, view.subject.id),
            "task": {"title": task.title, "goal": task.goal, "input": task.input},
            "dependencies": {d.key: (d.output or {}).get("summary") for d in deps},
            "plan": task.plan,
            "attempts": [a for a in attempts if a],
            "episodes": await context.episodes_timeline(session, view.run.id),
            "journal": {"summary": summary, "recent": entries},
            "policies": [
                {"rule": p.rule, "params": [s.params for s in p.sources if s.applies]}
                for p in view.policies
            ],
            "tools": [
                {"name": t.name, "description": t.description, "arguments": t.input_schema}
                for t in view.tools.values()
                if t.input_schema
            ],
            "trigger": new_info,
        },
    )


async def _draft(
    session: AsyncSession, view: AgentView, task: RunTask, epoch: int, new_info: str | None
) -> PlanDraft | None:
    """Asks the planner, with one retry on validation errors; None if still invalid."""
    message = await _packet(session, view, task, new_info)
    for _ in range(2):
        draft = await call_llm(
            session,
            view.run,
            role="planner",
            model=view.config.models.loop,
            instructions=INSTRUCTIONS,
            message=message,
            output_type=PlanDraft,
            epoch=epoch,
            task_id=task.id,
        )
        errors = validate(draft, view, existing=len(task.plan))
        if not errors:
            return draft
        message += "\n\n## errors in your last plan\n" + "\n".join(errors)
    return None


async def _blocked(
    session: AsyncSession, view: AgentView, task: RunTask, why: str, kind: str
) -> None:
    task.status = "BLOCKED"
    await raise_attention(
        session,
        view.run,
        kind=kind,
        summary=f"{task.title}: {why}",
        dedup_key=f"sr:{task.id}:{kind}:{len(task.plan)}:{task.plan_appends}",
        task_id=task.id,
        options=[{"value": "retry", "label": "Try again"}, {"value": "skip", "label": "Skip task"}],
    )
    await session.commit()


async def plan_task(session: AsyncSession, view: AgentView, task: RunTask, epoch: int) -> bool:
    """Writes the first plan; False (task BLOCKED) when the planner can't produce a valid one."""
    draft = await _draft(session, view, task, epoch, None)
    if draft is None:
        await _blocked(session, view, task, "couldn't make a valid plan", "item_failed")
        return False
    task.plan = _stored(draft, 1, 0)
    await session.commit()
    return True


async def append(
    session: AsyncSession,
    view: AgentView,
    task: RunTask,
    *,
    reason: str,
    new_info: str,
    epoch: int,
    supersede: Sequence[str] = (),
) -> list[str]:
    """Adds items after the existing ones; `supersede` items point at their replacements."""
    if task.plan_appends >= get_settings().plan_append_cap:
        await _blocked(session, view, task, "the plan was changed too many times", "plan_cap")
        raise CapHit
    draft = await _draft(session, view, task, epoch, f"{reason}\n{new_info}")
    if draft is None:
        await _blocked(session, view, task, "couldn't extend the plan", "item_failed")
        raise CapHit
    added = _stored(draft, len(task.plan) + 1, task.plan_appends + 1)
    new_ids = [i["id"] for i in added]
    task.plan = [
        {**i, "status": "SUPERSEDED", "superseded_by": new_ids, "reason": reason}
        if i["id"] in supersede
        else i
        for i in task.plan
    ] + added
    task.plan_appends += 1
    await session.commit()
    return new_ids
