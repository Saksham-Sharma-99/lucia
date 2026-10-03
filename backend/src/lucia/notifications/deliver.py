"""Sends outbound chat messages to Slack threads and attention items to Slack DMs
(CHANNELS_SPEC §4.2-4.3). Idempotent by message / notification id: a sender first claims the
row (`external_ref = "sending:<at>"`), so a beat sweep and a task never post the same row."""

import uuid
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.connectors import slack
from lucia.connectors.base import ConnectorError, MaybeSent
from lucia.connectors.slack_ingest import connection, split_ref, token
from lucia.core.clock import get_clock
from lucia.db.models import (
    Agent,
    AgentRun,
    ConnectorConnection,
    ContactPoint,
    Conversation,
    Message,
    Notification,
    StepResult,
    Subject,
    SubjectContact,
)
from lucia.notifications.render import check_public, public_text

CLAIM_TTL = timedelta(seconds=60)  # a claim older than this is a sender that died


async def _claim(session: AsyncSession, row: Message | Notification) -> bool | None:
    """None: someone else holds a live claim. Else True if an earlier claim went stale (that
    sender may have posted before dying), False for a first attempt."""
    seen, now = row.external_ref, get_clock().now()
    stale = bool(seen and seen.startswith("sending:"))
    if seen and stale and datetime.fromisoformat(seen[8:]) > now - CLAIM_TTL:
        return None
    model = type(row)
    won = await session.execute(
        update(model)
        .where(
            model.id == row.id,
            model.status == "queued",
            model.external_ref.is_not_distinct_from(seen),
        )
        .values(external_ref=f"sending:{now.isoformat()}")
    )
    await session.commit()
    if not cast(CursorResult[Any], won).rowcount:
        return None
    await session.refresh(row)
    return stale


async def _names(session: AsyncSession, subject_id: uuid.UUID | None) -> list[str]:
    if subject_id is None:
        return []
    return list(
        await session.scalars(
            select(ContactPoint.name)
            .join(SubjectContact, SubjectContact.contact_point_id == ContactPoint.id)
            .where(SubjectContact.subject_id == subject_id)
        )
    )


async def _public(
    session: AsyncSession,
    run_id: uuid.UUID | None,
    kind: str,
    text: str,
    subject_id: uuid.UUID | None,
) -> str:
    """Agent text leaves the app only if it names no contact and carries no identifier."""
    if check_public(text, await _names(session, subject_id)) and kind != "clinical":
        return text
    run = await session.get(AgentRun, run_id) if run_id else None
    handle = (
        await session.scalar(select(Agent.handle).where(Agent.id == run.agent_id))
        if run
        else "lucia"
    )
    title = await session.scalar(select(Subject.title).where(Subject.id == subject_id)) or "a case"
    return public_text(kind=kind, subject=title, agent=handle or "lucia")


def _buttons(blocks: list[dict[str, Any]], conv: Conversation) -> list[dict[str, Any]]:
    pending = (conv.state.get("pending") or {}).get("message_id", "")
    actions: list[dict[str, Any]] = []
    for b in blocks:
        if b["type"] == "attention":
            actions += [
                {
                    "action_id": f"lucia:answer:{b['step_result_id']}:{o['value']}",
                    "text": o["label"],
                    "value": o["value"],
                }
                for o in b["options"]
            ]
        elif b["type"] == "run_confirm":  # to reopen, reply in the thread: a new ask reopens it
            actions.append(
                {
                    "action_id": f"lucia:answer:{b['step_result_id']}:confirm",
                    "text": "Confirm complete",
                    "value": "confirm",
                }
            )
        elif b["type"] == "subject_picker":
            actions += [
                {
                    "action_id": f"lucia:subject_pick:{pending}:{o['subject_id']}",
                    "text": o["title"],
                    "value": o["subject_id"],
                }
                for o in b["options"]
            ]
        elif b["type"] == "agent_suggestion":
            kind = "agent_suggest" if b.get("mentioned") else "clarify_agent"
            actions += [
                {
                    "action_id": f"lucia:{kind}:{pending}:{s['handle']}",
                    "text": f"Use @{s['handle']}",
                    "value": s["handle"],
                }
                for s in b["suggested"]
            ]
        elif b["type"] == "retry":
            actions.append(
                {
                    "action_id": f"lucia:retry:{b['message_id']}:retry",
                    "text": "Retry",
                    "value": "retry",
                }
            )
    if not actions:
        return []
    return [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": a["action_id"],
                    "value": a["value"],
                    "text": {"type": "plain_text", "text": a["text"][:75]},
                }
                for a in actions[:25]
            ],
        }
    ]


