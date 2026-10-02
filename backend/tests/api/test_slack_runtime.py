import json
import time
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import respx
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.connectors.service import set_secrets
from lucia.connectors.slack_ingest import acknowledge
from lucia.core.clock import FrozenClock
from lucia.db.models import (
    ConnectorConnection,
    Conversation,
    Episode,
    Message,
    Notification,
    StepResult,
)
from lucia.notifications.deliver import deliver_message, deliver_notification, deliver_pending
from tests.slack_fakes import replies
from tests.unit.test_slack_signature import sign
from tests.world import World, make_leased_run, make_world

API = "https://slack.com/api"


async def _slack_conn(db: AsyncSession, w: World) -> ConnectorConnection:
    conn = ConnectorConnection(
        firm_id=w.firm.id,
        connector="slack",
        label="Slack",
        status="connected",
        config={"team_id": "T1", "team_name": "Smith", "bot_user_id": "UBOT"},
    )
    set_secrets(conn, {"bot_token": "xoxb-test"})
    db.add(conn)
    await db.commit()
    return conn


async def _event(client: AsyncClient, event: dict[str, Any], team: str = "T1") -> Response:
    body = json.dumps({"type": "event_callback", "team_id": team, "event": event}).encode()
    ts = str(int(time.time()))
    return await client.post(
        "/api/v1/hooks/slack",
        content=body,
        headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sign(body, ts)},
    )


def _mention(ts: str = "100.1", **kw: Any) -> dict[str, Any]:
    return {
        "type": "app_mention",
        "user": "UJANE",
        "text": "<@UBOT> @checkin call Jane",
        "channel": "C1",
        "ts": ts,
        **kw,
    }


@respx.mock
async def test_top_level_mention_starts_a_conversation(
    client: AsyncClient, db: AsyncSession, sent: list[Any]
) -> None:
    w = await make_world(db)
    await _slack_conn(db, w)
    react = respx.post(f"{API}/reactions.add").mock(return_value=Response(200, json={"ok": True}))
    who = respx.get(f"{API}/users.info").mock(
        return_value=Response(200, json={"ok": True, "user": {"real_name": "Priya"}})
    )
    assert (await _event(client, _mention())).status_code == 200
    assert not (react.called or who.called), "Slack wants the ack within 3s: no calls inline"
    conv = await db.scalar(select(Conversation))
    assert conv is not None and (conv.channel, conv.external_thread_ref) == (
        "slack",
        "slack:T1:C1:100.1",
    )
    msg = await db.scalar(select(Message))
    assert msg is not None and msg.body == "@checkin call Jane"
    assert ("orchestrator.handle_message", (str(msg.id),)) in sent
    assert ("connectors.slack_ack", (str(msg.id),)) in sent
    await acknowledge(db, msg.id)
    await db.refresh(msg)
    assert msg.external_author == {"slack_user_id": "UJANE", "display_name": "Priya"}
    assert react.called


@respx.mock
async def test_thread_replies_join_the_conversation_and_replays_are_ignored(
    client: AsyncClient, db: AsyncSession
) -> None:
    w = await make_world(db)
    await _slack_conn(db, w)
    await _event(client, _mention())
    reply = {
        "type": "message",
        "user": "UJANE",
        "text": "also ask about PT",
        "channel": "C1",
        "ts": "100.2",
        "thread_ts": "100.1",
    }
    await _event(client, reply)
    await _event(client, reply)
    assert len(list(await db.scalars(select(Message)))) == 2
    assert len(list(await db.scalars(select(Conversation)))) == 1


@respx.mock
async def test_unrelated_and_bot_messages_are_ignored(
    client: AsyncClient, db: AsyncSession
) -> None:
    w = await make_world(db)
    await _slack_conn(db, w)
    await _event(
        client, {"type": "message", "user": "UJANE", "text": "hi", "channel": "C1", "ts": "1.1"}
    )
    await _event(
        client,
        {
            "type": "message",
            "user": "UJANE",
            "text": "x",
            "channel": "C1",
            "ts": "1.3",
            "thread_ts": "9.9",
        },
    )
    await _event(client, _mention(ts="1.2", bot_id="B1"))
    await _event(client, _mention(ts="1.4"), team="TOTHER")
    assert await db.scalar(select(Message)) is None


