import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from lucia.core.schema import AlertChannel, Read, Strict, Urgency
from lucia.db.models.mapping import MappingStatus
from lucia.firms.schemas import Weekday, Window

Identities = dict[str, uuid.UUID]  # connector name -> connection id
Weight = Field(default=100, ge=0, le=100)


class Cadence(Strict):
    min_wait_hours: int = Field(ge=0, le=24 * 60)


class Overrides(Strict):
    cadence: Cadence | None = None
    alert_routing: dict[Urgency, list[AlertChannel]] | None = None
    policy_params: dict[str, dict[str, Any]] | None = None


class ChecklistItem(Read):
    connector: str
    required: bool = True
    connection_id: uuid.UUID | None
    ok: bool
    reason: str


class MappingBase(Read):
    id: uuid.UUID
    firm_id: uuid.UUID
    agent_id: uuid.UUID
    agent_prompt_id: uuid.UUID
    identities: Identities
    overrides: Overrides
    ab_weight: int
    status: MappingStatus
    kill_switch: bool
    supersedes_mapping_id: uuid.UUID | None
    mapped_by: uuid.UUID
    mapped_at: datetime


class MappingOut(MappingBase):
    firm_name: str
    agent_handle: str
    agent_name: str
    version: int
    checklist_ok: bool
    checklist_missing: int


class MappingCreate(Strict):
    firm_id: uuid.UUID
    agent_prompt_id: uuid.UUID
    identities: Identities = {}
    overrides: Overrides = Overrides()
    ab_weight: int = Weight
    activate: bool = False


class MappingPatch(Strict):
    identities: Identities | None = None
    overrides: Overrides | None = None
    ab_weight: int | None = Field(default=None, ge=0, le=100)
    status: MappingStatus | None = None
    kill_switch: bool | None = None


class SwitchVersion(Strict):
    agent_prompt_id: uuid.UUID


Source = Literal["version", "firm", "mapping"]  # where a resolved setting comes from


class PolicySource(Read):
    source: Source
    params: dict[str, Any]
    applies: bool  # false when this mapping's stricter settings replace it


class ResolvedPolicy(Read):
    rule: str
    display_name: str
    description: str
    required: bool  # the platform minimum for agents that contact people
    sources: list[PolicySource]


class ResolvedRoute(Read):
    """Alert channels for one urgency: the mapping wins, then the firm, then the agent."""

    urgency: Urgency
    channels: list[str]
    source: Source | None
    version: list[str] | None
    firm: list[str] | None
    mapping: list[str] | None


class ResolvedCadence(Read):
    version_min_wait_hours: int
    override_min_wait_hours: int | None
    min_wait_hours: int


class MappingHistoryItem(Read):
    id: uuid.UUID
    version: int
    status: MappingStatus
    mapped_at: datetime


class MappingResolved(Read):
    """What the mapping runs under, and where each part comes from. Computed, never stored."""

    policies: list[ResolvedPolicy]
    cadence: ResolvedCadence
    alert_routing: list[ResolvedRoute]
    timezone: str
    business_hours: dict[Weekday, Window | None]
    quiet_hours: Window | None
    history: list[MappingHistoryItem]  # the mappings this one replaced, newest first
