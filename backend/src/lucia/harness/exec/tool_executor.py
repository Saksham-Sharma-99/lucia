"""Every model-chosen tool call goes through here (RUNTIME_SPEC §8).

Outbound tools: recipient → idempotency key → policy → guardrail → outbox row (fenced, cap
lock) → kill switch check → send → compare-and-set. The key is harness state plus the resolved
recipient address, never the drafted text, so a reworded draft after a crash gets the same key."""

import uuid
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.connectors.base import ConnectorError, MaybeSent
from lucia.core.clock import get_clock
from lucia.db.models import AgentRun, AgentRunStep, CompiledAgentFirmMapping
from lucia.db.models.run import CLAIMABLE
from lucia.harness.attention import raise_attention
from lucia.harness.exec.guardrail import check
from lucia.harness.exec.policy import Allow, Decision, Deny, PolicyInput, Recipient, evaluate
from lucia.harness.lease import LeaseLost, fence
from lucia.harness.steps import add_step
from lucia.harness.tools.base import Outboxed, ToolContext, ToolResult
from lucia.harness.tools.registry import IMPLS
from lucia.harness.tools.vapi_tool import VAPI
from lucia.llm.client import LLMError

OUTBOX: dict[str, Outboxed] = {"vapi.place_call": VAPI}
SENT = ("SUCCEEDED", "AWAITING_CALLBACK")
MAYBE_SENT = ("PENDING", *SENT)  # an outbox row that may have reached the recipient


async def run(ctx: ToolContext, tool: str, args: dict[str, Any]) -> ToolResult:
    spec = ctx.view.tools.get(tool)
    if spec is None or (tool not in OUTBOX and tool not in IMPLS):
        return ToolResult(status="FAILED", reason="not_bound", summary=f"{tool} is not available")
    if errors := [e.message for e in Draft202012Validator(spec.input_schema).iter_errors(args)]:
        return ToolResult(
            status="FAILED", retryable=True, reason="schema", summary="; ".join(errors)
        )
    if tool in OUTBOX:
        return await _outboxed(ctx, tool, OUTBOX[tool], args)
    key = ctx.key(tool)
    prior = await ctx.session.scalar(
        select(AgentRunStep).where(AgentRunStep.idempotency_key == key)
    )
    if prior is not None and prior.status == "SUCCEEDED":
        return _cached(prior)
    result = await IMPLS[tool](ctx, args)
    if result.status == "DEFERRED":
        return result
    step = await add_step(
        ctx.session,
        ctx.view.run,
        kind="tool",
        tool=tool,
        status="SUCCEEDED" if result.status == "SUCCEEDED" else "FAILED",
        idempotency_key=key if prior is None else f"{key}:{uuid.uuid4()}",
        epoch=ctx.epoch,
        task_id=ctx.task.id,
        plan_item_id=ctx.item["id"],
        input=args,
        summary=result.summary,
    )
    return result.model_copy(update={"step_id": step.id})


async def _sent_today(
    session: AsyncSession, run: AgentRun, r: Recipient, now: datetime, firm_tz: str
) -> tuple[int, int]:
    """Outbound attempts to this contact point since local midnight: (this subject, the firm).
    "Local" is the recipient's zone, else the firm's, as the policy engine reads it."""
    tz = ZoneInfo(r.tz or firm_tz)
    since = datetime.combine(now.astimezone(tz).date(), time(0), tzinfo=tz)
    base = (
        select(func.count())
        .select_from(AgentRunStep)
        .where(
            AgentRunStep.kind == "tool",
            AgentRunStep.contact_point_id == r.contact_point_id,
            AgentRunStep.status.in_(MAYBE_SENT),
            AgentRunStep.started_at >= since,
        )
    )
    org = await session.scalar(base) or 0
    subject = (
        await session.scalar(
            base.join(AgentRun, AgentRun.id == AgentRunStep.run_id).where(
                AgentRun.subject_id == run.subject_id
            )
        )
        or 0
    )
    return subject, org


async def _decide(ctx: ToolContext, r: Recipient | None) -> Decision:
    now, firm_tz = get_clock().now(), ctx.view.firm.timezone
    subject, org = await _sent_today(ctx.session, ctx.view.run, r, now, firm_tz) if r else (0, 0)
    return evaluate(
        PolicyInput(
            rules=ctx.view.policies,
            recipient=r,
            firm_tz=firm_tz,
            now=now,
            sent_today_subject=subject,
            sent_today_org=org,
        )
    )


