import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import ConnectorConnection
from lucia.db.models.mapping import ONE_ACTIVE_INDEX
from tests.factories import ZERO, Json, config, connected, create_agent, create_firm


class UniqueViolation(Exception):
    constraint_name = ONE_ACTIVE_INDEX


@dataclass
class Ctx:
    agent: Json
    firm: Json
    gmail: str
    v1: str

    def body(self, **extra: Any) -> Json:
        return {
            "firm_id": self.firm["id"],
            "agent_prompt_id": self.v1,
            "identities": {"gmail": self.gmail},
            **extra,
        }


@pytest.fixture
async def ctx(authed: AsyncClient, db: AsyncSession) -> Ctx:
    agent = await create_agent(authed)
    firm = await create_firm(authed)
    gmail = await connected(db, firm["id"], "gmail", {"mailbox": "r@acme.com"})
    return Ctx(agent, firm, str(gmail.id), agent["versions"][0]["id"])


async def _create(client: AsyncClient, ctx: Ctx, **extra: Any) -> Response:
    return await client.post("/api/v1/mappings", json=ctx.body(**extra))


async def _v2(client: AsyncClient) -> Json:
    return (
        await client.post(
            "/api/v1/agents/chaser/versions", json={"from_version": 1, "config": config()}
        )
    ).json()


async def _switch(client: AsyncClient, mapping: Json, version_id: str) -> Response:
    return await client.post(
        f"/api/v1/mappings/{mapping['id']}/switch-version", json={"agent_prompt_id": version_id}
    )


# --- checklist ---------------------------------------------------------------------------


async def test_checklist_unbound(authed: AsyncClient, ctx: Ctx) -> None:
    items = (
        await authed.get(
            "/api/v1/mappings/checklist",
            params={"firm_id": ctx.firm["id"], "agent_prompt_id": ctx.v1},
        )
    ).json()
    assert items == [
        {
            "connector": "gmail",
            "required": True,
            "connection_id": None,
            "ok": False,
            "reason": "Pick a gmail connection",
        }
    ]


async def test_checklist_bound(authed: AsyncClient, ctx: Ctx) -> None:
    items = (
        await authed.get(
            "/api/v1/mappings/checklist",
            params={
                "firm_id": ctx.firm["id"],
                "agent_prompt_id": ctx.v1,
                "identities": [f"gmail:{ctx.gmail}"],
            },
        )
    ).json()
    assert items[0]["ok"] is True and items[0]["connection_id"] == ctx.gmail


async def test_checklist_ignores_unparsable_pairs(authed: AsyncClient, ctx: Ctx) -> None:
    items = (
        await authed.get(
            "/api/v1/mappings/checklist",
            params={
                "firm_id": ctx.firm["id"],
                "agent_prompt_id": ctx.v1,
                "identities": ["gmail:not-a-uuid", "junk"],
            },
        )
    ).json()
    assert items[0]["ok"] is False and items[0]["reason"].startswith("Pick")


@pytest.mark.parametrize("field", ["firm_id", "agent_prompt_id"])
async def test_checklist_unknown_reference_is_404(
    authed: AsyncClient, ctx: Ctx, field: str
) -> None:
    params = {"firm_id": ctx.firm["id"], "agent_prompt_id": ctx.v1, field: ZERO}
    assert (await authed.get("/api/v1/mappings/checklist", params=params)).status_code == 404


# --- create ------------------------------------------------------------------------------


async def test_create_inactive_reports_missing_bindings(authed: AsyncClient, ctx: Ctx) -> None:
    resp = await _create(authed, ctx, identities={})
    assert resp.status_code == 201
    body = resp.json()
    assert (body["status"], body["checklist_ok"], body["checklist_missing"]) == (
        "inactive",
        False,
        1,
    )
    assert (body["agent_handle"], body["version"], body["ab_weight"]) == ("chaser", 1, 100)


async def test_create_and_activate(authed: AsyncClient, ctx: Ctx) -> None:
    body = (await _create(authed, ctx, activate=True)).json()
    assert body["status"] == "active" and body["checklist_ok"] is True


async def test_checklist_blocks_activation(authed: AsyncClient, ctx: Ctx) -> None:
    resp = await _create(authed, ctx, identities={}, activate=True)
    assert resp.status_code == 409 and "gmail: Pick a gmail connection" in resp.json()["detail"]


