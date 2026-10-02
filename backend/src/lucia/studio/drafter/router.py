from collections.abc import AsyncIterable
from typing import Annotated, Any

from fastapi import Depends
from fastapi.sse import EventSourceResponse

from lucia.api.tags import api_router
from lucia.auth.deps import DbSession
from lucia.core.errors import Problem
from lucia.registry.snapshot import RegistrySnapshot, load_snapshot
from lucia.studio.drafter import schemas as s
from lucia.studio.drafter import service
from lucia.studio.drafter.llm import Drafter, get_drafter

DRAFTER_ERRORS: dict[int | str, dict[str, Any]] = {
    502: {"model": Problem, "description": "The model provider failed"},
    503: {"model": Problem, "description": "AI drafting isn't configured"},
    504: {"model": Problem, "description": "The drafter timed out"},
}


async def _registry(session: DbSession) -> RegistrySnapshot:
    """The registry the form validates against. Then the session's connection goes back to the
    pool, so a long model call never holds one (auth and this are the only DB reads)."""
    snap = await load_snapshot(session)
    await session.close()
    return snap


router = api_router("drafts", "/agents/drafts")
Registry = Annotated[RegistrySnapshot, Depends(_registry)]
DrafterDep = Annotated[Drafter, Depends(get_drafter)]


@router.post(
    "/prompt",
    response_class=EventSourceResponse,
    summary="Stream a drafted or refined system prompt",
    operation_id="draftAgentPrompt",
    responses=DRAFTER_ERRORS,
)
async def draft_prompt(
    body: s.PromptDraftRequest, snap: Registry, drafter: DrafterDep
) -> AsyncIterable[s.PromptEvent]:
    async for event in service.draft_prompt(body, snap, drafter):
        yield event


@router.post(
    "/section",
    summary="Draft one config section from the system prompt",
    operation_id="draftAgentSection",
    responses=DRAFTER_ERRORS,
)
async def draft_section(
    body: s.SectionDraftRequest, snap: Registry, drafter: DrafterDep
) -> s.SectionDraft:
    return await service.draft_section(body, snap, drafter)
