"""Idempotent seed: `uv run python -m lucia.seeds` (make seed). Upserts by unique key."""

import asyncio
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.config import get_settings
from lucia.core.security import canonical_hash, hash_password
from lucia.db.models import (
    Agent,
    AgentPrompt,
    AppUser,
    CompiledAgentFirmMapping,
    ConnectorConnection,
    ContactPoint,
    Firm,
    Subject,
    SubjectContact,
)
from lucia.db.session import get_sessionmaker
from lucia.firms.schemas import FirmSettings
from lucia.registry.sync import sync_registry
from lucia.seeds.data import FIRMS, USERS
from lucia.studio import service as studio
from lucia.studio.schemas import AgentCreate, VersionCreate
from lucia.studio.templates import CHECKIN_VOICE_ONLY, TEMPLATES


async def seed_users(session: AsyncSession) -> AppUser:
    password = get_settings().seed_password
    generated = not password
    first: AppUser | None = None
    for u in USERS:
        user = await session.scalar(select(AppUser).where(AppUser.username == u["username"]))
        if user is None:
            pw = password or secrets.token_urlsafe(12)
            user = AppUser(
                username=u["username"],
                display_name=u["display_name"],
                password_hash=hash_password(pw),
            )
            session.add(user)
            print(f"user {u['username']}: " + (f"password {pw}" if generated else "SEED_PASSWORD"))
        first = first or user
    await session.commit()
    assert first is not None
    return first


async def seed_agent(session: AsyncSession, spec: AgentCreate, user: AppUser) -> None:
    if await session.scalar(select(Agent.id).where(Agent.handle == spec.handle)):
        return
    await studio.create_agent(session, spec, user, is_template=spec in TEMPLATES)
    print(f"agent @{spec.handle}")


async def seed_firms(session: AsyncSession, user: AppUser) -> None:
    for f in FIRMS:
        firm = await session.scalar(select(Firm).where(Firm.slug == f["slug"]))
        if firm is None:
            firm = Firm(**f, settings=FirmSettings().model_dump(mode="json"))
            session.add(firm)
            await session.flush()
            print(f"firm {f['slug']}")
    await session.commit()


async def _checkin_v2(session: AsyncSession, user: AppUser) -> tuple[Agent, AgentPrompt]:
    agent = await session.scalar(select(Agent).where(Agent.handle == "checkin"))
    assert agent is not None
    config = CHECKIN_VOICE_ONLY.stored()
    version = await session.scalar(
        select(AgentPrompt).where(
            AgentPrompt.agent_id == agent.id, AgentPrompt.config_hash == canonical_hash(config)
        )
    )
    if version is None:
        body = VersionCreate(from_version=1, config=CHECKIN_VOICE_ONLY, changelog="Voice only")
        version = await studio.amend(session, "checkin", body, user)
        print(f"agent @checkin v{version.version} (voice only)")
    return agent, version


async def _demo_subject(session: AsyncSession, firm: Firm) -> None:
    ref = "DOE-2026-001"
    if await session.scalar(select(Subject.id).where(Subject.external_ref == ref)):
        return
    subject = Subject(
        firm_id=firm.id, kind="matter", title="Doe v. Acme Trucking", external_ref=ref
    )
    jane = ContactPoint(
        firm_id=firm.id,
        name="Jane Doe",
        phones=[{"e164": get_settings().seed_test_phone, "type": "voice", "label": "mobile"}],
        tz="America/New_York",
    )
    session.add_all([subject, jane])
    await session.flush()
    session.add(
        SubjectContact(
            firm_id=firm.id,
            subject_id=subject.id,
            contact_point_id=jane.id,
            role="client",
            consent={"voice": {"status": "granted", "by": "seed"}},
            alias_ordinal=1,
        )
    )
    print(f"subject {subject.title}")


async def seed_runtime(session: AsyncSession, user: AppUser) -> None:
    """The P1 demo (D56): Smith & Associates runs @checkin v2 on its Vapi line for Doe v. Acme.
    The mapping needs VAPI_PHONE_NUMBER_ID; without it only the subject is seeded."""
    firm = await session.scalar(select(Firm).where(Firm.slug == "smith-associates"))
    assert firm is not None
    agent, version = await _checkin_v2(session, user)
    await _demo_subject(session, firm)
    number = get_settings().vapi_phone_number_id
    if number:
        conn = await session.scalar(
            select(ConnectorConnection).where(
                ConnectorConnection.firm_id == firm.id, ConnectorConnection.connector == "vapi"
            )
        )
        if conn is None:
            conn = ConnectorConnection(
                firm_id=firm.id,
                connector="vapi",
                label="Main line",
                status="connected",
                config={"phone_number_id": number, "phone_number": ""},
            )
            session.add(conn)
            await session.flush()
        M = CompiledAgentFirmMapping
        if not await session.scalar(
            select(M.id).where(M.firm_id == firm.id, M.agent_id == agent.id)
        ):
            session.add(
                M(
                    agent_prompt_id=version.id,
                    agent_id=agent.id,
                    firm_id=firm.id,
                    identities={"vapi": str(conn.id)},
                    status="active",
                    mapped_by=user.id,
                )
            )
            print("mapping smith-associates -> @checkin v2")
    else:
        print("VAPI_PHONE_NUMBER_ID is empty: skipped the Vapi connection and @checkin mapping")
    await session.commit()


async def main() -> None:
    async with get_sessionmaker()() as session:
        await sync_registry(session)
        user = await seed_users(session)
        for spec in TEMPLATES:
            await seed_agent(session, spec, user)
        await seed_firms(session, user)
        await seed_runtime(session, user)


if __name__ == "__main__":
    asyncio.run(main())
