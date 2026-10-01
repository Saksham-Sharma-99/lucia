import re
from typing import Any

from lucia.connectors.base import ConnectorError, Outcome, hook_url, http, inbound_outcome, need
from lucia.core.config import get_settings
from lucia.core.errors import FieldError, conflict, invalid
from lucia.core.time import utcnow
from lucia.db.models import ConnectorConnection, Firm

API = "https://api.vapi.ai"
E164 = re.compile(r"\+[1-9]\d{6,14}")
SYSTEM_KEYS = frozenset({"assistant_id", "phone_number_id", "phone_number"})
TWILIO_KEYS = ("twilio_account_sid", "twilio_auth_token")


def configured() -> bool:
    s = get_settings()
    return bool(s.vapi_api_key and s.vapi_webhook_secret)


async def _api(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    async with http() as client:
        resp = await client.request(
            method,
            f"{API}{path}",
            json=body,
            headers={"Authorization": f"Bearer {get_settings().vapi_api_key}"},
        )
    data: dict[str, Any] = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        raise ConnectorError(
            f"Vapi error {resp.status_code}: {data.get('message', '')}".strip(": ")
        )
    return data


async def setup(
    conn: ConnectorConnection, firm: Firm, config: dict[str, Any], secrets: dict[str, str]
) -> dict[str, str]:
    """Create the firm's assistant and import its Twilio number (platform Twilio by default)."""
    s = get_settings()
    phone = str(config.get("phone_number", ""))
    if not E164.fullmatch(phone):
        raise invalid(
            [
                FieldError(
                    path="/config/phone_number",
                    code="invalid_phone",
                    message="Use E.164 format, e.g. +14155550123",
                )
            ]
        )
    if not configured():
        raise conflict("Vapi is not configured on the platform")
    own = {k: secrets[k] for k in TWILIO_KEYS if secrets.get(k)}
    sid = own.get("twilio_account_sid") or s.twilio_account_sid
    token = own.get("twilio_auth_token") or s.twilio_auth_token
    if not sid or not token:
        raise invalid(
            [
                FieldError(
                    path="/secrets",
                    code="twilio_missing",
                    message="Provide Twilio credentials or set them on the platform",
                )
            ]
        )
    assistant = await _api(
        "POST",
        "/assistant",
        {
            "name": f"Lucia - {firm.name}"[:40],
            "firstMessage": "Hello, how can I help?",
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [{"role": "system", "content": "You answer calls for the firm."}],
            },
            "server": {
                "url": hook_url("vapi"),
                "headers": {"x-vapi-secret": s.vapi_webhook_secret},
            },
            "serverMessages": ["end-of-call-report", "status-update"],
        },
    )
    number = await _api(
        "POST",
        "/phone-number",
        {
            "provider": "twilio",
            "number": phone,
            "twilioAccountSid": sid,
            "twilioAuthToken": token,
            "assistantId": assistant["id"],
            "smsEnabled": False,
        },
    )
    conn.config = {
        "assistant_id": assistant["id"],
        "phone_number_id": number["id"],
        "phone_number": phone,
    }
    conn.status, conn.connected_at = "connected", utcnow()
    return own


async def auth_test(conn: ConnectorConnection, secrets: dict[str, str]) -> Outcome:
    await _api("GET", f"/assistant/{need(conn.config, 'assistant_id')}")
    number = await _api("GET", f"/phone-number/{need(conn.config, 'phone_number_id')}")
    return Outcome(True, f"Assistant and number {number.get('number', '')} are ready")


async def tool_test(
    tool: str, data: dict[str, Any], conn: ConnectorConnection, secrets: dict[str, str]
) -> Outcome:
    if tool == "vapi.place_call":
        call = await _api(
            "POST",
            "/call",
            {
                "assistantId": need(conn.config, "assistant_id"),
                "phoneNumberId": need(conn.config, "phone_number_id"),
                "customer": {"number": data["to"]},
                "assistantOverrides": {
                    "firstMessage": "Hello, this is a short test call from Lucia. Goodbye.",
                    "maxDurationSeconds": 20,
                },
            },
        )
        return Outcome(True, f"Call {call.get('id', '')} queued to {data['to']}")
    return inbound_outcome(conn, "vapi.", "Call the firm's number")


async def enable_inbound(
    conn: ConnectorConnection, secrets: dict[str, str]
) -> tuple[dict[str, Any], str]:
    return {}, "The assistant already sends call events to Lucia"
