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

from health_service.adapters.dexcom import (
    build_auth_url as dexcom_build_auth_url,
    exchange_code_for_tokens,
    fetch_user_info as dexcom_fetch_user_info,
)
from health_service.adapters.registry import route
from health_service.api.auth import get_current_user
from health_service.config import settings
from health_service.core.anti_cheat import SyncPayload, run_pipeline
from health_service.core.goal_evaluator import evaluate
from health_service.core.oauth_state import mint_state, verify_state
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


@router.get("/oauth/{provider}/start")
async def oauth_start(
    provider: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Mints a CSRF-protection nonce and returns the provider's authorization URL.

    The mobile client calls this endpoint, then redirects the user to the
    returned `authorize_url`. The callback handler verifies the `state` was
    minted for this same user. Without this two-step flow, an attacker can
    trick a logged-in victim into binding the attacker's provider account
    (audit finding #3).
    """
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'.")
    if provider != "dexcom":
        raise HTTPException(status_code=501, detail=f"OAuth for '{provider}' not yet implemented.")
    if not settings.dexcom_client_id:
        raise HTTPException(
            status_code=503,
            detail="Dexcom OAuth is not configured on this deployment.",
        )

    nonce = await mint_state(current_user.id)
    redirect_uri = _absolute_callback_url(request, provider)
    authorize_url = dexcom_build_auth_url(redirect_uri=redirect_uri, state=nonce)
    return {
        "authorize_url": authorize_url,
        "state": nonce,
        "redirect_uri": redirect_uri,
    }


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Completes OAuth 2.0 flow. The mobile client initiates the OAuth dance via
    /start; on success, the provider redirects here with an authorization code
    and the state nonce. We verify the state, exchange the code for tokens,
    fetch the provider's stable user identifier (so webhooks can resolve back
    to this user — finding #1), and persist everything encrypted.
    """
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'.")

    # CSRF defense: state must have been minted by /start for THIS user (#3).
    if not await verify_state(state, current_user.id):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state. Please retry the connection.",
        )

    if provider != "dexcom":
        raise HTTPException(
            status_code=501, detail=f"OAuth for '{provider}' not yet implemented."
        )

    redirect_uri = _absolute_callback_url(request, provider)
    token_data = await exchange_code_for_tokens(code=code, redirect_uri=redirect_uri)

    # Real /userinfo lookup so OAuthToken.provider_user_id is populated with
    # the provider's stable identifier — finding #1 depends on this. Without
    # it, _resolve_user_id below cannot route webhooks correctly.
    user_info = await dexcom_fetch_user_info(token_data["access_token"])
    provider_user_id = str(user_info.get("userId") or user_info.get("id") or "")
    if not provider_user_id:
        raise HTTPException(
            status_code=502,
            detail="Provider did not return a stable user identifier.",
        )

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])

    stmt = select(OAuthToken).where(
        OAuthToken.user_id == current_user.id,
        OAuthToken.provider == provider,
    )
    existing: OAuthToken | None = (await db.execute(stmt)).scalar_one_or_none()

    # access_token / refresh_token are stored via EncryptedString TypeDecorator,
    # so assigning plaintext below produces ciphertext at rest automatically.
    if existing:
        existing.access_token_encrypted = token_data["access_token"]
        existing.refresh_token_encrypted = token_data["refresh_token"]
        existing.expires_at = expires_at.replace(tzinfo=None)
        existing.scope = token_data.get("scope", "")
        existing.provider_user_id = provider_user_id
    else:
        db.add(OAuthToken(
            user_id=current_user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            access_token_encrypted=token_data["access_token"],
            refresh_token_encrypted=token_data["refresh_token"],
            expires_at=expires_at.replace(tzinfo=None),
            scope=token_data.get("scope", ""),
        ))

    logger.info("Stored OAuth token for user_id=%d, provider=%s", current_user.id, provider)
    return {"status": "connected", "provider": provider}


def _absolute_callback_url(request: Request, provider: str) -> str:
    """Build the absolute callback URL the provider will redirect to.

    Dexcom rejects relative redirect_uri values (the prior bug at this site),
    so we construct it from the request's scheme+host. In production this is
    the public hostname behind the Nginx gateway; in dev it's localhost.
    """
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    return f"{scheme}://{host}/api/health/oauth/{provider}/callback"


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
    """Map provider's stable user identifier back to our internal user_id.

    Audit finding #1: the previous implementation returned the FIRST OAuthToken
    row for the provider, so every webhook for that provider was attributed to
    one (essentially random) victim. This now matches by `(provider, provider_user_id)`,
    backed by the indexed UNIQUE constraint added in Phase 1.
    """
    if not provider_user_id:
        return None
    stmt = select(OAuthToken.user_id).where(
        OAuthToken.provider == provider,
        OAuthToken.provider_user_id == provider_user_id,
    )
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
    """Send a failed payload to the Dead Letter Queue for engineering review.
    raw_body is stored via EncryptedString TypeDecorator — ciphertext at rest."""
    db.add(DeadLetterPayload(
        source=source,
        raw_body_encrypted=raw_bytes.decode("utf-8", errors="replace"),
        error_message=error,
    ))
    logger.error("Payload from '%s' sent to DLQ: %s", source, error)
