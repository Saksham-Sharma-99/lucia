import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.connectors import vapi as vapi_api
from lucia.core.clock import FrozenClock
from lucia.core.config import get_settings
from lucia.db.models import AgentRun, AgentRunStep, ContactPoint, Episode, RunTask, StepResult
from lucia.harness.agent_view import load
from lucia.harness.exec import tool_executor
from lucia.harness.exec.guardrail import GuardrailVerdict
from lucia.harness.executor import resume_task
from lucia.harness.tools.base import ToolContext
from lucia.harness.tools.vapi_tool import RAILS, ingest_report, poll_stale
from lucia.llm.fake import FakeLLM
from tests.world import World, item, make_leased_run, make_task, make_world

CALLS = f"{vapi_api.API}/call"


async def _ctx(db: AsyncSession) -> tuple[World, AgentRun, RunTask, ToolContext]:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run, plan=[item(1, "tool", status="RUNNING", attempts=1)])
    return w, run, task, ToolContext(db, await load(db, run), task, task.plan[0], 1)


def _args(w: World) -> dict[str, Any]:
    return {
        "to_contact_id": str(w.jane_link.id),
        "script": "Ask how she is.",
        "first_message": "Hi Jane",
        "max_seconds": 300,
    }


async def _place(
    db: AsyncSession, fake_llm: FakeLLM
) -> tuple[World, AgentRun, RunTask, AgentRunStep, respx.Route]:
    w, run, task, ctx = await _ctx(db)
    fake_llm.on("guardrail", GuardrailVerdict(ok=True, reasons=[]))
    route = respx.post(CALLS).mock(return_value=Response(201, json={"id": "call-1"}))
    result = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    assert result.status == "AWAITING_CALLBACK" and result.step_id
    return w, run, task, await db.get_one(AgentRunStep, result.step_id), route


