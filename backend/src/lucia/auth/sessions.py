"""Redis-backed login sessions and login lockout."""

import secrets
import uuid

from redis.asyncio import Redis

from lucia.core.config import get_settings

SESSION_PREFIX = "session:"
SLIDE_AFTER_SECONDS = 3600
LOGIN_FAIL_PREFIX = "login_fail:"
LOGIN_FAIL_LIMIT = 5
LOGIN_FAIL_WINDOW_SECONDS = 15 * 60


def _ttl() -> int:
    return get_settings().session_ttl_days * 86400


async def create_session(redis: Redis, user_id: uuid.UUID) -> str:
    token = secrets.token_urlsafe(32)
    await redis.set(SESSION_PREFIX + token, str(user_id), ex=_ttl())
    return token


async def resolve_session(redis: Redis, token: str) -> uuid.UUID | None:
    """The session's user id. The TTL slides at most once per hour; EXPIRE never recreates a
    key, so a logout racing this cannot bring the session back."""
    key = SESSION_PREFIX + token
    user_id = await redis.get(key)
    if user_id is None:
        return None
    if await redis.ttl(key) < _ttl() - SLIDE_AFTER_SECONDS:
        await redis.expire(key, _ttl())
    return uuid.UUID(user_id)


async def delete_session(redis: Redis, token: str) -> None:
    await redis.delete(SESSION_PREFIX + token)


async def login_blocked(redis: Redis, username: str) -> bool:
    count = await redis.get(LOGIN_FAIL_PREFIX + username)
    return count is not None and int(count) >= LOGIN_FAIL_LIMIT


async def record_login_failure(redis: Redis, username: str) -> None:
    """INCR and EXPIRE NX in one transaction, so the counter always gets its window."""
    key = LOGIN_FAIL_PREFIX + username
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, LOGIN_FAIL_WINDOW_SECONDS, nx=True)
        await pipe.execute()


async def clear_login_failures(redis: Redis, username: str) -> None:
    await redis.delete(LOGIN_FAIL_PREFIX + username)
