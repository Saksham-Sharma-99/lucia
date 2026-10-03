from zoneinfo import available_timezones

from pydantic import BaseModel

from lucia.api.tags import api_router
from lucia.connectors import gmail, slack, vapi
from lucia.core.config import get_settings

router = api_router("platform", "/platform")


class PlatformStatus(BaseModel):
    slack: bool
    google: bool
    vapi: bool
    public_base_url: str
    allowed_models: list[str]
    drafter_enabled: bool


@router.get(
    "/status", summary="Which platform app registrations are set", operation_id="getPlatformStatus"
)
async def platform_status() -> PlatformStatus:
    s = get_settings()
    return PlatformStatus(
        slack=slack.configured(),
        google=gmail.configured(),
        vapi=vapi.configured(),
        public_base_url=s.public_base_url,
        allowed_models=s.allowed_models,
        drafter_enabled=bool(s.openai_api_key),
    )


# Region/City zones only: legacy aliases (US/Eastern, Etc/GMT+5, ...) stay valid but aren't offered.
_REGIONS = (
    "Africa/",
    "America/",
    "Antarctica/",
    "Asia/",
    "Atlantic/",
    "Australia/",
    "Europe/",
    "Indian/",
    "Pacific/",
)


@router.get("/timezones", summary="IANA timezones to pick from", operation_id="listTimezones")
async def timezones() -> list[str]:
    return [*sorted(z for z in available_timezones() if z.startswith(_REGIONS)), "UTC"]
