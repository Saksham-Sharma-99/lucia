"""The inline content check before anything leaves the firm (RUNTIME_SPEC §8.5): fixed
patterns first, then a small model. A block is never retried automatically (HLD ADR-4)."""

import re

from pydantic import BaseModel

from lucia.harness.steps import call_llm
from lucia.harness.tools.base import ToolContext

_NEVER_SEND = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "contains a Social Security number"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "contains a card number"),
]
INSTRUCTIONS = """You check a message or call script before an AI agent sends it on behalf of a
law firm. Fail it if it gives legal or medical advice, shares clinical details the task
doesn't need, is addressed to the wrong person, or tells the callee anything against the
firm's policies. Recapping to a client, after they confirm who they are, what they told the
firm themselves is needed for a check-in. Otherwise pass it."""


class GuardrailVerdict(BaseModel):
    ok: bool
    reasons: list[str]


async def check(ctx: ToolContext, text: str, recipient_role: str) -> GuardrailVerdict:
    hits = [why for pattern, why in _NEVER_SEND if pattern.search(text)]
    if hits:
        return GuardrailVerdict(ok=False, reasons=hits)
    return await call_llm(
        ctx.session,
        ctx.view.run,
        role="guardrail",
        model=ctx.view.config.models.guardrail,
        instructions=INSTRUCTIONS,
        message=f"## recipient role\n{recipient_role}\n\n## text\n{text}",
        output_type=GuardrailVerdict,
        epoch=ctx.epoch,
        task_id=ctx.task.id,
        plan_item_id=ctx.item["id"],
    )
