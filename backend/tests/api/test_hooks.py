import base64
import json
import time
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.config import get_settings
from tests.factories import connected, create_firm
from tests.unit.test_slack_signature import sign


async def _slack(
    client: AsyncClient, payload: Any, *, valid: bool = True, age: int = 0
) -> Response:
    body = json.dumps(payload).encode()
    ts = str(int(time.time()) - age)
    return await client.post(
        "/api/v1/hooks/slack",
        content=body,
        headers={
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sign(body, ts) if valid else "v0=x",
        },
    )


async def _gmail(client: AsyncClient, message: Any, token: str | None = None) -> Response:
    token = get_settings().google_pubsub_verification_token if token is None else token
    return await client.post(
        "/api/v1/hooks/gmail", params={"token": token}, json={"message": message}
    )


def _push(email: str) -> dict[str, str]:
    return {"data": base64.b64encode(json.dumps({"emailAddress": email}).encode()).decode()}


async def _vapi(client: AsyncClient, message: Any, secret: str | bytes | None = None) -> Response:
    value = get_settings().vapi_webhook_secret if secret is None else secret
    raw = value if isinstance(value, bytes) else value.encode()
    return await client.post(
        "/api/v1/hooks/vapi", json={"message": message}, headers=[(b"x-vapi-secret", raw)]
    )


# --- Slack -------------------------------------------------------------------------------


async def test_slack_url_verification(client: AsyncClient) -> None:
    resp = await _slack(client, {"type": "url_verification", "challenge": "abc"})
    assert resp.json()["challenge"] == "abc"


@pytest.mark.parametrize(("valid", "age"), [(False, 0), (True, 600)])
async def test_slack_bad_or_stale_signature_is_401(
    client: AsyncClient, valid: bool, age: int
) -> None:
    resp = await _slack(client, {"type": "url_verification"}, valid=valid, age=age)
    assert resp.status_code == 401


async def test_slack_event_records_last_inbound(authed: AsyncClient, db: AsyncSession) -> None:
    firm = await create_firm(authed)
    c = await connected(db, firm["id"], "slack", {"team_id": "T9"})
    resp = await _slack(
        authed, {"type": "event_callback", "team_id": "T9", "event": {"type": "app_mention"}}
    )
    assert resp.json()["recorded"] == 1
    got = (await authed.get(f"/api/v1/connections/{c.id}")).json()
    assert got["last_inbound_type"] == "slack.app_mention" and got["last_inbound_at"]


async def test_slack_event_updates_every_matching_connection(
    authed: AsyncClient, db: AsyncSession
) -> None:
    for slug in ("firm-one", "firm-two"):
        firm = await create_firm(authed, slug=slug)
        await connected(db, firm["id"], "slack", {"team_id": "TSHARED"})
    resp = await _slack(
        authed, {"type": "event_callback", "team_id": "TSHARED", "event": {"type": "message"}}
    )
    assert resp.json()["recorded"] == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "app_rate_limited"},
        {"type": "event_callback", "team_id": "T-none", "event": {"type": "app_mention"}},
        {"type": "event_callback", "team_id": "T1", "event": "not-an-object"},
        {"type": "event_callback"},
    ],
)
async def test_slack_unmatched_or_odd_payloads_record_nothing(
    client: AsyncClient, payload: Any
) -> None:
    resp = await _slack(client, payload)
    assert resp.status_code == 200 and resp.json()["recorded"] == 0


@pytest.mark.parametrize("payload", [[1], "text"])
async def test_slack_non_object_body_is_400(client: AsyncClient, payload: Any) -> None:
    assert (await _slack(client, payload)).status_code == 400


# --- Gmail -------------------------------------------------------------------------------


async def test_gmail_push_records_case_insensitively(authed: AsyncClient, db: AsyncSession) -> None:
    firm = await create_firm(authed)
    c = await connected(db, firm["id"], "gmail", {"mailbox": "records@acme.com"})
    assert (await _gmail(authed, _push("RECORDS@Acme.COM"))).json()["recorded"] == 1
    got = (await authed.get(f"/api/v1/connections/{c.id}")).json()
    assert got["last_inbound_type"] == "gmail.message"


@pytest.mark.parametrize("token", ["nope", "é", ""])
async def test_gmail_bad_token_is_401(client: AsyncClient, token: str) -> None:
    assert (await _gmail(client, _push("x@y.com"), token=token)).status_code == 401


@pytest.mark.parametrize(
    "message",
    [
        {"data": "!!"},
        {"data": base64.b64encode(b'{"x":1}').decode()},
        "text",
        None,
        {},
    ],
)
async def test_gmail_malformed_message_is_400(client: AsyncClient, message: Any) -> None:
    assert (await _gmail(client, message)).status_code == 400


async def test_gmail_invalid_json_is_400(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/hooks/gmail",
        content=b"{",
        params={"token": get_settings().google_pubsub_verification_token},
    )
    assert resp.status_code == 400


# --- Vapi --------------------------------------------------------------------------------


async def test_vapi_records_by_phone_number(authed: AsyncClient, db: AsyncSession) -> None:
    firm = await create_firm(authed)
    c = await connected(db, firm["id"], "vapi", {"phone_number_id": "pn_1"})
    message = {"type": "end-of-call-report", "call": {"phoneNumberId": "pn_1"}}
    assert (await _vapi(authed, message)).json()["recorded"] == 1
    got = (await authed.get(f"/api/v1/connections/{c.id}")).json()
    assert got["last_inbound_type"] == "vapi.end-of-call-report"


async def test_vapi_without_a_platform_secret_rejects_everything(
    authed: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed (D43): an unset secret must not open the hook that resumes runs."""
    monkeypatch.setattr(get_settings(), "vapi_webhook_secret", "")
    message = {"type": "status-update", "call": {"phoneNumberId": "pn_1"}}
    assert (await _vapi(authed, message, secret="")).status_code == 401


@pytest.mark.parametrize("secret", ["wrong", "ü".encode(), ""])
async def test_vapi_bad_secret_is_401(client: AsyncClient, secret: str | bytes) -> None:
    assert (await _vapi(client, {}, secret=secret)).status_code == 401


@pytest.mark.parametrize(
    "message",
    [
        {"type": "status-update"},
        "text",
        None,
        {"call": 5},
        {"type": "x", "call": {"phoneNumberId": "nobody"}},
        {"type": "x", "assistant": {"id": "asst_1"}},
    ],
)
async def test_vapi_unmatched_or_odd_payloads_record_nothing(
    client: AsyncClient, message: Any
) -> None:
    resp = await _vapi(client, message)
    assert resp.status_code == 200 and resp.json()["recorded"] == 0
