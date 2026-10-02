from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AgentRun, Episode, RunTask, StepResult
from lucia.harness import executor, worker
from lucia.llm.client import LLMError
from lucia.scheduling import scheduler
from tests.world import World, item, make_run, make_task, make_world


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    seen: list[tuple[str, Any]] = []

    async def triage(session: AsyncSession, run: AgentRun, ep: Episode, epoch: int) -> None:
        seen.append(("triage", ep.dedup_key))

    async def resume(
        session: AsyncSession, run: AgentRun, task: RunTask, ep: Episode, epoch: int
    ) -> None:
        seen.append(("resume", (task.key, ep.dedup_key)))

    async def execute(session: AsyncSession, run: AgentRun, task: RunTask, epoch: int) -> None:
        seen.append(("execute", task.key))
        task.status = "DONE"
        await session.commit()

    monkeypatch.setattr(worker, "run_triage", triage)
    monkeypatch.setattr(worker, "resume_task", resume)

    async def check(session: AsyncSession, run: AgentRun, epoch: int, cause: str) -> None:
        seen.append(("check", cause))

    monkeypatch.setattr(worker, "execute_task", execute)
    monkeypatch.setattr(worker, "check_run", check)
    return seen


def _ep(w: World, run: AgentRun, key: str, **kw: Any) -> Episode:
    fields: dict[str, Any] = {"trigger_type": "user_input", "status": "pending", **kw}
    return Episode(firm_id=w.firm.id, run_id=run.id, dedup_key=key, **fields)


def _task(w: World, run: AgentRun, key: str, **kw: Any) -> RunTask:
    return RunTask(
        firm_id=w.firm.id,
        run_id=run.id,
        key=key,
        kind="call",
        target={"type": "run", "ref": None},
        title=key,
        goal="g",
        created_by="triage",
        **kw,
    )


async def test_order_handback_then_run_wide_then_task_then_runnable(
    db: AsyncSession, clock: FrozenClock, calls: list[tuple[str, Any]], sent: list[Any]
) -> None:
    w = await make_world(db)
    run = await make_run(db, w)
    task = _task(w, run, "call:run")
    task.created_at = clock.now()
    db.add(task)
    await db.flush()
    db.add_all(
        [
            _ep(w, run, "msg:task", task_id=task.id),
            _ep(w, run, "msg:wide"),
            _ep(w, run, "handback:1", trigger_type="handback"),
        ]
    )
    later = _task(w, run, "other:run")
    later.created_at = clock.now() + timedelta(seconds=1)  # same-transaction rows tie on now()
    db.add(later)
    await db.commit()
    for _ in range(6):  # the last unit is the completion check, queued as an Episode
        await worker.advance_run(db, run.id, owner="t")
    assert calls == [
        ("triage", "handback:1"),
        ("triage", "msg:wide"),
        ("resume", ("call:run", "msg:task")),
        ("execute", "call:run"),
        ("execute", "other:run"),
        ("check", calls[-1][1]),  # keyed by the state it checked
    ]
    statuses = set(await db.scalars(select(Episode.status)))
    assert statuses == {"completed"}
    assert sent[-1] == ("harness.advance_run", (str(run.id),))


async def test_dependent_task_waits_for_its_dependency(
    db: AsyncSession, clock: FrozenClock, calls: list[tuple[str, Any]]
) -> None:
    w = await make_world(db)
    run = await make_run(db, w)
    db.add_all([_task(w, run, "b:run", depends_on=["a:run"]), _task(w, run, "a:run")])
    await db.commit()
    for _ in range(3):  # a, then b, then the completion check
        await worker.advance_run(db, run.id, owner="t")
    assert [c for c, _ in calls] == ["execute", "execute", "check"]


async def test_crashed_episode_is_resumed_first(
    db: AsyncSession, clock: FrozenClock, calls: list[tuple[str, Any]]
) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="ACTIVE", lease_epoch=3)
    db.add_all([_ep(w, run, "msg:new"), _ep(w, run, "msg:old", status="running", lease_epoch=3)])
    await db.commit()
    await worker.advance_run(db, run.id, owner="t")
    assert calls == [("triage", "msg:old")]


async def test_poison_episode_fails_after_three_resumes(
    db: AsyncSession, clock: FrozenClock, calls: list[tuple[str, Any]]
) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="ACTIVE", lease_epoch=1)
    ep = _ep(w, run, "msg:p", status="running", lease_epoch=1, metadata_={"resume_count": 3})
    db.add(ep)
    await db.commit()
    await worker.advance_run(db, run.id, owner="t")
    await db.refresh(ep)
    assert (ep.status, ep.outcome) == ("failed", "poison")
    assert calls == []
    assert await db.scalar(select(StepResult.kind)) == "escalation"


