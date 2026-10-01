from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import (
    Agent,
    AgentPrompt,
    CompiledAgentFirmMapping,
    ConnectorConnection,
    Firm,
)
from lucia.seeds.cleanup_e2e import cleanup
from tests.factories import connected, create_agent, create_firm


async def _map(client: AsyncClient, agent: dict, firm: dict, gmail: str) -> None:
    body = {
        "firm_id": firm["id"],
        "agent_prompt_id": agent["versions"][0]["id"],
        "identities": {"gmail": gmail},
    }
    resp = await client.post("/api/v1/mappings", json=body)
    assert resp.status_code == 201, resp.text


async def _count(db: AsyncSession, model: type) -> int:
    return await db.scalar(select(func.count()).select_from(model)) or 0


async def test_removes_only_e2e_rows_and_everything_hanging_off_them(
    authed: AsyncClient, db: AsyncSession
) -> None:
    kept_agent = await create_agent(authed, "chaser")
    e2e_agent = await create_agent(authed, "e2e-abc")
    kept_firm = await create_firm(authed, "acme-law")
    e2e_firm = await create_firm(authed, "e2e-firm-abc")
    kept_gmail = str((await connected(db, kept_firm["id"], "gmail", {"mailbox": "a@x.com"})).id)
    e2e_gmail = str((await connected(db, e2e_firm["id"], "gmail", {"mailbox": "b@x.com"})).id)
    await _map(authed, kept_agent, kept_firm, kept_gmail)  # kept
    await _map(authed, e2e_agent, kept_firm, kept_gmail)  # e2e agent at a real firm: removed
    await _map(authed, kept_agent, e2e_firm, e2e_gmail)  # real agent at an e2e firm: removed
    before = {m: await _count(db, m) for m in (Agent, Firm, AgentPrompt, ConnectorConnection)}

    removed = await cleanup(db)

    assert removed == {"mappings": 2, "connections": 1, "versions": 1, "agents": 1, "firms": 1}
    assert await db.scalar(select(Agent.handle).where(Agent.handle.like("e2e-%"))) is None
    assert await db.scalar(select(Firm.slug).where(Firm.slug.like("e2e-firm-%"))) is None
    assert await _count(db, CompiledAgentFirmMapping) == 1
    assert await _count(db, Agent) == before[Agent] - 1
    assert await _count(db, Firm) == before[Firm] - 1
    assert await _count(db, AgentPrompt) == before[AgentPrompt] - 1
    assert await _count(db, ConnectorConnection) == before[ConnectorConnection] - 1


async def test_is_a_no_op_without_e2e_rows(authed: AsyncClient, db: AsyncSession) -> None:
    await create_agent(authed, "chaser")
    assert set((await cleanup(db)).values()) == {0}
