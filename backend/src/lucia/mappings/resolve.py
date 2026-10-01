"""The view of a mapping the runtime will enforce: the version's config combined with the
firm's settings and the mapping's tighten-only overrides. Pure, so it is unit tested."""

from typing import Any, get_args

from lucia.core.schema import Urgency
from lucia.mappings import schemas as s
from lucia.mappings.tighten import min_wait_hours
from lucia.registry.snapshot import RegistrySnapshot
from lucia.studio.config_schema import VersionConfig
from lucia.studio.validator import MIN_PACK_RULE, needs_min_pack


def policies(
    config: dict[str, Any],
    floor: list[dict[str, Any]],
    overrides: dict[str, Any],
    snap: RegistrySnapshot,
) -> list[s.ResolvedPolicy]:
    """One entry per rule in the version pack or the firm floor, in that order. A mapping
    override replaces both (it was checked to be stricter); otherwise every source applies."""
    tightened = overrides.get("policy_params") or {}
    required = needs_min_pack(VersionConfig.model_validate(config), snap)
    sources: dict[str, list[s.PolicySource]] = {}
    origins: tuple[tuple[s.Source, list[dict[str, Any]]], ...] = (
        ("version", config.get("policy_pack", [])),
        ("firm", floor),
    )
    for origin, refs in origins:
        for ref in refs:
            sources.setdefault(ref["rule"], []).append(
                s.PolicySource(
                    source=origin,
                    params=ref.get("params", {}),
                    applies=ref["rule"] not in tightened,
                )
            )
    out: list[s.ResolvedPolicy] = []
    for rule, found in sources.items():
        if rule in tightened:
            found.append(s.PolicySource(source="mapping", params=tightened[rule], applies=True))
        entry = snap.policy_rules.get(rule)
        out.append(
            s.ResolvedPolicy(
                rule=rule,
                display_name=entry.display_name if entry else rule,
                description=entry.description if entry else "",
                required=required and rule == MIN_PACK_RULE,
                sources=found,
            )
        )
    return out


def cadence(config: dict[str, Any], overrides: dict[str, Any]) -> s.ResolvedCadence:
    base = min_wait_hours(config)
    override = (overrides.get("cadence") or {}).get("min_wait_hours")
    return s.ResolvedCadence(
        version_min_wait_hours=base,
        override_min_wait_hours=override,
        min_wait_hours=override if override is not None else base,
    )


def alert_routing(
    config: dict[str, Any], firm_routing: dict[str, list[str]], overrides: dict[str, Any]
) -> list[s.ResolvedRoute]:
    version = config.get("alert_policy", {}).get("default_channels", {})
    mapping = overrides.get("alert_routing") or {}
    routes: list[s.ResolvedRoute] = []
    for urgency in get_args(Urgency):
        layers: tuple[tuple[s.Source, dict[str, list[str]]], ...] = (
            ("mapping", mapping),
            ("firm", firm_routing),
            ("version", version),
        )
        winner: tuple[s.Source, list[str]] | None = next(
            ((name, layer[urgency]) for name, layer in layers if layer.get(urgency)), None
        )
        routes.append(
            s.ResolvedRoute(
                urgency=urgency,
                channels=winner[1] if winner else [],
                source=winner[0] if winner else None,
                version=version.get(urgency),
                firm=firm_routing.get(urgency),
                mapping=mapping.get(urgency),
            )
        )
    return routes
