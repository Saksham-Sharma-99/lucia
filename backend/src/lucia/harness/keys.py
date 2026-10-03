"""Task identity: `slug(kind):canonical(target)`, built by the harness, never by the model
(DATA_MODEL §4.4), so the same work always lands on the same task."""

import re
import unicodedata
import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import AgentRun, RunTask
from lucia.db.models.run import TERMINAL_TASK

KIND_LIMIT = 40
SIMILAR = 0.8


class TargetRef(BaseModel):
    type: Literal["contact", "document", "period", "external", "run"]
    ref: str | None


def slug(text: str, limit: int = KIND_LIMIT) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:limit]


def canonical_target(target: TargetRef) -> str:
    ref = target.ref or ""
    match target.type:
        case "run":
            return "run"
        case "contact":
            return f"contact-{ref[:8]}"
        case "document":
            return f"doc-{slug(ref, 60)}"
        case "period":
            return slug(ref, 20)
        case "external":
            return f"ext-{slug(ref.replace(':', ' '), 60)}"


def task_key(kind: str, target: TargetRef) -> str:
    k = slug(kind)
    if not k:
        raise ValueError(f"task kind {kind!r} has no letters or digits")
    return f"{k}:{canonical_target(target)}"


async def kind_vocabulary(session: AsyncSession, run: AgentRun, limit: int = 30) -> list[str]:
    """The kinds this agent version has used at this firm (this run included), most frequent
    first, so triage reuses a kind instead of inventing a near-synonym."""
    rows = await session.execute(
        select(RunTask.kind, func.count())
        .join(AgentRun, AgentRun.id == RunTask.run_id)
        .where(AgentRun.agent_prompt_id == run.agent_prompt_id, AgentRun.firm_id == run.firm_id)
        .group_by(RunTask.kind)
        .order_by(func.count().desc())
        .limit(limit)
    )
    return [kind for kind, _ in rows.all()]


async def similar_open_task(session: AsyncSession, run_id: uuid.UUID, key: str) -> RunTask | None:
    score = func.similarity(RunTask.key, key)
    return await session.scalar(
        select(RunTask)
        .where(
            RunTask.run_id == run_id,
            RunTask.status.not_in(TERMINAL_TASK),
            RunTask.key != key,
            score >= SIMILAR,
        )
        .order_by(score.desc())
        .limit(1)
    )
