import hashlib
import json
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet
from itsdangerous import BadSignature, URLSafeSerializer

from lucia.core.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _fernet() -> Fernet:
    return Fernet(get_settings().secret_key.encode())


def encrypt_json(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    data: dict[str, Any] = json.loads(_fernet().decrypt(token.encode()))
    return data


def secret_hint(value: str) -> str:
    return "••••" + value[-4:] if len(value) > 4 else "••••"


def sign_state(payload: dict[str, str], purpose: str) -> str:
    return URLSafeSerializer(get_settings().secret_key, salt=purpose).dumps(payload)


def unsign_state(token: str, purpose: str) -> dict[str, str] | None:
    try:
        data: dict[str, str] = URLSafeSerializer(get_settings().secret_key, salt=purpose).loads(
            token
        )
    except BadSignature:
        return None
    return data


def canonical_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
