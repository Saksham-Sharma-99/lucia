from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AgentRun, AppUser, Conversation, Episode, Message, Notification
from lucia.harness.attention import raise_attention
from lucia.notifications.render import check_public, public_text
from tests.world import World, make_leased_run, make_world


async def _linked(db: AsyncSession, w: World, user: AppUser) -> tuple[AgentRun, Conversation]:
    run = await make_leased_run(db, w)
    conv = Conversation(
        firm_id=w.firm.id, channel="playground", subject_id=w.subject.id, created_by=user.id
    )
    db.add(conv)
    await db.flush()
    db.add(
        Message(
            firm_id=w.firm.id,
            conversation_id=conv.id,
            direction="inbound",
            actor="human",
            author_user_id=user.id,
            body="@checkin call Jane",
            status="received",
        )
    )
    db.add(
        Episode(
            firm_id=w.firm.id,
            run_id=run.id,
            trigger_type="user_input",
            status="completed",
            dedup_key="msg:n",
            metadata_={"conversation_id": str(conv.id)},
        )
    )
    await db.commit()
    return run, conv


async def test_attention_is_posted_to_the_chat_and_rings_the_bell(
    db: AsyncSession, clock: FrozenClock, user: AppUser
) -> None:
    w = await make_world(db)
    run, conv = await _linked(db, w, user)
    item_id = await raise_attention(
        db,
        run,
        kind="question",
        summary="Which number should I call?",
        dedup_key="sr:q",
        options=[{"value": "a", "label": "Mobile"}],
    )
    await db.commit()
    msg = await db.scalar(
        select(Message).where(Message.conversation_id == conv.id, Message.actor == "agent")
    )
    assert msg is not None and msg.body == "Which number should I call?"
    assert msg.blocks == [
        {
            "type": "attention",
            "step_result_id": str(item_id),
            "kind": "question",
            "options": [{"value": "a", "label": "Mobile"}],
            "free_text": True,
        }
    ]
    bell = await db.scalar(select(Notification))
    assert bell is not None and (bell.channel, bell.target) == ("in_app", str(user.id))


async def test_a_duplicate_item_notifies_once(
    db: AsyncSession, clock: FrozenClock, user: AppUser
) -> None:
    w = await make_world(db)
    run, _ = await _linked(db, w, user)
    for _ in range(2):
        await raise_attention(db, run, kind="question", summary="q", dedup_key="sr:dup")
        await db.commit()
    assert len(list(await db.scalars(select(Notification)))) == 1


async def test_routing_without_in_app_sends_no_bell(
    db: AsyncSession, clock: FrozenClock, user: AppUser
) -> None:
    from tests.world import VOICE_CONFIG

    config = {
        **VOICE_CONFIG,
        "alert_policy": {"default_channels": {"P0": [], "P1": ["email"], "P2": []}},
    }
    w = await make_world(db, config=config)
    run, _ = await _linked(db, w, user)
    await raise_attention(db, run, kind="question", summary="q", dedup_key="sr:e")
    await db.commit()
    assert await db.scalar(select(Notification)) is None


async def test_bell_lists_reads_and_clears(
    authed: AsyncClient, db: AsyncSession, clock: FrozenClock, user: AppUser
) -> None:
    w = await make_world(db)
    run, _ = await _linked(db, w, user)
    for key in ("sr:1", "sr:2"):
        await raise_attention(db, run, kind="question", summary=key, dedup_key=key)
    await db.commit()
    unread = (await authed.get("/api/v1/notifications", params={"unread": True})).json()
    assert len(unread) == 2 and unread[0]["summary"] in ("sr:1", "sr:2")
    assert (await authed.post(f"/api/v1/notifications/{unread[0]['id']}/read")).status_code == 204
    assert len((await authed.get("/api/v1/notifications", params={"unread": True})).json()) == 1
    assert (await authed.post("/api/v1/notifications/read-all")).status_code == 204
    assert (await authed.get("/api/v1/notifications", params={"unread": True})).json() == []


def test_public_text_hides_names_and_clinical_detail() -> None:
    text = public_text(kind="question", subject="Doe v. Acme", agent="checkin")
    assert text == "@checkin needs your input on Doe v. Acme · Open Lucia for details"


def test_check_public_rejects_names_and_identifiers() -> None:
    names = ["Jane Doe", "Dr. Lee"]
    assert check_public("Which fax number should I use?", names)
    assert not check_public("Should I call Jane Doe again?", names)
    assert not check_public("Her SSN is 123-45-6789", names)
