import re
import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from lucia.core.time import utcnow

# Constraint and index names follow Postgres's own defaults (users_pkey, users_email_key, ...).
NAMING_CONVENTION = {
    "pk": "%(table_name)s_pkey",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
    "ck": "%(table_name)s_%(constraint_name)s_check",
}


def table_name(class_name: str) -> str:
    """CompiledAgentFirmMapping -> compiled_agent_firm_mappings, RegistryEntry -> ..._entries."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
    return snake[:-1] + "ies" if re.search(r"[^aeiou]y$", snake) else snake + "s"


class Base(DeclarativeBase):
    """Declarative base for all ORM models. Table names are derived, never declared."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Fetch server defaults (ids, created_at) with INSERT ... RETURNING, so no refresh is needed.
    __mapper_args__ = {"eager_defaults": True}

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return table_name(cls.__name__)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        sort_order=-1,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, sort_order=1
    )
    # Set in Python, so it is never left expired after a flush; the column stays nullable.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True, default=utcnow, onupdate=utcnow, sort_order=1
    )
