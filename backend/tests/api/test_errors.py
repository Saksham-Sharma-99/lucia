from httpx import AsyncClient


async def test_unknown_route_is_problem_json(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["status"] == 404


async def test_invalid_uuid_path_is_422_with_pointer(authed: AsyncClient) -> None:
    resp = await authed.get("/api/v1/firms/not-a-uuid")
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/firm_id"


async def test_pagination_bounds(authed: AsyncClient) -> None:
    for params in ({"page": 0}, {"limit": 0}, {"limit": 101}):
        assert (await authed.get("/api/v1/firms", params=params)).status_code == 422
    page = (await authed.get("/api/v1/firms", params={"page": 5, "limit": 100})).json()
    assert page == {"items": [], "total": 0, "page": 5, "limit": 100}


async def test_platform_status(authed: AsyncClient) -> None:
    body = (await authed.get("/api/v1/platform/status")).json()
    assert body == {
        "slack": True,
        "google": True,
        "vapi": True,
        "twilio": True,
        "public_base_url": "https://lucia.test",
        "allowed_models": ["gpt-5.6", "gpt-5.6-sol", "gpt-5.6-luna"],
        "drafter_enabled": False,
    }
