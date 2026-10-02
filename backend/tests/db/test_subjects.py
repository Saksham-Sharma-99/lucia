import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import ContactPoint, Firm, Subject, SubjectContact


async def _firm(db: AsyncSession, slug: str = "f-one") -> Firm:
    firm = Firm(name=slug, slug=slug, timezone="America/New_York", color="#000000", settings={})
    db.add(firm)
    await db.flush()
    return firm


async def test_subject_with_contact(db: AsyncSession) -> None:
    firm = await _firm(db)
    subject = Subject(firm_id=firm.id, kind="matter", title="Doe v. Acme", external_ref="D-1")
    cp = ContactPoint(
        firm_id=firm.id, name="Jane Doe", phones=[{"e164": "+15555550100", "type": "voice"}]
    )
    db.add_all([subject, cp])
    await db.flush()
    db.add(
        SubjectContact(
            firm_id=firm.id,
            subject_id=subject.id,
            contact_point_id=cp.id,
            role="client",
            consent={"voice": {"status": "granted"}},
            alias_ordinal=1,
        )
    )
    await db.flush()
    assert subject.status == "open" and subject.revision == 1


async def test_external_ref_is_unique_per_firm_but_nulls_repeat(db: AsyncSession) -> None:
    firm = await _firm(db)
    db.add_all(
        [
            Subject(firm_id=firm.id, kind="matter", title="A"),
            Subject(firm_id=firm.id, kind="matter", title="B"),
            Subject(firm_id=firm.id, kind="matter", title="C", external_ref="X"),
        ]
    )
    await db.flush()
    db.add(Subject(firm_id=firm.id, kind="matter", title="D", external_ref="X"))
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.parametrize(
    "bad",
    [{"kind": "Not OK!"}, {"status": "archived"}],
)
async def test_subject_checks(db: AsyncSession, bad: dict[str, str]) -> None:
    firm = await _firm(db)
    db.add(Subject(**{"firm_id": firm.id, "kind": "matter", "title": "A", **bad}))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_contact_role_check(db: AsyncSession) -> None:
    firm = await _firm(db)
    s = Subject(firm_id=firm.id, kind="matter", title="A")
    cp = ContactPoint(firm_id=firm.id, name="X")
    db.add_all([s, cp])
    await db.flush()
    db.add(
        SubjectContact(
            firm_id=firm.id, subject_id=s.id, contact_point_id=cp.id, role="boss", alias_ordinal=1
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_contact_point_of_another_firm_cannot_be_linked(db: AsyncSession) -> None:
    a, b = await _firm(db, "f-a"), await _firm(db, "f-b")
    s = Subject(firm_id=a.id, kind="matter", title="A")
    cp = ContactPoint(firm_id=b.id, name="X")
    db.add_all([s, cp])
    await db.flush()
    db.add(
        SubjectContact(
            firm_id=a.id, subject_id=s.id, contact_point_id=cp.id, role="client", alias_ordinal=1
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()
