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

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from health_service.config import settings
from health_service.core.hardware_attestation import (
    canonical_payload,
    lookup_device_key,
    verify as verify_hardware_signature,
)

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

    Phase 3 / fix #6: this is now a real HMAC check against a per-device key
    stored in the `device_attestations` table — the previous version only
    checked that `hardware_signature` was a non-empty string, which any
    client could trivially satisfy.

    Manual entries (no signature) and unknown devices (no enrolled key) are
    logged clinically but earn no Mana. A signature that fails verification
    is quarantined as a tampering attempt.
    """

    async def validate(
        self,
        payload: SyncPayload,
        result: PipelineResult,
        db: AsyncSession,
    ) -> None:
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
            return

        key = await lookup_device_key(
            db,
            user_id=payload.user_id,
            manufacturer=payload.manufacturer,
            device_id=payload.device_id,
        )
        if key is None:
            # Device not enrolled (or attestation revoked). Log clinically
            # so no PHI is lost, but no Mana is awarded.
            result.reward_eligible = False
            result.clinical_log_only = True
            result.audit_notes.append(
                f"No active device attestation for device_id='{payload.device_id}'. "
                "Treated as manual entry."
            )
            return

        canonical = canonical_payload(
            user_id=payload.user_id,
            data_type=payload.data_type,
            value=payload.value,
            recorded_at=payload.recorded_at,
        )
        if not verify_hardware_signature(key, canonical, payload.hardware_signature):
            # Signature mismatch. Quarantine and audit — likely tampering.
            result.reward_eligible = False
            result.quarantined = True
            result.audit_notes.append(
                "Hardware signature did not verify — payload quarantined as suspected tampering."
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

    Phase 6 / fix #16 — pg_advisory_xact_lock keyed on the user serializes
    concurrent /sync requests, so two parallel pipelines can't both pass
    the cap check. The lock is held until transaction commit, by which
    time the previous request's ManaLedger row has been written and is
    visible to this request's SUM query.

    Phase 6 / fix #17 — the cap window respects the user's IANA timezone
    (column added in Phase 1, defaults to UTC). A US-Pacific user can no
    longer farm rewards twice per civil day around UTC midnight.
    """

    async def validate(
        self,
        payload: SyncPayload,
        result: PipelineResult,
        db: AsyncSession,
    ) -> None:
        from health_service.db.models import ManaLedger, User

        # Per-user serialization. hashtext + advisory_xact_lock takes a
        # 32-bit key; "mana_cap:" prefix gives us a separate lock space
        # from any other advisory lock in the application.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"mana_cap:{payload.user_id}"},
        )

        # Look up the user's timezone (defaults to UTC). We don't fetch the
        # whole User row; just the column.
        tz_row = (
            await db.execute(
                select(User.timezone).where(User.id == payload.user_id)
            )
        ).first()
        user_tz = (tz_row[0] if tz_row else None) or "UTC"

        # SUM(amount) for today, in the user's timezone. The
        # `timezone(user_tz, awarded_at)::date` expression converts the
        # naive-UTC `awarded_at` into the user's local civil date.
        stmt = select(func.sum(ManaLedger.amount)).where(
            ManaLedger.user_id == payload.user_id,
            func.date(func.timezone(user_tz, ManaLedger.awarded_at))
            == func.date(func.timezone(user_tz, func.now())),
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

    await HardwareVerificationRule().validate(payload, result, db)
    VelocityCheckRule().validate(payload, result)
    await DailyCapRule().validate(payload, result, db)

    if result.audit_notes:
        logger.warning(
            "Anti-cheat flags for user %d: %s",
            payload.user_id,
            " | ".join(result.audit_notes),
        )

    return result
