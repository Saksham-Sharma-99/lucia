import uuid

from lucia.auth import sessions
from lucia.core.redis import get_redis


async def test_session_round_trip() -> None:
    redis = await get_redis()
    user_id = uuid.uuid4()
    token = await sessions.create_session(redis, user_id)
    assert await sessions.resolve_session(redis, token) == user_id


async def test_unknown_token_resolves_to_none() -> None:
    assert await sessions.resolve_session(await get_redis(), "unknown") is None


async def test_deleted_session_stays_deleted() -> None:
    redis = await get_redis()
    token = await sessions.create_session(redis, uuid.uuid4())
    await sessions.delete_session(redis, token)
    assert await sessions.resolve_session(redis, token) is None
    assert await redis.exists(sessions.SESSION_PREFIX + token) == 0


async def test_ttl_does_not_slide_within_the_hour() -> None:
    redis = await get_redis()
    token = await sessions.create_session(redis, uuid.uuid4())
    key = sessions.SESSION_PREFIX + token
    full = sessions._ttl()
    await redis.expire(key, full - 60)
    await sessions.resolve_session(redis, token)
    assert await redis.ttl(key) <= full - 60


async def test_ttl_slides_after_an_hour() -> None:
    redis = await get_redis()
    token = await sessions.create_session(redis, uuid.uuid4())
    key = sessions.SESSION_PREFIX + token
    await redis.expire(key, 100)
    await sessions.resolve_session(redis, token)
    assert await redis.ttl(key) > sessions._ttl() - 5


async def test_lockout_after_limit_and_clear() -> None:
    redis = await get_redis()
    for _ in range(sessions.LOGIN_FAIL_LIMIT - 1):
        await sessions.record_login_failure(redis, "u")
    assert not await sessions.login_blocked(redis, "u")
    await sessions.record_login_failure(redis, "u")
    assert await sessions.login_blocked(redis, "u")
    await sessions.clear_login_failures(redis, "u")
    assert not await sessions.login_blocked(redis, "u")


async def test_failure_counter_always_has_its_window() -> None:
    redis = await get_redis()
    key = sessions.LOGIN_FAIL_PREFIX + "u"
    await sessions.record_login_failure(redis, "u")
    first = await redis.ttl(key)
    await sessions.record_login_failure(redis, "u")
    assert 0 < await redis.ttl(key) <= first <= sessions.LOGIN_FAIL_WINDOW_SECONDS
