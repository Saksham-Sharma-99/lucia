import uuid

import pytest

from lucia.harness.keys import TargetRef, slug, task_key

CONTACT = uuid.UUID("1a2b3c4d-0000-0000-0000-000000000000")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Call Client", "call-client"),
        ("  get__records!! ", "get-records"),
        ("Ünïcode Café", "unicode-cafe"),
    ],
)
def test_slug(text: str, expected: str) -> None:
    assert slug(text) == expected


@pytest.mark.parametrize(
    ("kind", "target", "key"),
    [
        (
            "call_client",
            TargetRef(type="contact", ref=str(CONTACT)),
            "call-client:contact-1a2b3c4d",
        ),
        ("weekly report", TargetRef(type="period", ref="2026-W40"), "weekly-report:2026-w40"),
        ("summarize", TargetRef(type="run", ref=None), "summarize:run"),
        ("fetch", TargetRef(type="external", ref="clio:INV 123"), "fetch:ext-clio-inv-123"),
        ("review", TargetRef(type="document", ref="Bills March"), "review:doc-bills-march"),
    ],
)
def test_task_key_is_built_from_kind_and_target(kind: str, target: TargetRef, key: str) -> None:
    assert task_key(kind, target) == key


def test_kind_is_truncated() -> None:
    assert task_key("x" * 80, TargetRef(type="run", ref=None)) == "x" * 40 + ":run"


def test_empty_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="kind"):
        task_key("!!!", TargetRef(type="run", ref=None))
