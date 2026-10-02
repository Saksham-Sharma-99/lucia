"""A fake outboxed voice tool for ToolExecutor tests."""

from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import AgentRunStep
from lucia.harness.exec.policy import Recipient
from lucia.harness.exec.recipients import contact_recipient
from lucia.harness.tools.base import ToolContext, ToolResult


class FakeCall:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.lookup: Literal["found", "absent", "unknown"] = "absent"
        self.fail = False

    async def recipient(self, ctx: ToolContext, args: dict[str, Any]) -> Recipient | None:
        return await contact_recipient(
            ctx.session, ctx.view.run, args.get("to_contact_id"), "voice"
        )

    def guard_text(self, args: dict[str, Any]) -> str:
        return f"{args.get('first_message', '')}\n{args.get('script', '')}"

    async def send(
        self,
        ctx: ToolContext,
        args: dict[str, Any],
        idem_key: str,
        recipient: Recipient,
        step: AgentRunStep,
    ) -> ToolResult:
        if self.fail:
            from lucia.connectors.base import ConnectorError

            raise ConnectorError("Vapi error 500")
        self.sent.append(idem_key)
        return ToolResult(
            status="AWAITING_CALLBACK",
            summary="Call placed",
            output={"call_id": f"call-{len(self.sent)}"},
        )

    async def sent_lookup(
        self, session: AsyncSession, step: AgentRunStep
    ) -> Literal["found", "absent", "unknown"]:
        return self.lookup
