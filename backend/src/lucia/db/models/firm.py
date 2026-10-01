from typing import Any, Literal

from sqlalchemy import CheckConstraint, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lucia.db.base import Base, IdMixin, TimestampMixin

FirmStatus = Literal["active", "inactive"]


class Firm(IdMixin, TimestampMixin, Base):
    __table_args__ = (
        CheckConstraint("status IN ('active','inactive')", name="status"),
        CheckConstraint("slug ~ '^[a-z0-9-]{2,40}$'", name="slug_format"),
    )

    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    timezone: Mapped[str] = mapped_column(Text)
    status: Mapped[FirmStatus] = mapped_column(Text, server_default="active")
    color: Mapped[str] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
