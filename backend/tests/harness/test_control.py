from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import (
    AgentRun,
    AuditLog,
    CompiledAgentFirmMapping,
    Episode,
    JournalEntry,
    Subject,
)
from lucia.harness import control, worker
from lucia.harness.gate import gate
from lucia.harness.intake import EpisodeSpec, create_or_fold
from lucia.harness.lease import LeaseLost, claim, fence
from lucia.harness.tasks import sweep_end_conditions
from lucia.mappings.schemas import MappingPatch
from lucia.mappings.service import patch
from lucia.subjects.schemas import SubjectPatch
from lucia.subjects.service import patch_subject
from tests.world import VOICE_CONFIG, World, make_leased_run, make_run, make_world


def _ep(w: World, run: AgentRun, key: str, **kw: Any) -> Episode:
    fields: dict[str, Any] = {"trigger_type": "user_input", "status": "pending", **kw}
    return Episode(firm_id=w.firm.id, run_id=run.id, dedup_key=key, **fields)


async def test_kill_switch_pauses_live_runs_and_unkill_resumes(
    db: AsyncSession, clock: FrozenClock, sent: list[Any]
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    db.add(_ep(w, run, "msg:1"))
    await db.commit()
    assert await control.set_kill(db, w.mapping.id, True) == [run.id]
    await db.commit()
    await db.refresh(run)
    assert (run.status, run.substatus, run.lease_epoch) == ("PAUSED", "kill_switch", 2)
    assert await db.scalar(select(Episode.status)) == "deferred"
    assert await control.set_kill(db, w.mapping.id, False) == [run.id]
    assert sent == [], "the caller enqueues once its transaction commits"
    await db.commit()
    await db.refresh(run)
    assert (run.status, run.substatus) == ("ACTIVE", None)
    assert await db.scalar(select(Episode.status)) == "pending"


async def test_unkilling_a_mapping_resumes_its_runs_after_the_commit(
    db: AsyncSession, clock: FrozenClock, sent: list[Any]
) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="PAUSED", substatus="kill_switch")
    mapping = await db.get_one(CompiledAgentFirmMapping, w.mapping.id)
    mapping.kill_switch = True
    await db.commit()
    await patch(db, mapping, MappingPatch(kill_switch=False))
    assert ("harness.advance_run", (str(run.id),)) in sent


async def test_mapping_patch_flips_the_kill_switch(
    authed: Any, db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="ACTIVE")
    resp = await authed.patch(f"/api/v1/mappings/{w.mapping.id}", json={"kill_switch": True})
    assert resp.status_code == 200, resp.text
    await db.refresh(run)
    assert (run.status, run.substatus) == ("PAUSED", "kill_switch")


async def test_sweep_pauses_stragglers(db: AsyncSession, clock: FrozenClock) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="ACTIVE")
    w.mapping.kill_switch = True  # set without the service, e.g. by hand in SQL
    await db.commit()
    assert await control.sweep_killed(db) == 1
    await db.refresh(run)
    assert run.status == "PAUSED"


async def test_takeover_fences_defers_and_supersedes(db: AsyncSession, clock: FrozenClock) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    db.add_all(
        [
            _ep(w, run, "msg:1"),
            Episode(
                firm_id=w.firm.id,
                run_id=run.id,
                trigger_type="scheduled",
                source="ladder",
                status="scheduled",
                due_at=clock.now() + timedelta(days=1),
                dedup_key="ladder:1",
            ),
        ]
    )
    await db.commit()
    await control.takeover(db, run, user_id=w.user.id, remarks="Calling Jane myself today")
    await db.refresh(run)
    assert run.takeover is not None
    assert (run.status, run.lease_epoch, run.takeover["remarks"]) == (
        "TAKEN_OVER",
        2,
        "Calling Jane myself today",
    )
    statuses = {
        k: v for k, v in (await db.execute(select(Episode.dedup_key, Episode.status))).all()
    }
    assert statuses == {"msg:1": "deferred", "ladder:1": "superseded"}
    r = await create_or_fold(
        db,
        firm_id=w.firm.id,
        agent_id=w.agent.id,
        subject_id=w.subject.id,
        origin="playground",
        spec=EpisodeSpec("user_input", "msg:2"),
    )
    assert r.deferred
    assert await db.scalar(select(JournalEntry.source)) == "human"
    assert await db.scalar(select(AuditLog.action)) == "run.takeover"


