import uuid
from typing import Any

from fastapi import Response, status

from lucia.api.tags import api_router
from lucia.auth.deps import DbSession
from lucia.connectors import schemas as s
from lucia.connectors import service
from lucia.db.models import ConnectorConnection
from lucia.db.queries import get_or_404

router = api_router("connections")
BAD_GATEWAY: dict[int | str, dict[str, Any]] = {
    502: {"description": "The provider rejected the request"}
}


async def _get(session: DbSession, conn_id: uuid.UUID) -> ConnectorConnection:
    return await get_or_404(session, ConnectorConnection, conn_id, "Connection")


@router.get(
    "/firms/{firm_id}/connections",
    summary="List a firm's connections (never returns secrets)",
    operation_id="listConnections",
)
async def list_connections(firm_id: uuid.UUID, session: DbSession) -> list[s.ConnectionOut]:
    return [service.connection_out(c) for c in await service.list_for_firm(session, firm_id)]


@router.post(
    "/firms/{firm_id}/connections",
    status_code=status.HTTP_201_CREATED,
    summary="Add a connection (Vapi is provisioned immediately)",
    operation_id="createConnection",
    responses=BAD_GATEWAY,
)
async def create_connection(
    firm_id: uuid.UUID, body: s.ConnectionCreate, session: DbSession
) -> s.ConnectionOut:
    return service.connection_out(await service.create(session, firm_id, body))


@router.get("/connections/{conn_id}", summary="Get a connection", operation_id="getConnection")
async def get_connection(conn_id: uuid.UUID, session: DbSession) -> s.ConnectionOut:
    return service.connection_out(await _get(session, conn_id))


@router.patch(
    "/connections/{conn_id}",
    summary="Update label, non-secret config or replace secrets",
    operation_id="updateConnection",
)
async def patch_connection(
    conn_id: uuid.UUID, body: s.ConnectionPatch, session: DbSession
) -> s.ConnectionOut:
    c = await service.patch(session, await _get(session, conn_id), body)
    return service.connection_out(c)


@router.delete(
    "/connections/{conn_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a connection no mapping uses",
    operation_id="deleteConnection",
)
async def delete_connection(conn_id: uuid.UUID, session: DbSession) -> Response:
    await service.delete(session, await _get(session, conn_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/connections/{conn_id}/consent-link",
    summary="Generate a consent/install link (invalidates earlier links)",
    operation_id="createConsentLink",
)
async def create_consent_link(conn_id: uuid.UUID, session: DbSession) -> s.ConsentLink:
    return s.ConsentLink(url=await service.consent_link(session, await _get(session, conn_id)))


@router.post(
    "/connections/{conn_id}/test",
    summary="Test auth, or one tool with an explicit target",
    operation_id="testConnection",
)
async def test_connection(
    conn_id: uuid.UUID, body: s.TestRequest, session: DbSession
) -> s.TestOutcome:
    return await service.test(session, await _get(session, conn_id), body)


@router.post(
    "/connections/{conn_id}/inbound/enable",
    summary="Enable inbound events and return the webhook URL",
    operation_id="enableConnectionInbound",
    responses=BAD_GATEWAY,
)
async def enable_inbound(conn_id: uuid.UUID, session: DbSession) -> s.InboundSetup:
    return await service.enable_inbound(session, await _get(session, conn_id))
