"""Public inbound webhooks. They verify the sender and record the last event; a Vapi
end-of-call report also resumes the task that placed the call. Bodies are never logged."""

import base64
import binascii
import hmac
import json
from typing import Any, cast

from fastapi import Header, Query, Request

from lucia.api.tags import api_router
from lucia.auth.deps import DbSession
from lucia.connectors import slack
from lucia.connectors.service import record_inbound
from lucia.connectors.slack_ingest import ingest_event
from lucia.core.config import get_settings
from lucia.core.errors import ProblemError
from lucia.core.schema import Read
from lucia.harness.tools.vapi_tool import ingest_report

router = api_router("hooks", "/hooks", public=True)


class HookAck(Read):
    ok: bool = True
    recorded: int = 0
    challenge: str | None = None


def _obj(value: Any) -> dict[str, Any]:
    """Provider payloads are untrusted: treat anything that is not an object as empty."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _require_secret(got: str, expected: str) -> None:
    # Compare bytes: str compare_digest raises on non-ASCII input.
    if not expected or not hmac.compare_digest(got.encode(), expected.encode()):
        raise ProblemError(401, "Invalid signature")


async def _json(request: Request) -> dict[str, Any]:
    try:
        data = json.loads(await request.body())
    except ValueError as exc:
        raise ProblemError(400, "Invalid JSON") from exc
    if not isinstance(data, dict):
        raise ProblemError(400, "Expected a JSON object")
    return cast(dict[str, Any], data)


@router.post("/slack", summary="Slack Events API", operation_id="slackHook")
async def slack_hook(
    request: Request,
    session: DbSession,
    x_slack_request_timestamp: str = Header(default=""),
    x_slack_signature: str = Header(default=""),
) -> HookAck:
    if not slack.verify_signature(
        await request.body(), x_slack_request_timestamp, x_slack_signature
    ):
        raise ProblemError(401, "Invalid signature")
    body = await _json(request)
    if body.get("type") == "url_verification":
        return HookAck(challenge=str(body.get("challenge", "")))
    if body.get("type") != "event_callback":
        return HookAck()
    event = _obj(body.get("event"))
    team = str(body.get("team_id", ""))
    await ingest_event(session, team, event)
    kind = f"slack.{event.get('type', 'unknown')}"
    return HookAck(recorded=await record_inbound(session, "slack", "team_id", team, kind))


@router.post("/gmail", summary="Gmail Pub/Sub push", operation_id="gmailHook")
async def gmail_hook(
    request: Request, session: DbSession, token: str = Query(default="")
) -> HookAck:
    _require_secret(token, get_settings().google_pubsub_verification_token)
    message = _obj((await _json(request)).get("message"))
    try:
        mailbox = str(json.loads(base64.b64decode(message.get("data", "")))["emailAddress"])
    except (ValueError, KeyError, TypeError, AttributeError, binascii.Error) as exc:
        raise ProblemError(400, "Invalid Pub/Sub message") from exc
    count = await record_inbound(session, "gmail", "mailbox", mailbox.lower(), "gmail.message")
    return HookAck(recorded=count)


@router.post("/vapi", summary="Vapi server messages", operation_id="vapiHook")
async def vapi_hook(
    request: Request, session: DbSession, x_vapi_secret: str = Header(default="")
) -> HookAck:
    # No secret configured (dev): calls are placed without one, so none is required. Production
    # refuses to start with Vapi and no secret (core/config.py).
    if secret := get_settings().vapi_webhook_secret:
        _require_secret(x_vapi_secret, secret)
    message = _obj((await _json(request)).get("message"))
    if message.get("type") == "end-of-call-report":
        await ingest_report(session, message, source="webhook")
    call = _obj(message.get("call"))
    number = call.get("phoneNumberId")
    if not number:
        return HookAck()
    kind = f"vapi.{message.get('type', 'unknown')}"
    return HookAck(
        recorded=await record_inbound(session, "vapi", "phone_number_id", str(number), kind)
    )
