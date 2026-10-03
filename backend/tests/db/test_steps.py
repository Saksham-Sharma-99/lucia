import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.audit import audit
from lucia.db.models import (
    AgentRun,
    AgentRunStep,
    AuditLog,
    JournalEntry,
    Notification,
    StepResult,
)
from tests.world import World, make_world


async def _run(db: AsyncSession) -> tuple[World, AgentRun]:
    w = await make_world(db)
    run = AgentRun(
        firm_id=w.firm.id,
        mapping_id=w.mapping.id,
        agent_id=w.agent.id,
        agent_prompt_id=w.version.id,
        subject_id=w.subject.id,
        origin="playground",
    )
    db.add(run)
    await db.flush()
    return w, run


def _step(w: World, run: AgentRun, seq: int, key: str) -> AgentRunStep:
    return AgentRunStep(
        firm_id=w.firm.id,
        run_id=run.id,
        seq=seq,
        kind="tool",
        status="PENDING",
        idempotency_key=key,
        lease_epoch=1,
        actor="agent",
    )


async def test_idempotency_key_is_unique(db: AsyncSession) -> None:
    w, run = await _run(db)
    db.add_all([_step(w, run, 1, "k"), _step(w, run, 2, "k")])
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_seq_is_unique_per_run(db: AsyncSession) -> None:
    w, run = await _run(db)
    db.add_all([_step(w, run, 1, "a"), _step(w, run, 1, "b")])
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.parametrize("bad", [{"kind": "magic"}, {"status": "DONE"}, {"actor": "robot"}])
async def test_step_checks(db: AsyncSession, bad: dict[str, str]) -> None:
    w, run = await _run(db)
    step = _step(w, run, 1, "k")
    for k, v in bad.items():
        setattr(step, k, v)
    db.add(step)
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_journal_is_append_only(db: AsyncSession) -> None:
    w, run = await _run(db)
    entry = JournalEntry(
        firm_id=w.firm.id, run_id=run.id, source="harness", text="hi", dedup_key="journal:1"
    )
    db.add(entry)
    await db.flush()
    with pytest.raises(DBAPIError, match="append-only"):
        await db.execute(
            text("UPDATE journal_entries SET text = 'x' WHERE id = :i"), {"i": entry.id}
        )


async def test_audit_is_append_only(db: AsyncSession) -> None:
    w, _ = await _run(db)
    await audit(
        db, action="run.takeover", entity_type="agent_run", entity_id=None, firm_id=w.firm.id
    )
    await db.flush()
    row = await db.scalar(text("SELECT id FROM audit_logs LIMIT 1"))
    with pytest.raises(DBAPIError, match="append-only"):
        await db.execute(text("DELETE FROM audit_logs WHERE id = :i"), {"i": row})


async def test_audit_records_action(db: AsyncSession) -> None:
    w, _ = await _run(db)
    await audit(db, action="x.y", entity_type="t", entity_id=None, firm_id=w.firm.id, data={"a": 1})
    await db.flush()
    log = await db.scalar(text("SELECT data FROM audit_logs WHERE action = 'x.y'"))
    assert log == {"a": 1}
    assert AuditLog.__tablename__ == "audit_logs"


def _sr(w: World, run: AgentRun, key: str) -> StepResult:
    return StepResult(
        firm_id=w.firm.id,
        run_id=run.id,
        type="attention",
        kind="question",
        urgency="P1",
        summary="s",
        summary_public="s",
        blocking=True,
        status="open",
        dedup_key=key,
    )


async def test_step_result_dedup_key_is_unique(db: AsyncSession) -> None:
    w, run = await _run(db)
    db.add_all([_sr(w, run, "sr:1"), _sr(w, run, "sr:1")])
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_one_notification_per_item_channel_and_target(db: AsyncSession) -> None:
    w, run = await _run(db)
    sr = _sr(w, run, "sr:2")
    db.add(sr)
    await db.flush()
    for _ in range(2):
        db.add(
            Notification(
                firm_id=w.firm.id,
                step_result_id=sr.id,
                channel="in_app",
                target="u1",
                status="queued",
            )
        )
    with pytest.raises(IntegrityError):
        await db.flush()
