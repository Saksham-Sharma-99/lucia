"""Golden requests for the drafter. Each runs the whole wizard chain: prompt, capabilities,
policies, schedules. Expectations are loose on purpose: they pin what any good draft must do."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    id: str
    instruction: str
    name: str = ""
    tools_present: tuple[str, ...] = ()
    tools_absent: tuple[str, ...] = ()
    rules_present: tuple[str, ...] = ()
    # Any of these; empty: not checked. A recurrence of None means one-off work.
    follow_up_modes: tuple[str, ...] = ()
    recurrence_days: tuple[int | None, ...] = ()
    unmapped_mentions: tuple[str, ...] = ()


CASES = [
    Case(
        "records",
        "Request and chase medical records and itemized bills from providers by email and "
        "phone until we get them. Escalate to a paralegal after about two weeks of silence.",
        name="Medical records follow-up",
        tools_present=("gmail.send_email", "vapi.place_call"),
        rules_present=("recipient_must_be_contact",),
        follow_up_modes=("fixed_ladder", "dynamic"),
        recurrence_days=(None,),
    ),
    Case(
        "checkin",
        "Call each client every two weeks to see how they are doing and whether anything "
        "changed with their treatment. Email them if they don't pick up. Never give legal advice.",
        name="Client check-in",
        tools_present=("vapi.place_call", "gmail.send_email"),
        rules_present=("recipient_must_be_contact", "opt_out_enforced"),
        recurrence_days=(14,),
    ),
    Case(
        "liens",
        "Confirm outstanding lien amounts with insurers and lienholders by email and get the "
        "final lien letter. Follow up as needed, but not more than twice a week.",
        name="Lien follow-up",
        tools_present=("gmail.send_email",),
        rules_present=("recipient_must_be_contact",),
        follow_up_modes=("dynamic", "fixed_ladder"),
    ),
    Case(
        "intake",
        "Answer inbound calls from people who may want to hire the firm, collect the basic "
        "facts of their accident, and post a summary for the intake team in Slack.",
        name="Intake line",
        tools_present=("vapi.receive_call", "slack.send_message"),
        tools_absent=("gmail.send_email",),
    ),
    Case(
        "deadlines_digest",
        "Each morning, post a short list of this week's filing deadlines in the firm's "
        "#litigation Slack channel. It never contacts anyone outside the firm.",
        name="Deadline digest",
        tools_present=("slack.send_message",),
        tools_absent=("gmail.send_email", "vapi.place_call"),
        follow_up_modes=("none",),
    ),
    Case(
        "fax_only",
        "Fax HIPAA authorization forms to providers and confirm they arrived.",
        name="Authorization sender",
        tools_absent=("fax.send_fax",),
        unmapped_mentions=("fax",),
    ),
    Case(
        "sms_reminders",
        "Text clients by SMS the day before every medical appointment to remind them to go.",
        name="Appointment reminders",
        unmapped_mentions=("sms",),
    ),
    Case(
        "one_shot_bills",
        "Email each provider once to request an itemized bill. Do not follow up; a person "
        "handles anything after that.",
        name="Bill request",
        tools_present=("gmail.send_email",),
        tools_absent=("vapi.place_call",),
        follow_up_modes=("none", "fixed_ladder"),
        recurrence_days=(None,),
    ),
]
