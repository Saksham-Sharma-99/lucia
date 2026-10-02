import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.config import get_settings
from lucia.db.models import (
    Agent,
    AgentPrompt,
    AppUser,
    CompiledAgentFirmMapping,
    Firm,
    Subject,
    SubjectContact,
)
from lucia.seeds.__main__ import seed_agent, seed_firms, seed_runtime, seed_users
from lucia.studio.templates import TEMPLATES


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
        for spec in TEMPLATES:
            await seed_agent(db, spec, user)
        await seed_firms(db, user)
    assert await _counts(db) == (2, 2, 3, 0)
    assert await db.scalar(select(Agent.id).where(Agent.handle == "orchestrator")) is None
    templates = await db.scalar(select(func.count()).where(Agent.is_template.is_(True)))
    assert templates == 3


async def _seed_all(db: AsyncSession) -> None:
    user = await seed_users(db)
    for spec in TEMPLATES:
        await seed_agent(db, spec, user)
    await seed_firms(db, user)
    await seed_runtime(db, user)


async def test_runtime_seed_is_idempotent(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "vapi_phone_number_id", "pn_seed")
    for _ in range(2):
        await _seed_all(db)
    checkin = await db.scalar(select(Agent).where(Agent.handle == "checkin"))
    assert checkin is not None
    versions = list(await db.scalars(select(AgentPrompt).where(AgentPrompt.agent_id == checkin.id)))
    assert sorted(v.version for v in versions) == [1, 2]
    v2 = next(v for v in versions if v.version == 2)
    assert [c["connector"] for c in v2.config["capabilities"]] == ["vapi"]
    mapping = await db.scalar(
        select(CompiledAgentFirmMapping).where(CompiledAgentFirmMapping.agent_id == checkin.id)
    )
    assert mapping is not None
    assert (mapping.status, mapping.agent_prompt_id) == ("active", v2.id)
    assert await db.scalar(select(func.count()).select_from(Subject)) == 1
    link = await db.scalar(select(SubjectContact))
    assert link is not None and link.consent["voice"]["status"] == "granted"


async def test_runtime_seed_without_a_vapi_number_skips_the_mapping(db: AsyncSession) -> None:
    await _seed_all(db)
    assert await db.scalar(select(func.count()).select_from(CompiledAgentFirmMapping)) == 0
    assert await db.scalar(select(func.count()).select_from(Subject)) == 1


@pytest.mark.parametrize(
    ("spec", "window"),
    [
        ("records", ("18:00", "08:00")),
        ("checkin", ("20:00", "09:00")),
        ("liens", ("18:00", "08:00")),
    ],
)
def test_quiet_hours_are_blocked_windows(spec: str, window: tuple[str, str]) -> None:
    agent = next(t for t in TEMPLATES if t.handle == spec)
    rule = next(r for r in agent.config.policy_pack if r.rule == "quiet_hours")
    assert (rule.params["start"], rule.params["end"]) == window
