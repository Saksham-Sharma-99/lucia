"""Vapi voice, outbound only. The firm's number already lives in the platform's Vapi account
(imported there from Twilio, Telnyx or Vonage); a connection stores its id. No assistant is
stored: each call carries a transient one that reports back to our webhook."""

from typing import Any

import httpx

from lucia.connectors.base import ConnectorError, MaybeSent, Outcome, hook_url, http, need
from lucia.core.config import get_settings
from lucia.core.errors import FieldError, conflict, invalid
from lucia.core.time import utcnow
from lucia.db.models import ConnectorConnection, Firm

API = "https://api.vapi.ai"
SYSTEM_KEYS = frozenset({"phone_number"})
# Lucia's voice: the model that talks, how it sounds (Cartesia, Katie) and how it hears.
MODEL = {"provider": "openai", "model": "gpt-4.1-mini"}
VOICE = {
    "provider": "cartesia",
    "model": "sonic-3.5",
    "voiceId": "f786b574-daa5-4673-aa0c-cbe3e8534c02",  # Katie, en-US female
    "generationConfig": {"speed": 1.1},
}
TRANSCRIBER = {"provider": "deepgram", "model": "nova-3"}
# A beat after the call connects before the assistant speaks. Vapi has no greeting-only delay:
# this minimum wait applies before every reply (Vapi's default is 0.4 s).
START_SPEAKING = {"waitSeconds": 1.0}


class UnknownId(ConnectorError):
    """Vapi rejected the id itself (400 malformed, 404 not in this account)."""


def configured() -> bool:
    return bool(get_settings().vapi_api_key)


async def _api(
    method: str, path: str, body: dict[str, Any] | None = None, params: dict[str, str] | None = None
) -> Any:
    try:
        async with http() as client:
            resp = await client.request(
                method,
                f"{API}{path}",
                json=body,
                params=params,
                headers={"Authorization": f"Bearer {get_settings().vapi_api_key}"},
            )
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:  # never left
        raise ConnectorError(f"Vapi unreachable: {type(e).__name__}") from e
    except httpx.HTTPError as e:  # sent, but no answer came back
        raise MaybeSent(f"Vapi didn't answer: {type(e).__name__}") from e
    if resp.status_code >= 500:
        raise MaybeSent(f"Vapi error {resp.status_code}")
    data: Any = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        data = data if isinstance(data, dict) else {}
        message = f"Vapi error {resp.status_code}: {data.get('message', '')}".strip(": ")
        if resp.status_code == 401:
            message += " Check VAPI_API_KEY: it must be the private key."
        raise (UnknownId if resp.status_code in (400, 404) else ConnectorError)(message)
    return data


def _bad_number(message: str) -> Exception:
    return invalid(
        [FieldError(path="/config/phone_number_id", code="invalid_number", message=message)]
    )


async def setup(
    conn: ConnectorConnection, firm: Firm, config: dict[str, Any], secrets: dict[str, str]
) -> dict[str, str]:
    """Check the firm's number, or the platform default, exists in Vapi and can place calls.
    The resolved id is stored, so changing the default later doesn't move existing firms."""
    if not configured():
        raise conflict("Vapi is not configured on the platform")
    if secrets:
        raise invalid(
            [
                FieldError(
                    path="/secrets", code="read_only", message="Vapi connections take no secrets"
                )
            ]
        )
    number_id = (
        str(config.get("phone_number_id", "")).strip() or get_settings().vapi_phone_number_id
    )
    if not number_id:
        raise _bad_number(
            "Paste the phone number id from the Vapi dashboard"
            " (the platform has no default VAPI_PHONE_NUMBER_ID)"
        )
    try:
        number = await _api("GET", f"/phone-number/{number_id}")
    except UnknownId as exc:  # other provider errors are the platform's, not this field's
        raise _bad_number(f"Vapi couldn't find this number ({exc})") from exc
    if number.get("provider") == "vapi":  # Vapi's free numbers are inbound only
        raise _bad_number(
            "Free Vapi numbers can't place calls. Import a Twilio, Telnyx or Vonage number"
        )
    conn.config = {"phone_number_id": number_id, "phone_number": number.get("number", "")}
    conn.status, conn.connected_at = "connected", utcnow()
    return {}


def assistant(
    first_message: str, instructions: str, metadata: dict[str, str], max_seconds: int
) -> dict[str, Any]:
    """A transient assistant for one call; `metadata` comes back on every webhook event."""
    secret = get_settings().vapi_webhook_secret
    return {
        "firstMessage": first_message,
        "model": {**MODEL, "messages": [{"role": "system", "content": instructions}]},
        "voice": VOICE,
        "transcriber": TRANSCRIBER,
        "maxDurationSeconds": max_seconds,
        "startSpeakingPlan": START_SPEAKING,
        "metadata": metadata,
        "server": {"url": hook_url("vapi"), "headers": {"x-vapi-secret": secret} if secret else {}},
        "serverMessages": ["end-of-call-report", "status-update"],
    }


async def place_call(conn: ConnectorConnection, to: str, spec: dict[str, Any]) -> str:
    """Queue a call from the connection's number; returns the Vapi call id."""
    call = await _api(
        "POST",
        "/call",
        {
            "phoneNumberId": need(conn.config, "phone_number_id"),
            "customer": {"number": to},
            "assistant": spec,
        },
    )
    return str(call.get("id", ""))


async def get_call(call_id: str) -> dict[str, Any]:
    return await _api("GET", f"/call/{call_id}")


async def recording_url(call_id: str) -> str:
    """A short-lived signed link to the call's mono recording: Vapi answers 302 (recordings
    are access-controlled, so the link is fetched when someone wants to listen)."""
    try:
        async with http() as client:
            resp = await client.get(
                f"{API}/call/{call_id}/mono-recording",
                headers={"Authorization": f"Bearer {get_settings().vapi_api_key}"},
            )
    except httpx.HTTPError as e:
        raise ConnectorError(f"Vapi unreachable: {type(e).__name__}") from e
    if resp.status_code >= 500 or resp.status_code in (401, 403):
        raise ConnectorError(f"Vapi error {resp.status_code}")
    if not resp.is_redirect or not resp.headers.get("location"):
        raise UnknownId(f"No recording for call {call_id}")
    return resp.headers["location"]


async def list_calls(phone_number_id: str, created_after: str) -> list[dict[str, Any]]:
    calls = await _api(
        "GET", "/call", params={"phoneNumberId": phone_number_id, "createdAtGt": created_after}
    )
    return calls if isinstance(calls, list) else []


async def auth_test(conn: ConnectorConnection, secrets: dict[str, str]) -> Outcome:
    number = await _api("GET", f"/phone-number/{need(conn.config, 'phone_number_id')}")
    return Outcome(True, f"Number {number.get('number', '')} is ready")


async def tool_test(
    tool: str, data: dict[str, Any], conn: ConnectorConnection, secrets: dict[str, str]
) -> Outcome:
    if tool != "vapi.place_call":
        raise ConnectorError(f"{tool} can't be tested")
    spec = assistant(
        "Hello, this is a short test call from Lucia. Goodbye.",
        "This is a test call. Say goodbye and end the call.",
        {"firm_id": str(conn.firm_id), "connection_id": str(conn.id)},
        max_seconds=20,
    )
    return Outcome(True, f"Call {await place_call(conn, data['to'], spec)} queued to {data['to']}")


async def enable_inbound(
    conn: ConnectorConnection, secrets: dict[str, str]
) -> tuple[dict[str, Any], str]:
    raise conflict("Vapi connections only place calls; inbound calls aren't supported")
