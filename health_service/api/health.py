"""
Health Data Ingestion — POST /api/health/sync

This is the primary entry point for biometric data from mobile clients.
The pipeline is:
  1. Authenticate user (JWT)
  2. Run anti-cheat rules engine
  3. Evaluate against user's health goal
  4. Persist to BiometricLog (always, even quarantined)
  5. If reward-eligible and goal met → publish RewardEvent to Game Service

The response never echoes raw health metric values back to the client.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from health_service.api.auth import get_current_user
from health_service.core.anti_cheat import SyncPayload, run_pipeline
from health_service.core.goal_evaluator import evaluate
from health_service.db.models import AuditLog, BiometricLog, User
from health_service.db.session import get_db
from health_service.publisher.redis_publisher import publish_reward
from shared.schemas import RewardEvent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/health", tags=["health"])


class HealthSyncRequest(BaseModel):
    device_id: str
    manufacturer: str
    data_type: str
    value: float
    unit: str
    recorded_at: datetime
    hardware_signature: str | None = None


class HealthSyncResponse(BaseModel):
    status: str
    mana_awarded: int
    quarantined: bool
    clinical_log_only: bool
    daily_cap_reached: bool
    message: str


@router.post("/sync", response_model=HealthSyncResponse)
async def sync_health_data(
    body: HealthSyncRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    payload = SyncPayload(
        user_id=current_user.id,
        device_id=body.device_id,
        manufacturer=body.manufacturer,
        data_type=body.data_type,
        value=body.value,
        unit=body.unit,
        recorded_at=body.recorded_at,
        hardware_signature=body.hardware_signature,
    )

    # Step 1: Anti-cheat validation
    pipeline_result = await run_pipeline(payload, db)

    # Step 2: Always persist to clinical log
    log_entry = BiometricLog(
        user_id=current_user.id,
        data_type=body.data_type,
        value=body.value,
        unit=body.unit,
        recorded_at=body.recorded_at,
        source_manufacturer=body.manufacturer,
        hardware_verified=bool(body.hardware_signature),
        quarantined=pipeline_result.quarantined,
        clinical_log_only=pipeline_result.clinical_log_only,
    )
    db.add(log_entry)

    # Step 3: Write audit log if there were flags
    if pipeline_result.audit_notes:
        audit = AuditLog(
            user_id=current_user.id,
            event_type="anti_cheat_flag",
            detail_json_encrypted=" | ".join(pipeline_result.audit_notes),
        )
        db.add(audit)

    # Step 4: Evaluate goal and issue reward if eligible
    mana_awarded = 0
    if pipeline_result.reward_eligible:
        goal_result = await evaluate(payload, db)
        if goal_result.met:
            reward = RewardEvent(
                user_id=current_user.id,
                event_type="mana_award",
                amount=goal_result.mana_to_award,
                source=body.data_type if body.data_type in ("steps", "glucose", "medication") else "steps",
            )
            published = await publish_reward(reward, db)
            if published:
                mana_awarded = goal_result.mana_to_award

    status_msg = "synced"
    if pipeline_result.quarantined:
        status_msg = "quarantined"
    elif pipeline_result.clinical_log_only:
        status_msg = "clinical_only"

    return HealthSyncResponse(
        status=status_msg,
        mana_awarded=mana_awarded,
        quarantined=pipeline_result.quarantined,
        clinical_log_only=pipeline_result.clinical_log_only,
        daily_cap_reached=pipeline_result.skip_reward,
        message="Data logged successfully." if not pipeline_result.quarantined
        else "Data quarantined for review. No reward issued.",
    )
