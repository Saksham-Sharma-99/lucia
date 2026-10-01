"""Tighten-only overrides (plan §10): a mapping may make a version stricter, never looser."""

from typing import Any, cast

from jsonschema import Draft202012Validator

from lucia.core.errors import FieldError
from lucia.mappings.schemas import Overrides
from lucia.registry.snapshot import RegistrySnapshot

DAY_MINUTES = 24 * 60


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def window_minutes(start: str, end: str) -> set[int]:
    """Minutes covered by a window; windows may wrap midnight (20:00-08:00).
    start == end is an empty window. Params reaching here passed the rule's JSON schema,
    which requires start and end."""
    a, b = _minutes(start), _minutes(end)
    return set(range(a, b)) if a <= b else set(range(a, DAY_MINUTES)) | set(range(0, b))


def _looser(rule: str, base: dict[str, Any], new: dict[str, Any]) -> str | None:
    """Return why `new` is looser than `base`, or None if it is the same or stricter."""
    if rule == "quiet_hours":
        if new.get("tz") != base.get("tz"):
            return "Quiet hours must keep the same timezone basis"
        if not window_minutes(base["start"], base["end"]) <= window_minutes(
            new["start"], new["end"]
        ):
            return "Quiet hours can only widen"
        return None
    if rule == "attachment_allowed":  # fewer allowed roles is stricter
        for kind, roles in new.items():
            if not set(roles) <= set(base.get(kind, [])):
                return f"{kind} can only allow fewer roles"
        return None
    for key, before in base.items():
        after = new.get(key, before)
        if isinstance(before, bool):
            if before and not after:
                return f"{key} can only go from false to true"
        elif isinstance(before, int | float):
            if after > before:
                return f"{key} can only decrease"
        elif isinstance(before, list) and not set(cast(list[Any], before)) <= set(after):
            return f"{key} can only add entries"
    return None


def effective_policy(
    pack: list[dict[str, Any]], floor: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """rule -> every baseline it must not loosen (version pack and firm floor)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for ref in [*pack, *floor]:
        out.setdefault(ref["rule"], []).append(ref.get("params", {}))
    return out


def min_wait_hours(config: dict[str, Any]) -> int:
    fu = config.get("follow_up", {})
    if fu.get("mode") == "dynamic" and fu.get("dynamic"):
        return fu["dynamic"]["min_hours"]
    waits = [r["wait_hours"] for r in fu.get("ladder", []) if r.get("channel")]
    return min(waits, default=0)


def check_overrides(
    overrides: Overrides,
    config: dict[str, Any],
    floor: list[dict[str, Any]],
    snap: RegistrySnapshot,
) -> list[FieldError]:
    errors: list[FieldError] = []
    if overrides.cadence and overrides.cadence.min_wait_hours < (base := min_wait_hours(config)):
        errors.append(
            FieldError(
                path="/overrides/cadence/min_wait_hours",
                code="looser",
                message=f"Minimum wait can only increase (at least {base}h)",
            )
        )
    baselines = effective_policy(config.get("policy_pack", []), floor)
    for rule, params in (overrides.policy_params or {}).items():
        path = f"/overrides/policy_params/{rule}"
        if rule not in baselines:
            errors.append(
                FieldError(
                    path=path,
                    code="not_in_policy",
                    message="Only rules in the version or firm floor apply",
                )
            )
            continue
        schema = snap.rule_schema(rule) if rule in snap.policy_rules else {}
        bad = next(iter(Draft202012Validator(schema).iter_errors(params)), None)
        if bad is not None:
            errors.append(FieldError(path=path, code="invalid_params", message=bad.message))
            continue
        for base in baselines[rule]:
            if reason := _looser(rule, base, params):
                errors.append(FieldError(path=path, code="looser", message=reason))
                break
    return errors
