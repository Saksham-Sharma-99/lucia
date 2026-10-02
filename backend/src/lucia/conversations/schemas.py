import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from lucia.core.schema import Read, Strict

Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class ConversationCreate(Strict):
    subject_id: uuid.UUID | None = None


class ConversationPatch(Strict):
    title: Annotated[str, Field(min_length=1, max_length=120)]


class ConversationOut(Read):
    id: uuid.UUID
    firm_id: uuid.UUID
    channel: str
    subject_id: uuid.UUID | None
    subject_title: str | None = None
    title: str | None
    pending: dict[str, Any] | None = None
    last_message_at: datetime
    created_at: datetime


class MessageIn(Strict):
    body: Body


class MessageOut(Read):
    id: uuid.UUID
    conversation_id: uuid.UUID
    direction: str
    actor: str
    author_user_id: uuid.UUID | None
    external_author: dict[str, Any] | None
    agent_id: uuid.UUID | None
    run_id: uuid.UUID | None
    body: str
    mentions: list[str]
    blocks: list[dict[str, Any]]
    status: str
    created_at: datetime


class ActionIn(Strict):
    type: Literal["subject_pick", "agent_suggest", "clarify_agent", "retry"]
    value: Annotated[str, Field(max_length=100)] | None = None
    message_id: uuid.UUID


class LinkedRun(Read):
    id: uuid.UUID
    agent_handle: str
    status: str
    substatus: str | None
    tasks_done: int
    tasks_total: int


class MentionableAgent(Read):
    handle: str
    name: str
    description: str
