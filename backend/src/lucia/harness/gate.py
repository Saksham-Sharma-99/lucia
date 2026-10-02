"""The deterministic gate before any work on a run (RUNTIME_SPEC §8.1): kill switch and end
conditions. Connector health is checked per send by the ToolExecutor."""

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.db.models import AgentPrompt, AgentRun, CompiledAgentFirmMapping, Subject
from lucia.db.models.run import CLAIMABLE
from lucia.harness.control import end_run, pause_for_subject, set_kill
from lucia.scheduling.durations import duration
from lucia.studio.config_schema import VersionConfig


async def gate(session: AsyncSession, run: AgentRun) -> Literal["ok", "paused", "ended"]:
    mapping = await session.get_one(CompiledAgentFirmMapping, run.mapping_id)
    if mapping.kill_switch:  # an inactive mapping only stops new runs: live ones finish
        await set_kill(session, mapping.id, True)
        await session.commit()
        return "paused"
    limits = VersionConfig.model_validate(
        (await session.get_one(AgentPrompt, run.agent_prompt_id)).config
    ).end_conditions
    started = run.started_at or get_clock().now()
    if run.step_count >= limits.max_steps:
        await end_run(session, run, "max_steps")
        return "ended"
    if get_clock().now() >= started + duration(limits.max_duration_days, "days"):
        await end_run(session, run, "max_duration")
        return "ended"
    subject = await session.get_one(Subject, run.subject_id)
    if subject.status == "closed":
        if limits.on_subject_closed == "end":
            await end_run(session, run, "subject_closed")
            return "ended"
        if run.status in CLAIMABLE:  # a run already paused keeps its reason (and its recovery)
            await pause_for_subject(session, run)
            await session.commit()
        return "paused"
    return "ok"
