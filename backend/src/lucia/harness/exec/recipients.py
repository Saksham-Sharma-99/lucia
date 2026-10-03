"""Who an outbound tool would reach: a contact on the run's subject, never a raw address."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import AgentRun, ContactPoint, SubjectContact
from lucia.harness.exec.policy import Recipient


async def contact_recipient(
    session: AsyncSession, run: AgentRun, subject_contact_id: str | None, channel: str
) -> Recipient | None:
    try:
        link_id = uuid.UUID(subject_contact_id or "")
    except ValueError:
        return None
    row = (
        await session.execute(
            select(SubjectContact, ContactPoint)
            .join(ContactPoint, ContactPoint.id == SubjectContact.contact_point_id)
            .where(SubjectContact.id == link_id, SubjectContact.subject_id == run.subject_id)
        )
    ).first()
    if row is None:
        return None
    link, cp = row
    if channel == "voice":
        address = next((p["e164"] for p in cp.phones if p.get("type") == "voice"), "")
    else:
        address = cp.emails[0] if cp.emails else ""
    return Recipient(
        subject_contact_id=str(link.id),
        contact_point_id=str(cp.id),
        role=link.role,
        channel=channel,
        consent={ch: v.get("status", "unknown") for ch, v in link.consent.items()},
        opt_out=sorted(cp.opt_out),
        tz=cp.tz,
        org_daily_cap=cp.org_daily_cap,
        address=address,
    )
