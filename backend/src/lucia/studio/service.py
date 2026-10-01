import uuid
from typing import Any

from sqlalchemy import ColumnElement, case, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.config import get_settings
from lucia.core.errors import FieldError, conflict, invalid, not_found
from lucia.core.pagination import Page, PageParams, paginate
from lucia.core.security import canonical_hash
from lucia.core.time import utcnow
from lucia.db.models import Agent, AgentPrompt, AppUser, CompiledAgentFirmMapping
from lucia.db.models.agent import VersionStatus
from lucia.db.queries import apply_patch, latest_active_version, like_pattern, unique_or
from lucia.registry.snapshot import load_snapshot
from lucia.studio import schemas as s
from lucia.studio.config_schema import VersionConfig
from lucia.studio.validator import validate_config

M = CompiledAgentFirmMapping
V = AgentPrompt

# Status is derived from the versions, never stored (HLD §0).
_any_active = exists().where(V.agent_id == Agent.id, V.status == "active")
_active_mappings = select(func.count()).where(M.agent_id == Agent.id, M.status == "active")
_latest = select(func.max(V.version)).where(V.agent_id == Agent.id)

SORTS: dict[str, ColumnElement[Any]] = {
    "name": Agent.name.asc(),
    "-name": Agent.name.desc(),
    "handle": Agent.handle.asc(),
    "updated_at": Agent.updated_at.asc(),
    "-updated_at": Agent.updated_at.desc(),
    "created_at": Agent.created_at.asc(),
    "-created_at": Agent.created_at.desc(),
}


async def check_config(session: AsyncSession, cfg: VersionConfig) -> None:
    """422 with `/config/...` pointers if the registry rejects the config."""
    errors = validate_config(cfg, await load_snapshot(session), get_settings().allowed_models)
    if errors:
        raise invalid([e.model_copy(update={"path": "/config" + e.path}) for e in errors])


async def list_agents(
    session: AsyncSession,
    paging: PageParams,
    q: str | None,
    status: VersionStatus | None,
    is_template: bool,
    sort: str,
) -> Page[s.AgentListItem]:
    stmt = (
        select(
            Agent.id,
            Agent.handle,
            Agent.name,
            Agent.description,
            Agent.is_template,
            Agent.updated_at,
            case((_any_active, "active"), else_="archived").label("status"),
            _latest.scalar_subquery().label("latest_version"),
            _latest.where(V.status == "active").scalar_subquery().label("latest_active_version"),
            _active_mappings.scalar_subquery().label("active_mapping_count"),
        )
        .where(Agent.is_template.is_(is_template))
        .order_by(SORTS[sort], Agent.id)
    )
    if q:  # served by the trigram index on name || ' ' || description
        like = like_pattern(q)
        stmt = stmt.where(
            or_(
                (Agent.name + " " + Agent.description).ilike(like, escape="\\"),
                Agent.handle.ilike(like, escape="\\"),
            )
        )
    if status:
        stmt = stmt.where(_any_active if status == "active" else ~_any_active)
    return await paginate(
        session,
        stmt,
        paging,
        lambda row: s.AgentListItem.model_validate(row._asdict()),
        scalars=False,
    )


async def get_agent(session: AsyncSession, handle: str, *, lock: bool = False) -> Agent:
    stmt = select(Agent).where(Agent.handle == handle)
    agent = await session.scalar(stmt.with_for_update() if lock else stmt)
    if agent is None:
        raise not_found(f"Agent @{handle}")
    return agent


async def _versions(
    session: AsyncSession, agent_id: uuid.UUID, version: int | None = None
) -> list[s.VersionSummary]:
    """Version summaries, newest first, with parent number and active mapping count."""
    parent = V.__table__.alias("parent")
    stmt = (
        select(
            *V.__table__.c,
            parent.c.version.label("parent_version"),
            select(func.count())
            .where(M.agent_prompt_id == V.id, M.status == "active")
            .scalar_subquery()
            .label("mapping_count"),
        )
        .outerjoin(parent, parent.c.id == V.parent_version_id)
        .where(V.agent_id == agent_id)
        .order_by(V.version.desc())
    )
    if version is not None:
        stmt = stmt.where(V.version == version)
    return [s.VersionSummary.model_validate(r._asdict()) for r in await session.execute(stmt)]


async def agent_detail(session: AsyncSession, agent: Agent) -> s.AgentDetail:
    versions = await _versions(session, agent.id)
    return s.AgentDetail(
        **s.AgentOut.model_validate(agent).model_dump(),
        status="active" if any(v.status == "active" for v in versions) else "archived",
        active_mapping_count=sum(v.mapping_count for v in versions),
        versions=versions,
    )


