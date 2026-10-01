import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import config, create_agent


async def test_amend_creates_next_version_with_parent(authed: AsyncClient) -> None:
    await create_agent(authed)
    new_cfg = config(system_prompt="Chase harder.")
    resp = await authed.post(
        "/api/v1/agents/chaser/versions",
        json={"from_version": 1, "config": new_cfg, "changelog": "harder"},
    )
    assert resp.status_code == 201
    v2 = resp.json()
    assert v2["version"] == 2 and v2["parent_version"] == 1
    assert v2["config"]["system_prompt"] == "Chase harder."
    listed = (await authed.get("/api/v1/agents/chaser/versions")).json()
    assert [v["version"] for v in listed] == [2, 1]
    assert listed[0]["config_hash"] != listed[1]["config_hash"]
    diff = (await authed.get("/api/v1/agents/chaser/versions/1/diff/2")).json()
    assert diff == [
        {
            "path": "/system_prompt",
            "op": "change",
            "before": "Chase records.",
            "after": "Chase harder.",
        }
    ]


async def test_amend_validates_and_missing_parent_is_404(authed: AsyncClient) -> None:
    await create_agent(authed)
    bad = await authed.post(
        "/api/v1/agents/chaser/versions", json={"from_version": 1, "config": config(policy_pack=[])}
    )
    assert bad.status_code == 422
    missing = await authed.post(
        "/api/v1/agents/chaser/versions", json={"from_version": 9, "config": config()}
    )
    assert missing.status_code == 404


async def test_config_update_rejected_by_db(authed: AsyncClient, db: AsyncSession) -> None:
    await create_agent(authed)
    with pytest.raises(DBAPIError, match="immutable"):
        async with db.begin_nested():
            await db.execute(text("UPDATE agent_prompts SET config='{}'::jsonb"))


async def test_archive_and_unarchive_version(authed: AsyncClient) -> None:
    await create_agent(authed)
    v = (await authed.post("/api/v1/agents/chaser/versions/1/archive")).json()
    assert v["status"] == "archived"
    assert (await authed.get("/api/v1/agents/chaser")).json()["status"] == "archived"
    v = (await authed.post("/api/v1/agents/chaser/versions/1/unarchive")).json()
    assert v["status"] == "active"


async def test_unknown_version_and_diff_404(authed: AsyncClient) -> None:
    await create_agent(authed)
    assert (await authed.get("/api/v1/agents/chaser/versions/9")).status_code == 404
    assert (await authed.get("/api/v1/agents/chaser/versions/1/diff/9")).status_code == 404
    assert (await authed.get("/api/v1/agents/chaser/versions/1/diff/1")).json() == []


async def test_amend_archived_agent_is_409(authed: AsyncClient) -> None:
    await create_agent(authed)
    await authed.post("/api/v1/agents/chaser/archive")
    resp = await authed.post(
        "/api/v1/agents/chaser/versions", json={"from_version": 1, "config": config()}
    )
    assert resp.status_code == 409 and "Unarchive" in resp.json()["detail"]


async def test_amend_from_older_version_numbers_past_latest(authed: AsyncClient) -> None:
    await create_agent(authed)
    for _ in range(2):
        await authed.post(
            "/api/v1/agents/chaser/versions", json={"from_version": 1, "config": config()}
        )
    v = (await authed.get("/api/v1/agents/chaser/versions/3")).json()
    assert v["parent_version"] == 1
    assert (
        v["config_hash"]
        == (await authed.get("/api/v1/agents/chaser/versions/1")).json()["config_hash"]
    )  # same config, same hash


async def test_unarchive_agent_reactivates_only_latest(authed: AsyncClient) -> None:
    await create_agent(authed)
    await authed.post(
        "/api/v1/agents/chaser/versions", json={"from_version": 1, "config": config()}
    )
    await authed.post("/api/v1/agents/chaser/archive")
    await authed.post("/api/v1/agents/chaser/unarchive")
    statuses = {
        v["version"]: v["status"]
        for v in (await authed.get("/api/v1/agents/chaser/versions")).json()
    }
    assert statuses == {2: "active", 1: "archived"}


async def test_unarchive_active_agent_is_idempotent(authed: AsyncClient) -> None:
    await create_agent(authed)
    resp = (await authed.post("/api/v1/agents/chaser/unarchive")).json()
    assert resp["status"] == "active" and [v["status"] for v in resp["versions"]] == ["active"]
