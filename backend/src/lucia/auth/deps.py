from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.auth.sessions import resolve_session
from lucia.core.config import get_settings
from lucia.core.errors import ProblemError
from lucia.core.redis import get_redis
from lucia.db.models import AppUser
from lucia.db.session import get_session

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "lucia"

DbSession = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def require_csrf_header(request: Request) -> None:
    """Cookie sessions + SameSite=Lax, plus a custom header a cross-site form cannot set."""
    if request.method in UNSAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise ProblemError(403, "Forbidden", f"Missing header X-Requested-With: {CSRF_VALUE}")


async def current_user(request: Request, session: DbSession, redis: RedisDep) -> AppUser:
    require_csrf_header(request)
    token = request.cookies.get(get_settings().session_cookie_name)
    user_id = await resolve_session(redis, token) if token else None
    user = await session.get(AppUser, user_id) if user_id else None
    if user is None or not user.is_active:
        raise ProblemError(401, "Not authenticated")
    return user


CurrentUser = Annotated[AppUser, Depends(current_user)]
