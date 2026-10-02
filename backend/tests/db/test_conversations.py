import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import Conversation, Firm, Message, Subject


async def _setup(db: AsyncSession) -> tuple[Firm, Subject, Subject]:
    firm = Firm(name="f", slug="f-conv", timezone="UTC", color="#000000", settings={})
    db.add(firm)
    await db.flush()
    a = Subject(firm_id=firm.id, kind="matter", title="A")
    b = Subject(firm_id=firm.id, kind="matter", title="B")
    db.add_all([a, b])
    await db.flush()
    return firm, a, b


async def test_subject_can_be_set_once_then_is_locked(db: AsyncSession) -> None:
    firm, a, b = await _setup(db)
    conv = Conversation(firm_id=firm.id, channel="playground")
    db.add(conv)
    await db.flush()
    conv.subject_id = a.id
    await db.flush()
    with pytest.raises(DBAPIError, match="conversation subject is locked"):
        await db.execute(
            text("UPDATE conversations SET subject_id = :s WHERE id = :c"),
            {"s": b.id, "c": conv.id},
        )


async def test_message_dedup_key_is_unique(db: AsyncSession) -> None:
    firm, _, _ = await _setup(db)
    conv = Conversation(firm_id=firm.id, channel="slack", external_thread_ref="slack:T:C:1")
    db.add(conv)
    await db.flush()
    for _ in range(2):
        db.add(
            Message(
                firm_id=firm.id,
                conversation_id=conv.id,
                direction="inbound",
                actor="human",
                body="hi",
                status="received",
                dedup_key="slack:T:C:1",
            )
        )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_thread_ref_is_unique_per_channel(db: AsyncSession) -> None:
    firm, _, _ = await _setup(db)
    db.add_all(
        [
            Conversation(firm_id=firm.id, channel="slack", external_thread_ref="slack:T:C:9"),
            Conversation(firm_id=firm.id, channel="slack", external_thread_ref="slack:T:C:9"),
        ]
    )
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.parametrize("field", [{"channel": "fax"}, {"channel": "sms"}])
async def test_channel_check(db: AsyncSession, field: dict[str, str]) -> None:
    firm, _, _ = await _setup(db)
    db.add(Conversation(firm_id=firm.id, **field))
    with pytest.raises(IntegrityError):
        await db.flush()
