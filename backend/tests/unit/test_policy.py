from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from lucia.harness.exec.policy import (
    Allow,
    Defer,
    Deny,
    PolicyInput,
    Recipient,
    evaluate,
    window_end,
)
from lucia.mappings.schemas import PolicySource, ResolvedPolicy

NY = "America/New_York"


def _rule(
    rule: str, params: dict[str, object] | None = None, source: str = "version"
) -> ResolvedPolicy:
    return ResolvedPolicy(
        rule=rule,
        display_name=rule,
        description="",
        required=False,
        sources=[PolicySource(source=source, params=params or {}, applies=True)],  # type: ignore[arg-type]
    )


QUIET = _rule("quiet_hours", {"start": "20:00", "end": "08:00", "tz": "recipient"})


def _jane(**kw: object) -> Recipient:
    base: dict[str, object] = {
        "subject_contact_id": "sc",
        "contact_point_id": "cp",
        "role": "client",
        "channel": "voice",
        "consent": {"voice": "granted"},
        "opt_out": [],
        "tz": NY,
        "org_daily_cap": None,
        "address": "+1555",
    }
    return Recipient(**{**base, **kw})  # type: ignore[arg-type]


def _input(
    rules: list[ResolvedPolicy], now: datetime, recipient: Recipient | None = None, **kw: int
) -> PolicyInput:
    return PolicyInput(
        rules=rules,
        recipient=recipient or _jane(),
        firm_tz=NY,
        now=now,
        sent_today_subject=kw.get("subject", 0),
        sent_today_org=kw.get("org", 0),
    )


@pytest.mark.parametrize(
    ("hour", "minute", "deferred_until_hour"),
    [(19, 59, None), (20, 0, 8), (23, 30, 8), (3, 0, 8), (7, 59, 8), (8, 0, None), (12, 0, None)],
)
def test_quiet_hours_crossing_midnight(
    hour: int, minute: int, deferred_until_hour: int | None
) -> None:
    now = datetime(2026, 10, 1, hour, minute, tzinfo=ZoneInfo(NY)).astimezone(UTC)
    decision = evaluate(_input([QUIET], now))
    if deferred_until_hour is None:
        assert isinstance(decision, Allow)
    else:
        assert isinstance(decision, Defer) and decision.rule == "quiet_hours"
        until = decision.until.astimezone(ZoneInfo(NY))
        assert (until.hour, until.minute) == (deferred_until_hour, 0)
        assert until > now


def test_daytime_window_does_not_cross_midnight() -> None:
    assert window_end(datetime(2026, 10, 1, 10, 0), time(9), time(17)) == datetime(
        2026, 10, 1, 17, 0
    )
    assert window_end(datetime(2026, 10, 1, 18, 0), time(9), time(17)) is None


def test_contact_without_a_timezone_uses_the_firm_timezone() -> None:
    now = datetime(2026, 10, 1, 21, 0, tzinfo=ZoneInfo(NY)).astimezone(UTC)
    assert isinstance(evaluate(_input([QUIET], now, _jane(tz=None))), Defer)


@pytest.mark.parametrize(
    ("rules", "recipient", "rule"),
    [
        ([_rule("recipient_must_be_contact")], None, "recipient_must_be_contact"),
        (
            [_rule("consent_required", {"channel": ["voice"], "roles": ["client"]})],
            _jane(consent={}),
            "consent_required",
        ),
        (
            [_rule("consent_required", {"channel": ["voice"], "roles": ["client"]})],
            _jane(consent={"voice": "refused"}),
            "consent_required",
        ),
        ([_rule("opt_out_enforced")], _jane(opt_out=["voice"]), "opt_out_enforced"),
    ],
)
def test_static_rules_deny(
    rules: list[ResolvedPolicy], recipient: Recipient | None, rule: str
) -> None:
    inp = _input(rules, datetime(2026, 10, 1, 14, tzinfo=UTC), _jane())
    inp = inp.__class__(**{**inp.__dict__, "recipient": recipient})
    decision = evaluate(inp)
    assert isinstance(decision, Deny) and decision.rule == rule


def test_consent_applies_only_to_listed_roles_and_channels() -> None:
    rule = _rule("consent_required", {"channel": ["voice"], "roles": ["client"]})
    noon = datetime(2026, 10, 1, 16, tzinfo=UTC)
    assert isinstance(evaluate(_input([rule], noon, _jane(role="provider", consent={}))), Allow)
    assert isinstance(evaluate(_input([rule], noon, _jane(channel="email", consent={}))), Allow)


def test_deny_wins_over_defer() -> None:
    late = datetime(2026, 10, 2, 2, tzinfo=UTC)  # 22:00 in New York
    decision = evaluate(_input([QUIET, _rule("opt_out_enforced")], late, _jane(opt_out=["voice"])))
    assert isinstance(decision, Deny)


def test_caps_defer_to_the_next_local_day() -> None:
    noon = datetime(2026, 10, 1, 16, tzinfo=UTC)
    capped = evaluate(_input([_rule("per_subject_contact_cap", {"n": 2})], noon, subject=2))
    assert isinstance(capped, Defer) and capped.rule == "per_subject_contact_cap"
    assert capped.until.astimezone(ZoneInfo(NY)) == datetime(2026, 10, 2, 0, 0, tzinfo=ZoneInfo(NY))
    org = evaluate(_input([], noon, _jane(org_daily_cap=5), org=5))
    assert isinstance(org, Defer) and org.rule == "org_daily_cap"
    assert isinstance(
        evaluate(_input([_rule("per_subject_contact_cap", {"n": 2})], noon, subject=1)), Allow
    )


def test_a_mapping_override_replaces_the_version_params() -> None:
    rule = ResolvedPolicy(
        rule="per_subject_contact_cap",
        display_name="",
        description="",
        required=False,
        sources=[
            PolicySource(source="version", params={"n": 3}, applies=False),
            PolicySource(source="mapping", params={"n": 1}, applies=True),
        ],
    )
    assert isinstance(
        evaluate(_input([rule], datetime(2026, 10, 1, 16, tzinfo=UTC), subject=1)), Defer
    )
