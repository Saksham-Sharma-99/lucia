"""What's happening on a subject, read straight from the database for status replies."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import Agent, AgentRun, RunTask, StepResult


async def read_status(session: AsyncSession, subject_id: uuid.UUID) -> dict[str, Any]:
    runs = await session.execute(
        select(AgentRun, Agent.handle)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(AgentRun.subject_id == subject_id)
        .order_by(AgentRun.created_at.desc())
        .limit(10)
    )
    out: list[dict[str, Any]] = []
    for run, handle in runs.all():
        tasks = await session.scalars(
            select(RunTask).where(RunTask.run_id == run.id).order_by(RunTask.created_at)
        )
        attention = await session.scalars(
            select(StepResult.summary).where(
                StepResult.run_id == run.id,
                StepResult.type == "attention",
                StepResult.status == "open",
            )
        )
        out.append(
            {
                "agent": f"@{handle}",
                "status": run.status,
                "goal": run.goal,
                "next_wake_at": run.next_wake_at,
                "tasks": [
                    {
                        "title": t.title,
                        "status": t.status,
                        "result": (t.output or {}).get("summary"),
                    }
                    for t in tasks
                ],
                "waiting_on_you": list(attention),
            }
        )
    findings = await session.scalars(
        select(StepResult.summary)
        .join(AgentRun, AgentRun.id == StepResult.run_id)
        .where(AgentRun.subject_id == subject_id, StepResult.type == "finding")
        .order_by(StepResult.created_at.desc())
        .limit(10)
    )
    return {"runs": out, "recent_findings": list(findings)}
