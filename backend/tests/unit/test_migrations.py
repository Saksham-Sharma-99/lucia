"""The migrations and the ORM models describe the same schema."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncEngine

import lucia.db.models  # noqa: F401
from lucia.db.base import Base
from lucia.db.manual import MANUAL_INDEXES


async def test_models_match_migrations(engine: AsyncEngine) -> None:
    def diff(conn: object) -> list[object]:
        ctx = MigrationContext.configure(
            conn,  # pyright: ignore[reportArgumentType]
            opts={
                "include_object": lambda _o, name, type_, _r, _c: (
                    not (type_ == "index" and name in MANUAL_INDEXES)
                )
            },
        )
        return compare_metadata(ctx, Base.metadata)

    async with engine.connect() as conn:
        assert await conn.run_sync(diff) == []
