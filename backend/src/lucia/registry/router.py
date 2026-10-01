from typing import Any

from pydantic import computed_field
from sqlalchemy import select

from lucia.api.tags import api_router
from lucia.auth.deps import DbSession
from lucia.core.schema import Read
from lucia.db.models import RegistryEntry
from lucia.db.models.registry import Kind
from lucia.registry.catalog import CHANNEL_TOOLS, CONNECTOR_SETUP

router = api_router("registry", "/registry")


class RegistryEntryOut(Read):
    kind: Kind
    name: str
    connector: str | None
    display_name: str
    description: str
    params_schema: dict[str, Any]
    risk_tier: str | None
    direction: str | None
    is_async: bool
    available: bool
    version: int

    @computed_field
    @property
    def channel_tool(self) -> str | None:
        return CHANNEL_TOOLS.get(self.name) if self.kind == "channel" else None


class ConnectorOut(RegistryEntryOut):
    setup: str
    tools: list[RegistryEntryOut]


@router.get("", summary="List registry entries", operation_id="listRegistry")
async def list_registry(
    session: DbSession, kind: Kind | None = None, connector: str | None = None
) -> list[RegistryEntryOut]:
    stmt = select(RegistryEntry).order_by(RegistryEntry.kind, RegistryEntry.name)
    if kind:
        stmt = stmt.where(RegistryEntry.kind == kind)
    if connector:
        stmt = stmt.where(RegistryEntry.connector == connector)
    return [RegistryEntryOut.model_validate(e) for e in await session.scalars(stmt)]


@router.get(
    "/connectors", summary="Connectors with their tools", operation_id="listRegistryConnectors"
)
async def list_connectors(session: DbSession) -> list[ConnectorOut]:
    entries = [
        RegistryEntryOut.model_validate(e)
        for e in await session.scalars(
            select(RegistryEntry)
            .where(RegistryEntry.kind.in_(["connector", "tool"]))
            .order_by(RegistryEntry.name)
        )
    ]
    return [
        ConnectorOut(
            **c.model_dump(exclude={"channel_tool"}),
            setup=CONNECTOR_SETUP.get(c.name, "none"),
            tools=[t for t in entries if t.kind == "tool" and t.connector == c.name],
        )
        for c in entries
        if c.kind == "connector"
    ]
