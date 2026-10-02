from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import JournalEntry, JournalSummary
from lucia.harness.journal import COMPACT_EVERY, append, compact, recent
from lucia.llm.fake import FakeLLM
from tests.world import make_run, make_world


async def test_append_is_deduplicated_and_recent_returns_the_last_entries(
    db: AsyncSession, clock: FrozenClock
) -> None:
    run = await make_run(db, await make_world(db))
    for i in range(7):
        await append(db, run, text=f"entry {i}", source="harness", key=f"e{i}")
    await append(db, run, text="entry 0", source="harness", key="e0")
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(JournalEntry)) == 7
    summary, entries = await recent(db, run.id)
    assert summary is None and entries == [f"entry {i}" for i in range(2, 7)]


async def test_compaction_summarizes_every_twenty_entries(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    run = await make_run(db, await make_world(db))
    for i in range(COMPACT_EVERY - 1):
        await append(db, run, text=f"e{i}", source="harness", key=f"k{i}")
    await db.commit()
    await compact(db, run)
    assert fake_llm.calls == []
    await append(db, run, text="last", source="agent", key="last")
    await db.commit()
    fake_llm.on("summarizer", "Called Jane twice; voicemail.")
    await compact(db, run)
    assert await db.scalar(select(JournalSummary.text)) == "Called Jane twice; voicemail."
    summary, _ = await recent(db, run.id)
    assert summary == "Called Jane twice; voicemail."
