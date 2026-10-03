import json
from typing import Any

import respx
from httpx import Response
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.connectors.service import set_secrets
from lucia.core.clock import FrozenClock
from lucia.db.models import ConnectorConnection, Conversation, Episode
from lucia.harness.agent_view import load
from lucia.harness.tools.base import ToolContext
from lucia.harness.tools.slack_tool import read_thread, send_message
from tests.slack_fakes import replies
from tests.world import VOICE_CONFIG, item, make_leased_run, make_task, make_world

API = "https://slack.com/api"
SLACK = {
    **VOICE_CONFIG,
    "capabilities": [
        *VOICE_CONFIG["capabilities"],
        {"connector": "slack", "tools": ["slack.send_message", "slack.read_thread"]},
    ],
}


async def _ctx(db: AsyncSession, linked: bool = True) -> ToolContext:
    w = await make_world(db, config=SLACK)
    conn = ConnectorConnection(
        firm_id=w.firm.id,
        connector="slack",
        label="S",
        status="connected",
        config={"team_id": "T1", "bot_user_id": "UBOT"},
    )
    set_secrets(conn, {"bot_token": "xoxb"})
    db.add(conn)
    run = await make_leased_run(db, w)
    if linked:
        conv = Conversation(
            firm_id=w.firm.id, channel="slack", external_thread_ref="slack:T1:C1:100.1"
        )
        db.add(conv)
        await db.flush()
        db.add(
            Episode(
                firm_id=w.firm.id,
                run_id=run.id,
                trigger_type="user_input",
                status="completed",
                dedup_key="msg:s",
                metadata_={"conversation_id": str(conv.id)},
            )
        )
    task = await make_task(
        db, w, run, plan=[item(1, "tool", tool="slack.send_message", status="RUNNING", attempts=1)]
    )
    return ToolContext(db, await load(db, run), task, task.plan[0], 1)


@respx.mock
async def test_send_message_posts_in_the_runs_thread(db: AsyncSession, clock: FrozenClock) -> None:
    ctx = await _ctx(db)
    replies()
    post = respx.post(f"{API}/chat.postMessage").mock(
        return_value=Response(200, json={"ok": True, "ts": "7"})
    )
    result = await send_message(ctx, {"text": "The call went well."})
    body: dict[str, Any] = json.loads(post.calls[0].request.content)
    assert result.status == "SUCCEEDED" and (body["channel"], body["thread_ts"]) == ("C1", "100.1")
    assert body["metadata"]["event_payload"] == {"message_id": f"{ctx.task.id}:{ctx.item['id']}"}


@respx.mock
async def test_a_retry_finds_the_items_earlier_post_instead_of_posting_again(
    db: AsyncSession, clock: FrozenClock
) -> None:
    ctx = await _ctx(db)
    key = f"{ctx.task.id}:{ctx.item['id']}"
    replies({"ts": "7", "metadata": {"event_payload": {"message_id": key}}})
    post = respx.post(f"{API}/chat.postMessage")
    result = await send_message(ctx, {"text": "The call went well (reworded)."})
    assert (result.status, result.output) == ("SUCCEEDED", {"ts": "7"}) and not post.called


@respx.mock
async def test_slack_errors_fail_the_item_instead_of_the_worker(
    db: AsyncSession, clock: FrozenClock
) -> None:
    ctx = await _ctx(db)
    respx.get(f"{API}/conversations.replies").mock(
        return_value=Response(200, json={"ok": False, "error": "ratelimited"})
    )
    for tool in (send_message, read_thread):
        result = await tool(ctx, {"text": "x"})
        assert (result.status, result.retryable) == ("FAILED", True)


async def test_send_message_without_a_slack_thread_fails(
    db: AsyncSession, clock: FrozenClock
) -> None:
    ctx = await _ctx(db, linked=False)
    result = await send_message(ctx, {"text": "x"})
    assert (result.status, result.reason) == ("FAILED", "no_slack_thread")


@respx.mock
async def test_read_thread_returns_redacted_lines(db: AsyncSession, clock: FrozenClock) -> None:
    ctx = await _ctx(db)
    respx.get(f"{API}/conversations.replies").mock(
        return_value=Response(
            200,
            json={
                "ok": True,
                "messages": [
                    {"user": "UJANE", "text": "her SSN is 123-45-6789", "ts": "1"},
                    {"bot_id": "B", "text": "ok", "ts": "2"},
                ],
            },
        )
    )
    result = await read_thread(ctx, {})
    assert result.output == {"messages": ["UJANE: her SSN is [SSN]", "bot: ok"]}
