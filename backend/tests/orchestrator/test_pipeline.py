from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.conversations.schemas import ActionIn
from lucia.conversations.service import apply_action
from lucia.core.clock import FrozenClock
from lucia.core.config import get_settings
from lucia.db.models import AgentRun, Conversation, Episode, Message, Subject
from lucia.llm.client import LLMError
from lucia.llm.fake import FakeLLM
from lucia.orchestrator.pipeline import handle_message
from lucia.orchestrator.schemas import (
    AgentScore,
    AgentScores,
    Brief,
    Intent,
    SplitPart,
    SplitResult,
    SubjectPick,
)
from tests.world import World, make_run, make_world

BRIEF = Brief(goal="Check in with Jane", entities=[], constraints=[], urgency="normal")


async def _chat(
    db: AsyncSession, w: World, body: str, *, subject: bool = False
) -> tuple[Conversation, Message]:
    conv = Conversation(
        firm_id=w.firm.id,
        channel="playground",
        subject_id=w.subject.id if subject else None,
        created_by=w.user.id,
    )
    db.add(conv)
    await db.flush()
    msg = Message(
        firm_id=w.firm.id,
        conversation_id=conv.id,
        direction="inbound",
        actor="human",
        author_user_id=w.user.id,
        body=body,
        status="received",
    )
    db.add(msg)
    await db.commit()
    return conv, msg


async def _replies(db: AsyncSession, conv: Conversation) -> list[Message]:
    return list(
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.actor == "system")
            .order_by(Message.seq)
        )
    )


def _scores(**s: float) -> AgentScores:
    return AgentScores(
        scores=[AgentScore(handle=h, score=v, reason=f"{h} fits") for h, v in s.items()],
        multi_intent=False,
    )


async def test_exact_reference_locks_the_subject_and_hands_off(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, sent: list[Any]
) -> None:
    w = await make_world(db)
    conv, msg = await _chat(db, w, "@checkin call Jane on DOE-1 for her check-in")
    fake_llm.on("agent_scores", _scores(checkin=0.9))
    fake_llm.on("brief", BRIEF)
    await handle_message(db, msg.id)
    await db.refresh(conv)
    assert conv.subject_id == w.subject.id and conv.state["subject_resolution"]["method"] == "exact"
    run = await db.scalar(select(AgentRun))
    assert run is not None and run.subject_id == w.subject.id
    ep = await db.scalar(select(Episode))
    assert (
        ep is not None
        and ep.metadata_["message_id"] == str(msg.id)
        and ep.metadata_["brief"]["goal"] == "Check in with Jane"
    )
    (reply,) = await _replies(db, conv)
    assert "@checkin" in reply.body and reply.blocks[0]["type"] == "run_link"
    assert [r for r, _ in fake_llm.calls] == ["agent_scores", "brief"]
    assert ("harness.advance_run", (str(run.id),)) in sent


