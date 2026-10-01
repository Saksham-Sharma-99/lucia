from typing import Any

from lucia.mappings.schemas import Overrides
from lucia.mappings.tighten import _looser, check_overrides, min_wait_hours, window_minutes
from tests.factories import config, snapshot

CFG = config(
    policy_pack=[
        {"rule": "recipient_must_be_contact", "params": {}},
        {"rule": "per_subject_contact_cap", "params": {"n": 3}},
        {"rule": "quiet_hours", "params": {"start": "20:00", "end": "08:00", "tz": "recipient"}},
        {"rule": "consent_required", "params": {"channel": ["email"], "roles": ["client"]}},
    ]
)


def codes(overrides: dict[str, Any], floor: list[dict[str, Any]] | None = None) -> list[str]:
    errs = check_overrides(Overrides.model_validate(overrides), CFG, floor or [], snapshot())
    return [f"{e.path}:{e.code}" for e in errs]


def test_window_wraps_midnight() -> None:
    assert 23 * 60 in window_minutes("20:00", "08:00")
    assert 12 * 60 not in window_minutes("20:00", "08:00")


def test_stricter_overrides_pass() -> None:
    assert (
        codes(
            {
                "policy_params": {
                    "per_subject_contact_cap": {"n": 2},
                    "quiet_hours": {"start": "19:00", "end": "09:00", "tz": "recipient"},
                    "consent_required": {"channel": ["email", "voice"], "roles": ["client"]},
                },
                "cadence": {"min_wait_hours": 72},
            }
        )
        == []
    )


def test_looser_overrides_fail() -> None:
    p = "/overrides/policy_params"
    assert codes(
        {
            "policy_params": {
                "per_subject_contact_cap": {"n": 5},
                "quiet_hours": {"start": "21:00", "end": "08:00", "tz": "recipient"},
                "consent_required": {"channel": ["voice"], "roles": ["client"]},
                "opt_out_enforced": {},
            }
        }
    ) == [
        f"{p}/per_subject_contact_cap:looser",
        f"{p}/quiet_hours:looser",
        f"{p}/consent_required:looser",
        f"{p}/opt_out_enforced:not_in_policy",
    ]


def test_cadence_can_only_increase() -> None:
    assert min_wait_hours(CFG) == 48
    assert codes({"cadence": {"min_wait_hours": 24}}) == [
        "/overrides/cadence/min_wait_hours:looser"
    ]


def test_firm_floor_is_a_baseline_too() -> None:
    floor = [
        {"rule": "per_subject_contact_cap", "params": {"n": 1}},
        {"rule": "opt_out_enforced", "params": {}},
    ]
    assert codes(
        {"policy_params": {"per_subject_contact_cap": {"n": 2}, "opt_out_enforced": {}}}, floor
    ) == ["/overrides/policy_params/per_subject_contact_cap:looser"]


def test_invalid_params_rejected() -> None:
    assert codes({"policy_params": {"per_subject_contact_cap": {"n": "x"}}}) == [
        "/overrides/policy_params/per_subject_contact_cap:invalid_params"
    ]


def test_attachment_roles_can_only_shrink() -> None:
    floor = [{"rule": "attachment_allowed", "params": {"hipaa_auth": ["provider", "client"]}}]
    ok = codes({"policy_params": {"attachment_allowed": {"hipaa_auth": ["provider"]}}}, floor)
    bad = codes(
        {"policy_params": {"attachment_allowed": {"hipaa_auth": ["insurer"], "bills": ["client"]}}},
        floor,
    )
    assert ok == [] and bad == ["/overrides/policy_params/attachment_allowed:looser"]


def test_quiet_hours_tz_must_match() -> None:
    assert codes(
        {"policy_params": {"quiet_hours": {"start": "19:00", "end": "09:00", "tz": "firm"}}}
    ) == ["/overrides/policy_params/quiet_hours:looser"]


def test_looser_generic_param_types() -> None:
    assert _looser("x", {"flag": True}, {"flag": False}) is not None
    assert _looser("x", {"flag": False}, {"flag": True}) is None
    assert _looser("x", {"cap": 2.5}, {"cap": 3}) is not None
    assert _looser("x", {"roles": ["a"]}, {"roles": ["a", "b"]}) is None
    assert _looser("x", {"cap": 2}, {}) is None  # omitted keys keep the baseline


def test_window_edges() -> None:
    assert window_minutes("08:00", "08:00") == set()
    assert len(window_minutes("00:00", "23:59")) == 23 * 60 + 59


def test_min_wait_per_follow_up_mode() -> None:
    dyn = {"follow_up": {"mode": "dynamic", "dynamic": {"min_hours": 30}}}
    assert min_wait_hours(dyn) == 30
    assert min_wait_hours({"follow_up": {"mode": "none"}}) == 0
    rungs = {
        "follow_up": {
            "ladder": [{"action": "flag", "wait_hours": 1}, {"channel": "email", "wait_hours": 5}]
        }
    }
    assert min_wait_hours(rungs) == 5


def test_empty_quiet_window_is_the_loosest() -> None:
    cfg = config(
        policy_pack=[
            {"rule": "recipient_must_be_contact", "params": {}},
            {"rule": "quiet_hours", "params": {"start": "08:00", "end": "08:00", "tz": "firm"}},
        ]
    )
    widen = Overrides.model_validate(
        {"policy_params": {"quiet_hours": {"start": "20:00", "end": "08:00", "tz": "firm"}}}
    )
    assert check_overrides(widen, cfg, [], snapshot()) == []
    narrow = Overrides.model_validate(
        {"policy_params": {"quiet_hours": {"start": "09:00", "end": "09:00", "tz": "recipient"}}}
    )
    assert [e.code for e in check_overrides(narrow, CFG, [], snapshot())] == ["looser"]


def test_missing_required_params_are_invalid_not_500() -> None:
    assert codes({"policy_params": {"quiet_hours": {"start": "21:00"}}}) == [
        "/overrides/policy_params/quiet_hours:invalid_params"
    ]


def test_list_rule_dropping_an_entry_is_looser() -> None:
    assert codes(
        {"policy_params": {"consent_required": {"channel": ["voice"], "roles": ["client"]}}}
    ) == ["/overrides/policy_params/consent_required:looser"]
