"""What every runtime tool implementation receives and returns."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import AgentRunStep, RunTask
from lucia.harness.agent_view import AgentView
from lucia.harness.exec.policy import Recipient

ToolStatus = Literal[
    "SUCCEEDED",
    "AWAITING_CALLBACK",
    "DEFERRED",
    "BLOCKED_BY_POLICY",
    "BLOCKED_BY_GUARDRAIL",
    "FAILED",
    "NEEDS_HUMAN",  # subagent: the reviewer kept failing the draft
    "SKIPPED",  # subagent: the work is outside the agent's scope
]


class ToolResult(BaseModel):
    status: ToolStatus
    summary: str = ""
    output: dict[str, Any] = {}
    step_id: uuid.UUID | None = None
    retryable: bool = False
    resume_at: datetime | None = None
    reason: str | None = None


@dataclass
class ToolContext:
    session: AsyncSession
    view: AgentView
    task: RunTask
    item: dict[str, Any]
    epoch: int

    def key(self, tool: str, recipient: str = "-") -> str:
        """The idempotency key of this attempt's send: the same for a resumed attempt, new for a
        deliberate retry (the attempt number moves)."""
        parts = (self.view.run.id, self.task.id, self.item["id"], tool, recipient.lower())
        raw = "|".join(map(str, (*parts, self.item["attempts"])))
        return hashlib.sha256(raw.encode()).hexdigest()


class ToolImpl(Protocol):
    async def __call__(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult: ...


class Outboxed(Protocol):
    """A tool that reaches a person outside the firm: policy, guardrail, outbox (§8.2)."""

    async def recipient(self, ctx: ToolContext, args: dict[str, Any]) -> Recipient | None: ...

    def guard_text(self, args: dict[str, Any]) -> str: ...

    async def send(
        self,
        ctx: ToolContext,
        args: dict[str, Any],
        idem_key: str,
        recipient: Recipient,
        step: AgentRunStep,
    ) -> ToolResult: ...

    async def sent_lookup(
        self, session: AsyncSession, step: AgentRunStep
    ) -> Literal["found", "absent", "unknown"]: ...
