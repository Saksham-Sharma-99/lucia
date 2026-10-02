"""One user message → subject → target agent(s) → brief → hand-off (ORCHESTRATOR_SPEC §3).

Stateless (D1): per-chat state lives on the conversation, every decision is audited, and a
model failure routes nothing (fail closed, D10)."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.conversations.events import publish
from lucia.conversations.service import post_system
from lucia.core.audit import audit
from lucia.core.config import get_settings
from lucia.db.models import AuditLog, Conversation, Message, Subject
from lucia.harness.context import conversation_context, subject_snapshot
from lucia.harness.intake import EpisodeSpec, TargetUnavailable, create_or_fold
from lucia.llm.client import LLMError
from lucia.orchestrator import prompts, status
from lucia.orchestrator.directory import DirectoryAgent, describe, for_firm, known_handles
from lucia.orchestrator.llm import ask, say
from lucia.orchestrator.mentions import parse
from lucia.orchestrator.schemas import AgentScores, Brief, Intent, SplitResult
from lucia.orchestrator.subject import resolve
from lucia.orchestrator.targeting import decide, precheck, sanitize

Target = tuple[DirectoryAgent, str]  # the agent and the part of the message it gets


async def handle_message(session: AsyncSession, message_id: uuid.UUID) -> None:
    msg = await session.get_one(Message, message_id)
    conv = await session.get_one(Conversation, msg.conversation_id)
    if await session.scalar(
        select(AuditLog.id).where(
            AuditLog.action == "orchestrator.handled", AuditLog.entity_id == msg.id
        )
    ):
        return
    conv_id = conv.id
    try:
        await _handle(session, conv, msg)
    except LLMError:
        await session.rollback()  # drop half-made decisions; reload what the reply needs
        conv = await session.get_one(Conversation, conv_id, populate_existing=True)
        msg = await session.get_one(Message, message_id, populate_existing=True)
        await _reply(
            session,
            conv,
            msg,
            "error",
            "Couldn't process this message.",
            [{"type": "retry", "message_id": str(msg.id)}],
        )
        raise
    if (conv.state.get("pending") or {}).get("message_id") == str(msg.id):
        await session.commit()  # still open: the answer re-runs this message
        return
    await audit(
        session,
        action="orchestrator.handled",
        entity_type="message",
        entity_id=msg.id,
        firm_id=conv.firm_id,
    )
    await session.commit()


async def _reply(
    session: AsyncSession,
    conv: Conversation,
    msg: Message,
    kind: str,
    body: str,
    blocks: list[dict[str, Any]] | None = None,
) -> None:
    await post_system(session, conv, body=body, blocks=blocks, dedup_key=f"orch:{msg.id}:{kind}")


async def _progress(conv: Conversation, msg: Message, stage: str) -> None:
    await publish(conv.id, "progress", {"message_id": str(msg.id), "stage": stage})


async def _handle(session: AsyncSession, conv: Conversation, msg: Message) -> None:
    if conv.subject_id is None and not await _lock_subject(session, conv, msg):
        return
    directory = await for_firm(session, conv.firm_id)
    targets = await _targets(session, conv, msg, directory)
    if targets:
        await _hand_off(session, conv, msg, targets)


async def _lock_subject(session: AsyncSession, conv: Conversation, msg: Message) -> bool:
    await _progress(conv, msg, "subject")
    found = await resolve(session, conv, msg)
    if found.subject_id is None:
        options = [
            {"subject_id": str(c.subject_id), "title": c.title, "kind": c.kind}
            for c in found.candidates
        ]
        conv.state = {
            **conv.state,
            "pending": {
                "kind": "subject_pick",
                "message_id": str(msg.id),
                "options": [o["subject_id"] for o in options],
            },
        }
        body = (
            "Which case is this about?"
            if options
            else ("I couldn't find that case. Pick one, or create it in Firms > Subjects.")
        )
        await _reply(
            session,
            conv,
            msg,
            "subject",
            body,
            [{"type": "subject_picker", "options": options, "allow_none": True}],
        )
        return False
    conv.subject_id = found.subject_id
    conv.state = {
        **conv.state,
        "subject_resolution": {
            "method": found.method,
            "confidence": found.confidence,
            "message_id": str(msg.id),
        },
    }
    await session.commit()
    await publish(conv.id, "conversation.updated", {"subject_id": str(found.subject_id)})
    return True


async def _context(
    session: AsyncSession, conv: Conversation, msg: Message, directory: list[DirectoryAgent]
) -> str:
    agents = describe(directory)
    chat = await conversation_context(session, str(conv.id))
    return f"## agents\n{agents}\n\n## conversation\n{chat}\n\n## message\n{msg.body}"


async def _scores(
    session: AsyncSession, conv: Conversation, msg: Message, directory: list[DirectoryAgent]
) -> AgentScores:
    await _progress(conv, msg, "scoring")
    raw = await ask(
        session,
        conv.firm_id,
        "agent_scores",
        prompts.AGENT_SCORES,
        await _context(session, conv, msg, directory),
        AgentScores,
    )
    return sanitize(raw, [a.handle for a in directory])


async def _targets(
    session: AsyncSession, conv: Conversation, msg: Message, directory: list[DirectoryAgent]
) -> list[Target]:
    by_handle = {a.handle: a for a in directory}
    settings = get_settings()
    chosen = conv.state.get("chosen") or {}
    if chosen.get("message_id") == str(msg.id) and chosen.get("handle") in by_handle:
        conv.state = {k: v for k, v in conv.state.items() if k != "chosen"}
        return [(by_handle[chosen["handle"]], msg.body)]
    mentions = parse(msg.body, await known_handles(session, conv.firm_id))
    if inactive := [m for m in mentions if m not in by_handle]:
        await _reply(
            session,
            conv,
            msg,
            "inactive",
            f"@{inactive[0]} isn't active for this firm. {_available(directory)}",
        )
        return []
    if mentions:
        scores = await _scores(session, conv, msg, directory)
        for handle in mentions:
            check = precheck(scores, handle, settings.precheck_threshold, settings.route_threshold)
            if not check.ok:
                await _suggest(session, conv, msg, handle, check.suggestions, by_handle)
                return []
        return [(by_handle[h], msg.body) for h in mentions]
    if settings.orchestrator_phase < 2:
        await _reply(
            session, conv, msg, "mention", f"Mention an agent to start. {_available(directory)}"
        )
        return []
    intent = await ask(
        session,
        conv.firm_id,
        "intent",
        prompts.INTENT,
        await _context(session, conv, msg, directory),
        Intent,
    )
    if intent.intent == "chat":
        await _reply(
            session,
            conv,
            msg,
            "help",
            f"I hand work to this firm's agents. {_available(directory)}",
        )
        return []
    if intent.intent == "status":
        await _status(session, conv, msg)
        return []
    return await _route(session, conv, msg, directory, await _scores(session, conv, msg, directory))


def _available(directory: list[DirectoryAgent]) -> str:
    if not directory:
        return "No agents are active at this firm yet."
    names = "; ".join(f"@{a.handle} ({a.description})" for a in directory)
    example = (directory[0].use_cases or [""])[0]
    return f"Available: {names}. For example: @{directory[0].handle} {example}"


async def _suggest(
    session: AsyncSession,
    conv: Conversation,
    msg: Message,
    mentioned: str,
    suggestions: list[Any],
    by_handle: dict[str, DirectoryAgent],
) -> None:
    if not suggestions:
        await _reply(
            session,
            conv,
            msg,
            "precheck",
            f"@{mentioned} can't do this, and no agent at this firm covers it.",
        )
        return
    conv.state = {
        **conv.state,
        "pending": {
            "kind": "agent_suggest",
            "message_id": str(msg.id),
            "options": [s.handle for s in suggestions],
        },
    }
    await _reply(
        session,
        conv,
        msg,
        "precheck",
        f"This looks like a job for @{suggestions[0].handle}: {suggestions[0].reason}",
        [
            {
                "type": "agent_suggestion",
                "mentioned": mentioned,
                "suggested": [
                    {"handle": s.handle, "score": s.score, "reason": s.reason} for s in suggestions
                ],
            }
        ],
    )


async def _status(session: AsyncSession, conv: Conversation, msg: Message) -> None:
    assert conv.subject_id is not None
    data = await status.read_status(session, conv.subject_id)
    text = await say(
        session,
        conv.firm_id,
        "status_reply",
        prompts.STATUS,
        f"## data\n{data}\n\n## question\n{msg.body}",
    )
    await _reply(session, conv, msg, "status", text)


async def _route(
    session: AsyncSession,
    conv: Conversation,
    msg: Message,
    directory: list[DirectoryAgent],
    scores: AgentScores,
) -> list[Target]:
    settings = get_settings()
    route = decide(
        scores,
        route_threshold=settings.route_threshold,
        margin=settings.route_margin,
        clarify_floor=settings.clarify_floor,
    )
    by_handle = {a.handle: a for a in directory}
    if route.kind == "route":
        return [(by_handle[route.handles[0]], msg.body)]
    if route.kind == "fanout":
        split = await ask(
            session,
            conv.firm_id,
            "split",
            prompts.SPLIT,
            f"## agents\n{', '.join(route.handles)}\n\n## message\n{msg.body}",
            SplitResult,
        )
        return [(by_handle[p.handle], p.text) for p in split.parts if p.handle in route.handles]
    if route.kind == "clarify":
        conv.state = {
            **conv.state,
            "pending": {
                "kind": "clarify_agent",
                "message_id": str(msg.id),
                "options": route.handles,
            },
        }
        ranked = {s.handle: s for s in scores.scores}
        await _reply(
            session,
            conv,
            msg,
            "clarify",
            "Which agent should handle this?",
            [
                {
                    "type": "agent_suggestion",
                    "mentioned": None,
                    "suggested": [
                        {"handle": h, "score": ranked[h].score, "reason": ranked[h].reason}
                        for h in route.handles
                    ],
                }
            ],
        )
        return []
    await _reply(
        session, conv, msg, "none", f"No agent at this firm covers this. {_available(directory)}"
    )
    return []


async def _hand_off(
    session: AsyncSession, conv: Conversation, msg: Message, targets: list[Target]
) -> None:
    assert conv.subject_id is not None
    subject = await session.get_one(Subject, conv.subject_id)
    snapshot = await subject_snapshot(session, subject)
    lines: list[str] = []
    blocks: list[dict[str, Any]] = []
    for agent, text in targets:
        await _progress(conv, msg, "brief")
        brief = await ask(
            session,
            conv.firm_id,
            "brief",
            prompts.BRIEF,
            f"## agent\n@{agent.handle}: {agent.description}\n\n"
            f"## subject\n{snapshot}\n\n## message\n{text}",
            Brief,
        )
        requester = (
            {"user_id": str(msg.author_user_id)}
            if msg.author_user_id
            else msg.external_author or {}
        )
        try:
            intake = await create_or_fold(
                session,
                firm_id=conv.firm_id,
                agent_id=agent.agent_id,
                subject_id=subject.id,
                origin="slack" if conv.channel == "slack" else "playground",
                spec=EpisodeSpec(
                    trigger_type="user_input",
                    dedup_key=f"msg:{msg.id}:{agent.agent_id}",
                    metadata={
                        "message_id": str(msg.id),
                        "conversation_id": str(conv.id),
                        "part": text,
                        "brief": brief.model_dump(),
                        "channel": conv.channel,
                        "requester": requester,
                    },
                ),
            )
        except TargetUnavailable:
            lines.append(f"@{agent.handle} was just deactivated.")
            continue
        if intake.deferred:
            lines.append(
                f"@{agent.handle}'s run on {subject.title} is paused; "
                "your message will run when it resumes."
            )
        else:
            verb = "Started" if intake.created_run else "Added to"
            lines.append(f"{verb} @{agent.handle} on {subject.title}.")
        blocks.append({"type": "run_link", "run_id": str(intake.run_id), "agent": agent.handle})
        await audit(
            session,
            action="orchestrator.route",
            entity_type="message",
            entity_id=msg.id,
            firm_id=conv.firm_id,
            data={
                "agent": agent.handle,
                "run_id": str(intake.run_id),
                "created": intake.created_run,
            },
        )
    await _reply(session, conv, msg, "handoff", " ".join(lines), blocks)
