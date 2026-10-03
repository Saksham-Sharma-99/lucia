"""Where an attention item (or an urgent finding) goes (CHANNELS_SPEC §6.2, D41): every chat
linked to the run, plus the firm's alert routing for its urgency (in-app bell here; Slack DMs
when the run came from Slack)."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import (
    AgentPrompt,
    AgentRun,
    CompiledAgentFirmMapping,
    Conversation,
    Firm,
    Message,
    Notification,
)
from lucia.harness.links import conversations
from lucia.mappings.resolve import alert_routing
from lucia.notifications.updates import post_run_update


async def _channels(session: AsyncSession, run: AgentRun, urgency: str) -> list[str]:
    config = (await session.get_one(AgentPrompt, run.agent_prompt_id)).config
    firm = await session.get_one(Firm, run.firm_id)
    mapping = await session.get_one(CompiledAgentFirmMapping, run.mapping_id)
    routes = alert_routing(config, firm.settings.get("alert_routing", {}), mapping.overrides)
    return next((r.channels for r in routes if r.urgency == urgency), [])


async def _people(session: AsyncSession, run: AgentRun) -> tuple[set[str], set[str]]:
    """App users and Slack users who asked for work on this run."""
    linked = [c.id for c in await conversations(session, run.id)]
    rows = await session.execute(
        select(Message.author_user_id, Message.external_author)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.conversation_id.in_(linked), Message.actor == "human")
    )
    users, slack = set[str](), set[str]()
    for user_id, external in rows.all():
        if user_id:
            users.add(str(user_id))
        if external and external.get("slack_user_id"):
            slack.add(external["slack_user_id"])
    return users, slack


async def notify(
    session: AsyncSession,
    run: AgentRun,
    item_id: uuid.UUID,
    *,
    kind: str,
    summary: str,
    urgency: str,
    options: list[dict[str, Any]],
) -> None:
    """Called once per new item, inside the caller's transaction."""
    block = {
        "type": "attention",
        "step_result_id": str(item_id),
        "kind": kind,
        "options": options,
        "free_text": True,
    }
    if kind == "confirm_completion":
        block = {"type": "run_confirm", "run_id": str(run.id), "step_result_id": str(item_id)}
    elif kind == "finding":  # a report to read, not a question to answer
        block = {"type": "finding", "step_result_id": str(item_id), "urgency": urgency}
    await post_run_update(session, run, body=summary, source_id=f"sr:{item_id}", blocks=[block])
    channels = await _channels(session, run, urgency)
    users, slack = await _people(session, run)
    targets = [("in_app", u) for u in users if "in_app" in channels]
    targets += [("slack_dm", s) for s in slack if "slack_dm" in channels]
    for channel, target in targets:
        await session.execute(
            insert(Notification)
            .values(
                firm_id=run.firm_id,
                step_result_id=item_id,
                run_id=run.id,
                channel=channel,
                target=target,
                status="sent" if channel == "in_app" else "queued",
            )
            .on_conflict_do_nothing()
        )
