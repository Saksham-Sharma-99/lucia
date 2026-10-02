from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import FrozenClock
from lucia.db.models import AgentRunStep, Episode, StepResult
from lucia.harness.executor import execute_task, resume_task
from lucia.harness.subagent import Review, SubBrief
from lucia.llm.fake import FakeLLM
from tests.world import item, make_leased_run, make_task, make_world


def _brief(in_scope: bool = True) -> SubBrief:
    return SubBrief(
        in_scope=in_scope,
        scope_reason="fits check-ins" if in_scope else "negotiation",
        what="Write a call script",
        why="To check in",
        inputs_used=[],
        output_format="plain text",
        quality_bar="Warm, under 150 words",
    )


def _review(score: float) -> Review:
    return Review(
        score=score,
        issues=[] if score >= 0.5 else ["mentions a diagnosis"],
        improve_instructions="" if score >= 0.5 else "Drop clinical details",
    )


async def _run(db: AsyncSession, fake_llm: FakeLLM, *scripted: tuple[str, Any]) -> Any:
    w = await make_world(db)
    run = await make_leased_run(db, w)
    task = await make_task(db, w, run, plan=[item(1, "subagent", title="Draft the script")])
    for role, out in scripted:
        fake_llm.on(role, out)
    outcome = await execute_task(db, run, task, 1)
    await db.refresh(task)
    return w, run, task, outcome


async def test_planner_executor_reviewer_produce_the_item_output(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, _, task, outcome = await _run(
        db,
        fake_llm,
        ("sub_planner", _brief()),
        ("sub_executor", "Hi Jane, it's Lucia..."),
        ("sub_reviewer", _review(0.8)),
    )
    assert outcome == "done"
    assert task.plan[0]["output"]["summary"] == "Hi Jane, it's Lucia..."
    parent = await db.scalar(select(AgentRunStep).where(AgentRunStep.kind == "subagent"))
    assert parent is not None and parent.output["score"] == 0.8
    children = list(
        await db.scalars(select(AgentRunStep.role).where(AgentRunStep.parent_step_id == parent.id))
    )
    assert sorted(c or "" for c in children) == ["sub_executor", "sub_planner", "sub_reviewer"]
    executor_prompt = fake_llm.instructions[[r for r, _ in fake_llm.calls].index("sub_executor")]
    assert "Warm, under 150 words" in executor_prompt


async def test_low_score_replans_once(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, _, task, outcome = await _run(
        db,
        fake_llm,
        ("sub_planner", _brief()),
        ("sub_executor", "v1"),
        ("sub_reviewer", _review(0.3)),
        ("sub_planner", _brief()),
        ("sub_executor", "v2"),
        ("sub_reviewer", _review(0.7)),
    )
    assert outcome == "done" and task.plan[0]["output"]["summary"] == "v2"
    replan = [m for r, m in fake_llm.calls if r == "sub_planner"][1]
    assert "Drop clinical details" in replan


async def test_low_score_twice_asks_a_person(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    w, run, task, outcome = await _run(
        db,
        fake_llm,
        ("sub_planner", _brief()),
        ("sub_executor", "v1"),
        ("sub_reviewer", _review(0.3)),
        ("sub_planner", _brief()),
        ("sub_executor", "v2"),
        ("sub_reviewer", _review(0.2)),
    )
    assert outcome == "blocked" and task.status == "BLOCKED"
    review = await db.scalar(select(StepResult))
    assert review is not None and review.kind == "review_low"
    assert {o["value"] for o in review.options} == {"accept", "retry", "skip"}
    # accept keeps the last draft
    ep = Episode(
        firm_id=w.firm.id,
        run_id=run.id,
        task_id=task.id,
        trigger_type="user_response",
        status="running",
        lease_epoch=1,
        dedup_key="answer:1",
        metadata_={"step_result_id": str(review.id), "answer": {"choice": "accept"}},
    )
    db.add(ep)
    await db.commit()
    await resume_task(db, run, task, ep, 1)
    await db.refresh(task)
    assert task.status == "DONE" and task.plan[0]["output"]["summary"] == "v2"


async def test_out_of_scope_work_is_not_done(
    db: AsyncSession, clock: FrozenClock, fake_llm: FakeLLM
) -> None:
    _, _, task, outcome = await _run(db, fake_llm, ("sub_planner", _brief(in_scope=False)))
    assert outcome == "done" and task.plan[0]["status"] == "SKIPPED"
    item_ = await db.scalar(select(StepResult))
    assert item_ is not None and item_.kind == "out_of_scope"
    assert [r for r, _ in fake_llm.calls] == ["sub_planner"]


@pytest.mark.parametrize("score", [-0.1, 1.5])
def test_review_score_is_bounded(score: float) -> None:
    with pytest.raises(ValueError):
        Review(score=score, issues=[], improve_instructions="")
