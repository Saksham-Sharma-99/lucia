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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lucia.db.base import Base, IdMixin, TimestampMixin

RunStatus = Literal[
    "CREATED",
    "ACTIVE",
    "TAKEN_OVER",
    "PAUSED",
    "AWAITING_CONFIRMATION",
    "COMPLETED",
    "ENDED",
    "FAILED",
]
LIVE = ("CREATED", "ACTIVE", "TAKEN_OVER", "PAUSED", "AWAITING_CONFIRMATION")
CLAIMABLE = ("CREATED", "ACTIVE", "AWAITING_CONFIRMATION")
FINISHED = ("COMPLETED", "ENDED", "FAILED")
TaskStatus = Literal["TODO", "IN_PROGRESS", "WAITING", "BLOCKED", "DONE", "SKIPPED", "FAILED"]
TERMINAL_TASK = ("DONE", "SKIPPED", "FAILED")
EpisodeStatus = Literal[
    "scheduled", "armed", "pending", "deferred", "running", "completed", "failed", "superseded"
]
ONE_LIVE_RUN = "agent_runs_one_active"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({','.join(repr(v) for v in values)})"


LIVE_PREDICATE = _in("status", LIVE)  # literal SQL: ON CONFLICT must match the index predicate


class AgentRun(IdMixin, TimestampMixin, Base):
    """One agent working on one subject (DATA_MODEL §3.6)."""

    __table_args__ = (
        CheckConstraint(_in("status", (*LIVE, *FINISHED)), name="status"),
        CheckConstraint(
            "(status = 'ACTIVE' AND coalesce(substatus IN ('RUNNING','WAITING','ATTENTION'), true))"
            " OR (status = 'PAUSED'"
            " AND substatus IN ('kill_switch','repeated_failure','subject_closed'))"
            " OR (status NOT IN ('ACTIVE','PAUSED') AND substatus IS NULL)",
            name="substatus",
        ),
        CheckConstraint("origin IN ('playground','slack','api','schedule')", name="origin"),
        UniqueConstraint("id", "firm_id"),
        ForeignKeyConstraint(
            ["mapping_id", "firm_id"],
            ["compiled_agent_firm_mappings.id", "compiled_agent_firm_mappings.firm_id"],
        ),
        ForeignKeyConstraint(["subject_id", "firm_id"], ["subjects.id", "subjects.firm_id"]),
        Index(
            ONE_LIVE_RUN,
            "agent_id",
            "subject_id",
            unique=True,
            postgresql_where=LIVE_PREDICATE,
        ),
        Index("agent_runs_firm_id_status_idx", "firm_id", "status"),
        Index("agent_runs_subject_id_idx", "subject_id"),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    mapping_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))
    agent_prompt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_prompts.id")
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[RunStatus] = mapped_column(Text, server_default="CREATED")
    substatus: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    goal: Mapped[str] = mapped_column(Text, server_default="")
    completion_criteria: Mapped[str] = mapped_column(Text, server_default="")
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    takeover: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cycle: Mapped[int] = mapped_column(Integer, server_default="0")
    step_count: Mapped[int] = mapped_column(Integer, server_default="0")
    next_wake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_epoch: Mapped[int] = mapped_column(BigInteger, server_default="0")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_reason: Mapped[str | None] = mapped_column(Text)


class RunTask(IdMixin, TimestampMixin, Base):
    """A unit of work in a run, with an append-only plan (DATA_MODEL §3.7, §4.3)."""

    __table_args__ = (
        CheckConstraint(
            _in("status", ("TODO", "IN_PROGRESS", "WAITING", "BLOCKED", *TERMINAL_TASK)),
            name="status",
        ),
        CheckConstraint("created_by IN ('triage','recurrence','human')", name="created_by"),
        UniqueConstraint("run_id", "key"),
        UniqueConstraint("id", "firm_id"),
        ForeignKeyConstraint(["run_id", "firm_id"], ["agent_runs.id", "agent_runs.firm_id"]),
        Index("run_tasks_run_id_status_idx", "run_id", "status"),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    key: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    target: Mapped[dict[str, Any]] = mapped_column(JSONB)
    title: Mapped[str] = mapped_column(Text)
    goal: Mapped[str] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[TaskStatus] = mapped_column(Text, server_default="TODO")
    created_by: Mapped[str] = mapped_column(Text)
    origin_episode_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    depends_on: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    plan_appends: Mapped[int] = mapped_column(Integer, server_default="0")
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    follow_up: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Episode(IdMixin, TimestampMixin, Base):
    """One trigger on a run: past, queued or future (DATA_MODEL §3.8)."""

    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('scheduled','user_input','user_response','external_response',"
            "'handback','retry','delegation')",
            name="trigger_type",
        ),
        CheckConstraint(
            "status IN ('scheduled','armed','pending','deferred','running','completed',"
            "'failed','superseded')",
            name="status",
        ),
        CheckConstraint("(trigger_type = 'scheduled') = (source IS NOT NULL)", name="source_iff"),
        CheckConstraint(
            "source IS NULL OR source IN ('ladder','dynamic','recurrence','deferral','retry',"
            "'plan_wait','reconcile')",
            name="source",
        ),
        CheckConstraint("dedup_key ~ '^[a-z_]+:'", name="dedup_key_format"),
        ForeignKeyConstraint(["run_id", "firm_id"], ["agent_runs.id", "agent_runs.firm_id"]),
        Index("episodes_arm_idx", "due_at", postgresql_where="status = 'scheduled'"),
        Index("episodes_refire_idx", "due_at", postgresql_where="status = 'armed'"),
        Index("episodes_pending_idx", "run_id", "queued_at", postgresql_where="status = 'pending'"),
        Index(
            "episodes_one_running_key",
            "run_id",
            unique=True,
            postgresql_where="status = 'running'",
        ),
        Index(
            "episodes_live_followup_key",
            "task_id",
            unique=True,
            postgresql_where=("status IN ('scheduled','armed') AND source IN ('ladder','dynamic')"),
        ),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run_tasks.id")
    )
    trigger_type: Mapped[str] = mapped_column(Text)
    status: Mapped[EpisodeStatus] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default="{}")
    dedup_key: Mapped[str] = mapped_column(Text, unique=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    rung: Mapped[int | None] = mapped_column(Integer)
    attempt: Mapped[int | None] = mapped_column(Integer)
    guard_version: Mapped[int] = mapped_column(Integer, server_default="0")
    celery_task_id: Mapped[str | None] = mapped_column(Text)
    lease_epoch: Mapped[int | None] = mapped_column(BigInteger)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default="0")
