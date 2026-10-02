import uuid

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.audit import audit
from lucia.core.clock import get_clock
from lucia.core.errors import FieldError, conflict, invalid, not_found
from lucia.core.pagination import Page, PageParams, fetch_page
from lucia.db.models import Agent, AgentRun, AppUser, ContactPoint, Subject, SubjectContact
from lucia.db.models.run import LIVE
from lucia.db.queries import apply_patch, get_or_404, like_pattern, unique_or
from lucia.harness.control import resume_for_subject
from lucia.subjects import schemas as s
from lucia.worker.dispatch import send

REF_TAKEN = invalid(
    [FieldError(path="/external_ref", code="taken", message="External ref is taken")]
)
REF_INDEX = "subjects_firm_id_external_ref_key"
SC = SubjectContact


async def list_subjects(
    session: AsyncSession,
    firm_id: uuid.UUID,
    paging: PageParams,
    q: str | None,
    kind: str | None,
    status: str | None,
) -> Page[s.SubjectOut]:
    contacts = select(func.count()).where(SC.subject_id == Subject.id).scalar_subquery()
    runs = (
        select(func.count())
        .where(AgentRun.subject_id == Subject.id, AgentRun.status.in_(LIVE))
        .scalar_subquery()
    )
    stmt = select(Subject, contacts, runs).where(Subject.firm_id == firm_id)
    if q:
        like = like_pattern(q)
        named = (
            select(SC.id)
            .join(ContactPoint, ContactPoint.id == SC.contact_point_id)
            .where(SC.subject_id == Subject.id, ContactPoint.name.ilike(like, escape="\\"))
            .exists()
        )
        stmt = stmt.where(
            Subject.title.ilike(like, escape="\\")
            | Subject.external_ref.ilike(like, escape="\\")
            | named
        )
    if kind:
        stmt = stmt.where(Subject.kind == kind)
    if status:
        stmt = stmt.where(Subject.status == status)
    rows, total = await fetch_page(
        session, stmt.order_by(Subject.title, Subject.id), paging, scalars=False
    )
    items = [
        s.SubjectOut.model_validate(subj).model_copy(
            update={"contact_count": n, "live_run_count": r}
        )
        for subj, n, r in rows
    ]
    return Page.of(items, total, paging)


async def kinds(session: AsyncSession, firm_id: uuid.UUID) -> list[str]:
    return list(
        await session.scalars(
            select(Subject.kind).where(Subject.firm_id == firm_id).distinct().order_by(Subject.kind)
        )
    )


async def create_subject(
    session: AsyncSession, firm_id: uuid.UUID, body: s.SubjectCreate, user: AppUser
) -> Subject:
    subject = Subject(firm_id=firm_id, created_by=user.id, **body.model_dump())
    session.add(subject)
    async with unique_or(session, REF_INDEX, REF_TAKEN):
        await session.flush()
    await session.commit()
    return subject


async def patch_subject(session: AsyncSession, subject: Subject, body: s.SubjectPatch) -> Subject:
    reopened = subject.status == "closed" and body.status == "open"
    apply_patch(subject, body)
    subject.revision += 1
    async with unique_or(session, REF_INDEX, REF_TAKEN):
        await session.flush()
    resumed = await resume_for_subject(session, subject.id) if reopened else []
    await session.commit()
    for run_id in resumed:
        send("harness.advance_run", run_id)
    return subject


async def detail(session: AsyncSession, subject: Subject) -> s.SubjectDetail:
    links = await session.execute(
        select(SC, ContactPoint)
        .join(ContactPoint, ContactPoint.id == SC.contact_point_id)
        .where(SC.subject_id == subject.id)
        .order_by(SC.alias_ordinal)
    )
    runs = await session.execute(
        select(AgentRun.id, Agent.handle, AgentRun.status)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(AgentRun.subject_id == subject.id)
        .order_by(AgentRun.created_at.desc())
    )
    contacts = [contact_out(link, cp) for link, cp in links.all()]
    return s.SubjectDetail(
        **s.SubjectOut.model_validate(subject).model_dump(),
        contacts=contacts,
        runs=[s.RunBrief(id=i, agent_handle=h, status=st) for i, h, st in runs.all()],
    )


def contact_out(link: SubjectContact, cp: ContactPoint) -> s.SubjectContactOut:
    return s.SubjectContactOut(
        id=link.id,
        role=link.role,
        consent=link.consent,
        alias_ordinal=link.alias_ordinal,
        contact_point=s.ContactPointOut.model_validate(cp),
    )