@pytest.mark.parametrize(("connector", "other_firm"), [("gmail", True), ("slack", False)])
async def test_binding_must_match_firm_and_connector(
    authed: AsyncClient, db: AsyncSession, ctx: Ctx, connector: str, other_firm: bool
) -> None:
    firm = await create_firm(authed, slug="other-firm") if other_firm else ctx.firm
    conn = await connected(db, firm["id"], connector)
    resp = await _create(authed, ctx, identities={"gmail": str(conn.id)}, activate=True)
    assert resp.status_code == 409


async def test_one_active_per_firm_agent(authed: AsyncClient, ctx: Ctx) -> None:
    await _create(authed, ctx, activate=True)
    second = await _create(authed, ctx, activate=True)
    assert second.status_code == 409 and "switch-version" in second.json()["detail"]


async def test_archived_version_is_409(authed: AsyncClient, ctx: Ctx) -> None:
    await authed.post("/api/v1/agents/chaser/versions/1/archive")
    resp = await _create(authed, ctx)
    assert resp.status_code == 409 and resp.json()["detail"] == "The version is archived"


async def test_inactive_firm_is_409(authed: AsyncClient, ctx: Ctx) -> None:
    await authed.post(f"/api/v1/firms/{ctx.firm['id']}/deactivate")
    resp = await _create(authed, ctx)
    assert resp.status_code == 409 and resp.json()["detail"] == "The firm is inactive"


@pytest.mark.parametrize("field", ["firm_id", "agent_prompt_id"])
async def test_unknown_reference_is_404(authed: AsyncClient, ctx: Ctx, field: str) -> None:
    assert (await _create(authed, ctx, **{field: ZERO})).status_code == 404


@pytest.mark.parametrize("weight", [-1, 101])
async def test_ab_weight_bounds(authed: AsyncClient, ctx: Ctx, weight: int) -> None:
    assert (await _create(authed, ctx, ab_weight=weight)).status_code == 422


