"""Public OAuth callbacks. The signed state and one-time nonce stand in for a session."""

import html
from typing import Literal

from fastapi import Response
from fastapi.responses import HTMLResponse, RedirectResponse

from lucia.api.tags import api_router
from lucia.auth.deps import DbSession
from lucia.connectors import service
from lucia.core.config import get_settings

router = api_router("oauth", "/oauth", public=True)
CONNECTOR = {"google": "gmail", "slack": "slack"}
CALLBACK_DOCS = {
    "response_class": Response,
    "responses": {
        303: {"description": "Connected; redirects to the firm page"},
        400: {"description": "HTML error page (bad or used link, declined consent)"},
    },
}


def _error_page(message: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><title>Lucia</title>"
        "<body style='font-family:system-ui;padding:3rem'><h1>Could not connect</h1>"
        f"<p>{html.escape(message)}</p><p>Ask your Lucia contact for a new link.</p></body>",
        status_code=400,
    )


async def _callback(
    provider: Literal["google", "slack"],
    session: DbSession,
    code: str | None,
    state: str | None,
    error: str | None,
) -> Response:
    if error:
        return _error_page(f"The request was declined ({error}).")
    if not code or not state:
        return _error_page("The link is incomplete.")
    try:
        conn = await service.complete_consent(session, CONNECTOR[provider], state, code)
    except service.PROVIDER_ERRORS as exc:
        return _error_page(service.safe_message(exc))
    return RedirectResponse(
        f"{get_settings().frontend_base_url}/firms/{conn.firm_id}"
        f"?tab=connections&connected={conn.id}",
        status_code=303,
    )


@router.get(
    "/google/callback",
    summary="Google consent callback",
    operation_id="googleOauthCallback",
    **CALLBACK_DOCS,
)
async def google_callback(
    session: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    return await _callback("google", session, code, state, error)


@router.get(
    "/slack/callback",
    summary="Slack install callback",
    operation_id="slackOauthCallback",
    **CALLBACK_DOCS,
)
async def slack_callback(
    session: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    return await _callback("slack", session, code, state, error)
