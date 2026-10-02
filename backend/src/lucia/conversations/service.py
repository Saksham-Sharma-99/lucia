import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.conversations import schemas as s
from lucia.conversations.events import publish
from lucia.core.clock import get_clock
from lucia.core.errors import conflict, not_found
from lucia.core.pagination import Page, PageParams, fetch_page
from lucia.db.models import (
    Agent,
    AgentRun,
    AppUser,
    CompiledAgentFirmMapping,
    Conversation,
    Message,
    RunTask,
    Subject,
)
from lucia.db.models.run import TERMINAL_TASK
from lucia.db.queries import like_pattern
from lucia.harness.links import run_ids_for_conversation
from lucia.worker.dispatch import send

M = CompiledAgentFirmMapping


def out(conv: Conversation, subject_title: str | None = None) -> s.ConversationOut:
    return s.ConversationOut.model_validate(conv).model_copy(
        update={"subject_title": subject_title, "pending": conv.state.get("pending")}
    )


async def detail(session: AsyncSession, conv: Conversation) -> s.ConversationOut:
    title = await session.scalar(select(Subject.title).where(Subject.id == conv.subject_id))
    return out(conv, title)


async def list_conversations(
    session: AsyncSession, firm_id: uuid.UUID, paging: PageParams, q: str | None
) -> Page[s.ConversationOut]:
    stmt = (
        select(Conversation, Subject.title)
        .outerjoin(Subject, Subject.id == Conversation.subject_id)
        .where(Conversation.firm_id == firm_id)
        .order_by(Conversation.last_message_at.desc(), Conversation.id)
    )
    if q:
        like = like_pattern(q)
        stmt = stmt.where(
            or_(Conversation.title.ilike(like, escape="\\"), Subject.title.ilike(like, escape="\\"))
        )
    rows, total = await fetch_page(session, stmt, paging, scalars=False)
    return Page.of([out(c, t) for c, t in rows], total, paging)


async def open_subject(session: AsyncSession, firm_id: uuid.UUID, subject_id: uuid.UUID) -> Subject:
    subject = await session.get(Subject, subject_id)
    if subject is None or subject.firm_id != firm_id or subject.status != "open":
        raise not_found("Subject")
    return subject


async def create(
    session: AsyncSession, firm_id: uuid.UUID, body: s.ConversationCreate, user: AppUser
) -> Conversation:
    if body.subject_id:
        await open_subject(session, firm_id, body.subject_id)
    conv = Conversation(
        firm_id=firm_id, channel="playground", subject_id=body.subject_id, created_by=user.id
    )
    session.add(conv)
    await session.commit()
    return conv


async def messages(
    session: AsyncSession, conv: Conversation, paging: PageParams
) -> Page[s.MessageOut]:
    stmt = select(Message).where(Message.conversation_id == conv.id).order_by(Message.seq)
    rows, total = await fetch_page(session, stmt, paging)
    return Page.of([s.MessageOut.model_validate(m) for m in rows], total, paging)


async def add_message(session: AsyncSession, conv: Conversation, **fields: Any) -> Message:
    """Stores a message, bumps the chat, and tells the browser after commit."""
    msg = Message(firm_id=conv.firm_id, conversation_id=conv.id, **fields)
    session.add(msg)
    conv.last_message_at = get_clock().now()
    await session.commit()
    await publish(
        conv.id, "message.created", s.MessageOut.model_validate(msg).model_dump(mode="json")
    )
    return msg


async def send_message(
    session: AsyncSession, conv: Conversation, body: str, user: AppUser
) -> Message:
    msg = await add_message(
        session,
        conv,
        direction="inbound",
        actor="human",
        author_user_id=user.id,
        body=body,
        status="received",
    )
    send("orchestrator.handle_message", msg.id)
    send("conversations.title" if conv.title is None else "conversations.summarize", conv.id)
    return msg


async def apply_action(session: AsyncSession, conv: Conversation, body: s.ActionIn) -> None:
    """Resolves the conversation's pending question, then re-runs the message it was about."""
    pending = conv.state.get("pending") or {}
    if body.type != "retry" and pending.get("message_id") != str(body.message_id):
        raise conflict("That choice is no longer open")
    state = {k: v for k, v in conv.state.items() if k != "pending"}
    if body.type == "subject_pick" and body.value != "none":
        subject = await open_subject(session, conv.firm_id, uuid.UUID(body.value or ""))
        if conv.subject_id not in (None, subject.id):
            raise conflict("This chat is about another subject; start a new chat")
        conv.subject_id = subject.id
        state["subject_resolution"] = {"method": "picker", "message_id": str(body.message_id)}
    elif body.type in ("agent_suggest", "clarify_agent"):
        state["chosen"] = {"message_id": str(body.message_id), "handle": body.value}
    conv.state = state
    await session.commit()
    await publish(conv.id, "conversation.updated", {"subject_id": conv.subject_id, "pending": None})
    if not (body.type == "subject_pick" and body.value == "none"):
        send("orchestrator.handle_message", body.message_id)


async def linked_runs(session: AsyncSession, conv: Conversation) -> list[s.LinkedRun]:
    tasks = select(func.count()).where(RunTask.run_id == AgentRun.id)
    rows = await session.execute(
        select(
            AgentRun.id,
            Agent.handle,
            AgentRun.status,
            AgentRun.substatus,
            tasks.where(RunTask.status.in_(TERMINAL_TASK)).scalar_subquery(),
            tasks.scalar_subquery(),
        )
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(AgentRun.id.in_(run_ids_for_conversation(conv.id)))
        .order_by(AgentRun.created_at.desc())
    )
    return [
        s.LinkedRun(
            id=run_id,
            agent_handle=handle,
            status=status,
            substatus=substatus,
            tasks_done=done,
            tasks_total=total,
        )
        for run_id, handle, status, substatus, done, total in rows
    ]


async def mentionable(session: AsyncSession, firm_id: uuid.UUID) -> list[s.MentionableAgent]:
    rows = await session.scalars(
        select(Agent)
        .join(M, M.agent_id == Agent.id)
        .where(M.firm_id == firm_id, M.status == "active", ~M.kill_switch)
        .order_by(Agent.handle)
    )
    return [s.MentionableAgent.model_validate(a) for a in rows]


async def post_system(
    session: AsyncSession,
    conv: Conversation,
    *,
    body: str,
    dedup_key: str,
    blocks: list[dict[str, Any]] | None = None,
) -> None:
    """An orchestrator reply; idempotent by `dedup_key`, so a retried message doesn't repeat it."""
    msg_id = await session.scalar(
        insert(Message)
        .values(
            firm_id=conv.firm_id,
            conversation_id=conv.id,
            direction="outbound",
            actor="system",
            body=body,
            blocks=blocks or [],
            status="queued" if conv.channel == "slack" else "sent",
            dedup_key=dedup_key,
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(Message.id)
    )
    conv.last_message_at = get_clock().now()
    await session.commit()
    if msg_id is not None and conv.channel == "slack":
        send("notifications.deliver_message", msg_id)
    if msg_id is not None:
        msg = await session.get_one(Message, msg_id)
        await publish(
            conv.id, "message.created", s.MessageOut.model_validate(msg).model_dump(mode="json")
        )
