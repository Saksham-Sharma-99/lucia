"""The drafter's own instructions: one markdown file per call, with the live catalog filled in."""

import json
from functools import cache
from pathlib import Path
from string import Template
from typing import Any, Literal

from lucia.registry.catalog import ALERT_CHANNELS, CHANNEL_TOOLS
from lucia.registry.snapshot import RegistrySnapshot

Name = Literal["prompt", "capabilities", "policies", "schedules"]
PROMPTS = Path(__file__).parent / "prompts"
_RISK = {
    "read": "reads",
    "internal_write": "writes inside the firm",
    "external_comm": "contacts people",
}


@cache
def _template(name: Name) -> Template:
    return Template((PROMPTS / f"{name}.md").read_text())


def catalog(snap: RegistrySnapshot) -> str:
    lines = ["Connectors and their tools:"]
    for c in snap.connectors.values():
        if not c.available:
            lines.append(f"- {c.display_name} (`{c.name}`): not available yet. Never use it.")
            continue
        lines.append(f"- {c.display_name} (`{c.name}`): {c.description}")
        lines += [
            f"  - `{t.name}`: {t.description} ({_RISK.get(t.risk_tier or '', 'tool')})"
            for t in snap.tools.values()
            if t.connector == c.name and t.available
        ]
    lines.append("\nFollow-up channels (each needs its send tool):")
    lines += [f"- `{ch}`: sends with `{tool}`" for ch, tool in CHANNEL_TOOLS.items()]
    lines.append("\nPolicy rules:")
    lines += [f"- `{r.name}`: {r.description}" for r in snap.policy_rules.values() if r.available]
    lines.append(f"\nAlert channels: {', '.join(f'`{a}`' for a in ALERT_CHANNELS)}.")
    return "\n".join(lines)


def instructions(name: Name, snap: RegistrySnapshot) -> str:
    return _template(name).substitute(catalog=catalog(snap))


def as_input(**parts: Any) -> str:
    """The request, as the user message. JSON keeps it unambiguous for the model."""
    return json.dumps({k: v for k, v in parts.items() if v not in (None, "", [], {})}, indent=2)