async def list_contact_points(
    session: AsyncSession, firm_id: uuid.UUID, paging: PageParams, q: str | None
) -> Page[s.ContactPointOut]:
    stmt = select(ContactPoint).where(ContactPoint.firm_id == firm_id)
    if q:
        like = like_pattern(q)
        stmt = stmt.where(
            or_(
                *(
                    field.ilike(like, escape="\\")
                    for field in (
                        ContactPoint.name,
                        ContactPoint.org_name,
                        cast(ContactPoint.emails, String),  # JSON text: matches any address
                        cast(ContactPoint.phones, String),
                    )
                )
            )
        )
    rows, total = await fetch_page(session, stmt.order_by(ContactPoint.name), paging)
    # A contact's type is its role on each subject it's on (one query for the page).
    links = await session.execute(
        select(SC.contact_point_id, SC.role)
        .where(SC.contact_point_id.in_([r.id for r in rows]))
        .distinct()
        .order_by(SC.role)
    )
    roles: dict[uuid.UUID, list[str]] = {}
    for cp_id, role in links.all():
        roles.setdefault(cp_id, []).append(role)
    items = [
        s.ContactPointOut.model_validate(r).model_copy(update={"roles": roles.get(r.id, [])})
        for r in rows
    ]
    return Page.of(items, total, paging)


async def create_contact_point(
    session: AsyncSession, firm_id: uuid.UUID, body: s.ContactPointCreate
) -> ContactPoint:
    cp = ContactPoint(firm_id=firm_id, **body.model_dump(mode="json"))
    session.add(cp)
    await session.commit()
    return cp


async def patch_contact_point(
    session: AsyncSession, cp: ContactPoint, body: s.ContactPointPatch, user: AppUser
) -> ContactPoint:
    """Opt-outs are set by anyone and cleared only with a reason (audited, HLD §15)."""
    if body.opt_out is not None:
        added = set(body.opt_out) - set(cp.opt_out)
        removed = set(cp.opt_out) - set(body.opt_out)
        if removed and not body.reason:
            raise invalid(
                [FieldError(path="/reason", code="required", message="Say why the opt-out ends")]
            )
        stamp = {"at": get_clock().now().isoformat(), "source": "human", "by": str(user.id)}
        cp.opt_out = {
            **{c: v for c, v in cp.opt_out.items() if c not in removed},
            **{c: stamp for c in added},
        }
        for action, channels in (
            ("contact.opt_out_set", added),
            ("contact.opt_out_cleared", removed),
        ):
            if channels:
                await audit(
                    session,
                    action=action,
                    entity_type="contact_point",
                    entity_id=cp.id,
                    firm_id=cp.firm_id,
                    actor_type="user",
                    actor_id=str(user.id),
                    data={"channels": sorted(channels), "reason": body.reason},
                )
    apply_patch(cp, body.model_copy(update={"opt_out": None, "reason": None}))
    if body.phones is not None:
        cp.phones = [p.model_dump() for p in body.phones]
    await session.commit()
    return cp


async def link_contact(
    session: AsyncSession, subject: Subject, body: s.SubjectContactCreate
) -> s.SubjectContactOut:
    cp = await session.get(ContactPoint, body.contact_point_id)
    if cp is None or cp.firm_id != subject.firm_id:
        raise not_found("Contact point")
    if await session.scalar(
        select(SC.id).where(
            SC.subject_id == subject.id, SC.contact_point_id == cp.id, SC.role == body.role
        )
    ):
        raise conflict("This contact already has that role on the subject")
    # Ordinals are never reused, so "Provider 2" always means the same contact (HLD §13).
    used = await session.scalar(
        select(func.max(SC.alias_ordinal)).where(SC.subject_id == subject.id)
    )
    link = SC(
        firm_id=subject.firm_id,
        subject_id=subject.id,
        contact_point_id=cp.id,
        role=body.role,
        alias_ordinal=max(used or 0, subject.data.get("alias_high_water", 0)) + 1,
    )
    session.add(link)
    subject.data = {**subject.data, "alias_high_water": link.alias_ordinal}
    await session.commit()
    return contact_out(link, cp)


async def patch_link(
    session: AsyncSession, link: SubjectContact, body: s.SubjectContactPatch, user: AppUser
) -> s.SubjectContactOut:
    if body.role:
        link.role = body.role
    if body.consent:
        stamp = {"at": get_clock().now().isoformat(), "by": str(user.id)}
        link.consent = {
            **link.consent,
            **{ch: {"status": st, **stamp} for ch, st in body.consent.items()},
        }
        await audit(
            session,
            action="consent.updated",
            entity_type="subject_contact",
            entity_id=link.id,
            firm_id=link.firm_id,
            actor_type="user",
            actor_id=str(user.id),
            data={**body.consent},
        )
    await session.commit()
    return contact_out(
        link, await get_or_404(session, ContactPoint, link.contact_point_id, "Contact point")
    )


async def unlink(session: AsyncSession, link: SubjectContact) -> None:
    await session.delete(link)
    await session.commit()
