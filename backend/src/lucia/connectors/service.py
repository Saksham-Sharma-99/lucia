import secrets as pysecrets
import uuid

import httpx
from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.connectors import gmail, slack, vapi
from lucia.connectors import schemas as s
from lucia.connectors.base import (
    Adapter,
    ConnectorError,
    Installed,
    OAuthAdapter,
    Outcome,
    hook_url,
    reject_system_keys,
)
from lucia.core.errors import FieldError, ProblemError, conflict, invalid
from lucia.core.security import decrypt_json, encrypt_json, secret_hint, sign_state, unsign_state
from lucia.core.time import utcnow
from lucia.db.models import (
    Agent,
    CompiledAgentFirmMapping,
    ConnectorConnection,
    Firm,
    RegistryEntry,
)
from lucia.db.queries import get_or_404

C = ConnectorConnection
ADAPTERS: dict[str, Adapter] = {"slack": slack, "gmail": gmail, "vapi": vapi}
OAUTH: dict[str, OAuthAdapter] = {"slack": slack, "gmail": gmail}
PROVIDER_ERRORS = (ConnectorError, httpx.HTTPError)


def safe_message(exc: Exception) -> str:
    """Provider errors are safe to show; transport errors only by type (no URLs or secrets)."""
    if isinstance(exc, ConnectorError):
        return str(exc)
    return f"Network error talking to the provider ({type(exc).__name__})"


async def to_out(session: AsyncSession, conns: list[C]) -> list[s.ConnectionOut]:
    """Connection DTOs, each with the agents whose mappings bind it (one query for all)."""
    M = CompiledAgentFirmMapping
    used_by: dict[str, list[str]] = {}
    if conns:
        rows = await session.execute(
            select(M.identities, Agent.handle)
            .join(Agent, Agent.id == M.agent_id)
            .where(M.firm_id.in_({c.firm_id for c in conns}))
            .order_by(Agent.handle)
        )
        for identities, handle in rows:
            for conn_id in identities.values():
                used_by.setdefault(conn_id, []).append(handle)
    return [
        s.ConnectionOut.model_validate(c).model_copy(
            update={
                "has_consent_link": c.consent_nonce is not None,
                "webhook_url": hook_url(c.connector),
                "used_by": sorted(set(used_by.get(str(c.id), []))),
            }
        )
        for c in conns
    ]


def set_secrets(c: C, values: dict[str, str]) -> None:
    c.encrypted_secrets = encrypt_json(values) if values else None
    c.secret_hints = {k: secret_hint(v) for k, v in values.items()}


async def list_for_firm(session: AsyncSession, firm_id: uuid.UUID) -> list[C]:
    await get_or_404(session, Firm, firm_id, "Firm")
    return list(
        await session.scalars(
            select(C).where(C.firm_id == firm_id).order_by(C.connector, C.created_at)
        )
    )


async def create(session: AsyncSession, firm_id: uuid.UUID, body: s.ConnectionCreate) -> C:
    firm = await get_or_404(session, Firm, firm_id, "Firm")
    c = C(
        firm_id=firm_id,
        connector=body.connector,
        label=body.label,
        status="pending",
        config={},
        secret_hints={},
        test_results={},
    )
    try:
        secrets = await ADAPTERS[body.connector].setup(c, firm, body.config, body.secrets)
    except PROVIDER_ERRORS as exc:
        raise ProblemError(502, "Provisioning failed", safe_message(exc)) from exc
    set_secrets(c, secrets)
    session.add(c)
    await session.commit()
    return c


async def patch(session: AsyncSession, c: C, body: s.ConnectionPatch) -> C:
    if body.label is not None:
        c.label = body.label
    if body.config is not None:
        reject_system_keys(body.config, ADAPTERS[c.connector].SYSTEM_KEYS)
        c.config = {**c.config, **body.config}
    if body.secrets is not None:
        set_secrets(c, {**decrypt_json(c.encrypted_secrets), **body.secrets})
    await session.commit()
    return c


async def delete(session: AsyncSession, c: C) -> None:
    M = CompiledAgentFirmMapping
    if await session.scalar(
        select(M.id).where(M.firm_id == c.firm_id, M.identities[c.connector].astext == str(c.id))
    ):
        raise conflict("A mapping uses this connection. Rebind or remove the mapping first.")
    await session.delete(c)
    await session.commit()


