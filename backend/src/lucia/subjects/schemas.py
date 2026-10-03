import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field

from lucia.core.schema import Read, Strict
from lucia.db.models.subject import Role, SubjectStatus
from lucia.firms.schemas import Timezone


def _lower(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


Kind = Annotated[str, BeforeValidator(_lower), Field(pattern=r"^[a-z0-9 _-]{1,40}$")]
Title = Annotated[str, Field(min_length=1, max_length=200)]
Email = Annotated[str, BeforeValidator(_lower), Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
ContactChannel = Literal["voice", "email", "slack"]
ConsentStatus = Literal["granted", "refused", "unknown"]


class SubjectCreate(Strict):
    kind: Kind
    title: Title
    external_ref: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    status: SubjectStatus = "open"
    description: Annotated[str, Field(max_length=4000)] = ""
    data: dict[str, Any] = {}


class SubjectPatch(Strict):
    kind: Kind | None = None
    title: Title | None = None
    external_ref: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    status: SubjectStatus | None = None
    description: Annotated[str, Field(max_length=4000)] | None = None
    data: dict[str, Any] | None = None


class Phone(Strict):
    e164: Annotated[str, Field(pattern=r"^\+[1-9]\d{6,14}$")]
    type: Literal["voice", "fax"] = "voice"
    label: Annotated[str, Field(max_length=40)] = ""


class ContactPointCreate(Strict):
    name: Title
    org_name: Annotated[str, Field(max_length=200)] | None = None
    emails: list[Email] = []
    phones: list[Phone] = []
    tz: Timezone | None = None
    org_daily_cap: Annotated[int, Field(ge=1, le=1000)] | None = None


class ContactPointPatch(Strict):
    name: Title | None = None
    org_name: Annotated[str, Field(max_length=200)] | None = None
    emails: list[Email] | None = None
    phones: list[Phone] | None = None
    tz: Timezone | None = None
    org_daily_cap: Annotated[int, Field(ge=1, le=1000)] | None = None
    opt_out: list[ContactChannel] | None = None  # the channels opted out after this change
    reason: Annotated[str, Field(min_length=10, max_length=500)] | None = None  # to clear one


class ContactPointOut(Read):
    id: uuid.UUID
    name: str
    org_name: str | None
    emails: list[str]
    phones: list[dict[str, Any]]
    tz: str | None
    opt_out: dict[str, Any]
    org_daily_cap: int | None
    roles: list[str] = []  # its role on each subject (in the firm's contact list)


class SubjectContactCreate(Strict):
    contact_point_id: uuid.UUID
    role: Role


class SubjectContactPatch(Strict):
    role: Role | None = None
    consent: dict[Literal["voice", "email"], ConsentStatus] | None = None


class SubjectContactOut(Read):
    id: uuid.UUID
    role: str
    consent: dict[str, Any]
    alias_ordinal: int
    contact_point: ContactPointOut


class RunBrief(Read):
    id: uuid.UUID
    agent_handle: str
    status: str


class SubjectOut(Read):
    id: uuid.UUID
    firm_id: uuid.UUID
    kind: str
    title: str
    external_ref: str | None
    status: str
    description: str
    data: dict[str, Any]
    revision: int
    created_at: datetime
    updated_at: datetime | None
    contact_count: int = 0
    live_run_count: int = 0


class SubjectDetail(SubjectOut):
    contacts: list[SubjectContactOut]
    runs: list[RunBrief]
