"""A small runtime world built straight through the ORM: one firm with a Vapi line, one
voice agent mapped to it, one subject with a client contact."""

import copy
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.security import canonical_hash, hash_password
from lucia.db.models import (
    Agent,
    AgentPrompt,
    AgentRun,
    AppUser,
    CompiledAgentFirmMapping,
    ConnectorConnection,
    ContactPoint,
    Firm,
    RunTask,
    Subject,
    SubjectContact,
)
from lucia.firms.schemas import FirmSettings
from lucia.studio.config_schema import VersionConfig

VOICE_CONFIG: dict[str, Any] = VersionConfig.model_validate(
    {
        "system_prompt": "You check in with clients by phone.",
        "models": {"loop": "gpt-5.6-sol", "guardrail": "gpt-5.6-luna", "judge": "gpt-5.6"},
        "capabilities": [{"connector": "vapi", "tools": ["vapi.place_call"]}],
        "follow_up": {"mode": "none"},
        "alert_policy": {"default_channels": {"P0": ["in_app"], "P1": ["in_app"], "P2": []}},
        "policy_pack": [
            {"rule": "recipient_must_be_contact", "params": {}},
            {"rule": "consent_required", "params": {"channel": ["voice"], "roles": ["client"]}},
            {
                "rule": "quiet_hours",
                "params": {"start": "20:00", "end": "09:00", "tz": "recipient"},
            },
            {"rule": "opt_out_enforced", "params": {}},
        ],
    }
).stored()


@dataclass
class World:
    user: AppUser
    firm: Firm
    agent: Agent
    version: AgentPrompt
    vapi: ConnectorConnection
    mapping: CompiledAgentFirmMapping
    subject: Subject
    jane: ContactPoint
    jane_link: SubjectContact


async def make_world(
    db: AsyncSession,
    *,
    slug: str = "smith",
    handle: str = "checkin",
    config: dict[str, Any] | None = None,
    use_cases: list[str] | None = None,
) -> World:
    cfg = copy.deepcopy(config or VOICE_CONFIG)
    user = AppUser(username=f"u-{slug}", display_name="U", password_hash=hash_password("x" * 12))
    firm = Firm(
        name=slug.title(),
        slug=slug,
        timezone="America/New_York",
        color="#000000",
        settings=FirmSettings().model_dump(mode="json"),
    )
    db.add_all([user, firm])
    await db.flush()
    agent = Agent(
        handle=handle,
        name=handle.title(),
        description=f"The {handle} agent",
        use_cases=use_cases or [f"{handle} the client"],
    )
    db.add(agent)
    await db.flush()
    version = AgentPrompt(
        agent_id=agent.id,
        version=1,
        config=cfg,
        config_hash=canonical_hash(cfg),
        created_by=user.id,
    )
    vapi = ConnectorConnection(
        firm_id=firm.id,
        connector="vapi",
        label="Main line",
        status="connected",
        config={"phone_number_id": "pn_1", "phone_number": "+15550000000"},
    )
    db.add_all([version, vapi])
    await db.flush()
    mapping = CompiledAgentFirmMapping(
        agent_prompt_id=version.id,
        agent_id=agent.id,
        firm_id=firm.id,
        identities={"vapi": str(vapi.id)},
        status="active",
        mapped_by=user.id,
    )
    subject = Subject(
        firm_id=firm.id, kind="matter", title="Doe v. Acme Trucking", external_ref="DOE-1"
    )
    jane = ContactPoint(
        firm_id=firm.id,
        name="Jane Doe",
        phones=[{"e164": "+15555550100", "type": "voice", "label": "mobile"}],
        tz="America/New_York",
    )
    db.add_all([mapping, subject, jane])
    await db.flush()
    link = SubjectContact(
        firm_id=firm.id,
        subject_id=subject.id,
        contact_point_id=jane.id,
        role="client",
        consent={"voice": {"status": "granted"}},
        alias_ordinal=1,
    )
    db.add(link)
    await db.commit()
    return World(user, firm, agent, version, vapi, mapping, subject, jane, link)


async def make_run(db: AsyncSession, w: World, **fields: Any) -> AgentRun:
    run = AgentRun(
        firm_id=w.firm.id,
        mapping_id=w.mapping.id,
        agent_id=w.agent.id,
        agent_prompt_id=w.version.id,
        origin="playground",
        **{"subject_id": w.subject.id, **fields},
    )
    db.add(run)
    await db.commit()
    return run


async def make_task(
    db: AsyncSession, w: World, run: AgentRun, key: str = "checkin:run", **fields: Any
) -> RunTask:
    base: dict[str, Any] = {
        "kind": "checkin",
        "target": {"type": "run", "ref": None},
        "title": "Check in with Jane",
        "goal": "Find out how Jane is doing",
        "created_by": "triage",
    }
    task = RunTask(firm_id=w.firm.id, run_id=run.id, key=key, **{**base, **fields})
    db.add(task)
    await db.commit()
    return task


def item(n: int, kind: str = "subagent", status: str = "PENDING", **fields: Any) -> dict[str, Any]:
    """A stored plan item (DATA_MODEL §4.3)."""
    return {
        "id": f"i{n}",
        "ordinal": n,
        "title": f"item {n}",
        "kind": kind,
        "tool": fields.pop("tool", "vapi.place_call" if kind == "tool" else None),
        "input_hint": "",
        "expected_output": "",
        "uses": [],
        "wait": None,
        "status": status,
        "attempts": 0,
        "step_ids": [],
        "output": None,
        "reason": None,
        "superseded_by": [],
        "added_in": 0,
        **fields,
    }


async def make_leased_run(db: AsyncSession, w: World, **fields: Any) -> AgentRun:
    """An ACTIVE run held by epoch 1 for the next hour, as a worker would hold it."""
    from datetime import timedelta

    from lucia.core.clock import get_clock

    held = {
        "status": "ACTIVE",
        "lease_epoch": 1,
        "lease_owner": "test",
        "lease_expires_at": get_clock().now() + timedelta(hours=1),
    }
    return await make_run(db, w, **{**held, **fields})
