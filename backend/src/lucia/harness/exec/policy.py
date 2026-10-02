"""Deterministic policy, no model (RUNTIME_SPEC §8.3). Static rules deny; temporal rules defer.
Deny beats defer. Quiet hours are a blocked window and may cross midnight (D50)."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from lucia.mappings.schemas import ResolvedPolicy


@dataclass(frozen=True)
class Recipient:
    subject_contact_id: str
    contact_point_id: str
    role: str
    channel: str  # voice | email | slack
    consent: dict[str, str]  # channel -> granted | refused | unknown
    opt_out: list[str]
    tz: str | None
    org_daily_cap: int | None
    address: str  # E.164 number or email, for the idempotency key


@dataclass(frozen=True)
class PolicyInput:
    rules: list[ResolvedPolicy]
    recipient: Recipient | None
    firm_tz: str
    now: datetime
    sent_today_subject: int
    sent_today_org: int


@dataclass(frozen=True)
class Allow:
    pass


@dataclass(frozen=True)
class Deny:
    rule: str
    reason: str


@dataclass(frozen=True)
class Defer:
    rule: str
    until: datetime


Decision = Allow | Deny | Defer


def _params(rule: ResolvedPolicy) -> list[dict[str, Any]]:
    """A mapping override replaces the other sources; otherwise every applying source counts."""
    applying = [s for s in rule.sources if s.applies]
    mapping = [s.params for s in applying if s.source == "mapping"]
    return mapping or [s.params for s in applying]


def window_end(local: datetime, start: time, end: time) -> datetime | None:
    """When the blocked window [start, end) containing `local` ends; None if outside it."""
    t = local.time()
    crosses = start > end
    inside = (t >= start or t < end) if crosses else (start <= t < end)
    if not inside:
        return None
    day = local.date() + timedelta(days=1) if crosses and t >= start else local.date()
    return datetime.combine(day, end, tzinfo=local.tzinfo)


def _hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def _deny(p: PolicyInput, rule: str, params: dict[str, Any]) -> str | None:
    r = p.recipient
    if r is None:
        return "the recipient is not a contact on this subject"
    match rule:
        case "consent_required":
            if (
                r.channel in params.get("channel", [])
                and r.role in params.get("roles", [])
                and r.consent.get(r.channel) != "granted"
            ):
                return f"no {r.channel} consent from the {r.role}"
        case "opt_out_enforced":
            if r.channel in r.opt_out:
                return f"opted out of {r.channel}"
    return None


def _defer(p: PolicyInput, rule: str, params: dict[str, Any], tz: ZoneInfo) -> datetime | None:
    local = p.now.astimezone(tz)
    midnight = datetime.combine(local.date() + timedelta(days=1), time(0), tzinfo=tz)
    match rule:
        case "quiet_hours":
            zone = ZoneInfo(p.firm_tz) if params.get("tz") == "firm" else tz
            return window_end(p.now.astimezone(zone), _hhmm(params["start"]), _hhmm(params["end"]))
        case "per_subject_contact_cap":
            return midnight if p.sent_today_subject >= params["n"] else None
    return None


def evaluate(p: PolicyInput) -> Decision:
    for rule in p.rules:
        for params in _params(rule):
            if reason := _deny(p, rule.rule, params):
                return Deny(rule.rule, reason)
    if p.recipient is None:
        return Deny("recipient_must_be_contact", "the recipient is not a contact on this subject")
    tz = ZoneInfo(p.recipient.tz or p.firm_tz)
    defers = [
        Defer(rule.rule, until)
        for rule in p.rules
        for params in _params(rule)
        if (until := _defer(p, rule.rule, params, tz))
    ]
    cap = p.recipient.org_daily_cap
    if cap is not None and p.sent_today_org >= cap:
        local = p.now.astimezone(tz)
        tomorrow = datetime.combine(local.date() + timedelta(days=1), time(0), tzinfo=tz)
        defers.append(Defer("org_daily_cap", tomorrow))
    return max(defers, key=lambda d: d.until) if defers else Allow()
