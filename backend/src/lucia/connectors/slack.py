import hashlib
import hmac
import re
import time
from typing import Any
from urllib.parse import urlencode

from lucia.connectors.base import (
    ConnectorError,
    Installed,
    Outcome,
    callback_url,
    hook_url,
    http,
    inbound_outcome,
    need,
    oauth_setup,
)
from lucia.core.config import get_settings
from lucia.db.models import ConnectorConnection, Firm

API = "https://slack.com/api"
SCOPES = "app_mentions:read,chat:write,channels:history,groups:history,files:write"
SYSTEM_KEYS = frozenset({"team_id", "team_name", "bot_user_id"})
MAX_SKEW_SECONDS = 300
CHANNEL_ID = re.compile(r"[CGD][A-Z0-9]{8,}")


def configured() -> bool:
    s = get_settings()
    return bool(s.slack_client_id and s.slack_client_secret and s.slack_signing_secret)


async def setup(
    conn: ConnectorConnection, firm: Firm, config: dict[str, Any], secrets: dict[str, str]
) -> dict[str, str]:
    return await oauth_setup(conn, config, secrets, SYSTEM_KEYS)


def consent_url(state: str) -> str:
    q = {
        "client_id": get_settings().slack_client_id,
        "scope": SCOPES,
        "redirect_uri": callback_url("slack"),
        "state": state,
    }
    return f"https://slack.com/oauth/v2/authorize?{urlencode(q)}"


async def _call(
    method: str, token: str | None = None, *, params: dict[str, Any] | None = None, **form: Any
) -> dict[str, Any]:
    """Slack answers 200 with `ok: false` on errors."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with http() as client:
        if params is not None:
            resp = await client.get(f"{API}/{method}", params=params, headers=headers)
        elif token:
            resp = await client.post(f"{API}/{method}", json=form, headers=headers)
        else:
            resp = await client.post(f"{API}/{method}", data=form)
    data: dict[str, Any] = resp.json()
    if not data.get("ok"):
        raise ConnectorError(f"Slack error: {data.get('error', 'unknown')}")
    return data


async def exchange(code: str) -> Installed:
    s = get_settings()
    data = await _call(
        "oauth.v2.access",
        code=code,
        client_id=s.slack_client_id,
        client_secret=s.slack_client_secret,
        redirect_uri=callback_url("slack"),
    )
    team = data.get("team") or {}
    return Installed(
        label=team.get("name") or "Slack",
        config={
            "team_id": team.get("id"),
            "team_name": team.get("name"),
            "bot_user_id": data.get("bot_user_id"),
        },
        secrets={"bot_token": data["access_token"]},
    )


async def auth_test(conn: ConnectorConnection, secrets: dict[str, str]) -> Outcome:
    data = await _call("auth.test", need(secrets, "bot_token"))
    return Outcome(True, f"Authenticated as {data.get('user')} in {data.get('team')}")


async def _post_file(token: str, channel: str) -> None:
    body = b"Lucia test file\n"
    up = await _call(
        "files.getUploadURLExternal",
        token,
        params={"filename": "lucia-test.txt", "length": len(body)},
    )
    async with http() as client:
        await client.post(up["upload_url"], content=body)
    await _call(
        "files.completeUploadExternal",
        token,
        channel_id=channel,
        files=[{"id": up["file_id"], "title": "Lucia test file"}],
    )


async def tool_test(
    tool: str, data: dict[str, Any], conn: ConnectorConnection, secrets: dict[str, str]
) -> Outcome:
    if tool == "slack.send_message":
        await _call(
            "chat.postMessage",
            need(secrets, "bot_token"),
            channel=data["channel"],
            text="Lucia test message",
        )
        return Outcome(True, f"Posted to {data['channel']}")
    if tool == "slack.post_file":
        # Uploads take only ids (messages also take names); resolving a name needs channels:read.
        if not CHANNEL_ID.fullmatch(data["channel"]):
            return Outcome(
                False,
                "File uploads need the channel ID (e.g. C0123456789), not its name. "
                "Find it in Slack under the channel's details.",
            )
        await _post_file(need(secrets, "bot_token"), data["channel"])
        return Outcome(True, f"Uploaded a file to {data['channel']}")
    return inbound_outcome(conn, "slack.", "Mention the bot in a channel it is in")


async def enable_inbound(
    conn: ConnectorConnection, secrets: dict[str, str]
) -> tuple[dict[str, Any], str]:
    return {}, f"Set {hook_url('slack')} as the Event Subscriptions URL in the Slack app"


def verify_signature(body: bytes, timestamp: str, signature: str) -> bool:
    secret = get_settings().slack_signing_secret
    if (
        not secret
        or not timestamp.isdigit()
        or abs(time.time() - int(timestamp)) > MAX_SKEW_SECONDS
    ):
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())
