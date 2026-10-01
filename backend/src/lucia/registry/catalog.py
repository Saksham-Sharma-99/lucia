"""The registry, declared in code (HLD §3). sync.py mirrors it into registry_entry on startup.

Tool names are "<connector>.<tool>". Channels map a follow-up channel to the outbound tool that
sends on it. Connector `setup` tells the UI how a firm connects it.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from lucia.core.schema import AlertChannel

Setup = Literal["oauth_link", "form", "none"]
Direction = Literal["inbound", "outbound"]
RiskTier = Literal["read", "internal_write", "external_comm"]

_TO = {"type": "object", "required": ["to"], "properties": {"to": {"type": "string"}}}
_CHANNEL = {
    "type": "object",
    "required": ["channel"],
    "properties": {"channel": {"type": "string", "description": "Slack channel id or name"}},
}


@dataclass(frozen=True)
class Connector:
    name: str
    display_name: str
    description: str
    setup: Setup
    available: bool = True
    params_schema: dict[str, Any] = field(default_factory=dict)  # per-firm setup form fields


@dataclass(frozen=True)
class Tool:
    connector: str
    tool: str
    display_name: str
    description: str
    direction: Direction
    risk_tier: RiskTier
    is_async: bool = False
    available: bool = True
    params_schema: dict[str, Any] = field(default_factory=dict)  # test inputs

    @property
    def name(self) -> str:
        return f"{self.connector}.{self.tool}"


@dataclass(frozen=True)
class PolicyRule:
    name: str
    display_name: str
    description: str
    params_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Channel:
    name: str
    display_name: str
    tool: str


@dataclass(frozen=True)
class EvidenceKind:
    name: str
    display_name: str
    description: str


CONNECTORS = [
    Connector(
        "slack",
        "Slack",
        "Listen to @mentions and post messages in a firm's workspace.",
        "oauth_link",
    ),
    Connector("gmail", "Gmail", "Send and read email from a firm's mailbox.", "oauth_link"),
    Connector(
        "vapi",
        "Vapi voice",
        "Place phone calls from a firm's number in the platform's Vapi account.",
        "form",
        params_schema={
            "type": "object",
            "required": ["phone_number_id"],
            "properties": {"phone_number_id": {"type": "string", "minLength": 1}},
        },
    ),
    Connector("fax", "Fax", "Send faxes to providers. Not available yet.", "none", available=False),
]

TOOLS = [
    Tool(
        "slack",
        "listen_mention",
        "Listen to @mentions",
        "Receive messages that mention the bot.",
        "inbound",
        "read",
    ),
    Tool(
        "slack",
        "read_thread",
        "Read thread",
        "Read the messages of a Slack thread.",
        "inbound",
        "read",
    ),
    Tool(
        "slack",
        "send_message",
        "Send message",
        "Post a message to a channel or thread.",
        "outbound",
        "internal_write",
        params_schema=_CHANNEL,
    ),
    Tool(
        "slack",
        "post_file",
        "Post file",
        "Upload a file to a channel.",
        "outbound",
        "internal_write",
        params_schema=_CHANNEL,
    ),
    Tool(
        "gmail", "list_inbox", "List inbox", "List new messages in the mailbox.", "inbound", "read"
    ),
    Tool("gmail", "read_thread", "Read thread", "Read an email thread.", "inbound", "read"),
    Tool(
        "gmail",
        "send_email",
        "Send email",
        "Send an email from the mailbox.",
        "outbound",
        "external_comm",
        params_schema=_TO,
    ),
    Tool(
        "vapi",
        "place_call",
        "Place call",
        "Call a number and run a voice conversation.",
        "outbound",
        "external_comm",
        is_async=True,
        params_schema={
            **_TO,
            "properties": {"to": {"type": "string", "pattern": r"^\+[1-9]\d{6,14}$"}},
        },
    ),
    Tool(
        "vapi",
        "receive_call",
        "Receive call",
        "Answer calls to the firm's number. Not available yet.",
        "inbound",
        "read",
        available=False,
    ),
    Tool(
        "fax",
        "send_fax",
        "Send fax",
        "Send a document by fax.",
        "outbound",
        "external_comm",
        available=False,
    ),
]

_ROLES = {
    "type": "array",
    "items": {"type": "string", "enum": ["client", "provider", "insurer", "other"]},
}
_TIME = {"type": "string", "pattern": r"^([01]\d|2[0-3]):[0-5]\d$"}

POLICY_RULES = [
    PolicyRule(
        "recipient_must_be_contact",
        "Recipient must be a contact",
        "Only send to contacts on the matter. Required when any external tool is enabled.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    PolicyRule(
        "consent_required",
        "Consent required",
        "Block contact on a channel unless the contact has consented.",
        {
            "type": "object",
            "required": ["channel", "roles"],
            "properties": {
                "channel": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["email", "voice", "slack"]},
                    "minItems": 1,
                },
                "roles": {**_ROLES, "minItems": 1},
            },
            "additionalProperties": False,
        },
    ),
    PolicyRule(
        "quiet_hours",
        "Quiet hours",
        "Defer outreach inside this window.",
        {
            "type": "object",
            "required": ["start", "end", "tz"],
            "properties": {
                "start": _TIME,
                "end": _TIME,
                "tz": {"type": "string", "enum": ["recipient", "firm"]},
            },
            "additionalProperties": False,
        },
    ),
    PolicyRule(
        "opt_out_enforced",
        "Honor opt-outs",
        "Stop contacting anyone who opts out, on that channel.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    PolicyRule(
        "attachment_allowed",
        "Attachment rules",
        "Which document kinds may be sent to which contact roles.",
        {"type": "object", "additionalProperties": _ROLES},
    ),
    PolicyRule(
        "per_subject_contact_cap",
        "Contact cap per matter",
        "Maximum contacts per contact per day on one matter.",
        {
            "type": "object",
            "required": ["n"],
            "properties": {"n": {"type": "integer", "minimum": 1, "maximum": 20}},
            "additionalProperties": False,
        },
    ),
]

CHANNELS = [
    Channel("email", "Email", "gmail.send_email"),
    Channel("voice", "Voice call", "vapi.place_call"),
    Channel("slack", "Slack", "slack.send_message"),
]

EVIDENCE_KINDS = [
    EvidenceKind("document", "Document", "A received file, such as records or bills."),
    EvidenceKind("call_report", "Call report", "The outcome of a completed call."),
    EvidenceKind("inbound_message", "Inbound message", "A reply from the contact."),
    EvidenceKind("human_close", "Closed by a human", "A person marked the item done."),
]

CONNECTOR_SETUP: dict[str, Setup] = {c.name: c.setup for c in CONNECTORS}
CHANNEL_TOOLS: dict[str, str] = {c.name: c.tool for c in CHANNELS}
ALERT_CHANNELS = get_args(AlertChannel)
