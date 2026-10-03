import pytest

from lucia.db.models import Episode
from lucia.harness.context import BUDGET_CHARS, ROLE_SECTIONS, _episode_line, packet


def test_triage_sees_the_conversation_and_the_planner_does_not() -> None:
    sections = {"conversation": {"messages": ["hi"]}, "goal": "g", "tools": ["vapi.place_call"]}
    assert "## conversation" in packet("triage", sections)
    planner = packet("planner", sections)
    assert "## conversation" not in planner and "## tools" in planner


@pytest.mark.parametrize("role", sorted(ROLE_SECTIONS))
def test_every_role_renders_only_its_sections(role: str) -> None:
    sections = {name: f"<{name}>" for names in ROLE_SECTIONS.values() for name in names}
    out = packet(role, sections)
    for name in sections:
        assert (f"## {name}\n" in out) == (name in ROLE_SECTIONS[role])


def test_budget_trims_journal_then_episodes_first() -> None:
    big = "x" * BUDGET_CHARS
    out = packet("triage", {"goal": "keep me", "journal": big, "episodes": big, "tasks": "keep"})
    assert "keep me" in out and "keep" in out
    assert "## journal" not in out and "## episodes" not in out


def test_unknown_role_is_an_error() -> None:
    with pytest.raises(KeyError):
        packet("nobody", {})


def test_an_answer_episode_shows_what_the_person_said() -> None:
    answered = Episode(
        trigger_type="user_response",
        status="completed",
        outcome="task_resumed",
        metadata_={"answer": {"text": "Not SOC 2 yet; call him back", "choice": None}},
    )
    assert _episode_line(answered) == (
        'user_response completed (person answered: "Not SOC 2 yet; call him back") -> task_resumed'
    )


def test_a_reopen_instruction_shows_what_the_person_said() -> None:
    reopened = Episode(
        trigger_type="user_input",
        status="completed",
        outcome="triaged",
        metadata_={"instruction": "Tell Doe the doctor change is fine"},
    )
    assert '(person said: "Tell Doe the doctor change is fine")' in _episode_line(reopened)
