"""The run's notebook: harness and agent entries, compacted every 20 (RUNTIME_SPEC §10.1)."""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import AgentPrompt, AgentRun, JournalEntry, JournalSummary
from lucia.harness.steps import call_llm

COMPACT_EVERY = 20
SUMMARIZE = (
    "Fold the existing summary and the new journal entries into one short summary of what "
    "happened in this run. Keep names, dates, outcomes and open threads. No new facts."
)


async def append(
    session: AsyncSession,
    run: AgentRun,
    *,
    text: str,
    source: str,
    key: str,
    episode_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
) -> None:
    """Adds an entry unless `key` was used before; the caller commits."""
    await session.execute(
        insert(JournalEntry)
        .values(
            firm_id=run.firm_id,
            run_id=run.id,
            episode_id=episode_id,
            task_id=task_id,
            source=source,
            text=text,
            dedup_key=f"journal:{run.id}:{key}",
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
    )


async def _latest_summary(session: AsyncSession, run_id: uuid.UUID) -> JournalSummary | None:
    return await session.scalar(
        select(JournalSummary)
        .where(JournalSummary.run_id == run_id)
        .order_by(JournalSummary.created_at.desc())
        .limit(1)
    )


async def _entries_after(
    session: AsyncSession, run_id: uuid.UUID, summary: JournalSummary | None
) -> list[JournalEntry]:
    stmt = select(JournalEntry).where(JournalEntry.run_id == run_id)
    if summary is not None:
        through = await session.get_one(JournalEntry, summary.through_entry_id)
        stmt = stmt.where(JournalEntry.seq > through.seq)
    return list(await session.scalars(stmt.order_by(JournalEntry.seq)))


async def recent(
    session: AsyncSession, run_id: uuid.UUID, n: int = 5
) -> tuple[str | None, list[str]]:
    """The latest summary and the last `n` entries."""
    rows = await session.scalars(
        select(JournalEntry.text)
        .where(JournalEntry.run_id == run_id)
        .order_by(JournalEntry.seq.desc())
        .limit(n)
    )
    summary = await _latest_summary(session, run_id)
    return (summary.text if summary else None), list(reversed(list(rows)))


async def compact(session: AsyncSession, run: AgentRun) -> None:
    summary = await _latest_summary(session, run.id)
    entries = await _entries_after(session, run.id, summary)
    if len(entries) < COMPACT_EVERY:
        return
    prompt = await session.get_one(AgentPrompt, run.agent_prompt_id)
    previous = summary.text if summary else ""
    text = await call_llm(
        session,
        run,
        role="summarizer",
        model=prompt.config["models"]["judge"],
        instructions=SUMMARIZE,
        message=f"## summary\n{previous}\n\n## new entries\n" + "\n".join(e.text for e in entries),
        epoch=run.lease_epoch,
        fenced=False,  # maintenance, outside any lease: a summary is safe to write regardless
    )
    session.add(
        JournalSummary(
            firm_id=run.firm_id, run_id=run.id, through_entry_id=entries[-1].id, text=text
        )
    )
    await session.commit()
