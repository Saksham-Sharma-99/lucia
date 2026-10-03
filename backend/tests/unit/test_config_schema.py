import pytest
from pydantic import ValidationError

from lucia.studio.config_schema import VersionConfig
from tests.factories import config


def test_valid_config_round_trips() -> None:
    stored = VersionConfig.model_validate(config()).stored()
    assert stored["max_turns_per_episode"] == 12
    assert "task_templates" not in stored


@pytest.mark.parametrize("key", ["task_templates", "finding_schema", "state_schema"])
def test_reserved_keys_rejected(key: str) -> None:
    with pytest.raises(ValidationError) as exc:
        VersionConfig.model_validate(config(**{key: []}))
    err = exc.value.errors()[0]
    assert err["loc"] == (key,) and err["type"] == "reserved"


def test_unknown_key_rejected() -> None:
    with pytest.raises(ValidationError):
        VersionConfig.model_validate(config(success_criteria="x"))


def test_bounds() -> None:
    with pytest.raises(ValidationError):
        VersionConfig.model_validate(config(max_turns_per_episode=51))
    with pytest.raises(ValidationError):
        VersionConfig.model_validate(config(capabilities=[]))


def test_rung_needs_exactly_one_of_channel_or_action() -> None:
    bad = {
        "mode": "fixed_ladder",
        "ladder": [{"channel": "email", "action": "flag", "wait_hours": 1}],
    }
    with pytest.raises(ValidationError):
        VersionConfig.model_validate(config(follow_up=bad))


def test_waits_and_recurrence_take_decimals_for_minute_scale_schedules() -> None:
    follow_up = {"mode": "fixed_ladder", "ladder": [{"channel": "voice", "wait_hours": 0.1}]}
    cfg = VersionConfig.model_validate(
        config(follow_up=follow_up, recurrence={"every_days": 0.005})
    ).stored()
    assert cfg["follow_up"]["ladder"][0]["wait_hours"] == 0.1  # 6 minutes
    assert cfg["recurrence"] == {"every_days": 0.005}  # ~7 minutes
    with pytest.raises(ValidationError):
        VersionConfig.model_validate(config(recurrence={"every_days": 0}))


def test_whole_numbers_stay_ints_so_stored_hashes_dont_change() -> None:
    stored = VersionConfig.model_validate(config(recurrence={"every_days": 14})).stored()
    assert stored["recurrence"]["every_days"] == 14
    assert isinstance(stored["recurrence"]["every_days"], int)
