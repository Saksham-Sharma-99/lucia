"""Tools every agent can plan without a connector (RUNTIME_SPEC §6.4). Asking a person and
thinking work are item kinds (human, subagent), not tools."""

from typing import Any

from sqlalchemy.dialects.postgresql import insert

from lucia.db.models import StepResult
from lucia.harness.journal import append
from lucia.harness.tools.base import ToolContext, ToolResult
from lucia.notifications.plan import notify


async def emit_finding(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    """P0/P1 findings notify like attention; P2 findings wait for the digest (HLD §14)."""
    run = ctx.view.run
    finding_id = await ctx.session.scalar(
        insert(StepResult)
        .values(
            firm_id=run.firm_id,
            run_id=run.id,
            task_id=ctx.task.id,
            type="finding",
            kind=args["kind"],
            urgency=args["urgency"],
            summary=args["summary"],
            summary_public=f"New {args['kind'].replace('_', ' ')} update",
            data=args.get("data") or {},
            dedup_key=f"sr:{ctx.task.id}:{ctx.item['id']}:finding:{ctx.item['attempts']}",
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(StepResult.id)
    )
    if finding_id is not None and args["urgency"] in ("P0", "P1"):
        await notify(
            ctx.session,
            run,
            finding_id,
            kind="finding",
            summary=args["summary"],
            urgency=args["urgency"],
            options=[],
        )
    return ToolResult(status="SUCCEEDED", summary=f"Reported {args['kind']}")


async def journal_append(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    await append(
        ctx.session,
        ctx.view.run,
        text=args["text"],
        source="agent",
        key=f"{ctx.task.id}:{ctx.item['id']}:{ctx.item['attempts']}:note",
        task_id=ctx.task.id,
    )
    return ToolResult(status="SUCCEEDED", summary="Noted")
