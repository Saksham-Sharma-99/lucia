import pytest
from pydantic import ValidationError

from lucia.core.config import Settings

KEY = "hmJ4Qp1P1ywJcAb8GtvzI7Hh4b6m4yKqk1r3kkQf6uU="  # test-only  # gitleaks:allow


def test_seconds_time_unit_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="schedule_time_unit"):
        Settings(env="production", schedule_time_unit="seconds", secret_key=KEY)


def test_vapi_without_webhook_secret_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="VAPI_WEBHOOK_SECRET"):
        Settings(env="production", vapi_api_key="k", vapi_webhook_secret="", secret_key=KEY)


def test_seconds_time_unit_is_allowed_outside_production() -> None:
    assert Settings(
        env="test", schedule_time_unit="seconds", secret_key=KEY
    ).schedule_time_unit == ("seconds")
