import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.config import get_settings
from lucia.core.security import sign_state
from lucia.core.time import utcnow
from lucia.db.models import ConnectorConnection
from tests.factories import ZERO, Json, connected, create_agent, create_firm, pending

SLACK_TOKEN = {
    "ok": True,
    "access_token": "token-1234",
    "bot_user_id": "U1",
    "team": {"id": "T1", "name": "Acme"},
}
VAPI_BODY = {"connector": "vapi", "label": "Main line", "config": {"phone_number": "+14155550123"}}


def _state(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


async def _link(client: AsyncClient, conn: Json) -> str:
    return (await client.post(f"/api/v1/connections/{conn['id']}/consent-link")).json()["url"]


async def _callback(client: AsyncClient, provider: str, url: str) -> httpx.Response:
    return await client.get(
        f"/api/v1/oauth/{provider}/callback", params={"code": "c", "state": _state(url)}
    )


@pytest.fixture
async def firm(authed: AsyncClient) -> Json:
    return await create_firm(authed)


@pytest.fixture
async def slack(db: AsyncSession, firm: Json) -> ConnectorConnection:
    return await connected(
        db, firm["id"], "slack", {"team_id": "T1"}, {"bot_token": "fake-token-1"}
    )


@pytest.fixture
async def vapi_conn(db: AsyncSession, firm: Json) -> ConnectorConnection:
    return await connected(db, firm["id"], "vapi", {"assistant_id": "a1", "phone_number_id": "p1"})


async def _test(client: AsyncClient, c: ConnectorConnection, **body: object) -> httpx.Response:
    return await client.post(f"/api/v1/connections/{c.id}/test", json=body)


# --- create, read, patch, delete ---------------------------------------------------------


async def test_pending_oauth_connection(authed: AsyncClient, firm: Json) -> None:
    conn = await pending(authed, firm["id"], "slack")
    assert conn["status"] == "pending" and conn["webhook_url"].endswith("/api/v1/hooks/slack")
    listed = (await authed.get(f"/api/v1/firms/{firm['id']}/connections")).json()
    assert [c["id"] for c in listed] == [conn["id"]]


async def test_unknown_firm_is_404(authed: AsyncClient) -> None:
    assert (await authed.get(f"/api/v1/firms/{ZERO}/connections")).status_code == 404
    resp = await authed.post(
        f"/api/v1/firms/{ZERO}/connections", json={"connector": "slack", "label": "x"}
    )
    assert resp.status_code == 404


@pytest.mark.parametrize("method", ["get", "delete"])
async def test_unknown_connection_is_404(authed: AsyncClient, method: str) -> None:
    assert (await authed.request(method.upper(), f"/api/v1/connections/{ZERO}")).status_code == 404


async def test_unsupported_connector_is_422(authed: AsyncClient, firm: Json) -> None:
    resp = await authed.post(
        f"/api/v1/firms/{firm['id']}/connections", json={"connector": "fax", "label": "x"}
    )
    assert resp.status_code == 422


async def test_oauth_connection_rejects_secrets(authed: AsyncClient, firm: Json) -> None:
    resp = await authed.post(
        f"/api/v1/firms/{firm['id']}/connections",
        json={"connector": "slack", "label": "x", "secrets": {"t": "x"}},
    )
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/secrets"


async def test_provider_owned_config_is_read_only_on_create(
    authed: AsyncClient, firm: Json
) -> None:
    resp = await authed.post(
        f"/api/v1/firms/{firm['id']}/connections",
        json={"connector": "gmail", "label": "x", "config": {"mailbox": "x@y.com"}},
    )
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/config/mailbox"


async def test_provider_owned_config_is_read_only_on_patch(
    authed: AsyncClient, slack: ConnectorConnection
) -> None:
    resp = await authed.patch(f"/api/v1/connections/{slack.id}", json={"config": {"team_id": "T2"}})
    assert resp.status_code == 422 and resp.json()["errors"][0]["code"] == "read_only"


async def test_patch_merges_builder_config_and_label(
    authed: AsyncClient, slack: ConnectorConnection
) -> None:
    resp = (
        await authed.patch(
            f"/api/v1/connections/{slack.id}", json={"label": "Renamed", "config": {"note": "main"}}
        )
    ).json()
    assert resp["label"] == "Renamed" and resp["config"] == {"team_id": "T1", "note": "main"}


async def test_patch_replaces_secret_and_shows_only_hint(
    authed: AsyncClient, slack: ConnectorConnection
) -> None:
    resp = (
        await authed.patch(
            f"/api/v1/connections/{slack.id}", json={"secrets": {"bot_token": "fake-token-new2"}}
        )
    ).json()
    assert resp["secret_hints"] == {"bot_token": "••••new2"}
    assert "fake-token" not in json.dumps(resp)


async def test_patch_merges_secrets(authed: AsyncClient, db: AsyncSession, firm: Json) -> None:
    c = await connected(db, firm["id"], "gmail", secrets={"refresh_token": "rt-secret-0001"})
    resp = (
        await authed.patch(f"/api/v1/connections/{c.id}", json={"secrets": {"extra": "value-9999"}})
    ).json()
    assert resp["secret_hints"] == {"refresh_token": "••••0001", "extra": "••••9999"}
    assert "rt-secret" not in json.dumps(resp)


async def test_delete_unused_connection(
    authed: AsyncClient, db: AsyncSession, slack: ConnectorConnection
) -> None:
    assert (await authed.delete(f"/api/v1/connections/{slack.id}")).status_code == 204
    assert await db.get(ConnectorConnection, slack.id) is None


async def test_delete_blocked_while_a_mapping_binds_it(
    authed: AsyncClient, db: AsyncSession, firm: Json
) -> None:
    agent = await create_agent(authed)
    gmail = await connected(db, firm["id"], "gmail")
    await authed.post(
        "/api/v1/mappings",
        json={
            "firm_id": firm["id"],
            "agent_prompt_id": agent["versions"][0]["id"],
            "identities": {"gmail": str(gmail.id)},
        },
    )
    assert (await authed.delete(f"/api/v1/connections/{gmail.id}")).status_code == 409


# --- consent links and OAuth callbacks ---------------------------------------------------


async def test_consent_link_rotation_invalidates_old_link(authed: AsyncClient, firm: Json) -> None:
    conn = await pending(authed, firm["id"], "slack")
    first = await _link(authed, conn)
    await _link(authed, conn)
    assert first.startswith("https://slack.com/oauth/v2/authorize")
    assert (await _callback(authed, "slack", first)).status_code == 400


@respx.mock
async def test_slack_callback_connects(authed: AsyncClient, firm: Json) -> None:
    conn = await pending(authed, firm["id"], "slack")
    respx.post("https://slack.com/api/oauth.v2.access").respond(json=SLACK_TOKEN)
    resp = await _callback(authed, "slack", await _link(authed, conn))
    assert resp.status_code == 303
    assert resp.headers["location"] == (
        f"https://app.lucia.test/firms/{firm['id']}?tab=connections&connected={conn['id']}"
    )
    got = (await authed.get(f"/api/v1/connections/{conn['id']}")).json()
    assert got["status"] == "connected" and got["config"]["team_id"] == "T1"
    assert got["secret_hints"] == {"bot_token": "••••1234"} and not got["has_consent_link"]
    assert "token-1234" not in json.dumps(got)


@respx.mock
async def test_replayed_callback_is_rejected(authed: AsyncClient, firm: Json) -> None:
    conn = await pending(authed, firm["id"], "slack")
    exchange = respx.post("https://slack.com/api/oauth.v2.access").respond(json=SLACK_TOKEN)
    url = await _link(authed, conn)
    await authed.get(f"/api/v1/connections/{conn['id']}")  # load the row into the session
    assert (await _callback(authed, "slack", url)).status_code == 303
    assert (await _callback(authed, "slack", url)).status_code == 400
    assert exchange.call_count == 1


@respx.mock
async def test_google_callback_stores_lowercased_mailbox(authed: AsyncClient, firm: Json) -> None:
    conn = await pending(authed, firm["id"], "gmail")
    url = await _link(authed, conn)
    assert parse_qs(urlparse(url).query)["access_type"] == ["offline"]
    respx.post("https://oauth2.googleapis.com/token").respond(
        json={"access_token": "at", "refresh_token": "rt-9999"}
    )
    respx.get("https://gmail.googleapis.com/gmail/v1/users/me/profile").respond(
        json={"emailAddress": "Records@Acme.com"}
    )
    assert (await _callback(authed, "google", url)).status_code == 303
    got = (await authed.get(f"/api/v1/connections/{conn['id']}")).json()
    assert got["label"] == "records@acme.com" and got["config"]["mailbox"] == "records@acme.com"


@respx.mock
async def test_google_without_refresh_token_is_rejected(authed: AsyncClient, firm: Json) -> None:
    conn = await pending(authed, firm["id"], "gmail")
    respx.post("https://oauth2.googleapis.com/token").respond(json={"access_token": "at"})
    resp = await _callback(authed, "google", await _link(authed, conn))
    assert resp.status_code == 400 and "refresh token" in resp.text


@respx.mock
async def test_rejected_code_keeps_connection_pending(authed: AsyncClient, firm: Json) -> None:
    conn = await pending(authed, firm["id"], "gmail")
    respx.post("https://oauth2.googleapis.com/token").respond(400, json={"error": "invalid_grant"})
    resp = await _callback(authed, "google", await _link(authed, conn))
    assert resp.status_code == 400 and "invalid_grant" in resp.text
    still = (await authed.get(f"/api/v1/connections/{conn['id']}")).json()
    assert still["status"] == "pending" and still["has_consent_link"]


async def test_state_for_another_connector_is_rejected(authed: AsyncClient, firm: Json) -> None:
    conn = await pending(authed, firm["id"], "slack")
    assert (await _callback(authed, "google", await _link(authed, conn))).status_code == 400


async def test_forged_nonce_is_rejected(authed: AsyncClient, firm: Json) -> None:
    conn = await pending(authed, firm["id"], "slack")
    await _link(authed, conn)
    forged = sign_state({"connection_id": conn["id"], "nonce": "guess"}, "consent:slack")
    resp = await authed.get("/api/v1/oauth/slack/callback", params={"code": "c", "state": forged})
    assert resp.status_code == 400


@pytest.mark.parametrize(
    ("params", "text"),
    [
        ({"code": "c", "state": "tampered"}, "invalid"),
        ({"error": "access_denied"}, "declined"),
        ({"code": "c"}, "incomplete"),
    ],
)
async def test_bad_callbacks_render_error_page(
    authed: AsyncClient, params: dict[str, str], text: str
) -> None:
    resp = await authed.get("/api/v1/oauth/slack/callback", params=params)
    assert resp.status_code == 400 and text in resp.text


async def test_consent_link_not_for_vapi(
    authed: AsyncClient, vapi_conn: ConnectorConnection
) -> None:
    resp = await authed.post(f"/api/v1/connections/{vapi_conn.id}/consent-link")
    assert resp.status_code == 409


async def test_consent_link_needs_platform_app(
    authed: AsyncClient, firm: Json, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = await pending(authed, firm["id"], "slack")
    monkeypatch.setattr(get_settings(), "slack_client_id", "")
    resp = await authed.post(f"/api/v1/connections/{conn['id']}/consent-link")
    assert resp.status_code == 409 and "not configured" in resp.json()["detail"]


# --- Vapi provisioning -------------------------------------------------------------------


@respx.mock
async def test_vapi_provisioning_with_own_twilio(authed: AsyncClient, firm: Json) -> None:
    assistant = respx.post("https://api.vapi.ai/assistant").respond(json={"id": "asst_1"})
    respx.post("https://api.vapi.ai/phone-number").respond(json={"id": "pn_1"})
    resp = await authed.post(
        f"/api/v1/firms/{firm['id']}/connections",
        json={
            **VAPI_BODY,
            "secrets": {"twilio_account_sid": "AC123", "twilio_auth_token": "tok-5678"},
        },
    )
    body = resp.json()
    assert resp.status_code == 201 and body["status"] == "connected"
    assert body["config"] == {
        "assistant_id": "asst_1",
        "phone_number_id": "pn_1",
        "phone_number": "+14155550123",
    }
    assert body["secret_hints"]["twilio_auth_token"] == "••••5678"
    server = json.loads(assistant.calls.last.request.content)["server"]
    assert server["url"] == "https://lucia.test/api/v1/hooks/vapi"
    assert server["headers"] == {"x-vapi-secret": get_settings().vapi_webhook_secret}


@respx.mock
async def test_vapi_falls_back_to_platform_twilio(authed: AsyncClient, firm: Json) -> None:
    respx.post("https://api.vapi.ai/assistant").respond(json={"id": "asst_1"})
    number = respx.post("https://api.vapi.ai/phone-number").respond(json={"id": "pn_1"})
    resp = (await authed.post(f"/api/v1/firms/{firm['id']}/connections", json=VAPI_BODY)).json()
    assert resp["secret_hints"] == {}
    sent = json.loads(number.calls.last.request.content)
    assert sent["twilioAccountSid"] == get_settings().twilio_account_sid


@pytest.mark.parametrize("phone", ["555", "14155550123", "+0123456789", ""])
async def test_vapi_rejects_non_e164_numbers(authed: AsyncClient, firm: Json, phone: str) -> None:
    resp = await authed.post(
        f"/api/v1/firms/{firm['id']}/connections",
        json={**VAPI_BODY, "config": {"phone_number": phone}},
    )
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/config/phone_number"


async def test_vapi_without_twilio_is_422(
    authed: AsyncClient, firm: Json, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "twilio_auth_token", "")
    resp = await authed.post(f"/api/v1/firms/{firm['id']}/connections", json=VAPI_BODY)
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/secrets"


async def test_vapi_without_platform_key_is_409(
    authed: AsyncClient, firm: Json, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "vapi_api_key", "")
    assert (
        await authed.post(f"/api/v1/firms/{firm['id']}/connections", json=VAPI_BODY)
    ).status_code == 409


@respx.mock
async def test_vapi_provider_error_is_502(authed: AsyncClient, firm: Json) -> None:
    respx.post("https://api.vapi.ai/assistant").respond(401, json={"message": "bad key"})
    resp = await authed.post(f"/api/v1/firms/{firm['id']}/connections", json=VAPI_BODY)
    assert resp.status_code == 502 and resp.json()["detail"] == "Vapi error 401: bad key"


# --- tests (auth and per tool) -----------------------------------------------------------


@respx.mock
async def test_auth_test_success_sets_health_ok(
    authed: AsyncClient, slack: ConnectorConnection
) -> None:
    respx.post("https://slack.com/api/auth.test").respond(
        json={"ok": True, "user": "lucia", "team": "Acme"}
    )
    assert (await _test(authed, slack)).json() == {
        "ok": True,
        "detail": "Authenticated as lucia in Acme",
    }
    got = (await authed.get(f"/api/v1/connections/{slack.id}")).json()
    assert got["health"] == "ok" and got["test_results"]["auth"]["ok"] is True
    assert got["last_tested_at"] is not None


@respx.mock
async def test_network_error_degrades_health(
    authed: AsyncClient, db: AsyncSession, firm: Json
) -> None:
    c = await connected(db, firm["id"], "gmail", {"mailbox": "r@acme.com"}, {"refresh_token": "r"})
    respx.post("https://oauth2.googleapis.com/token").mock(side_effect=httpx.ConnectError("down"))
    resp = (await _test(authed, c)).json()
    assert resp == {"ok": False, "detail": "Network error talking to the provider (ConnectError)"}
    assert (await authed.get(f"/api/v1/connections/{c.id}")).json()["health"] == "degraded"


async def test_missing_secret_fails_test_not_500(
    authed: AsyncClient, db: AsyncSession, firm: Json
) -> None:
    c = await connected(db, firm["id"], "slack")
    resp = (await _test(authed, c)).json()
    assert resp == {"ok": False, "detail": "Connection is missing bot_token; reconnect it"}


async def test_tests_need_connected(authed: AsyncClient, firm: Json) -> None:
    conn = await pending(authed, firm["id"], "slack")
    assert (await authed.post(f"/api/v1/connections/{conn['id']}/test", json={})).status_code == 409


@respx.mock
async def test_send_message_uses_bot_token(authed: AsyncClient, slack: ConnectorConnection) -> None:
    post = respx.post("https://slack.com/api/chat.postMessage").respond(json={"ok": True})
    resp = await _test(authed, slack, tool="slack.send_message", input={"channel": "C1"})
    assert resp.json() == {"ok": True, "detail": "Posted to C1"}
    assert post.calls.last.request.headers["authorization"] == "Bearer fake-token-1"


@respx.mock
async def test_provider_failure_is_stored_not_raised(
    authed: AsyncClient, slack: ConnectorConnection
) -> None:
    respx.post("https://slack.com/api/chat.postMessage").respond(
        json={"ok": False, "error": "channel_not_found"}
    )
    resp = await _test(authed, slack, tool="slack.send_message", input={"channel": "C1"})
    assert resp.json() == {"ok": False, "detail": "Slack error: channel_not_found"}
    got = (await authed.get(f"/api/v1/connections/{slack.id}")).json()
    assert got["test_results"]["slack.send_message"]["ok"] is False
    assert got["health"] == "unknown"  # only the auth test moves health


@respx.mock
async def test_slack_post_file_three_step_upload(
    authed: AsyncClient, slack: ConnectorConnection
) -> None:
    respx.get("https://slack.com/api/files.getUploadURLExternal").respond(
        json={"ok": True, "upload_url": "https://files.slack.com/up/1", "file_id": "F1"}
    )
    upload = respx.post("https://files.slack.com/up/1").respond(200)
    done = respx.post("https://slack.com/api/files.completeUploadExternal").respond(
        json={"ok": True}
    )
    resp = await _test(authed, slack, tool="slack.post_file", input={"channel": "C1"})
    assert resp.json()["ok"] and upload.called
    assert json.loads(done.calls.last.request.content)["channel_id"] == "C1"


@respx.mock
async def test_gmail_send_email(authed: AsyncClient, db: AsyncSession, firm: Json) -> None:
    c = await connected(db, firm["id"], "gmail", {"mailbox": "r@acme.com"}, {"refresh_token": "r"})
    respx.post("https://oauth2.googleapis.com/token").respond(json={"access_token": "at"})
    send = respx.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send").respond(
        json={"id": "m1"}
    )
    resp = await _test(authed, c, tool="gmail.send_email", input={"to": "me@example.com"})
    assert resp.json() == {"ok": True, "detail": "Sent a test email to me@example.com"}
    assert send.calls.last.request.headers["authorization"] == "Bearer at"


async def test_outbound_test_needs_input(authed: AsyncClient, slack: ConnectorConnection) -> None:
    resp = await _test(authed, slack, tool="slack.send_message")
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/input"


@pytest.mark.parametrize("tool", ["gmail.send_email", "slack.nope", "fax.send_fax"])
async def test_tool_must_belong_to_connector(
    authed: AsyncClient, slack: ConnectorConnection, tool: str
) -> None:
    resp = await _test(authed, slack, tool=tool)
    assert resp.status_code == 422 and resp.json()["errors"][0]["code"] == "unknown_tool"


async def test_inbound_tool_asks_for_an_event(
    authed: AsyncClient, slack: ConnectorConnection
) -> None:
    resp = (await _test(authed, slack, tool="slack.listen_mention")).json()
    assert resp["ok"] is False and "Mention the bot" in resp["detail"]


async def test_inbound_tool_passes_on_recent_event(
    authed: AsyncClient, db: AsyncSession, slack: ConnectorConnection
) -> None:
    slack.last_inbound_at, slack.last_inbound_type = utcnow(), "slack.app_mention"
    await db.commit()
    assert (await _test(authed, slack, tool="slack.listen_mention")).json()["ok"] is True


@pytest.mark.parametrize(
    ("age", "kind"), [(timedelta(hours=1), "slack.app_mention"), (timedelta(0), "gmail.message")]
)
async def test_inbound_tool_fails_on_stale_or_foreign_event(
    authed: AsyncClient, db: AsyncSession, slack: ConnectorConnection, age: timedelta, kind: str
) -> None:
    slack.last_inbound_at, slack.last_inbound_type = utcnow() - age, kind
    await db.commit()
    assert (await _test(authed, slack, tool="slack.listen_mention")).json()["ok"] is False


@respx.mock
async def test_vapi_auth_test(authed: AsyncClient, vapi_conn: ConnectorConnection) -> None:
    respx.get("https://api.vapi.ai/assistant/a1").respond(json={"id": "a1"})
    respx.get("https://api.vapi.ai/phone-number/p1").respond(json={"number": "+14155550123"})
    assert (await _test(authed, vapi_conn)).json() == {
        "ok": True,
        "detail": "Assistant and number +14155550123 are ready",
    }


@respx.mock
async def test_vapi_place_call(authed: AsyncClient, vapi_conn: ConnectorConnection) -> None:
    call = respx.post("https://api.vapi.ai/call").respond(json={"id": "call_1"})
    resp = await _test(authed, vapi_conn, tool="vapi.place_call", input={"to": "+14155550199"})
    assert resp.json() == {"ok": True, "detail": "Call call_1 queued to +14155550199"}
    sent = json.loads(call.calls.last.request.content)
    assert sent["assistantOverrides"]["maxDurationSeconds"] == 20
    assert sent["customer"] == {"number": "+14155550199"}


async def test_vapi_call_rejects_non_e164_target(
    authed: AsyncClient, vapi_conn: ConnectorConnection
) -> None:
    resp = await _test(authed, vapi_conn, tool="vapi.place_call", input={"to": "555"})
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/input/to"


# --- inbound enable ----------------------------------------------------------------------


@respx.mock
async def test_gmail_inbound_enable_watches(
    authed: AsyncClient, db: AsyncSession, firm: Json
) -> None:
    g = await connected(db, firm["id"], "gmail", {"mailbox": "r@acme.com"}, {"refresh_token": "r"})
    respx.post("https://oauth2.googleapis.com/token").respond(json={"access_token": "at"})
    watch = respx.post("https://gmail.googleapis.com/gmail/v1/users/me/watch").respond(
        json={"historyId": "1", "expiration": "999"}
    )
    resp = (await authed.post(f"/api/v1/connections/{g.id}/inbound/enable")).json()
    assert resp["webhook_url"] == "https://lucia.test/api/v1/hooks/gmail"
    assert (
        json.loads(watch.calls.last.request.content)["topicName"]
        == get_settings().google_pubsub_topic
    )
    got = (await authed.get(f"/api/v1/connections/{g.id}")).json()
    assert got["config"]["watch_expiration"] == "999"


@respx.mock
async def test_gmail_watch_failure_is_502(
    authed: AsyncClient, db: AsyncSession, firm: Json
) -> None:
    g = await connected(db, firm["id"], "gmail", {"mailbox": "r@acme.com"}, {"refresh_token": "r"})
    respx.post("https://oauth2.googleapis.com/token").respond(json={"access_token": "at"})
    respx.post("https://gmail.googleapis.com/gmail/v1/users/me/watch").respond(
        403, json={"error": {"message": "topic not permitted"}}
    )
    resp = await authed.post(f"/api/v1/connections/{g.id}/inbound/enable")
    assert resp.status_code == 502 and "topic not permitted" in resp.json()["detail"]


async def test_slack_inbound_enable_returns_webhook(
    authed: AsyncClient, slack: ConnectorConnection
) -> None:
    resp = (await authed.post(f"/api/v1/connections/{slack.id}/inbound/enable")).json()
    assert resp["webhook_url"] == "https://lucia.test/api/v1/hooks/slack"


async def test_inbound_enable_needs_connected(authed: AsyncClient, firm: Json) -> None:
    conn = await pending(authed, firm["id"], "gmail")
    resp = await authed.post(f"/api/v1/connections/{conn['id']}/inbound/enable")
    assert resp.status_code == 409
