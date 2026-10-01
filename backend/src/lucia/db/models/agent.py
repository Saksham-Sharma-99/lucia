import uuid
from typing import Any, Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lucia.db.base import Base, IdMixin, TimestampMixin

VersionPolicy = Literal["pin", "follow_active_at_cycle"]
VersionStatus = Literal["active", "archived"]


class Agent(IdMixin, TimestampMixin, Base):
    """Global agent identity. Status is derived from its versions (HLD §0)."""

    __table_args__ = (
        CheckConstraint("handle ~ '^[a-z][a-z0-9_-]{2,31}$'", name="handle_format"),
        CheckConstraint(
            "version_policy IN ('pin','follow_active_at_cycle')", name="version_policy"
        ),
        CheckConstraint("cardinality(use_cases) <= 20", name="use_cases_max"),
    )

    handle: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    use_cases: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    is_template: Mapped[bool] = mapped_column(Boolean, server_default="false", index=True)
    source_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id")
    )
    is_callable: Mapped[bool] = mapped_column(Boolean, server_default="true")
    auto_delegate: Mapped[bool] = mapped_column(Boolean, server_default="false")
    version_policy: Mapped[VersionPolicy] = mapped_column(Text, server_default="pin")


class AgentPrompt(IdMixin, TimestampMixin, Base):
    """One immutable version of an agent's behavior config."""

    __table_args__ = (
        UniqueConstraint("agent_id", "version"),
        CheckConstraint("status IN ('active','archived')", name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[VersionStatus] = mapped_column(Text, server_default="active")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    config_hash: Mapped[str] = mapped_column(Text)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_prompts.id")
    )
    changelog: Mapped[str] = mapped_column(Text, server_default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id"))
