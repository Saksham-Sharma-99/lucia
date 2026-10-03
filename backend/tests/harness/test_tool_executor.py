from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AgentRun, AgentRunStep, StepResult
from lucia.harness.agent_view import load
from lucia.harness.exec import tool_executor
from lucia.harness.exec.guardrail import GuardrailVerdict
from lucia.harness.tools.base import ToolContext
from lucia.llm.client import LLMError
from lucia.llm.fake import FakeLLM
from tests.harness.outbox_fakes import FakeCall
from tests.world import World, item, make_leased_run, make_task, make_world

OK = GuardrailVerdict(ok=True, reasons=[])


@pytest.fixture
def call(monkeypatch: pytest.MonkeyPatch) -> FakeCall:
    fake = FakeCall()
    monkeypatch.setitem(tool_executor.OUTBOX, "vapi.place_call", fake)
    return fake


async def _ctx(db: AsyncSession, w: World | None = None) -> tuple[World, ToolContext]:
    w = w or await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run, plan=[item(1, "tool", status="RUNNING", attempts=1)])
    return w, ToolContext(db, await load(db, run), task, task.plan[0], 1)


def _args(w: World, **kw: Any) -> dict[str, Any]:
    return {
        "to_contact_id": str(w.jane_link.id),
        "script": "Ask how Jane is doing.",
        "first_message": "Hi Jane",
        **kw,
    }