async def test_unique_index_race_becomes_409(
    authed: AsyncClient, db: AsyncSession, ctx: Ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulates losing the race at commit; a true two-session race needs committed data,
    which the rollback-per-test fixture does not allow."""

    async def lost_race() -> None:
        violation = Exception("duplicate key")
        violation.__cause__ = UniqueViolation()  # asyncpg puts the constraint name here
        raise IntegrityError("INSERT", {}, violation)

    async def rollback() -> None:
        return None

    monkeypatch.setattr(db, "commit", lost_race)
    monkeypatch.setattr(db, "rollback", rollback)
    resp = await _create(authed, ctx, activate=True)
    assert resp.status_code == 409 and "switch-version" in resp.json()["detail"]


# --- overrides (tighten-only) ------------------------------------------------------------


async def test_looser_policy_override_is_422(authed: AsyncClient, ctx: Ctx) -> None:
    resp = await _create(
        authed, ctx, overrides={"policy_params": {"per_subject_contact_cap": {"n": 10}}}
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["path"] == "/overrides/policy_params/per_subject_contact_cap"


async def test_stricter_overrides_are_stored(authed: AsyncClient, ctx: Ctx) -> None:
    tight = {
        "policy_params": {"per_subject_contact_cap": {"n": 1}},
        "cadence": {"min_wait_hours": 72},
        "alert_routing": {"P0": ["slack_dm"]},
    }
    resp = await _create(authed, ctx, overrides=tight)
    assert resp.status_code == 201 and resp.json()["overrides"] == tight


async def test_override_rules_must_be_in_policy(authed: AsyncClient, ctx: Ctx) -> None:
    resp = await _create(
        authed,
        ctx,
        overrides={"policy_params": {"opt_out_enforced": {}}, "cadence": {"min_wait_hours": 1}},
    )
    assert {e["code"] for e in resp.json()["errors"]} == {"not_in_policy", "looser"}


async def test_unknown_override_key_is_422(authed: AsyncClient, ctx: Ctx) -> None:
    assert (await _create(authed, ctx, overrides={"other": 1})).status_code == 422


async def test_firm_floor_applies_to_overrides(authed: AsyncClient, ctx: Ctx) -> None:
    floor = [{"rule": "per_subject_contact_cap", "params": {"n": 1}}]
    await authed.patch(
        f"/api/v1/firms/{ctx.firm['id']}", json={"settings": {"policy_floor": floor}}
    )
    resp = await _create(
        authed, ctx, overrides={"policy_params": {"per_subject_contact_cap": {"n": 2}}}
    )
    assert resp.status_code == 422


# --- patch -------------------------------------------------------------------------------


async def test_active_mapping_cannot_lose_bindings(authed: AsyncClient, ctx: Ctx) -> None:
    m = (await _create(authed, ctx, activate=True)).json()
    resp = await authed.patch(f"/api/v1/mappings/{m['id']}", json={"identities": {}})
    assert resp.status_code == 409


async def test_deactivate_and_unbind_together(authed: AsyncClient, ctx: Ctx) -> None:
    m = (await _create(authed, ctx, activate=True)).json()
    resp = (
        await authed.patch(
            f"/api/v1/mappings/{m['id']}", json={"status": "inactive", "identities": {}}
        )
    ).json()
    assert resp["status"] == "inactive" and resp["checklist_missing"] == 1


async def test_deactivating_a_broken_mapping_is_allowed(
    authed: AsyncClient, db: AsyncSession, ctx: Ctx
) -> None:
    m = (await _create(authed, ctx, activate=True)).json()
    gmail = await db.get(ConnectorConnection, uuid.UUID(ctx.gmail))
    assert gmail is not None
    gmail.status = "error"
    await db.commit()
    resp = await authed.patch(f"/api/v1/mappings/{m['id']}", json={"status": "inactive"})
    assert resp.status_code == 200 and resp.json()["checklist_ok"] is False
    again = await authed.patch(f"/api/v1/mappings/{m['id']}", json={"status": "active"})
    assert again.status_code == 409


async def test_activate_via_patch(authed: AsyncClient, ctx: Ctx) -> None:
    m = (await _create(authed, ctx)).json()
    resp = (await authed.patch(f"/api/v1/mappings/{m['id']}", json={"status": "active"})).json()
    assert resp["status"] == "active"


async def test_second_activation_via_patch_is_409(authed: AsyncClient, ctx: Ctx) -> None:
    await _create(authed, ctx, activate=True)
    other = (await _create(authed, ctx)).json()
    resp = await authed.patch(f"/api/v1/mappings/{other['id']}", json={"status": "active"})
    assert resp.status_code == 409


async def test_patch_weight_and_kill_switch(authed: AsyncClient, ctx: Ctx) -> None:
    m = (await _create(authed, ctx)).json()
    resp = (
        await authed.patch(
            f"/api/v1/mappings/{m['id']}", json={"ab_weight": 0, "kill_switch": True}
        )
    ).json()
    assert (resp["ab_weight"], resp["kill_switch"], resp["status"]) == (0, True, "inactive")


async def test_unknown_mapping_is_404(authed: AsyncClient) -> None:
    assert (await authed.get(f"/api/v1/mappings/{ZERO}")).status_code == 404
    assert (await authed.patch(f"/api/v1/mappings/{ZERO}", json={})).status_code == 404


# --- switch version ----------------------------------------------------------------------


async def test_switch_supersedes_active_mapping(authed: AsyncClient, ctx: Ctx) -> None:
    old = (await _create(authed, ctx, activate=True)).json()
    new = (await _switch(authed, old, (await _v2(authed))["id"])).json()
    assert (new["version"], new["status"], new["supersedes_mapping_id"]) == (2, "active", old["id"])
    assert (await authed.get(f"/api/v1/mappings/{old['id']}")).json()["status"] == "inactive"


async def test_switch_keeps_inactive_and_copies_settings(authed: AsyncClient, ctx: Ctx) -> None:
    overrides = {"policy_params": {"per_subject_contact_cap": {"n": 2}}}
    old = (await _create(authed, ctx, overrides=overrides, ab_weight=40)).json()
    await authed.patch(f"/api/v1/mappings/{old['id']}", json={"kill_switch": True})
    new = (await _switch(authed, old, (await _v2(authed))["id"])).json()
    assert new["status"] == "inactive"
    assert (new["identities"], new["overrides"], new["ab_weight"], new["kill_switch"]) == (
        old["identities"],
        old["overrides"],
        40,
        True,
    )


async def test_switch_to_version_needing_more_bindings_lands_inactive(
    authed: AsyncClient, ctx: Ctx
) -> None:
    old = (await _create(authed, ctx, activate=True)).json()
    caps = [*config()["capabilities"], {"connector": "slack", "tools": ["slack.send_message"]}]
    v2 = (
        await authed.post(
            "/api/v1/agents/chaser/versions",
            json={"from_version": 1, "config": config(capabilities=caps)},
        )
    ).json()
    new = (await _switch(authed, old, v2["id"])).json()
    assert (new["status"], new["checklist_missing"]) == ("inactive", 1)


async def test_switch_to_same_version_is_409(authed: AsyncClient, ctx: Ctx) -> None:
    m = (await _create(authed, ctx)).json()
    assert (await _switch(authed, m, ctx.v1)).status_code == 409


async def test_switch_to_another_agent_is_409(authed: AsyncClient, ctx: Ctx) -> None:
    m = (await _create(authed, ctx)).json()
    other = await create_agent(authed, "other")
    resp = await _switch(authed, m, other["versions"][0]["id"])
    assert resp.status_code == 409 and "different agent" in resp.json()["detail"]


async def test_switch_to_archived_version_is_409(authed: AsyncClient, ctx: Ctx) -> None:
    m = (await _create(authed, ctx)).json()
    v2 = await _v2(authed)
    await authed.post("/api/v1/agents/chaser/versions/2/archive")
    assert (await _switch(authed, m, v2["id"])).status_code == 409


async def test_switch_on_inactive_firm_is_409(authed: AsyncClient, ctx: Ctx) -> None:
    m = (await _create(authed, ctx)).json()
    v2 = await _v2(authed)
    await authed.post(f"/api/v1/firms/{ctx.firm['id']}/deactivate")
    assert (await _switch(authed, m, v2["id"])).status_code == 409


# --- list and cascades -------------------------------------------------------------------


async def test_list_filters(authed: AsyncClient, ctx: Ctx) -> None:
    await _create(authed, ctx, activate=True)
    await _create(authed, ctx)
    by_firm = (await authed.get("/api/v1/mappings", params={"firm_id": ctx.firm["id"]})).json()
    active = (await authed.get("/api/v1/mappings", params={"status": "active"})).json()
    none = (await authed.get("/api/v1/mappings", params={"agent_id": ZERO})).json()
    assert (by_firm["total"], active["total"], none["total"]) == (2, 1, 0)


async def test_list_pages_newest_first(authed: AsyncClient, ctx: Ctx) -> None:
    ids = [(await _create(authed, ctx)).json()["id"] for _ in range(3)]
    first = (await authed.get("/api/v1/mappings", params={"limit": 2})).json()
    second = (await authed.get("/api/v1/mappings", params={"limit": 2, "page": 2})).json()
    assert first["total"] == second["total"] == 3
    assert [m["id"] for m in first["items"] + second["items"]] == ids[::-1]


async def test_list_mixes_passing_and_failing_checklists(authed: AsyncClient, ctx: Ctx) -> None:
    await _create(authed, ctx, activate=True)
    await _create(authed, ctx, identities={})
    items = (await authed.get("/api/v1/mappings")).json()["items"]
    assert sorted(i["checklist_ok"] for i in items) == [False, True]


async def test_archive_agent_deactivates_its_mappings(authed: AsyncClient, ctx: Ctx) -> None:
    m = (await _create(authed, ctx, activate=True)).json()
    archived = (await authed.post("/api/v1/agents/chaser/archive")).json()
    assert archived["deactivated_mapping_ids"] == [m["id"]]
    assert (await authed.get(f"/api/v1/mappings/{m['id']}")).json()["status"] == "inactive"


async def test_archiving_a_version_in_use_is_409(authed: AsyncClient, ctx: Ctx) -> None:
    await _create(authed, ctx, activate=True)
    resp = await authed.post("/api/v1/agents/chaser/versions/1/archive")
    assert resp.status_code == 409 and "active mapping" in resp.json()["detail"]


async def test_deactivating_firm_deactivates_mappings(authed: AsyncClient, ctx: Ctx) -> None:
    m = (await _create(authed, ctx, activate=True)).json()
    await authed.post(f"/api/v1/firms/{ctx.firm['id']}/deactivate")
    assert (await authed.get(f"/api/v1/mappings/{m['id']}")).json()["status"] == "inactive"
