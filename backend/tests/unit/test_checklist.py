import uuid

import pytest

from lucia.db.models import ConnectorConnection
from lucia.mappings.checklist import build_checklist
from tests.factories import config

FIRM = uuid.uuid4()
CFG = config(capabilities=[{"connector": "gmail", "tools": []}])


def conn(
    connector: str = "gmail", status: str = "connected", firm: uuid.UUID = FIRM
) -> ConnectorConnection:
    return ConnectorConnection(
        id=uuid.uuid4(), firm_id=firm, connector=connector, label="L", status=status
    )


def check(c: ConnectorConnection | None, bound: bool = True) -> tuple[bool, str]:
    conns = {str(c.id): c} if c else {}
    ids = {"gmail": str(c.id) if c else str(uuid.uuid4())} if bound else {}
    (item,) = build_checklist(FIRM, CFG, ids, conns)
    return item.ok, item.reason


def test_bound_connected_connection_passes() -> None:
    assert check(conn()) == (True, "Bound to L")


@pytest.mark.parametrize(
    ("c", "bound", "reason"),
    [
        (None, False, "Pick a gmail connection"),
        (None, True, "Connection not found for this firm"),
        (conn(firm=uuid.uuid4()), True, "Connection not found for this firm"),
        (conn("slack"), True, "Connection is slack, not gmail"),
        (conn(status="pending"), True, "Connection is pending; finish connecting it"),
        (conn(status="error"), True, "Connection is error; finish connecting it"),
    ],
)
def test_failing_bindings(c: ConnectorConnection | None, bound: bool, reason: str) -> None:
    assert check(c, bound) == (False, reason)


def test_one_item_per_capability_connector() -> None:
    cfg = config(capabilities=[{"connector": c, "tools": []} for c in ("gmail", "vapi")])
    items = build_checklist(FIRM, cfg, {}, {})
    assert [(i.connector, i.ok, i.connection_id) for i in items] == [
        ("gmail", False, None),
        ("vapi", False, None),
    ]
