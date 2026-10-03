from datetime import UTC, datetime, timedelta

from lucia.core.clock import FrozenClock, SystemClock, get_clock, set_clock


def test_system_clock_is_utc() -> None:
    assert SystemClock().now().tzinfo is UTC


def test_frozen_clock_advances_and_is_installed_globally() -> None:
    start = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
    clock = FrozenClock(start)
    set_clock(clock)
    try:
        clock.advance(timedelta(minutes=5))
        assert get_clock().now() == start + timedelta(minutes=5)
    finally:
        set_clock(None)
    assert isinstance(get_clock(), SystemClock)
