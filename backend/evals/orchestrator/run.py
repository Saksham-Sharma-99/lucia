"""Orchestrator evals against the real model: `make eval-orchestrator` (needs OPENAI_API_KEY).

Subject: the model must lock the right subject, and must not lock confidently when the
message is ambiguous. Routing: the deterministic rule over the model's scores must reach the
labeled outcome; routing to the wrong agent is counted separately. Exits 1 below the
thresholds, 2 without a key."""

import asyncio
import sys

from evals.orchestrator.cases import (
    DIRECTORY,
    ROUTE_CASES,
    SUBJECT_CASES,
    SUBJECTS,
    RouteCase,
    SubjectCase,
)
from lucia.core.config import get_settings
from lucia.llm.client import get_llm
from lucia.orchestrator import prompts
from lucia.orchestrator.directory import describe
from lucia.orchestrator.schemas import AgentScores, SubjectPick
from lucia.orchestrator.subject import candidates_text
from lucia.orchestrator.targeting import decide, sanitize

SUBJECT_PASS = 0.9
ROUTE_PASS = 0.85
WRONG_ROUTE_MAX = 0.05
CONCURRENCY = 6


async def subject_ok(case: SubjectCase, slots: asyncio.Semaphore) -> bool:
    async with slots:
        pick, _ = await get_llm().structured(
            role="subject",
            model=get_settings().orchestrator_model,
            instructions=prompts.SUBJECT,
            message=f"## candidates\n{candidates_text(SUBJECTS)}\n\n## message\n{case.message}",
            output_type=SubjectPick,
            seconds=30,
        )
    locked = pick.subject_id if pick.confidence >= get_settings().subject_auto_threshold else None
    ok = locked == (str(case.expected) if case.expected else None)
    if not ok:
        print(f"  subject  {case.message!r}: got {pick.subject_id} @ {pick.confidence:.2f}")
    return ok


async def route(case: RouteCase, slots: asyncio.Semaphore) -> tuple[bool, bool]:
    """(correct, routed to a wrong agent)."""
    s = get_settings()
    async with slots:
        raw, _ = await get_llm().structured(
            role="agent_scores",
            model=s.orchestrator_model,
            instructions=prompts.AGENT_SCORES,
            message=f"## agents\n{describe(DIRECTORY)}\n\n## message\n{case.message}",
            output_type=AgentScores,
            seconds=30,
        )
    scores = sanitize(raw, [a.handle for a in DIRECTORY])
    got = decide(
        scores,
        route_threshold=s.route_threshold,
        margin=s.route_margin,
        clarify_floor=s.clarify_floor,
    )
    if case.kind == "clarify":
        correct = got.kind in ("clarify", "none") or (
            got.kind == "route" and got.handles[0] in case.handles
        )
    elif case.kind == "fanout":
        correct = got.kind == "fanout" and set(case.handles) <= set(got.handles)
    else:
        correct = got.kind == case.kind and set(got.handles) == set(case.handles)
    wrong = got.kind in ("route", "fanout") and not set(got.handles) <= set(case.handles)
    if not correct:
        top = sorted(scores.scores, key=lambda x: -x.score)[:3]
        print(
            f"  route    {case.message!r}: want {case.kind} {case.handles}, "
            f"got {got.kind} {got.handles} "
            f"[{', '.join(f'{x.handle}={x.score:.2f}' for x in top)}]"
        )
    return correct, wrong


async def main() -> int:
    if not get_settings().openai_api_key:
        print("Set OPENAI_API_KEY to run the orchestrator evals.")
        return 2
    slots = asyncio.Semaphore(CONCURRENCY)
    subjects = await asyncio.gather(*(subject_ok(c, slots) for c in SUBJECT_CASES))
    routes = await asyncio.gather(*(route(c, slots) for c in ROUTE_CASES))
    subject_acc = sum(subjects) / len(subjects)
    route_acc = sum(ok for ok, _ in routes) / len(routes)
    wrong = sum(w for _, w in routes) / len(routes)
    print(f"subject accuracy {subject_acc:.0%} (pass {SUBJECT_PASS:.0%})")
    print(
        f"routing accuracy {route_acc:.0%} (pass {ROUTE_PASS:.0%}), "
        f"wrong route {wrong:.0%} (max {WRONG_ROUTE_MAX:.0%})"
    )
    passed = subject_acc >= SUBJECT_PASS and route_acc >= ROUTE_PASS and wrong <= WRONG_ROUTE_MAX
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
