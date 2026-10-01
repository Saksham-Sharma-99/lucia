"""Connector adapters: thin httpx wrappers per provider (no vendor SDKs in this phase).
Every adapter module implements `Adapter`; the connections service only dispatches."""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

import httpx

from lucia.core.config import get_settings
from lucia.core.errors import FieldError, invalid
from lucia.core.time import utcnow
from lucia.db.models import ConnectorConnection, Firm

INBOUND_FRESH = timedelta(minutes=30)


class ConnectorError(Exception):
    """A provider call failed. The message is safe to show the builder (no secrets)."""


@dataclass
class Outcome:
    ok: bool
    detail: str


@dataclass
class Installed:
    """What an OAuth callback produced."""

    label: str
    config: dict[str, Any]
    secrets: dict[str, str] = field(default_factory=dict)


class Adapter(Protocol):
    SYSTEM_KEYS: frozenset[str]  # config keys the provider owns; builders cannot set them

    def configured(self) -> bool: ...

    async def setup(
        self,
        conn: ConnectorConnection,
        firm: Firm,
        config: dict[str, Any],
        secrets: dict[str, str],
    ) -> dict[str, str]:
        """Prepare a new connection; returns the secrets to store encrypted."""
        ...

    async def auth_test(self, conn: ConnectorConnection, secrets: dict[str, str]) -> Outcome: ...

    async def tool_test(
        self, tool: str, data: dict[str, Any], conn: ConnectorConnection, secrets: dict[str, str]
    ) -> Outcome: ...

    async def enable_inbound(
        self, conn: ConnectorConnection, secrets: dict[str, str]
    ) -> tuple[dict[str, Any], str]: ...


class OAuthAdapter(Adapter, Protocol):
    def consent_url(self, state: str) -> str: ...

    async def exchange(self, code: str) -> Installed: ...


def need(values: dict[str, Any], key: str) -> Any:
    """A stored secret or provisioned config value; missing means the connection is broken."""
    if not values.get(key):
        raise ConnectorError(f"Connection is missing {key}; reconnect it")
    return values[key]


def http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=15.0)


def callback_url(provider: str) -> str:
    return f"{get_settings().public_base_url}/api/v1/oauth/{provider}/callback"


def hook_url(connector: str) -> str:
    return f"{get_settings().public_base_url}/api/v1/hooks/{connector}"


def reject_system_keys(config: dict[str, Any], keys: frozenset[str]) -> None:
    if bad := sorted(set(config) & keys):
        raise invalid(
            [
                FieldError(
                    path=f"/config/{k}",
                    code="read_only",
                    message="Set by the provider; cannot be changed",
                )
                for k in bad
            ]
        )


async def oauth_setup(
    conn: ConnectorConnection,
    config: dict[str, Any],
    secrets: dict[str, str],
    keys: frozenset[str],
) -> dict[str, str]:
    """OAuth connections start pending; their secrets arrive through the consent link."""
    reject_system_keys(config, keys)
    if secrets:
        raise invalid(
            [
                FieldError(
                    path="/secrets",
                    code="read_only",
                    message="Connect with the consent link instead",
                )
            ]
        )
    conn.config = config
    return {}


def inbound_outcome(conn: ConnectorConnection, prefix: str, ask: str) -> Outcome:
    """Inbound tools pass when a matching event arrived recently."""
    at, kind = conn.last_inbound_at, conn.last_inbound_type or ""
    if at and kind.startswith(prefix) and utcnow() - at <= INBOUND_FRESH:
        return Outcome(True, f"Received {kind} at {at.isoformat()}")
    return Outcome(False, f"No recent event. {ask}, then retest.")
