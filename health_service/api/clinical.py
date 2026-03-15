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
from health_service.db.models import BiometricLog, DeletionRequest, User
from health_service.db.session import get_db
from health_service.publisher.redis_publisher import publish_reward
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
    Initiates the Right to Erasure workflow:
    1. Soft-deletes the user record (marks deleted_at)
    2. Hard-deletes all BiometricLog records
    3. Publishes ErasureEvent to Game Service to anonymize game state

    The game avatar and historical guild data are preserved as orphaned,
    anonymized records per the data lifecycle policy.
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

    # Soft-delete user
    current_user.deleted_at = datetime.now(timezone.utc)

    # Hard-delete all raw biometric PHI
    logs_stmt = select(BiometricLog).where(BiometricLog.user_id == current_user.id)
    logs_result = await db.execute(logs_stmt)
    for log in logs_result.scalars().all():
        await db.delete(log)

    # Record the deletion request
    deletion_record = DeletionRequest(
        user_id=current_user.id,
        status="processing",
    )
    db.add(deletion_record)
    await db.flush()

    # Publish ErasureEvent to game service
    erasure_event = ErasureEvent(user_id=current_user.id)
    await publish_reward(erasure_event, db)

    deletion_record.status = "completed"
    deletion_record.completed_at = datetime.now(timezone.utc)

    logger.info(
        "Right to Erasure completed for user_id=%d. PHI deleted, game state anonymization dispatched.",
        current_user.id,
    )

    return {"detail": "Your account and health data have been permanently deleted."}
