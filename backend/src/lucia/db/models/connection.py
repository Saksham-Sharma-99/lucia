import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lucia.db.base import Base, IdMixin, TimestampMixin

ConnectionStatus = Literal["pending", "connected", "error"]
Health = Literal["unknown", "ok", "degraded", "revoked"]


class ConnectorConnection(IdMixin, TimestampMixin, Base):
    """A firm's installation of a connector. Secrets are Fernet-encrypted and never returned."""

    __table_args__ = (
        CheckConstraint("status IN ('pending','connected','error')", name="status"),
        CheckConstraint("health IN ('unknown','ok','degraded','revoked')", name="health"),
        Index("connector_connections_firm_id_connector_idx", "firm_id", "connector"),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    connector: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    status: Mapped[ConnectionStatus] = mapped_column(Text, server_default="pending")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    encrypted_secrets: Mapped[str | None] = mapped_column(Text)
    secret_hints: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    consent_nonce: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    health: Mapped[Health] = mapped_column(Text, server_default="unknown")
    test_results: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_inbound_type: Mapped[str | None] = mapped_column(Text)
