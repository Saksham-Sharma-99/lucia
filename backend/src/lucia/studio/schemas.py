import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field

from lucia.core.errors import FieldError
from lucia.core.schema import Read, Strict
from lucia.db.models.agent import VersionPolicy, VersionStatus
from lucia.studio.config_schema import VersionConfig

Handle = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{2,31}$")]
Name = Annotated[str, Field(min_length=1, max_length=120)]
Text = Annotated[str, Field(max_length=2000)]
UseCases = Annotated[list[str], Field(max_length=20)]


class AgentListItem(Read):
    id: uuid.UUID
    handle: str
    name: str
    description: str
    is_template: bool
    status: VersionStatus
    latest_version: int
    latest_active_version: int | None
    active_mapping_count: int
    updated_at: datetime


class VersionSummary(Read):
    id: uuid.UUID
    version: int
    status: VersionStatus
    changelog: str
    parent_version: int | None
    created_by: uuid.UUID
    created_by_name: str
    created_at: datetime
    config_hash: str
    mapping_count: int


class VersionDetail(VersionSummary):
    config: VersionConfig


class AgentOut(Read):
    id: uuid.UUID
    handle: str
    name: str
    description: str
    use_cases: list[str]
    is_template: bool
    source_agent_id: uuid.UUID | None
    is_callable: bool
    auto_delegate: bool
    version_policy: VersionPolicy
    created_at: datetime
    updated_at: datetime


class AgentDetail(AgentOut):
    status: VersionStatus
    active_mapping_count: int
    versions: list[VersionSummary]


class AgentPatch(Strict):
    name: Name | None = None
    description: Text | None = None
    use_cases: UseCases | None = None
    is_callable: bool | None = None
    auto_delegate: bool | None = None
    version_policy: VersionPolicy | None = None


class AgentCreate(Strict):
    handle: Handle
    name: Name
    description: Text = ""
    use_cases: UseCases = []
    is_callable: bool = True
    auto_delegate: bool = False
    version_policy: VersionPolicy = "pin"
    source_agent_id: uuid.UUID | None = None
    config: VersionConfig
    changelog: Text = ""


class AgentDuplicate(Strict):
    handle: Handle
    name: Name


class ArchiveResult(Read):
    agent: AgentDetail
    deactivated_mapping_ids: list[uuid.UUID]


class ValidateRequest(Strict):
    config: VersionConfig


class ValidateResult(Read):
    errors: list[FieldError] = []


class VersionCreate(Strict):
    from_version: int = Field(ge=1)
    config: VersionConfig
    changelog: Text = ""
