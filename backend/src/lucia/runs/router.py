import uuid
from typing import Annotated

from fastapi import Query
from sqlalchemy import Row, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.api.tags import api_router
from lucia.auth.deps import CurrentUser, DbSession
from lucia.core.errors import conflict, not_found
from lucia.core.pagination import Page, Paging, fetch_page
from lucia.db.models import (
    Agent,
    AgentPrompt,
    AgentRun,
    AgentRunStep,
    Episode,
    Firm,
    JournalEntry,
    JournalSummary,
    RunStepLog,
    RunTask,
    StepResult,
    Subject,
)
from lucia.db.models.run import TERMINAL_TASK, RunStatus
from lucia.db.queries import get_or_404, like_pattern
from lucia.harness import control
from lucia.runs import schemas as s

router = api_router("runs")


def _runs() -> Select[AgentRun, str, str, int, int, int]:
    """Runs with what a run card shows, in one query (tasks counted by correlated subqueries)."""
    tasks = select(func.count()).where(RunTask.run_id == AgentRun.id)
    done = tasks.where(RunTask.status.in_(TERMINAL_TASK))
    return (
        select(
            AgentRun,
            Agent.handle,
            Subject.title,
            AgentPrompt.version,
            done.scalar_subquery(),
            tasks.scalar_subquery(),
        )
        .join(Agent, Agent.id == AgentRun.agent_id)
        .join(Subject, Subject.id == AgentRun.subject_id)
        .join(AgentPrompt, AgentPrompt.id == AgentRun.agent_prompt_id)
    )


def _row_out(row: Row[AgentRun, str, str, int, int, int]) -> s.RunOut:
    run, handle, subject, version, done, total = row
    return s.RunOut.model_validate(
        {
            **{c: getattr(run, c) for c in s.RunOut.model_fields if hasattr(run, c)},
            "agent_handle": handle,
            "subject_title": subject,
            "version": version,
            "tasks_done": done,
            "tasks_total": total,
        }
    )


