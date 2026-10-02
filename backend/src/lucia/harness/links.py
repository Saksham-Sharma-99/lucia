"""Which conversations a run is linked to: the ones its Episodes came from (CHANNELS_SPEC §3.3)."""

import uuid

from sqlalchemy import Select, String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import Conversation, Episode


async def conversations(session: AsyncSession, run_id: uuid.UUID) -> list[Conversation]:
    linked = select(Episode.metadata_["conversation_id"].astext).where(Episode.run_id == run_id)
    return list(
        await session.scalars(
            select(Conversation)
            .where(cast(Conversation.id, String).in_(linked))
            .order_by(Conversation.id)
        )
    )


def run_ids_for_conversation(conversation_id: uuid.UUID) -> Select[uuid.UUID]:
    return select(Episode.run_id).where(
        Episode.metadata_["conversation_id"].astext == str(conversation_id)
    )