async def test_takeover_of_a_finished_run_is_refused(db: AsyncSession, clock: FrozenClock) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="COMPLETED")
    with pytest.raises(control.ControlError):
        await control.takeover(db, run, user_id=w.user.id, remarks="too late for this")


async def test_handback_queues_remarks_first_and_resumes(
    db: AsyncSession, clock: FrozenClock, sent: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    db.add(_ep(w, run, "msg:1"))
    await db.commit()
    await control.takeover(db, run, user_id=w.user.id, remarks="Calling Jane myself today")
    episode_id = await control.handback(db, run, user_id=w.user.id, remarks="Reached her, all good")
    await db.refresh(run)
    assert run.takeover is not None and run.status == "ACTIVE"
    assert run.takeover["handback"]["remarks"] == "Reached her, all good"
    first = await db.get_one(Episode, episode_id)
    assert (first.trigger_type, first.metadata_["remarks"]) == ("handback", "Reached her, all good")
    seen: list[str] = []

    async def triage(session: AsyncSession, r: AgentRun, ep: Episode, epoch: int) -> None:
        seen.append(ep.trigger_type)

    monkeypatch.setattr(worker, "run_triage", triage)
    await worker.advance_run(db, run.id, owner="t")
    assert seen == ["handback"]
    with pytest.raises(control.ControlError):
        await control.handback(db, run, user_id=w.user.id, remarks="again, twice over")


async def test_handback_restores_the_wakeups_the_takeover_cancelled(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    due = clock.now() + timedelta(hours=8)
    wake = Episode(
        firm_id=w.firm.id,
        run_id=run.id,
        trigger_type="scheduled",
        source="deferral",
        status="scheduled",
        due_at=due,
        dedup_key="deferral:1",
    )
    db.add(wake)
    await db.commit()
    await control.takeover(db, run, user_id=w.user.id, remarks="Calling Jane myself today")
    await control.handback(db, run, user_id=w.user.id, remarks="Back to you")
    await db.refresh(wake)
    await db.refresh(run)
    assert (wake.status, wake.due_at, wake.guard_version) == ("scheduled", due, 2)
    assert "supersede" not in wake.metadata_ and run.next_wake_at == due


async def test_gate_pauses_killed_and_ends_on_limits(db: AsyncSession, clock: FrozenClock) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="ACTIVE", started_at=clock.now())
    assert await gate(db, run) == "ok"
    run.step_count = 600
    await db.commit()
    assert await gate(db, run) == "ended"
    await db.refresh(run)
    assert (run.status, run.ended_reason) == ("ENDED", "max_steps")


async def test_gate_ends_after_max_duration(db: AsyncSession, clock: FrozenClock) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="ACTIVE", started_at=clock.now())
    clock.advance(timedelta(days=121))
    assert await gate(db, run) == "ended"


@pytest.mark.parametrize(
    ("policy", "status", "sub"), [("end", "ENDED", None), ("pause", "PAUSED", "subject_closed")]
)
async def test_gate_on_a_closed_subject(
    db: AsyncSession, clock: FrozenClock, policy: str, status: str, sub: str | None
) -> None:
    config = {
        **VOICE_CONFIG,
        "end_conditions": {**VOICE_CONFIG["end_conditions"], "on_subject_closed": policy},
    }
    w = await make_world(db, config=config)
    run = await make_run(db, w, status="ACTIVE", started_at=clock.now())
    subject = await db.get_one(Subject, w.subject.id)
    subject.status = "closed"
    await db.commit()
    assert await gate(db, run) != "ok"
    await db.refresh(run)
    assert (run.status, run.substatus) == (status, sub)


async def test_reopening_the_subject_resumes_a_run_paused_on_it(
    db: AsyncSession, clock: FrozenClock, sent: list[Any]
) -> None:
    config = {
        **VOICE_CONFIG,
        "end_conditions": {**VOICE_CONFIG["end_conditions"], "on_subject_closed": "pause"},
    }
    w = await make_world(db, config=config)
    run = await make_run(db, w, status="ACTIVE", started_at=clock.now())
    db.add(_ep(w, run, "msg:1"))
    subject = await db.get_one(Subject, w.subject.id)
    subject.status = "closed"
    await db.commit()
    assert await gate(db, run) == "paused"
    assert await db.scalar(select(Episode.status)) == "deferred"
    await patch_subject(db, subject, SubjectPatch(status="open"))
    await db.refresh(run)
    assert (run.status, run.substatus) == ("ACTIVE", None)
    assert await db.scalar(select(Episode.status)) == "pending"
    assert ("harness.advance_run", (str(run.id),)) in sent


