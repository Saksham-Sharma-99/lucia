"""Attention SLAs (HLD §13): P0 within an hour, P1 within one business day, P2 none.
An overdue item escalates once to the next urgency and notifies again."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.db.models import AgentRun, Notification, StepResult
from lucia.notifications.updates import post_run_update

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
UP = {"P2": "P1", "P1": "P0", "P0": "P0"}


def due_at(urgency: str, now: datetime, tz: str, settings: dict[str, Any]) -> datetime | None:
    if urgency == "P0":
        return now + timedelta(hours=1)
    if urgency != "P1":
        return None
    hours = settings.get("business_hours") or {}
    local = now.astimezone(ZoneInfo(tz))
    for days in range(1, 8):  # the same local time on the next business day
        candidate = local + timedelta(days=days)
        if hours.get(DAYS[candidate.weekday()]):
            return candidate
    return local + timedelta(days=1)


async def sweep(session: AsyncSession) -> int:
    overdue = list(
        await session.scalars(
            select(StepResult).where(
                StepResult.type == "attention",
                StepResult.status == "open",
                StepResult.sla_due_at < get_clock().now(),
                ~StepResult.data.has_key("escalated"),
            )
        )
    )
    for item in overdue:
        item.urgency = UP[item.urgency]
        item.data = {**item.data, "escalated": True}
        if item.run_id:
            run = await session.get_one(AgentRun, item.run_id)
            await post_run_update(
                session,
                run,
                body=f"Still waiting on you: {item.summary}",
                source_id=f"sla:{item.id}",
            )
        await session.execute(
            update(Notification).where(Notification.step_result_id == item.id).values(read_at=None)
        )
    await session.commit()
    return len(overdue)
