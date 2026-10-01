"""Draft a system prompt (streamed) or one config section. Stateless: nothing is stored, and
logs carry only the mode or section and timing, never prompt text."""

import logging
import time
from collections.abc import AsyncIterator

from lucia.core.schema import PolicyRuleRef
from lucia.registry.snapshot import RegistrySnapshot
from lucia.studio.config_schema import MAX_PROMPT
from lucia.studio.drafter import schemas as s
from lucia.studio.drafter.llm import Drafter, DrafterError
from lucia.studio.drafter.outputs import output_model
from lucia.studio.drafter.prompts import as_input, instructions
from lucia.studio.validator import MIN_PACK_RULE, contacts_outside

PROMPT_SECONDS = 90.0
SECTION_SECONDS = 45.0

log = logging.getLogger(__name__)


async def draft_prompt(
    req: s.PromptDraftRequest, snap: RegistrySnapshot, drafter: Drafter
) -> AsyncIterator[s.PromptEvent]:
    """Deltas, then `done` with the whole prompt. A failure after the stream has started is an
    `error` event, since the status code is already sent."""
    started = time.monotonic()
    message = as_input(
        instruction=req.instruction,
        basic=req.basic.model_dump(exclude_defaults=True),
        current_prompt=req.current_prompt,
        context=req.context.model_dump(exclude_none=True) if req.context else None,
    )
    parts: list[str] = []
    try:
        async for delta in drafter.stream_text(
            instructions("prompt", snap), message, PROMPT_SECONDS
        ):
            parts.append(delta)
            yield s.PromptDelta(text=delta)
    except DrafterError as e:
        yield s.PromptFailed(code=e.code, message=e.problem.detail or e.problem.title)
        return
    prompt = "".join(parts).strip()
    mode = "refine" if req.current_prompt else "draft"
    log.info("draft prompt mode=%s ms=%d", mode, (time.monotonic() - started) * 1000)
    if not prompt:
        yield s.PromptFailed(code="empty", message="The drafter returned nothing. Try again.")
    elif len(prompt) > MAX_PROMPT:
        yield s.PromptFailed(code="too_long", message="The draft is too long. Ask for less.")
    else:
        yield s.PromptDone(prompt=prompt)


def _with_min_pack(draft: s.PoliciesDraft) -> s.PoliciesDraft:
    """An agent that contacts people outside the firm always carries the platform's min rule."""
    if any(r.rule == MIN_PACK_RULE for r in draft.policy_pack):
        return draft
    pack = [PolicyRuleRef(rule=MIN_PACK_RULE), *draft.policy_pack]
    return draft.model_copy(update={"policy_pack": pack})


async def draft_section(
    req: s.SectionDraftRequest, snap: RegistrySnapshot, drafter: Drafter
) -> s.SectionDraft:
    started = time.monotonic()
    tools = [t for cap in req.upstream.capabilities or [] for t in cap.tools]
    message = as_input(
        system_prompt=req.system_prompt,
        basic=req.basic.model_dump(exclude_defaults=True),
        upstream=req.upstream.model_dump(exclude_none=True),
    )
    out = await drafter.run_structured(
        instructions(req.section, snap),
        message,
        output_model(req.section, snap, tools),
        SECTION_SECONDS,
    )
    log.info("draft section=%s ms=%d", req.section, (time.monotonic() - started) * 1000)
    draft = out.to_draft()
    if isinstance(draft, s.PoliciesDraft) and contacts_outside(tools, snap):
        return _with_min_pack(draft)
    return draft
