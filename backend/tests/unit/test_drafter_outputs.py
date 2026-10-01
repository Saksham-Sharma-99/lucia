import json
from typing import Any

import pytest
from agents import AgentOutputSchema
from pydantic import ValidationError

from lucia.core.schema import PolicyRuleRef
from lucia.db.models import RegistryEntry
from lucia.registry.snapshot import RegistrySnapshot
from lucia.studio.config_schema import Models, VersionConfig
from lucia.studio.drafter import schemas as s
from lucia.studio.drafter.outputs import follow_up_channels, output_model, rule_model
from lucia.studio.templates import TEMPLATES
from lucia.studio.validator import MIN_PACK_RULE, validate_config
from tests.factories import (
    ACTION_RUNG,
    ALLOWED,
    CHANNEL_RUNG,
    DRAFT_OUTPUTS,
    DYNAMIC,
    GMAIL_TOOLS,
    snapshot,
)

SNAP = snapshot()
GMAIL = GMAIL_TOOLS
NOTE: dict[str, Any] = {"rationale": "why", "unmapped": []}
POLICIES = DRAFT_OUTPUTS["PoliciesOut"]
SCHEDULE = DRAFT_OUTPUTS["SchedulesOut"]
RUNG, ESCALATE = CHANNEL_RUNG, ACTION_RUNG
# One valid params value per catalog rule, as the drafter's output gives it.
RULE_OUTPUTS: dict[str, dict[str, Any]] = {
    "recipient_must_be_contact": {},
    "consent_required": {"channel": ["email"], "roles": ["client"]},
    "quiet_hours": {"start": "08:00", "end": "18:00", "tz": "recipient"},
    "opt_out_enforced": {},
    "attachment_allowed": {"entries": [{"key": "hipaa_auth", "value": ["provider"]}]},
    "per_subject_contact_cap": {"n": 2},
}


def _draft(section: s.Section, data: dict[str, Any], tools: list[str] = GMAIL) -> Any:
    return output_model(section, SNAP, tools).model_validate(data).to_draft()


def _draft_with(model: Any, data: dict[str, Any]) -> Any:
    return model.model_validate(data).to_draft()


def _rule(name: str, params_schema: dict[str, Any], available: bool = True) -> RegistryEntry:
    return RegistryEntry(
        kind="policy_rule",
        name=name,
        display_name=name,
        description="",
        params_schema=params_schema,
        available=available,
    )


def _issues(**sections: Any) -> list[str]:
    """Validation codes of a config made of these sections plus a minimal valid rest."""
    cfg: dict[str, Any] = {
        "system_prompt": "Chase records.",
        "models": Models(loop=ALLOWED[0], guardrail=ALLOWED[-1], judge=ALLOWED[0]),
        "capabilities": [{"connector": "gmail", "tools": GMAIL}],
        "policy_pack": [PolicyRuleRef(rule="recipient_must_be_contact")],
        "alert_policy": {"default_channels": {"P0": [], "P1": [], "P2": []}},
    }
    return [e.code for e in validate_config(VersionConfig(**cfg | sections), SNAP, ALLOWED)]


@pytest.mark.parametrize(
    ("section", "tools"),
    [("capabilities", []), ("policies", GMAIL), ("schedules", GMAIL), ("schedules", [])],
)
def test_output_models_are_strict_json_schemas(section: s.Section, tools: list[str]) -> None:
    schema = AgentOutputSchema(output_model(section, SNAP, tools))
    assert schema.is_strict_json_schema()
    assert '"const"' not in json.dumps(schema.json_schema())  # plain enums only


# Capabilities


def test_capabilities_are_grouped_by_connector_and_deduped() -> None:
    tools = ["gmail.send_email", "vapi.place_call", "gmail.read_thread", "gmail.send_email"]
    draft = _draft("capabilities", {"tools": tools, **NOTE})
    assert [(c.connector, c.tools) for c in draft.capabilities] == [
        ("gmail", ["gmail.send_email", "gmail.read_thread"]),
        ("vapi", ["vapi.place_call"]),
    ]
    assert (draft.rationale, draft.unmapped) == ("why", [])


@pytest.mark.parametrize("tool", ["fax.send_fax", "gmail.delete_all", "send_email"])
def test_only_available_tools_can_be_picked(tool: str) -> None:
    with pytest.raises(ValidationError):
        _draft("capabilities", {"tools": [tool], **NOTE})


def test_no_tools_is_a_valid_answer() -> None:
    assert _draft("capabilities", {"tools": [], **NOTE}).capabilities == []


# Policies


def test_every_catalog_rule_has_a_sample() -> None:
    assert set(RULE_OUTPUTS) == set(SNAP.policy_rules)


@pytest.mark.parametrize("rule", RULE_OUTPUTS)
def test_every_catalog_rule_can_be_drafted_and_passes_validation(rule: str) -> None:
    rules = [{"rule": r, **RULE_OUTPUTS[r]} for r in dict.fromkeys([MIN_PACK_RULE, rule])]
    pack = _draft("policies", {**POLICIES, "rules": rules}).policy_pack
    assert rule in [r.rule for r in pack]
    assert _issues(policy_pack=pack) == []


