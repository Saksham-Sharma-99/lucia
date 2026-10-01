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
