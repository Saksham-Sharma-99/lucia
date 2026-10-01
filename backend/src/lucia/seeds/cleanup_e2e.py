"""Hard-deletes what the Playwright smoke run creates: agents `@e2e-*` and firms `e2e-firm-*`,
with their versions, mappings and connections. Run after every E2E run:
`uv run python -m lucia.seeds.cleanup_e2e` (Playwright's global teardown does)."""

import asyncio
from typing import Any, cast

from sqlalchemy import CursorResult, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.config import get_settings
from lucia.db.models import (
    Agent,
    AgentPrompt,
    CompiledAgentFirmMapping,
    ConnectorConnection,
    Firm,
)
from lucia.db.session import get_sessionmaker

AGENTS = Agent.handle.like("e2e-%")
FIRMS = Firm.slug.like("e2e-firm-%")


async def cleanup(session: AsyncSession) -> dict[str, int]:
    """Deletes children before parents; returns how many rows each step removed."""
    agents = select(Agent.id).where(AGENTS)
    firms = select(Firm.id).where(FIRMS)
    M = CompiledAgentFirmMapping
    steps = {
        "mappings": delete(M).where(or_(M.agent_id.in_(agents), M.firm_id.in_(firms))),
        "connections": delete(ConnectorConnection).where(ConnectorConnection.firm_id.in_(firms)),
        "versions": delete(AgentPrompt).where(AgentPrompt.agent_id.in_(agents)),
        "agents": delete(Agent).where(AGENTS),
        "firms": delete(Firm).where(FIRMS),
    }
    removed = {
        # A DELETE returns a CursorResult, which carries the affected row count.
        name: cast(CursorResult[Any], await session.execute(stmt)).rowcount
        for name, stmt in steps.items()
    }
    await session.commit()
    return removed


async def main() -> None:
    if get_settings().env == "production":
        raise SystemExit("Refusing to delete E2E data in production.")
    async with get_sessionmaker()() as session:
        removed = await cleanup(session)
    print("e2e cleanup: " + ", ".join(f"{n} {name}" for name, n in removed.items()))


if __name__ == "__main__":
    asyncio.run(main())
