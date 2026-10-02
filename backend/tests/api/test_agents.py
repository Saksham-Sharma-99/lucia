import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import AppUser
from lucia.studio import service
from lucia.studio.templates import RECORDS
from tests.factories import ZERO, config, create_agent


async def _post(client: AsyncClient, **body: object) -> Response:
    return await client.post(
        "/api/v1/agents", json={"handle": "bot", "name": "x", "config": config(), **body}
    )


# --- create and get ----------------------------------------------------------------------


async def test_create_saves_v1(authed: AsyncClient) -> None:
    agent = await create_agent(authed, use_cases=["get records"])
    assert agent["status"] == "active" and agent["active_mapping_count"] == 0
    (v1,) = agent["versions"]
    assert (v1["version"], v1["status"], v1["changelog"], v1["parent_version"]) == (
        1,
        "active",
        "Initial version",
        None,
    )


async def test_get_by_handle(authed: AsyncClient) -> None:
    await create_agent(authed, use_cases=["get records"])
    got = (await authed.get("/api/v1/agents/chaser")).json()
    assert (got["handle"], got["use_cases"], got["version_policy"]) == (
        "chaser",
        ["get records"],
        "pin",
    )


async def test_taken_handle_is_409(authed: AsyncClient) -> None:
    await create_agent(authed, "bot")
    assert (await _post(authed)).status_code == 409


@pytest.mark.parametrize("handle", ["1x", "ab", "UPPER", "has space", "a" * 33])
async def test_bad_handle_is_422(authed: AsyncClient, handle: str) -> None:
    resp = await _post(authed, handle=handle)
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/handle"


async def test_orchestrator_is_a_reserved_handle(authed: AsyncClient) -> None:
    resp = await _post(authed, handle="orchestrator")
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/handle"


async def test_semantic_errors_use_config_pointers(authed: AsyncClient) -> None:
    resp = await _post(authed, config=config(policy_pack=[]))
    assert resp.status_code == 422
    assert [(e["path"], e["code"]) for e in resp.json()["errors"]] == [
        ("/config/policy_pack", "min_pack")
    ]


async def test_reserved_key_is_rejected_with_reason(authed: AsyncClient) -> None:
    resp = await authed.post("/api/v1/agents/validate", json={"config": config(task_templates=[])})
    assert resp.status_code == 422
    err = resp.json()["errors"][0]
    assert (err["path"], err["code"]) == ("/config/task_templates", "reserved")


async def test_validate_accepts_a_valid_config(authed: AsyncClient) -> None:
    resp = await authed.post("/api/v1/agents/validate", json={"config": config()})
    assert resp.status_code == 200 and resp.json() == {"errors": []}


async def test_unknown_source_agent_is_422(authed: AsyncClient) -> None:
    resp = await _post(authed, source_agent_id=ZERO)
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/source_agent_id"


async def test_unknown_fields_are_422(authed: AsyncClient) -> None:
    assert (await _post(authed, status="active")).status_code == 422


async def test_handle_is_immutable_in_db(authed: AsyncClient, db: AsyncSession) -> None:
    await create_agent(authed)
    with pytest.raises(DBAPIError, match="immutable"):
        async with db.begin_nested():
            await db.execute(text("UPDATE agents SET handle='renamed' WHERE handle='chaser'"))


@pytest.mark.parametrize("path", ["", "/versions", "/versions/1"])
async def test_unknown_handle_is_404(authed: AsyncClient, path: str) -> None:
    assert (await authed.get(f"/api/v1/agents/ghost{path}")).status_code == 404


# --- list --------------------------------------------------------------------------------


async def test_search_matches_name_description_and_handle(authed: AsyncClient) -> None:
    await create_agent(authed, "records-bot", description="medical records chaser")
    await create_agent(authed, "lien-bot", description="liens")
    for q, expected in (("MEDICAL", ["records-bot"]), ("lien-", ["lien-bot"]), ("zzz", [])):
        page = (await authed.get("/api/v1/agents", params={"q": q})).json()
        assert [a["handle"] for a in page["items"]] == expected, q


async def test_list_item_summarises_versions(authed: AsyncClient) -> None:
    await create_agent(authed)
    await authed.post(
        "/api/v1/agents/chaser/versions", json={"from_version": 1, "config": config()}
    )
    await authed.post("/api/v1/agents/chaser/versions/2/archive")
    (item,) = (await authed.get("/api/v1/agents")).json()["items"]
    assert (item["latest_version"], item["latest_active_version"], item["status"]) == (
        2,
        1,
        "active",
    )


async def test_status_filter(authed: AsyncClient) -> None:
    await create_agent(authed, "keep")
    await create_agent(authed, "gone")
    await authed.post("/api/v1/agents/gone/archive")
    for status, expected in (("archived", ["gone"]), ("active", ["keep"])):
        page = (await authed.get("/api/v1/agents", params={"status": status})).json()
        assert [a["handle"] for a in page["items"]] == expected


