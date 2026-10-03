from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.errors import FieldError, conflict, invalid
from lucia.core.pagination import Page, PageParams, paginate
from lucia.db.models import CompiledAgentFirmMapping, ConnectorConnection, Firm
from lucia.db.models.firm import FirmStatus
from lucia.db.queries import apply_patch, like_pattern, unique_or
from lucia.firms import schemas as s
from lucia.registry.snapshot import load_snapshot
from lucia.studio.validator import validate_policy_refs

M = CompiledAgentFirmMapping
SLUG_TAKEN = invalid([FieldError(path="/slug", code="taken", message="Slug is taken")])


async def _settings_json(session: AsyncSession, settings: s.FirmSettings) -> dict[str, Any]:
    snap = await load_snapshot(session)
    if errors := validate_policy_refs(settings.policy_floor, snap, "/settings/policy_floor"):
        raise invalid(errors)
    return settings.model_dump(mode="json")


async def list_firms(
    session: AsyncSession, paging: PageParams, q: str | None, status: FirmStatus | None
) -> Page[s.FirmOut]:
    stmt = select(Firm).order_by(Firm.name, Firm.id)
    if q:
        like = like_pattern(q)
        stmt = stmt.where(Firm.name.ilike(like, escape="\\") | Firm.slug.ilike(like, escape="\\"))
    if status:
        stmt = stmt.where(Firm.status == status)
    return await paginate(session, stmt, paging, s.FirmOut.model_validate)


async def firm_detail(session: AsyncSession, firm: Firm) -> s.FirmDetail:
    C = ConnectorConnection
    conns = await session.execute(
        select(C.connector, func.count()).where(C.firm_id == firm.id).group_by(C.connector)
    )
    maps = await session.execute(
        select(M.status, func.count()).where(M.firm_id == firm.id).group_by(M.status)
    )
    return s.FirmDetail(
        **s.FirmOut.model_validate(firm).model_dump(),
        connection_counts=dict(conns.all()),
        mapping_counts={"active": 0, "inactive": 0} | dict(maps.all()),
    )


async def create_firm(session: AsyncSession, body: s.FirmCreate) -> Firm:
    firm = Firm(
        **body.model_dump(exclude={"settings"}),
        settings=await _settings_json(session, body.settings),
    )
    session.add(firm)
    async with unique_or(session, "firms_slug_key", SLUG_TAKEN):
        await session.flush()
    await session.commit()
    return firm


async def patch_firm(session: AsyncSession, firm: Firm, body: s.FirmPatch) -> Firm:
    apply_patch(firm, body, exclude={"settings"})
    if body.settings is not None:
        firm.settings = await _settings_json(session, body.settings)
    await session.commit()
    return firm


async def set_status(session: AsyncSession, firm: Firm, status: FirmStatus) -> Firm:
    """Deactivating a firm also deactivates its mappings; activating does not restore them."""
    if firm.status == status:
        raise conflict(f"Firm is already {status}")
    firm.status = status
    if status == "inactive":
        await session.execute(
            update(M).where(M.firm_id == firm.id, M.status == "active").values(status="inactive")
        )
    await session.commit()
    return firm
