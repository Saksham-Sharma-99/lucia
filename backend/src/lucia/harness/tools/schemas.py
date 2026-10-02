"""Argument schemas of the harness tools (no imports, so the agent view can read them)."""

EMIT_FINDING = {
    "type": "object",
    "required": ["kind", "summary", "urgency", "data"],
    "properties": {
        "kind": {"type": "string", "description": "snake_case, e.g. new_provider"},
        "summary": {"type": "string", "maxLength": 500},
        "urgency": {"type": "string", "enum": ["P0", "P1", "P2"]},
        "data": {"type": "object"},
    },
    "additionalProperties": False,
}
JOURNAL_APPEND = {
    "type": "object",
    "required": ["text"],
    "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 2000}},
    "additionalProperties": False,
}
SCHEMAS = {
    "harness.emit_finding": ("Report a meaningful update about the subject.", EMIT_FINDING),
    "harness.journal_append": ("Keep a note for later in this run.", JOURNAL_APPEND),
}