def _as_output(ref: PolicyRuleRef) -> dict[str, Any]:
    if isinstance(SNAP.rule_schema(ref.rule).get("additionalProperties"), dict):
        return {
            "rule": ref.rule,
            "entries": [{"key": k, "value": v} for k, v in ref.params.items()],
        }
    return {"rule": ref.rule, **ref.params}


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.handle)
def test_template_policy_packs_round_trip(template: Any) -> None:
    cfg = template.config
    tools = [t for cap in cfg.capabilities for t in cap.tools]
    rules = [_as_output(r) for r in cfg.policy_pack]
    assert _draft("policies", {**POLICIES, "rules": rules}, tools).policy_pack == cfg.policy_pack


def test_unavailable_rules_are_not_offered() -> None:
    snap = RegistrySnapshot(
        policy_rules={
            "opt_out_enforced": _rule("opt_out_enforced", {"properties": {}}, available=False)
        }
    )
    with pytest.raises(ValidationError):
        output_model("policies", snap, []).model_validate(
            {**POLICIES, "rules": [{"rule": "opt_out_enforced"}]}
        )


def test_with_no_rules_in_the_registry_the_pack_is_empty() -> None:
    model = output_model("policies", RegistrySnapshot(), [])
    assert _draft_with(model, POLICIES).policy_pack == []
    with pytest.raises(ValidationError):
        model.model_validate({**POLICIES, "rules": [{"rule": "anything"}]})


def test_duplicate_rules_are_left_for_validation() -> None:
    rules = [{"rule": "opt_out_enforced"}, {"rule": "opt_out_enforced"}]
    pack = _draft("policies", {**POLICIES, "rules": rules}).policy_pack
    assert "duplicate" in _issues(policy_pack=pack)


def test_more_rules_than_the_catalog_has_are_rejected() -> None:
    rules = [{"rule": "opt_out_enforced"}] * (len(SNAP.policy_rules) + 1)
    with pytest.raises(ValidationError):
        _draft("policies", {**POLICIES, "rules": rules})


def test_optional_params_left_null_are_dropped() -> None:
    schema = {**SNAP.rule_schema("quiet_hours"), "required": ["start", "end"]}
    out = rule_model(_rule("quiet_hours", schema)).model_validate(
        {"rule": "quiet_hours", "start": "08:00", "end": "18:00", "tz": None}
    )
    assert out.ref().params == {"start": "08:00", "end": "18:00"}


def test_an_unsupported_param_schema_fails_loudly() -> None:
    with pytest.raises(ValueError, match="can't express"):
        rule_model(_rule("ratio", {"properties": {"x": {"type": "number"}}}))


