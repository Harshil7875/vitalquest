"""
Clinical Portal — GET /api/clinical/export
DELETE /api/health/account  — Right to Erasure

The export endpoint returns decrypted PHI. It is restricted to Pro users,
sits behind TLS (enforced at Nginx), and requires a valid JWT.

This is the ONLY endpoint that intentionally returns raw health data to
the authenticated user (or their physician).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from health_service.api.auth import get_current_user
from health_service.core.crypto import lookup_hash
from health_service.db.models import (
    AuditLog,
    BiometricLog,
    DeletionRequest,
    DeviceAttestation,
    DeviceToken,
    ManaLedger,
    OAuthToken,
    User,
)
from health_service.db.session import get_db
from health_service.publisher.redis_publisher import publish_event
from shared.schemas import ErasureEvent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/clinical", tags=["clinical"])


class BiometricEntry(BaseModel):
    data_type: str
    value: float
    unit: str
    recorded_at: datetime
    source_manufacturer: str
    hardware_verified: bool
    quarantined: bool


class ExportResponse(BaseModel):
    user_id: int
    export_generated_at: datetime
    entries: list[BiometricEntry]
    total_records: int


@router.get("/export", response_model=ExportResponse)
async def export_clinical_data(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in ("pro", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clinical export requires a VitalQuest Pro subscription.",
        )

    stmt = (
        select(BiometricLog)
        .where(BiometricLog.user_id == current_user.id)
        .order_by(BiometricLog.recorded_at.desc())
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()

    entries = [
        BiometricEntry(
            data_type=log.data_type,
            value=log.value,
            unit=log.unit,
            recorded_at=log.recorded_at,
            source_manufacturer=log.source_manufacturer,
            hardware_verified=log.hardware_verified,
            quarantined=log.quarantined,
        )
        for log in logs
    ]

    return ExportResponse(
        user_id=current_user.id,
        export_generated_at=datetime.now(timezone.utc),
        entries=entries,
        total_records=len(entries),
    )


# ─── Right to Erasure ─────────────────────────────────────────────────────────

router_account = APIRouter(prefix="/api/health", tags=["account"])


@router_account.delete("/account", status_code=status.HTTP_202_ACCEPTED)
async def request_account_deletion(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Right to Erasure (audit finding #5).

    Cascades a hard delete across every table that stores PHI or PII linked
    to this user. The previous version only deleted BiometricLog rows —
    OAuth refresh tokens, ManaLedger, AuditLog, DeviceToken, and
    DeviceAttestation rows all survived, so the "deleted" user could still
    be re-identified and Dexcom/Oura/Fitbit could keep pushing PHI to a
    user record that no longer existed in our user-facing UI.

    Steps:
      1. Soft-delete the User row (preserves the FK so downstream deletes
         remain referentially valid in the same transaction).
      2. Hard-delete BiometricLog, OAuthToken, ManaLedger, AuditLog,
         DeviceToken, DeviceAttestation rows for this user.
      3. Anonymize the User row's identifying fields (email, lookup_hash,
         password) so the row itself can stay as an FK target without
         carrying any PII.
      4. Anonymize the DeletionRequest row's user_id to a hash for
         compliance receipt purposes.
      5. Enqueue an ErasureEvent for the game service via the outbox.
    """
    # Check for existing pending request
    existing_stmt = select(DeletionRequest).where(
        DeletionRequest.user_id == current_user.id,
        DeletionRequest.status.in_(["pending", "processing"]),
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A deletion request is already in progress.",
        )

    user_id = current_user.id
    deletion_record = DeletionRequest(user_id=user_id, status="processing")
    db.add(deletion_record)
    await db.flush()

    # Cascade delete across every PHI/PII-bearing table.
    cascade_models = [
        BiometricLog,
        OAuthToken,
        ManaLedger,
        AuditLog,
        DeviceToken,
        DeviceAttestation,
    ]
    for model in cascade_models:
        rows = (
            await db.execute(select(model).where(model.user_id == user_id))
        ).scalars().all()
        for row in rows:
            await db.delete(row)

    # Anonymize the User row in place. Keep the row so any FK that refers
    # to this user_id stays valid (e.g. Guild.created_by_user_id), but
    # strip every identifier.
    anonymized_marker = f"deleted_user_{lookup_hash(str(user_id))[:16]}"
    current_user.email_encrypted = anonymized_marker
    current_user.email_lookup_hash = lookup_hash(anonymized_marker)
    current_user.hashed_password = ""  # Login becomes impossible
    current_user.deleted_at = datetime.now(timezone.utc)

    # Anonymize the DeletionRequest user_id to a hash for the compliance
    # receipt — we keep the row to prove the deletion happened, but the
    # original user_id is gone.
    deletion_record.user_id = None  # column is nullable post-Phase-1
    deletion_record.status = "completed"
    deletion_record.completed_at = datetime.now(timezone.utc)

    # Enqueue ErasureEvent through the outbox so the game service
    # anonymizes its Redis state. publish_event (Phase 5) handles
    # ErasureEvent specially — no ManaLedger row is created for the
    # user being erased.
    await publish_event(ErasureEvent(user_id=user_id), db)

    logger.info(
        "Right to Erasure completed for user_id=%d: PHI cascade across %d tables, "
        "user record anonymized, game state event dispatched.",
        user_id, len(cascade_models),
    )

    return {"detail": "Your account and health data have been permanently deleted."}
