from sqlalchemy.ext.asyncio import AsyncSession

from lucia.harness.agent_view import load
from tests.world import make_run, make_world


async def test_view_combines_version_registry_and_mapping(db: AsyncSession) -> None:
    w = await make_world(db)
    run = await make_run(db, w)
    view = await load(db, run)
    tool = view.tools["vapi.place_call"]
    assert (tool.risk_tier, tool.is_async) == ("external_comm", True)
    assert "to_contact_id" in tool.input_schema["properties"]
    assert view.config.models.loop == "gpt-5.6-sol"
    assert {p.rule for p in view.policies} >= {"recipient_must_be_contact", "quiet_hours"}
    assert view.connection_id("vapi") == w.vapi.id
    assert view.agent.handle == "checkin" and view.subject.id == w.subject.id