@respx.mock
async def test_place_call_sends_metadata_and_rails(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w, run, task, step, route = await _place(db, fake_llm)
    body = json.loads(route.calls[0].request.content)
    assert body["customer"] == {"number": "+15555550100"} and body["phoneNumberId"] == "pn_1"
    meta = body["assistant"]["metadata"]
    assert meta == {
        "firm_id": str(w.firm.id),
        "connection_id": str(w.vapi.id),
        "run_id": str(run.id),
        "task_id": str(task.id),
        "plan_item_id": "i1",
        "step_id": str(step.id),
        "idem_key": step.idempotency_key,
    }
    assert RAILS in body["assistant"]["model"]["messages"][0]["content"]
    assert body["assistant"]["maxDurationSeconds"] == 300
    assert step.external_ref == "call-1"


@respx.mock
async def test_contact_without_a_phone_fails_without_calling(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w, _, _, ctx = await _ctx(db)
    jane = await db.get_one(ContactPoint, w.jane.id)
    jane.phones = []
    await db.commit()
    route = respx.post(CALLS)
    result = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    assert (result.status, result.reason, result.retryable) == ("FAILED", "no_address", False)
    assert not route.called and fake_llm.calls == [], "no guardrail call for an unreachable contact"
    assert await db.scalar(select(AgentRunStep.id).where(AgentRunStep.kind == "tool")) is None


@pytest.mark.parametrize(
    "outcome", [Response(502), Response(504), httpx.ReadTimeout("no response")]
)
@respx.mock
async def test_a_call_that_may_have_been_placed_asks_instead_of_retrying(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, outcome: Any
) -> None:
    w, _, _, ctx = await _ctx(db)
    fake_llm.on("guardrail", GuardrailVerdict(ok=True, reasons=[]))
    respx.post(CALLS).mock(side_effect=[outcome])
    result = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    assert (result.status, result.retryable) == ("NEEDS_HUMAN", False)
    step = await db.get_one(AgentRunStep, result.step_id)
    assert step.status == "FAILED" and (step.error or {})["class"] == "uncertain"
    assert await db.scalar(select(StepResult.kind)) == "uncertain_send"


@respx.mock
async def test_maybe_sent_again_after_not_sent_asks_again(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w, _, _, ctx = await _ctx(db)
    fake_llm.on(
        "guardrail", GuardrailVerdict(ok=True, reasons=[]), GuardrailVerdict(ok=True, reasons=[])
    )
    respx.post(CALLS).mock(side_effect=[Response(502), Response(502)])
    first = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    step = await db.get_one(AgentRunStep, first.step_id)
    step.status, step.error = "FAILED", {"class": "not_sent"}  # a person: "it was not sent"
    await db.commit()
    ctx.epoch = 2  # the answer runs in a later unit
    await db.execute(update(AgentRun).where(AgentRun.id == ctx.view.run.id).values(lease_epoch=2))
    await tool_executor.run(ctx, "vapi.place_call", _args(w))
    asks = list(await db.scalars(select(StepResult).where(StepResult.kind == "uncertain_send")))
    assert len(asks) == 2, "the second unsure send gets its own question"


@respx.mock
async def test_a_refused_connection_never_reached_vapi_and_is_retried(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w, _, _, ctx = await _ctx(db)
    fake_llm.on("guardrail", GuardrailVerdict(ok=True, reasons=[]))
    respx.post(CALLS).mock(side_effect=httpx.ConnectError("refused"))
    result = await tool_executor.run(ctx, "vapi.place_call", _args(w))
    assert (result.status, result.retryable) == ("FAILED", True)


def _report(step: AgentRunStep, **kw: Any) -> dict[str, Any]:
    return {
        "type": "end-of-call-report",
        "endedReason": kw.get("ended", "customer-ended-call"),
        "summary": "Jane is doing well, started PT.",
        "transcript": "AI: Hi Jane...",
        "call": {
            "id": "call-1",
            "phoneNumberId": "pn_1",
            "assistant": {"metadata": {"idem_key": step.idempotency_key}},
        },
    }


@respx.mock
async def test_report_resumes_the_task(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, sent: list[Any]
) -> None:
    _, run, task, step, _ = await _place(db, fake_llm)
    episode_id = await ingest_report(db, _report(step), source="webhook")
    assert (
        episode_id is not None and await ingest_report(db, _report(step), source="webhook") is None
    )
    ep = await db.get_one(Episode, episode_id)
    assert (ep.trigger_type, ep.task_id, ep.dedup_key) == (
        "external_response",
        task.id,
        "vapi:call-1",
    )
    assert ep.metadata_["reached"] is True and ep.metadata_["plan_item_id"] == "i1"
    assert ("harness.advance_run", (str(run.id),)) in sent
    ep.status, ep.lease_epoch = "running", 1
    task.plan = [{**task.plan[0], "status": "WAITING"}]
    await db.commit()
    await resume_task(db, run, task, ep, 1)
    await db.refresh(step)
    await db.refresh(task)
    assert (
        step.status == "SUCCEEDED" and step.output["summary"] == "Jane is doing well, started PT."
    )
    assert task.status == "DONE"


@respx.mock
async def test_a_report_without_a_call_id_is_keyed_by_its_step(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, _, _, step, _ = await _place(db, fake_llm)
    step.external_ref = None
    await db.commit()
    report = _report(step)
    report["call"]["id"] = None
    episode_id = await ingest_report(db, report, source="webhook")
    ep = await db.get_one(Episode, episode_id)
    assert ep.dedup_key == f"vapi:{step.id}", "never vapi:None, shared by every such call"


@pytest.mark.parametrize("ended", ["customer-did-not-answer", "voicemail", "customer-busy"])
@respx.mock
async def test_unanswered_calls_are_not_reached(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, ended: str
) -> None:
    _, _, _, step, _ = await _place(db, fake_llm)
    episode_id = await ingest_report(db, _report(step, ended=ended), source="webhook")
    assert episode_id is not None
    assert (await db.get_one(Episode, episode_id)).metadata_["reached"] is False


async def test_report_for_an_unknown_call_is_ignored(db: AsyncSession, clock: FrozenClock) -> None:
    report = {
        "type": "end-of-call-report",
        "call": {"id": "call-x", "assistant": {"metadata": {"idem_key": "nope"}}},
    }
    assert await ingest_report(db, report, source="webhook") is None


@respx.mock
async def test_webhook_ingests_with_the_secret(
    client: AsyncClient, db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, _, _, step, _ = await _place(db, fake_llm)
    headers = {"x-vapi-secret": get_settings().vapi_webhook_secret}
    resp = await client.post("/api/v1/hooks/vapi", json={"message": _report(step)}, headers=headers)
    assert resp.status_code == 200
    assert (
        await db.scalar(
            select(Episode.dedup_key).where(Episode.trigger_type == "external_response")
        )
        == "vapi:call-1"
    )
    bad = await client.post(
        "/api/v1/hooks/vapi", json={"message": _report(step)}, headers={"x-vapi-secret": "no"}
    )
    assert bad.status_code == 401


@respx.mock
async def test_poll_ingests_ended_calls_and_times_out_missing_ones(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, _, _, step, _ = await _place(db, fake_llm)
    clock.advance(timedelta(minutes=31))
    respx.get(f"{CALLS}/call-1").mock(
        return_value=Response(
            200,
            json={
                "id": "call-1",
                "status": "ended",
                "endedReason": "voicemail",
                "summary": "Left a voicemail",
                "assistant": {"metadata": {"idem_key": step.idempotency_key}},
            },
        )
    )
    assert await poll_stale(db) == 1
    ep = await db.scalar(select(Episode).where(Episode.dedup_key == "vapi:call-1"))
    assert ep is not None and ep.metadata_["source"] == "poll" and ep.metadata_["reached"] is False


@respx.mock
async def test_poll_synthesizes_a_timeout_when_vapi_lost_the_call(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, _, _, _, _ = await _place(db, fake_llm)
    clock.advance(timedelta(minutes=31))
    respx.get(f"{CALLS}/call-1").mock(return_value=Response(404, json={"message": "not found"}))
    assert await poll_stale(db) == 1
    ep = await db.scalar(select(Episode).where(Episode.dedup_key == "vapi:call-1"))
    assert ep is not None and ep.metadata_["ended_reason"] == "vapi_timeout"
    assert await db.scalar(select(StepResult.kind)) == "escalation"


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (Response(200, json=[{"id": "c", "assistant": {"metadata": {"idem_key": "K"}}}]), "found"),
        (
            Response(200, json=[{"id": "c", "assistant": {"metadata": {"idem_key": "other"}}}]),
            "absent",
        ),
        (Response(500, json={"message": "down"}), "unknown"),
    ],
)
@respx.mock
async def test_sent_lookup(
    db: AsyncSession, clock: FrozenClock, response: Response, expected: str
) -> None:
    from lucia.harness.tools.vapi_tool import VAPI

    w = await make_world(db)
    run = await make_leased_run(db, w)
    step = AgentRunStep(
        firm_id=w.firm.id,
        run_id=run.id,
        seq=1,
        kind="tool",
        tool="vapi.place_call",
        status="PENDING",
        idempotency_key="K",
        lease_epoch=1,
        actor="agent",
        input={"to_contact_id": str(w.jane_link.id)},
        started_at=clock.now(),
    )
    db.add(step)
    await db.commit()
    respx.get(CALLS).mock(return_value=response)
    assert await VAPI.sent_lookup(db, step) == expected
