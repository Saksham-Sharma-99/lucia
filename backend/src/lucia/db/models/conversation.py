import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lucia.core.time import utcnow
from lucia.db.base import Base, IdMixin, TimestampMixin

Channel = Literal["playground", "slack", "voice", "email", "api"]
Direction = Literal["inbound", "outbound", "internal"]
Actor = Literal["human", "agent", "system", "contact"]
MessageStatus = Literal["received", "queued", "sent", "failed"]


class Conversation(IdMixin, TimestampMixin, Base):
    """One chat: a playground chat or a Slack thread. Its subject is locked once set (D4)."""

    __table_args__ = (
        CheckConstraint("channel IN ('playground','slack','voice','email','api')", name="channel"),
        UniqueConstraint("id", "firm_id"),
        UniqueConstraint("firm_id", "channel", "external_thread_ref"),
        Index("conversations_firm_id_last_message_at_idx", "firm_id", "last_message_at"),
        ForeignKeyConstraint(["subject_id", "firm_id"], ["subjects.id", "subjects.firm_id"]),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    channel: Mapped[Channel] = mapped_column(Text)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str | None] = mapped_column(Text)
    external_thread_ref: Mapped[str | None] = mapped_column(Text)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_users.id")
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class Message(IdMixin, TimestampMixin, Base):
    """Chat order is `seq` (rows written in one transaction share created_at)."""

    __table_args__ = (
        CheckConstraint("direction IN ('inbound','outbound','internal')", name="direction"),
        CheckConstraint("actor IN ('human','agent','system','contact')", name="actor"),
        CheckConstraint("status IN ('received','queued','sent','failed')", name="status"),
        ForeignKeyConstraint(
            ["conversation_id", "firm_id"], ["conversations.id", "conversations.firm_id"]
        ),
        Index("messages_conversation_id_seq_idx", "conversation_id", "seq"),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("firms.id"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    direction: Mapped[Direction] = mapped_column(Text)
    actor: Mapped[Actor] = mapped_column(Text)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_users.id")
    )
    external_author: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    status: Mapped[MessageStatus] = mapped_column(Text)
    external_ref: Mapped[str | None] = mapped_column(Text)
    dedup_key: Mapped[str | None] = mapped_column(Text, unique=True)
