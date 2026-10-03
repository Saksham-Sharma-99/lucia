import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import AuditLog


async def audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    firm_id: uuid.UUID | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Adds an audit row; the caller's transaction commits it."""
    session.add(
        AuditLog(
            firm_id=firm_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            data=data or {},
        )
    )
