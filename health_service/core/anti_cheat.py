"""
Anti-Cheat Rules Engine

Each rule is a discrete validator. They are composed into a pipeline by
run_pipeline(). Rules are evaluated in order; a failing rule does not
stop subsequent rules from logging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from health_service.config import settings

logger = logging.getLogger(__name__)

ALLOWED_MANUFACTURERS = {
    "APPLE_HEALTHKIT",
    "GOOGLE_FIT",
    "DEXCOM",
    "WITHINGS",
    "GARMIN",
    "FITBIT",
}


@dataclass
class SyncPayload:
    """Incoming health sync data from the mobile client."""

    user_id: int
    device_id: str
    manufacturer: str
    data_type: str  # "steps" | "glucose" | "heart_rate" | "medication_dose"
    value: float
    unit: str
    recorded_at: datetime
    hardware_signature: Optional[str] = None


@dataclass
class PipelineResult:
    reward_eligible: bool = True
    clinical_log_only: bool = False
    quarantined: bool = False
    skip_reward: bool = False  # daily cap reached
    audit_notes: list[str] = field(default_factory=list)
    mana_to_award: int = 0


# ─── Individual Rules ──────────────────────────────────────────────────────────

class HardwareVerificationRule:
    """
    Rule 1: Payload must originate from a trusted hardware source.
    Manual entries are logged clinically but earn no game rewards.
    """

    def validate(self, payload: SyncPayload, result: PipelineResult) -> None:
        if not payload.hardware_signature:
            result.reward_eligible = False
            result.clinical_log_only = True
            result.audit_notes.append(
                "Hardware signature absent — classified as manual entry, reward withheld."
            )
            return

        if payload.manufacturer.upper() not in ALLOWED_MANUFACTURERS:
            result.reward_eligible = False
            result.clinical_log_only = True
            result.audit_notes.append(
                f"Manufacturer '{payload.manufacturer}' not in allowlist."
            )


class VelocityCheckRule:
    """
    Rule 2: Values must fall within physiological plausibility limits.
    Out-of-range payloads are quarantined for physician review.
    """

    def validate(self, payload: SyncPayload, result: PipelineResult) -> None:
        flagged = False

        if payload.data_type == "steps":
            if payload.value > settings.max_steps_per_sync or payload.value < 0:
                flagged = True
                result.audit_notes.append(
                    f"Steps value {payload.value} exceeds plausibility limit "
                    f"({settings.max_steps_per_sync})."
                )

        elif payload.data_type == "glucose":
            if not (settings.min_glucose_mg_dl <= payload.value <= settings.max_glucose_mg_dl):
                flagged = True
                result.audit_notes.append(
                    f"Glucose {payload.value} mg/dL outside range "
                    f"[{settings.min_glucose_mg_dl}, {settings.max_glucose_mg_dl}]."
                )

        elif payload.data_type == "heart_rate":
            if not (settings.min_heart_rate_bpm <= payload.value <= settings.max_heart_rate_bpm):
                flagged = True
                result.audit_notes.append(
                    f"Heart rate {payload.value} bpm outside range "
                    f"[{settings.min_heart_rate_bpm}, {settings.max_heart_rate_bpm}]."
                )

        if flagged:
            result.quarantined = True
            result.reward_eligible = False


class DailyCapRule:
    """
    Rule 3: Enforce the daily Mana cap to prevent unhealthy over-exertion.
    Requires a database session to check today's awarded total.
    """

    async def validate(
        self,
        payload: SyncPayload,
        result: PipelineResult,
        db: AsyncSession,
    ) -> None:
        from health_service.db.models import ManaLedger

        today = date.today()
        stmt = select(func.sum(ManaLedger.amount)).where(
            ManaLedger.user_id == payload.user_id,
            func.date(ManaLedger.awarded_at) == today,
        )
        row = await db.execute(stmt)
        awarded_today: int = row.scalar_one_or_none() or 0

        if awarded_today >= settings.daily_mana_cap:
            result.skip_reward = True
            result.reward_eligible = False
            result.audit_notes.append(
                f"Daily Mana cap ({settings.daily_mana_cap}) reached. "
                "Clinical logging continues."
            )


# ─── Pipeline ─────────────────────────────────────────────────────────────────

async def run_pipeline(
    payload: SyncPayload,
    db: AsyncSession,
) -> PipelineResult:
    """
    Runs all three anti-cheat rules in order.
    Returns a PipelineResult that health.py uses to decide whether to
    publish a reward event.
    """
    result = PipelineResult()

    HardwareVerificationRule().validate(payload, result)
    VelocityCheckRule().validate(payload, result)
    await DailyCapRule().validate(payload, result, db)

    if result.audit_notes:
        logger.warning(
            "Anti-cheat flags for user %d: %s",
            payload.user_id,
            " | ".join(result.audit_notes),
        )

    return result
