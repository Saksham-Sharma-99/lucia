"""Chat housekeeping with a small model: a title after the first message, and a rolling
summary of messages older than the last 20 (ORCHESTRATOR_SPEC §9)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.config import get_settings
from lucia.db.models import Conversation, Message
from lucia.llm.client import get_llm

WINDOW = 20
FOLD_AFTER = 10


async def title(session: AsyncSession, conversation_id: uuid.UUID) -> None:
    conv = await session.get_one(Conversation, conversation_id)
    if conv.title:
        return
    first = await session.scalar(
        select(Message.body)
        .where(Message.conversation_id == conv.id, Message.actor == "human")
        .order_by(Message.seq)
        .limit(1)
    )
    if not first:
        return
    text, _ = await get_llm().text(
        role="title",
        model=get_settings().orchestrator_summary_model,
        instructions="Write a 3 to 6 word title for this chat. No quotes.",
        message=first,
    )
    conv.title = text.strip()[:120]
    await session.commit()


async def summarize(session: AsyncSession, conversation_id: uuid.UUID) -> None:
    conv = await session.get_one(Conversation, conversation_id)
    through = conv.state.get("summary_through_seq", 0)
    rows = list(
        await session.scalars(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.seq.desc())
        )
    )
    outside = [m for m in reversed(rows[WINDOW:]) if m.seq > through]
    if len(outside) < FOLD_AFTER:
        return
    text, _ = await get_llm().text(
        role="summary",
        model=get_settings().orchestrator_summary_model,
        instructions="Fold the summary and the messages into one short summary of the chat.",
        message=f"## summary\n{conv.state.get('summary', '')}\n\n## messages\n"
        + "\n".join(f"{m.actor}: {m.body}" for m in outside),
    )
    conv.state = {**conv.state, "summary": text, "summary_through_seq": outside[-1].seq}
    await session.commit()
