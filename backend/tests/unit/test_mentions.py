import pytest

from lucia.orchestrator.mentions import parse

HANDLES = ["records", "rec", "checkin", "liens"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("@checkin call Jane", ["checkin"]),
        ("please @checkin, then @liens.", ["checkin", "liens"]),
        ("@records and @rec", ["records", "rec"]),
        ("write to jane@checkin.com", []),
        ("@Checkin upper case", []),
        ("@unknown agent", []),
        ("@checkin twice @checkin", ["checkin"]),
        ("@checkin-team is not a mention", []),
    ],
)
def test_parse(text: str, expected: list[str]) -> None:
    assert parse(text, HANDLES) == expected
