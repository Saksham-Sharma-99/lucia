"""Which subject a chat is about: an exact match, else a fuzzy shortlist the model picks from
(ORCHESTRATOR_SPEC §4, D4)."""

import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.config import get_settings
from lucia.db.models import Conversation, Message
from lucia.orchestrator.llm import ask
from lucia.orchestrator.prompts import SUBJECT
from lucia.orchestrator.schemas import SubjectPick
from lucia.subjects.search import Candidate, exact_match, shortlist


@dataclass(frozen=True)
class SubjectOutcome:
    subject_id: uuid.UUID | None
    method: Literal["exact", "llm", "none"]
    confidence: float = 0.0
    candidates: list[Candidate] = field(default_factory=list)


async def resolve(session: AsyncSession, conv: Conversation, msg: Message) -> SubjectOutcome:
    if hit := await exact_match(session, conv.firm_id, msg.body):
        return SubjectOutcome(hit, "exact", 1.0)
    recent = await session.scalars(
        select(Message.body)
        .where(Message.conversation_id == conv.id, Message.actor == "human")
        .order_by(Message.seq.desc())
        .limit(5)
    )
    candidates = await shortlist(session, conv.firm_id, " ".join(recent))
    if not candidates:
        return SubjectOutcome(None, "none")
    listing = candidates_text(candidates)
    pick = await ask(
        session,
        conv.firm_id,
        "subject",
        SUBJECT,
        f"## candidates\n{listing}\n\n## message\n{msg.body}",
        SubjectPick,
    )
    known = {str(c.subject_id): c for c in candidates}
    if pick.subject_id in known and pick.confidence >= get_settings().subject_auto_threshold:
        return SubjectOutcome(known[pick.subject_id].subject_id, "llm", pick.confidence)
    # The picker leads with the model's guess, then the best fuzzy matches.
    ranked = sorted(candidates, key=lambda c: (str(c.subject_id) != pick.subject_id, -c.score))
    return SubjectOutcome(None, "none", pick.confidence, ranked[:3])


def candidates_text(candidates: list[Candidate]) -> str:
    """The shortlist the model picks from (shared with the evals)."""
    return "\n".join(
        f"- {c.subject_id}: {c.title} ({c.kind}, ref {c.external_ref}; "
        f"contacts {', '.join(c.contacts)})"
        for c in candidates
    )