async def test_worker_stops_at_the_gate(db: AsyncSession, clock: FrozenClock) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="ACTIVE", step_count=10_000, started_at=clock.now())
    db.add(_ep(w, run, "msg:1"))
    await db.commit()
    assert await worker.advance_run(db, run.id, owner="t") == "gated"


async def test_takeover_fences_out_a_claim_made_after_the_run_was_read(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    run = await make_run(db, w)  # the API read the run …
    epoch = await claim(db, run.id, "worker")  # … then a worker claimed it
    await control.takeover(db, run, user_id=w.user.id, remarks="mine")
    with pytest.raises(LeaseLost):
        await fence(db, run.id, epoch or 0)


async def test_fence_refuses_a_run_that_is_no_longer_claimable(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    run = await make_run(db, w)
    epoch = await claim(db, run.id, "worker")
    await db.execute(update(AgentRun).where(AgentRun.id == run.id).values(status="TAKEN_OVER"))
    with pytest.raises(LeaseLost):
        await fence(db, run.id, epoch or 0)


async def test_a_run_paused_by_repeated_failures_can_be_taken_over_and_handed_back(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="PAUSED", substatus="repeated_failure")
    await control.takeover(db, run, user_id=w.user.id, remarks="Looking into the outage")
    await control.handback(db, run, user_id=w.user.id, remarks="Provider is back")
    assert (run.status, run.substatus) == ("ACTIVE", None)


async def test_a_run_paused_by_the_kill_switch_cannot_be_taken_over(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="PAUSED", substatus="kill_switch")
    with pytest.raises(control.ControlError):
        await control.takeover(db, run, user_id=w.user.id, remarks="x")


async def test_the_end_sweep_ends_paused_runs_past_their_duration(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    run = await make_run(
        db, w, status="PAUSED", substatus="repeated_failure", started_at=clock.now()
    )
    clock.advance(timedelta(days=121))
    assert await sweep_end_conditions(db) == 1
    await db.refresh(run)
    assert (run.status, run.ended_reason) == ("ENDED", "max_duration")


async def test_runs_on_an_inactive_mapping_keep_running_on_their_version(
    db: AsyncSession, clock: FrozenClock
) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="ACTIVE", started_at=clock.now())
    w.mapping.status = "inactive"  # e.g. switch_version moved the agent to a new version
    await db.commit()
    assert await gate(db, run) == "ok"


async def test_the_end_sweep_leaves_a_run_taken_over_after_it_was_listed(
    db: AsyncSession, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await make_world(db)
    run = await make_run(db, w, status="ACTIVE", started_at=clock.now())
    clock.advance(timedelta(days=121))
    real_scalars = db.scalars

    async def list_then_take_over(stmt: Any, *a: Any, **kw: Any) -> Any:
        listed = await real_scalars(stmt, *a, **kw)
        ids = list(listed)
        # a person takes the run over between the sweep's list and its re-read
        await db.execute(
            update(AgentRun)
            .where(AgentRun.id == run.id)
            .values(status="TAKEN_OVER", substatus=None)
        )
        monkeypatch.setattr(db, "scalars", real_scalars)
        return iter(ids)

    monkeypatch.setattr(db, "scalars", list_then_take_over)
    assert await sweep_end_conditions(db) == 0
    await db.refresh(run)
    assert run.status == "TAKEN_OVER"


async def test_a_closed_subject_keeps_a_repeated_failure_pause_for_the_person(
    db: AsyncSession, clock: FrozenClock
) -> None:
    """Recovery from repeated failures is Take over → Hand back (user decision): the sweep must
    not swap that pause for subject_closed, which would block the takeover and auto-resume."""
    config = {
        **VOICE_CONFIG,
        "end_conditions": {**VOICE_CONFIG["end_conditions"], "on_subject_closed": "pause"},
    }
    w = await make_world(db, config=config)
    run = await make_run(
        db, w, status="PAUSED", substatus="repeated_failure", started_at=clock.now()
    )
    subject = await db.get_one(Subject, w.subject.id)
    subject.status = "closed"
    await db.commit()
    await sweep_end_conditions(db)
    await db.refresh(run)
    assert (run.status, run.substatus) == ("PAUSED", "repeated_failure")
    await control.takeover(db, run, user_id=w.user.id, remarks="I'll look at it")