async def consent_link(session: AsyncSession, c: C) -> str:
    """A fresh link; storing a new nonce invalidates any earlier one."""
    adapter = OAUTH.get(c.connector)
    if adapter is None:
        raise conflict(f"{c.connector} connections do not use a consent link")
    if not adapter.configured():
        raise conflict(f"The platform {c.connector} app is not configured")
    c.consent_nonce = nonce = pysecrets.token_urlsafe(16)
    await session.commit()
    return adapter.consent_url(
        sign_state({"connection_id": str(c.id), "nonce": nonce}, f"consent:{c.connector}")
    )


async def complete_consent(session: AsyncSession, connector: str, state: str, code: str) -> C:
    """Verify the signed state and one-time nonce, exchange the code and mark it connected.
    The row lock makes a replayed callback wait, then fail on the cleared nonce; it is held
    across the provider exchange (bounded by the 15s HTTP timeout)."""
    data = unsign_state(state, f"consent:{connector}") or {}
    c = None
    if data:  # populate_existing: reread the nonce under the lock, not a cached copy
        c = await session.get(
            C, uuid.UUID(data["connection_id"]), with_for_update=True, populate_existing=True
        )
    if (
        c is None
        or c.connector != connector
        or not c.consent_nonce
        or not pysecrets.compare_digest(c.consent_nonce, data["nonce"])
    ):
        raise ConnectorError("This link is invalid or was already used.")
    installed: Installed = await OAUTH[connector].exchange(code)
    c.label = installed.label or c.label
    c.config = {**c.config, **installed.config}
    set_secrets(c, installed.secrets)
    c.status, c.health, c.connected_at, c.consent_nonce = "connected", "unknown", utcnow(), None
    await session.commit()
    return c


def _require_connected(c: C) -> None:
    if c.status != "connected":
        raise conflict("Finish connecting first")


async def _check_tool_input(session: AsyncSession, c: C, body: s.TestRequest) -> None:
    entry = await session.scalar(
        select(RegistryEntry).where(RegistryEntry.kind == "tool", RegistryEntry.name == body.tool)
    )
    if entry is None or entry.connector != c.connector or not entry.available:
        raise invalid(
            [
                FieldError(
                    path="/tool",
                    code="unknown_tool",
                    message=f"{body.tool} is not a {c.connector} tool",
                )
            ]
        )
    if errors := [
        FieldError(
            path="/input" + "".join(f"/{p}" for p in e.absolute_path),
            code="invalid_input",
            message=e.message,
        )
        for e in Draft202012Validator(entry.params_schema).iter_errors(body.input)
    ]:
        raise invalid(errors)


async def test(session: AsyncSession, c: C, body: s.TestRequest) -> s.TestOutcome:
    """Auth test (no tool) or one tool test. The result is stored; failures are not errors."""
    _require_connected(c)
    if body.tool:
        await _check_tool_input(session, c, body)
    adapter, secrets = ADAPTERS[c.connector], decrypt_json(c.encrypted_secrets)
    try:
        outcome = await (
            adapter.tool_test(body.tool, body.input, c, secrets)
            if body.tool
            else adapter.auth_test(c, secrets)
        )
    except PROVIDER_ERRORS as exc:
        outcome = Outcome(False, safe_message(exc))
    c.last_tested_at = now = utcnow()
    c.test_results = {
        **c.test_results,
        body.tool or "auth": {"ok": outcome.ok, "at": now.isoformat(), "detail": outcome.detail},
    }
    if not body.tool:
        c.health = "ok" if outcome.ok else "degraded"
    await session.commit()
    return s.TestOutcome(ok=outcome.ok, detail=outcome.detail)


async def enable_inbound(session: AsyncSession, c: C) -> s.InboundSetup:
    _require_connected(c)
    try:
        config, detail = await ADAPTERS[c.connector].enable_inbound(
            c, decrypt_json(c.encrypted_secrets)
        )
    except PROVIDER_ERRORS as exc:
        raise ProblemError(502, "Enabling inbound events failed", safe_message(exc)) from exc
    c.config = {**c.config, **config}
    await session.commit()
    return s.InboundSetup(webhook_url=hook_url(c.connector), detail=detail)


async def record_inbound(
    session: AsyncSession, connector: str, key: str, value: str, kind: str
) -> int:
    """Stamp the last inbound event on every connection whose `config[key]` matches."""
    conns = list(
        await session.scalars(
            select(C).where(C.connector == connector, C.config[key].astext == value)
        )
    )
    for c in conns:
        c.last_inbound_at, c.last_inbound_type = utcnow(), kind
    await session.commit()
    return len(conns)
