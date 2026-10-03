import uuid
from typing import Any, Literal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lucia.db.base import Base, IdMixin, TimestampMixin

SubjectStatus = Literal["open", "closed"]
Role = Literal["client", "provider", "insurer", "prospect", "other"]
CLIENT_ROLES = ("client",)


class Subject(IdMixin, TimestampMixin, Base):
    """The folder agents work on: a matter, a prospect, ... (DATA_MODEL §3.1)."""

    __table_args__ = (
        CheckConstraint("status IN ('open','closed')", name="status"),
        CheckConstraint("kind ~ '^[a-z0-9 _-]{1,40}$'", name="kind_format"),
        UniqueConstraint("id", "firm_id"),
        Index(
            "subjects_firm_id_external_ref_key",
            "firm_id",
            "external_ref",
            unique=True,
            postgresql_where="external_ref IS NOT NULL",
        ),
        Index("subjects_firm_id_status_idx", "firm_id", "status"),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    external_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SubjectStatus] = mapped_column(Text, server_default="open")
    description: Mapped[str] = mapped_column(Text, server_default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_users.id")
    )


class ContactPoint(IdMixin, TimestampMixin, Base):
    """One real-world endpoint, shared by a firm's subjects; opt-outs live here."""

    __table_args__ = (UniqueConstraint("id", "firm_id"),)

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    name: Mapped[str] = mapped_column(Text)
    org_name: Mapped[str | None] = mapped_column(Text)
    emails: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    phones: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    tz: Mapped[str | None] = mapped_column(Text)
    opt_out: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    org_daily_cap: Mapped[int | None] = mapped_column(Integer)


class SubjectContact(IdMixin, TimestampMixin, Base):
    """A contact point's role on one subject, with per-subject consent."""

    __table_args__ = (
        CheckConstraint("role IN ('client','provider','insurer','prospect','other')", name="role"),
        UniqueConstraint("subject_id", "contact_point_id", "role"),
        ForeignKeyConstraint(["subject_id", "firm_id"], ["subjects.id", "subjects.firm_id"]),
        ForeignKeyConstraint(
            ["contact_point_id", "firm_id"], ["contact_points.id", "contact_points.firm_id"]
        ),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    contact_point_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    role: Mapped[Role] = mapped_column(Text)
    consent: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    alias_ordinal: Mapped[int] = mapped_column(Integer)