async def _slack_reply(db: AsyncSession, w: World, body: str, **kw: Any) -> Message:
    conv = Conversation(
        firm_id=w.firm.id,
        channel="slack",
        external_thread_ref="slack:T1:C1:100.1",
        subject_id=w.subject.id,
    )
    db.add(conv)
    await db.flush()
    msg = Message(
        firm_id=w.firm.id,
        conversation_id=conv.id,
        direction="outbound",
        body=body,
        status="queued",
        **{"actor": "system", **kw},
    )
    db.add(msg)
    await db.commit()
    return msg


@respx.mock
async def test_replies_post_into_the_thread_once(db: AsyncSession) -> None:
    w = await make_world(db)
    await _slack_conn(db, w)
    msg = await _slack_reply(db, w, "Started @checkin on Doe v. Acme Trucking.")
    post = respx.post(f"{API}/chat.postMessage").mock(
        return_value=Response(200, json={"ok": True, "ts": "100.5"})
    )
    await deliver_message(db, msg.id)
    await deliver_message(db, msg.id)
    body = json.loads(post.calls[0].request.content)
    assert post.call_count == 1 and (body["channel"], body["thread_ts"]) == ("C1", "100.1")
    assert body["metadata"]["event_payload"] == {"message_id": str(msg.id)}
    await db.refresh(msg)
    assert (msg.status, msg.external_ref) == ("sent", "100.5")


