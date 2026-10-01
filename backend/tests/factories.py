import copy
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.connectors.service import set_secrets
from lucia.core.time import utcnow
from lucia.db.models import ConnectorConnection, RegistryEntry
from lucia.registry.snapshot import RegistrySnapshot
from lucia.registry.sync import catalog_rows

ALLOWED = ["gpt-5.6", "gpt-5.6-sol", "gpt-5.6-luna"]
ZERO = "00000000-0000-0000-0000-000000000000"
Json = dict[str, Any]

BASE_CONFIG: dict[str, Any] = {
    "system_prompt": "Chase records.",
    "models": {"loop": "gpt-5.6-sol", "guardrail": "gpt-5.6-luna", "judge": "gpt-5.6"},
    "capabilities": [{"connector": "gmail", "tools": ["gmail.send_email", "gmail.read_thread"]}],
    "follow_up": {
        "mode": "fixed_ladder",
        "ladder": [{"channel": "email", "wait_hours": 48, "attempts": 2}],
    },
    "policy_pack": [
        {"rule": "recipient_must_be_contact", "params": {}},
        {"rule": "per_subject_contact_cap", "params": {"n": 3}},
    ],
    "alert_policy": {"default_channels": {"P0": ["slack_dm"], "P1": ["email"], "P2": ["digest"]}},
}


def config(**overrides: Any) -> dict[str, Any]:
    cfg = copy.deepcopy(BASE_CONFIG)
    cfg.update(overrides)
    return cfg


def snapshot() -> RegistrySnapshot:
    snap = RegistrySnapshot()
    buckets = {
        "connector": snap.connectors,
        "tool": snap.tools,
        "policy_rule": snap.policy_rules,
        "channel": snap.channels,
    }
    for row in catalog_rows():
        if row["kind"] in buckets:
            buckets[row["kind"]][row["name"]] = RegistryEntry(**row)
    return snap


async def create_agent(client: AsyncClient, handle: str = "chaser", **extra: Any) -> Json:
    body = {"handle": handle, "name": handle.title(), "config": config(), **extra}
    resp = await client.post("/api/v1/agents", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def create_firm(client: AsyncClient, slug: str = "acme-law", **extra: Any) -> Json:
    body = {
        "name": "Acme Law",
        "slug": slug,
        "timezone": "America/New_York",
        "color": "#123456",
        **extra,
    }
    resp = await client.post("/api/v1/firms", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def pending(client: AsyncClient, firm_id: str, connector: str) -> Json:
    resp = await client.post(
        f"/api/v1/firms/{firm_id}/connections", json={"connector": connector, "label": connector}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def connected(
    db: AsyncSession,
    firm_id: str,
    connector: str,
    config: Json | None = None,
    secrets: dict[str, str] | None = None,
) -> ConnectorConnection:
    """Insert a connected connection directly (skips the OAuth dance)."""
    c = ConnectorConnection(
        firm_id=uuid.UUID(firm_id),
        connector=connector,
        label=connector,
        status="connected",
        config=config or {},
        secret_hints={},
        test_results={},
        connected_at=utcnow(),
    )
    set_secrets(c, secrets or {})
    db.add(c)
    await db.commit()
    return c
