import importlib.util
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import Agent, AgentPrompt, CompiledAgentFirmMapping
from tests.world import make_world

_PATH = Path(__file__).parents[2] / "alembic/versions/0006_remove_orchestrator_agent.py"
_spec = importlib.util.spec_from_file_location("m0006", _PATH)
assert _spec and _spec.loader
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


async def test_migration_deletes_the_orchestrator_and_its_rows(db: AsyncSession) -> None:
    await make_world(db, handle="orchestrator")
    await make_world(db, slug="other", handle="checkin")
    for sql in migration.STATEMENTS:
        await db.execute(text(sql))
    assert await db.scalar(select(func.count()).select_from(Agent)) == 1
    assert await db.scalar(select(func.count()).select_from(AgentPrompt)) == 1
    assert await db.scalar(select(func.count()).select_from(CompiledAgentFirmMapping)) == 1
