import pytest
from cryptography.fernet import InvalidToken

from lucia.core.security import (
    canonical_hash,
    decrypt_json,
    encrypt_json,
    hash_password,
    secret_hint,
    sign_state,
    unsign_state,
    verify_password,
)


def test_argon2_round_trip() -> None:
    h = hash_password("s3cret")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "s3cret") and not verify_password(h, "wrong")
    assert not verify_password("not-a-hash", "s3cret")


def test_fernet_round_trip_and_tamper() -> None:
    token = encrypt_json({"bot_token": "fake-token-1"})
    assert "fake-token" not in token
    assert decrypt_json(token) == {"bot_token": "fake-token-1"}
    with pytest.raises(InvalidToken):
        decrypt_json(token[:-4] + "AAAA")


def test_signed_state_detects_tampering_and_purpose() -> None:
    state = sign_state({"connection_id": "c1", "nonce": "n1"}, "consent:slack")
    assert unsign_state(state, "consent:slack") == {"connection_id": "c1", "nonce": "n1"}
    assert unsign_state(state, "consent:gmail") is None
    assert unsign_state(state[:-2] + "xx", "consent:slack") is None


def test_hint_and_canonical_hash() -> None:
    assert secret_hint("abcdef1234") == "••••1234"
    assert canonical_hash({"b": 1, "a": [1]}) == canonical_hash({"a": [1], "b": 1})
