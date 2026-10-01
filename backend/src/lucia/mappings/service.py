import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.errors import conflict, invalid
from lucia.core.pagination import Page, PageParams, fetch_page
from lucia.db.models import (
    Agent,
    AgentPrompt,
    AppUser,
    CompiledAgentFirmMapping,
    ConnectorConnection,
    Firm,
)
from lucia.db.models.mapping import ONE_ACTIVE_INDEX, MappingStatus
from lucia.db.queries import apply_patch, get_or_404, unique_or
from lucia.mappings import resolve
from lucia.mappings import schemas as s
from lucia.mappings.checklist import build_checklist
from lucia.mappings.tighten import check_overrides
from lucia.registry.snapshot import load_snapshot

M = CompiledAgentFirmMapping
V = AgentPrompt
ONE_ACTIVE = "Another active mapping exists for this agent at this firm. Use switch-version."


async def _connections(session: AsyncSession, ids: set[str]) -> dict[str, ConnectorConnection]:
    if not ids:
        return {}
    C = ConnectorConnection
    rows = await session.scalars(select(C).where(C.id.in_([uuid.UUID(i) for i in ids])))
    return {str(c.id): c for c in rows}


async def _checklist(
    session: AsyncSession, firm_id: uuid.UUID, version: AgentPrompt, identities: dict[str, str]
) -> list[s.ChecklistItem]:
    conns = await _connections(session, set(identities.values()))
    return build_checklist(firm_id, version.config, identities, conns)


async def checklist(
    session: AsyncSession, firm_id: uuid.UUID, version_id: uuid.UUID, pairs: list[str]
) -> list[s.ChecklistItem]:
    """`pairs` are `connector:connection_id`; an unparsable id shows as an unbound connector."""
    _, version = await _load(session, firm_id, version_id)
    identities: dict[str, str] = {}
    for pair in pairs:
        connector, _, conn_id = pair.partition(":")
        try:
            identities[connector] = str(uuid.UUID(conn_id))
        except ValueError:
            continue
    return await _checklist(session, firm_id, version, identities)


def _require_usable(firm: Firm, version: AgentPrompt) -> None:
    if firm.status != "active":
        raise conflict("The firm is inactive")
    if version.status != "active":
        raise conflict("The version is archived")


async def _validate_overrides(
    session: AsyncSession, overrides: s.Overrides, version: AgentPrompt, firm: Firm
) -> dict[str, Any]:
    floor = firm.settings.get("policy_floor", [])
    if errors := check_overrides(overrides, version.config, floor, await load_snapshot(session)):
        raise invalid(errors)
    return overrides.model_dump(exclude_none=True)


async def _require_activatable(
    session: AsyncSession, mapping: M, firm: Firm, version: AgentPrompt
) -> None:
    _require_usable(firm, version)
    items = await _checklist(session, firm.id, version, mapping.identities)
    if missing := [i for i in items if not i.ok]:
        raise conflict(
            "Checklist incomplete: " + "; ".join(f"{i.connector}: {i.reason}" for i in missing)
        )
    if await session.scalar(
        select(M.id).where(
            M.firm_id == mapping.firm_id,
            M.agent_id == mapping.agent_id,
            M.status == "active",
            M.id != mapping.id,
        )
    ):
        raise conflict(ONE_ACTIVE)


async def _commit(session: AsyncSession) -> None:
    async with unique_or(session, ONE_ACTIVE_INDEX, conflict(ONE_ACTIVE)):
        await session.commit()


