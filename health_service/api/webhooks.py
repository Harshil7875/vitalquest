"""
Webhook & OAuth Endpoints for Cloud-to-Cloud Integrations

POST /api/health/webhooks/{provider}  — receives real-time pushes from Dexcom, Oura, Fitbit
GET  /api/health/oauth/{provider}/callback — completes the OAuth 2.0 authorization flow

These endpoints feed into the same pipeline as /api/health/sync, using the
adapter registry to normalize the raw payloads before anti-cheat + goal evaluation.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from health_service.adapters.dexcom import exchange_code_for_tokens
from health_service.adapters.registry import route
from health_service.api.auth import get_current_user
from health_service.core.anti_cheat import SyncPayload, run_pipeline
from health_service.core.goal_evaluator import evaluate
from health_service.db.models import (
    AuditLog,
    BiometricLog,
    DeadLetterPayload,
    OAuthToken,
    User,
)
from health_service.db.session import get_db
from health_service.publisher.redis_publisher import publish_reward
from shared.schemas import RewardEvent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/health", tags=["webhooks"])

_SUPPORTED_PROVIDERS = {"dexcom", "oura", "fitbit"}


@router.post("/webhooks/{provider}", status_code=status.HTTP_200_OK)
async def receive_webhook(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_signature: str = Header(default="", alias="X-Webhook-Signature"),
):
    """
    Receives webhook payloads from cloud device providers.
    The user_id is resolved by looking up the provider's user identifier
    in the OAuthToken table (provider_user_id stored at OAuth time).
    """
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'.")

    raw_bytes = await request.body()
    raw_body = await request.json()

    # Resolve VitalQuest user_id from provider's patient/user identifier
    provider_user_id = _extract_provider_user_id(provider, raw_body)
    user_id = await _resolve_user_id(provider, provider_user_id, db)
    if user_id is None:
        # Unknown provider user — log to DLQ and return 200 to prevent retries
        await _to_dead_letter(provider, raw_bytes, "No matching OAuthToken found", db)
        return {"status": "unmatched"}

    await _process_adapter_payload(provider, user_id, raw_body, raw_bytes, x_signature, db)
    return {"status": "accepted"}


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Completes OAuth 2.0 flow. The mobile client initiates the OAuth dance;
    on success, Dexcom redirects to this callback with an authorization code.
    We exchange it for access + refresh tokens and store them encrypted.
    """
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'.")

    # Only Dexcom is fully implemented; others follow the same pattern
    if provider == "dexcom":
        token_data = await exchange_code_for_tokens(
            code=code,
            redirect_uri=f"/api/health/oauth/dexcom/callback",
        )
    else:
        raise HTTPException(status_code=501, detail=f"OAuth for '{provider}' not yet implemented.")

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])

    # Upsert the token record
    stmt = select(OAuthToken).where(
        OAuthToken.user_id == current_user.id,
        OAuthToken.provider == provider,
    )
    existing: OAuthToken | None = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        existing.access_token_encrypted = token_data["access_token"]  # TODO: encrypt
        existing.refresh_token_encrypted = token_data["refresh_token"]  # TODO: encrypt
        existing.expires_at = expires_at.replace(tzinfo=None)
        existing.scope = token_data.get("scope", "")
    else:
        db.add(OAuthToken(
            user_id=current_user.id,
            provider=provider,
            access_token_encrypted=token_data["access_token"],
            refresh_token_encrypted=token_data["refresh_token"],
            expires_at=expires_at.replace(tzinfo=None),
            scope=token_data.get("scope", ""),
        ))

    logger.info("Stored OAuth token for user_id=%d, provider=%s", current_user.id, provider)
    return {"status": "connected", "provider": provider}


# ─── Internal helpers ─────────────────────────────────────────────────────────

async def _process_adapter_payload(
    source: str,
    user_id: int,
    raw_body: dict,
    raw_bytes: bytes,
    signature: str,
    db: AsyncSession,
) -> None:
    """Runs adapter → anti-cheat → goal evaluation → reward publish."""
    try:
        standard_payloads = route(source, user_id, raw_body, raw_bytes, signature)
    except (ValueError, PermissionError) as exc:
        await _to_dead_letter(source, raw_bytes, str(exc), db)
        return

    for sp in standard_payloads:
        sync_payload = SyncPayload(
            user_id=sp.user_id,
            device_id=sp.device_id,
            manufacturer=sp.manufacturer,
            data_type=sp.metric_type.value,
            value=sp.value,
            unit=sp.unit,
            recorded_at=sp.recorded_at,
            hardware_signature=sp.hardware_signature,
        )

        pipeline_result = await run_pipeline(sync_payload, db)

        log_entry = BiometricLog(
            user_id=user_id,
            data_type=sp.metric_type.value,
            value=sp.value,
            unit=sp.unit,
            recorded_at=sp.recorded_at,
            source_manufacturer=sp.manufacturer,
            hardware_verified=bool(sp.hardware_signature),
            quarantined=pipeline_result.quarantined,
            clinical_log_only=pipeline_result.clinical_log_only,
        )
        db.add(log_entry)

        if pipeline_result.audit_notes:
            db.add(AuditLog(
                user_id=user_id,
                event_type="anti_cheat_flag",
                detail_json_encrypted=" | ".join(pipeline_result.audit_notes),
            ))

        if pipeline_result.reward_eligible:
            goal_result = await evaluate(sync_payload, db)
            if goal_result.met:
                source_literal = sp.metric_type.value if sp.metric_type.value in (
                    "steps", "glucose", "medication", "diet"
                ) else "steps"
                reward = RewardEvent(
                    user_id=user_id,
                    event_type="mana_award",
                    amount=goal_result.mana_to_award,
                    source=source_literal,
                )
                await publish_reward(reward, db)


async def _resolve_user_id(provider: str, provider_user_id: str, db: AsyncSession) -> int | None:
    """Map provider's user identifier back to our internal user_id via OAuthToken."""
    # In production, store provider_user_id on OAuthToken at time of OAuth exchange
    # For MVP, we do a simple lookup by provider
    stmt = select(OAuthToken.user_id).where(OAuthToken.provider == provider)
    result = await db.execute(stmt)
    row = result.first()
    return row[0] if row else None


def _extract_provider_user_id(provider: str, body: dict) -> str:
    if provider == "dexcom":
        return body.get("patientId", "")
    if provider == "oura":
        return body.get("user_id", "")
    if provider == "fitbit":
        return body.get("ownerId", "")
    return ""


async def _to_dead_letter(source: str, raw_bytes: bytes, error: str, db: AsyncSession) -> None:
    """Send a failed payload to the Dead Letter Queue for engineering review."""
    db.add(DeadLetterPayload(
        source=source,
        raw_body_encrypted=raw_bytes.decode("utf-8", errors="replace"),  # TODO: encrypt
        error_message=error,
    ))
    logger.error("Payload from '%s' sent to DLQ: %s", source, error)
