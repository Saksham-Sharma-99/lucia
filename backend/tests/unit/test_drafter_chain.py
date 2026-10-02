"""The drafter evals: the wizard chain they run, the checks, and that one broken case never
stops the run."""

import asyncio

import pytest
from evals.drafter.cases import Case
from evals.drafter.run import check, draft_config, run_case
from pydantic import BaseModel

from lucia.studio.drafter.llm import DrafterError
from tests.factories import CHANNEL_RUNG, FakeDrafter, draft_output, snapshot

SNAP = snapshot()
CASE = Case(
    "records",
    "Chase records by email.",
    tools_present=("gmail.send_email",),
    tools_absent=("vapi.place_call",),
    rules_present=("recipient_must_be_contact",),
    follow_up_modes=("fixed_ladder",),
    recurrence_days=(None,),
    unmapped_mentions=("fax",),
)


def _fake() -> FakeDrafter:
    fake = FakeDrafter()
    fake.outputs["CapabilitiesOut"] = draft_output("CapabilitiesOut", unmapped=["Fax"])
    fake.outputs["SchedulesOut"] = draft_output(
        "SchedulesOut", mode="fixed_ladder", ladder=[CHANNEL_RUNG]
    )
    return fake


class _Judge(FakeDrafter):
    async def run_structured[T: BaseModel](
        self, instructions: str, message: str, output_type: type[T], seconds: float
    ) -> T:
        if self.error:
            raise self.error
        return output_type.model_validate({"score": 5, "reasons": "Clear."})


async def test_each_section_sees_the_earlier_drafts() -> None:
    fake = _fake()
    config, notes = await draft_config(CASE, SNAP, fake)
    prompt_call, caps_call, policies_call, schedules_call = fake.inputs
    assert prompt_call["instruction"] == CASE.instruction
    assert "upstream" not in caps_call  # nothing drafted yet
    assert policies_call["upstream"]["capabilities"] == config["capabilities"]
    assert schedules_call["upstream"]["policy_pack"] == config["policy_pack"]
    assert config["system_prompt"] == "## Role\nYou chase records."
    assert notes == "fax"


async def test_a_good_draft_passes_every_check() -> None:
    config, notes = await draft_config(CASE, SNAP, _fake())
    checks = check(CASE, config, notes, SNAP)
    assert checks and all(checks.values()), checks


async def test_failed_checks_are_reported() -> None:
    config, notes = await draft_config(CASE, SNAP, _fake())
    case = Case("calls", "Call people.", tools_present=("vapi.place_call",), recurrence_days=(14,))
    checks = check(case, config, notes, SNAP)
    assert checks == {"has vapi.place_call": False, "recurrence": False, "config valid": True}


async def test_a_config_without_tools_is_invalid() -> None:
    fake = _fake()
    fake.outputs["CapabilitiesOut"]["tools"] = []
    fake.outputs["SchedulesOut"] = draft_output("SchedulesOut")  # "none" is all it may answer
    config, notes = await draft_config(CASE, SNAP, fake)
    assert check(Case("none", "x"), config, notes, SNAP) == {"config valid": False}


async def test_a_failed_prompt_stops_the_chain() -> None:
    fake = _fake()
    fake.fail_after = DrafterError(504, "timeout", "slow")
    with pytest.raises(RuntimeError, match="prompt timeout"):
        await draft_config(CASE, SNAP, fake)
    assert len(fake.inputs) == 1


def _broken(kind: str) -> tuple[FakeDrafter, FakeDrafter]:
    drafter, judge = _fake(), _Judge()
    if kind == "provider":
        drafter.error = DrafterError(502, "provider_error", "x")
    elif kind == "bug":
        del drafter.outputs["PoliciesOut"]  # KeyError inside the chain
    else:
        judge.error = DrafterError(504, "timeout", "slow")
    return drafter, judge


@pytest.mark.parametrize(
    ("kind", "error"),
    [("provider", "provider_error"), ("bug", "KeyError: 'PoliciesOut'"), ("judge", "timeout")],
)
async def test_a_broken_case_is_recorded_and_the_rest_still_run(kind: str, error: str) -> None:
    slots = asyncio.Semaphore(2)
    drafter, judge = _broken(kind)
    broken, ok = await asyncio.gather(
        run_case(CASE, SNAP, drafter, judge, slots),
        run_case(CASE, SNAP, _fake(), _Judge(), slots),
    )
    assert (broken.error, broken.checks, broken.score) == (error, {}, 0)
    assert (ok.error, ok.score) == ("", 5) and all(ok.checks.values())


async def test_cases_never_exceed_the_concurrency_limit() -> None:
    running, peak = 0, 0

    class Slow(_Judge):
        async def run_structured[T: BaseModel](
            self, instructions: str, message: str, output_type: type[T], seconds: float
        ) -> T:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1
            return await super().run_structured(instructions, message, output_type, seconds)

    slots = asyncio.Semaphore(2)
    await asyncio.gather(*(run_case(CASE, SNAP, _fake(), Slow(), slots) for _ in range(5)))
    assert peak == 2
