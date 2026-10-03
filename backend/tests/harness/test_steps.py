from decimal import Decimal

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AgentRunStep, RunStepLog
from lucia.harness.steps import add_step, call_llm, log
from lucia.llm.client import LLMError
from lucia.llm.fake import FakeLLM
from tests.world import make_leased_run, make_world


class Out(BaseModel):
    ok: bool


async def test_llm_calls_are_recorded_with_usage_and_logged(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    run = await make_leased_run(db, await make_world(db))
    fake_llm.on("planner", Out(ok=True))
    out = await call_llm(
        db,
        run,
        role="planner",
        model="gpt-5.6-sol",
        instructions="i",
        message="m",
        output_type=Out,
        epoch=1,
    )
    assert out == Out(ok=True)
    step = await db.scalar(select(AgentRunStep))
    assert step is not None
    assert (step.kind, step.role, step.model, step.status, step.seq) == (
        "llm",
        "planner",
        "gpt-5.6-sol",
        "SUCCEEDED",
        1,
    )
    assert (step.input_tokens, step.output_tokens, step.cost) == (10, 5, Decimal("0.0001"))
    assert step.output == {"ok": True}
    line = await db.scalar(select(RunStepLog.message))
    assert line == "LLM planner via gpt-5.6-sol (5 ms)"
    await db.refresh(run)
    assert run.step_count == 1


async def test_failed_llm_calls_are_recorded_then_reraised(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    run = await make_leased_run(db, await make_world(db))
    fake_llm.on("triage", LLMError("timeout", retryable=True))
    with pytest.raises(LLMError):
        await call_llm(
            db,
            run,
            role="triage",
            model="m",
            instructions="i",
            message="x",
            output_type=Out,
            epoch=1,
        )
    step = await db.scalar(select(AgentRunStep))
    assert step is not None and (step.status, step.error) == (
        "FAILED",
        {"class": "retryable", "reason": "llm_error", "detail": "timeout"},
    )


async def test_a_failed_call_commits_nothing_of_the_callers_work(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    run = await make_leased_run(db, await make_world(db))
    run.goal = "half-made decision"
    fake_llm.on("triage", LLMError("timeout", retryable=True))
    with pytest.raises(LLMError):
        await call_llm(
            db,
            run,
            role="triage",
            model="m",
            instructions="i",
            message="x",
            output_type=Out,
            epoch=1,
        )
    await db.rollback()  # what the worker does with a failed unit
    await db.refresh(run)
    assert run.goal != "half-made decision"


async def test_text_and_tool_calls_share_the_recorder(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    run = await make_leased_run(db, await make_world(db))
    fake_llm.on("summarizer", "short summary")
    fake_llm.on("executor", {"to_contact_id": "x"})
    assert (
        await call_llm(
            db, run, role="summarizer", model="m", instructions="i", message="x", epoch=1
        )
        == "short summary"
    )
    args = await call_llm(
        db,
        run,
        role="executor",
        model="m",
        instructions="i",
        message="x",
        epoch=1,
        tool=("vapi.place_call", {"type": "object"}),
    )
    assert args == {"to_contact_id": "x"}
    seqs = list(await db.scalars(select(AgentRunStep.seq).order_by(AgentRunStep.seq)))
    assert seqs == [1, 2]


async def test_logs_are_redacted(db: AsyncSession, clock: FrozenClock) -> None:
    run = await make_leased_run(db, await make_world(db))
    await log(db, run, stage="Call", message="Jane's SSN is 123-45-6789")
    await db.commit()
    assert await db.scalar(select(RunStepLog.message)) == "Jane's SSN is [SSN]"


async def test_add_step_numbers_steps_per_run(db: AsyncSession, clock: FrozenClock) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    a = await add_step(
        db, run, kind="system", tool="harness.x", status="SUCCEEDED", idempotency_key="a", epoch=1
    )
    b = await add_step(
        db, run, kind="system", tool="harness.x", status="SUCCEEDED", idempotency_key="b", epoch=1
    )
    assert (a.seq, b.seq) == (1, 2)
