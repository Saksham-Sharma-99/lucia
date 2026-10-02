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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lucia.db.base import Base, IdMixin, TimestampMixin

AttentionKind = Literal[
    "question",
    "verify",
    "out_of_scope",
    "escalation",
    "guardrail_block",
    "uncertain_send",
    "confirm_completion",
    "plan_cap",
    "item_failed",
    "review_low",
]
SRStatus = Literal["open", "answered", "dismissed", "resolved_by_system", "acknowledged"]


class StepResult(IdMixin, TimestampMixin, Base):
    """Findings and attention items in one table (DATA_MODEL §3.12)."""

    __table_args__ = (
        CheckConstraint("type IN ('finding','attention')", name="type"),
        CheckConstraint("urgency IN ('P0','P1','P2')", name="urgency"),
        CheckConstraint(
            "status IN ('open','answered','dismissed','resolved_by_system','acknowledged')",
            name="status",
        ),
        Index(
            "step_results_firm_id_status_idx",
            "firm_id",
            "status",
            postgresql_where="type = 'attention'",
        ),
        Index("step_results_run_id_status_idx", "run_id", "status"),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id")
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run_tasks.id")
    )
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_run_steps.id")
    )
    type: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    urgency: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    summary_public: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    blocking: Mapped[bool] = mapped_column(Boolean, server_default="false")
    status: Mapped[SRStatus] = mapped_column(Text, server_default="open")
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    answered_by: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedup_key: Mapped[str] = mapped_column(Text, unique=True)


class Notification(IdMixin, TimestampMixin, Base):
    __table_args__ = (
        CheckConstraint("channel IN ('conversation','slack_dm','in_app')", name="channel"),
        CheckConstraint("status IN ('queued','sent','failed')", name="status"),
        UniqueConstraint("step_result_id", "channel", "target"),
        Index("notifications_target_read_at_idx", "target", "read_at"),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    step_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("step_results.id")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id")
    )
    channel: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    external_ref: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")


class AuditLog(IdMixin, TimestampMixin, Base):
    """Append-only (trigger). `at` is `created_at`."""

    __table_args__ = (
        CheckConstraint("actor_type IN ('user','slack_user','system','agent')", name="actor_type"),
        Index("audit_logs_entity_type_entity_id_idx", "entity_type", "entity_id"),
    )

    firm_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, index=True)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
