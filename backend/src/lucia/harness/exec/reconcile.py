"""Before a new lease holder runs anything, outbox rows left PENDING by a dead worker are
resolved with the provider (RUNTIME_SPEC §8.4). Sent → adopted; absent → resend under the same
key; recently absent → re-check later; unknown → a person decides. Until it's settled the item
waits, so the worker never sends again on its own. At most once when unsure."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.db.models import AgentRun, AgentRunStep, RegistryEntry, RunTask
from lucia.db.models.run import TaskStatus
from lucia.harness.exec.tool_executor import OUTBOX, ask_if_sent
from lucia.harness.plan import item, set_item
from lucia.scheduling import scheduler

MIN_AGE = timedelta(seconds=120)  # a provider may not list a just-placed call yet


async def reconcile_orphans(session: AsyncSession, run: AgentRun, epoch: int) -> None:
    orphans = await session.scalars(
        select(AgentRunStep).where(
            AgentRunStep.run_id == run.id,
            AgentRunStep.status == "PENDING",
            AgentRunStep.kind == "tool",
            AgentRunStep.lease_epoch < epoch,
        )
    )
    now = get_clock().now()
    for step in orphans:
        tool = OUTBOX.get(step.tool or "")
        if tool is None:
            continue
        found = await tool.sent_lookup(session, step)
        if found == "found":
            asynchronous = await session.scalar(
                select(RegistryEntry.is_async).where(
                    RegistryEntry.kind == "tool", RegistryEntry.name == step.tool
                )
            )
            step.status = "AWAITING_CALLBACK" if asynchronous else "SUCCEEDED"
            step.output = {**step.output, "adopted": True}
        elif found == "absent" and step.started_at and now - step.started_at >= MIN_AGE:
            step.status, step.error = "FAILED", {"class": "not_sent", "reason": "absent"}
        elif found == "absent":
            await _park(session, step, "WAITING")
            await scheduler.schedule(
                session,
                run,
                task_id=step.task_id,
                source="reconcile",
                due_at=(step.started_at or now) + MIN_AGE,
                dedup_key=f"reconcile:{step.id}",
                reason="check whether the send went out",
                metadata={"plan_item_id": step.plan_item_id, "step_id": str(step.id)},
            )
        else:
            await ask_if_sent(session, run, step)
            await _park(session, step, "BLOCKED")
    await session.commit()


async def _park(session: AsyncSession, step: AgentRunStep, task_status: TaskStatus) -> None:
    assert step.task_id is not None and step.plan_item_id is not None
    task = await session.get_one(RunTask, step.task_id)
    ids = item(task, step.plan_item_id)["step_ids"]
    if str(step.id) not in ids:
        ids = [*ids, str(step.id)]
    set_item(task, step.plan_item_id, status="WAITING", step_ids=ids)
    task.status = task_status
