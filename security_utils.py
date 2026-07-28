from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

_PREFIX = "enc:v1:"


def _derive_local_key() -> bytes:
    secret = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if secret:
        try:
            raw = secret.encode("ascii")
            Fernet(raw)
            return raw
        except (ValueError, TypeError):
            digest = hashlib.sha256(secret.encode("utf-8")).digest()
            return base64.urlsafe_b64encode(digest)

    if os.getenv("APP_ENV", "development").lower() == "production":
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is required in production")

    fallback = os.getenv("FLASK_SECRET_KEY", "local-development-only")
    digest = hashlib.sha256(fallback.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return Fernet(_derive_local_key())


def encrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    if clean.startswith(_PREFIX):
        return clean
    token = _fernet().encrypt(clean.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    if not value.startswith(_PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def has_secret(value: str | None) -> bool:
    return bool(value)
