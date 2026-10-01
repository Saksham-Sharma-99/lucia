from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.time import utcnow
from lucia.db.models import RegistryEntry
from lucia.registry import catalog


def _row(kind: str, name: str, display_name: str, description: str, **extra: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "name": name,
        "display_name": display_name,
        "description": description,
        "connector": None,
        "params_schema": {},
        "available": True,
        "risk_tier": None,
        "direction": None,
        "is_async": False,
        **extra,
    }


def catalog_rows() -> list[dict[str, Any]]:
    return [
        *(
            _row(
                "connector",
                c.name,
                c.display_name,
                c.description,
                params_schema=c.params_schema,
                available=c.available,
            )
            for c in catalog.CONNECTORS
        ),
        *(
            _row(
                "tool",
                t.name,
                t.display_name,
                t.description,
                connector=t.connector,
                params_schema=t.params_schema,
                available=t.available,
                risk_tier=t.risk_tier,
                direction=t.direction,
                is_async=t.is_async,
            )
            for t in catalog.TOOLS
        ),
        *(
            _row(
                "policy_rule", r.name, r.display_name, r.description, params_schema=r.params_schema
            )
            for r in catalog.POLICY_RULES
        ),
        *(
            _row(
                "channel",
                ch.name,
                ch.display_name,
                f"Sends with {ch.tool}",
                connector=ch.tool.split(".")[0],
            )
            for ch in catalog.CHANNELS
        ),
        *(
            _row("evidence_kind", e.name, e.display_name, e.description)
            for e in catalog.EVIDENCE_KINDS
        ),
    ]


async def sync_registry(session: AsyncSession) -> None:
    """Upsert catalog entries by (kind, name), bumping `version` on change. Entries that left
    the catalog are marked unavailable, never deleted."""
    existing = {(e.kind, e.name): e for e in await session.scalars(select(RegistryEntry))}
    now = utcnow()
    for row in catalog_rows():
        entry = existing.pop((row["kind"], row["name"]), None)
        if entry is None:
            session.add(RegistryEntry(**row, synced_at=now))
            continue
        if any(getattr(entry, k) != v for k, v in row.items()):
            for k, v in row.items():
                setattr(entry, k, v)
            entry.version += 1
        entry.synced_at = now
    for entry in existing.values():
        if entry.available:
            entry.available = False
            entry.version += 1
    await session.commit()
