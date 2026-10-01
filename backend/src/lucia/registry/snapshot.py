"""An in-memory view of the registry used by validators."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import RegistryEntry
from lucia.registry.sync import catalog_rows


@dataclass
class RegistrySnapshot:
    connectors: dict[str, RegistryEntry] = field(default_factory=dict)
    tools: dict[str, RegistryEntry] = field(default_factory=dict)
    policy_rules: dict[str, RegistryEntry] = field(default_factory=dict)
    channels: dict[str, RegistryEntry] = field(default_factory=dict)

    def rule_schema(self, rule: str) -> dict[str, Any]:
        return self.policy_rules[rule].params_schema


def _snapshot(entries: Iterable[RegistryEntry]) -> RegistrySnapshot:
    snap = RegistrySnapshot()
    buckets = {
        "connector": snap.connectors,
        "tool": snap.tools,
        "policy_rule": snap.policy_rules,
        "channel": snap.channels,
    }
    for entry in entries:
        bucket = buckets.get(entry.kind)
        if bucket is not None:
            bucket[entry.name] = entry
    return snap


async def load_snapshot(session: AsyncSession) -> RegistrySnapshot:
    return _snapshot((await session.scalars(select(RegistryEntry))).all())


def catalog_snapshot() -> RegistrySnapshot:
    """The code-declared registry without a database (unit tests, drafter evals)."""
    return _snapshot(RegistryEntry(**row) for row in catalog_rows())
