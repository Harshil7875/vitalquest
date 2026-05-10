"""
PHI encryption helpers.

Wraps Fernet (AES-128-CBC + HMAC-SHA256, authenticated) using `settings.encryption_key`.
Used by:
  - The `EncryptedString` SQLAlchemy `TypeDecorator` below, which transparently
    encrypts and decrypts string columns at the ORM boundary.
  - `email_lookup_hash` for indexed login: lookup-by-plaintext doesn't work
    against ciphertext (every Fernet token is non-deterministic), so we keep
    a deterministic HMAC alongside the encrypted email column.

Fail-closed: bad/empty key at import time raises; bad ciphertext on read raises.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as _hmac

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import String, Text, TypeDecorator

from health_service.config import settings


def _load_fernet() -> Fernet:
    key = settings.encryption_key
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. Refusing to start the service without "
            "PHI encryption configured."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "ENCRYPTION_KEY is not a valid Fernet key (must be 32 url-safe "
            "base64-encoded bytes). Generate with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from exc


_fernet: Fernet = _load_fernet()


def _lookup_hmac_key() -> bytes:
    """Derive a separate HMAC key from the encryption key — never reuse the same
    key material for two purposes."""
    base = settings.encryption_key.encode() if isinstance(settings.encryption_key, str) else settings.encryption_key
    return hashlib.sha256(b"vitalquest-lookup-hmac|" + base).digest()


_HMAC_KEY: bytes = _lookup_hmac_key()


def encrypt_str(plaintext: str) -> str:
    """Encrypt a string. Empty inputs encrypt normally — only `None` is rejected."""
    if plaintext is None:
        raise ValueError("encrypt_str received None; the caller must guard.")
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_str(ciphertext: str) -> str:
    """Decrypt a Fernet token. Raises on tamper or wrong key."""
    if ciphertext is None:
        raise ValueError("decrypt_str received None; the caller must guard.")
    try:
        return _fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "Failed to decrypt ciphertext — token is invalid, tampered, "
            "or was encrypted with a different key."
        ) from exc


def lookup_hash(value: str) -> str:
    """
    Deterministic HMAC-SHA256 of the given value, hex-encoded.

    Used as a secondary lookup column alongside encrypted PII so unique
    constraints and equality lookups still work. Two identical inputs produce
    identical hashes (by design — that's the whole point), so do NOT use this
    for anything that needs ciphertext-style indistinguishability.
    """
    if value is None:
        raise ValueError("lookup_hash received None.")
    digest = _hmac.new(_HMAC_KEY, value.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


# ─── SQLAlchemy TypeDecorator ──────────────────────────────────────────────────


class EncryptedString(TypeDecorator):
    """
    Transparently encrypts/decrypts a string column with Fernet.

    Storage is `Text` (unbounded) because Fernet tokens are ~76 chars + ~4/3 of
    plaintext, which can exceed any sensible `String(N)` limit and there's no
    benefit to bounding ciphertext length at the column level.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_str(value)