async def deliver_message(session: AsyncSession, message_id: uuid.UUID) -> None:
    msg = await session.get_one(Message, message_id)
    conv = await session.get_one(Conversation, msg.conversation_id)
    if msg.status != "queued" or conv.channel != "slack" or not conv.external_thread_ref:
        return
    team, channel, root = split_ref(conv.external_thread_ref)
    conn = await connection(session, team)
    if conn is None:
        msg.status = "failed"
        await session.commit()
        return
    bot = token(conn)
    text = (
        msg.body
        if msg.actor == "system"
        else await _public(session, msg.run_id, "update", msg.body, conv.subject_id)
    )
    retry = await _claim(session, msg)
    if retry is None:
        return
    ts = (
        await slack.posted(bot, channel, root, str(msg.id), since=msg.created_at) if retry else None
    )
    if ts is None:
        ts = await slack.post_message(
            bot,
            channel,
            text,
            thread_ts=root,
            blocks=_buttons(msg.blocks, conv),
            message_id=str(msg.id),
        )
    msg.status, msg.external_ref = "sent", ts
    await session.commit()


async def deliver_notification(session: AsyncSession, notification_id: uuid.UUID) -> None:
    note = await session.get_one(Notification, notification_id)
    if note.status != "queued" or note.channel != "slack_dm":
        return
    item = await session.get_one(StepResult, note.step_result_id)
    run = await session.get_one(AgentRun, note.run_id)
    conn = await session.scalar(
        select(ConnectorConnection).where(
            ConnectorConnection.firm_id == run.firm_id, ConnectorConnection.connector == "slack"
        )
    )
    if conn is None:
        note.status = "failed"
        await session.commit()
        return
    if await _claim(session, note) is None:
        return
    bot = token(conn)
    handle = await session.scalar(select(Agent.handle).where(Agent.id == run.agent_id)) or "lucia"
    title = (
        await session.scalar(select(Subject.title).where(Subject.id == run.subject_id)) or "a case"
    )
    try:
        dm = await slack.open_dm(bot, note.target)
        note.external_ref = await slack.post_message(
            bot, dm, public_text(kind=item.kind, subject=title, agent=handle)
        )
        note.status = "sent"
    except MaybeSent:  # it may have reached them: an alert at most once, never twice
        note.status, note.external_ref = "sent", "unconfirmed"
    except ConnectorError:
        note.attempts, note.external_ref = note.attempts + 1, None  # nothing went out
        note.status = "failed" if note.attempts >= 3 else "queued"
    await session.commit()


async def deliver_pending(session: AsyncSession) -> int:
    """Beat sweep: run updates written inside harness transactions, and queued DMs."""
    messages = list(
        await session.scalars(
            select(Message.id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.status == "queued", Conversation.channel == "slack")
            .limit(100)
        )
    )
    notes = list(
        await session.scalars(
            select(Notification.id)
            .where(Notification.status == "queued", Notification.channel == "slack_dm")
            .limit(100)
        )
    )
    for m in messages:
        try:
            await deliver_message(session, m)
        except ConnectorError:
            await session.rollback()
    for n in notes:
        await deliver_notification(session, n)
    return len(messages) + len(notes)
