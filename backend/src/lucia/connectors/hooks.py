"""Public inbound webhooks. They verify the sender and record the last event; no runs yet.
Bodies are never logged (they can carry client data)."""

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
from lucia.core.config import get_settings
from lucia.core.errors import ProblemError
from lucia.core.schema import Read

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
    kind = f"slack.{_obj(body.get('event')).get('type', 'unknown')}"
    team = str(body.get("team_id", ""))
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
    _require_secret(x_vapi_secret, get_settings().vapi_webhook_secret)
    message = _obj((await _json(request)).get("message"))
    call = _obj(message.get("call"))
    assistant = _obj(message.get("assistant")).get("id") or call.get("assistantId")
    if not assistant:
        return HookAck()
    kind = f"vapi.{message.get('type', 'unknown')}"
    return HookAck(
        recorded=await record_inbound(session, "vapi", "assistant_id", str(assistant), kind)
    )
