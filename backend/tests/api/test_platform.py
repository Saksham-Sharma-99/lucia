from httpx import AsyncClient


async def test_timezones_are_region_zones_the_api_accepts(authed: AsyncClient) -> None:
    zones = (await authed.get("/api/v1/platform/timezones")).json()
    assert {"Asia/Kolkata", "America/New_York", "UTC"} <= set(zones)
    assert "US/Eastern" not in zones and not any(z.startswith("Etc/") for z in zones)
    assert zones[:-1] == sorted(zones[:-1])
