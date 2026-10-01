from fastapi import status

from lucia.api.tags import api_router
from lucia.auth.deps import CurrentUser, DbSession
from lucia.studio import schemas as s
from lucia.studio import service
from lucia.studio.diff import DiffEntry, diff

router = api_router("agents", "/agents/{handle}/versions")


@router.get("", summary="List an agent's versions", operation_id="listAgentVersions")
async def list_versions(handle: str, session: DbSession) -> list[s.VersionSummary]:
    return (await service.agent_detail(session, await service.get_agent(session, handle))).versions


@router.get("/{n}", summary="Get one version with its config", operation_id="getAgentVersion")
async def get_version(handle: str, n: int, session: DbSession) -> s.VersionDetail:
    agent = await service.get_agent(session, handle)
    return await service.version_detail(session, await service.get_version(session, agent, n))


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Amend: save a new immutable version",
    operation_id="createAgentVersion",
)
async def amend(
    handle: str, body: s.VersionCreate, session: DbSession, user: CurrentUser
) -> s.VersionDetail:
    return await service.version_detail(session, await service.amend(session, handle, body, user))


@router.post("/{n}/archive", summary="Archive a version", operation_id="archiveAgentVersion")
async def archive_version(handle: str, n: int, session: DbSession) -> s.VersionDetail:
    v = await service.get_version(session, await service.get_agent(session, handle), n)
    await service.set_version_status(session, v, "archived")
    return await service.version_detail(session, v)


@router.post("/{n}/unarchive", summary="Reactivate a version", operation_id="unarchiveAgentVersion")
async def unarchive_version(handle: str, n: int, session: DbSession) -> s.VersionDetail:
    v = await service.get_version(session, await service.get_agent(session, handle), n)
    await service.set_version_status(session, v, "active")
    return await service.version_detail(session, v)


@router.get(
    "/{a}/diff/{b}", summary="Structural diff of two versions", operation_id="diffAgentVersions"
)
async def diff_versions(handle: str, a: int, b: int, session: DbSession) -> list[DiffEntry]:
    agent = await service.get_agent(session, handle)
    va, vb = (
        await service.get_version(session, agent, a),
        await service.get_version(session, agent, b),
    )
    return diff(va.config, vb.config)
