from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import ContactPoint, Subject, SubjectContact
from lucia.subjects.search import exact_match, shortlist
from tests.world import make_world


async def _extra(db: AsyncSession, firm_id: object) -> None:
    db.add_all(
        [
            Subject(
                firm_id=firm_id, kind="matter", title="Roe v. Apex Logistics", external_ref="ROE-7"
            ),
            Subject(firm_id=firm_id, kind="matter", title="Doe v. Acme (closed)", status="closed"),
        ]
    )
    await db.commit()


async def test_shortlist_ranks_by_title_and_contact_name(db: AsyncSession) -> None:
    w = await make_world(db)
    await _extra(db, w.firm.id)
    got = await shortlist(db, w.firm.id, "please call jane doe about the acme trucking case")
    assert got[0].subject_id == w.subject.id
    assert got[0].contacts == ["Jane Doe"]
    assert all("closed" not in c.title for c in got)


async def test_shortlist_is_firm_scoped(db: AsyncSession) -> None:
    w = await make_world(db)
    other = await make_world(db, slug="other", handle="other")
    got = await shortlist(db, w.firm.id, "Doe v. Acme Trucking")
    assert {c.subject_id for c in got} == {w.subject.id}
    assert other.subject.id not in {c.subject_id for c in got}


async def test_shortlist_of_empty_text_is_empty(db: AsyncSession) -> None:
    w = await make_world(db)
    assert await shortlist(db, w.firm.id, "   ") == []


async def test_exact_match_on_external_ref_or_title(db: AsyncSession) -> None:
    w = await make_world(db)
    await _extra(db, w.firm.id)
    assert await exact_match(db, w.firm.id, "status of roe-7 please") is not None
    assert await exact_match(db, w.firm.id, "update on doe v. acme trucking?") == w.subject.id
    assert await exact_match(db, w.firm.id, "something else entirely") is None


async def test_contact_link_needed_for_contact_names(db: AsyncSession) -> None:
    w = await make_world(db)
    db.add(ContactPoint(firm_id=w.firm.id, name="Unlinked Person"))
    await db.commit()
    got = await shortlist(db, w.firm.id, "Unlinked Person")
    assert all(c.contacts != ["Unlinked Person"] for c in got)
    assert SubjectContact.__tablename__ == "subject_contacts"
