"""Thinking work as data, not code (D25): a planner writes a brief, an executor follows it as
its system prompt, a reviewer scores the result. One replan on a low score, then a person.
Text in, text out: subagents never call tools."""

from pydantic import BaseModel, Field

from lucia.harness.attention import raise_attention
from lucia.harness.steps import add_step, call_llm
from lucia.harness.tools.base import ToolContext, ToolResult

LOW_SCORE = 0.5
CONTINUE = "[CONTINUE]"
PLANNER = """Turn this work item into a brief for a writer. First decide whether it fits what
this agent is for (its description and use cases); if not, set in_scope false and stop."""
EXECUTOR_RULES = f"""Follow this brief exactly. Output only the result. If you run out of room,
end with {CONTINUE} and you will be asked to finish."""
REVIEWER = """Score the result against the brief from 0 (unusable) to 1 (perfect). List the
issues and say how to improve it."""


class SubBrief(BaseModel):
    in_scope: bool
    scope_reason: str
    what: str
    why: str
    inputs_used: list[str]
    output_format: str
    quality_bar: str


class Review(BaseModel):
    score: float = Field(ge=0, le=1)
    issues: list[str]
    improve_instructions: str


def _render(brief: SubBrief) -> str:
    return (
        f"{EXECUTOR_RULES}\n\n## what\n{brief.what}\n## why\n{brief.why}\n"
        f"## output format\n{brief.output_format}\n## quality bar\n{brief.quality_bar}"
    )


async def run_subagent(ctx: ToolContext) -> ToolResult:
    view, task, it = ctx.view, ctx.task, ctx.item
    run, models = view.run, view.config.models
    parent = await add_step(
        ctx.session,
        run,
        kind="subagent",
        tool="harness.subagent",
        status="RUNNING",
        idempotency_key=f"subagent:{task.id}:{it['id']}:{it['attempts']}",
        epoch=ctx.epoch,
        task_id=task.id,
        plan_item_id=it["id"],
        input={"title": it["title"], "hint": it["input_hint"]},
    )
    links = {"task_id": task.id, "plan_item_id": it["id"], "parent_step_id": parent.id}
    inputs = {u: (next(i for i in task.plan if i["id"] == u)["output"] or {}) for u in it["uses"]}
    work = (
        f"## agent\n{view.agent.description}\nUse cases: {', '.join(view.agent.use_cases)}\n"
        f"## task\n{task.title}: {task.goal}\n## item\n{it['title']}\n{it['input_hint']}\n"
        f"Expected: {it['expected_output']}\n## inputs\n{inputs}"
    )
    feedback = ""
    artifact, review = "", None
    for _ in range(2):
        brief = await call_llm(
            ctx.session,
            run,
            role="sub_planner",
            model=models.loop,
            instructions=PLANNER,
            message=work + feedback,
            output_type=SubBrief,
            epoch=ctx.epoch,
            **links,
        )
        if not brief.in_scope:
            parent.status = "SUCCEEDED"
            parent.output = {"in_scope": False, "reason": brief.scope_reason}
            await raise_attention(
                ctx.session,
                run,
                kind="out_of_scope",
                summary=f"{it['title']}: {brief.scope_reason}",
                dedup_key=f"sr:{task.id}:{it['id']}:out_of_scope",
                task_id=task.id,
                data={"item_id": it["id"]},
            )
            return ToolResult(status="SKIPPED", reason=f"out_of_scope: {brief.scope_reason}")
        artifact = await call_llm(
            ctx.session,
            run,
            role="sub_executor",
            model=models.loop,
            instructions=_render(brief),
            message=f"## inputs\n{inputs}",
            epoch=ctx.epoch,
            **links,
        )
        if artifact.endswith(CONTINUE):  # the one extra turn the executor may take
            more = await call_llm(
                ctx.session,
                run,
                role="sub_executor",
                model=models.loop,
                instructions=_render(brief),
                message=f"Finish this:\n{artifact}",
                epoch=ctx.epoch,
                **links,
            )
            artifact = artifact.removesuffix(CONTINUE) + more
        review = await call_llm(
            ctx.session,
            run,
            role="sub_reviewer",
            model=models.judge,
            instructions=REVIEWER,
            message=f"## brief\n{_render(brief)}\n\n## result\n{artifact}",
            output_type=Review,
            epoch=ctx.epoch,
            **links,
        )
        if review.score >= LOW_SCORE:
            parent.status, parent.output = "SUCCEEDED", {"score": review.score, "text": artifact}
            return ToolResult(status="SUCCEEDED", summary=artifact, step_id=parent.id)
        feedback = f"\n\n## reviewer feedback on the last attempt\n{review.improve_instructions}"
    assert review is not None
    parent.status, parent.output = "SUCCEEDED", {"score": review.score, "text": artifact}
    await raise_attention(
        ctx.session,
        run,
        kind="review_low",
        summary=f"{it['title']}: the draft scored {review.score:.2f} ({'; '.join(review.issues)})",
        dedup_key=f"sr:{task.id}:{it['id']}:review_low:{it['attempts']}",
        task_id=task.id,
        data={"item_id": it["id"], "draft": artifact},
        options=[
            {"value": "accept", "label": "Use this draft"},
            {"value": "retry", "label": "Try again"},
            {"value": "skip", "label": "Skip it"},
        ],
    )
    return ToolResult(status="NEEDS_HUMAN", summary=artifact, step_id=parent.id)
