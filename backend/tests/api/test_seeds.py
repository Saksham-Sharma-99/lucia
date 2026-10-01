from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import Agent, AppUser, CompiledAgentFirmMapping, Firm
from lucia.seeds.__main__ import seed_agent, seed_firms, seed_users
from lucia.studio.templates import ORCHESTRATOR, TEMPLATES


async def _counts(db: AsyncSession) -> tuple[int, ...]:
    return tuple(
        [
            await db.scalar(select(func.count()).select_from(m)) or 0
            for m in (AppUser, Firm, Agent, CompiledAgentFirmMapping)
        ]
    )


async def test_seed_is_idempotent(db: AsyncSession) -> None:
    for _ in range(2):
        user = await seed_users(db)
        for spec in [*TEMPLATES, ORCHESTRATOR]:
            await seed_agent(db, spec, user)
        await seed_firms(db, user)
    assert await _counts(db) == (2, 2, 4, 2)
    templates = await db.scalar(select(func.count()).where(Agent.is_template.is_(True)))
    assert templates == 3