def _cached(step: AgentRunStep) -> ToolResult:
    """The result of a send that already went out (SENT statuses only)."""
    status = "AWAITING_CALLBACK" if step.status == "AWAITING_CALLBACK" else "SUCCEEDED"
    return ToolResult(
        status=status, summary=step.summary or "", output=step.output, step_id=step.id
    )


async def _outboxed(ctx: ToolContext, tool: str, ob: Outboxed, args: dict[str, Any]) -> ToolResult:
    session, run = ctx.session, ctx.view.run
    recipient = await ob.recipient(ctx, args)
    if recipient is not None and not recipient.address:
        return ToolResult(
            status="FAILED", reason="no_address", summary="The contact can't be reached here"
        )
    key = ctx.key(tool, (recipient.address if recipient else None) or "-")
    prior = await session.scalar(select(AgentRunStep).where(AgentRunStep.idempotency_key == key))
    if prior is not None and prior.status in SENT:
        return _cached(prior)  # already sent (or adopted after a crash)
    if prior is not None and (prior.status == "PENDING" or _uncertain(prior)):
        # an unsettled send: reconcile or a person decides; never send again from here
        return ToolResult(status="AWAITING_CALLBACK", reason="unsettled", step_id=prior.id)
    decision = await _decide(ctx, recipient)
    if not isinstance(decision, Allow):
        return await _not_allowed(ctx, tool, key, args, decision)
    assert recipient is not None
    try:
        verdict = await check(ctx, ob.guard_text(args), recipient.role)
    except LLMError:
        return ToolResult(status="FAILED", retryable=True, reason="guardrail_error")
    if not verdict.ok:
        return await _guardrail_block(ctx, tool, key, args, verdict.reasons)
    step = await _write_pending(ctx, tool, key, args, recipient, prior)
    if isinstance(step, ToolResult):
        return step
    if await _killed(session, run, ctx.epoch):
        await _settle(session, step, "FAILED", error={"class": "not_sent", "reason": "kill_switch"})
        return ToolResult(status="FAILED", reason="kill_switch", step_id=step.id)
    try:
        result = await ob.send(ctx, args, key, recipient, step)
    except MaybeSent:
        await ask_if_sent(session, run, step)
        await session.commit()
        return ToolResult(status="NEEDS_HUMAN", reason="maybe_sent", step_id=step.id)
    except ConnectorError as e:
        await _settle(
            session,
            step,
            "FAILED",
            error={"class": "not_sent", "reason": "connector", "detail": str(e)},
        )
        return ToolResult(
            status="FAILED",
            retryable=True,
            reason="connector_error",
            summary=str(e),
            step_id=step.id,
        )
    await _settle(
        session,
        step,
        result.status,
        output=result.output,
        summary=result.summary,
        external_ref=result.output.get("call_id"),
    )
    return result.model_copy(update={"step_id": step.id})


async def ask_if_sent(session: AsyncSession, run: AgentRun, step: AgentRunStep) -> None:
    """We can't tell whether a send went out: never resend on our own, a person decides.
    The caller commits."""
    step.status, step.error = "FAILED", {"class": "uncertain", "reason": "unconfirmed"}
    await raise_attention(
        session,
        run,
        kind="uncertain_send",
        summary=f"We can't tell whether {step.tool} reached the recipient. Was it sent?",
        dedup_key=f"sr:{step.id}:uncertain_send:{step.lease_epoch}",  # one per send try
        task_id=step.task_id,
        step_id=step.id,
        data={"step_id": str(step.id), "item_id": step.plan_item_id},
        options=[
            {"value": "sent", "label": "It was sent"},
            {"value": "not_sent", "label": "It was not sent"},
        ],
    )


def _uncertain(step: AgentRunStep) -> bool:
    return step.status == "FAILED" and (step.error or {}).get("class") == "uncertain"


