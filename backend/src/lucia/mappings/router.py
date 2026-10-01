import uuid
from typing import Annotated

from fastapi import Query, status

from lucia.api.tags import api_router
from lucia.auth.deps import CurrentUser, DbSession
from lucia.core.pagination import Page, Paging
from lucia.db.models import CompiledAgentFirmMapping
from lucia.db.models.mapping import MappingStatus
from lucia.db.queries import get_or_404
from lucia.mappings import schemas as s
from lucia.mappings import service

router = api_router("mappings", "/mappings")


async def _get(session: DbSession, mapping_id: uuid.UUID) -> CompiledAgentFirmMapping:
    return await get_or_404(session, CompiledAgentFirmMapping, mapping_id, "Mapping")


async def _out(session: DbSession, mapping: CompiledAgentFirmMapping) -> s.MappingOut:
    return (await service.to_out(session, [mapping]))[0]


@router.get("", summary="List firm mappings", operation_id="listMappings")
async def list_mappings(
    session: DbSession,
    paging: Paging,
    firm_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    status: MappingStatus | None = None,
) -> Page[s.MappingOut]:
    return await service.list_mappings(session, paging, firm_id, agent_id, status)


@router.get(
    "/checklist",
    summary="Activation checklist for a firm, version and identities",
    operation_id="getMappingChecklist",
)
async def get_checklist(
    session: DbSession,
    firm_id: uuid.UUID,
    agent_prompt_id: uuid.UUID,
    identities: Annotated[
        list[str], Query(description="connector:connection_id pairs, e.g. gmail:<uuid>")
    ] = [],  # noqa: B006 - FastAPI copies query defaults
) -> list[s.ChecklistItem]:
    return await service.checklist(session, firm_id, agent_prompt_id, identities)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Map an agent version to a firm",
    operation_id="createMapping",
)
async def create_mapping(
    body: s.MappingCreate, session: DbSession, user: CurrentUser
) -> s.MappingOut:
    return await _out(session, await service.create(session, body, user))


@router.get("/{mapping_id}", summary="Get a mapping", operation_id="getMapping")
async def get_mapping(mapping_id: uuid.UUID, session: DbSession) -> s.MappingOut:
    return await _out(session, await _get(session, mapping_id))


@router.patch("/{mapping_id}", summary="Update a mapping", operation_id="updateMapping")
async def patch_mapping(
    mapping_id: uuid.UUID, body: s.MappingPatch, session: DbSession
) -> s.MappingOut:
    return await _out(session, await service.patch(session, await _get(session, mapping_id), body))


@router.post(
    "/{mapping_id}/switch-version",
    status_code=status.HTTP_201_CREATED,
    summary="Move a mapping to another version (creates a superseding row)",
    description="The old row becomes inactive. The new row is active only if the old one was "
    "active and the new version's checklist passes; otherwise it is created inactive and its "
    "`checklist_missing` says what to bind before activating.",
    operation_id="switchMappingVersion",
)
async def switch_version(
    mapping_id: uuid.UUID, body: s.SwitchVersion, session: DbSession, user: CurrentUser
) -> s.MappingOut:
    old = await _get(session, mapping_id)
    return await _out(session, await service.switch_version(session, old, body, user))
