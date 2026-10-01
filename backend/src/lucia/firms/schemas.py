import uuid
from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import available_timezones

from pydantic import AfterValidator, Field

from lucia.core.schema import HHMM, AlertChannel, PolicyRuleRef, Read, Strict, Urgency
from lucia.db.models.firm import FirmStatus

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _known_tz(value: str) -> str:
    if value not in available_timezones():
        raise ValueError("Unknown IANA timezone")
    return value


Timezone = Annotated[str, AfterValidator(_known_tz)]
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Name = Annotated[str, Field(min_length=1, max_length=120)]


class Window(Strict):
    start: str = Field(pattern=HHMM)
    end: str = Field(pattern=HHMM)


_WORK = Window(start="09:00", end="18:00")


class FirmSettings(Strict):
    business_hours: dict[Weekday, Window | None] = {
        "mon": _WORK,
        "tue": _WORK,
        "wed": _WORK,
        "thu": _WORK,
        "fri": _WORK,
        "sat": None,
        "sun": None,
    }
    quiet_hours: Window | None = Window(start="20:00", end="08:00")
    alert_routing: dict[Urgency, list[AlertChannel]] = {}
    policy_floor: list[PolicyRuleRef] = []


class FirmCreate(Strict):
    name: Name
    slug: str = Field(pattern=r"^[a-z0-9-]{2,40}$")
    timezone: Timezone
    color: Color
    settings: FirmSettings = FirmSettings()


class FirmPatch(Strict):
    """Slug is immutable, so it is not accepted here."""

    name: Name | None = None
    timezone: Timezone | None = None
    color: Color | None = None
    settings: FirmSettings | None = None


class FirmOut(Read):
    id: uuid.UUID
    name: str
    slug: str
    timezone: str
    status: FirmStatus
    color: str
    settings: FirmSettings
    created_at: datetime
    updated_at: datetime


class FirmDetail(FirmOut):
    connection_counts: dict[str, int]
    mapping_counts: dict[str, int]
