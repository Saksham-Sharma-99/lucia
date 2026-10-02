import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import AgentRun, Episode, RunTask
from tests.world import World, make_world


def _run(w: World, **kw: object) -> AgentRun:
    return AgentRun(
        firm_id=w.firm.id,
        mapping_id=w.mapping.id,
        agent_id=w.agent.id,
        agent_prompt_id=w.version.id,
        subject_id=w.subject.id,
        origin="playground",
        **kw,
    )


async def test_one_live_run_per_agent_and_subject(db: AsyncSession) -> None:
    w = await make_world(db)
    db.add(_run(w))
    await db.flush()
    db.add(_run(w))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_a_finished_run_allows_a_new_one(db: AsyncSession) -> None:
    w = await make_world(db)
    db.add(_run(w, status="COMPLETED"))
    db.add(_run(w))
    await db.flush()


@pytest.mark.parametrize(
    ("status", "substatus"),
    [("ACTIVE", "kill_switch"), ("PAUSED", "RUNNING"), ("COMPLETED", "WAITING"), ("NOPE", None)],
)
async def test_status_and_substatus_checks(
    db: AsyncSession, status: str, substatus: str | None
) -> None:
    w = await make_world(db)
    db.add(_run(w, status=status, substatus=substatus))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_paused_for_a_closed_subject_is_allowed(db: AsyncSession) -> None:
    w = await make_world(db)
    db.add(_run(w, status="PAUSED", substatus="subject_closed"))
    await db.flush()


async def test_task_key_unique_per_run(db: AsyncSession) -> None:
    w = await make_world(db)
    run = _run(w)
    db.add(run)
    await db.flush()
    for _ in range(2):
        db.add(
            RunTask(
                firm_id=w.firm.id,
                run_id=run.id,
                key="call:run",
                kind="call",
                target={"type": "run", "ref": None},
                title="t",
                goal="g",
                created_by="triage",
            )
        )
    with pytest.raises(IntegrityError):
        await db.flush()


def _episode(w: World, run: AgentRun, **kw: object) -> Episode:
    base: dict[str, object] = {
        "trigger_type": "user_input",
        "status": "pending",
        "dedup_key": "msg:1",
    }
    return Episode(firm_id=w.firm.id, run_id=run.id, **{**base, **kw})


@pytest.mark.parametrize(
    "bad",
    [
        {"trigger_type": "scheduled"},  # scheduled needs a source
        {"source": "ladder"},  # only scheduled episodes have a source
        {"dedup_key": "NoNamespace"},
        {"status": "lost"},
    ],
)
async def test_episode_checks(db: AsyncSession, bad: dict[str, object]) -> None:
    w = await make_world(db)
    run = _run(w)
    db.add(run)
    await db.flush()
    db.add(_episode(w, run, **bad))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_one_running_episode_per_run(db: AsyncSession) -> None:
    w = await make_world(db)
    run = _run(w)
    db.add(run)
    await db.flush()
    db.add_all(
        [
            _episode(w, run, status="running", dedup_key="msg:1"),
            _episode(w, run, status="running", dedup_key="msg:2"),
        ]
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_episode_dedup_key_is_unique(db: AsyncSession) -> None:
    w = await make_world(db)
    run = _run(w)
    db.add(run)
    await db.flush()
    db.add_all([_episode(w, run), _episode(w, run)])
    with pytest.raises(IntegrityError):
        await db.flush()
