"""What a run executes: its pinned version, the registry tools it may use, and the policy
the mapping enforces (RUNTIME_SPEC §2)."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import (
    Agent,
    AgentPrompt,
    AgentRun,
    CompiledAgentFirmMapping,
    Firm,
    RegistryEntry,
    Subject,
)
from lucia.harness.tools.schemas import SCHEMAS as HARNESS_TOOLS
from lucia.mappings import resolve
from lucia.mappings.schemas import ResolvedPolicy, ResolvedRoute
from lucia.registry.snapshot import load_snapshot
from lucia.studio.config_schema import VersionConfig


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk_tier: str
    is_async: bool
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


@dataclass(frozen=True)
class AgentView:
    run: AgentRun
    agent: Agent
    config: VersionConfig
    mapping: CompiledAgentFirmMapping
    firm: Firm
    subject: Subject
    tools: dict[str, ToolSpec]
    policies: list[ResolvedPolicy]
    alert_routes: list[ResolvedRoute]

    def connection_id(self, connector: str) -> uuid.UUID:
        return uuid.UUID(self.mapping.identities[connector])


async def load(session: AsyncSession, run: AgentRun) -> AgentView:
    prompt = await session.get_one(AgentPrompt, run.agent_prompt_id)
    mapping = await session.get_one(CompiledAgentFirmMapping, run.mapping_id)
    firm = await session.get_one(Firm, run.firm_id)
    config = VersionConfig.model_validate(prompt.config)
    names = [t for cap in config.capabilities for t in cap.tools]
    entries = await session.scalars(
        select(RegistryEntry).where(RegistryEntry.kind == "tool", RegistryEntry.name.in_(names))
    )
    tools = {
        e.name: ToolSpec(
            e.name,
            e.description,
            e.risk_tier or "read",
            e.is_async,
            e.input_schema,
            e.output_schema,
        )
        for e in entries
    }
    tools.update(
        (name, ToolSpec(name, desc, "internal_write", False, schema, {}))
        for name, (desc, schema) in HARNESS_TOOLS.items()
    )
    settings = firm.settings
    return AgentView(
        run=run,
        agent=await session.get_one(Agent, run.agent_id),
        config=config,
        mapping=mapping,
        firm=firm,
        subject=await session.get_one(Subject, run.subject_id),
        tools=tools,
        policies=resolve.policies(
            prompt.config,
            settings.get("policy_floor", []),
            mapping.overrides,
            await load_snapshot(session),
        ),
        alert_routes=resolve.alert_routing(
            prompt.config, settings.get("alert_routing", {}), mapping.overrides
        ),
    )
