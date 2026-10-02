"""Per-role LLM packets (RUNTIME_SPEC §10): each role sees only the sections it needs, in a
fixed order, trimmed to a budget (journal and episodes go first)."""

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import (
    AgentRun,
    ContactPoint,
    Conversation,
    Episode,
    Message,
    RunTask,
    StepResult,
    Subject,
    SubjectContact,
)

ROLE_SECTIONS: dict[str, tuple[str, ...]] = {
    "triage": (
        "system_prompt",
        "goal",
        "subject",
        "timeline",
        "tasks",
        "kinds",
        "episodes",
        "journal",
        "conversation",
        "trigger",
    ),
    "planner": (
        "system_prompt",
        "goal",
        "subject",
        "timeline",
        "task",
        "dependencies",
        "plan",
        "attempts",
        "episodes",
        "journal",
        "policies",
        "tools",
        "trigger",
    ),
    "relevance": ("task", "plan", "attempts", "trigger"),
    "executor": ("system_prompt", "subject", "task", "item", "inputs", "attempts", "policies"),
    "completion": ("system_prompt", "goal", "timeline", "tasks", "episodes", "journal"),
    "summarizer": ("task", "item", "trigger"),
}
TRIM_ORDER = ("journal", "episodes", "attempts", "timeline")
BUDGET_CHARS = 24_000 * 4  # ~24k tokens at ~4 characters per token


def _render(name: str, value: Any) -> str:
    body = value if isinstance(value, str) else json.dumps(value, default=str, indent=1)
    return f"## {name}\n{body}"


def packet(role: str, sections: dict[str, Any]) -> str:
    present = {n: sections[n] for n in ROLE_SECTIONS[role] if sections.get(n) not in (None, "")}
    for name in TRIM_ORDER:
        if sum(len(_render(n, v)) for n, v in present.items()) <= BUDGET_CHARS:
            break
        present.pop(name, None)
    return "\n\n".join(_render(n, v) for n, v in present.items())


# --- section builders (shared by every role) ------------------------------------------------


async def subject_snapshot(session: AsyncSession, subject: Subject) -> dict[str, Any]:
    rows = await session.execute(
        select(SubjectContact, ContactPoint)
        .join(ContactPoint, ContactPoint.id == SubjectContact.contact_point_id)
        .where(SubjectContact.subject_id == subject.id)
        .order_by(SubjectContact.alias_ordinal)
    )
    return {
        "title": subject.title,
        "kind": subject.kind,
        "external_ref": subject.external_ref,
        "description": subject.description,
        "contacts": [
            {
                "contact_id": str(link.id),
                "name": cp.name,
                "role": link.role,
                "phones": [p["e164"] for p in cp.phones if p.get("type") == "voice"],
                "emails": cp.emails,
                "timezone": cp.tz,
                "consent": {ch: v.get("status") for ch, v in link.consent.items()},
                "opted_out": sorted(cp.opt_out),
            }
            for link, cp in rows.all()
        ],
    }


async def timeline(session: AsyncSession, subject_id: uuid.UUID, limit: int = 20) -> list[str]:
    """Findings from every agent on the subject, newest last (D31)."""
    rows = await session.scalars(
        select(StepResult.summary)
        .join(AgentRun, AgentRun.id == StepResult.run_id)
        .where(AgentRun.subject_id == subject_id, StepResult.type == "finding")
        .order_by(StepResult.created_at.desc())
        .limit(limit)
    )
    return list(reversed(list(rows)))


async def tasks_overview(session: AsyncSession, run_id: uuid.UUID) -> list[dict[str, Any]]:
    tasks = await session.scalars(
        select(RunTask).where(RunTask.run_id == run_id).order_by(RunTask.created_at)
    )
    return [
        {
            "task_id": str(t.id),
            "key": t.key,
            "kind": t.kind,
            "title": t.title,
            "goal": t.goal,
            "status": t.status,
            "output": (t.output or {}).get("summary"),
            "evidence_step_ids": (t.output or {}).get("evidence_step_ids", []),
        }
        for t in tasks
    ]


async def episodes_timeline(session: AsyncSession, run_id: uuid.UUID, limit: int = 20) -> list[str]:
    rows = await session.scalars(
        select(Episode)
        .where(Episode.run_id == run_id)
        .order_by(Episode.created_at.desc())
        .limit(limit)
    )
    return [_episode_line(e) for e in reversed(list(rows))]


def _episode_line(e: Episode) -> str:
    line = f"{e.trigger_type}/{e.source}" if e.source else e.trigger_type
    line += f" {e.status}"
    if e.due_at:
        line += f" due {e.due_at.isoformat()}"
    return f"{line} -> {e.outcome}" if e.outcome else line


async def conversation_context(
    session: AsyncSession, conversation_id: str | None
) -> dict[str, Any] | None:
    """The last 20 messages and the rolling summary of older ones (D5)."""
    if not conversation_id:
        return None
    conv = await session.get(Conversation, uuid.UUID(conversation_id))
    if conv is None:
        return None
    rows = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    return {
        "summary": conv.state.get("summary"),
        "messages": [f"{m.actor}: {m.body}" for m in reversed(list(rows))],
    }


async def trigger(session: AsyncSession, episode: Episode) -> dict[str, Any]:
    meta = {k: v for k, v in episode.metadata_.items() if k != "agent_prompt_id"}
    message = None
    if message_id := meta.get("message_id"):
        message = await session.scalar(
            select(Message.body).where(Message.id == uuid.UUID(message_id))
        )
    return {
        "type": episode.trigger_type,
        "source": episode.source,
        "message": message,
        **{k: v for k, v in meta.items() if k not in ("message_id", "conversation_id")},
    }
