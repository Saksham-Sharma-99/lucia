"""Find the subject a message is about: fuzzy shortlist for the LLM, or an exact hit
(ORCHESTRATOR_SPEC §4.1). word_similarity scores how well a title appears inside the text."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import ContactPoint, Subject, SubjectContact

MIN_SCORE = 0.3


@dataclass(frozen=True)
class Candidate:
    subject_id: uuid.UUID
    title: str
    kind: str
    external_ref: str | None
    contacts: list[str]
    score: float


async def shortlist(
    session: AsyncSession, firm_id: uuid.UUID, query: str, limit: int = 10
) -> list[Candidate]:
    if not query.strip():
        return []
    q = query.lower()
    score = func.greatest(
        func.word_similarity(func.lower(Subject.title), q),
        func.word_similarity(func.lower(func.coalesce(Subject.external_ref, "")), q),
        func.coalesce(func.max(func.word_similarity(func.lower(ContactPoint.name), q)), 0),
    ).label("score")
    rows = await session.execute(
        select(Subject, func.array_remove(func.array_agg(ContactPoint.name), None), score)
        .outerjoin(SubjectContact, SubjectContact.subject_id == Subject.id)
        .outerjoin(ContactPoint, ContactPoint.id == SubjectContact.contact_point_id)
        .where(Subject.firm_id == firm_id, Subject.status == "open")
        .group_by(Subject.id)
        .having(score >= MIN_SCORE)
        .order_by(text("score DESC"), Subject.title)
        .limit(limit)
    )
    return [
        Candidate(s.id, s.title, s.kind, s.external_ref, sorted(names), round(float(sc), 4))
        for s, names, sc in rows.all()
    ]


async def exact_match(session: AsyncSession, firm_id: uuid.UUID, query: str) -> uuid.UUID | None:
    """The one open subject whose title or external ref appears verbatim in the text."""
    q = query.lower()
    hits = list(
        await session.scalars(
            select(Subject.id).where(
                Subject.firm_id == firm_id,
                Subject.status == "open",
                (func.strpos(q, func.lower(Subject.title)) > 0)
                | (func.strpos(q, func.lower(Subject.external_ref)) > 0),
            )
        )
    )
    return hits[0] if len(hits) == 1 else None
