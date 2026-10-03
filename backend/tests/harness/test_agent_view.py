from sqlalchemy.ext.asyncio import AsyncSession

from lucia.harness.agent_view import load
from tests.world import VOICE_CONFIG, make_run, make_world


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


async def test_instructions_carry_the_hitl_triggers(db: AsyncSession) -> None:
    cfg = {**VOICE_CONFIG, "hitl": {"ask_on": ["legal_question", "client_distressed"]}}
    w = await make_world(db, config=cfg)
    view = await load(db, await make_run(db, w))
    assert view.instructions.startswith(view.config.system_prompt)
    assert "Ask a person (a human item) when: legal question, client distressed." in (
        view.instructions
    )


async def test_instructions_are_the_prompt_without_triggers(db: AsyncSession) -> None:
    w = await make_world(db)
    view = await load(db, await make_run(db, w))
    assert view.instructions == view.config.system_prompt


async def test_only_tools_the_runtime_can_run_are_offered(db: AsyncSession) -> None:
    email = {"connector": "gmail", "tools": ["gmail.send_email", "gmail.read_thread"]}
    cfg = {**VOICE_CONFIG, "capabilities": [*VOICE_CONFIG["capabilities"], email]}
    w = await make_world(db, config=cfg)
    view = await load(db, await make_run(db, w))
    assert "vapi.place_call" in view.tools
    assert not {"gmail.send_email", "gmail.read_thread"} & set(view.tools)
