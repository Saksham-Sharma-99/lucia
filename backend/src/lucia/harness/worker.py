"""`advance_run`: claim the lease, do one unit of work, release (RUNTIME_SPEC §4).

A unit is, in order: a crashed Episode left running, the oldest run-wide Episode (triage, or a
completion check), the oldest task Episode (resume that task), or the next runnable task. Every
failure is bounded: an Episode retries with backoff, then the run pauses for a person."""

import hashlib
import logging
import uuid

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.db.models import AgentRun, Episode, RunTask
from lucia.db.models.run import TERMINAL_TASK
from lucia.harness.attention import raise_attention
from lucia.harness.completion import check_run
from lucia.harness.exec.reconcile import reconcile_orphans
from lucia.harness.executor import RETRY_BACKOFF, execute_task, resume_task, uncount_resumes
from lucia.harness.gate import gate
from lucia.harness.intake import EpisodeSpec, insert_episode
from lucia.harness.lease import LeaseLost, claim, fence, release
from lucia.harness.triage import run_triage
from lucia.llm.client import LLMError
from lucia.worker.dispatch import send

MAX_EPISODE_RESUMES = 3  # an Episode that keeps killing the worker is set aside
log = logging.getLogger(__name__)


async def advance_run(session: AsyncSession, run_id: uuid.UUID, *, owner: str) -> str:
    epoch = await claim(session, run_id, owner)
    if epoch is None:
        return "not_claimed"
    try:
        run = await session.get_one(AgentRun, run_id, populate_existing=True)
        await reconcile_orphans(session, run, epoch)
        if await gate(session, run) != "ok":
            return await _release(session, run_id, epoch, "gated")
        outcome = await _one_unit(session, run, epoch)
        if (key := await _check_key(session, run)) is not None:
            await _queue_check(session, run, key)  # after every unit: a crash can't lose it
    except LeaseLost:
        return "lease_lost"
    return await _release(session, run_id, epoch, outcome)


async def _release(session: AsyncSession, run_id: uuid.UUID, epoch: int, outcome: str) -> str:
    # only Episodes that arrived while we held the lease bring an idle run back
    if await release(session, run_id, epoch, tasks=outcome not in ("no_work", "gated")):
        send("harness.advance_run", run_id)
    return outcome


async def _one_unit(session: AsyncSession, run: AgentRun, epoch: int) -> str:
    episode = await _next_episode(session, run, epoch)
    if episode is not None:
        return await _process(session, run, episode, epoch)
    task = await next_runnable(session, run.id)
    if task is not None:
        _substatus(run, "RUNNING")  # with an expired lease, the reaper's sign of a dead worker
        await session.commit()
        try:
            await execute_task(session, run, task, epoch)
        except LeaseLost:
            raise
        except Exception as e:  # any failure: a bounded retry, never a loop
            return await _as_retry(session, run, epoch, e, task)
        return "executed"
    _substatus(run, "WAITING")
    await session.commit()
    return "no_work"


def _substatus(run: AgentRun, value: str) -> None:
    """Substatus only qualifies ACTIVE (DATA_MODEL §3.6)."""
    if run.status == "ACTIVE":
        run.substatus = value


async def _next_episode(session: AsyncSession, run: AgentRun, epoch: int) -> Episode | None:
    crashed = await session.scalar(
        select(Episode).where(
            Episode.run_id == run.id, Episode.status == "running", Episode.lease_epoch < epoch
        )
    )
    if crashed is not None:
        resumes = crashed.metadata_.get("resume_count", 0)
        if resumes >= MAX_EPISODE_RESUMES:
            await _give_up(session, run, crashed, "poison", "An episode kept crashing the worker")
            return await _next_episode(session, run, epoch)
        crashed.metadata_ = {**crashed.metadata_, "resume_count": resumes + 1}
        episode = crashed
    else:
        episode = await session.scalar(
            select(Episode)
            .where(Episode.run_id == run.id, Episode.status == "pending")
            .order_by(
                case((Episode.trigger_type == "handback", 0), else_=1),
                case((Episode.task_id.is_(None), 0), else_=1),
                Episode.queued_at,
                Episode.created_at,
            )
            .limit(1)
        )
        if episode is None:
            return None
    episode.status, episode.lease_epoch = "running", epoch
    episode.started_at = episode.started_at or get_clock().now()
    _substatus(run, "RUNNING")
    await session.commit()
    return episode


async def _process(session: AsyncSession, run: AgentRun, episode: Episode, epoch: int) -> str:
    try:
        if episode.metadata_.get("unit") == "completion":
            key = episode.metadata_["key"]
            # queued for a state that has moved on (new work, a later triage): a newer check owns it
            stale = await _check_key(session, run) != key
            outcome = "stale" if stale else await check_run(session, run, epoch, key)
        elif episode.task_id is None:
            await run_triage(session, run, episode, epoch)
            outcome = "triaged"
        else:
            task = await session.get_one(RunTask, episode.task_id)
            await resume_task(session, run, task, episode, epoch)
            outcome = "task_resumed"
    except LeaseLost:
        raise
    except Exception as e:
        return await _retry_or_stop(session, run, episode, epoch, e)
    episode.status, episode.outcome, episode.ended_at = "completed", outcome, get_clock().now()
    await session.commit()
    return outcome


