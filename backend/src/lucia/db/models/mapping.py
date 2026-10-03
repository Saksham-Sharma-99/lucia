import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lucia.core.time import utcnow
from lucia.db.base import Base, IdMixin, TimestampMixin

MappingStatus = Literal["active", "inactive"]
# At most one active mapping per (firm, agent): a partial unique index.
ONE_ACTIVE_INDEX = "compiled_agent_firm_mappings_active_firm_id_agent_id_key"


class CompiledAgentFirmMapping(IdMixin, TimestampMixin, Base):
    """The only firm <-> agent link: which version a firm runs, with its identities."""

    __table_args__ = (
        CheckConstraint("status IN ('active','inactive')", name="status"),
        CheckConstraint("ab_weight BETWEEN 0 AND 100", name="ab_weight"),
        UniqueConstraint("id", "firm_id"),  # target of runs' composite FK
        Index(
            ONE_ACTIVE_INDEX,
            "firm_id",
            "agent_id",
            unique=True,
            postgresql_where="status = 'active'",
        ),
    )

    agent_prompt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_prompts.id")
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))
    firm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("firms.id"), index=True
    )
    identities: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    overrides: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    ab_weight: Mapped[int] = mapped_column(Integer, server_default="100")
    status: Mapped[MappingStatus] = mapped_column(Text, server_default="inactive")
    kill_switch: Mapped[bool] = mapped_column(Boolean, server_default="false")
    supersedes_mapping_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compiled_agent_firm_mappings.id")
    )
    mapped_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id"))
    # Python default too, so rows created in one transaction still order by creation.
    mapped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )
