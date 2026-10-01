"""OpenAPI tag convention and the router factory that applies it.

Every operation carries exactly one tag of the form "<audience>:<resource>":
- internal: used only by the agent builder (Studio). This is every API today.
- external: exposed to the Workspace / customers (none yet).
"""

from typing import Literal

from fastapi import APIRouter, Depends

from lucia.auth.deps import current_user
from lucia.core.errors import PROBLEM_RESPONSES

Audience = Literal["internal", "external"]

TAG_DESCRIPTIONS: dict[str, str] = {
    "internal:health": "Liveness of the API and its dependencies.",
    "internal:auth": "Builder login sessions (httpOnly cookie).",
    "internal:firms": "Firms (tenants) and their settings.",
    "internal:registry": "Code-declared connectors, tools, policy rules, channels, evidence kinds.",
    "internal:agents": "Agents and their immutable versions.",
    "internal:connections": "A firm's connector installations, consent links and tests.",
    "internal:oauth": "OAuth callbacks for Gmail and Slack consent links (public).",
    "internal:hooks": "Inbound provider webhooks; record the last event only (public).",
    "internal:mappings": "Which agent version each firm runs, with its identities.",
    "internal:platform": "Which platform-level app registrations are configured.",
}


def tag(audience: Audience, resource: str) -> str:
    name = f"{audience}:{resource}"
    if name not in TAG_DESCRIPTIONS:
        raise ValueError(f"Add {name!r} to TAG_DESCRIPTIONS")
    return name


def openapi_tags() -> list[dict[str, str]]:
    return [{"name": name, "description": desc} for name, desc in TAG_DESCRIPTIONS.items()]


def api_router(
    resource: str, prefix: str = "", *, audience: Audience = "internal", public: bool = False
) -> APIRouter:
    """A router with its one tag, problem+json error docs, and (unless public) a session."""
    return APIRouter(
        prefix=prefix,
        tags=[tag(audience, resource)],
        dependencies=[] if public else [Depends(current_user)],
        responses=PROBLEM_RESPONSES,
    )
