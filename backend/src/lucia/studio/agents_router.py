from typing import Annotated

from fastapi import Query, status

from lucia.api.tags import api_router
from lucia.auth.deps import CurrentUser, DbSession
from lucia.core.pagination import Page, Paging
from lucia.db.models.agent import VersionStatus
from lucia.studio import schemas as s
from lucia.studio import service

router = api_router("agents", "/agents")


@router.get("", summary="List agents", operation_id="listAgents")
async def list_agents(
    session: DbSession,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: VersionStatus | None = None,
    is_template: bool = False,
    sort: Annotated[str, Query(pattern=f"^({'|'.join(service.SORTS)})$")] = "-updated_at",
) -> Page[s.AgentListItem]:
    return await service.list_agents(session, paging, q, status, is_template, sort)


@router.post(
    "/validate",
    summary="Validate a version config against the registry",
    operation_id="validateAgentConfig",
)
async def validate_config(body: s.ValidateRequest, session: DbSession) -> s.ValidateResult:
    await service.check_config(session, body.config)
    return s.ValidateResult()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create an agent and its v1",
    operation_id="createAgent",
)
async def create_agent(body: s.AgentCreate, session: DbSession, user: CurrentUser) -> s.AgentDetail:
    agent = await service.create_agent(session, body, user)
    return await service.agent_detail(session, agent)


@router.get("/{handle}", summary="Get an agent with its versions", operation_id="getAgent")
async def get_agent(handle: str, session: DbSession) -> s.AgentDetail:
    return await service.agent_detail(session, await service.get_agent(session, handle))


@router.patch(
    "/{handle}", summary="Update agent metadata (no new version)", operation_id="updateAgent"
)
async def patch_agent(handle: str, body: s.AgentPatch, session: DbSession) -> s.AgentDetail:
    agent = await service.patch_agent(session, await service.get_agent(session, handle), body)
    return await service.agent_detail(session, agent)


@router.post(
    "/{handle}/archive",
    summary="Archive every version and deactivate its mappings",
    operation_id="archiveAgent",
)
async def archive_agent(handle: str, session: DbSession) -> s.ArchiveResult:
    agent = await service.get_agent(session, handle)
    ids = await service.archive_agent(session, agent)
    return s.ArchiveResult(
        agent=await service.agent_detail(session, agent), deactivated_mapping_ids=ids
    )


@router.post(
    "/{handle}/unarchive",
    summary="Reactivate the latest version",
    operation_id="unarchiveAgent",
)
async def unarchive_agent(handle: str, session: DbSession) -> s.AgentDetail:
    agent = await service.get_agent(session, handle)
    await service.unarchive_agent(session, agent)
    return await service.agent_detail(session, agent)


@router.post(
    "/{handle}/duplicate",
    status_code=status.HTTP_201_CREATED,
    summary="Copy an agent's latest active version into a new agent",
    operation_id="duplicateAgent",
)
async def duplicate_agent(
    handle: str, body: s.AgentDuplicate, session: DbSession, user: CurrentUser
) -> s.AgentDetail:
    source = await service.get_agent(session, handle)
    agent = await service.duplicate_agent(session, source, body, user)
    return await service.agent_detail(session, agent)
