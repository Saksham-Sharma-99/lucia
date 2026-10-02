from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AgentRun, Episode, JournalSummary, RunStepLog, StepResult, Subject
from lucia.harness.journal import append
from lucia.harness.steps import add_step
from tests.factories import ZERO
from tests.world import World, item, make_run, make_task, make_world


async def _run(db: AsyncSession, **kw: Any) -> tuple[World, AgentRun]:
    w = await make_world(db)
    run = await make_run(db, w, status="ACTIVE", goal="Check in with Jane", **kw)
    return w, run


async def test_list_filters_and_detail(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    w, run = await _run(db)
    await make_task(db, w, run, status="DONE")
    await make_task(db, w, run, key="b:run", status="TODO")
    base = f"/api/v1/firms/{w.firm.id}/runs"
    page = (await authed.get(base)).json()
    assert page["total"] == 1 and page["items"][0]["agent_handle"] == "checkin"
    assert (page["items"][0]["tasks_done"], page["items"][0]["tasks_total"]) == (1, 2)
    assert (await authed.get(base, params={"status": "COMPLETED"})).json()["total"] == 0
    assert (await authed.get(base, params={"q": "acme"})).json()["total"] == 1
    assert (await authed.get(base, params={"q": "nothing"})).json()["total"] == 0
    detail = (await authed.get(f"/api/v1/runs/{run.id}")).json()
    assert (detail["goal"], detail["subject_title"], detail["version"]) == (
        "Check in with Jane",
        "Doe v. Acme Trucking",
        1,
    )


async def test_listing_runs_costs_the_same_queries_for_one_run_or_many(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    w, _ = await _run(db)
    base = f"/api/v1/firms/{w.firm.id}/runs"
    with _counting(db) as one:
        await authed.get(base)
    for n in range(3):
        sub = Subject(firm_id=w.firm.id, kind="matter", title=f"Case {n}")
        db.add(sub)
        await db.flush()
        await make_run(db, w, subject_id=sub.id)
    with _counting(db) as many:
        page = (await authed.get(base)).json()
    assert page["total"] == 4 and len(many) == len(one)


@contextmanager
def _counting(db: AsyncSession) -> Iterator[list[str]]:
    seen: list[str] = []

    def count(*args: Any) -> None:
        seen.append(args[2])

    conn = db.bind.sync_connection  # type: ignore[union-attr]
    event.listen(conn, "before_cursor_execute", count)
    try:
        yield seen
    finally:
        event.remove(conn, "before_cursor_execute", count)


async def test_unknown_run_is_404(authed: AsyncClient) -> None:
    assert (await authed.get(f"/api/v1/runs/{ZERO}")).status_code == 404


async def test_tasks_steps_logs_episodes_journal_attention(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    w, run = await _run(db)
    task = await make_task(db, w, run, plan=[item(1, "subagent")])
    parent = await add_step(
        db,
        run,
        kind="subagent",
        tool="harness.subagent",
        status="SUCCEEDED",
        idempotency_key="p",
        epoch=1,
        task_id=task.id,
        plan_item_id="i1",
    )
    await add_step(
        db,
        run,
        kind="llm",
        role="sub_planner",
        status="SUCCEEDED",
        idempotency_key="c",
        epoch=1,
        task_id=task.id,
        plan_item_id="i1",
        parent_step_id=parent.id,
    )
    db.add(
        RunStepLog(
            firm_id=w.firm.id,
            run_id=run.id,
            task_id=task.id,
            level="debug",
            stage="Plan",
            message="LLM planner via x",
            at=clock.now(),
        )
    )
    db.add(
        RunStepLog(
            firm_id=w.firm.id,
            run_id=run.id,
            level="info",
            stage="Call",
            message="Calling",
            at=clock.now(),
        )
    )
    db.add(
        Episode(
            firm_id=w.firm.id,
            run_id=run.id,
            trigger_type="user_input",
            status="completed",
            dedup_key="msg:r",
        )
    )
    await append(db, run, text="note", source="agent", key="n")
    await db.flush()
    db.add(
        StepResult(
            firm_id=w.firm.id,
            run_id=run.id,
            type="attention",
            kind="question",
            urgency="P1",
            summary="q?",
            summary_public="q",
            status="open",
            dedup_key="sr:r",
        )
    )
    await db.commit()
    entry_id = (await authed.get(f"/api/v1/runs/{run.id}/journal")).json()["entries"][0]["id"]
    db.add(
        JournalSummary(firm_id=w.firm.id, run_id=run.id, through_entry_id=entry_id, text="So far")
    )
    await db.commit()
    base = f"/api/v1/runs/{run.id}"
    tasks = (await authed.get(f"{base}/tasks")).json()
    assert tasks[0]["plan"][0]["id"] == "i1"
    steps = (
        await authed.get(f"{base}/steps", params={"task_id": str(task.id), "plan_item_id": "i1"})
    ).json()
    assert [(s["kind"], s["parent_step_id"]) for s in steps] == [
        ("subagent", None),
        ("llm", str(parent.id)),
    ]
    logs = (await authed.get(f"{base}/logs", params={"level": "debug"})).json()
    assert [entry["stage"] for entry in logs] == ["Plan"]
    assert len((await authed.get(f"{base}/logs", params={"q": "calling"})).json()) == 1
    assert [e["dedup_key"] for e in (await authed.get(f"{base}/episodes")).json()] == ["msg:r"]
    journal = (await authed.get(f"{base}/journal")).json()
    assert journal["summary"] == "So far" and journal["entries"][0]["text"] == "note"
    assert [a["summary"] for a in (await authed.get(f"{base}/attention")).json()] == ["q?"]


async def test_takeover_and_handback(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    _, run = await _run(db)
    resp = await authed.post(
        f"/api/v1/runs/{run.id}/takeover", json={"remarks": "Calling her myself"}
    )
    assert resp.status_code == 200 and resp.json()["status"] == "TAKEN_OVER"
    assert (
        await authed.post(f"/api/v1/runs/{run.id}/takeover", json={"remarks": "Calling her myself"})
    ).status_code == 409
    resp = await authed.post(
        f"/api/v1/runs/{run.id}/handback", json={"remarks": "Done talking to her"}
    )
    assert resp.status_code == 200 and resp.json()["status"] == "ACTIVE"


@pytest.mark.parametrize("remarks", ["", "too short"])
async def test_remarks_are_required(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock, remarks: str
) -> None:
    _, run = await _run(db)
    resp = await authed.post(f"/api/v1/runs/{run.id}/takeover", json={"remarks": remarks})
    assert resp.status_code == 422
