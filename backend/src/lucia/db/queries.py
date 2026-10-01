import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.errors import ProblemError, not_found
from lucia.db.models import AgentPrompt


async def get_or_404[T](session: AsyncSession, model: type[T], id_: uuid.UUID, what: str) -> T:
    row = await session.get(model, id_)
    if row is None:
        raise not_found(what)
    return row


def apply_patch(obj: Any, body: BaseModel, *, exclude: set[str] | None = None) -> None:
    """Copy the fields a PATCH body set (nulls mean "unchanged") onto an ORM row."""
    for key, value in body.model_dump(exclude_none=True, exclude=exclude).items():
        setattr(obj, key, value)


async def latest_active_version(session: AsyncSession, agent_id: uuid.UUID) -> AgentPrompt | None:
    return await session.scalar(
        select(AgentPrompt)
        .where(AgentPrompt.agent_id == agent_id, AgentPrompt.status == "active")
        .order_by(AgentPrompt.version.desc())
        .limit(1)
    )


def like_pattern(q: str) -> str:
    """A contains-pattern for ILIKE ... ESCAPE '\\' that treats % and _ literally."""
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@asynccontextmanager
async def unique_or(
    session: AsyncSession, constraint: str, error: ProblemError
) -> AsyncIterator[None]:
    """Turn a violation of one unique constraint (e.g. a lost create race) into `error`."""
    try:
        yield
    except IntegrityError as exc:
        # asyncpg's error (the driver error's cause) carries the violated constraint's name.
        if getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None) != constraint:
            raise  # any other integrity error is a bug: let it surface as a 500
        await session.rollback()
        raise error from exc
