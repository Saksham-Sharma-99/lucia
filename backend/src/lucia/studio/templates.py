"""Seeded reference agents (HLD Appendix A, adapted to backend-plan §6).

Each agent is an `AgentCreate`, so it is validated when this module loads. Membership in
`TEMPLATES` is what makes an agent a template."""

from lucia.core.schema import PolicyRuleRef
from lucia.studio.config_schema import (
    AlertPolicy,
    Capability,
    Dynamic,
    EndConditions,
    EscalateAfter,
    FollowUp,
    Hitl,
    LadderRung,
    Models,
    Recurrence,
    VersionConfig,
)
from lucia.studio.schemas import AgentCreate

_MODELS = Models(loop="gpt-5.6-sol", guardrail="gpt-5.6-luna", judge="gpt-5.6")
_DAY = 24
_MIN_PACK = PolicyRuleRef(rule="recipient_must_be_contact")
_EMAIL_AND_VOICE = [
    Capability(connector="gmail", tools=["gmail.send_email", "gmail.read_thread"]),
    Capability(connector="vapi", tools=["vapi.place_call"]),
]


def _quiet_hours(start: str, end: str) -> PolicyRuleRef:
    """The window in which outreach is deferred (blocked, D50)."""
    return PolicyRuleRef(rule="quiet_hours", params={"start": start, "end": end, "tz": "recipient"})


RECORDS = AgentCreate(
    handle="records",
    name="Medical Records Follow-up",
    description="Requests and chases medical records and bills from providers until received",
    use_cases=["get medical records", "get bills", "chase provider"],
    config=VersionConfig(
        system_prompt=(
            "You obtain complete medical records and itemized bills for the client's matter "
            "from each provider. Be polite, specific and persistent."
        ),
        models=_MODELS,
        capabilities=_EMAIL_AND_VOICE,
        follow_up=FollowUp(
            mode="fixed_ladder",
            ladder=[
                LadderRung(channel="email", wait_hours=7 * _DAY, attempts=2),
                LadderRung(channel="voice", wait_hours=5 * _DAY, attempts=2),
                LadderRung(action="escalate", wait_hours=0, urgency="P1"),
            ],
        ),
        end_conditions=EndConditions(max_duration_days=120, max_steps=600),
        policy_pack=[
            _MIN_PACK,
            PolicyRuleRef(rule="attachment_allowed", params={"hipaa_auth": ["provider"]}),
            _quiet_hours("18:00", "08:00"),
            PolicyRuleRef(rule="per_subject_contact_cap", params={"n": 2}),
        ],
        hitl=Hitl(ask_on=["channel_not_supported", "missing_authorization", "fee_required"]),
        alert_policy=AlertPolicy(
            default_channels={
                "P0": ["slack_dm", "email"],
                "P1": ["slack_thread", "email"],
                "P2": ["digest"],
            }
        ),
    ),
)

CHECKIN = AgentCreate(
    handle="checkin",
    name="Client Check-in",
    description="Calls the client periodically, learns how they are doing, reports changes",
    use_cases=["check on client", "client wellbeing update"],
    auto_delegate=True,
    version_policy="follow_active_at_cycle",
    config=VersionConfig(
        system_prompt=(
            "You are a warm, brief check-in caller for the firm. "
            "Never give legal or medical advice."
        ),
        models=_MODELS,
        capabilities=[
            Capability(connector="vapi", tools=["vapi.place_call"]),
            Capability(connector="gmail", tools=["gmail.send_email"]),
        ],
        recurrence=Recurrence(every_days=14),
        follow_up=FollowUp(
            mode="fixed_ladder",
            ladder=[
                LadderRung(channel="voice", wait_hours=0),
                LadderRung(channel="voice", wait_hours=2 * _DAY),
                LadderRung(channel="email", wait_hours=0),
                LadderRung(channel="voice", wait_hours=2 * _DAY),
                LadderRung(action="flag", wait_hours=0, urgency="P2"),
            ],
        ),
        end_conditions=EndConditions(max_duration_days=730, max_steps=2000),
        policy_pack=[
            _MIN_PACK,
            PolicyRuleRef(
                rule="consent_required", params={"channel": ["voice", "email"], "roles": ["client"]}
            ),
            _quiet_hours("20:00", "09:00"),
            PolicyRuleRef(rule="opt_out_enforced"),
        ],
        hitl=Hitl(ask_on=["client_distressed", "legal_question"]),
        alert_policy=AlertPolicy(
            default_channels={"P0": ["slack_dm", "email"], "P1": ["slack_thread"], "P2": ["digest"]}
        ),
    ),
)

LIENS = AgentCreate(
    handle="liens",
    name="Lien Follow-up",
    description="Confirms lien amounts with insurers and lienholders and chases final letters",
    use_cases=["confirm lien amount", "get final lien letter"],
    config=VersionConfig(
        system_prompt=(
            "You confirm outstanding lien amounts and obtain final lien letters "
            "from insurers and lienholders."
        ),
        models=_MODELS,
        capabilities=_EMAIL_AND_VOICE,
        follow_up=FollowUp(
            mode="dynamic",
            dynamic=Dynamic(
                min_hours=5 * _DAY,
                max_hours=15 * _DAY,
                channels=["email", "voice"],
                escalate_after=EscalateAfter(attempts=4, urgency="P1"),
            ),
        ),
        policy_pack=[_MIN_PACK, _quiet_hours("18:00", "08:00")],
        alert_policy=AlertPolicy(
            default_channels={"P0": ["slack_dm"], "P1": ["slack_thread"], "P2": ["digest"]}
        ),
    ),
)

TEMPLATES = [RECORDS, CHECKIN, LIENS]

# The runtime demo amends @checkin to this voice-only v2 (D56): no Gmail connection needed.
CHECKIN_VOICE_ONLY = CHECKIN.config.model_copy(
    update={
        "capabilities": [Capability(connector="vapi", tools=["vapi.place_call"])],
        "follow_up": FollowUp(
            mode="fixed_ladder",
            ladder=[
                LadderRung(channel="voice", wait_hours=0),
                LadderRung(channel="voice", wait_hours=2 * _DAY),
                LadderRung(action="flag", wait_hours=0, urgency="P2"),
            ],
        ),
        "policy_pack": [
            _MIN_PACK,
            PolicyRuleRef(
                rule="consent_required", params={"channel": ["voice"], "roles": ["client"]}
            ),
            _quiet_hours("20:00", "09:00"),
            PolicyRuleRef(rule="opt_out_enforced"),
        ],
    }
)
