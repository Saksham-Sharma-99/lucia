"""The agents a firm can route to: its active, non-killed mappings (ORCHESTRATOR_SPEC §5)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import Agent, AgentPrompt, CompiledAgentFirmMapping

M = CompiledAgentFirmMapping


@dataclass(frozen=True)
class DirectoryAgent:
    agent_id: uuid.UUID
    handle: str
    name: str
    description: str
    use_cases: list[str]
    tools: list[str]


async def for_firm(session: AsyncSession, firm_id: uuid.UUID) -> list[DirectoryAgent]:
    rows = await session.execute(
        select(Agent, AgentPrompt.config)
        .join(M, M.agent_id == Agent.id)
        .join(AgentPrompt, AgentPrompt.id == M.agent_prompt_id)
        .where(M.firm_id == firm_id, M.status == "active", ~M.kill_switch, Agent.is_callable)
        .order_by(Agent.handle)
    )
    return [
        DirectoryAgent(
            agent.id,
            agent.handle,
            agent.name,
            agent.description,
            agent.use_cases,
            [t for cap in config["capabilities"] for t in cap["tools"]],
        )
        for agent, config in rows.all()
    ]


async def known_handles(session: AsyncSession, firm_id: uuid.UUID) -> set[str]:
    """Every agent mapped at the firm, active or not, so a stale @mention gets an answer."""
    return set(
        await session.scalars(
            select(Agent.handle).join(M, M.agent_id == Agent.id).where(M.firm_id == firm_id)
        )
    )


def describe(directory: list[DirectoryAgent]) -> str:
    """The agent listing the router scores against (shared with the evals)."""
    return "\n".join(
        f"- @{a.handle}: {a.name}. {a.description} "
        f"Use cases: {'; '.join(a.use_cases)}. Tools: {', '.join(a.tools)}"
        for a in directory
    )
