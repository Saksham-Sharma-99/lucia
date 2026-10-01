import json
from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from lucia.core.config import get_settings
from lucia.studio.drafter import llm
from lucia.studio.drafter.llm import DrafterError
from tests.factories import (
    ACTION_RUNG,
    CHANNEL_RUNG,
    DYNAMIC,
    FakeDrafter,
    Json,
    config,
    draft_output,
)

PROMPT = "/api/v1/agents/drafts/prompt"
SECTION = "/api/v1/agents/drafts/section"
GMAIL = [{"connector": "gmail", "tools": ["gmail.send_email", "gmail.read_thread"]}]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeDrafter]:
    drafter = FakeDrafter()
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "openai_drafter", lambda model, key: drafter)
    yield drafter


def _events(body: str) -> list[Json]:
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


async def test_prompt_streams_deltas_then_the_whole_prompt(
    authed: AsyncClient, fake: FakeDrafter
) -> None:
    resp = await authed.post(PROMPT, json={"instruction": "Chase medical records"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert _events(resp.text) == [
        {"type": "delta", "text": "## Role\n"},
        {"type": "delta", "text": "You chase records."},
        {"type": "done", "prompt": "## Role\nYou chase records."},
    ]


async def test_refine_sends_the_current_prompt_and_config(
    authed: AsyncClient, fake: FakeDrafter
) -> None:
    body = {
        "instruction": "Make it shorter",
        "basic": {"name": "Records", "description": "Chases records"},
        "current_prompt": "You chase records, at length.",
        "context": {"capabilities": GMAIL},
    }
    await authed.post(PROMPT, json=body)
    sent = fake.inputs[0]
    assert sent["current_prompt"] == "You chase records, at length."
    assert sent["context"]["capabilities"] == GMAIL
    assert sent["basic"]["name"] == "Records"


async def test_a_failure_mid_stream_is_an_error_event(
    authed: AsyncClient, fake: FakeDrafter
) -> None:
    fake.fail_after = DrafterError(504, "timeout", "slow")
    resp = await authed.post(PROMPT, json={"instruction": "Chase records"})
    events = _events(resp.text)
    assert events[0]["type"] == "delta"
    assert events[-1]["type"] == "error" and events[-1]["code"] == "timeout"


async def test_an_empty_prompt_is_an_error(authed: AsyncClient, fake: FakeDrafter) -> None:
    fake.deltas = ["  "]
    events = _events((await authed.post(PROMPT, json={"instruction": "x"})).text)
    assert events[-1] == {"type": "error", "code": "empty", "message": events[-1]["message"]}


async def test_instruction_is_capped(authed: AsyncClient, fake: FakeDrafter) -> None:
    assert (await authed.post(PROMPT, json={"instruction": "x" * 4000})).status_code == 200
    resp = await authed.post(PROMPT, json={"instruction": "x" * 4001})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["path"] == "/instruction"


async def test_without_a_key_drafting_is_unavailable(authed: AsyncClient) -> None:
    for url, body in (
        (PROMPT, {"instruction": "x"}),
        (SECTION, {"section": "capabilities", "system_prompt": "x"}),
    ):
        resp = await authed.post(url, json=body)
        assert resp.status_code == 503
        assert resp.headers["content-type"] == "application/problem+json"


async def test_drafting_needs_a_session(client: AsyncClient) -> None:
    resp = await client.post(
        PROMPT, json={"instruction": "x"}, headers={"X-Requested-With": "lucia"}
    )
    assert resp.status_code == 401


NOTE: Json = {"rationale": "It emails providers.", "unmapped": ["fax"]}


def _section(section: str, capabilities: list[Json] | None = GMAIL) -> Json:
    upstream = {} if capabilities is None else {"capabilities": capabilities}
    return {"section": section, "system_prompt": "Email providers.", "upstream": upstream}


async def test_capabilities_draft(authed: AsyncClient, fake: FakeDrafter) -> None:
    fake.outputs["CapabilitiesOut"] = draft_output("CapabilitiesOut", **NOTE)
    resp = await authed.post(SECTION, json=_section("capabilities", None))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"section": "capabilities", "capabilities": GMAIL, **NOTE}
    assert "upstream" not in fake.inputs[0]  # nothing chosen yet


async def test_policies_draft(authed: AsyncClient, fake: FakeDrafter) -> None:
    fake.outputs["PoliciesOut"] = draft_output(
        "PoliciesOut",
        rules=[{"rule": "per_subject_contact_cap", "n": 2}],
        ask_on=["legal_question"],
        p0_channels=["slack_dm", "email"],
    )
    resp = await authed.post(SECTION, json=_section("policies"))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["policy_pack"] == [
        {"rule": "recipient_must_be_contact", "params": {}},
        {"rule": "per_subject_contact_cap", "params": {"n": 2}},
    ]
    assert data["hitl"] == {"ask_on": ["legal_question"], "verify_evidence_below": 0.8}
    assert data["alert_policy"]["default_channels"]["P0"] == ["slack_dm", "email"]
    assert fake.inputs[0]["upstream"]["capabilities"] == GMAIL


@pytest.mark.parametrize(
    ("capabilities", "rules", "pack"),
    [
        (GMAIL, [], ["recipient_must_be_contact"]),
        (
            GMAIL,
            ["opt_out_enforced", "recipient_must_be_contact"],
            ["opt_out_enforced", "recipient_must_be_contact"],
        ),
        ([{"connector": "slack", "tools": ["slack.send_message"]}], [], []),
        (None, [], []),
    ],
    ids=["added", "kept_once", "internal_only", "no_tools_yet"],
)
async def test_the_min_rule_is_there_whenever_a_tool_contacts_people(
    authed: AsyncClient,
    fake: FakeDrafter,
    capabilities: list[Json] | None,
    rules: list[str],
    pack: list[str],
) -> None:
    fake.outputs["PoliciesOut"] = draft_output("PoliciesOut", rules=[{"rule": r} for r in rules])
    resp = await authed.post(SECTION, json=_section("policies", capabilities))
    assert [r["rule"] for r in resp.json()["policy_pack"]] == pack


async def test_schedules_draft(authed: AsyncClient, fake: FakeDrafter) -> None:
    fake.outputs["SchedulesOut"] = draft_output(
        "SchedulesOut",
        mode="fixed_ladder",
        ladder=[{**CHANNEL_RUNG, "wait_hours": 168, "attempts": 2}, ACTION_RUNG],
        recurrence_every_days=14,
        max_duration_days=730,
    )
    resp = await authed.post(SECTION, json=_section("schedules"))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["follow_up"]["ladder"] == [
        {"channel": "email", "action": None, "wait_hours": 168, "attempts": 2, "urgency": None},
        {"channel": None, "action": "escalate", "wait_hours": 0, "attempts": 1, "urgency": "P1"},
    ]
    assert data["recurrence"] == {"every_days": 14}
    assert data["end_conditions"]["max_duration_days"] == 730


async def test_an_inconsistent_draft_is_returned_for_the_form_to_flag(
    authed: AsyncClient, fake: FakeDrafter
) -> None:
    fake.outputs["SchedulesOut"] = draft_output(
        "SchedulesOut", mode="dynamic", dynamic={**DYNAMIC, "min_hours": 200}
    )
    resp = await authed.post(SECTION, json=_section("schedules"))
    assert resp.status_code == 200, resp.text
    dynamic = resp.json()["follow_up"]["dynamic"]
    assert (dynamic["min_hours"], dynamic["max_hours"]) == (200, 120)  # as drafted
    cfg = config(follow_up=resp.json()["follow_up"])
    check = await authed.post("/api/v1/agents/validate", json={"config": cfg})
    assert check.status_code == 422
    assert "min_gt_max" in [e["code"] for e in check.json()["errors"]]


@pytest.mark.parametrize(
    ("error", "status"),
    [(DrafterError(504, "timeout", "slow"), 504), (DrafterError(502, "provider_error", "x"), 502)],
)
async def test_section_failures_are_problems(
    authed: AsyncClient, fake: FakeDrafter, error: DrafterError, status: int
) -> None:
    fake.error = error
    resp = await authed.post(SECTION, json={"section": "capabilities", "system_prompt": "x"})
    assert resp.status_code == status
    assert resp.json()["status"] == status


@pytest.mark.parametrize(("size", "last"), [(20000, "done"), (20001, "error")])
async def test_a_prompt_over_the_limit_is_an_error(
    authed: AsyncClient, fake: FakeDrafter, size: int, last: str
) -> None:
    fake.deltas = ["x" * 15000, "y" * (size - 15000)]
    events = _events((await authed.post(PROMPT, json={"instruction": "x"})).text)
    assert events[-1]["type"] == last
    assert last == "done" or events[-1]["code"] == "too_long"


@pytest.mark.parametrize(
    ("url", "body", "path"),
    [
        (PROMPT, {"instruction": ""}, "/instruction"),
        (PROMPT, {"instruction": "x", "current_prompt": "p" * 20001}, "/current_prompt"),
        (PROMPT, {"instruction": "x", "tone": "warm"}, "/tone"),
        (PROMPT, {"instruction": "x", "basic": {"name": "n" * 121}}, "/basic/name"),
        (SECTION, {"section": "models", "system_prompt": "x"}, "/section"),
        (SECTION, {"section": "capabilities", "system_prompt": ""}, "/system_prompt"),
        (SECTION, {"section": "capabilities"}, "/system_prompt"),
        (
            SECTION,
            {
                "section": "policies",
                "system_prompt": "x",
                "upstream": {"capabilities": [{"connector": "gmail", "tools": []}]},
            },
            "/upstream/capabilities/0/tools",
        ),
    ],
)
async def test_bad_requests_are_422_with_the_field(
    authed: AsyncClient, fake: FakeDrafter, url: str, body: Json, path: str
) -> None:
    resp = await authed.post(url, json=body)
    assert resp.status_code == 422
    assert path in [e["path"] for e in resp.json()["errors"]]
    assert fake.inputs == []  # the model is never called
