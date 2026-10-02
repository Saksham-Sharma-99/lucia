"""Deterministic routing over model scores (ORCHESTRATOR_SPEC §6, D8, D9). Pure functions."""

from dataclasses import dataclass, field
from typing import Literal

from lucia.orchestrator.schemas import AgentScore, AgentScores


def sanitize(raw: AgentScores, handles: list[str]) -> AgentScores:
    """Drops unknown handles, zero-fills missing ones, clamps to [0, 1], keeps directory order.
    Models often echo handles as written in the prompt ("@records"), so those are normalized."""
    given = {s.handle.strip().lstrip("@").lower(): s for s in raw.scores}
    return AgentScores(
        scores=[
            AgentScore(
                handle=h,
                score=round(min(max(given[h].score, 0.0), 1.0), 4) if h in given else 0.0,
                reason=given[h].reason if h in given else "",
            )
            for h in handles
        ],
        multi_intent=raw.multi_intent,
    )


def _ranked(scores: AgentScores) -> list[AgentScore]:
    return sorted(scores.scores, key=lambda s: s.score, reverse=True)


@dataclass(frozen=True)
class Precheck:
    ok: bool
    suggestions: list[AgentScore] = field(default_factory=list)


def precheck(
    scores: AgentScores, mentioned: str, threshold: float, route_threshold: float
) -> Precheck:
    """Can the @mentioned agent do this? If not, which agents (max 3) clearly can."""
    if next((s.score for s in scores.scores if s.handle == mentioned), 0.0) >= threshold:
        return Precheck(ok=True)
    better = [s for s in _ranked(scores) if s.handle != mentioned and s.score >= route_threshold]
    return Precheck(ok=False, suggestions=better[:3])


@dataclass(frozen=True)
class Route:
    kind: Literal["route", "fanout", "clarify", "none"]
    handles: list[str]


def decide(
    scores: AgentScores, *, route_threshold: float, margin: float, clarify_floor: float
) -> Route:
    ranked = _ranked(scores)
    top = ranked[0].score if ranked else 0.0
    second = ranked[1].score if len(ranked) > 1 else 0.0
    if scores.multi_intent and top >= route_threshold and second >= route_threshold:
        return Route("fanout", [s.handle for s in ranked if s.score >= route_threshold])
    if top >= route_threshold and round(top - second, 4) >= margin:
        return Route("route", [ranked[0].handle])
    if top >= clarify_floor:
        return Route("clarify", [s.handle for s in ranked[:3] if s.score >= clarify_floor])
    return Route("none", [])