@pytest.mark.parametrize(
    "rule",
    [
        {"rule": "unknown_rule"},
        {"rule": "per_subject_contact_cap", "n": 0},
        {"rule": "per_subject_contact_cap", "n": 21},
        {"rule": "quiet_hours", "start": "8am", "end": "18:00", "tz": "recipient"},
        {"rule": "quiet_hours", "start": "08:00", "end": "18:00", "tz": "utc"},
        {"rule": "consent_required", "channel": [], "roles": ["client"]},
        {"rule": "consent_required", "channel": ["sms"], "roles": ["client"]},
        {"rule": "attachment_allowed", "entries": [{"key": "bill", "value": ["judge"]}]},
    ],
)
def test_rules_outside_the_catalog_schema_are_rejected(rule: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _draft("policies", {**POLICIES, "rules": [rule]})


def test_hitl_and_alerts() -> None:
    data = {**POLICIES, "ask_on": ["legal_question", "fee_required"], "verify_evidence_below": 0.7}
    draft = _draft("policies", data)
    assert draft.hitl.model_dump() == {
        "ask_on": ["legal_question", "fee_required"],
        "verify_evidence_below": 0.7,
    }
    assert draft.alert_policy.default_channels == {
        "P0": ["slack_dm"],
        "P1": ["slack_thread"],
        "P2": ["digest"],
    }


@pytest.mark.parametrize(
    ("mode", "given", "kept"),
    [("fixed", "P0", "P0"), ("fixed", None, None), ("auto", "P0", None)],
)
def test_fixed_urgency_is_kept_only_in_fixed_mode(
    mode: str, given: str | None, kept: str | None
) -> None:
    data = {**POLICIES, "urgency_mode": mode, "fixed_urgency": given}
    assert _draft("policies", data).alert_policy.fixed_urgency == kept


def test_fixed_mode_without_a_level_is_left_for_validation() -> None:
    alerts = _draft("policies", {**POLICIES, "urgency_mode": "fixed"}).alert_policy
    assert _issues(alert_policy=alerts) == ["required"]


@pytest.mark.parametrize(
    "bad",
    [{"ask_on": ["Legal Question"]}, {"verify_evidence_below": 1.5}, {"p0_channels": ["pager"]}],
)
def test_hitl_and_alert_values_are_checked(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _draft("policies", {**POLICIES, **bad})


# Schedules


def test_follow_up_channels_follow_the_chosen_tools() -> None:
    assert follow_up_channels(GMAIL) == ["email"]
    assert follow_up_channels(["vapi.place_call", "gmail.send_email"]) == ["email", "voice"]
    assert follow_up_channels([]) == []


@pytest.mark.parametrize(
    "bad",
    [
        {"mode": "fixed_ladder", "ladder": [{**RUNG, "channel": "voice"}]},
        {"mode": "dynamic", "dynamic": {**DYNAMIC, "channels": ["voice"]}},
    ],
)
def test_follow_up_can_only_use_channels_the_agent_has(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _draft("schedules", {**SCHEDULE, **bad})


@pytest.mark.parametrize("mode", ["fixed_ladder", "dynamic"])
def test_without_a_send_tool_the_agent_cannot_follow_up(mode: str) -> None:
    with pytest.raises(ValidationError):
        _draft("schedules", {**SCHEDULE, "mode": mode}, [])
    assert _draft("schedules", SCHEDULE, []).follow_up.mode == "none"


def test_fixed_ladder_steps() -> None:
    draft = _draft("schedules", {**SCHEDULE, "mode": "fixed_ladder", "ladder": [RUNG, ESCALATE]})
    assert [(r.channel, r.action, r.wait_hours, r.urgency) for r in draft.follow_up.ladder] == [
        ("email", None, 48, None),
        (None, "escalate", 0, "P1"),
    ]


@pytest.mark.parametrize(
    "rung",
    [
        {**RUNG, "channel": None},
        {**ESCALATE, "action": None},
        {**RUNG, "kind": "call"},
        {**RUNG, "wait_hours": -1},
        {**RUNG, "attempts": 11},
    ],
)
def test_malformed_steps_are_rejected(rung: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _draft("schedules", {**SCHEDULE, "mode": "fixed_ladder", "ladder": [rung]})


def test_settings_of_other_modes_are_dropped() -> None:
    data = {**SCHEDULE, "ladder": [RUNG], "dynamic": DYNAMIC}
    none = _draft("schedules", data).follow_up
    assert (none.ladder, none.dynamic) == ([], None)
    dynamic = _draft("schedules", {**data, "mode": "dynamic"}).follow_up
    assert dynamic.ladder == [] and dynamic.dynamic is not None
    assert dynamic.dynamic.escalate_after.model_dump() == {"attempts": 3, "urgency": "P1"}


@pytest.mark.parametrize(
    ("follow_up", "code"),
    [
        ({"mode": "fixed_ladder", "ladder": []}, "required"),
        ({"mode": "dynamic", "dynamic": None}, "required"),
        ({"mode": "dynamic", "dynamic": {**DYNAMIC, "min_hours": 200}}, "min_gt_max"),
    ],
)
def test_inconsistent_follow_ups_are_left_for_validation(
    follow_up: dict[str, Any], code: str
) -> None:
    draft = _draft("schedules", {**SCHEDULE, **follow_up})
    assert code in _issues(follow_up=draft.follow_up)


@pytest.mark.parametrize(
    "bad",
    [
        {"dynamic": {**DYNAMIC, "channels": []}},
        {"dynamic": {**DYNAMIC, "min_hours": 0}},
        {"recurrence_every_days": 0},
        {"recurrence_every_days": 366},
        {"max_steps": 5},
        {"max_turns_per_episode": 51},
        {"on_subject_closed": "archive"},
    ],
)
def test_schedule_limits_are_checked(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _draft("schedules", {**SCHEDULE, "mode": "dynamic", "dynamic": DYNAMIC, **bad})


def test_recurrence_and_end_conditions() -> None:
    data = {**SCHEDULE, "recurrence_every_days": 14, "max_duration_days": 730, "max_steps": 2000}
    draft = _draft("schedules", data)
    assert draft.recurrence is not None and draft.recurrence.every_days == 14
    assert draft.end_conditions.model_dump() == {
        "max_duration_days": 730,
        "max_steps": 2000,
        "on_subject_closed": "end",
    }
    assert _draft("schedules", SCHEDULE).recurrence is None


def test_drafted_sections_combine_into_a_valid_config() -> None:
    policies = _draft("policies", {**POLICIES, "rules": [{"rule": MIN_PACK_RULE}]})
    schedules = _draft(
        "schedules", {**SCHEDULE, "mode": "fixed_ladder", "ladder": [RUNG, ESCALATE]}
    )
    issues = _issues(
        capabilities=_draft("capabilities", {"tools": GMAIL, **NOTE}).capabilities,
        policy_pack=policies.policy_pack,
        hitl=policies.hitl,
        alert_policy=policies.alert_policy,
        follow_up=schedules.follow_up,
        recurrence=schedules.recurrence,
        end_conditions=schedules.end_conditions,
        max_turns_per_episode=schedules.max_turns_per_episode,
    )
    assert issues == []
