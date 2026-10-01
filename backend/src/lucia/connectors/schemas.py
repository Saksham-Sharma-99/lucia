import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from lucia.core.schema import Read, Strict
from lucia.db.models.connection import ConnectionStatus, Health

ConnectorName = Literal["slack", "gmail", "vapi"]
Label = Field(min_length=1, max_length=120)


class TestResult(Read):
    ok: bool
    at: datetime
    detail: str


class ConnectionOut(Read):
    id: uuid.UUID
    firm_id: uuid.UUID
    connector: str
    label: str
    status: ConnectionStatus
    config: dict[str, Any]
    secret_hints: dict[str, str]
    has_consent_link: bool = False
    connected_at: datetime | None
    health: Health
    test_results: dict[str, TestResult]
    last_tested_at: datetime | None
    last_inbound_at: datetime | None
    last_inbound_type: str | None
    webhook_url: str = ""
    # Handles of agents whose mappings bind this connection; it can't be deleted while non-empty.
    used_by: list[str] = []
    created_at: datetime
    updated_at: datetime


class ConnectionCreate(Strict):
    connector: ConnectorName
    label: str = Label
    config: dict[str, Any] = {}
    secrets: dict[str, str] = Field(default={}, json_schema_extra={"writeOnly": True})


class ConnectionPatch(Strict):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    config: dict[str, Any] | None = None
    secrets: dict[str, str] | None = Field(default=None, json_schema_extra={"writeOnly": True})


class ConsentLink(Read):
    url: str


class TestRequest(Strict):
    tool: str | None = None
    input: dict[str, Any] = {}


class TestOutcome(Read):
    ok: bool
    detail: str


class InboundSetup(Read):
    webhook_url: str
    detail: str
