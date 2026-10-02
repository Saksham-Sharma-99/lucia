import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import AuditLog
from tests.factories import ZERO, Json, create_firm

JANE = {
    "name": "Jane Doe",
    "phones": [{"e164": "+15555550100", "type": "voice", "label": "mobile"}],
    "emails": ["Jane@Example.com"],
    "tz": "America/New_York",
}


@pytest.fixture
async def firm(authed: AsyncClient) -> Json:
    return await create_firm(authed)


async def _subject(client: AsyncClient, firm: Json, **extra: object) -> Json:
    body = {"kind": "matter", "title": "Doe v. Acme Trucking", "external_ref": "DOE-1", **extra}
    resp = await client.post(f"/api/v1/firms/{firm['id']}/subjects", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _contact(client: AsyncClient, firm: Json, **extra: object) -> Json:
    resp = await client.post(f"/api/v1/firms/{firm['id']}/contact-points", json={**JANE, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _link(client: AsyncClient, subject: Json, contact: Json, role: str = "client") -> Json:
    resp = await client.post(
        f"/api/v1/subjects/{subject['id']}/contacts",
        json={"contact_point_id": contact["id"], "role": role},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_and_get(authed: AsyncClient, firm: Json) -> None:
    s = await _subject(authed, firm, description="Truck accident")
    got = (await authed.get(f"/api/v1/subjects/{s['id']}")).json()
    assert (got["title"], got["status"], got["revision"], got["contacts"], got["runs"]) == (
        "Doe v. Acme Trucking",
        "open",
        1,
        [],
        [],
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("kind", "Bad Kind!"), ("title", ""), ("kind", "x" * 41), ("status", "archived")],
)
async def test_create_validation(authed: AsyncClient, firm: Json, field: str, value: str) -> None:
    resp = await authed.post(
        f"/api/v1/firms/{firm['id']}/subjects", json={"kind": "matter", "title": "A", field: value}
    )
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == f"/{field}"


async def test_kind_is_lowercased(authed: AsyncClient, firm: Json) -> None:
    assert (await _subject(authed, firm, kind="Prospect"))["kind"] == "prospect"


async def test_external_ref_taken_is_422(authed: AsyncClient, firm: Json) -> None:
    await _subject(authed, firm)
    resp = await authed.post(
        f"/api/v1/firms/{firm['id']}/subjects",
        json={"kind": "matter", "title": "Other", "external_ref": "DOE-1"},
    )
    assert resp.status_code == 422 and resp.json()["errors"][0]["code"] == "taken"


async def test_same_external_ref_in_another_firm_is_fine(authed: AsyncClient, firm: Json) -> None:
    await _subject(authed, firm)
    await _subject(authed, await create_firm(authed, slug="other-law"))


async def test_unknown_firm_or_subject_is_404(authed: AsyncClient) -> None:
    assert (await authed.get(f"/api/v1/firms/{ZERO}/subjects")).status_code == 404
    assert (await authed.get(f"/api/v1/subjects/{ZERO}")).status_code == 404


async def test_patch_bumps_revision(authed: AsyncClient, firm: Json) -> None:
    s = await _subject(authed, firm)
    got = (await authed.patch(f"/api/v1/subjects/{s['id']}", json={"status": "closed"})).json()
    assert (got["status"], got["revision"]) == ("closed", 2)


async def test_list_filters_and_search(authed: AsyncClient, firm: Json) -> None:
    await _subject(authed, firm)
    await _subject(authed, firm, title="Acme lead", kind="prospect", external_ref=None)
    base = f"/api/v1/firms/{firm['id']}/subjects"
    assert (await authed.get(base)).json()["total"] == 2
    assert [
        i["title"] for i in (await authed.get(base, params={"kind": "prospect"})).json()["items"]
    ] == ["Acme lead"]
    assert [i["title"] for i in (await authed.get(base, params={"q": "doe"})).json()["items"]] == [
        "Doe v. Acme Trucking"
    ]
    kinds = (await authed.get(f"/api/v1/firms/{firm['id']}/subject-kinds")).json()
    assert kinds == ["matter", "prospect"]


async def test_contacts_link_and_consent(authed: AsyncClient, firm: Json, db: AsyncSession) -> None:
    s = await _subject(authed, firm)
    c = await _contact(authed, firm)
    assert c["emails"] == ["jane@example.com"]
    link = await _link(authed, s, c)
    assert (link["alias_ordinal"], link["consent"]) == (1, {})
    resp = await authed.patch(
        f"/api/v1/subject-contacts/{link['id']}", json={"consent": {"voice": "granted"}}
    )
    consent = resp.json()["consent"]["voice"]
    assert consent["status"] == "granted" and consent["by"] and consent["at"]
    got = (await authed.get(f"/api/v1/subjects/{s['id']}")).json()
    assert got["contacts"][0]["contact_point"]["name"] == "Jane Doe"
    actions = set(await db.scalars(select(AuditLog.action)))
    assert "consent.updated" in actions


async def test_alias_ordinals_are_never_reused(authed: AsyncClient, firm: Json) -> None:
    s = await _subject(authed, firm)
    first = await _link(authed, s, await _contact(authed, firm))
    assert (await authed.delete(f"/api/v1/subject-contacts/{first['id']}")).status_code == 204
    second = await _link(authed, s, await _contact(authed, firm, name="Dr. Lee"), "provider")
    assert second["alias_ordinal"] == 2


async def test_cannot_link_a_contact_of_another_firm(authed: AsyncClient, firm: Json) -> None:
    s = await _subject(authed, firm)
    c = await _contact(authed, await create_firm(authed, slug="other-law"))
    resp = await authed.post(
        f"/api/v1/subjects/{s['id']}/contacts", json={"contact_point_id": c["id"], "role": "client"}
    )
    assert resp.status_code == 404


async def test_duplicate_link_is_409(authed: AsyncClient, firm: Json) -> None:
    s, c = await _subject(authed, firm), await _contact(authed, firm)
    await _link(authed, s, c)
    resp = await authed.post(
        f"/api/v1/subjects/{s['id']}/contacts", json={"contact_point_id": c["id"], "role": "client"}
    )
    assert resp.status_code == 409


@pytest.mark.parametrize(
    "phone",
    [{"e164": "555-0100", "type": "voice"}, {"e164": "+15555550100", "type": "pager"}],
)
async def test_bad_phone_is_422(authed: AsyncClient, firm: Json, phone: Json) -> None:
    resp = await authed.post(
        f"/api/v1/firms/{firm['id']}/contact-points", json={"name": "X", "phones": [phone]}
    )
    assert resp.status_code == 422


async def test_bad_role_is_422(authed: AsyncClient, firm: Json) -> None:
    s, c = await _subject(authed, firm), await _contact(authed, firm)
    resp = await authed.post(
        f"/api/v1/subjects/{s['id']}/contacts", json={"contact_point_id": c["id"], "role": "boss"}
    )
    assert resp.status_code == 422


async def test_opt_out_set_and_cleared_with_reason(
    authed: AsyncClient, firm: Json, db: AsyncSession
) -> None:
    c = await _contact(authed, firm)
    url = f"/api/v1/contact-points/{c['id']}"
    got = (await authed.patch(url, json={"opt_out": ["voice"]})).json()
    assert got["opt_out"]["voice"]["source"] == "human"
    resp = await authed.patch(url, json={"opt_out": []})
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/reason"
    got = (
        await authed.patch(url, json={"opt_out": [], "reason": "Client asked again by phone"})
    ).json()
    assert got["opt_out"] == {}
    actions = list(await db.scalars(select(AuditLog.action).order_by(AuditLog.created_at)))
    assert (
        actions.count("contact.opt_out_set") == 1 and actions.count("contact.opt_out_cleared") == 1
    )


async def test_contact_point_search(authed: AsyncClient, firm: Json) -> None:
    await _contact(authed, firm)
    await _contact(authed, firm, name="St. Mary's Records")
    page = (
        await authed.get(f"/api/v1/firms/{firm['id']}/contact-points", params={"q": "mary"})
    ).json()
    assert [c["name"] for c in page["items"]] == ["St. Mary's Records"]
