"""Fixed-ladder and dynamic follow-ups after an outbound attempt that didn't reach anyone
(RUNTIME_SPEC §9.3). The ladder position lives in run_tasks.follow_up."""

from typing import Any

from lucia.studio.config_schema import LadderRung, VersionConfig


def next_rung(config: VersionConfig, state: dict[str, Any]) -> tuple[int, int, LadderRung] | None:
    """The (rung, attempt) after the current one; the first attempt is rung 0, attempt 1."""
    ladder = config.follow_up.ladder
    rung, attempt = state.get("rung", 0), state.get("attempt", 1)
    if rung < len(ladder) and attempt < ladder[rung].attempts:
        return rung, attempt + 1, ladder[rung]
    if rung + 1 < len(ladder):
        return rung + 1, 1, ladder[rung + 1]
    return None
