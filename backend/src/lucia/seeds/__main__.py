"""Idempotent seed: `uv run python -m lucia.seeds` (make seed). Upserts by unique key."""

import asyncio
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.config import get_settings
from lucia.core.security import hash_password
from lucia.db.models import Agent, AppUser, Firm
from lucia.db.session import get_sessionmaker
from lucia.firms.schemas import FirmSettings
from lucia.mappings.orchestrator import ensure_orchestrator_mapping
from lucia.registry.sync import sync_registry
from lucia.seeds.data import FIRMS, USERS
from lucia.studio import service as studio
from lucia.studio.schemas import AgentCreate
from lucia.studio.templates import ORCHESTRATOR, TEMPLATES


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
        await ensure_orchestrator_mapping(session, firm.id, user.id)
    await session.commit()


async def main() -> None:
    async with get_sessionmaker()() as session:
        await sync_registry(session)
        user = await seed_users(session)
        for spec in [*TEMPLATES, ORCHESTRATOR]:
            await seed_agent(session, spec, user)
        await seed_firms(session, user)


if __name__ == "__main__":
    asyncio.run(main())
