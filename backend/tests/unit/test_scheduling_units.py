from datetime import timedelta

import pytest

from lucia.core.config import get_settings
from lucia.scheduling.durations import duration


def test_durations_are_real_by_default() -> None:
    assert duration(14, "days") == timedelta(days=14)
    assert duration(48, "hours") == timedelta(hours=48)


def test_durations_read_as_seconds_in_dev_time_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "schedule_time_unit", "seconds")
    assert duration(14, "days") == timedelta(seconds=14)
    assert duration(48, "hours") == timedelta(seconds=48)
    assert duration(90, "seconds") == timedelta(seconds=90)
