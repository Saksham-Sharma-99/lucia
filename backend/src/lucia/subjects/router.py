import uuid
from typing import Annotated

from fastapi import Query, status

from lucia.api.tags import api_router
from lucia.auth.deps import CurrentUser, DbSession
from lucia.core.pagination import Page, Paging
from lucia.db.models import ContactPoint, Firm, Subject, SubjectContact
from lucia.db.models.subject import SubjectStatus
from lucia.db.queries import get_or_404
from lucia.subjects import schemas as s
from lucia.subjects import service

router = api_router("subjects")
Q = Annotated[str | None, Query(max_length=100)]


@router.get(
    "/firms/{firm_id}/subjects", summary="List a firm's subjects", operation_id="listSubjects"
)
async def list_subjects(
    firm_id: uuid.UUID,
    session: DbSession,
    paging: Paging,
    q: Q = None,
    kind: str | None = None,
    status: SubjectStatus | None = None,
) -> Page[s.SubjectOut]:
    await get_or_404(session, Firm, firm_id, "Firm")
    return await service.list_subjects(session, firm_id, paging, q, kind, status)


@router.post(
    "/firms/{firm_id}/subjects",
    status_code=status.HTTP_201_CREATED,
    summary="Create a subject",
    operation_id="createSubject",
)
async def create_subject(
    firm_id: uuid.UUID, body: s.SubjectCreate, session: DbSession, user: CurrentUser
) -> s.SubjectDetail:
    await get_or_404(session, Firm, firm_id, "Firm")
    return await service.detail(session, await service.create_subject(session, firm_id, body, user))


@router.get(
    "/firms/{firm_id}/subject-kinds",
    summary="The subject kinds a firm uses",
    operation_id="listSubjectKinds",
)
async def list_kinds(firm_id: uuid.UUID, session: DbSession) -> list[str]:
    return await service.kinds(session, firm_id)


@router.get("/subjects/{subject_id}", summary="Get a subject", operation_id="getSubject")
async def get_subject(subject_id: uuid.UUID, session: DbSession) -> s.SubjectDetail:
    return await service.detail(session, await get_or_404(session, Subject, subject_id, "Subject"))


@router.patch("/subjects/{subject_id}", summary="Update a subject", operation_id="updateSubject")
async def patch_subject(
    subject_id: uuid.UUID, body: s.SubjectPatch, session: DbSession
) -> s.SubjectDetail:
    subject = await get_or_404(session, Subject, subject_id, "Subject")
    return await service.detail(session, await service.patch_subject(session, subject, body))


@router.get(
    "/firms/{firm_id}/contact-points",
    summary="List a firm's contact points",
    operation_id="listContactPoints",
)
async def list_contact_points(
    firm_id: uuid.UUID, session: DbSession, paging: Paging, q: Q = None
) -> Page[s.ContactPointOut]:
    return await service.list_contact_points(session, firm_id, paging, q)


@router.post(
    "/firms/{firm_id}/contact-points",
    status_code=status.HTTP_201_CREATED,
    summary="Create a contact point",
    operation_id="createContactPoint",
)
async def create_contact_point(
    firm_id: uuid.UUID, body: s.ContactPointCreate, session: DbSession
) -> s.ContactPointOut:
    await get_or_404(session, Firm, firm_id, "Firm")
    cp = await service.create_contact_point(session, firm_id, body)
    return s.ContactPointOut.model_validate(cp)


@router.patch(
    "/contact-points/{contact_point_id}",
    summary="Update a contact point (clearing an opt-out needs a reason)",
    operation_id="updateContactPoint",
)
async def patch_contact_point(
    contact_point_id: uuid.UUID, body: s.ContactPointPatch, session: DbSession, user: CurrentUser
) -> s.ContactPointOut:
    cp = await get_or_404(session, ContactPoint, contact_point_id, "Contact point")
    return s.ContactPointOut.model_validate(
        await service.patch_contact_point(session, cp, body, user)
    )


@router.post(
    "/subjects/{subject_id}/contacts",
    status_code=status.HTTP_201_CREATED,
    summary="Link a contact point to a subject with a role",
    operation_id="linkSubjectContact",
)
async def link_contact(
    subject_id: uuid.UUID, body: s.SubjectContactCreate, session: DbSession
) -> s.SubjectContactOut:
    subject = await get_or_404(session, Subject, subject_id, "Subject")
    return await service.link_contact(session, subject, body)


@router.patch(
    "/subject-contacts/{link_id}",
    summary="Change a contact's role or consent on a subject",
    operation_id="updateSubjectContact",
)
async def patch_link(
    link_id: uuid.UUID, body: s.SubjectContactPatch, session: DbSession, user: CurrentUser
) -> s.SubjectContactOut:
    link = await get_or_404(session, SubjectContact, link_id, "Subject contact")
    return await service.patch_link(session, link, body, user)


@router.delete(
    "/subject-contacts/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink a contact from a subject",
    operation_id="unlinkSubjectContact",
)
async def unlink(link_id: uuid.UUID, session: DbSession) -> None:
    await service.unlink(
        session, await get_or_404(session, SubjectContact, link_id, "Subject contact")
    )
