from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AgentRun, Episode, StepResult
from tests.factories import ZERO
from tests.world import World, make_leased_run, make_task, make_world


async def _item(db: AsyncSession, kind: str, **kw: Any) -> tuple[World, AgentRun, StepResult]:
    w = await make_world(db)
    run = await make_leased_run(db, w, status=kw.pop("run_status", "ACTIVE"))
    task = await make_task(db, w, run)
    sr = StepResult(
        firm_id=w.firm.id,
        run_id=run.id,
        task_id=task.id,
        type="attention",
        kind=kind,
        urgency="P1",
        summary="Which number?",
        summary_public="Input needed",
        blocking=kind != "out_of_scope",
        status="open",
        dedup_key=f"sr:{kind}",
        **kw,
    )
    db.add(sr)
    await db.commit()
    return w, run, sr


async def _answer(client: AsyncClient, sr: StepResult, **body: Any) -> Any:
    return await client.post(f"/api/v1/attention/{sr.id}/answer", json=body)


async def test_answering_a_question_queues_one_episode(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock, sent: list[Any]
) -> None:
    _, run, sr = await _item(db, "question")
    resp = await _answer(authed, sr, text="Her mobile")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "answered" and resp.json()["answer"] == {
        "choice": None,
        "text": "Her mobile",
    }
    ep = await db.scalar(select(Episode))
    assert ep is not None and (ep.trigger_type, ep.dedup_key, ep.task_id) == (
        "user_response",
        f"answer:{sr.id}",
        sr.task_id,
    )
    assert ("harness.advance_run", (str(run.id),)) in sent


async def test_the_first_answer_wins(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    _, _, sr = await _item(db, "question")
    assert (await _answer(authed, sr, text="a")).status_code == 200
    assert (await _answer(authed, sr, text="b")).status_code == 409


async def test_non_blocking_items_are_acknowledged_without_an_episode(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    _, _, sr = await _item(db, "out_of_scope")
    assert (await _answer(authed, sr, choice="dismiss")).status_code == 200
    assert await db.scalar(select(Episode)) is None


async def test_choice_must_be_one_of_the_options(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    _, _, sr = await _item(
        db,
        "item_failed",
        options=[{"value": "retry", "label": "Retry"}, {"value": "skip", "label": "Skip"}],
    )
    resp = await _answer(authed, sr, choice="explode")
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/choice"


async def test_an_empty_answer_is_rejected(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    _, _, sr = await _item(db, "question")
    assert (await _answer(authed, sr)).status_code == 422


async def test_confirming_completes_the_run(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    _, run, sr = await _item(
        db,
        "confirm_completion",
        run_status="AWAITING_CONFIRMATION",
        options=[{"value": "confirm", "label": "Confirm"}, {"value": "reopen", "label": "Reopen"}],
    )
    assert (await _answer(authed, sr, choice="confirm")).status_code == 200
    await db.refresh(run)
    assert run.status == "COMPLETED"


async def test_reopen_needs_text(authed: AsyncClient, db: AsyncSession, clock: FrozenClock) -> None:
    _, _, sr = await _item(
        db,
        "confirm_completion",
        run_status="AWAITING_CONFIRMATION",
        options=[{"value": "confirm", "label": "Confirm"}, {"value": "reopen", "label": "Reopen"}],
    )
    resp = await _answer(authed, sr, choice="reopen")
    assert resp.status_code == 422 and resp.json()["errors"][0]["path"] == "/text"


async def test_unknown_item_is_404(authed: AsyncClient) -> None:
    resp = await authed.post(f"/api/v1/attention/{ZERO}/answer", json={"text": "x"})
    assert resp.status_code == 404


@pytest.mark.parametrize("field", [{"text": "x" * 2001}])
async def test_answer_length_is_bounded(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock, field: dict[str, str]
) -> None:
    _, _, sr = await _item(db, "question")
    assert (await _answer(authed, sr, **field)).status_code == 422