async def version_detail(session: AsyncSession, v: AgentPrompt) -> s.VersionDetail:
    (summary,) = await _versions(session, v.agent_id, v.version)
    return s.VersionDetail(**summary.model_dump(), config=VersionConfig.model_validate(v.config))


async def get_version(session: AsyncSession, agent: Agent, n: int) -> AgentPrompt:
    v = await session.scalar(select(V).where(V.agent_id == agent.id, V.version == n))
    if v is None:
        raise not_found(f"@{agent.handle} v{n}")
    return v


def _version(
    agent_id: uuid.UUID,
    n: int,
    cfg: VersionConfig,
    user: AppUser,
    changelog: str,
    parent_id: uuid.UUID | None = None,
) -> AgentPrompt:
    stored = cfg.stored()
    return V(
        agent_id=agent_id,
        version=n,
        status="active",
        config=stored,
        config_hash=canonical_hash(stored),
        parent_version_id=parent_id,
        changelog=changelog,
        created_by=user.id,
    )


async def create_agent(
    session: AsyncSession, body: s.AgentCreate, user: AppUser, *, is_template: bool = False
) -> Agent:
    if body.source_agent_id and await session.get(Agent, body.source_agent_id) is None:
        raise invalid(
            [
                FieldError(
                    path="/source_agent_id", code="not_found", message="Source agent not found"
                )
            ]
        )
    await check_config(session, body.config)
    agent = Agent(**body.model_dump(exclude={"config", "changelog"}), is_template=is_template)
    session.add(agent)
    async with unique_or(session, "agents_handle_key", conflict(f"Handle @{body.handle} is taken")):
        await session.flush()
    session.add(_version(agent.id, 1, body.config, user, body.changelog or "Initial version"))
    await session.commit()
    return agent


async def patch_agent(session: AsyncSession, agent: Agent, body: s.AgentPatch) -> Agent:
    apply_patch(agent, body)
    await session.commit()
    return agent


async def archive_agent(session: AsyncSession, agent: Agent) -> list[uuid.UUID]:
    """Archive every version and deactivate the agent's mappings; returns those mapping ids."""
    await session.execute(update(V).where(V.agent_id == agent.id).values(status="archived"))
    ids = await session.scalars(
        update(M)
        .where(M.agent_id == agent.id, M.status == "active")
        .values(status="inactive")
        .returning(M.id)
    )
    agent.updated_at = utcnow()
    await session.commit()
    return list(ids)


async def unarchive_agent(session: AsyncSession, agent: Agent) -> None:
    """Reactivate the latest version (every agent has at least v1)."""
    latest = await session.scalar(
        select(V).where(V.agent_id == agent.id).order_by(V.version.desc()).limit(1)
    )
    if latest is not None:  # every agent has v1, but stay total
        latest.status = "active"
    agent.updated_at = utcnow()
    await session.commit()


async def duplicate_agent(
    session: AsyncSession, source: Agent, body: s.AgentDuplicate, user: AppUser
) -> Agent:
    version = await latest_active_version(session, source.id)
    if version is None:
        raise conflict(f"@{source.handle} has no active version to copy")
    create = s.AgentCreate(
        **body.model_dump(),
        description=source.description,
        use_cases=source.use_cases,
        is_callable=source.is_callable,
        auto_delegate=source.auto_delegate,
        version_policy=source.version_policy,
        source_agent_id=source.id,
        config=VersionConfig.model_validate(version.config),
        changelog=f"Copied from @{source.handle} v{version.version}",
    )
    return await create_agent(session, create, user)


async def amend(
    session: AsyncSession, handle: str, body: s.VersionCreate, user: AppUser
) -> AgentPrompt:
    agent = await get_agent(session, handle, lock=True)  # serializes version numbering
    parent = await get_version(session, agent, body.from_version)
    if await latest_active_version(session, agent.id) is None:
        raise conflict(f"@{handle} is archived. Unarchive it before amending.")
    await check_config(session, body.config)
    latest = await session.scalar(select(func.max(V.version)).where(V.agent_id == agent.id))
    v = _version(agent.id, (latest or 0) + 1, body.config, user, body.changelog, parent.id)
    session.add(v)
    agent.updated_at = utcnow()
    await session.commit()
    return v


async def set_version_status(session: AsyncSession, v: AgentPrompt, status: VersionStatus) -> None:
    if status == "archived" and await session.scalar(
        select(exists().where(M.agent_prompt_id == v.id, M.status == "active"))
    ):
        raise conflict("An active mapping uses this version. Switch or deactivate it first.")
    v.status = status
    await session.commit()
