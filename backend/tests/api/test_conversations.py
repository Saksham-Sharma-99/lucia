import asyncio
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.conversations.events import publish, stream
from lucia.core.clock import FrozenClock
from lucia.db.models import Conversation, Episode, Message, Subject
from lucia.llm.fake import FakeLLM
from tests.factories import ZERO
from tests.world import World, make_run, make_world


async def _conv(client: AsyncClient, w: World, **body: Any) -> dict[str, Any]:
    resp = await client.post(f"/api/v1/firms/{w.firm.id}/conversations", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _send(client: AsyncClient, conv: dict[str, Any], body: str = "@checkin call Jane") -> Any:
    return await client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": body})


async def test_send_stores_the_message_and_hands_it_to_the_orchestrator(
    authed: AsyncClient, db: AsyncSession, sent: list[Any]
) -> None:
    w = await make_world(db)
    conv = await _conv(authed, w)
    resp = await _send(authed, conv)
    assert resp.status_code == 202
    msg = resp.json()
    assert (msg["direction"], msg["actor"], msg["status"]) == ("inbound", "human", "received")
    tasks = [t for t, _ in sent]
    assert ("orchestrator.handle_message", (msg["id"],)) in sent
    assert "conversations.title" in tasks
    listed = (await authed.get(f"/api/v1/conversations/{conv['id']}/messages")).json()
    assert [m["body"] for m in listed["items"]] == ["@checkin call Jane"]


async def test_agent_posts_name_their_agent(
    authed: AsyncClient, db: AsyncSession, sent: list[Any]
) -> None:
    w = await make_world(db)
    conv = await _conv(authed, w)
    await _send(authed, conv)
    db.add(
        Message(
            firm_id=w.firm.id,
            conversation_id=uuid.UUID(conv["id"]),
            direction="outbound",
            actor="agent",
            agent_id=w.agent.id,
            body="I'll call Jane.",
            status="sent",
        )
    )
    await db.commit()
    listed = (await authed.get(f"/api/v1/conversations/{conv['id']}/messages")).json()
    assert [(m["actor"], m["agent_handle"]) for m in listed["items"]] == [
        ("human", None),
        ("agent", "checkin"),
    ]


@pytest.mark.parametrize("body", ["", " ", "x" * 8001])
async def test_bad_message_bodies_are_422(authed: AsyncClient, db: AsyncSession, body: str) -> None:
    w = await make_world(db)
    conv = await _conv(authed, w)
    assert (await _send(authed, conv, body)).status_code == 422


async def test_list_searches_title_and_subject_and_orders_by_activity(
    authed: AsyncClient, db: AsyncSession
) -> None:
    w = await make_world(db)
    a = await _conv(authed, w)
    b = await _conv(authed, w, subject_id=str(w.subject.id))
    await authed.patch(f"/api/v1/conversations/{a['id']}", json={"title": "Records for Roe"})
    await _send(authed, a, "hello")
    base = f"/api/v1/firms/{w.firm.id}/conversations"
    assert [c["id"] for c in (await authed.get(base)).json()["items"]] == [a["id"], b["id"]]
    assert [c["id"] for c in (await authed.get(base, params={"q": "roe"})).json()["items"]] == [
        a["id"]
    ]
    found = (await authed.get(base, params={"q": "acme"})).json()["items"]
    assert [c["id"] for c in found] == [b["id"]] and found[0][
        "subject_title"
    ] == "Doe v. Acme Trucking"


async def test_subject_of_another_firm_is_refused(authed: AsyncClient, db: AsyncSession) -> None:
    w = await make_world(db)
    other = await make_world(db, slug="other-firm", handle="other")
    resp = await authed.post(
        f"/api/v1/firms/{w.firm.id}/conversations", json={"subject_id": str(other.subject.id)}
    )
    assert resp.status_code == 404


async def test_unknown_conversation_is_404(authed: AsyncClient) -> None:
    assert (await authed.get(f"/api/v1/conversations/{ZERO}")).status_code == 404


async def _pending(db: AsyncSession, conv_id: str, msg_id: str, kind: str = "subject_pick") -> None:
    conv = await db.get_one(Conversation, uuid.UUID(conv_id))
    conv.state = {"pending": {"kind": kind, "message_id": msg_id, "options": []}}
    await db.commit()


async def test_subject_pick_locks_the_subject_and_reruns_the_message(
    authed: AsyncClient, db: AsyncSession, sent: list[Any]
) -> None:
    w = await make_world(db)
    conv = await _conv(authed, w)
    msg = (await _send(authed, conv)).json()
    await _pending(db, conv["id"], msg["id"])
    sent.clear()
    resp = await authed.post(
        f"/api/v1/conversations/{conv['id']}/actions",
        json={"type": "subject_pick", "value": str(w.subject.id), "message_id": msg["id"]},
    )
    assert resp.status_code == 200, resp.text
    got = (await authed.get(f"/api/v1/conversations/{conv['id']}")).json()
    assert got["subject_id"] == str(w.subject.id) and got["pending"] is None
    assert sent == [("orchestrator.handle_message", (msg["id"],))]


async def test_action_on_a_stale_pick_is_409(authed: AsyncClient, db: AsyncSession) -> None:
    w = await make_world(db)
    conv = await _conv(authed, w)
    msg = (await _send(authed, conv)).json()
    resp = await authed.post(
        f"/api/v1/conversations/{conv['id']}/actions",
        json={"type": "subject_pick", "value": str(w.subject.id), "message_id": msg["id"]},
    )
    assert resp.status_code == 409


async def test_picking_a_closed_or_foreign_subject_is_refused(
    authed: AsyncClient, db: AsyncSession
) -> None:
    w = await make_world(db)
    conv = await _conv(authed, w)
    msg = (await _send(authed, conv)).json()
    await _pending(db, conv["id"], msg["id"])
    subject = await db.get_one(Subject, w.subject.id)
    subject.status = "closed"
    await db.commit()
    resp = await authed.post(
        f"/api/v1/conversations/{conv['id']}/actions",
        json={"type": "subject_pick", "value": str(w.subject.id), "message_id": msg["id"]},
    )
    assert resp.status_code == 404


async def test_agent_suggestion_records_the_choice(
    authed: AsyncClient, db: AsyncSession, sent: list[Any]
) -> None:
    w = await make_world(db)
    conv = await _conv(authed, w, subject_id=str(w.subject.id))
    msg = (await _send(authed, conv)).json()
    await _pending(db, conv["id"], msg["id"], "agent_suggest")
    resp = await authed.post(
        f"/api/v1/conversations/{conv['id']}/actions",
        json={"type": "agent_suggest", "value": "checkin", "message_id": msg["id"]},
    )
    assert resp.status_code == 200
    conversation = await db.get_one(Conversation, uuid.UUID(conv["id"]))
    await db.refresh(conversation)
    assert conversation.state["chosen"] == {"message_id": msg["id"], "handle": "checkin"}


async def test_linked_runs(authed: AsyncClient, db: AsyncSession, clock: FrozenClock) -> None:
    w = await make_world(db)
    conv = await _conv(authed, w, subject_id=str(w.subject.id))
    run = await make_run(db, w)
    db.add(
        Episode(
            firm_id=w.firm.id,
            run_id=run.id,
            trigger_type="user_input",
            status="completed",
            dedup_key="msg:link",
            metadata_={"conversation_id": conv["id"]},
        )
    )
    await db.commit()
    runs = (await authed.get(f"/api/v1/conversations/{conv['id']}/runs")).json()
    assert [(r["id"], r["agent_handle"]) for r in runs] == [(str(run.id), "checkin")]


async def test_mentionable_agents(authed: AsyncClient, db: AsyncSession) -> None:
    w = await make_world(db)
    agents = (await authed.get(f"/api/v1/firms/{w.firm.id}/mentionable-agents")).json()
    assert [a["handle"] for a in agents] == ["checkin"]
    w.mapping.kill_switch = True
    await db.commit()
    assert (await authed.get(f"/api/v1/firms/{w.firm.id}/mentionable-agents")).json() == []


async def test_events_are_relayed() -> None:
    conv = uuid.uuid4()

    async def first() -> Any:
        async for event in stream(conv, limit=1):
            return event

    reader = asyncio.create_task(first())
    await asyncio.sleep(0.05)
    await publish(conv, "progress", {"stage": "subject"})
    event = await asyncio.wait_for(reader, 2)
    assert event.event == "progress" and event.data == {"stage": "subject"}


async def test_title_is_written_once(db: AsyncSession, fake_llm: FakeLLM) -> None:
    from lucia.conversations.summarize import title

    w = await make_world(db)
    conv = Conversation(firm_id=w.firm.id, channel="playground")
    db.add(conv)
    await db.flush()
    db.add(
        Message(
            firm_id=w.firm.id,
            conversation_id=conv.id,
            direction="inbound",
            actor="human",
            body="@checkin please call Jane",
            status="received",
        )
    )
    await db.commit()
    fake_llm.on("title", "Jane check-in call")
    await title(db, conv.id)
    await title(db, conv.id)
    await db.refresh(conv)
    assert conv.title == "Jane check-in call" and len(fake_llm.calls) == 1


async def test_summary_folds_messages_that_left_the_window(
    db: AsyncSession, fake_llm: FakeLLM
) -> None:
    from lucia.conversations.summarize import summarize

    w = await make_world(db)
    conv = Conversation(firm_id=w.firm.id, channel="playground")
    db.add(conv)
    await db.flush()
    for i in range(29):
        db.add(
            Message(
                firm_id=w.firm.id,
                conversation_id=conv.id,
                direction="inbound",
                actor="human",
                body=f"m{i}",
                status="received",
            )
        )
        await db.flush()
    await db.commit()
    await summarize(db, conv.id)
    assert fake_llm.calls == []  # only 9 messages are out of the window
    db.add(
        Message(
            firm_id=w.firm.id,
            conversation_id=conv.id,
            direction="inbound",
            actor="human",
            body="m29",
            status="received",
        )
    )
    await db.commit()
    fake_llm.on("summary", "Talked about Jane.")
    await summarize(db, conv.id)
    await db.refresh(conv)
    assert conv.state["summary"] == "Talked about Jane."
