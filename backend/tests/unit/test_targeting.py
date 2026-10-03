import pytest

from lucia.orchestrator.schemas import AgentScore, AgentScores
from lucia.orchestrator.targeting import decide, precheck, sanitize

HANDLES = ["records", "checkin", "liens"]


def _scores(multi: bool = False, **scores: float) -> AgentScores:
    return AgentScores(
        scores=[AgentScore(handle=h, score=v, reason="r") for h, v in scores.items()],
        multi_intent=multi,
    )


def test_sanitize_drops_unknown_zero_fills_and_clamps() -> None:
    raw = _scores(records=1.7, ghost=0.9)
    clean = sanitize(raw, HANDLES)
    assert [(s.handle, s.score) for s in clean.scores] == [
        ("records", 1.0),
        ("checkin", 0.0),
        ("liens", 0.0),
    ]


def test_precheck_passes_a_fitting_mention() -> None:
    assert precheck(_scores(checkin=0.8, liens=0.1), "checkin", 0.6, 0.75).ok


def test_precheck_suggests_better_agents() -> None:
    result = precheck(_scores(checkin=0.2, liens=0.9, records=0.8), "checkin", 0.6, 0.75)
    assert not result.ok and [s.handle for s in result.suggestions] == ["liens", "records"]


def test_precheck_with_no_better_agent_suggests_nothing() -> None:
    result = precheck(_scores(checkin=0.2, liens=0.3), "checkin", 0.6, 0.75)
    assert not result.ok and result.suggestions == []


@pytest.mark.parametrize(
    ("scores", "multi", "kind", "handles"),
    [
        ({"records": 0.9, "checkin": 0.2}, False, "route", ["records"]),
        ({"records": 0.75, "checkin": 0.6}, False, "route", ["records"]),  # margin exactly 0.15
        ({"records": 0.75, "checkin": 0.6001}, False, "clarify", ["records", "checkin"]),
        ({"records": 0.5, "checkin": 0.45}, False, "clarify", ["records", "checkin"]),
        ({"records": 0.39, "checkin": 0.1}, False, "none", []),
        ({"records": 0.8, "checkin": 0.78}, True, "fanout", ["records", "checkin"]),
        ({"records": 0.8, "checkin": 0.5}, True, "route", ["records"]),
    ],
)
def test_decide(scores: dict[str, float], multi: bool, kind: str, handles: list[str]) -> None:
    route = decide(_scores(multi, **scores), route_threshold=0.75, margin=0.15, clarify_floor=0.40)
    assert (route.kind, route.handles) == (kind, handles)


def test_sanitize_accepts_at_prefixed_and_cased_handles() -> None:
    raw = AgentScores(
        scores=[
            AgentScore(handle="@Records", score=0.9, reason="r"),
            AgentScore(handle=" @checkin ", score=0.4, reason="r"),
        ],
        multi_intent=False,
    )
    clean = sanitize(raw, HANDLES)
    assert [(s.handle, s.score) for s in clean.scores] == [
        ("records", 0.9),
        ("checkin", 0.4),
        ("liens", 0.0),
    ]
