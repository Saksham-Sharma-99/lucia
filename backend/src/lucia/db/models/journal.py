import uuid
from typing import Literal

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lucia.db.base import Base, IdMixin, TimestampMixin

JournalSource = Literal["harness", "agent", "human"]


class JournalEntry(IdMixin, TimestampMixin, Base):
    """The run's running notebook. Append-only (trigger)."""

    __table_args__ = (CheckConstraint("source IN ('harness','agent','human')", name="source"),)

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id"), index=True
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    source: Mapped[JournalSource] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(Text, unique=True)


class JournalSummary(IdMixin, TimestampMixin, Base):
    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id"), index=True
    )
    through_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    text: Mapped[str] = mapped_column(Text)