async def _check_key(session: AsyncSession, run: AgentRun) -> str | None:
    """When the run is active and every task is terminal (§11.2 trigger): a fingerprint of the
    task outcomes and the latest triage. A new fingerprint is owed one completion check; the
    same one never gets two (a person's note re-checks, a no-op unit doesn't)."""
    if run.status != "ACTIVE":
        return None
    tasks = (
        await session.execute(
            select(RunTask.id, RunTask.status, func.jsonb_array_length(RunTask.plan))
            .where(RunTask.run_id == run.id)
            .order_by(RunTask.id)
        )
    ).all()
    if not tasks or any(status not in TERMINAL_TASK for _, status, _ in tasks):
        return None
    triage = await session.scalar(
        select(Episode.id)
        .where(
            Episode.run_id == run.id,
            Episode.task_id.is_(None),
            Episode.status == "completed",
            Episode.metadata_["unit"].astext.is_(None),
        )
        .order_by(Episode.ended_at.desc())
        .limit(1)
    )
    raw = "|".join([*(f"{t}:{st}:{n}" for t, st, n in tasks), str(triage)])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def _queue_check(session: AsyncSession, run: AgentRun, key: str) -> None:
    """The completion check is its own unit, an Episode: a crash in it is resumed like any
    other, and its model failures get the Episode backoff. Idempotent by `key`."""
    await insert_episode(
        session,
        run,
        EpisodeSpec(
            trigger_type="scheduled",
            source="retry",  # a unit the worker re-runs, like a retry (B21)
            dedup_key=f"completion:{run.id}:{key}",
            metadata={"unit": "completion", "key": key},
        ),
    )
    await session.commit()


async def _as_retry(
    session: AsyncSession, run: AgentRun, epoch: int, e: Exception, task: RunTask
) -> str:
    """A task run (outside any Episode) failed: it becomes a retry Episode for the task, so it
    gets the Episode backoff."""
    firm_id, run_id, task_id = run.firm_id, run.id, task.id
    await session.rollback()
    await fence(session, run_id, epoch)  # a control that landed during the unit wins
    episode = Episode(
        firm_id=firm_id,
        run_id=run_id,
        task_id=task_id,
        trigger_type="scheduled",
        source="retry",
        status="running",
        lease_epoch=epoch,
        dedup_key=f"retry:task:{uuid.uuid4()}",  # a failure, not a replayable trigger
    )
    session.add(episode)
    await session.commit()
    run = await session.get_one(AgentRun, run_id, populate_existing=True)
    return await _retry_or_stop(session, run, episode, epoch, e)


async def _retry_or_stop(
    session: AsyncSession, run: AgentRun, episode: Episode, epoch: int, e: Exception
) -> str:
    """Retry the same Episode with backoff; the third failure pauses the run (ADR-SE-03). Model
    errors say whether a retry can help; any other error is retried the same bounded way. The
    Episode's runnable task is parked meanwhile (WAITING, then BLOCKED), so the worker doesn't
    pick it up again before its retry is due."""
    log.warning("unit failed on run %s: %s", run.id, type(e).__name__)  # no message: may hold PHI
    run_id, episode_id = run.id, episode.id
    await session.rollback()  # the unit's half-made work, and the failed call's step
    # a control that landed during the unit wins: LeaseLost, and the Episode stays running,
    # to be resumed once the run is handed back
    await fence(session, run_id, epoch)
    run = await session.get_one(AgentRun, run_id, populate_existing=True)
    episode = await session.get_one(Episode, episode_id, populate_existing=True)
    task = await session.get(RunTask, episode.task_id) if episode.task_id else None
    count = episode.metadata_.get("retry_count", 0) + 1
    episode.metadata_ = {**episode.metadata_, "retry_count": count, "last_error": repr(e)}
    retryable = e.retryable if isinstance(e, LLMError) else True
    retry = retryable and count <= len(RETRY_BACKOFF)
    if task is not None:
        uncount_resumes(task)  # a caught error isn't a killed worker
        if task.status in ("TODO", "IN_PROGRESS", "WAITING"):
            task.status = "WAITING" if retry else "BLOCKED"
    if retry:
        episode.status, episode.due_at = "scheduled", get_clock().now() + RETRY_BACKOFF[count - 1]
        await session.commit()
        return "retry_scheduled"
    why = f"This step kept failing ({type(e).__name__})."
    if retryable:
        run.status, run.substatus = "PAUSED", "repeated_failure"
        why += " The run is paused: answer, then take it over and hand it back to resume."
    await _give_up(session, run, episode, "failed", why)
    return "failed"


async def _give_up(
    session: AsyncSession, run: AgentRun, episode: Episode, outcome: str, why: str
) -> None:
    episode.status, episode.outcome, episode.ended_at = "failed", outcome, get_clock().now()
    on_task = episode.task_id is not None  # a person can retry or skip that task
    await raise_attention(
        session,
        run,
        kind="item_failed" if on_task else "escalation",
        summary=why,
        dedup_key=f"sr:episode:{episode.id}:failed",
        task_id=episode.task_id,
        data={"episode_id": str(episode.id), "source": outcome, "item_id": None},
        options=[{"value": "retry", "label": "Try again"}, {"value": "skip", "label": "Skip it"}]
        if on_task
        else (),
    )
    await session.commit()


async def next_runnable(session: AsyncSession, run_id: uuid.UUID) -> RunTask | None:
    """The oldest TODO/IN_PROGRESS task whose dependencies are all terminal."""
    tasks = list(
        await session.scalars(
            select(RunTask)
            .where(RunTask.run_id == run_id)
            .order_by(RunTask.created_at, RunTask.key)
        )
    )
    done = {t.key for t in tasks if t.status in TERMINAL_TASK}
    return next(
        (
            t
            for t in tasks
            if t.status in ("TODO", "IN_PROGRESS") and all(d in done for d in t.depends_on)
        ),
        None,
    )
