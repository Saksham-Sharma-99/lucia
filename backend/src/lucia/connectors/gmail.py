import base64
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlencode

from lucia.connectors.base import (
    ConnectorError,
    Installed,
    Outcome,
    callback_url,
    http,
    inbound_outcome,
    need,
    oauth_setup,
)
from lucia.core.config import get_settings
from lucia.db.models import ConnectorConnection, Firm

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = " ".join(
    f"https://www.googleapis.com/auth/gmail.{s}" for s in ("send", "readonly", "modify")
)
SYSTEM_KEYS = frozenset({"mailbox", "watch_expiration"})


def configured() -> bool:
    s = get_settings()
    return bool(s.google_oauth_client_id and s.google_oauth_client_secret)


async def setup(
    conn: ConnectorConnection, firm: Firm, config: dict[str, Any], secrets: dict[str, str]
) -> dict[str, str]:
    return await oauth_setup(conn, config, secrets, SYSTEM_KEYS)


def consent_url(state: str) -> str:
    q = {
        "client_id": get_settings().google_oauth_client_id,
        "redirect_uri": callback_url("google"),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(q)}"


async def _token(**form: str) -> dict[str, Any]:
    s = get_settings()
    async with http() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                **form,
                "client_id": s.google_oauth_client_id,
                "client_secret": s.google_oauth_client_secret,
            },
        )
    data: dict[str, Any] = resp.json()
    if "access_token" not in data:
        raise ConnectorError(f"Google token error: {data.get('error', resp.status_code)}")
    return data


async def _access_token(secrets: dict[str, str]) -> str:
    form = {"grant_type": "refresh_token", "refresh_token": need(secrets, "refresh_token")}
    return (await _token(**form))["access_token"]


async def _api(
    method: str, path: str, token: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    async with http() as client:
        resp = await client.request(
            method, f"{API}{path}", json=body, headers={"Authorization": f"Bearer {token}"}
        )
    data: dict[str, Any] = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        message = (data.get("error") or {}).get("message", "")
        raise ConnectorError(f"Gmail error {resp.status_code}: {message}".strip(": "))
    return data


async def exchange(code: str) -> Installed:
    data = await _token(
        grant_type="authorization_code", code=code, redirect_uri=callback_url("google")
    )
    if "refresh_token" not in data:
        raise ConnectorError("Google did not return a refresh token; retry the consent link")
    mailbox = (await _api("GET", "/profile", data["access_token"]))["emailAddress"].lower()
    return Installed(
        label=mailbox, config={"mailbox": mailbox}, secrets={"refresh_token": data["refresh_token"]}
    )


async def auth_test(conn: ConnectorConnection, secrets: dict[str, str]) -> Outcome:
    profile = await _api("GET", "/profile", await _access_token(secrets))
    return Outcome(True, f"Connected to {profile['emailAddress']}")


def _raw_email(sender: str, to: str) -> str:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, "Lucia test email"
    msg.set_content("This is a test email sent by Lucia to check the connection.")
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


async def tool_test(
    tool: str, data: dict[str, Any], conn: ConnectorConnection, secrets: dict[str, str]
) -> Outcome:
    if tool == "gmail.send_email":
        raw = _raw_email(conn.config.get("mailbox", "me"), data["to"])
        await _api("POST", "/messages/send", await _access_token(secrets), {"raw": raw})
        return Outcome(True, f"Sent a test email to {data['to']}")
    return inbound_outcome(conn, "gmail.", "Email the mailbox")


async def enable_inbound(
    conn: ConnectorConnection, secrets: dict[str, str]
) -> tuple[dict[str, Any], str]:
    topic = get_settings().google_pubsub_topic
    if not topic:
        raise ConnectorError("GOOGLE_PUBSUB_TOPIC is not set")
    watch = await _api(
        "POST", "/watch", await _access_token(secrets), {"topicName": topic, "labelIds": ["INBOX"]}
    )
    return (
        {"watch_expiration": watch.get("expiration")},
        "Gmail now pushes new mail to the Pub/Sub topic",
    )
