import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.auth import router
from lucia.db.models import AppUser
from tests.conftest import CSRF, PASSWORD


async def _login(client: AsyncClient, password: str = PASSWORD, username: str = "tester"):
    return await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}, headers=CSRF
    )


async def test_login_sets_cookie_and_me_works(client: AsyncClient, user: AppUser) -> None:
    resp = await _login(client, username="  TESTER ")
    assert resp.status_code == 200
    assert resp.json()["username"] == "tester"
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["display_name"] == "Tester"


async def test_wrong_password_is_401_problem(client: AsyncClient, user: AppUser) -> None:
    resp = await _login(client, password="nope")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_rate_limit_after_five_failures(client: AsyncClient, user: AppUser) -> None:
    for _ in range(5):
        assert (await _login(client, password="nope")).status_code == 401
    assert (await _login(client)).status_code == 429


async def test_logout_ends_session(authed: AsyncClient) -> None:
    assert (await authed.post("/api/v1/auth/logout")).status_code == 204
    authed.cookies.clear()
    assert (await authed.get("/api/v1/auth/me")).status_code == 401


async def test_unauthenticated_is_401(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/agents")).status_code == 401


async def test_unsafe_method_needs_csrf_header(authed: AsyncClient) -> None:
    resp = await authed.post("/api/v1/auth/logout", headers={"X-Requested-With": "something-else"})
    assert resp.status_code == 403


async def test_inactive_user_cannot_log_in_or_use_session(
    authed: AsyncClient, user: AppUser, db: AsyncSession
) -> None:
    user.is_active = False
    await db.commit()
    assert (await authed.get("/api/v1/auth/me")).status_code == 401
    assert (await _login(authed)).status_code == 401


async def test_unknown_user_counts_toward_lockout(client: AsyncClient) -> None:
    for _ in range(5):
        assert (await _login(client, username="ghost")).status_code == 401
    assert (await _login(client, username="ghost")).status_code == 429


async def test_login_needs_csrf_header_and_valid_body(client: AsyncClient, user: AppUser) -> None:
    no_header = await client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": PASSWORD}
    )
    assert no_header.status_code == 403
    empty = await client.post(
        "/api/v1/auth/login", json={"username": "", "password": ""}, headers=CSRF
    )
    assert empty.status_code == 422
    assert {e["path"] for e in empty.json()["errors"]} == {"/username", "/password"}


async def test_logout_without_session_is_401(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/auth/logout", headers=CSRF)).status_code == 401


async def test_forged_cookie_is_401(client: AsyncClient) -> None:
    client.cookies.set("lucia_session", "forged")
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_unknown_user_still_verifies_a_hash(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def spy(password_hash: str, password: str) -> bool:
        calls.append(password_hash)
        return False

    monkeypatch.setattr(router, "verify_password", spy)
    assert (await _login(client, username="ghost")).status_code == 401
    assert calls == [router._DUMMY_HASH]
