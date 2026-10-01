from typing import Literal

from sqlalchemy import Boolean, CheckConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column

from lucia.db.base import Base, IdMixin, TimestampMixin

Role = Literal["builder"]


class AppUser(IdMixin, TimestampMixin, Base):
    __table_args__ = (CheckConstraint("role IN ('builder')", name="role"),)

    username: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[Role] = mapped_column(Text, server_default="builder")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
