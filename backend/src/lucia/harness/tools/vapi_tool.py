"""`vapi.place_call` at runtime (CHANNELS_SPEC §5): outbound only. The model picks a contact on
the subject, never a number; the call result comes back as an end-of-call Episode."""

from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.connectors import vapi
from lucia.connectors.base import ConnectorError
from lucia.core.clock import get_clock
from lucia.db.models import (
    AgentRun,
    AgentRunStep,
    CompiledAgentFirmMapping,
    ConnectorConnection,
    Episode,
)
from lucia.db.models.run import CLAIMABLE
from lucia.harness.attention import raise_attention
from lucia.harness.exec.policy import Recipient
from lucia.harness.exec.recipients import contact_recipient
from lucia.harness.intake import EpisodeSpec, insert_episode
from lucia.harness.tools.base import ToolContext, ToolResult
from lucia.worker.dispatch import send

TOOL = "vapi.place_call"
RAILS = (
    "You are an AI assistant calling on behalf of a law firm; say so if asked. Never give "
    "legal or medical advice. If the person asks not to be called again, apologize, say you "
    "will note it, and end the call."
)
NOT_REACHED = {
    "customer-did-not-answer",
    "voicemail",
    "customer-busy",
    "silence-timed-out",
    "vapi_timeout",
}
STALE = timedelta(minutes=30)


async def _connection(session: AsyncSession, run: AgentRun) -> ConnectorConnection:
    mapping = await session.get_one(CompiledAgentFirmMapping, run.mapping_id)
    return await session.get_one(ConnectorConnection, mapping.identities["vapi"])


class VapiCall:
    async def recipient(self, ctx: ToolContext, args: dict[str, Any]) -> Recipient | None:
        return await contact_recipient(
            ctx.session, ctx.view.run, args.get("to_contact_id"), "voice"
        )

    def guard_text(self, args: dict[str, Any]) -> str:
        return f"First message: {args.get('first_message', '')}\nScript: {args.get('script', '')}"

    async def send(
        self,
        ctx: ToolContext,
        args: dict[str, Any],
        idem_key: str,
        recipient: Recipient,
        step: AgentRunStep,
    ) -> ToolResult:
        run = ctx.view.run
        conn = await _connection(ctx.session, run)
        metadata = {
            "firm_id": str(run.firm_id),
            "connection_id": str(conn.id),
            "run_id": str(run.id),
            "task_id": str(ctx.task.id),
            "plan_item_id": ctx.item["id"],
            "step_id": str(step.id),
            "idem_key": idem_key,
        }
        spec = vapi.assistant(
            args["first_message"],
            f"{args['script']}\n\n{RAILS}",
            metadata,
            args.get("max_seconds", 600),
        )
        call_id = await vapi.place_call(conn, recipient.address, spec)
        return ToolResult(
            status="AWAITING_CALLBACK", summary="Call placed", output={"call_id": call_id}
        )

    async def sent_lookup(
        self, session: AsyncSession, step: AgentRunStep
    ) -> Literal["found", "absent", "unknown"]:
        run = await session.get_one(AgentRun, step.run_id)
        conn = await _connection(session, run)
        since = (step.started_at or get_clock().now()) - timedelta(minutes=1)
        try:
            calls = await vapi.list_calls(conn.config["phone_number_id"], since.isoformat())
        except ConnectorError:
            return "unknown"
        found = any(_metadata(c).get("idem_key") == step.idempotency_key for c in calls)
        return "found" if found else "absent"


VAPI = VapiCall()


def _metadata(call: dict[str, Any]) -> dict[str, Any]:
    return (call.get("assistant") or {}).get("metadata") or call.get("metadata") or {}


async def ingest_report(
    session: AsyncSession, message: dict[str, Any], *, source: Literal["webhook", "poll"]
) -> Any:
    """An end-of-call report becomes the waiting task's external_response Episode."""
    call = message.get("call") or {}
    key, call_id = _metadata(call).get("idem_key"), str(call.get("id") or "")
    step = await session.scalar(
        select(AgentRunStep).where(
            AgentRunStep.tool == TOOL,
            (AgentRunStep.idempotency_key == key) | (AgentRunStep.external_ref == call_id),
        )
    )
    if step is None:
        return None
    run = await session.get_one(AgentRun, step.run_id)
    ended = str(message.get("endedReason") or call.get("endedReason") or "")
    episode_id = await insert_episode(
        session,
        run,
        EpisodeSpec(
            trigger_type="external_response",
            dedup_key=f"vapi:{call_id or step.external_ref or step.id}",
            task_id=step.task_id,
            metadata={
                "vapi_call_id": call_id,
                "step_id": str(step.id),
                "plan_item_id": step.plan_item_id,
                "ended_reason": ended,
                "reached": ended not in NOT_REACHED and "error" not in ended,
                "summary": message.get("summary")
                or (message.get("analysis") or {}).get("summary")
                or "",
                "transcript": message.get("transcript")
                or (message.get("artifact") or {}).get("transcript")
                or "",
                "source": source,
            },
        ),
    )
    await session.commit()
    if episode_id and run.status in CLAIMABLE:
        send("harness.advance_run", run.id)
    return episode_id


async def poll_stale(session: AsyncSession) -> int:
    """Calls with no end-of-call report after 30 minutes: ask Vapi, or give up (HLD §16)."""
    reported = exists().where(Episode.dedup_key == func.concat("vapi:", AgentRunStep.external_ref))
    steps = list(
        await session.scalars(
            select(AgentRunStep).where(
                AgentRunStep.tool == TOOL,
                AgentRunStep.status == "AWAITING_CALLBACK",
                AgentRunStep.started_at < get_clock().now() - STALE,
                ~reported,
            )
        )
    )
    for step in steps:
        try:
            call = await vapi.get_call(step.external_ref or "")
        except vapi.UnknownId:
            call = {
                "id": step.external_ref,
                "endedReason": "vapi_timeout",
                "assistant": {"metadata": {"idem_key": step.idempotency_key}},
            }
            run = await session.get_one(AgentRun, step.run_id)
            await raise_attention(
                session,
                run,
                kind="escalation",
                summary="A call never reported back; check the Vapi call log",
                dedup_key=f"sr:{step.id}:no_callback",
                task_id=step.task_id,
                step_id=step.id,
                data={"source": "no_callback", "item_id": step.plan_item_id},
            )
        except ConnectorError:
            continue
        if call.get("status", "ended") != "ended":
            continue
        # A call carries the report's fields (endedReason, summary, transcript, artifact).
        await ingest_report(session, {**call, "call": call}, source="poll")
    return len(steps)
