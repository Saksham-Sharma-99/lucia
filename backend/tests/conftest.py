from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lucia.core.config import get_settings
from lucia.db.session import get_session
from lucia.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(get_settings().test_database_url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def _test_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = _test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await engine.dispose()
