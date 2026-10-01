import copy
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.connectors.service import set_secrets
from lucia.core.time import utcnow
from lucia.db.models import ConnectorConnection
from lucia.registry.snapshot import RegistrySnapshot, catalog_snapshot
from lucia.studio.drafter.llm import DrafterError

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
    return catalog_snapshot()


# What the model returns for each section (the drafter's output models), valid for an agent
# with GMAIL_TOOLS. Tests copy one with `draft_output(...)` and override what they need.
GMAIL_TOOLS = ["gmail.send_email", "gmail.read_thread"]
CHANNEL_RUNG: Json = {
    "kind": "channel",
    "channel": "email",
    "wait_hours": 48,
    "attempts": 1,
    "urgency": None,
}
ACTION_RUNG: Json = {
    "kind": "action",
    "action": "escalate",
    "wait_hours": 0,
    "attempts": 1,
    "urgency": "P1",
}
DYNAMIC: Json = {
    "min_hours": 48,
    "max_hours": 120,
    "business_hours": True,
    "channels": ["email"],
    "escalate_after_attempts": 3,
    "escalate_urgency": "P1",
}
_NOTE: Json = {"rationale": "why", "unmapped": []}
DRAFT_OUTPUTS: dict[str, Json] = {
    "CapabilitiesOut": {"tools": GMAIL_TOOLS, **_NOTE},
    "PoliciesOut": {
        "rules": [],
        "ask_on": [],
        "verify_evidence_below": 0.8,
        "urgency_mode": "auto",
        "fixed_urgency": None,
        "p0_channels": ["slack_dm"],
        "p1_channels": ["slack_thread"],
        "p2_channels": ["digest"],
        **_NOTE,
    },
    "SchedulesOut": {
        "mode": "none",
        "ladder": [],
        "dynamic": None,
        "recurrence_every_days": None,
        "max_duration_days": 120,
        "max_steps": 600,
        "on_subject_closed": "end",
        "max_turns_per_episode": 12,
        **_NOTE,
    },
}


def draft_output(model: str, **overrides: Any) -> Json:
    return {**copy.deepcopy(DRAFT_OUTPUTS[model]), **overrides}


class FakeDrafter:
    """Stands in for the model. Streams `deltas`, answers a section from `outputs` (keyed by
    output model name, e.g. "PoliciesOut"), and records the input of every call."""

    def __init__(self) -> None:
        self.deltas = ["## Role\n", "You chase records."]
        self.outputs: dict[str, Json] = copy.deepcopy(DRAFT_OUTPUTS)
        self.error: DrafterError | None = None  # raised by a section call
        self.fail_after: DrafterError | None = None  # raised after the deltas
        self.inputs: list[Json] = []

    async def stream_text(
        self, instructions: str, message: str, seconds: float
    ) -> AsyncIterator[str]:
        self.inputs.append(json.loads(message))
        for delta in self.deltas:
            yield delta
        if self.fail_after:
            raise self.fail_after

    async def run_structured[T: BaseModel](
        self, instructions: str, message: str, output_type: type[T], seconds: float
    ) -> T:
        self.inputs.append(json.loads(message))
        if self.error:
            raise self.error
        return output_type.model_validate(self.outputs[output_type.__name__])


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
