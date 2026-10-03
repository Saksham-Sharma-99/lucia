from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import (
    AgentRun,
    AgentRunStep,
    Conversation,
    Episode,
    Message,
    RunTask,
    StepResult,
)
from lucia.harness.keys import TargetRef
from lucia.harness.triage import OutOfScope, SameTask, TriageOp, TriageResult, run_triage
from lucia.llm.fake import FakeLLM
from tests.world import World, make_leased_run, make_world


def _op(op: str = "create", **kw: Any) -> TriageOp:
    base: dict[str, Any] = {
        "op": op,
        "task_id": None,
        "kind": "call_client",
        "target": None,
        "title": "Call Jane",
        "goal": "Check in with Jane",
        "input_note": None,
        "depends_on_keys": [],
        "reason": "asked",
    }
    return TriageOp(**{**base, **kw})


def _result(*ops: TriageOp, **kw: Any) -> TriageResult:
    base: dict[str, Any] = {
        "ops": list(ops),
        "out_of_scope": [],
        "goal": "Check in with Jane",
        "criteria": "A completed call",
        "reply": "On it.",
    }
    return TriageResult(**{**base, **kw})


async def _episode(
    db: AsyncSession, w: World, run: AgentRun, key: str = "msg:1", **kw: Any
) -> Episode:
    conv = Conversation(firm_id=w.firm.id, channel="playground", subject_id=w.subject.id)
    db.add(conv)
    await db.flush()
    msg = Message(
        firm_id=w.firm.id,
        conversation_id=conv.id,
        direction="inbound",
        actor="human",
        body="@checkin call Jane for her check-in",
        status="received",
    )
    db.add(msg)
    await db.flush()
    fields: dict[str, Any] = {
        "trigger_type": "user_input",
        "status": "running",
        "lease_epoch": 1,
        "metadata_": {
            "message_id": str(msg.id),
            "conversation_id": str(conv.id),
            "brief": {"goal": "check in"},
        },
        **kw,
    }
    ep = Episode(firm_id=w.firm.id, run_id=run.id, dedup_key=key, **fields)
    db.add(ep)
    await db.commit()
    return ep


def _jane(w: World) -> TargetRef:
    return TargetRef(type="contact", ref=str(w.jane_link.id))