async def test_confident_model_pick_locks_the_subject(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    conv, msg = await _chat(db, w, "@checkin call jane about the trucking case")
    fake_llm.on(
        "subject", SubjectPick(subject_id=str(w.subject.id), confidence=0.92, reason="trucking")
    )
    fake_llm.on("agent_scores", _scores(checkin=0.9))
    fake_llm.on("brief", BRIEF)
    await handle_message(db, msg.id)
    await db.refresh(conv)
    assert (
        conv.subject_id == w.subject.id and conv.state["subject_resolution"]["confidence"] == 0.92
    )


async def test_unsure_pick_asks_with_a_picker_and_routes_nothing(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    conv, msg = await _chat(db, w, "@checkin call jane about the trucking case")
    fake_llm.on(
        "subject", SubjectPick(subject_id=str(w.subject.id), confidence=0.6, reason="maybe")
    )
    await handle_message(db, msg.id)
    await db.refresh(conv)
    (reply,) = await _replies(db, conv)
    assert reply.blocks[0]["type"] == "subject_picker" and reply.blocks[0]["options"][0][
        "subject_id"
    ] == str(w.subject.id)
    assert conv.subject_id is None and conv.state["pending"] == {
        "kind": "subject_pick",
        "message_id": str(msg.id),
        "options": [str(w.subject.id)],
    }
    assert await db.scalar(select(AgentRun)) is None


async def test_a_picked_subject_reruns_the_message_and_starts_the_run(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, sent: list[Any]
) -> None:
    w = await make_world(db)
    conv, msg = await _chat(db, w, "@checkin call jane about the trucking case")
    fake_llm.on(
        "subject", SubjectPick(subject_id=str(w.subject.id), confidence=0.6, reason="maybe")
    )
    await handle_message(db, msg.id)
    await apply_action(
        db, conv, ActionIn(type="subject_pick", value=str(w.subject.id), message_id=msg.id)
    )
    assert ("orchestrator.handle_message", (str(msg.id),)) in sent
    fake_llm.on("agent_scores", _scores(checkin=0.9))
    fake_llm.on("brief", BRIEF)
    await handle_message(db, msg.id)
    run = await db.scalar(select(AgentRun))
    assert run is not None and run.subject_id == w.subject.id


async def test_a_clicked_suggestion_reruns_the_message_and_starts_the_run(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    other = await make_world(db, slug="other-firm", handle="liens")
    other.mapping.firm_id = w.firm.id
    await db.commit()
    conv, msg = await _chat(db, w, "@checkin negotiate the lien", subject=True)
    fake_llm.on("agent_scores", _scores(checkin=0.1, liens=0.9))
    await handle_message(db, msg.id)
    await db.refresh(conv)
    await apply_action(db, conv, ActionIn(type="agent_suggest", value="liens", message_id=msg.id))
    fake_llm.on("brief", BRIEF)
    await handle_message(db, msg.id)
    assert await db.scalar(select(AgentRun.agent_id)) == other.agent.id


async def test_no_candidate_subject_says_so(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    conv, msg = await _chat(db, w, "@checkin zzz qqq")
    await handle_message(db, msg.id)
    (reply,) = await _replies(db, conv)
    assert "couldn't find" in reply.body and fake_llm.calls == []


async def test_model_picking_an_id_off_the_list_is_ignored(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    conv, msg = await _chat(db, w, "@checkin call jane about the trucking case")
    fake_llm.on(
        "subject",
        SubjectPick(subject_id="00000000-0000-0000-0000-000000000000", confidence=0.99, reason="x"),
    )
    await handle_message(db, msg.id)
    await db.refresh(conv)
    assert conv.subject_id is None and conv.state["pending"]["kind"] == "subject_pick"


async def test_inactive_mention_is_explained(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    w.mapping.status = "inactive"
    await db.commit()
    conv, msg = await _chat(db, w, "@checkin call Jane", subject=True)
    await handle_message(db, msg.id)
    (reply,) = await _replies(db, conv)
    assert "@checkin isn't active" in reply.body


async def test_mention_that_doesnt_fit_suggests_another_agent(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    other = await make_world(db, slug="other-firm", handle="liens")
    other.mapping.firm_id = w.firm.id  # map @liens at this firm too
    await db.commit()
    conv, msg = await _chat(db, w, "@checkin negotiate the lien", subject=True)
    fake_llm.on("agent_scores", _scores(checkin=0.1, liens=0.9))
    await handle_message(db, msg.id)
    (reply,) = await _replies(db, conv)
    assert (
        reply.blocks[0]["type"] == "agent_suggestion"
        and reply.blocks[0]["suggested"][0]["handle"] == "liens"
    )
    await db.refresh(conv)
    assert conv.state["pending"]["kind"] == "agent_suggest"
    assert await db.scalar(select(AgentRun)) is None


async def test_a_clicked_suggestion_routes_without_scoring(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    conv, msg = await _chat(db, w, "@liens negotiate", subject=True)
    conv.state = {"chosen": {"message_id": str(msg.id), "handle": "checkin"}}
    await db.commit()
    fake_llm.on("brief", BRIEF)
    await handle_message(db, msg.id)
    assert await db.scalar(select(AgentRun.agent_id)) == w.agent.id
    assert [r for r, _ in fake_llm.calls] == ["brief"]


async def test_a_message_is_handled_once(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    conv, msg = await _chat(db, w, "@checkin call Jane", subject=True)
    fake_llm.on("agent_scores", _scores(checkin=0.9))
    fake_llm.on("brief", BRIEF)
    await handle_message(db, msg.id)
    await handle_message(db, msg.id)
    assert len(await _replies(db, conv)) == 1


async def test_model_failure_fails_closed_with_a_retry(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    conv, msg = await _chat(db, w, "@checkin call Jane", subject=True)
    fake_llm.on("agent_scores", LLMError("down", retryable=True))
    with pytest.raises(LLMError):
        await handle_message(db, msg.id)
    (reply,) = await _replies(db, conv)
    assert reply.blocks == [{"type": "retry", "message_id": str(msg.id)}]
    assert await db.scalar(select(AgentRun)) is None


async def test_paused_run_says_the_message_will_wait(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    await make_run(db, w, status="TAKEN_OVER")
    conv, msg = await _chat(db, w, "@checkin call Jane", subject=True)
    fake_llm.on("agent_scores", _scores(checkin=0.9))
    fake_llm.on("brief", BRIEF)
    await handle_message(db, msg.id)
    (reply,) = await _replies(db, conv)
    assert "paused" in reply.body


async def test_phase_one_requires_a_mention(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "orchestrator_phase", 1)
    w = await make_world(db)
    conv, msg = await _chat(db, w, "call Jane", subject=True)
    await handle_message(db, msg.id)
    (reply,) = await _replies(db, conv)
    assert "@checkin" in reply.body and fake_llm.calls == []


# --- phase 2: no mention ---------------------------------------------------------------------


async def test_chat_intent_gets_help(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    conv, msg = await _chat(db, w, "what can you do?", subject=True)
    fake_llm.on("intent", Intent(intent="chat"))
    await handle_message(db, msg.id)
    (reply,) = await _replies(db, conv)
    assert "@checkin" in reply.body and await db.scalar(select(AgentRun)) is None


async def test_status_intent_answers_from_the_runs(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    await make_run(db, w, status="ACTIVE", goal="Check in with Jane")
    conv, msg = await _chat(db, w, "how is Jane's check-in going?", subject=True)
    fake_llm.on("intent", Intent(intent="status"))
    fake_llm.on("status_reply", "The check-in run is active.")
    await handle_message(db, msg.id)
    (reply,) = await _replies(db, conv)
    assert reply.body == "The check-in run is active."
    assert "Check in with Jane" in fake_llm.calls[1][1]


async def test_work_without_a_mention_is_routed(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    _conv, msg = await _chat(db, w, "call Jane for her check-in", subject=True)
    fake_llm.on("intent", Intent(intent="work"))
    fake_llm.on("agent_scores", _scores(checkin=0.9))
    fake_llm.on("brief", BRIEF)
    await handle_message(db, msg.id)
    assert await db.scalar(select(func.count()).select_from(AgentRun)) == 1


async def test_unclear_work_asks_which_agent(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    conv, msg = await _chat(db, w, "do the thing", subject=True)
    fake_llm.on("intent", Intent(intent="work"))
    fake_llm.on("agent_scores", _scores(checkin=0.5))
    await handle_message(db, msg.id)
    (reply,) = await _replies(db, conv)
    assert reply.blocks[0]["type"] == "agent_suggestion"
    await db.refresh(conv)
    assert conv.state["pending"]["kind"] == "clarify_agent"


async def test_no_agent_fits(db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM) -> None:
    w = await make_world(db)
    conv, msg = await _chat(db, w, "bake a cake", subject=True)
    fake_llm.on("intent", Intent(intent="work"))
    fake_llm.on("agent_scores", _scores(checkin=0.1))
    await handle_message(db, msg.id)
    (reply,) = await _replies(db, conv)
    assert "No agent" in reply.body


async def test_two_intents_fan_out(db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM) -> None:
    w = await make_world(db)
    other = await make_world(db, slug="other-firm", handle="liens")
    other.mapping.firm_id = w.firm.id
    await db.commit()
    _conv, msg = await _chat(db, w, "check in with Jane and chase the lien", subject=True)
    fake_llm.on("intent", Intent(intent="work"))
    fake_llm.on(
        "agent_scores",
        AgentScores(
            scores=[
                AgentScore(handle="checkin", score=0.9, reason="r"),
                AgentScore(handle="liens", score=0.85, reason="r"),
            ],
            multi_intent=True,
        ),
    )
    fake_llm.on(
        "split",
        SplitResult(
            parts=[
                SplitPart(handle="checkin", text="check in with Jane"),
                SplitPart(handle="liens", text="chase the lien"),
            ]
        ),
    )
    fake_llm.on("brief", BRIEF, BRIEF)
    await handle_message(db, msg.id)
    keys = set(await db.scalars(select(Episode.dedup_key)))
    assert len(keys) == 2 and all(k.startswith(f"msg:{msg.id}:") for k in keys)
    assert await db.scalar(select(Subject.id)) is not None
