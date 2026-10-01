import uuid

from fastapi import Request, Response, status
from pydantic import Field
from sqlalchemy import select

from lucia.api.tags import api_router
from lucia.auth import sessions
from lucia.auth.deps import CurrentUser, DbSession, RedisDep, require_csrf_header
from lucia.core.config import get_settings
from lucia.core.errors import ProblemError
from lucia.core.schema import Read, Strict
from lucia.core.security import hash_password, verify_password
from lucia.db.models import AppUser
from lucia.db.models.user import Role

router = api_router("auth", "/auth", public=True)

# Verifying against this when the user is unknown keeps response time from revealing usernames.
_DUMMY_HASH = hash_password("lucia-timing-equalizer")


class LoginRequest(Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(Read):
    id: uuid.UUID
    username: str
    display_name: str
    role: Role


@router.post("/login", summary="Log in with username and password", operation_id="login")
async def login(
    body: LoginRequest, request: Request, response: Response, session: DbSession, redis: RedisDep
) -> UserOut:
    require_csrf_header(request)
    username = body.username.strip().lower()
    if await sessions.login_blocked(redis, username):
        raise ProblemError(429, "Too many attempts", "Too many failed logins. Try again later.")
    user = await session.scalar(select(AppUser).where(AppUser.username == username))
    valid = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    if user is None or not user.is_active or not valid:
        await sessions.record_login_failure(redis, username)
        raise ProblemError(401, "Invalid credentials", "Username or password is incorrect")
    await sessions.clear_login_failures(redis, username)
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        await sessions.create_session(redis, user.id),
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return UserOut.model_validate(user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out and clear the session cookie",
    operation_id="logout",
)
async def logout(request: Request, response: Response, redis: RedisDep, _: CurrentUser) -> None:
    name = get_settings().session_cookie_name
    if token := request.cookies.get(name):
        await sessions.delete_session(redis, token)
    response.delete_cookie(name)


@router.get("/me", summary="The logged-in user", operation_id="getMe")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
