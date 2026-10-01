"""Activation checklist: every connector the version uses must be bound to a connected
connection of the same firm and connector."""

import uuid
from typing import Any

from lucia.db.models import ConnectorConnection
from lucia.mappings.schemas import ChecklistItem


def build_checklist(
    firm_id: uuid.UUID,
    config: dict[str, Any],
    identities: dict[str, str],
    connections: dict[str, ConnectorConnection],
) -> list[ChecklistItem]:
    """`identities` and `connections` are keyed by connection id as a string (as stored)."""
    items: list[ChecklistItem] = []
    for connector in (c["connector"] for c in config.get("capabilities", [])):
        conn_id = identities.get(connector)
        conn = connections.get(conn_id) if conn_id else None
        if conn_id is None:
            ok, reason = False, f"Pick a {connector} connection"
        elif conn is None or conn.firm_id != firm_id:
            ok, reason = False, "Connection not found for this firm"
        elif conn.connector != connector:
            ok, reason = False, f"Connection is {conn.connector}, not {connector}"
        elif conn.status != "connected":
            ok, reason = False, f"Connection is {conn.status}; finish connecting it"
        else:
            ok, reason = True, f"Bound to {conn.label}"
        items.append(
            ChecklistItem(
                connector=connector,
                connection_id=uuid.UUID(conn_id) if conn_id else None,
                ok=ok,
                reason=reason,
            )
        )
    return items
