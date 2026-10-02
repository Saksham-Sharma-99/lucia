"""An agent's Slack tools act on the Slack thread its run came from (internal, no policy)."""

from typing import Any

from lucia.connectors import slack
from lucia.connectors.base import ConnectorError
from lucia.connectors.slack_ingest import connection, split_ref, token
from lucia.core.redact import redact
from lucia.harness.links import conversations
from lucia.harness.tools.base import ToolContext, ToolResult


async def _thread(ctx: ToolContext) -> tuple[str, str, str] | None:
    linked = await conversations(ctx.session, ctx.view.run.id)
    ref = next((c.external_thread_ref for c in linked if c.channel == "slack"), None)
    if not ref:
        return None
    team, channel, ts = split_ref(ref)
    conn = await connection(ctx.session, team)
    return (token(conn), channel, ts) if conn else None


async def send_message(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    where = await _thread(ctx)
    if where is None:
        return ToolResult(
            status="FAILED", reason="no_slack_thread", summary="This run has no Slack thread"
        )
    bot, channel, ts = where
    key = f"{ctx.task.id}:{ctx.item['id']}"  # one post per item: a retry finds an earlier one
    try:
        since = ctx.task.started_at or ctx.view.run.created_at
        posted = await slack.posted(bot, channel, ts, key, since=since) or await slack.post_message(
            bot, channel, args["text"], thread_ts=ts, message_id=key
        )
    except ConnectorError as e:
        return _slack_failed(e)
    return ToolResult(
        status="SUCCEEDED", summary="Posted in the Slack thread", output={"ts": posted}
    )


async def read_thread(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    where = await _thread(ctx)
    if where is None:
        return ToolResult(
            status="FAILED", reason="no_slack_thread", summary="This run has no Slack thread"
        )
    bot, channel, ts = where
    try:
        messages = await slack.thread(bot, channel, ts)
    except ConnectorError as e:
        return _slack_failed(e)
    lines = [f"{m.get('user') or 'bot'}: {redact(str(m.get('text', '')))}" for m in messages]
    return ToolResult(
        status="SUCCEEDED", summary=f"{len(lines)} messages", output={"messages": lines}
    )


def _slack_failed(e: ConnectorError) -> ToolResult:
    return ToolResult(status="FAILED", retryable=True, reason="slack_error", summary=str(e))
