"""A person's answer to an attention item, from any channel (DATA_MODEL §3.12)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.clock import get_clock
from lucia.core.errors import FieldError, ProblemError, conflict, invalid, not_found
from lucia.db.models import AgentRun, StepResult
from lucia.harness.attention import RESUMES_TASK
from lucia.harness.completion import confirm
from lucia.harness.control import end_run
from lucia.harness.intake import EpisodeSpec, insert_episode
from lucia.worker.dispatch import send


async def answer(
    session: AsyncSession,
    item_id: uuid.UUID,
    *,
    choice: str | None,
    text: str | None,
    answered_by: dict[str, str],
) -> StepResult:
    """First answer wins (compare-and-set on `open`); every channel answers through here."""
    item = await session.scalar(
        select(StepResult).where(StepResult.id == item_id).with_for_update()
    )
    if item is None or item.type != "attention":  # findings are read, not answered
        raise not_found("Attention item")
    if item.status != "open":
        raise conflict("This item was already answered")
    values = {o["value"] for o in item.options}
    if choice is not None and values and choice not in values:
        raise _invalid("/choice", "unknown", "Not one of the options")
    if not choice and not text:
        raise _invalid("/text", "required", "Pick an option or type an answer")
    if choice == "reopen" and not text:
        raise _invalid("/text", "required", "Say what's still needed")
    item.status = "answered"
    item.answer = {"choice": choice, "text": text}
    item.answered_by, item.answered_at = answered_by, get_clock().now()
    run = await session.get_one(AgentRun, item.run_id) if item.run_id else None
    wake = False  # the run has new work once this commits
    if run is not None and choice == "end_run":  # offered only where ending is the answer
        await end_run(session, run, "closed_by_person")
    elif run is not None and item.kind == "confirm_completion":
        await confirm(session, run, item, choice=choice or "confirm", text=text)
        wake = choice == "reopen"
    elif run is not None and item.kind in RESUMES_TASK:
        wake = bool(
            await insert_episode(
                session,
                run,
                EpisodeSpec(
                    trigger_type="user_response",
                    dedup_key=f"answer:{item.id}",
                    metadata={"step_result_id": str(item.id), "answer": item.answer},
                    task_id=item.task_id,
                ),
            )
        )
    await session.commit()
    if run is not None and wake:
        send("harness.advance_run", run.id)
    return item


def _invalid(path: str, code: str, message: str) -> ProblemError:
    return invalid([FieldError(path=path, code=code, message=message)])