async def test_first_triage_creates_tasks_sets_goal_and_replies(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    ep = await _episode(db, w, run)
    fake_llm.on("triage", _result(_op(target=_jane(w))))
    await run_triage(db, run, ep, 1)
    task = await db.scalar(select(RunTask))
    assert task is not None
    assert (task.key, task.status, task.created_by, task.origin_episode_id) == (
        f"call-client:contact-{str(w.jane_link.id)[:8]}",
        "TODO",
        "triage",
        ep.id,
    )
    await db.refresh(run)
    assert (run.goal, run.completion_criteria) == ("Check in with Jane", "A completed call")
    reply = await db.scalar(select(Message).where(Message.actor == "agent"))
    assert reply is not None and reply.body == "On it."
    assert "## conversation" in fake_llm.calls[0][1]


async def test_create_with_an_existing_key_updates_instead(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w, goal="g", completion_criteria="c")
    fake_llm.on("triage", _result(_op(target=_jane(w))))
    first = await _episode(db, w, run, "msg:1")
    await run_triage(db, run, first, 1)
    first.status = "completed"
    await db.commit()
    fake_llm.on("triage", _result(_op(target=_jane(w), goal="Also ask about the new doctor")))
    await run_triage(db, run, await _episode(db, w, run, "msg:2"), 1)
    tasks = list(await db.scalars(select(RunTask)))
    assert len(tasks) == 1 and tasks[0].goal == "Also ask about the new doctor"


async def test_contact_target_must_be_on_the_subject(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w, goal="g", completion_criteria="c")
    bad = TargetRef(type="contact", ref="00000000-0000-0000-0000-000000000000")
    fake_llm.on("triage", _result(_op(target=bad)), _result(_op(target=_jane(w))))
    await run_triage(db, run, await _episode(db, w, run), 1)
    assert "not a contact on this subject" in fake_llm.calls[1][1]
    assert await db.scalar(select(RunTask.key)) is not None


async def test_still_invalid_after_retry_drops_the_op(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w, goal="g", completion_criteria="c")
    bad = TargetRef(type="contact", ref="nope")
    fake_llm.on("triage", _result(_op(target=bad)), _result(_op(target=bad)))
    await run_triage(db, run, await _episode(db, w, run), 1)
    assert await db.scalar(select(RunTask)) is None


async def test_near_duplicate_key_is_confirmed_as_the_same_task(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w, goal="g", completion_criteria="c")
    db.add(
        RunTask(
            firm_id=w.firm.id,
            run_id=run.id,
            key="request-records:ext-st-marys",
            kind="request_records",
            target={"type": "external", "ref": "st-marys"},
            title="t",
            goal="old",
            created_by="triage",
        )
    )
    await db.commit()
    fake_llm.on(
        "triage",
        _result(
            _op(
                kind="request_records",
                target=TargetRef(type="external", ref="st marys"),
                goal="new",
            )
        ),
    )
    fake_llm.on("triage", SameTask(same=True))
    await run_triage(db, run, await _episode(db, w, run), 1)
    tasks = list(await db.scalars(select(RunTask)))
    assert [(t.key, t.goal) for t in tasks] == [("request-records:ext-st-marys", "new")]


async def test_cancel_skips_the_task_and_supersedes_its_items(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w, goal="g", completion_criteria="c")
    task = RunTask(
        firm_id=w.firm.id,
        run_id=run.id,
        key="call:run",
        kind="call",
        target={"type": "run", "ref": None},
        title="t",
        goal="g",
        created_by="triage",
        status="WAITING",
        plan=[{"id": "i1", "status": "DONE"}, {"id": "i2", "status": "WAITING"}],
    )
    db.add(task)
    await db.commit()
    fake_llm.on("triage", _result(_op("cancel", task_id=str(task.id), reason="user said stop")))
    await run_triage(db, run, await _episode(db, w, run), 1)
    await db.refresh(task)
    assert task.status == "SKIPPED"
    assert [i["status"] for i in task.plan] == ["DONE", "SUPERSEDED"]


async def test_update_of_a_planned_task_queues_a_relevance_episode(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w, goal="g", completion_criteria="c")
    task = RunTask(
        firm_id=w.firm.id,
        run_id=run.id,
        key="call:run",
        kind="call",
        target={"type": "run", "ref": None},
        title="t",
        goal="g",
        created_by="triage",
        status="WAITING",
        plan=[{"id": "i1", "status": "PENDING"}],
    )
    db.add(task)
    await db.commit()
    fake_llm.on(
        "triage", _result(_op("update", task_id=str(task.id), input_note="ask about bills"))
    )
    ep = await _episode(db, w, run)
    await run_triage(db, run, ep, 1)
    follow = await db.scalar(select(Episode).where(Episode.task_id == task.id))
    assert follow is not None and (follow.status, follow.trigger_type) == ("pending", "user_input")
    assert follow.metadata_["message_id"] == ep.metadata_["message_id"]
    await db.refresh(task)
    assert task.input["notes"] == ["ask about bills"]


async def test_out_of_scope_raises_attention_and_later_criteria_change_is_recorded(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w, goal="g", completion_criteria="old criteria")
    fake_llm.on(
        "triage",
        _result(
            out_of_scope=[OutOfScope(request="negotiate the bill", reason="no such capability")],
            goal=None,
            criteria="new criteria",
        ),
    )
    await run_triage(db, run, await _episode(db, w, run), 1)
    item = await db.scalar(select(StepResult))
    assert item is not None and (item.kind, item.blocking) == ("out_of_scope", False)
    step = await db.scalar(
        select(AgentRunStep).where(AgentRunStep.tool == "harness.run.amend_criteria")
    )
    assert step is not None and step.input == {"old": "old criteria", "new": "new criteria"}
    await db.refresh(run)
    assert run.completion_criteria == "new criteria"


async def test_recurrence_creates_the_cycle_task_without_the_model(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(
        db, w, goal="Check in every two weeks", completion_criteria="c", cycle=2
    )
    ep = Episode(
        firm_id=w.firm.id,
        run_id=run.id,
        trigger_type="scheduled",
        source="recurrence",
        status="running",
        lease_epoch=1,
        dedup_key="recurrence:x:3",
        metadata_={"cycle": 3},
    )
    db.add(ep)
    await db.commit()
    await run_triage(db, run, ep, 1)
    await run_triage(db, run, ep, 1)  # the Episode replayed after a crash
    task = await db.scalar(select(RunTask))
    assert task is not None and (task.key, task.created_by, task.goal) == (
        "checkin:cycle-3",
        "recurrence",
        "Check in every two weeks",
    )
    await db.refresh(run)
    assert run.cycle == 3 and fake_llm.calls == []


async def test_dependencies_on_unknown_tasks_are_dropped(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    ep = await _episode(db, w, run)
    first = _op(kind="gather_records", target=TargetRef(type="run", ref=None), title="Records")
    second = _op(
        target=_jane(w), depends_on_keys=["gather-records:run", "made-up:run", "call-client:x"]
    )
    fake_llm.on("triage", _result(first, second))
    await run_triage(db, run, ep, 1)
    task = await db.scalar(select(RunTask).where(RunTask.kind == "call_client"))
    assert task is not None and task.depends_on == ["gather-records:run"]
