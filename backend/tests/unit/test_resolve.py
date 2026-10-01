from lucia.mappings import resolve
from tests.factories import config, snapshot

SNAP = snapshot()
QUIET = {"start": "21:00", "end": "07:00", "tz": "recipient"}


def _by_rule(policies):
    return {p.rule: p for p in policies}


def test_version_pack_then_firm_floor_each_apply_without_an_override() -> None:
    floor = [
        {"rule": "quiet_hours", "params": QUIET},
        {"rule": "per_subject_contact_cap", "params": {"n": 2}},
    ]
    got = _by_rule(resolve.policies(config(), floor, {}, SNAP))
    assert list(got) == ["recipient_must_be_contact", "per_subject_contact_cap", "quiet_hours"]
    cap = got["per_subject_contact_cap"]
    assert [(x.source, x.params, x.applies) for x in cap.sources] == [
        ("version", {"n": 3}, True),
        ("firm", {"n": 2}, True),
    ]
    assert got["quiet_hours"].display_name == "Quiet hours"


def test_a_mapping_override_replaces_the_baselines_it_tightens() -> None:
    overrides = {"policy_params": {"per_subject_contact_cap": {"n": 1}}}
    cap = _by_rule(resolve.policies(config(), [], overrides, SNAP))["per_subject_contact_cap"]
    assert [(x.source, x.params, x.applies) for x in cap.sources] == [
        ("version", {"n": 3}, False),
        ("mapping", {"n": 1}, True),
    ]


def test_the_platform_minimum_is_marked_required_only_for_agents_that_contact_people() -> None:
    contacting = _by_rule(resolve.policies(config(), [], {}, SNAP))
    assert contacting["recipient_must_be_contact"].required
    assert not contacting["per_subject_contact_cap"].required
    reading_only = config(
        capabilities=[{"connector": "gmail", "tools": ["gmail.read_thread"]}],
        follow_up={"mode": "none"},
    )
    quiet = _by_rule(resolve.policies(reading_only, [], {}, SNAP))
    assert not quiet["recipient_must_be_contact"].required


def test_cadence_uses_the_override_when_set() -> None:
    assert resolve.cadence(config(), {}).model_dump() == {
        "version_min_wait_hours": 48,
        "override_min_wait_hours": None,
        "min_wait_hours": 48,
    }
    assert resolve.cadence(config(), {"cadence": {"min_wait_hours": 72}}).min_wait_hours == 72


def test_alert_routing_prefers_the_mapping_then_the_firm_then_the_agent() -> None:
    firm = {"P1": ["slack_thread"], "P2": []}  # an empty list leaves the urgency to the agent
    overrides = {"alert_routing": {"P0": ["email", "slack_dm"]}}
    routes = {r.urgency: r for r in resolve.alert_routing(config(), firm, overrides)}
    assert (routes["P0"].source, routes["P0"].channels) == ("mapping", ["email", "slack_dm"])
    assert (routes["P1"].source, routes["P1"].channels) == ("firm", ["slack_thread"])
    assert (routes["P2"].source, routes["P2"].channels) == ("version", ["digest"])
    assert routes["P1"].version == ["email"]  # the losers stay visible


def test_an_urgency_nobody_routes_has_no_channels() -> None:
    cfg = config(alert_policy={"default_channels": {}})
    routes = resolve.alert_routing(cfg, {}, {})
    assert [(r.channels, r.source) for r in routes] == [([], None)] * 3
