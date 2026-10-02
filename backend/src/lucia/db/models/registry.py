from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lucia.db.base import Base, IdMixin, TimestampMixin

Kind = Literal["connector", "tool", "policy_rule", "channel", "evidence_kind"]


class RegistryEntry(IdMixin, TimestampMixin, Base):
    __table_args__ = (
        UniqueConstraint("kind", "name"),
        CheckConstraint(
            "kind IN ('connector','tool','policy_rule','channel','evidence_kind')",
            name="kind",
        ),
        CheckConstraint(
            "risk_tier IS NULL OR risk_tier IN ('read','internal_write','external_comm')",
            name="risk_tier",
        ),
        CheckConstraint(
            "direction IS NULL OR direction IN ('inbound','outbound')",
            name="direction",
        ),
    )

    kind: Mapped[Kind] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    connector: Mapped[str | None] = mapped_column(Text, index=True)
    display_name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    params_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    risk_tier: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str | None] = mapped_column(Text)
    is_async: Mapped[bool] = mapped_column(Boolean, server_default="false")
    available: Mapped[bool] = mapped_column(Boolean, server_default="true")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
