"""Labeled cases for the orchestrator's model calls (ORCHESTRATOR_SPEC §12)."""

import uuid
from dataclasses import dataclass

from lucia.orchestrator.directory import DirectoryAgent
from lucia.subjects.search import Candidate


def _sid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


SUBJECTS = [
    Candidate(
        _sid(1),
        "Doe v. Acme Trucking",
        "matter",
        "DOE-2026-001",
        ["Jane Doe", "St. Mary's ER"],
        0.6,
    ),
    Candidate(_sid(2), "Doe v. Apex Logistics", "matter", "DOE-2025-014", ["John Doe"], 0.5),
    Candidate(
        _sid(3), "Roe v. City Bus", "matter", "ROE-2026-003", ["Mary Roe", "Dr. Lee PT"], 0.4
    ),
    Candidate(_sid(4), "Smith slip and fall", "matter", "SMI-2026-010", ["Alan Smith"], 0.4),
    Candidate(_sid(5), "Garcia v. Northside Clinic", "matter", "GAR-2026-002", ["Ana Garcia"], 0.4),
    Candidate(_sid(6), "Acme Corp (prospect)", "prospect", None, ["Bill Acme"], 0.4),
    Candidate(_sid(7), "Nguyen dog bite", "matter", "NGU-2026-004", ["Linh Nguyen"], 0.3),
    Candidate(_sid(8), "Patel v. Rideshare", "matter", "PAT-2026-008", ["Ravi Patel"], 0.3),
    Candidate(_sid(9), "Kim workplace injury", "matter", "KIM-2026-005", ["Soo Kim"], 0.3),
    Candidate(_sid(10), "Lopez v. Metro Transit", "matter", "LOP-2026-006", ["Maria Lopez"], 0.3),
]


@dataclass(frozen=True)
class SubjectCase:
    message: str
    expected: uuid.UUID | None  # None: the model must not lock confidently


SUBJECT_CASES = [
    SubjectCase("call Jane about her check-in on the trucking case", _sid(1)),
    SubjectCase("get St. Mary's records for Jane Doe", _sid(1)),
    SubjectCase("chase Dr. Lee for Mary Roe's PT notes", _sid(3)),
    SubjectCase("check in with Mary Roe, the bus case", _sid(3)),
    SubjectCase("follow up on the Apex Logistics matter", _sid(2)),
    SubjectCase("John Doe needs a check-in call", _sid(2)),
    SubjectCase("call Alan about the slip and fall", _sid(4)),
    SubjectCase("records for Ana Garcia from the Northside clinic", _sid(5)),
    SubjectCase("reach out to Bill at Acme about the demo", _sid(6)),
    SubjectCase("check how Linh is doing after the dog bite", _sid(7)),
    SubjectCase("Ravi Patel's rideshare case needs the police report", _sid(8)),
    SubjectCase("Soo Kim's workplace injury, call her this week", _sid(9)),
    SubjectCase("Maria Lopez metro transit case, get her bills", _sid(10)),
    SubjectCase("the Garcia clinic matter: confirm the lien", _sid(5)),
    SubjectCase("Jane Doe's case: did St. Mary's send the bills?", _sid(1)),
    SubjectCase("call Ms. Roe", _sid(3)),
    SubjectCase("Kim case update please", _sid(9)),
    SubjectCase("Nguyen matter: schedule a check-in", _sid(7)),
    SubjectCase("Patel: call the client", _sid(8)),
    SubjectCase("Lopez: chase the bills", _sid(10)),
    SubjectCase("call the Doe client", None),  # Jane or John
    SubjectCase("check in with the client", None),
    SubjectCase("get the records", None),
    SubjectCase("Acme case update", None),  # Acme Trucking or Acme Corp
    SubjectCase("call Maria", None),  # Maria Lopez or Mary Roe
    SubjectCase("the bus case", _sid(3)),
    SubjectCase("Alan Smith", _sid(4)),
    SubjectCase("the Johnson matter", None),  # not on the list
    SubjectCase("call Dr. Lee about the PT records", _sid(3)),
    SubjectCase("chase records for the slip and fall", _sid(4)),
]

