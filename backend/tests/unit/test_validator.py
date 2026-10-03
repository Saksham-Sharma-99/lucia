from typing import Any

import pytest

from lucia.studio.config_schema import VersionConfig
from lucia.studio.schemas import AgentCreate
from lucia.studio.templates import TEMPLATES
from lucia.studio.validator import validate_config
from tests.factories import ALLOWED, config, snapshot


def errors(cfg: dict[str, Any]) -> list[tuple[str, str]]:
    found = validate_config(VersionConfig.model_validate(cfg), snapshot(), ALLOWED)
    return [(e.path, e.code) for e in found]


def test_base_config_is_valid() -> None:
    assert errors(config()) == []


@pytest.mark.parametrize("spec", TEMPLATES, ids=lambda s: s.handle)
def test_seeded_agents_are_valid(spec: AgentCreate) -> None:
    assert errors(spec.config.stored()) == []


def test_unknown_and_unavailable_connectors() -> None:
    caps = [
        {"connector": "nope", "tools": ["x.y"]},
        {"connector": "fax", "tools": ["fax.send_fax"]},
    ]
    assert errors(config(capabilities=caps, follow_up={"mode": "none"})) == [
        ("/capabilities/0/connector", "unknown_connector"),
        ("/capabilities/1/connector", "unknown_connector"),
    ]


def test_tool_must_belong_to_connector_and_be_unique() -> None:
    caps = [
        {
            "connector": "gmail",
            "tools": ["gmail.send_email", "slack.send_message", "gmail.send_email", "gmail.nope"],
        }
    ]
    assert errors(config(capabilities=caps)) == [
        ("/capabilities/0/tools/1", "wrong_connector"),
        ("/capabilities/0/tools/2", "duplicate"),
        ("/capabilities/0/tools/3", "unknown_tool"),
    ]


def test_policy_params_validated_against_schema() -> None:
    pack = [
        {"rule": "recipient_must_be_contact"},
        {"rule": "per_subject_contact_cap", "params": {"n": 0}},
        {"rule": "quiet_hours", "params": {"start": "25:00", "end": "08:00", "tz": "firm"}},
        {"rule": "made_up"},
    ]
    assert errors(config(policy_pack=pack)) == [
        ("/policy_pack/1/params/n", "invalid_params"),
        ("/policy_pack/2/params/start", "invalid_params"),
        ("/policy_pack/3/rule", "unknown_rule"),
    ]


def test_ladder_channel_needs_send_tool() -> None:
    fu = {"mode": "fixed_ladder", "ladder": [{"channel": "voice", "wait_hours": 1}]}
    assert errors(config(follow_up=fu)) == [("/follow_up/ladder/0/channel", "channel_tool_missing")]


def test_empty_ladder_and_dynamic_bounds() -> None:
    assert ("/follow_up/ladder", "required") in errors(
        config(follow_up={"mode": "fixed_ladder", "ladder": []})
    )
    dyn = {
        "mode": "dynamic",
        "dynamic": {
            "min_hours": 50,
            "max_hours": 10,
            "channels": ["email"],
            "escalate_after": {"attempts": 2, "urgency": "P1"},
        },
    }
    assert errors(config(follow_up=dyn)) == [("/follow_up/dynamic/min_hours", "min_gt_max")]


def test_external_tool_requires_minimum_pack() -> None:
    assert errors(config(policy_pack=[])) == [("/policy_pack", "min_pack")]


def test_alert_policy_and_models() -> None:
    cfg = config(
        alert_policy={"urgency_mode": "fixed", "default_channels": {"P0": ["pager"]}},
        models={"loop": "gpt-5.6-sol", "guardrail": "other", "judge": "gpt-5.6"},
    )
    assert errors(cfg) == [
        ("/alert_policy/fixed_urgency", "required"),
        ("/alert_policy/default_channels/P0/0", "unknown_alert_channel"),
        ("/models/guardrail", "model_not_allowed"),
    ]
