"""When new information reaches a task (an instruction, a hand-back, a call report), check
whether its remaining items still make sense (RUNTIME_SPEC §7.2)."""

from typing import Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import Episode, RunTask
from lucia.harness import context
from lucia.harness.agent_view import AgentView
from lucia.harness.planner import append
from lucia.harness.steps import call_llm

UNSETTLED = ("PENDING", "WAITING")  # items a new message may make moot
INSTRUCTIONS = """New information arrived for this task. For each remaining item, say keep,
skip (no longer needed) or supersede (needs to be done differently). Set append_needed when
the task needs items it doesn't have yet."""


class ItemVerdict(BaseModel):
    item_id: str
    verdict: Literal["keep", "skip", "supersede"]
    reason: str


class Relevance(BaseModel):
    verdicts: list[ItemVerdict]
    append_needed: bool
    append_reason: str


async def check(
    session: AsyncSession, view: AgentView, task: RunTask, episode: Episode, epoch: int
) -> None:
    new_info = str(await context.trigger(session, episode))
    if not any(i["status"] in UNSETTLED for i in task.plan):
        await append(session, view, task, reason="new input", new_info=new_info, epoch=epoch)
        return
    result = await call_llm(
        session,
        view.run,
        role="relevance",
        model=view.config.models.guardrail,
        instructions=INSTRUCTIONS,
        message=context.packet(
            "relevance",
            {
                "task": {"title": task.title, "goal": task.goal},
                "plan": task.plan,
                "trigger": new_info,
            },
        ),
        output_type=Relevance,
        epoch=epoch,
        task_id=task.id,
        episode_id=episode.id,
    )
    open_ids = {i["id"] for i in task.plan if i["status"] in UNSETTLED}
    verdicts = {v.item_id: v for v in result.verdicts if v.item_id in open_ids}
    task.plan = [
        {**i, "status": "SKIPPED", "reason": verdicts[i["id"]].reason}
        if verdicts.get(i["id"]) and verdicts[i["id"]].verdict == "skip"
        else i
        for i in task.plan
    ]
    await session.commit()
    supersede = [i for i, v in verdicts.items() if v.verdict == "supersede"]
    if supersede or result.append_needed:
        reason = result.append_reason or "; ".join(verdicts[i].reason for i in supersede)
        await append(
            session, view, task, reason=reason, new_info=new_info, epoch=epoch, supersede=supersede
        )