async def test_happy_path_writes_an_outbox_step_and_sends_once(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    w, ctx = await _ctx(db)
    fake_llm.on("guardrail", OK)
    first = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    again = await tool_executor.run(
        ctx, "vapi.place_call", _args(w, script="reworded after a crash")
    )
    assert first.status == again.status == "AWAITING_CALLBACK"
    assert len(call.sent) == 1 and first.step_id == again.step_id
    step = await db.get_one(AgentRunStep, first.step_id)
    assert (step.status, step.contact_point_id, step.idempotency_key) == (
        "AWAITING_CALLBACK",
        w.jane.id,
        call.sent[0],
    )


async def test_consent_refused_is_denied_without_sending(
    db: AsyncSession, clock: FrozenClock, call: FakeCall
) -> None:
    w, ctx = await _ctx(db)
    w.jane_link.consent = {"voice": {"status": "refused"}}
    await db.commit()
    result = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    assert (result.status, result.reason) == ("BLOCKED_BY_POLICY", "consent_required")
    assert call.sent == []
    step = await db.scalar(select(AgentRunStep).where(AgentRunStep.kind == "policy"))
    assert step is not None and step.status == "BLOCKED_BY_POLICY"


async def test_unknown_recipient_is_denied(
    db: AsyncSession, clock: FrozenClock, call: FakeCall
) -> None:
    w, ctx = await _ctx(db)
    result = await tool_executor.run(
        ctx, "vapi.place_call", _args(w, to_contact_id="00000000-0000-0000-0000-000000000000")
    )
    assert (result.status, result.reason) == ("BLOCKED_BY_POLICY", "recipient_must_be_contact")


async def test_quiet_hours_defer(db: AsyncSession, clock: FrozenClock, call: FakeCall) -> None:
    clock.set(datetime(2026, 10, 2, 2, 0, tzinfo=UTC))  # 22:00 in New York
    w, ctx = await _ctx(db)
    result = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    assert result.status == "DEFERRED" and result.resume_at == datetime(
        2026, 10, 2, 13, 0, tzinfo=UTC
    )
    assert call.sent == []


async def test_ssn_in_a_script_is_blocked_before_the_model(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    w, ctx = await _ctx(db)
    result = await tool_executor.run(
        ctx, "vapi.place_call", _args(w, script="Confirm SSN 123-45-6789")
    )
    assert result.status == "BLOCKED_BY_GUARDRAIL" and call.sent == []
    assert fake_llm.calls == []
    block = await db.scalar(select(StepResult))
    assert block is not None and (block.kind, block.urgency) == ("guardrail_block", "P1")


async def test_guardrail_model_block(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    w, ctx = await _ctx(db)
    fake_llm.on("guardrail", GuardrailVerdict(ok=False, reasons=["gives legal advice"]))
    result = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    assert result.status == "BLOCKED_BY_GUARDRAIL" and "legal advice" in (result.reason or "")


async def test_guardrail_outage_fails_closed(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    w, ctx = await _ctx(db)
    fake_llm.on("guardrail", LLMError("down", retryable=True))
    result = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    assert (result.status, result.retryable, result.reason) == ("FAILED", True, "guardrail_error")
    assert call.sent == []


async def test_kill_switch_between_check_and_send_stops_the_call(
    db: AsyncSession,
    clock: FrozenClock,
    fake_llm: FakeLLM,
    call: FakeCall,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w, ctx = await _ctx(db)

    async def flip(*_: Any, **__: Any) -> GuardrailVerdict:
        w.mapping.kill_switch = True
        await db.commit()
        return OK

    monkeypatch.setattr(tool_executor, "check", flip)
    result = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    assert (result.status, result.reason) == ("FAILED", "kill_switch") and call.sent == []


async def test_bad_arguments_are_a_schema_error(
    db: AsyncSession, clock: FrozenClock, call: FakeCall
) -> None:
    w, ctx = await _ctx(db)
    result = await tool_executor.run(ctx, "vapi.place_call", {"to_contact_id": str(w.jane_link.id)})
    assert (result.status, result.reason) == ("FAILED", "schema") and call.sent == []


async def test_connector_error_is_retryable_and_frees_the_key(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    w, ctx = await _ctx(db)
    fake_llm.on("guardrail", OK, OK)
    call.fail = True
    failed = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    assert (failed.status, failed.retryable) == ("FAILED", True)
    call.fail = False
    sent = await tool_executor.run(ctx, "vapi.place_call", _args(w, script="Second draft"))
    assert sent.status == "AWAITING_CALLBACK" and sent.step_id == failed.step_id
    step = await db.get_one(AgentRunStep, sent.step_id)
    assert step.input["script"] == "Second draft", "the step records what actually went out"


async def test_daily_cap_defers(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    from tests.world import VOICE_CONFIG

    capped = {
        **VOICE_CONFIG,
        "policy_pack": [
            *VOICE_CONFIG["policy_pack"],
            {"rule": "per_subject_contact_cap", "params": {"n": 1}},
        ],
    }
    w = await make_world(db, config=capped)
    _, ctx = await _ctx(db, w)
    fake_llm.on("guardrail", OK)
    assert (await tool_executor.run(ctx, "vapi.place_call", _args(w))).status == "AWAITING_CALLBACK"
    ctx.item = {**ctx.item, "attempts": 2}
    assert (await tool_executor.run(ctx, "vapi.place_call", _args(w))).status == "DEFERRED"


async def test_daily_cap_counts_from_firm_midnight_when_the_contact_has_no_tz(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, call: FakeCall
) -> None:
    from tests.world import VOICE_CONFIG

    cap = {"rule": "per_subject_contact_cap", "params": {"n": 1}}
    w = await make_world(
        db, config={**VOICE_CONFIG, "policy_pack": [*VOICE_CONFIG["policy_pack"], cap]}
    )
    w.jane.tz = None
    _, ctx = await _ctx(db, w)
    fake_llm.on("guardrail", OK, OK)
    first = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    step = await db.get_one(AgentRunStep, first.step_id)
    step.started_at = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)  # 22:00 the day before in New York
    await db.commit()
    ctx.item = {**ctx.item, "attempts": 2}
    assert (await tool_executor.run(ctx, "vapi.place_call", _args(w))).status == "AWAITING_CALLBACK"


async def test_a_cap_filled_by_a_concurrent_send_defers_without_losing_the_callers_work(
    db: AsyncSession,
    clock: FrozenClock,
    fake_llm: FakeLLM,
    call: FakeCall,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lucia.harness.exec.policy import Allow, Defer

    w, ctx = await _ctx(db)
    fake_llm.on("guardrail", OK)
    later = clock.now().replace(hour=23)
    decisions = iter([Allow(), Defer(rule="org_daily_cap", until=later)])

    async def decide(*_: Any) -> Any:
        return next(decisions)  # free before the lock, full under it

    monkeypatch.setattr(tool_executor, "_decide", decide)
    ctx.task.title = "unsaved change by the caller"
    result = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    assert (result.status, result.resume_at) == ("DEFERRED", later) and call.sent == []
    assert ctx.task.title == "unsaved change by the caller"


@pytest.mark.parametrize("status", ["ENDED", "PAUSED"])
async def test_the_last_check_before_a_send_sees_an_ended_or_paused_run(
    db: AsyncSession, clock: FrozenClock, status: str
) -> None:
    """The sweep ends or pauses a run without bumping the epoch, from another session."""
    _, ctx = await _ctx(db)
    sub = "subject_closed" if status == "PAUSED" else None
    await db.execute(
        update(AgentRun).where(AgentRun.id == ctx.view.run.id).values(status=status, substatus=sub)
    )
    assert await tool_executor._killed(db, ctx.view.run, ctx.epoch)  # pyright: ignore[reportPrivateUsage]
