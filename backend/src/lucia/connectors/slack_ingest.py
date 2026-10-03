"""Slack messages into conversations (CHANNELS_SPEC §4.1): a top-level @mention starts a
thread conversation; replies in that thread continue it. One firm per workspace (D42)."""

import logging
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.connectors import slack
from lucia.connectors.base import ConnectorError
from lucia.core.clock import get_clock
from lucia.core.security import decrypt_json
from lucia.db.models import ConnectorConnection, Conversation, Message
from lucia.worker.dispatch import send

log = logging.getLogger(__name__)


def thread_ref(team: str, channel: str, ts: str) -> str:
    return f"slack:{team}:{channel}:{ts}"


def split_ref(ref: str) -> tuple[str, str, str]:
    _, team, channel, ts = ref.split(":", 3)
    return team, channel, ts


async def connection(session: AsyncSession, team: str) -> ConnectorConnection | None:
    return await session.scalar(
        select(ConnectorConnection).where(
            ConnectorConnection.connector == "slack",
            ConnectorConnection.status == "connected",
            ConnectorConnection.config["team_id"].astext == team,
        )
    )


def token(conn: ConnectorConnection) -> str:
    return decrypt_json(conn.encrypted_secrets)["bot_token"]


async def ingest_event(session: AsyncSession, team: str, event: dict[str, Any]) -> uuid.UUID | None:
    if (
        event.get("type") not in ("app_mention", "message")
        or event.get("bot_id")
        or event.get("subtype")
    ):
        return None
    conn = await connection(session, team)
    if conn is None or event.get("user") == conn.config.get("bot_user_id"):
        return None
    channel, ts = str(event.get("channel", "")), str(event.get("ts", ""))
    root = str(event.get("thread_ts") or ts)
    ref = thread_ref(team, channel, root)
    conv = await session.scalar(
        select(Conversation).where(
            Conversation.firm_id == conn.firm_id, Conversation.external_thread_ref == ref
        )
    )
    if conv is None:
        if event["type"] != "app_mention" or event.get("thread_ts"):
            return None  # only a top-level mention starts a conversation
        conv = Conversation(firm_id=conn.firm_id, channel="slack", external_thread_ref=ref)
        session.add(conv)
        await session.flush()
    text = re.sub(
        rf"<@{re.escape(str(conn.config.get('bot_user_id')))}>\s*", "", str(event.get("text", ""))
    ).strip()
    user = str(event.get("user", ""))
    message_id = await session.scalar(
        insert(Message)
        .values(
            firm_id=conn.firm_id,
            conversation_id=conv.id,
            direction="inbound",
            actor="human",
            external_author={"slack_user_id": user},
            body=text,
            status="received",
            external_ref=ts,
            dedup_key=f"slack:{team}:{channel}:{ts}",
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(Message.id)
    )
    conv.last_message_at = get_clock().now()
    await session.commit()
    if message_id is None:
        return None
    send("orchestrator.handle_message", message_id)
    send("connectors.slack_ack", message_id)
    send("conversations.title" if conv.title is None else "conversations.summarize", conv.id)
    return message_id


async def acknowledge(session: AsyncSession, message_id: uuid.UUID) -> None:
    """Off the 3-second ack path: the author's display name, and an eyes reaction as receipt."""
    msg = await session.get_one(Message, message_id)
    conv = await session.get_one(Conversation, msg.conversation_id)
    assert conv.external_thread_ref and msg.external_author and msg.external_ref
    team, channel, _ = split_ref(conv.external_thread_ref)
    conn = await connection(session, team)
    if conn is None:
        return
    bot, user = token(conn), msg.external_author["slack_user_id"]
    try:
        name = await slack.user_name(bot, user)
    except ConnectorError:
        name = user
    msg.external_author = {**msg.external_author, "display_name": name}
    await session.commit()
    try:
        await slack.add_reaction(bot, channel, msg.external_ref)
    except ConnectorError:
        log.warning("couldn't add the eyes reaction")