@respx.mock
async def test_a_message_another_worker_is_sending_is_left_alone(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    await _slack_conn(db, w)
    msg = await _slack_reply(db, w, "Started @checkin.")
    msg.external_ref = f"sending:{clock.now().isoformat()}"
    await db.commit()
    post = respx.post(f"{API}/chat.postMessage").mock(
        return_value=Response(200, json={"ok": True, "ts": "100.5"})
    )
    await deliver_message(db, msg.id)
    assert post.call_count == 0


@respx.mock
async def test_a_stale_send_finds_its_earlier_post_instead_of_posting_again(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    await _slack_conn(db, w)
    msg = await _slack_reply(db, w, "Started @checkin.")
    msg.external_ref = f"sending:{(clock.now() - timedelta(minutes=5)).isoformat()}"
    await db.commit()
    replies({"ts": "100.7", "metadata": {"event_payload": {"message_id": str(msg.id)}}})
    post = respx.post(f"{API}/chat.postMessage").mock(
        return_value=Response(200, json={"ok": True, "ts": "100.8"})
    )
    await deliver_message(db, msg.id)
    await db.refresh(msg)
    assert post.call_count == 0 and (msg.status, msg.external_ref) == ("sent", "100.7")


@respx.mock
async def test_a_slack_timeout_is_a_connector_error_and_the_sweep_carries_on(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    await _slack_conn(db, w)
    msg = await _slack_reply(db, w, "Started @checkin.")
    respx.post(f"{API}/chat.postMessage").mock(side_effect=httpx.ReadTimeout("slow"))
    assert await deliver_pending(db) == 1
    await db.refresh(msg)
    assert msg.status == "queued", "left for the next sweep, which checks the thread first"


@respx.mock
async def test_agent_text_naming_a_contact_is_replaced_for_slack(db: AsyncSession) -> None:
    w = await make_world(db)
    await _slack_conn(db, w)
    run = await make_leased_run(db, w)
    msg = await _slack_reply(
        db,
        w,
        "Called Jane Doe: she was in the ER last week.",
        actor="agent",
        run_id=run.id,
        agent_id=w.agent.id,
    )
    post = respx.post(f"{API}/chat.postMessage").mock(
        return_value=Response(200, json={"ok": True, "ts": "1"})
    )
    await deliver_message(db, msg.id)
    text = json.loads(post.calls[0].request.content)["text"]
    assert "Jane" not in text and "ER" not in text and "Open Lucia" in text


@respx.mock
async def test_slack_dm_notifications(db: AsyncSession, clock: FrozenClock) -> None:
    w = await make_world(db)
    await _slack_conn(db, w)
    run = await make_leased_run(db, w)
    item = StepResult(
        firm_id=w.firm.id,
        run_id=run.id,
        type="attention",
        kind="question",
        urgency="P1",
        summary="Call Jane Doe on which number?",
        summary_public="x",
        status="open",
        dedup_key="sr:dm",
    )
    db.add(item)
    await db.flush()
    note = Notification(
        firm_id=w.firm.id,
        step_result_id=item.id,
        run_id=run.id,
        channel="slack_dm",
        target="UPRIYA",
        status="queued",
    )
    db.add(note)
    await db.commit()
    respx.post(f"{API}/conversations.open").mock(
        return_value=Response(200, json={"ok": True, "channel": {"id": "D1"}})
    )
    post = respx.post(f"{API}/chat.postMessage").mock(
        return_value=Response(200, json={"ok": True, "ts": "9"})
    )
    await deliver_notification(db, note.id)
    await deliver_notification(db, note.id)
    sent_text = json.loads(post.calls[0].request.content)["text"]
    assert "Jane" not in sent_text and "@checkin needs your input" in sent_text
    await db.refresh(note)
    assert note.status == "sent" and post.call_count == 1
    note.status, note.external_ref = "queued", f"sending:{clock.now().isoformat()}"
    await db.commit()
    await deliver_notification(db, note.id)  # another worker holds the send
    assert post.call_count == 1


@respx.mock
async def test_a_dm_that_may_have_arrived_is_not_sent_again(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    await _slack_conn(db, w)
    run = await make_leased_run(db, w)
    item = StepResult(
        firm_id=w.firm.id,
        run_id=run.id,
        type="attention",
        kind="question",
        urgency="P1",
        summary="q",
        summary_public="q",
        status="open",
        dedup_key="sr:dm2",
    )
    db.add(item)
    await db.flush()
    note = Notification(
        firm_id=w.firm.id,
        step_result_id=item.id,
        run_id=run.id,
        channel="slack_dm",
        target="UPRIYA",
        status="queued",
    )
    db.add(note)
    await db.commit()
    respx.post(f"{API}/conversations.open").mock(
        return_value=Response(200, json={"ok": True, "channel": {"id": "D1"}})
    )
    respx.post(f"{API}/chat.postMessage").mock(side_effect=httpx.ReadTimeout("slow"))
    await deliver_notification(db, note.id)
    await db.refresh(note)
    assert (note.status, note.external_ref) == ("sent", "unconfirmed")


async def _interactive(client: AsyncClient, payload: dict[str, Any]) -> Response:
    body = urlencode({"payload": json.dumps(payload)}).encode()
    ts = str(int(time.time()))
    return await client.post(
        "/api/v1/hooks/slack/interactive",
        content=body,
        headers={
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sign(body, ts),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )


async def _question(db: AsyncSession, w: World) -> StepResult:
    run = await make_leased_run(db, w)
    item = StepResult(
        firm_id=w.firm.id,
        run_id=run.id,
        type="attention",
        kind="question",
        urgency="P1",
        summary="q",
        summary_public="q",
        status="open",
        dedup_key="sr:btn",
        options=[{"value": "mobile", "label": "Mobile"}],
    )
    db.add(item)
    await db.commit()
    return item


def _click(action_id: str, team: str = "T1") -> dict[str, Any]:
    return {
        "type": "block_actions",
        "team": {"id": team},
        "user": {"id": "UPRIYA"},
        "actions": [{"action_id": action_id, "value": "mobile"}],
    }


async def test_buttons_answer_attention_as_the_slack_user(
    client: AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    await _slack_conn(db, w)
    item = await _question(db, w)
    assert (await _interactive(client, _click(f"lucia:answer:{item.id}"))).status_code == 200
    await db.refresh(item)
    assert (item.status, item.answered_by) == ("answered", {"slack_user_id": "UPRIYA"})
    assert await db.scalar(select(Episode.trigger_type)) == "user_response"
    again = await _interactive(client, _click(f"lucia:answer:{item.id}"))
    assert again.status_code == 200, "a second click on a stale button is not an error to Slack"


async def test_malformed_and_foreign_clicks_change_nothing(
    client: AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    await _slack_conn(db, w)
    item = await _question(db, w)
    stale_then_good = _click(f"lucia:answer:{uuid.uuid4()}")
    stale_then_good["actions"].append({"action_id": f"lucia:answer:{item.id}", "value": "mobile"})
    assert (await _interactive(client, stale_then_good)).status_code == 200
    await db.refresh(item)
    assert item.status == "answered", "one stale button doesn't drop the next action"
    item.status = "open"
    await db.commit()
    for click in (
        _click("lucia:answer:not-a-uuid"),
        _click(f"lucia:subject_pick:{uuid.uuid4()}"),
        _click(f"lucia:answer:{item.id}", team="TOTHER"),
    ):
        assert (await _interactive(client, click)).status_code == 200
    await db.refresh(item)
    assert item.status == "open"


async def test_unsigned_interactive_is_401(client: AsyncClient) -> None:
    body = urlencode({"payload": "{}"}).encode()
    resp = await client.post(
        "/api/v1/hooks/slack/interactive",
        content=body,
        headers={"X-Slack-Request-Timestamp": str(int(time.time())), "X-Slack-Signature": "v0=x"},
    )
    assert resp.status_code == 401
