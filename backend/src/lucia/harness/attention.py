"""Attention items: things only a human can resolve (DATA_MODEL §3.12)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.db.models import AgentRun, Firm, StepResult
from lucia.notifications.plan import notify
from lucia.notifications.sla import due_at

BLOCKING = frozenset(
    {"question", "verify", "item_failed", "review_low", "plan_cap", "confirm_completion"}
)
# Answers that move a task on: they become a user_response Episode for that task.
RESUMES_TASK = frozenset(
    {
        "question",
        "verify",
        "item_failed",
        "review_low",
        "plan_cap",
        "uncertain_send",
        "guardrail_block",
    }
)


async def raise_attention(
    session: AsyncSession,
    run: AgentRun,
    *,
    kind: str,
    summary: str,
    dedup_key: str,
    urgency: str = "P1",
    summary_public: str | None = None,
    data: dict[str, Any] | None = None,
    options: Sequence[dict[str, str]] = (),
    task_id: uuid.UUID | None = None,
    step_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Idempotent by `dedup_key`; the caller commits. Returns None for a duplicate.
    A new item is posted to the run's chats and routed to people (notifications.plan)."""

    firm = await session.get_one(Firm, run.firm_id)
    item_id = await session.scalar(
        insert(StepResult)
        .values(
            firm_id=run.firm_id,
            run_id=run.id,
            task_id=task_id,
            step_id=step_id,
            type="attention",
            kind=kind,
            urgency=urgency,
            summary=summary,
            summary_public=summary_public or summary,
            data=data or {},
            options=list(options),
            blocking=kind in BLOCKING,
            sla_due_at=due_at(urgency, get_clock().now(), firm.timezone, firm.settings),
            dedup_key=dedup_key,
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(StepResult.id)
    )
    if item_id is not None:
        await notify(
            session,
            run,
            item_id,
            kind=kind,
            summary=summary,
            urgency=urgency,
            options=list(options),
        )
    return item_id