async def _load(
    session: AsyncSession, firm_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[Firm, AgentPrompt]:
    return (
        await get_or_404(session, Firm, firm_id, "Firm"),
        await get_or_404(session, AgentPrompt, version_id, "Version"),
    )


async def create(session: AsyncSession, body: s.MappingCreate, user: AppUser) -> M:
    firm, version = await _load(session, body.firm_id, body.agent_prompt_id)
    _require_usable(firm, version)
    mapping = M(
        agent_prompt_id=version.id,
        agent_id=version.agent_id,
        firm_id=firm.id,
        identities=body.model_dump(mode="json")["identities"],
        overrides=await _validate_overrides(session, body.overrides, version, firm),
        ab_weight=body.ab_weight,
        status="inactive",
        mapped_by=user.id,
    )
    session.add(mapping)
    await session.flush()
    if body.activate:
        await _require_activatable(session, mapping, firm, version)
        mapping.status = "active"
    await _commit(session)
    return mapping


async def patch(session: AsyncSession, mapping: M, body: s.MappingPatch) -> M:
    firm, version = await _load(session, mapping.firm_id, mapping.agent_prompt_id)
    if body.identities is not None:
        mapping.identities = body.model_dump(mode="json")["identities"]
    if body.overrides is not None:
        mapping.overrides = await _validate_overrides(session, body.overrides, version, firm)
    apply_patch(mapping, body, exclude={"identities", "overrides", "status"})
    status = body.status or mapping.status
    if status == "active":  # re-check whatever changed, before the status is flushed
        await _require_activatable(session, mapping, firm, version)
    mapping.status = status
    await _commit(session)
    return mapping


async def switch_version(session: AsyncSession, old: M, body: s.SwitchVersion, user: AppUser) -> M:
    """Supersede `old` with a row on another version of the same agent. The new row is active
    only if `old` was active and the checklist still passes."""
    firm, version = await _load(session, old.firm_id, body.agent_prompt_id)
    if version.agent_id != old.agent_id:
        raise conflict("The new version belongs to a different agent")
    if version.id == old.agent_prompt_id:
        raise conflict("The mapping already uses this version")
    _require_usable(firm, version)
    overrides = await _validate_overrides(
        session, s.Overrides.model_validate(old.overrides), version, firm
    )
    was_active, old.status = old.status == "active", "inactive"
    await session.flush()
    new = M(
        agent_prompt_id=version.id,
        agent_id=old.agent_id,
        firm_id=old.firm_id,
        identities=dict(old.identities),
        overrides=overrides,
        ab_weight=old.ab_weight,
        kill_switch=old.kill_switch,
        status="inactive",
        supersedes_mapping_id=old.id,
        mapped_by=user.id,
    )
    session.add(new)
    await session.flush()
    if was_active and all(
        i.ok for i in await _checklist(session, firm.id, version, new.identities)
    ):
        new.status = "active"
    await _commit(session)
    return new


async def to_out(session: AsyncSession, mappings: list[M]) -> list[s.MappingOut]:
    """Mapping DTOs with firm, agent, version and checklist summary, in at most three queries."""
    if not mappings:
        return []
    rows = {
        r.id: r
        for r in await session.execute(
            select(V.id, V.version, V.config, Agent.handle, Agent.name)
            .join(Agent, Agent.id == V.agent_id)
            .where(V.id.in_({m.agent_prompt_id for m in mappings}))
        )
    }
    firm_ids = {m.firm_id for m in mappings}
    firm_rows = await session.execute(select(Firm.id, Firm.name).where(Firm.id.in_(firm_ids)))
    firms = {fid: name for fid, name in firm_rows}
    conns = await _connections(session, {i for m in mappings for i in m.identities.values()})
    out: list[s.MappingOut] = []
    for m in mappings:
        r = rows[m.agent_prompt_id]
        items = build_checklist(m.firm_id, r.config, m.identities, conns)
        out.append(
            s.MappingOut(
                **s.MappingBase.model_validate(m).model_dump(),
                firm_name=firms[m.firm_id],
                agent_handle=r.handle,
                agent_name=r.name,
                version=r.version,
                checklist_ok=all(i.ok for i in items),
                checklist_missing=sum(not i.ok for i in items),
            )
        )
    return out


async def list_mappings(
    session: AsyncSession,
    paging: PageParams,
    firm_id: uuid.UUID | None,
    agent_id: uuid.UUID | None,
    status: MappingStatus | None,
) -> Page[s.MappingOut]:
    stmt = select(M).order_by(M.mapped_at.desc(), M.id)
    for col, value in ((M.firm_id, firm_id), (M.agent_id, agent_id), (M.status, status)):
        if value is not None:
            stmt = stmt.where(col == value)
    rows, total = await fetch_page(session, stmt, paging)
    return Page.of(await to_out(session, rows), total, paging)


async def resolved(session: AsyncSession, mapping: M) -> s.MappingResolved:
    version = await session.get_one(V, mapping.agent_prompt_id)
    firm = await session.get_one(Firm, mapping.firm_id)
    settings = firm.settings
    overrides = mapping.overrides
    snap = await load_snapshot(session)
    return s.MappingResolved(
        policies=resolve.policies(
            version.config, settings.get("policy_floor", []), overrides, snap
        ),
        cadence=resolve.cadence(version.config, overrides),
        alert_routing=resolve.alert_routing(
            version.config, settings.get("alert_routing", {}), overrides
        ),
        timezone=firm.timezone,
        business_hours=settings.get("business_hours", {}),
        quiet_hours=settings.get("quiet_hours"),
        history=await _history(session, mapping),
    )


async def _history(session: AsyncSession, mapping: M) -> list[s.MappingHistoryItem]:
    """Walk the switch-version chain back from this mapping (a handful of rows at most)."""
    out: list[s.MappingHistoryItem] = []
    previous = mapping.supersedes_mapping_id
    while previous is not None:
        row = (
            await session.execute(
                select(M.id, M.status, M.mapped_at, M.supersedes_mapping_id, V.version)
                .join(V, V.id == M.agent_prompt_id)
                .where(M.id == previous)
            )
        ).one()
        out.append(
            s.MappingHistoryItem(
                id=row.id, version=row.version, status=row.status, mapped_at=row.mapped_at
            )
        )
        previous = row.supersedes_mapping_id
    return out
