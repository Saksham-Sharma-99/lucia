import hashlib
import hmac
import time

from lucia.connectors.slack import verify_signature
from lucia.core.config import get_settings


def sign(body: bytes, ts: str) -> str:
    key = get_settings().slack_signing_secret.encode()
    return "v0=" + hmac.new(key, b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()


def test_valid_signature() -> None:
    ts = str(int(time.time()))
    assert verify_signature(b"{}", ts, sign(b"{}", ts))


def test_bad_signature_and_stale_timestamp() -> None:
    ts = str(int(time.time()))
    assert not verify_signature(b"{}", ts, sign(b"{ }", ts))
    old = str(int(time.time()) - 301)
    assert not verify_signature(b"{}", old, sign(b"{}", old))
    assert not verify_signature(b"{}", "abc", "v0=x")
