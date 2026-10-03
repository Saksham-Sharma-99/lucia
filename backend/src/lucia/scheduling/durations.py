"""Config durations become timedeltas here only, so the dev time scale applies everywhere
(SCHEDULE_TIME_UNIT=seconds: every duration is read as seconds, RUNTIME_SPEC §9.2)."""

from datetime import timedelta
from typing import Literal

from lucia.core.config import get_settings

Unit = Literal["seconds", "hours", "days"]
_SECONDS = {"seconds": 1, "hours": 3600, "days": 86400}


def duration(value: float, unit: Unit) -> timedelta:
    scale = 1 if get_settings().schedule_time_unit == "seconds" else _SECONDS[unit]
    return timedelta(seconds=value * scale)
