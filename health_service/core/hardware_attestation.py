"""
Hardware attestation HMAC.

Phase 3 / fix #6: replaces the truthy-string check in HardwareVerificationRule
with a real cryptographic verifier. Each enrolled device has its own HMAC key
stored (encrypted) in the `device_attestations` table. The mobile app signs
each biometric payload with that key; this module validates the signature.

The pure-crypto helpers in this module are DB-free so they can be unit-tested
without infrastructure. The `lookup_device_key` function does the DB read.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from health_service.db.models import DeviceAttestation

logger = logging.getLogger(__name__)


def canonical_payload(
    user_id: int,
    data_type: str,
    value: float,
    recorded_at: datetime,
) -> bytes:
    """
    Deterministic byte string covering every field a tampering attacker could
    modify. Both sides (mobile app + this service) MUST produce the same bytes
    for the same logical payload, so format is locked here.

    Format: `{user_id}|{data_type}|{value}|{recorded_at_iso}`
    Float `value` is rendered with repr() to avoid Python locale-specific
    formatting drift; the mobile client mirrors this convention.
    """
    iso = recorded_at.isoformat()
    return f"{user_id}|{data_type}|{value!r}|{iso}".encode("utf-8")


def compute_signature(key: bytes, payload: bytes) -> str:
    """HMAC-SHA256 → hex string. Public for use by attestation enrollment tools."""
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify(key: bytes, payload: bytes, provided_signature: str) -> bool:
    """Constant-time compare of HMAC-SHA256 over `payload` against `provided_signature`."""
    if not provided_signature:
        return False
    expected = compute_signature(key, payload)
    return hmac.compare_digest(expected, provided_signature)


async def lookup_device_key(
    db: AsyncSession,
    user_id: int,
    manufacturer: str,
    device_id: str,
) -> Optional[bytes]:
    """
    Read the per-device HMAC key from the `device_attestations` table.

    Returns None if no attestation row exists for the (user_id, manufacturer,
    device_id) tuple, or if the row is revoked. The HMAC key column uses the
    EncryptedString TypeDecorator, so the bytes returned here are plaintext
    even though the row is encrypted at rest.

    Returning None is the "no enrolled key" path — the caller in
    HardwareVerificationRule treats it as `clinical_log_only` (data is logged
    but no Mana is awarded), which preserves clinical fidelity for users who
    haven't completed device enrollment yet.
    """
    stmt = select(DeviceAttestation).where(
        DeviceAttestation.user_id == user_id,
        DeviceAttestation.manufacturer == manufacturer.upper(),
        DeviceAttestation.device_id == device_id,
        DeviceAttestation.revoked_at.is_(None),
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    # The hmac_key_encrypted column is stored as base64 plaintext (the
    # EncryptedString decrypts to a string). Decode to bytes for HMAC use.
    try:
        import base64
        return base64.b64decode(row.hmac_key_encrypted)
    except Exception as exc:
        logger.error("Failed to decode HMAC key for user_id=%d: %s", user_id, exc)
        return None
