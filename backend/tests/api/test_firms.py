import pytest
from httpx import AsyncClient

from tests.factories import ZERO, Json, create_firm

BAD = {"name": "X", "slug": "acme-law", "timezone": "UTC", "color": "#000000"}


@pytest.fixture
async def firm(authed: AsyncClient) -> Json:
    return await create_firm(authed)


async def test_create_returns_defaults(firm: Json) -> None:
    assert (firm["status"], firm["connection_counts"]) == ("active", {})
    assert firm["settings"]["business_hours"]["sat"] is None
    assert firm["settings"]["quiet_hours"] == {"start": "20:00", "end": "08:00"}


async def test_create_makes_no_mappings(firm: Json) -> None:
    assert firm["mapping_counts"] == {"active": 0, "inactive": 0}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("slug", "Bad Slug"),
        ("slug", "a"),
        ("timezone", "Mars/Base"),
        ("color", "red"),
        ("name", ""),
    ],
)
async def test_create_field_validation(authed: AsyncClient, field: str, value: str) -> None:
    resp = await authed.post("/api/v1/firms", json={**BAD, field: value})
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == f"/{field}"


async def test_taken_slug_is_422(authed: AsyncClient, firm: Json) -> None:
    resp = await authed.post("/api/v1/firms", json=BAD)
    assert resp.status_code == 422 and resp.json()["errors"][0]["code"] == "taken"


async def test_get_unknown_firm_is_404(authed: AsyncClient) -> None:
    resp = await authed.get(f"/api/v1/firms/{ZERO}")
    assert resp.status_code == 404 and resp.json()["detail"] == "Firm not found"


async def test_patch_name_and_settings(authed: AsyncClient, firm: Json) -> None:
    resp = (
        await authed.patch(
            f"/api/v1/firms/{firm['id']}",
            json={
                "name": "Acme 2",
                "timezone": "Europe/Paris",
                "settings": {"quiet_hours": {"start": "21:00", "end": "07:00"}},
            },
        )
    ).json()
    assert (resp["name"], resp["timezone"]) == ("Acme 2", "Europe/Paris")
    assert resp["settings"]["quiet_hours"] == {"start": "21:00", "end": "07:00"}


@pytest.mark.parametrize(
    ("body", "path"),
    [
        ({"slug": "new-slug"}, "/slug"),
        ({"settings": {"x": 1}}, "/settings/x"),
        ({"timezone": "Nope/Zone"}, "/timezone"),
        (
            {
                "settings": {
                    "policy_floor": [{"rule": "per_subject_contact_cap", "params": {"n": 0}}]
                }
            },
            "/settings/policy_floor/0/params/n",
        ),
        ({"settings": {"alert_routing": {"P0": ["pager"]}}}, "/settings/alert_routing/P0/0"),
    ],
)
async def test_patch_validation(authed: AsyncClient, firm: Json, body: Json, path: str) -> None:
    resp = await authed.patch(f"/api/v1/firms/{firm['id']}", json=body)
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == path


async def test_search_by_name_or_slug(authed: AsyncClient, firm: Json) -> None:
    await create_firm(authed, slug="other-firm", name="Other")
    for q, expected in (("ACME", ["acme-law"]), ("other-", ["other-firm"])):
        page = (await authed.get("/api/v1/firms", params={"q": q})).json()
        assert [f["slug"] for f in page["items"]] == expected


async def test_status_filter(authed: AsyncClient, firm: Json) -> None:
    await create_firm(authed, slug="other-firm", name="Other")
    await authed.post(f"/api/v1/firms/{firm['id']}/deactivate")
    inactive = (await authed.get("/api/v1/firms", params={"status": "inactive"})).json()
    assert [f["slug"] for f in inactive["items"]] == ["acme-law"]


async def test_deactivate_then_activate(authed: AsyncClient, firm: Json) -> None:
    off = (await authed.post(f"/api/v1/firms/{firm['id']}/deactivate")).json()
    on = (await authed.post(f"/api/v1/firms/{firm['id']}/activate")).json()
    assert (off["status"], on["status"]) == ("inactive", "active")


@pytest.mark.parametrize(("action", "times"), [("activate", 1), ("deactivate", 2)])
async def test_repeated_status_change_is_409(
    authed: AsyncClient, firm: Json, action: str, times: int
) -> None:
    for _ in range(times - 1):
        await authed.post(f"/api/v1/firms/{firm['id']}/{action}")
    resp = await authed.post(f"/api/v1/firms/{firm['id']}/{action}")
    assert resp.status_code == 409 and "already" in resp.json()["detail"]


@pytest.mark.parametrize("q", ["%", "_"])
async def test_search_treats_wildcards_literally(authed: AsyncClient, firm: Json, q: str) -> None:
    await create_firm(authed, slug="odd-firm", name="50% Off_Law")
    page = (await authed.get("/api/v1/firms", params={"q": q})).json()
    assert [f["slug"] for f in page["items"]] == ["odd-firm"]
