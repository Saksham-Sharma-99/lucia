"""What may leave the app (CHANNELS_SPEC §7, D36): Slack and other outside channels get
operational text only; names and clinical detail stay behind a link into Lucia."""

import re
from collections.abc import Iterable

_IDENTIFIERS = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b(?:\d[ -]?){13,16}\b|\bMRN:?\s*\d+", re.I)
_WHAT = {
    "question": "needs your input",
    "verify": "needs you to check something",
    "confirm_completion": "thinks the work is done",
    "uncertain_send": "needs you to confirm a send",
    "guardrail_block": "held a message for review",
}


def public_text(*, kind: str, subject: str, agent: str) -> str:
    what = _WHAT.get(kind, "has an update")
    return f"@{agent} {what} on {subject} · Open Lucia for details"


def check_public(text: str, names: Iterable[str]) -> bool:
    """True when `text` names no contact and carries no identifier."""
    lowered = text.lower()
    return not _IDENTIFIERS.search(text) and not any(n.lower() in lowered for n in names if n)
