import pytest

from lucia.core.redact import redact


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SSN 123-45-6789", "SSN [SSN]"),
        ("born 01/02/1990", "born [DATE]"),
        ("born 1990-01-02", "born [DATE]"),
        ("call +1 555 010 2222 now", "call [PHONE] now"),
        ("call (555) 010-2222", "call [PHONE]"),
        ("mail jane.doe@example.com", "mail [EMAIL]"),
        ("MRN: 88231", "[MRN]"),
        ("card 4111 1111 1111 1111", "card [CARD]"),
        ("Called the provider, voicemail left", "Called the provider, voicemail left"),
        ("", ""),
    ],
)
def test_redact(text: str, expected: str) -> None:
    assert redact(text) == expected
