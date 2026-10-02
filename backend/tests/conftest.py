"""Test fixtures. Every test runs inside a transaction that is rolled back; service-level
commits become SAVEPOINT releases. Redis uses DB 1, flushed per test."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

os.environ["ENV"] = "test"
os.environ["SECRET_KEY"] = (
    "hmJ4Qp1P1ywJcAb8GtvzI7Hh4b6m4yKqk1r3kkQf6uU="  # test-only key  # gitleaks:allow
)
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["PUBLIC_BASE_URL"] = "https://lucia.test"
os.environ["FRONTEND_BASE_URL"] = "https://app.lucia.test"
os.environ["OPENAI_API_KEY"] = ""  # the drafter stays off; tests fake it
os.environ["VAPI_PHONE_NUMBER_ID"] = ""  # no default number unless a test sets one
for key in (
    "SLACK_CLIENT_ID",
    "SLACK_CLIENT_SECRET",
    "SLACK_SIGNING_SECRET",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_PUBSUB_TOPIC",
    "GOOGLE_PUBSUB_VERIFICATION_TOKEN",
    "VAPI_API_KEY",
    "VAPI_WEBHOOK_SECRET",
):
    os.environ[key] = f"test-{key.lower().replace('_', '-')}"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine  # noqa: E402

from lucia.core.config import get_settings  # noqa: E402

os.environ["DATABASE_URL"] = get_settings().test_database_url
get_settings.cache_clear()

from datetime import UTC, datetime  # noqa: E402

from lucia.core.clock import FrozenClock, set_clock  # noqa: E402
from lucia.core.redis import get_redis  # noqa: E402
from lucia.core.security import hash_password  # noqa: E402
from lucia.db.models import AppUser  # noqa: E402
from lucia.db.session import get_session  # noqa: E402
from lucia.llm.client import set_llm  # noqa: E402
from lucia.llm.fake import FakeLLM  # noqa: E402
from lucia.main import create_app  # noqa: E402
from lucia.registry.sync import sync_registry  # noqa: E402
from lucia.worker.celery_app import celery_app  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "correct-horse-battery"
CSRF = {"X-Requested-With": "lucia"}


@pytest.fixture(scope="session", autouse=True)
def _migrate() -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        check=True,
        env={**os.environ},
    )


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(get_settings().database_url)
    yield eng
    await eng.dispose()


class _ProdRollbackSession(AsyncSession):
    """Savepoint rollbacks expire only rows touched since the savepoint; a real rollback expires
    everything loaded. Mirror production so code that reads ORM rows after a rollback fails here
    (MissingGreenlet) instead of in the worker."""

    async def rollback(self) -> None:
        await super().rollback()
        self.expire_all()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = _ProdRollbackSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        await sync_registry(session)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture(autouse=True)
async def _flush_redis() -> AsyncIterator[None]:
    redis = await get_redis()
    await redis.flushdb()
    yield


@pytest.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def user(db: AsyncSession) -> AppUser:
    u = AppUser(username="tester", display_name="Tester", password_hash=hash_password(PASSWORD))
    db.add(u)
    await db.commit()
    return u


@pytest.fixture
async def authed(client: AsyncClient, user: AppUser) -> AsyncClient:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": PASSWORD},
        headers=CSRF,
    )
    assert resp.status_code == 200, resp.text
    client.headers.update(CSRF)
    return client


@pytest.fixture
def clock() -> Iterator[FrozenClock]:
    """Thursday 2026-10-01 14:00 UTC (10:00 in New York): inside business hours."""
    c = FrozenClock(datetime(2026, 10, 1, 14, 0, tzinfo=UTC))
    set_clock(c)
    yield c
    set_clock(None)


@pytest.fixture
def fake_llm() -> Iterator[FakeLLM]:
    fake = FakeLLM()
    set_llm(fake)
    yield fake
    set_llm(None)


@pytest.fixture(autouse=True)
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[str, ...]]]:
    """Celery sends are captured instead of reaching the broker."""
    calls: list[tuple[str, tuple[str, ...]]] = []

    def send_task(task: str, args: list[str], **_: object) -> None:
        calls.append((task, tuple(args)))

    monkeypatch.setattr(celery_app, "send_task", send_task)
    return calls
