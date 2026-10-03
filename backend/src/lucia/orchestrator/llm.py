"""The orchestrator's model calls: no run exists yet, so each is audited instead of being a step."""

import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.audit import audit
from lucia.core.config import get_settings
from lucia.llm.client import get_llm


async def ask[T: BaseModel](
    session: AsyncSession,
    firm_id: uuid.UUID,
    role: str,
    instructions: str,
    message: str,
    output: type[T],
) -> T:
    out, usage = await get_llm().structured(
        role=role,
        model=get_settings().orchestrator_model,
        instructions=instructions,
        message=message,
        output_type=output,
        seconds=10,
    )
    await audit(
        session,
        action="orchestrator.llm",
        entity_type="firm",
        entity_id=firm_id,
        firm_id=firm_id,
        data={
            "role": role,
            "model": usage.model,
            "latency_ms": usage.latency_ms,
            "tokens": usage.input_tokens + usage.output_tokens,
        },
    )
    return out


async def say(
    session: AsyncSession, firm_id: uuid.UUID, role: str, instructions: str, message: str
) -> str:
    text, _ = await get_llm().text(
        role=role,
        model=get_settings().orchestrator_model,
        instructions=instructions,
        message=message,
        seconds=10,
    )
    return text
