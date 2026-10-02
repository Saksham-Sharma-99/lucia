from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import JournalEntry, StepResult
from lucia.harness.agent_view import load
from lucia.harness.exec import tool_executor
from lucia.harness.tools.base import ToolContext
from tests.world import item, make_leased_run, make_task, make_world


async def _ctx(db: AsyncSession) -> ToolContext:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run, plan=[item(1, "tool", tool="harness.emit_finding")])
    return ToolContext(db, await load(db, run), task, task.plan[0], 1)


async def test_every_agent_can_plan_the_harness_tools(db: AsyncSession) -> None:
    ctx = await _ctx(db)
    assert {"harness.emit_finding", "harness.journal_append"} <= set(ctx.view.tools)


async def test_emit_finding_records_a_finding(db: AsyncSession, clock: FrozenClock) -> None:
    ctx = await _ctx(db)
    result = await tool_executor.run(
        ctx,
        "harness.emit_finding",
        {
            "kind": "new_provider",
            "summary": "Jane started PT with Dr. Lee",
            "urgency": "P1",
            "data": {},
        },
    )
    assert result.status == "SUCCEEDED"
    finding = await db.scalar(select(StepResult))
    assert finding is not None
    assert (finding.type, finding.kind, finding.urgency, finding.status) == (
        "finding",
        "new_provider",
        "P1",
        "open",
    )


async def test_journal_append_adds_an_agent_note(db: AsyncSession, clock: FrozenClock) -> None:
    ctx = await _ctx(db)
    await tool_executor.run(ctx, "harness.journal_append", {"text": "Jane prefers mornings"})
    entry = await db.scalar(select(JournalEntry))
    assert entry is not None and (entry.source, entry.text) == ("agent", "Jane prefers mornings")


async def test_unknown_tool_is_not_bound(db: AsyncSession, clock: FrozenClock) -> None:
    ctx = await _ctx(db)
    result = await tool_executor.run(ctx, "gmail.send_email", {})
    assert (result.status, result.reason) == ("FAILED", "not_bound")
