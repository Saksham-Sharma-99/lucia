import uuid
from typing import Annotated

from fastapi import Query, status

from lucia.api.tags import api_router
from lucia.auth.deps import CurrentUser, DbSession
from lucia.core.pagination import Page, Paging
from lucia.db.models import Firm
from lucia.db.models.firm import FirmStatus
from lucia.db.queries import get_or_404
from lucia.firms import schemas as s
from lucia.firms import service

router = api_router("firms", "/firms")


@router.get("", summary="List firms", operation_id="listFirms")
async def list_firms(
    session: DbSession,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: FirmStatus | None = None,
) -> Page[s.FirmOut]:
    return await service.list_firms(session, paging, q, status)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a firm (and its inactive @orchestrator mapping)",
    operation_id="createFirm",
)
async def create_firm(body: s.FirmCreate, session: DbSession, user: CurrentUser) -> s.FirmDetail:
    return await service.firm_detail(session, await service.create_firm(session, body, user))


@router.get("/{firm_id}", summary="Get a firm with counts", operation_id="getFirm")
async def get_firm(firm_id: uuid.UUID, session: DbSession) -> s.FirmDetail:
    return await service.firm_detail(session, await get_or_404(session, Firm, firm_id, "Firm"))


@router.patch("/{firm_id}", summary="Update a firm", operation_id="updateFirm")
async def patch_firm(firm_id: uuid.UUID, body: s.FirmPatch, session: DbSession) -> s.FirmDetail:
    firm = await get_or_404(session, Firm, firm_id, "Firm")
    return await service.firm_detail(session, await service.patch_firm(session, firm, body))


@router.post(
    "/{firm_id}/deactivate",
    summary="Deactivate a firm and its mappings",
    operation_id="deactivateFirm",
)
async def deactivate_firm(firm_id: uuid.UUID, session: DbSession) -> s.FirmDetail:
    firm = await get_or_404(session, Firm, firm_id, "Firm")
    return await service.firm_detail(session, await service.set_status(session, firm, "inactive"))


@router.post("/{firm_id}/activate", summary="Activate a firm", operation_id="activateFirm")
async def activate_firm(firm_id: uuid.UUID, session: DbSession) -> s.FirmDetail:
    firm = await get_or_404(session, Firm, firm_id, "Firm")
    return await service.firm_detail(session, await service.set_status(session, firm, "active"))
