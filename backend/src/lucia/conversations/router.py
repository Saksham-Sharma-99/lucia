import uuid
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import Query, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from lucia.api.tags import api_router
from lucia.auth.deps import CurrentUser, DbSession
from lucia.conversations import schemas as s
from lucia.conversations import service
from lucia.conversations.events import stream
from lucia.core.pagination import Page, Paging
from lucia.db.models import Conversation, Firm
from lucia.db.queries import get_or_404

router = api_router("conversations")


@router.get(
    "/firms/{firm_id}/conversations",
    summary="List a firm's playground chats",
    operation_id="listConversations",
)
async def list_conversations(
    firm_id: uuid.UUID,
    session: DbSession,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[s.ConversationOut]:
    await get_or_404(session, Firm, firm_id, "Firm")
    return await service.list_conversations(session, firm_id, paging, q)


@router.post(
    "/firms/{firm_id}/conversations",
    status_code=status.HTTP_201_CREATED,
    summary="Start a playground chat",
    operation_id="createConversation",
)
async def create_conversation(
    firm_id: uuid.UUID, body: s.ConversationCreate, session: DbSession, user: CurrentUser
) -> s.ConversationOut:
    await get_or_404(session, Firm, firm_id, "Firm")
    return await service.detail(session, await service.create(session, firm_id, body, user))


@router.get(
    "/conversations/{conversation_id}", summary="Get a chat", operation_id="getConversation"
)
async def get_conversation(conversation_id: uuid.UUID, session: DbSession) -> s.ConversationOut:
    conv = await get_or_404(session, Conversation, conversation_id, "Conversation")
    return await service.detail(session, conv)


@router.patch(
    "/conversations/{conversation_id}", summary="Rename a chat", operation_id="renameConversation"
)
async def rename(
    conversation_id: uuid.UUID, body: s.ConversationPatch, session: DbSession
) -> s.ConversationOut:
    conv = await get_or_404(session, Conversation, conversation_id, "Conversation")
    conv.title = body.title
    await session.commit()
    return await service.detail(session, conv)


@router.get(
    "/conversations/{conversation_id}/messages",
    summary="A chat's messages, oldest first",
    operation_id="listMessages",
)
async def list_messages(
    conversation_id: uuid.UUID, session: DbSession, paging: Paging
) -> Page[s.MessageOut]:
    conv = await get_or_404(session, Conversation, conversation_id, "Conversation")
    return await service.messages(session, conv, paging)


@router.post(
    "/conversations/{conversation_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a message (the orchestrator handles it in the background)",
    operation_id="sendMessage",
)
async def send_message(
    conversation_id: uuid.UUID, body: s.MessageIn, session: DbSession, user: CurrentUser
) -> s.MessageOut:
    conv = await get_or_404(session, Conversation, conversation_id, "Conversation")
    return s.MessageOut.model_validate(await service.send_message(session, conv, body.body, user))


@router.post(
    "/conversations/{conversation_id}/actions",
    summary="Answer the chat's pending choice (subject, agent) or retry a message",
    operation_id="conversationAction",
)
async def action(
    conversation_id: uuid.UUID, body: s.ActionIn, session: DbSession
) -> s.ConversationOut:
    conv = await get_or_404(session, Conversation, conversation_id, "Conversation")
    await service.apply_action(session, conv, body)
    return await service.detail(session, conv)


@router.get(
    "/conversations/{conversation_id}/runs",
    summary="Agent runs this chat is linked to",
    operation_id="listConversationRuns",
)
async def runs(conversation_id: uuid.UUID, session: DbSession) -> list[s.LinkedRun]:
    conv = await get_or_404(session, Conversation, conversation_id, "Conversation")
    return await service.linked_runs(session, conv)


@router.get(
    "/conversations/{conversation_id}/events",
    response_class=EventSourceResponse,
    summary="Live chat events (SSE)",
    operation_id="conversationEvents",
)
async def events(conversation_id: uuid.UUID, session: DbSession) -> AsyncIterable[ServerSentEvent]:
    await get_or_404(session, Conversation, conversation_id, "Conversation")
    await session.close()  # don't hold a connection for the life of the stream
    async for event in stream(conversation_id):
        yield event


@router.get(
    "/firms/{firm_id}/mentionable-agents",
    summary="Agents that can be @mentioned at a firm",
    operation_id="listMentionableAgents",
)
async def mentionable(firm_id: uuid.UUID, session: DbSession) -> list[s.MentionableAgent]:
    return await service.mentionable(session, firm_id)
