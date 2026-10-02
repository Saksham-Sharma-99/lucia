from evals.orchestrator.cases import DIRECTORY, ROUTE_CASES, SUBJECT_CASES, SUBJECTS


def test_cases_reference_the_fixtures() -> None:
    subject_ids = {s.subject_id for s in SUBJECTS}
    handles = {a.handle for a in DIRECTORY}
    assert len(SUBJECT_CASES) == 30 and len(ROUTE_CASES) == 30
    assert all(c.expected is None or c.expected in subject_ids for c in SUBJECT_CASES)
    assert all(set(c.handles) <= handles for c in ROUTE_CASES)
    assert {c.kind for c in ROUTE_CASES} == {"route", "clarify", "none", "fanout"}
