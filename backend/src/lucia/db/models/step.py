import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lucia.db.base import Base, IdMixin, TimestampMixin

StepKind = Literal["llm", "tool", "subagent", "human", "policy", "guardrail", "system"]
StepStatus = Literal[
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "BLOCKED_BY_POLICY",
    "BLOCKED_BY_GUARDRAIL",
    "DEFERRED",
    "AWAITING_CALLBACK",
]


class AgentRunStep(IdMixin, TimestampMixin, Base):
    """One executed action. Planned work lives in run_tasks.plan, never here (D17)."""

    __table_args__ = (
        CheckConstraint(
            "kind IN ('llm','tool','subagent','human','policy','guardrail','system')", name="kind"
        ),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','BLOCKED_BY_POLICY',"
            "'BLOCKED_BY_GUARDRAIL','DEFERRED','AWAITING_CALLBACK')",
            name="status",
        ),
        CheckConstraint("actor IN ('agent','human','system')", name="actor"),
        UniqueConstraint("run_id", "seq"),
        ForeignKeyConstraint(["run_id", "firm_id"], ["agent_runs.id", "agent_runs.firm_id"]),
        Index("agent_run_steps_task_id_plan_item_id_idx", "task_id", "plan_item_id"),
        Index(
            "agent_run_steps_contact_sends_idx",
            "contact_point_id",
            "started_at",
            postgresql_where="kind = 'tool' AND status IN ('SUCCEEDED','AWAITING_CALLBACK')",
        ),
        Index(
            "agent_run_steps_awaiting_idx",
            "started_at",
            postgresql_where="status = 'AWAITING_CALLBACK'",
        ),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run_tasks.id")
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("episodes.id")
    )
    plan_item_id: Mapped[str | None] = mapped_column(Text)
    parent_step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_run_steps.id")
    )
    seq: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[StepKind] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    tool: Mapped[str | None] = mapped_column(Text)
    status: Mapped[StepStatus] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    lease_epoch: Mapped[int] = mapped_column(BigInteger)
    actor: Mapped[str] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    summary: Mapped[str | None] = mapped_column(Text)
    external_ref: Mapped[str | None] = mapped_column(Text)
    contact_point_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact_points.id")
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunStepLog(IdMixin, TimestampMixin, Base):
    __table_args__ = (
        CheckConstraint("level IN ('debug','info','warn','error')", name="level"),
        Index("run_step_logs_run_id_at_idx", "run_id", "at"),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    level: Mapped[str] = mapped_column(Text, server_default="info")
    stage: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
