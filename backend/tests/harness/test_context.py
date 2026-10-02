import pytest

from lucia.harness.context import BUDGET_CHARS, ROLE_SECTIONS, packet


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
