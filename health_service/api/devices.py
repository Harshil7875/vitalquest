"""
Device Attestation Enrollment

POST   /api/health/devices/enroll   — register a new device, receive HMAC key
GET    /api/health/devices          — list this user's active devices
DELETE /api/health/devices/{manufacturer}/{device_id} — soft-revoke a device

Threat model:
  The hardware-attestation premise (Phase 3 / fix #6) requires every /sync
  payload to carry a per-device HMAC signature, computed against a key the
  server can verify. This module establishes how the device acquires that
  key in the first place.

  Trust-on-first-use: the JWT-authenticated enrollment endpoint generates
  a fresh 32-byte key server-side, persists it encrypted (EncryptedString
  via Phase 1), and returns the plaintext exactly once in the HTTPS
  response body. The mobile app is responsible for storing the key in
  hardware-backed storage (iOS Keychain / Android Keystore via
  expo-secure-store). Subsequent /sync requests sign with this key.

  Re-enrollment of an existing (user_id, manufacturer, device_id) tuple is
  rejected (409). To rotate a compromised key, revoke the old attestation
  first, then enroll fresh. This prevents accidental key rotation that
  would silently brick existing /sync calls.

  Limitations: this MVP does NOT include app-attestation (Apple AppAttest /
  Android Play Integrity), so a determined attacker who controls a logged-in
  user's JWT could enroll a fake device. Production deployments should
  layer app-attestation on top of this flow before HIPAA / DPDP launch.
"""

from __future__ import annotations

import base64
import logging
import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from health_service.api.auth import get_current_user
from health_service.core.anti_cheat import ALLOWED_MANUFACTURERS
from health_service.core.crypto import encrypt_str
from health_service.db.models import DeviceAttestation, User
from health_service.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/health/devices", tags=["devices"])

HMAC_KEY_BYTES = 32  # 256-bit symmetric key


# ─── Request / Response Schemas ───────────────────────────────────────────────


class EnrollRequest(BaseModel):
    manufacturer: str  # one of ALLOWED_MANUFACTURERS — case-insensitive on input
    device_id: str     # opaque, app-generated unique identifier (e.g. iOS identifierForVendor)


class EnrollResponse(BaseModel):
    """The hmac_key_b64 field is returned EXACTLY ONCE.

    The mobile app must persist it to hardware-backed secure storage on
    first receipt. There is no recovery endpoint — losing the key requires
    revoking and re-enrolling.
    """
    device_id: str
    manufacturer: str
    hmac_key_b64: str
    enrolled_at: datetime


class DeviceListItem(BaseModel):
    """List view never includes the HMAC key."""
    manufacturer: str
    device_id: str
    enrolled_at: datetime
    revoked_at: datetime | None


class DeviceListResponse(BaseModel):
    devices: list[DeviceListItem]


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/enroll", response_model=EnrollResponse, status_code=status.HTTP_201_CREATED)
async def enroll_device(
    body: EnrollRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new device. Returns a freshly-generated HMAC key in the
    response body — the only time it ever leaves the server."""
    manufacturer = body.manufacturer.upper()
    if manufacturer not in ALLOWED_MANUFACTURERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Manufacturer '{body.manufacturer}' is not in the allowlist. "
                f"Allowed: {sorted(ALLOWED_MANUFACTURERS)}."
            ),
        )

    # Reject duplicate enrollment of an active attestation. Caller must
    # revoke first if rotating the key.
    existing_stmt = select(DeviceAttestation).where(
        DeviceAttestation.user_id == current_user.id,
        DeviceAttestation.manufacturer == manufacturer,
        DeviceAttestation.device_id == body.device_id,
        DeviceAttestation.revoked_at.is_(None),
    )
    if (await db.execute(existing_stmt)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Device is already enrolled. Revoke the existing attestation "
                "before enrolling a fresh key."
            ),
        )

    # Generate the per-device key. secrets.token_bytes uses the OS CSPRNG.
    key_bytes = secrets.token_bytes(HMAC_KEY_BYTES)
    key_b64 = base64.b64encode(key_bytes).decode("ascii")

    attestation = DeviceAttestation(
        user_id=current_user.id,
        manufacturer=manufacturer,
        device_id=body.device_id,
        # EncryptedString TypeDecorator encrypts on bind — key never lands
        # in Postgres or any log in plaintext.
        hmac_key_encrypted=key_b64,
    )
    db.add(attestation)
    await db.flush()

    logger.info(
        "Enrolled device for user_id=%d, manufacturer=%s, device_id=%s",
        current_user.id, manufacturer, body.device_id,
    )

    return EnrollResponse(
        device_id=body.device_id,
        manufacturer=manufacturer,
        hmac_key_b64=key_b64,
        enrolled_at=attestation.enrolled_at,
    )


@router.get("", response_model=DeviceListResponse)
async def list_devices(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List devices enrolled to this user. Never returns the HMAC key.

    Useful for the mobile app to show "Connected devices" UI and detect
    stale enrollments the user might want to revoke.
    """
    stmt = (
        select(DeviceAttestation)
        .where(DeviceAttestation.user_id == current_user.id)
        .order_by(DeviceAttestation.enrolled_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return DeviceListResponse(
        devices=[
            DeviceListItem(
                manufacturer=row.manufacturer,
                device_id=row.device_id,
                enrolled_at=row.enrolled_at,
                revoked_at=row.revoked_at,
            )
            for row in rows
        ],
    )


@router.delete(
    "/{manufacturer}/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_device(
    manufacturer: str,
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-revoke a device. Sets `revoked_at = now()`; the row stays for
    audit. After revocation, /sync calls signed with this key fail the
    HardwareVerificationRule (lookup_device_key returns None for revoked
    rows), and the user can re-enroll fresh.
    """
    manufacturer_upper = manufacturer.upper()
    stmt = select(DeviceAttestation).where(
        DeviceAttestation.user_id == current_user.id,
        DeviceAttestation.manufacturer == manufacturer_upper,
        DeviceAttestation.device_id == device_id,
        DeviceAttestation.revoked_at.is_(None),
    )
    attestation = (await db.execute(stmt)).scalar_one_or_none()
    if attestation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active attestation matches that device.",
        )

    attestation.revoked_at = datetime.utcnow()
    logger.info(
        "Revoked device for user_id=%d, manufacturer=%s, device_id=%s",
        current_user.id, manufacturer_upper, device_id,
    )
    return None
