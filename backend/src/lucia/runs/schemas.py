import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import Field

from lucia.core.schema import Read, Strict


class AnswerIn(Strict):
    choice: Annotated[str, Field(max_length=40)] | None = None
    text: Annotated[str, Field(max_length=2000)] | None = None


class StepResultOut(Read):
    id: uuid.UUID
    run_id: uuid.UUID | None
    task_id: uuid.UUID | None
    type: str
    kind: str
    urgency: str
    summary: str
    data: dict[str, Any]
    options: list[dict[str, Any]]
    blocking: bool
    status: str
    answer: dict[str, Any] | None
    answered_at: datetime | None
    created_at: datetime


class RunOut(Read):
    id: uuid.UUID
    firm_id: uuid.UUID
    agent_handle: str
    subject_id: uuid.UUID
    subject_title: str
    status: str
    substatus: str | None
    goal: str
    completion_criteria: str
    version: int
    cycle: int
    next_wake_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    ended_reason: str | None
    takeover: dict[str, Any] | None
    tasks_done: int
    tasks_total: int
    created_at: datetime
    updated_at: datetime | None


class TaskOut(Read):
    id: uuid.UUID
    key: str
    kind: str
    title: str
    goal: str
    status: str
    depends_on: list[str]
    plan: list[dict[str, Any]]
    output: dict[str, Any] | None
    follow_up: dict[str, Any]
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class RecordingOut(Read):
    url: str


class StepOut(Read):
    id: uuid.UUID
    task_id: uuid.UUID | None
    episode_id: uuid.UUID | None
    plan_item_id: str | None
    parent_step_id: uuid.UUID | None
    seq: int
    kind: str
    role: str | None
    tool: str | None
    status: str
    input: dict[str, Any]
    output: dict[str, Any]
    summary: str | None
    error: dict[str, Any] | None
    model: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    cost: float | None
    started_at: datetime | None
    ended_at: datetime | None


class LogOut(Read):
    id: uuid.UUID
    task_id: uuid.UUID | None
    step_id: uuid.UUID | None
    level: str
    stage: str
    message: str
    at: datetime


class EpisodeOut(Read):
    id: uuid.UUID
    task_id: uuid.UUID | None
    trigger_type: str
    source: str | None
    status: str
    dedup_key: str
    due_at: datetime | None
    reason: str | None
    outcome: str | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class JournalEntryOut(Read):
    id: uuid.UUID
    task_id: uuid.UUID | None
    episode_id: uuid.UUID | None
    source: str
    text: str
    created_at: datetime


class JournalOut(Read):
    summary: str | None
    entries: list[JournalEntryOut]


class RemarksIn(Strict):
    remarks: Annotated[str, Field(min_length=10, max_length=2000)]
