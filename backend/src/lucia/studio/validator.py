"""Semantic checks of a version config against the registry (backend-plan §7). Pure functions."""

from collections.abc import Iterable, Sequence

from jsonschema import Draft202012Validator

from lucia.core.errors import FieldError
from lucia.core.schema import PolicyRuleRef
from lucia.registry.catalog import ALERT_CHANNELS, CHANNEL_TOOLS
from lucia.registry.snapshot import RegistrySnapshot
from lucia.studio.config_schema import VersionConfig

MIN_PACK_RULE = "recipient_must_be_contact"


def _err(path: str, code: str, message: str) -> FieldError:
    return FieldError(path=path, code=code, message=message)


def validate_policy_refs(
    refs: Sequence[PolicyRuleRef], snap: RegistrySnapshot, base: str
) -> list[FieldError]:
    errors: list[FieldError] = []
    seen: set[str] = set()
    for i, ref in enumerate(refs):
        path = f"{base}/{i}"
        if ref.rule in seen:
            errors.append(_err(f"{path}/rule", "duplicate", f"Rule {ref.rule} is listed twice"))
            continue
        seen.add(ref.rule)
        entry = snap.policy_rules.get(ref.rule)
        if entry is None or not entry.available:
            errors.append(_err(f"{path}/rule", "unknown_rule", f"Unknown policy rule {ref.rule}"))
            continue
        for e in Draft202012Validator(entry.params_schema).iter_errors(ref.params):
            sub = "".join(f"/{p}" for p in e.absolute_path)
            errors.append(_err(f"{path}/params{sub}", "invalid_params", e.message))
    return errors


def _check_capabilities(cfg: VersionConfig, snap: RegistrySnapshot) -> list[FieldError]:
    errors: list[FieldError] = []
    seen: set[str] = set()
    for i, cap in enumerate(cfg.capabilities):
        path = f"/capabilities/{i}"
        if cap.connector in seen:
            errors.append(
                _err(f"{path}/connector", "duplicate", f"Connector {cap.connector} is listed twice")
            )
            continue
        seen.add(cap.connector)
        conn = snap.connectors.get(cap.connector)
        if conn is None or not conn.available:
            errors.append(
                _err(
                    f"{path}/connector",
                    "unknown_connector",
                    f"Connector {cap.connector} is not available",
                )
            )
            continue
        tools: set[str] = set()
        for j, name in enumerate(cap.tools):
            tool = snap.tools.get(name)
            tpath = f"{path}/tools/{j}"
            if name in tools:
                errors.append(_err(tpath, "duplicate", f"Tool {name} is listed twice"))
            elif tool is None or not tool.available:
                errors.append(_err(tpath, "unknown_tool", f"Tool {name} is not available"))
            elif tool.connector != cap.connector:
                errors.append(
                    _err(
                        tpath, "wrong_connector", f"Tool {name} does not belong to {cap.connector}"
                    )
                )
            tools.add(name)
    return errors


def _selected_tools(cfg: VersionConfig) -> set[str]:
    return {t for cap in cfg.capabilities for t in cap.tools}


def _check_channel(channel: str, selected: set[str], path: str) -> FieldError | None:
    tool = CHANNEL_TOOLS.get(channel)
    if tool is None:
        return _err(path, "unknown_channel", f"Unknown channel {channel}")
    if tool not in selected:
        return _err(path, "channel_tool_missing", f"Channel {channel} needs the {tool} tool")
    return None


def _check_follow_up(cfg: VersionConfig) -> list[FieldError]:
    fu, selected = cfg.follow_up, _selected_tools(cfg)
    errors: list[FieldError] = []
    if fu.mode == "fixed_ladder":
        if not fu.ladder:
            errors.append(_err("/follow_up/ladder", "required", "Add at least one ladder step"))
        for i, rung in enumerate(fu.ladder):
            if rung.channel and (
                e := _check_channel(rung.channel, selected, f"/follow_up/ladder/{i}/channel")
            ):
                errors.append(e)
    elif fu.mode == "dynamic":
        if fu.dynamic is None:
            return [_err("/follow_up/dynamic", "required", "Dynamic follow-up needs settings")]
        if fu.dynamic.min_hours > fu.dynamic.max_hours:
            errors.append(
                _err(
                    "/follow_up/dynamic/min_hours",
                    "min_gt_max",
                    "Minimum wait must not exceed the maximum",
                )
            )
        for i, ch in enumerate(fu.dynamic.channels):
            if e := _check_channel(ch, selected, f"/follow_up/dynamic/channels/{i}"):
                errors.append(e)
    return errors


def contacts_outside(tools: Iterable[str], snap: RegistrySnapshot) -> bool:
    return any(
        (t := snap.tools.get(name)) is not None and t.risk_tier == "external_comm" for name in tools
    )


def needs_min_pack(cfg: VersionConfig, snap: RegistrySnapshot) -> bool:
    """An agent that can contact people outside the firm must carry the platform's minimum rule."""
    return contacts_outside(_selected_tools(cfg), snap)


def _check_min_pack(cfg: VersionConfig, snap: RegistrySnapshot) -> list[FieldError]:
    if needs_min_pack(cfg, snap) and all(ref.rule != MIN_PACK_RULE for ref in cfg.policy_pack):
        return [
            _err(
                "/policy_pack",
                "min_pack",
                f"External tools need the {MIN_PACK_RULE} rule. Add it to the policy pack.",
            )
        ]
    return []


def _check_alerts(cfg: VersionConfig) -> list[FieldError]:
    ap, errors = cfg.alert_policy, []
    if ap.urgency_mode == "fixed" and ap.fixed_urgency is None:
        errors.append(
            _err(
                "/alert_policy/fixed_urgency",
                "required",
                "Pick an urgency when urgency mode is fixed",
            )
        )
    for level, channels in ap.default_channels.items():
        for i, ch in enumerate(channels):
            if ch not in ALERT_CHANNELS:
                errors.append(
                    _err(
                        f"/alert_policy/default_channels/{level}/{i}",
                        "unknown_alert_channel",
                        f"Unknown alert channel {ch}",
                    )
                )
    return errors


def _check_models(cfg: VersionConfig, allowed: Sequence[str]) -> list[FieldError]:
    return [
        _err(f"/models/{role}", "model_not_allowed", f"Model {name} is not allowed")
        for role, name in cfg.models.model_dump().items()
        if name not in allowed
    ]


def validate_config(
    cfg: VersionConfig, snap: RegistrySnapshot, allowed_models: Sequence[str]
) -> list[FieldError]:
    return [
        *_check_capabilities(cfg, snap),
        *validate_policy_refs(cfg.policy_pack, snap, "/policy_pack"),
        *_check_follow_up(cfg),
        *_check_min_pack(cfg, snap),
        *_check_alerts(cfg),
        *_check_models(cfg, allowed_models),
    ]
