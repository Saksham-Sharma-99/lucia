import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import Agent, CompiledAgentFirmMapping
from lucia.db.queries import latest_active_version
from lucia.studio.templates import ORCHESTRATOR

M = CompiledAgentFirmMapping


async def ensure_orchestrator_mapping(
    session: AsyncSession, firm_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Every firm gets an inactive @orchestrator mapping (activated once Slack is bound)."""
    agent = await session.scalar(select(Agent).where(Agent.handle == ORCHESTRATOR.handle))
    if agent is None or await session.scalar(
        select(M.id).where(M.firm_id == firm_id, M.agent_id == agent.id)
    ):
        return
    if version := await latest_active_version(session, agent.id):
        session.add(
            M(
                agent_prompt_id=version.id,
                agent_id=agent.id,
                firm_id=firm_id,
                identities={},
                overrides={},
                status="inactive",
                mapped_by=user_id,
            )
        )
