"""Slack button clicks (CHANNELS_SPEC §4.2): action ids are `lucia:<type>:<id>:<value>`."""

import json
import uuid
from typing import Any
from urllib.parse import parse_qs

from fastapi import Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.api.tags import api_router
from lucia.auth.deps import DbSession
from lucia.connectors import slack
from lucia.connectors.slack_ingest import connection
from lucia.conversations import service as conversations
from lucia.conversations.schemas import ActionIn
from lucia.core.errors import ProblemError, not_found
from lucia.db.models import Conversation, Message, StepResult
from lucia.harness.answers import answer

router = api_router("hooks", "/hooks", public=True)


@router.post("/slack/interactive", summary="Slack button clicks", operation_id="slackInteractive")
async def slack_interactive(
    request: Request,
    session: DbSession,
    x_slack_request_timestamp: str = Header(default=""),
    x_slack_signature: str = Header(default=""),
) -> dict[str, bool]:
    body = await request.body()
    if not slack.verify_signature(body, x_slack_request_timestamp, x_slack_signature):
        raise ProblemError(401, "Invalid signature")
    payload: dict[str, Any] = json.loads(parse_qs(body.decode()).get("payload", ["{}"])[0])
    conn = await connection(session, str((payload.get("team") or {}).get("id", "")))
    if conn is None:
        return {"ok": True}  # not a workspace we serve
    firm_id, user = conn.firm_id, str((payload.get("user") or {}).get("id", ""))
    for action in payload.get("actions") or []:
        parts = str(action.get("action_id", "")).split(":")
        if len(parts) < 3 or parts[0] != "lucia":
            continue
        try:
            await _act(session, firm_id, parts[1], uuid.UUID(parts[2]), action.get("value"), user)
        except (ValueError, ProblemError):
            await session.rollback()  # a stale or malformed button: Slack only needs the ack
    return {"ok": True}


async def _act(
    session: AsyncSession,
    firm_id: uuid.UUID,
    kind: str,
    target: uuid.UUID,
    value: str | None,
    user: str,
) -> None:
    """One click, only on this workspace's firm's rows."""
    if kind == "answer":
        item = await session.get(StepResult, target)
        if item is None or item.firm_id != firm_id:
            raise not_found("Attention item")
        await answer(session, target, choice=value, text=None, answered_by={"slack_user_id": user})
        return
    msg = await session.get(Message, target)
    if msg is None or msg.firm_id != firm_id:
        raise not_found("Message")
    conv = await session.get_one(Conversation, msg.conversation_id)
    action = ActionIn.model_validate({"type": kind, "value": value, "message_id": target})
    await conversations.apply_action(session, conv, action)