async def test_no_work_marks_the_run_waiting(
    db: AsyncSession, clock: FrozenClock, calls: list[Any]
) -> None:
    w = await make_world(db)
    run = await make_run(db, w)
    assert await worker.advance_run(db, run.id, owner="t") == "no_work"
    await db.refresh(run)
    assert (run.status, run.substatus, run.lease_expires_at) == ("ACTIVE", "WAITING", None)


async def test_not_claimed_when_another_worker_holds_it(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="ACTIVE", lease_expires_at=clock.now().replace(year=2030))
    assert await worker.advance_run(db, run.id, owner="t") == "not_claimed"


async def test_retryable_llm_failure_backs_off_then_pauses(
    db: AsyncSession, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(*_: Any) -> None:
        raise LLMError("timeout", retryable=True)

    monkeypatch.setattr(worker, "run_triage", down)
    w = await make_world(db)
    run = await make_run(db, w)
    ep = _ep(w, run, "msg:1")
    db.add(ep)
    await db.commit()
    await worker.advance_run(db, run.id, owner="t")
    await db.refresh(ep)
    assert (ep.status, ep.metadata_["retry_count"]) == ("scheduled", 1)
    assert ep.metadata_["last_error"] == "LLMError('timeout')"  # repr: never empty
    assert ep.due_at is not None and (ep.due_at - clock.now()).total_seconds() == 60
    for _ in range(2):
        ep.status = "pending"
        await db.commit()
        await worker.advance_run(db, run.id, owner="t")
        await db.refresh(ep)
    await db.refresh(run)
    assert (ep.status, run.status, run.substatus) == ("failed", "PAUSED", "repeated_failure")
    assert await db.scalar(select(StepResult.kind)) == "escalation"


async def test_non_retryable_llm_failure_fails_the_episode(
    db: AsyncSession, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bad(*_: Any) -> None:
        raise LLMError("bad request", retryable=False)

    monkeypatch.setattr(worker, "run_triage", bad)
    w = await make_world(db)
    run = await make_run(db, w)
    ep = _ep(w, run, "msg:1")
    db.add(ep)
    await db.commit()
    await worker.advance_run(db, run.id, owner="t")
    await db.refresh(ep)
    await db.refresh(run)
    assert (ep.status, ep.outcome, run.status) == ("failed", "failed", "ACTIVE")
    assert await db.scalar(select(StepResult.kind)) == "escalation"


async def test_an_idle_run_awaiting_confirmation_keeps_its_status(
    db: AsyncSession, clock: FrozenClock, calls: list[Any]
) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="AWAITING_CONFIRMATION")
    assert await worker.advance_run(db, run.id, owner="t") == "no_work"
    await db.refresh(run)
    assert (run.status, run.substatus) == ("AWAITING_CONFIRMATION", None)


async def test_a_run_with_nothing_runnable_is_not_enqueued_again(
    db: AsyncSession, clock: FrozenClock, sent: list[Any]
) -> None:
    w = await make_world(db)
    run = await make_run(db, w)
    await make_task(db, w, run, depends_on=["never:run"])
    assert await worker.advance_run(db, run.id, owner="t") == "no_work"
    assert sent == []


async def test_completion_is_rechecked_only_when_something_could_change_it(
    db: AsyncSession, clock: FrozenClock, calls: list[tuple[str, Any]]
) -> None:
    w = await make_world(db)
    run = await make_run(db, w)
    done = _task(w, run, "call:run", status="DONE")
    db.add(done)
    await db.commit()
    for _ in range(2):  # an all-done run is owed one check
        await worker.advance_run(db, run.id, owner="t")
    assert [c for c, _ in calls] == ["check"]
    db.add(_ep(w, run, "late:report", task_id=done.id))  # a stray report on a finished task
    await db.commit()
    for _ in range(2):
        await worker.advance_run(db, run.id, owner="t")
    assert [c for c, _ in calls] == ["check", "resume"], "nothing changed: no second check"
    db.add(_ep(w, run, "msg:2"))  # a person's note: triage may change the answer
    await db.commit()
    for _ in range(2):
        await worker.advance_run(db, run.id, owner="t")
    assert [c for c, _ in calls] == ["check", "resume", "triage", "check"]


async def test_a_model_failure_on_the_task_path_backs_off_then_pauses(
    db: AsyncSession, clock: FrozenClock, sent: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def down(*_: Any) -> None:
        calls.append("llm")
        raise LLMError("timeout", retryable=True)

    monkeypatch.setattr(worker, "execute_task", down)
    monkeypatch.setattr(executor, "execute_task", down)  # what a fired retry runs
    w = await make_world(db)
    run = await make_run(db, w)
    task_id, run_id = (await make_task(db, w, run)).id, run.id
    for _ in range(3):  # re-enqueues and reaper wakes before the retry is due
        await worker.advance_run(db, run_id, owner="t")
    assert calls == ["llm"], "the task waits for its retry instead of looping"
    (retry,) = await db.scalars(select(Episode).where(Episode.source == "retry"))
    assert (retry.status, retry.task_id, retry.metadata_["retry_count"]) == (
        "scheduled",
        task_id,
        1,
    )
    assert retry.due_at == clock.now() + timedelta(seconds=60)
    for _ in range(2):  # the retry fires and fails again, twice
        retry.status = "pending"
        await db.commit()
        await worker.advance_run(db, run_id, owner="t")
        await db.refresh(retry)
    run = await db.get_one(AgentRun, run_id, populate_existing=True)
    assert (run.status, run.substatus, len(calls)) == ("PAUSED", "repeated_failure", 3)


async def test_a_non_retryable_failure_on_the_task_path_blocks_the_task_once(
    db: AsyncSession, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bad(*_: Any) -> None:
        raise LLMError("bad request", retryable=False)

    monkeypatch.setattr(worker, "execute_task", bad)
    w = await make_world(db)
    run = await make_run(db, w)
    task_id, run_id = (await make_task(db, w, run)).id, run.id
    for _ in range(3):
        await worker.advance_run(db, run_id, owner="t")
    task = await db.get_one(RunTask, task_id, populate_existing=True)
    asks = list(await db.scalars(select(StepResult).where(StepResult.kind == "item_failed")))
    assert task.status == "BLOCKED" and len(asks) == 1


async def test_a_failed_completion_check_is_retried(
    db: AsyncSession, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    checks: list[str] = []

    async def check(session: AsyncSession, r: AgentRun, epoch: int, cause: str) -> str:
        checks.append(cause)
        if len(checks) == 1:
            raise LLMError("timeout", retryable=True)
        return "asked"

    async def execute(session: AsyncSession, r: AgentRun, t: RunTask, epoch: int) -> None:
        t.status = "DONE"
        await session.commit()

    monkeypatch.setattr(worker, "check_run", check)
    monkeypatch.setattr(worker, "execute_task", execute)
    w = await make_world(db)
    run = await make_run(db, w)
    await make_task(db, w, run)
    run_id = run.id
    assert await worker.advance_run(db, run_id, owner="t") == "executed"
    assert await worker.advance_run(db, run_id, owner="t") == "retry_scheduled"
    (check_ep,) = await db.scalars(
        select(Episode).where(Episode.metadata_["unit"].astext == "completion")
    )
    assert check_ep.status == "scheduled"
    check_ep.status = "pending"
    await db.commit()
    assert await worker.advance_run(db, run_id, owner="t") == "asked"  # the check's outcome
    assert len(checks) == 2 and checks[0] == checks[1], "the retry checks the same state"


async def test_a_worker_killed_during_the_completion_check_has_it_redone(
    db: AsyncSession, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    checks: list[str] = []

    async def check(session: AsyncSession, r: AgentRun, epoch: int, cause: str) -> str:
        checks.append(cause)
        if len(checks) == 1:
            raise SystemExit("deploy restart")
        return "asked"

    async def execute(session: AsyncSession, r: AgentRun, t: RunTask, epoch: int) -> None:
        t.status = "DONE"
        await session.commit()

    monkeypatch.setattr(worker, "check_run", check)
    monkeypatch.setattr(worker, "execute_task", execute)
    w = await make_world(db)
    run = await make_run(db, w)
    run_id = run.id
    await make_task(db, w, run)
    await worker.advance_run(db, run_id, owner="a")
    with pytest.raises(SystemExit):
        await worker.advance_run(db, run_id, owner="a")
    await db.rollback()
    clock.advance(timedelta(minutes=10))  # worker a's lease runs out
    assert run_id in await scheduler.reap(db)
    assert await worker.advance_run(db, run_id, owner="b") == "asked"
    assert len(checks) == 2


async def test_a_finished_unit_does_not_look_like_a_dead_worker(
    db: AsyncSession, clock: FrozenClock, calls: list[tuple[str, Any]]
) -> None:
    w = await make_world(db)
    run = await make_run(db, w)
    await make_task(db, w, run)
    await make_task(db, w, run, key="later:run", status="WAITING")  # the run isn't done
    assert await worker.advance_run(db, run.id, owner="t") == "executed"
    await db.refresh(run)
    assert run.substatus == "WAITING" and await scheduler.reap(db) == []


async def test_any_exception_in_a_task_unit_is_retried_then_parked_not_looped(
    db: AsyncSession, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def broken(*_: Any) -> None:
        calls.append("run")
        raise KeyError("a malformed plan item")

    monkeypatch.setattr(worker, "execute_task", broken)
    monkeypatch.setattr(executor, "execute_task", broken)
    w = await make_world(db)
    run = await make_run(db, w)
    task_id, run_id = (await make_task(db, w, run)).id, run.id
    for _ in range(4):
        await worker.advance_run(db, run_id, owner="t")
        for retry in await db.scalars(select(Episode).where(Episode.status == "scheduled")):
            retry.status = "pending"  # the backoff has passed
        await db.commit()
    run = await db.get_one(AgentRun, run_id, populate_existing=True)
    task = await db.get_one(RunTask, task_id, populate_existing=True)
    asked = await db.scalar(select(StepResult).where(StepResult.task_id == task_id))
    assert len(calls) == 3 and (run.status, run.substatus) == ("PAUSED", "repeated_failure")
    assert task.status == "BLOCKED" and asked is not None and asked.kind == "item_failed"
    assert {o["value"] for o in asked.options} == {"retry", "skip"}
    assert "take it over and hand it back" in asked.summary, "the paused run says how to resume"


async def test_a_failure_while_answering_keeps_the_task_blocked(
    db: AsyncSession, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(*_: Any) -> None:
        raise LLMError("timeout", retryable=True)

    monkeypatch.setattr(worker, "resume_task", down)
    w = await make_world(db)
    run = await make_run(db, w)
    task = await make_task(db, w, run, status="BLOCKED")
    db.add(_ep(w, run, "answer:1", trigger_type="user_response", task_id=task.id))
    await db.commit()
    task_id, run_id = task.id, run.id
    await worker.advance_run(db, run_id, owner="t")
    task = await db.get_one(RunTask, task_id, populate_existing=True)
    assert task.status == "BLOCKED"


async def test_a_caught_failure_does_not_count_as_a_killed_worker(
    db: AsyncSession, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: Any) -> None:
        raise KeyError("x")

    monkeypatch.setattr(worker, "execute_task", broken)
    w = await make_world(db)
    run = await make_run(db, w)
    plan = [{**item(1, "tool"), "status": "RUNNING", "attempts": 1, "resumes": 2}]
    task_id, run_id = (await make_task(db, w, run, plan=plan)).id, run.id
    await worker.advance_run(db, run_id, owner="t")
    task = await db.get_one(RunTask, task_id, populate_existing=True)
    assert task.plan[0]["resumes"] == 0


async def test_a_crash_before_the_check_is_queued_still_gets_it_checked(
    db: AsyncSession,
    clock: FrozenClock,
    calls: list[tuple[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = await make_world(db)
    run = await make_run(db, w)
    await make_task(db, w, run)
    run_id = run.id

    async def die(*_: Any) -> None:
        raise SystemExit("killed right after the task finished")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(worker, "_queue_check", die)
        with pytest.raises(SystemExit):
            await worker.advance_run(db, run_id, owner="a")
    await db.rollback()
    clock.advance(timedelta(minutes=10))
    for _ in range(3):
        await worker.advance_run(db, run_id, owner="b")
    assert [c for c, _ in calls] == ["execute", "check"]


async def test_a_queued_check_is_dropped_when_work_reopened_before_it_ran(
    db: AsyncSession, clock: FrozenClock, calls: list[tuple[str, Any]]
) -> None:
    w = await make_world(db)
    run = await make_run(db, w)
    await make_task(db, w, run)
    assert await worker.advance_run(db, run.id, owner="t") == "executed"  # queues the check
    await make_task(db, w, run, key="new:run")  # e.g. a triage just added work
    assert await worker.advance_run(db, run.id, owner="t") == "stale"
    assert "check" not in [c for c, _ in calls]