async def test_templates_listed_only_on_request(
    authed: AsyncClient, db: AsyncSession, user: AppUser
) -> None:
    await service.create_agent(db, RECORDS, user, is_template=True)
    assert (await authed.get("/api/v1/agents")).json()["total"] == 0
    templates = (await authed.get("/api/v1/agents", params={"is_template": True})).json()
    assert [a["handle"] for a in templates["items"]] == ["records"]


@pytest.mark.parametrize(
    ("sort", "first"),
    [
        ("name", "alpha"),
        ("-name", "zulu"),
        ("handle", "alpha"),
        ("updated_at", "alpha"),
        ("-updated_at", "zulu"),  # created_at ties in one transaction
    ],
)
async def test_sorting(authed: AsyncClient, sort: str, first: str) -> None:
    await create_agent(authed, "alpha")
    await create_agent(authed, "zulu")
    page = (await authed.get("/api/v1/agents", params={"sort": sort})).json()
    assert page["items"][0]["handle"] == first


async def test_unknown_sort_is_422(authed: AsyncClient) -> None:
    assert (await authed.get("/api/v1/agents", params={"sort": "id"})).status_code == 422


async def test_pagination(authed: AsyncClient) -> None:
    for h in ("aaa", "bbb", "ccc"):
        await create_agent(authed, h)
    page = (
        await authed.get("/api/v1/agents", params={"sort": "handle", "page": 2, "limit": 2})
    ).json()
    assert (page["total"], [a["handle"] for a in page["items"]]) == (3, ["ccc"])


# --- patch, archive, duplicate -----------------------------------------------------------


async def test_patch_updates_metadata_without_new_version(authed: AsyncClient) -> None:
    await create_agent(authed)
    patched = (
        await authed.patch("/api/v1/agents/chaser", json={"name": "Renamed", "auto_delegate": True})
    ).json()
    assert (patched["name"], patched["auto_delegate"], len(patched["versions"])) == (
        "Renamed",
        True,
        1,
    )


async def test_patch_null_means_unchanged(authed: AsyncClient) -> None:
    await create_agent(authed)
    assert (await authed.patch("/api/v1/agents/chaser", json={"name": None})).json()[
        "name"
    ] == "Chaser"


@pytest.mark.parametrize(
    "body",
    [{"version_policy": "latest"}, {"use_cases": ["x"] * 21}, {"handle": "new"}, {"name": ""}],
)
async def test_patch_rejects_bad_values(authed: AsyncClient, body: dict[str, object]) -> None:
    await create_agent(authed)
    assert (await authed.patch("/api/v1/agents/chaser", json=body)).status_code == 422


async def test_archive_archives_every_version(authed: AsyncClient) -> None:
    await create_agent(authed)
    archived = (await authed.post("/api/v1/agents/chaser/archive")).json()
    assert archived["agent"]["status"] == "archived"
    assert archived["deactivated_mapping_ids"] == []


async def test_duplicate_copies_latest_active_version(authed: AsyncClient) -> None:
    source = await create_agent(authed, use_cases=["one"])
    await authed.post(
        "/api/v1/agents/chaser/versions",
        json={"from_version": 1, "config": config(system_prompt="v2")},
    )
    dup = await authed.post(
        "/api/v1/agents/chaser/duplicate", json={"handle": "copy", "name": "Copy"}
    )
    assert dup.status_code == 201 and dup.json()["source_agent_id"] == source["id"]
    v1 = (await authed.get("/api/v1/agents/copy/versions/1")).json()
    assert (v1["config"]["system_prompt"], v1["changelog"]) == ("v2", "Copied from @chaser v2")
    assert dup.json()["use_cases"] == ["one"]


async def test_duplicate_archived_agent_is_409(authed: AsyncClient) -> None:
    await create_agent(authed)
    await authed.post("/api/v1/agents/chaser/archive")
    resp = await authed.post(
        "/api/v1/agents/chaser/duplicate", json={"handle": "copy", "name": "x"}
    )
    assert resp.status_code == 409


async def test_duplicate_into_taken_handle_is_409(authed: AsyncClient) -> None:
    await create_agent(authed)
    await create_agent(authed, "other")
    resp = await authed.post(
        "/api/v1/agents/chaser/duplicate", json={"handle": "other", "name": "x"}
    )
    assert resp.status_code == 409


@pytest.mark.parametrize("q", ["%", "_", "\\"])
async def test_search_treats_wildcards_literally(authed: AsyncClient, q: str) -> None:
    await create_agent(authed, "plain", description="nothing special")
    await create_agent(authed, "pct", description="100% done_now \\o/")
    page = (await authed.get("/api/v1/agents", params={"q": q})).json()
    assert [a["handle"] for a in page["items"]] == ["pct"]