async def _out(session: AsyncSession, run_id: uuid.UUID) -> s.RunOut:
    # populate_existing: bulk updates (scheduling, controls) may have changed the loaded run
    row = (
        await session.execute(
            _runs().where(AgentRun.id == run_id).execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        raise not_found("Run")
    return _row_out(row)


@router.get("/firms/{firm_id}/runs", summary="List a firm's agent runs", operation_id="listRuns")
async def list_runs(
    firm_id: uuid.UUID,
    session: DbSession,
    paging: Paging,
    agent: str | None = None,
    status: RunStatus | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[s.RunOut]:
    await get_or_404(session, Firm, firm_id, "Firm")
    stmt = _runs().where(AgentRun.firm_id == firm_id).order_by(AgentRun.created_at.desc())
    if agent:
        stmt = stmt.where(Agent.handle == agent)
    if status:
        stmt = stmt.where(AgentRun.status == status)
    if q:
        stmt = stmt.where(Subject.title.ilike(like_pattern(q), escape="\\"))
    rows, total = await fetch_page(session, stmt, paging, scalars=False)
    return Page.of([_row_out(r) for r in rows], total, paging)


@router.get("/runs/{run_id}", summary="Get a run", operation_id="getRun")
async def get_run(run_id: uuid.UUID, session: DbSession) -> s.RunOut:
    return await _out(session, run_id)


@router.get("/runs/{run_id}/tasks", summary="A run's tasks with plans", operation_id="listRunTasks")
async def list_tasks(run_id: uuid.UUID, session: DbSession) -> list[s.TaskOut]:
    await get_or_404(session, AgentRun, run_id, "Run")
    rows = await session.scalars(
        select(RunTask).where(RunTask.run_id == run_id).order_by(RunTask.created_at)
    )
    return [s.TaskOut.model_validate(t) for t in rows]


@router.get("/runs/{run_id}/steps", summary="A run's executed steps", operation_id="listRunSteps")
async def list_steps(
    run_id: uuid.UUID,
    session: DbSession,
    task_id: uuid.UUID | None = None,
    plan_item_id: str | None = None,
) -> list[s.StepOut]:
    await get_or_404(session, AgentRun, run_id, "Run")
    stmt = select(AgentRunStep).where(AgentRunStep.run_id == run_id).order_by(AgentRunStep.seq)
    if task_id:
        stmt = stmt.where(AgentRunStep.task_id == task_id)
    if plan_item_id:
        stmt = stmt.where(AgentRunStep.plan_item_id == plan_item_id)
    return [s.StepOut.model_validate(st) for st in await session.scalars(stmt)]


@router.get("/runs/{run_id}/logs", summary="A run's redacted logs", operation_id="listRunLogs")
async def list_logs(
    run_id: uuid.UUID,
    session: DbSession,
    task_id: uuid.UUID | None = None,
    step_id: uuid.UUID | None = None,
    level: str | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[s.LogOut]:
    await get_or_404(session, AgentRun, run_id, "Run")
    stmt = (
        select(RunStepLog).where(RunStepLog.run_id == run_id).order_by(RunStepLog.at, RunStepLog.id)
    )
    for column, value in (
        (RunStepLog.task_id, task_id),
        (RunStepLog.step_id, step_id),
        (RunStepLog.level, level),
    ):
        if value is not None:
            stmt = stmt.where(column == value)
    if q:
        stmt = stmt.where(RunStepLog.message.ilike(like_pattern(q), escape="\\"))
    return [s.LogOut.model_validate(entry) for entry in await session.scalars(stmt.limit(1000))]


@router.get("/runs/{run_id}/episodes", summary="A run's episodes", operation_id="listRunEpisodes")
async def list_episodes(run_id: uuid.UUID, session: DbSession) -> list[s.EpisodeOut]:
    await get_or_404(session, AgentRun, run_id, "Run")
    rows = await session.scalars(
        select(Episode).where(Episode.run_id == run_id).order_by(Episode.created_at.desc())
    )
    return [s.EpisodeOut.model_validate(e) for e in rows]


@router.get("/runs/{run_id}/journal", summary="A run's journal", operation_id="listRunJournal")
async def journal(run_id: uuid.UUID, session: DbSession) -> s.JournalOut:
    await get_or_404(session, AgentRun, run_id, "Run")
    summary = await session.scalar(
        select(JournalSummary.text)
        .where(JournalSummary.run_id == run_id)
        .order_by(JournalSummary.created_at.desc())
    )
    entries = await session.scalars(
        select(JournalEntry).where(JournalEntry.run_id == run_id).order_by(JournalEntry.seq)
    )
    return s.JournalOut(
        summary=summary, entries=[s.JournalEntryOut.model_validate(e) for e in entries]
    )


@router.get(
    "/runs/{run_id}/attention", summary="A run's attention items", operation_id="listRunAttention"
)
async def attention(run_id: uuid.UUID, session: DbSession) -> list[s.StepResultOut]:
    await get_or_404(session, AgentRun, run_id, "Run")
    rows = await session.scalars(
        select(StepResult)
        .where(StepResult.run_id == run_id, StepResult.type == "attention")
        .order_by((StepResult.status != "open"), StepResult.created_at.desc())
    )
    return [s.StepResultOut.model_validate(r) for r in rows]


async def _control(
    run_id: uuid.UUID, session: AsyncSession, action: str, user_id: uuid.UUID, remarks: str
) -> s.RunOut:
    run = await get_or_404(session, AgentRun, run_id, "Run")
    try:
        if action == "takeover":
            await control.takeover(session, run, user_id=user_id, remarks=remarks)
        else:
            await control.handback(session, run, user_id=user_id, remarks=remarks)
    except control.ControlError as e:
        raise conflict(str(e)) from e
    return await _out(session, run.id)


@router.post(
    "/runs/{run_id}/takeover",
    summary="Take over a run (pauses the agent)",
    operation_id="takeoverRun",
)
async def takeover(
    run_id: uuid.UUID, body: s.RemarksIn, session: DbSession, user: CurrentUser
) -> s.RunOut:
    return await _control(run_id, session, "takeover", user.id, body.remarks)


@router.post(
    "/runs/{run_id}/handback", summary="Hand a run back to its agent", operation_id="handbackRun"
)
async def handback(
    run_id: uuid.UUID, body: s.RemarksIn, session: DbSession, user: CurrentUser
) -> s.RunOut:
    return await _control(run_id, session, "handback", user.id, body.remarks)