DIRECTORY = [
    DirectoryAgent(
        _sid(101),
        "records",
        "Medical Records Follow-up",
        "Requests and chases medical records and bills from providers until received",
        ["get medical records", "get bills", "chase provider"],
        ["gmail.send_email", "vapi.place_call"],
    ),
    DirectoryAgent(
        _sid(102),
        "checkin",
        "Client Check-in",
        "Calls the client periodically, learns how they are doing, reports changes",
        ["check on client", "client wellbeing update"],
        ["vapi.place_call"],
    ),
    DirectoryAgent(
        _sid(103),
        "liens",
        "Lien Follow-up",
        "Confirms lien amounts with insurers and lienholders and chases final letters",
        ["confirm lien amount", "get final lien letter"],
        ["gmail.send_email", "vapi.place_call"],
    ),
    DirectoryAgent(
        _sid(104),
        "sdr",
        "Sales Development",
        "Calls prospects to book a demo of the firm's services",
        ["call a prospect", "book a demo"],
        ["vapi.place_call"],
    ),
    DirectoryAgent(
        _sid(105),
        "intake",
        "New Client Intake",
        "Collects a new client's details and documents to open a matter",
        ["intake a new client", "collect client documents"],
        ["gmail.send_email"],
    ),
]


@dataclass(frozen=True)
class RouteCase:
    message: str
    kind: str  # route | clarify | none | fanout
    handles: tuple[str, ...] = ()


ROUTE_CASES = [
    RouteCase("get the medical records from St. Mary's", "route", ("records",)),
    RouteCase("chase the hospital for the itemized bills", "route", ("records",)),
    RouteCase("Dr. Lee hasn't sent the PT notes, follow up", "route", ("records",)),
    RouteCase("call Jane and see how she's feeling", "route", ("checkin",)),
    RouteCase("do a wellbeing check with the client", "route", ("checkin",)),
    RouteCase("find out if the client has had any new treatment", "route", ("checkin",)),
    RouteCase("confirm the final lien amount with Aetna", "route", ("liens",)),
    RouteCase("get the final lien letter from the insurer", "route", ("liens",)),
    RouteCase("Medicare lien: confirm what we owe", "route", ("liens",)),
    RouteCase("call the prospect and book a demo", "route", ("sdr",)),
    RouteCase("reach out to Acme Corp about our services", "route", ("sdr",)),
    RouteCase("open a matter for the new client and collect her documents", "route", ("intake",)),
    RouteCase("we signed a new client, start intake", "route", ("intake",)),
    RouteCase(
        "get the records and also check in with the client", "fanout", ("records", "checkin")
    ),
    RouteCase("confirm the lien and request the bills", "fanout", ("liens", "records")),
    RouteCase("call the client and get their records", "fanout", ("checkin", "records")),
    RouteCase("draft the demand letter to the adjuster", "none"),
    RouteCase("negotiate the bill down with the hospital", "none"),
    RouteCase("file the complaint with the court", "none"),
    RouteCase("what's the weather tomorrow", "none"),
    RouteCase("follow up with them", "clarify", ("records", "checkin", "liens", "sdr")),
    RouteCase("call them", "clarify", ("checkin", "sdr", "records", "liens")),
    RouteCase("chase it", "clarify", ("records", "liens")),
    RouteCase("send the documents", "clarify", ("intake", "records")),
    RouteCase("get the bills", "route", ("records",)),
    RouteCase("check on the client", "route", ("checkin",)),
    RouteCase("lien letter please", "route", ("liens",)),
    RouteCase("book a demo with the lead", "route", ("sdr",)),
    RouteCase("intake for the new client", "route", ("intake",)),
    RouteCase("ask the provider when the records will arrive", "route", ("records",)),
]
