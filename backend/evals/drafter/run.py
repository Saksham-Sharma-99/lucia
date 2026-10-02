"""Run the drafter evals against the real model: `make eval-drafter` (needs OPENAI_API_KEY).

Each case runs the wizard chain (the prompt, then each section fed what came before), checks
the combined config, and has the judge grade the prompt. Exits 1 below the thresholds, 2
without a key.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from evals.drafter.cases import CASES, Case
from lucia.core.config import get_settings
from lucia.registry.snapshot import RegistrySnapshot, catalog_snapshot
from lucia.studio.config_schema import VersionConfig
from lucia.studio.drafter import schemas as s
from lucia.studio.drafter import service
from lucia.studio.drafter.llm import Drafter, DrafterError, openai_drafter
from lucia.studio.validator import validate_config

CHECKS_PASS = 0.9
JUDGE_PASS = 4.0
JUDGE = (Path(__file__).parent / "judge.md").read_text()
JUDGE_MODEL = os.environ.get("DRAFTER_JUDGE_MODEL", "gpt-5.6")
CONCURRENCY = 4  # cases in flight; keeps clear of rate limits
SECTIONS: tuple[s.Section, ...] = ("capabilities", "policies", "schedules")


class Judgment(BaseModel):
    score: int = Field(ge=1, le=5)
    reasons: str


class Result(BaseModel):
    case: str
    checks: dict[str, bool] = {}
    score: int = 0
    reasons: str = ""
    error: str = ""


async def draft_config(
    case: Case, snap: RegistrySnapshot, drafter: Drafter
) -> tuple[dict[str, Any], str]:
    """The config fields the wizard would end with, and every `unmapped` note."""
    basic = s.Basic(name=case.name)
    prompt = ""
    async for event in service.draft_prompt(
        s.PromptDraftRequest(instruction=case.instruction, basic=basic), snap, drafter
    ):
        if isinstance(event, s.PromptFailed):
            raise RuntimeError(f"prompt {event.code}")
        if isinstance(event, s.PromptDone):
            prompt = event.prompt
    config: dict[str, Any] = {"system_prompt": prompt}
    notes: list[str] = []
    for section in SECTIONS:
        upstream = s.DraftContext.model_validate(
            {k: v for k, v in config.items() if k in s.DraftContext.model_fields}
        )
        req = s.SectionDraftRequest(
            section=section, system_prompt=prompt, basic=basic, upstream=upstream
        )
        draft = await service.draft_section(req, snap, drafter)
        config |= draft.model_dump(mode="json", exclude={"section", "rationale", "unmapped"})
        notes += draft.unmapped
    return config, " ".join(notes).lower()


def check(
    case: Case, config: dict[str, Any], notes: str, snap: RegistrySnapshot
) -> dict[str, bool]:
    tools = {t for cap in config["capabilities"] for t in cap["tools"]}
    rules = {r["rule"] for r in config["policy_pack"]}
    checks = {
        **{f"has {t}": t in tools for t in case.tools_present},
        **{f"lacks {t}": t not in tools for t in case.tools_absent},
        **{f"rule {r}": r in rules for r in case.rules_present},
        **{f"notes {w}": w in notes for w in case.unmapped_mentions},
    }
    if case.follow_up_modes:
        checks["follow-up mode"] = config["follow_up"]["mode"] in case.follow_up_modes
    if case.recurrence_days:
        every = (config["recurrence"] or {}).get("every_days")
        checks["recurrence"] = every in case.recurrence_days
    allowed = get_settings().allowed_models
    models = {"loop": allowed[0], "guardrail": allowed[-1], "judge": allowed[0]}
    try:
        cfg = VersionConfig.model_validate({**config, "models": models})
        checks["config valid"] = not validate_config(cfg, snap, allowed)
    except ValidationError:  # e.g. no capabilities at all
        checks["config valid"] = False
    return checks


async def run_case(
    case: Case, snap: RegistrySnapshot, drafter: Drafter, judge: Drafter, slots: asyncio.Semaphore
) -> Result:
    """One case; any failure is recorded on its result rather than stopping the run."""
    async with slots:
        try:
            config, notes = await draft_config(case, snap, drafter)
            judgment = await judge.run_structured(
                JUDGE,
                json.dumps({"request": case.instruction, "prompt": config["system_prompt"]}),
                Judgment,
                60,
            )
        except DrafterError as e:
            return Result(case=case.id, error=e.code)
        except Exception as e:  # an eval run reports every case, whatever broke
            return Result(case=case.id, error=f"{type(e).__name__}: {e}")
    return Result(
        case=case.id,
        checks=check(case, config, notes, snap),
        score=judgment.score,
        reasons=judgment.reasons,
    )


async def main() -> int:
    settings = get_settings()
    if not settings.openai_api_key:
        print("Set OPENAI_API_KEY to run the drafter evals.")
        return 2
    snap = catalog_snapshot()
    drafter = openai_drafter(settings.drafter_model, settings.openai_api_key)
    judge = openai_drafter(JUDGE_MODEL, settings.openai_api_key)
    slots = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*(run_case(c, snap, drafter, judge, slots) for c in CASES))

    for r in results:
        failed = ", ".join(name for name, ok in r.checks.items() if not ok) or "-"
        print(f"{r.case:<18} {r.error or f'judge {r.score}/5':<14} failed: {failed}")
        if r.reasons:
            print(f"{'':<18} {r.reasons}")

    checks = [ok for r in results for ok in r.checks.values()]
    errors = any(r.error for r in results)
    pass_rate = 0.0 if errors or not checks else sum(checks) / len(checks)
    judged = [r.score for r in results if not r.error]
    mean = sum(judged) / len(judged) if judged else 0.0
    print(
        f"\nchecks {pass_rate:.0%} (need {CHECKS_PASS:.0%}) · judge {mean:.2f} (need {JUDGE_PASS})"
    )
    return 0 if pass_rate >= CHECKS_PASS and mean >= JUDGE_PASS else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
