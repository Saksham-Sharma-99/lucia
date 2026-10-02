"""Agent updates posted into every conversation linked to a run (D40)."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.conversations.events import publish
from lucia.db.models import AgentRun, Message
from lucia.harness.links import conversations


async def post_run_update(
    session: AsyncSession,
    run: AgentRun,
    *,
    body: str,
    source_id: str,
    blocks: Sequence[dict[str, Any]] = (),
) -> None:
    """Idempotent per (run, source, conversation); the caller commits. The browser is told
    right away; it refetches if it races the commit."""
    for conv in await conversations(session, run.id):
        message_id = await session.scalar(
            insert(Message)
            .values(
                firm_id=run.firm_id,
                conversation_id=conv.id,
                direction="outbound",
                actor="agent",
                agent_id=run.agent_id,
                run_id=run.id,
                body=body,
                blocks=list(blocks),
                status="queued"
                if conv.channel == "slack"
                else "sent",  # Slack: the beat sweep sends it
                dedup_key=f"update:{run.id}:{source_id}:{conv.id}",
            )
            .on_conflict_do_nothing(index_elements=["dedup_key"])
            .returning(Message.id)
        )
        if message_id is not None:
            await publish(conv.id, "message.updated", {"message_id": str(message_id)})
