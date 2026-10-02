"""The drafter's own instructions: they render, and every id they name exists."""

import json
import re
from typing import Any, get_args

import pytest

from lucia.registry.catalog import ALERT_CHANNELS, CHANNEL_TOOLS
from lucia.studio.drafter.outputs import output_model
from lucia.studio.drafter.prompts import Name, as_input, catalog, instructions
from lucia.studio.drafter.schemas import Section
from tests.factories import snapshot

SNAP = snapshot()
# Backticked words in the prompts that are not registry ids or output fields.
EXAMPLES = {
    # policies.md: sample values for free-form fields
    "hipaa_auth",
    "legal_question",
    "client_distressed",
    "missing_authorization",
    "fee_required",
    # every prompt's "What you get": keys of the JSON input (prompts.as_input)
    "instruction",
    "basic",
    "current_prompt",
    "context",
    "system_prompt",
    "upstream",
    "upstream.capabilities",
}


def _schema_words(schema: Any) -> set[str]:
    """Every property name and enum value in an output model's JSON schema."""
    if isinstance(schema, dict):
        words = set(schema.get("properties", {})) | {str(v) for v in schema.get("enum", [])}
        return words.union(*(_schema_words(v) for v in schema.values()))
    if isinstance(schema, list):
        return set().union(*(_schema_words(v) for v in schema))
    return set()


def _known() -> set[str]:
    words = {*SNAP.tools, *SNAP.policy_rules, *SNAP.connectors, *CHANNEL_TOOLS, *ALERT_CHANNELS}
    sections: list[tuple[Section, list[str]]] = [
        ("capabilities", []),
        ("policies", []),
        ("schedules", list(SNAP.tools)),
    ]
    for section, tools in sections:
        words |= _schema_words(output_model(section, SNAP, tools).model_json_schema())
    return words | {"recipient", "firm", "P0", "P1", "P2", "null"} | EXAMPLES


@pytest.mark.parametrize("name", get_args(Name))
def test_instructions_render_with_the_catalog(name: Name) -> None:
    text = instructions(name, SNAP)
    assert "$" not in text
    assert "`gmail.send_email`" in text


@pytest.mark.parametrize("name", get_args(Name))
def test_every_id_the_instructions_name_exists(name: Name) -> None:
    named = set(re.findall(r"`([^`\s]+)`", instructions(name, SNAP)))
    assert named - _known() == set()


def test_catalog_lists_what_exists_and_flags_what_does_not() -> None:
    text = catalog(SNAP)
    assert "- `gmail.send_email`: Send an email from the mailbox. (contacts people)" in text
    assert "Fax (`fax`): not available yet" in text
    assert "fax.send_fax" not in text
    assert "`email`: sends with `gmail.send_email`" in text


def test_input_drops_empty_parts_only() -> None:
    sent = json.loads(as_input(a="x", b=None, c="", d=[], e={}, f=0, g=False, h=["y"]))
    assert sent == {"a": "x", "f": 0, "g": False, "h": ["y"]}
