"""Celery entry points for the harness. Arguments are ids only (no PHI in the broker)."""

import os
import socket
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import AgentRun
from lucia.db.models.run import CLAIMABLE
from lucia.harness.control import sweep_killed
from lucia.harness.gate import gate
from lucia.harness.worker import advance_run
from lucia.worker.celery_app import celery_app
from lucia.worker.runner import run_async

OWNER = f"{socket.gethostname()}:{os.getpid()}"


@celery_app.task(name="harness.advance_run")
def advance_run_task(run_id: str) -> str:
    return run_async(lambda session: advance_run(session, uuid.UUID(run_id), owner=OWNER))


@celery_app.task(name="harness.kill_switch_sweep")
def kill_switch_sweep() -> int:
    return run_async(sweep_killed)


async def sweep_end_conditions(session: AsyncSession) -> int:
    """Idle and paused runs reach max_duration too; the gate ends or pauses them. Taken-over
    runs are left to the person holding them."""
    live = (*CLAIMABLE, "PAUSED")
    run_ids = list(await session.scalars(select(AgentRun.id).where(AgentRun.status.in_(live))))
    ended = 0
    for run_id in run_ids:
        # re-read under lock: it may have been taken over or finished since the list was read
        run = await session.get_one(AgentRun, run_id, with_for_update=True, populate_existing=True)
        if run.status in live:
            ended += await gate(session, run) != "ok"
        await session.commit()
    return ended


@celery_app.task(name="harness.end_condition_sweep")
def end_condition_sweep() -> int:
    return run_async(sweep_end_conditions)
