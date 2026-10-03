"""Every executed action is an AgentRunStep; every LLM call is one too, with its usage
(RUNTIME_SPEC §10.2). Logs are redacted before they are stored."""

import uuid
from datetime import timedelta
from typing import Any, overload

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.core.redact import redact
from lucia.db.models import AgentRun, AgentRunStep, RunStepLog
from lucia.harness.lease import RENEW_BELOW, ensure_lease
from lucia.llm.client import LLMError, get_llm

# Planner calls on the flagship model take up to ~30 s, so the 30 s default timed out. Each call
# starts with about RENEW_BELOW of lease left (claim, then ensure_lease after every call); the
# margin covers the work between calls, so a call never outlives the lease.
MODEL_SECONDS = (RENEW_BELOW - timedelta(seconds=5)).total_seconds()


async def add_step(
    session: AsyncSession,
    run: AgentRun,
    *,
    kind: str,
    status: str,
    idempotency_key: str,
    epoch: int,
    **fields: Any,
) -> AgentRunStep:
    """Adds a step with the run's next sequence number; the caller commits."""
    seq = await session.scalar(
        select(func.coalesce(func.max(AgentRunStep.seq), 0) + 1).where(
            AgentRunStep.run_id == run.id
        )
    )
    step = AgentRunStep(
        firm_id=run.firm_id,
        run_id=run.id,
        seq=seq,
        kind=kind,
        status=status,
        idempotency_key=idempotency_key,
        lease_epoch=epoch,
        actor=fields.pop("actor", "agent"),
        started_at=fields.pop("started_at", get_clock().now()),
        **fields,
    )
    session.add(step)
    run.step_count += 1
    await session.flush()
    return step


async def log(
    session: AsyncSession,
    run: AgentRun,
    *,
    stage: str,
    message: str,
    level: str = "info",
    task_id: uuid.UUID | None = None,
    step_id: uuid.UUID | None = None,
) -> None:
    session.add(
        RunStepLog(
            firm_id=run.firm_id,
            run_id=run.id,
            task_id=task_id,
            step_id=step_id,
            level=level,
            stage=stage,
            message=redact(message),
            at=get_clock().now(),
        )
    )


@overload
async def call_llm[T: BaseModel](
    session: AsyncSession,
    run: AgentRun,
    *,
    role: str,
    model: str,
    instructions: str,
    message: str,
    epoch: int,
    output_type: type[T],
    **links: Any,
) -> T: ...
@overload
async def call_llm(
    session: AsyncSession,
    run: AgentRun,
    *,
    role: str,
    model: str,
    instructions: str,
    message: str,
    epoch: int,
    tool: tuple[str, dict[str, Any]],
    **links: Any,
) -> dict[str, Any]: ...
@overload
async def call_llm(
    session: AsyncSession,
    run: AgentRun,
    *,
    role: str,
    model: str,
    instructions: str,
    message: str,
    epoch: int,
    **links: Any,
) -> str: ...
async def call_llm(
    session: AsyncSession,
    run: AgentRun,
    *,
    role: str,
    model: str,
    instructions: str,
    message: str,
    epoch: int,
    output_type: type[BaseModel] | None = None,
    tool: tuple[str, dict[str, Any]] | None = None,
    fenced: bool = True,
    **links: Any,
) -> Any:
    """One model call: structured (`output_type`), a forced tool call (`tool`) or text.
    `links` are step columns (task_id, episode_id, plan_item_id, parent_step_id).

    Every unit's model calls go through here, so here a unit learns it lost the run while the
    model thought: a takeover, kill switch or end since the call began raises LeaseLost before
    the caller writes (`fenced`; work outside a lease, like journal compaction, opts out)."""
    llm = get_llm()
    try:
        if output_type is not None:
            out, usage = await llm.structured(
                role=role,
                model=model,
                instructions=instructions,
                message=message,
                output_type=output_type,
                seconds=MODEL_SECONDS,
            )
            recorded: dict[str, Any] = out.model_dump(mode="json")
        elif tool is not None:
            out, usage = await llm.tool_call(
                role=role,
                model=model,
                instructions=instructions,
                message=message,
                tool_name=tool[0],
                tool_schema=tool[1],
                seconds=MODEL_SECONDS,
            )
            recorded = out
        else:
            out, usage = await llm.text(
                role=role,
                model=model,
                instructions=instructions,
                message=message,
                seconds=MODEL_SECONDS,
            )
            recorded = {"text": out}
    except LLMError as e:
        await add_step(
            session,
            run,
            kind="llm",
            role=role,
            model=model,
            status="FAILED",
            idempotency_key=f"llm:{uuid.uuid4()}",
            epoch=epoch,
            input={"message": message},
            error={
                "class": "retryable" if e.retryable else "fatal",
                "reason": "llm_error",
                "detail": str(e),
            },
            **links,
        )
        raise  # the caller decides: keep the step with its own work, or roll both back
    step = await add_step(
        session,
        run,
        kind="llm",
        role=role,
        status="SUCCEEDED",
        idempotency_key=f"llm:{uuid.uuid4()}",
        epoch=epoch,
        input={"message": message},
        output=recorded,
        model=usage.model,
        latency_ms=usage.latency_ms,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost=usage.cost,
        ended_at=get_clock().now(),
        **links,
    )
    await log(
        session,
        run,
        stage=role,
        message=f"LLM {role} via {usage.model} ({usage.latency_ms} ms)",
        level="debug",
        task_id=links.get("task_id"),
        step_id=step.id,
    )
    if fenced:
        await ensure_lease(session, run.id, epoch)
    return out


async def settle_callback(session: AsyncSession, report: dict[str, Any]) -> None:
    """An async tool's step finishes when its report arrives (late reports included)."""
    if step_id := report.get("step_id"):
        step = await session.get_one(AgentRunStep, uuid.UUID(step_id))
        if step.status in ("AWAITING_CALLBACK", "FAILED"):
            step.status, step.ended_at = "SUCCEEDED", get_clock().now()
            step.output = {
                **step.output,
                "summary": report.get("summary"),
                "ended_reason": report.get("ended_reason"),
                "transcript": report.get("transcript"),
            }