async def _not_allowed(
    ctx: ToolContext, tool: str, key: str, args: dict[str, Any], d: Decision
) -> ToolResult:
    if isinstance(d, Deny):
        if not await ctx.session.scalar(
            select(AgentRunStep.id).where(AgentRunStep.idempotency_key == f"policy:{key}")
        ):
            await add_step(
                ctx.session,
                ctx.view.run,
                kind="policy",
                tool=tool,
                status="BLOCKED_BY_POLICY",
                idempotency_key=f"policy:{key}",
                epoch=ctx.epoch,
                task_id=ctx.task.id,
                plan_item_id=ctx.item["id"],
                input=args,
                summary=d.reason,
                output={"policy": {"rule": d.rule, "decision": "deny"}},
                actor="system",
            )  # the executor commits this with the item's status
        return ToolResult(status="BLOCKED_BY_POLICY", reason=d.rule, summary=d.reason)
    assert not isinstance(d, Allow)
    return ToolResult(status="DEFERRED", reason=d.rule, resume_at=d.until)


async def _guardrail_block(
    ctx: ToolContext, tool: str, key: str, args: dict[str, Any], reasons: list[str]
) -> ToolResult:
    step = await add_step(
        ctx.session,
        ctx.view.run,
        kind="guardrail",
        tool=tool,
        status="BLOCKED_BY_GUARDRAIL",
        idempotency_key=f"guardrail:{key}",
        epoch=ctx.epoch,
        task_id=ctx.task.id,
        plan_item_id=ctx.item["id"],
        input=args,
        summary="; ".join(reasons),
        actor="system",
    )
    await raise_attention(
        ctx.session,
        ctx.view.run,
        kind="guardrail_block",
        urgency="P1",
        summary=f"{ctx.item['title']} was not sent: {'; '.join(reasons)}",
        summary_public="A message was held for review",
        dedup_key=f"sr:{step.id}:guardrail_block",
        task_id=ctx.task.id,
        step_id=step.id,
        data={"item_id": ctx.item["id"], "draft": args, "reasons": reasons},
        options=[{"value": "skip", "label": "Discard"}, {"value": "retry", "label": "Redraft"}],
    )  # the executor commits this with the item's status
    return ToolResult(status="BLOCKED_BY_GUARDRAIL", reason="; ".join(reasons), step_id=step.id)


async def _write_pending(
    ctx: ToolContext,
    tool: str,
    key: str,
    args: dict[str, Any],
    r: Recipient,
    prior: AgentRunStep | None,
) -> AgentRunStep | ToolResult:
    """The outbox row, in one fenced transaction holding the contact point's cap lock."""
    session, run = ctx.session, ctx.view.run
    await fence(session, run.id, ctx.epoch)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:cp))"), {"cp": r.contact_point_id}
    )
    decision = await _decide(ctx, r)  # caps again, under the lock (its commit releases it)
    if not isinstance(decision, Allow):
        return await _not_allowed(ctx, tool, key, args, decision)
    if prior is not None:  # FAILED{not_sent}: reuse the key, record what this try sends
        prior.status, prior.lease_epoch, prior.error = "PENDING", ctx.epoch, None
        prior.input, prior.started_at, prior.ended_at = args, get_clock().now(), None
        step = prior
    else:
        step = await add_step(
            session,
            run,
            kind="tool",
            tool=tool,
            status="PENDING",
            idempotency_key=key,
            epoch=ctx.epoch,
            task_id=ctx.task.id,
            plan_item_id=ctx.item["id"],
            input=args,
            contact_point_id=r.contact_point_id,
        )
    await session.commit()
    return step


async def _killed(session: AsyncSession, run: AgentRun, epoch: int) -> bool:
    """The final fence, read fresh: a reclaimed lease raises; a kill switch, or a run that was
    ended or paused meanwhile (the sweep doesn't bump the epoch), stops the send."""
    row = (
        await session.execute(
            select(AgentRun.lease_epoch, AgentRun.status, CompiledAgentFirmMapping.kill_switch)
            .join(CompiledAgentFirmMapping, CompiledAgentFirmMapping.id == AgentRun.mapping_id)
            .where(AgentRun.id == run.id)
        )
    ).one()
    if row.lease_epoch != epoch:
        raise LeaseLost
    return bool(row.kill_switch) or row.status not in CLAIMABLE


async def _settle(session: AsyncSession, step: AgentRunStep, status: str, **fields: Any) -> None:
    await session.execute(
        update(AgentRunStep)
        .where(AgentRunStep.id == step.id, AgentRunStep.status == "PENDING")
        .values(status=status, ended_at=get_clock().now(), **fields)
    )
    await session.commit()
    await session.refresh(step)
