"""Land a human control (takeover, kill switch, end) while a scripted model call is in flight."""

import uuid
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import AgentRun
from lucia.llm.fake import FakeLLM

CONTROLS = [
    pytest.param({"status": "TAKEN_OVER", "substatus": None, "lease_epoch": 2}, id="takeover"),
    pytest.param({"status": "PAUSED", "substatus": "kill_switch", "lease_epoch": 2}, id="kill"),
    pytest.param({"status": "ENDED", "substatus": None}, id="end"),  # end_run: no epoch bump
]


def land_during(
    monkeypatch: pytest.MonkeyPatch,
    fake_llm: FakeLLM,
    db: AsyncSession,
    run_id: uuid.UUID,
    control_role: str,
    control: dict[str, Any],
) -> None:
    """The control commits while the first `role` call waits on the model, as another
    connection's would."""
    landed: list[bool] = []
    for name in ("structured", "tool_call", "text"):
        call = getattr(fake_llm, name)

        async def during(*, role: str, _call: Any = call, **kw: Any) -> Any:
            if role == control_role and not landed:  # lands before the model answers (or fails)
                landed.append(True)
                await db.execute(update(AgentRun).where(AgentRun.id == run_id).values(**control))
                await db.commit()
            return await _call(role=role, **kw)

        monkeypatch.setattr(fake_llm, name, during)
