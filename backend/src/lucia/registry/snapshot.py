"""An in-memory view of the registry used by validators."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import RegistryEntry


@dataclass
class RegistrySnapshot:
    connectors: dict[str, RegistryEntry] = field(default_factory=dict)
    tools: dict[str, RegistryEntry] = field(default_factory=dict)
    policy_rules: dict[str, RegistryEntry] = field(default_factory=dict)
    channels: dict[str, RegistryEntry] = field(default_factory=dict)

    def rule_schema(self, rule: str) -> dict[str, Any]:
        return self.policy_rules[rule].params_schema


async def load_snapshot(session: AsyncSession) -> RegistrySnapshot:
    snap = RegistrySnapshot()
    buckets = {
        "connector": snap.connectors,
        "tool": snap.tools,
        "policy_rule": snap.policy_rules,
        "channel": snap.channels,
    }
    for entry in (await session.scalars(select(RegistryEntry))).all():
        bucket = buckets.get(entry.kind)
        if bucket is not None:
            bucket[entry.name] = entry
    return snap
