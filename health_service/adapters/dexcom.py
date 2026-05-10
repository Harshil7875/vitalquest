"""
Dexcom Adapter (Pathway B: Cloud-to-Cloud)

Dexcom CGMs sync to Dexcom's cloud, which then pushes real-time webhook
events to our endpoint. We also support OAuth 2.0 for the initial
authorization flow.

Two modes:
  1. Webhook push: Dexcom POSTs to /api/health/webhooks/dexcom
  2. Polling: background cron fetches new readings every 15 minutes

Security: HMAC-SHA256 signature on every webhook payload.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime
from typing import Any

from health_service.adapters.base import (
    BaseAdapter,
    MetricType,
    VitalQuestStandardPayload,
    mmol_l_to_mg_dl,
    normalize_timestamp,
)
from health_service.config import settings

logger = logging.getLogger(__name__)

DEXCOM_MANUFACTURER = "DEXCOM"

# Dexcom event types → MetricType
_DEXCOM_EVENT_MAP: dict[str, MetricType] = {
    "EGV": MetricType.GLUCOSE,          # Estimated Glucose Value (CGM reading)
    "CALIBRATION": MetricType.GLUCOSE,  # Manual calibration entry
}


class DexcomAdapter(BaseAdapter):
    """
    Parses Dexcom webhook payloads.

    Webhook shape (simplified Dexcom Share API format):
    {
        "events": [
            {
                "eventType": "EGV",
                "eventSubType": null,
                "displayTime": "2024-01-15T09:00:00",
                "systemTime": "2024-01-15T14:00:00",
                "value": 142,
                "unit": "mg/dL",
                "rateOfChange": -1.2,
                "transmitterId": "8G12AB",
                "transmitterGeneration": "G7"
            }
        ],
        "patientId": "<dexcom_user_id>"  # not the VitalQuest user_id
    }
    """

    MANUFACTURER = DEXCOM_MANUFACTURER

    def verify_signature(self, raw_body: bytes, signature_header: str) -> bool:
        """
        Dexcom signs webhook payloads with HMAC-SHA256 using our webhook secret.
        The signature is in the X-Dexcom-Signature header.

        Fail-closed: if `dexcom_webhook_secret` is empty (audit finding #2),
        the registry route() call will surface a clear error rather than
        silently accept unsigned payloads. Pre-launch deployments that don't
        yet have a Dexcom secret should leave `dexcom_client_id` empty too —
        that branch is rejected upstream before this method is reached.
        """
        if not settings.dexcom_webhook_secret:
            logger.error(
                "Dexcom webhook secret is not configured — refusing to verify "
                "this signature. Set DEXCOM_WEBHOOK_SECRET in the environment."
            )
            return False

        expected = hmac.new(
            settings.dexcom_webhook_secret.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def adapt(self, user_id: int, raw_body: dict[str, Any]) -> list[VitalQuestStandardPayload]:
        events = raw_body.get("events", [])
        transmitter_id = None
        payloads: list[VitalQuestStandardPayload] = []

        for event in events:
            event_type = event.get("eventType", "")
            metric_type = _DEXCOM_EVENT_MAP.get(event_type)
            if metric_type is None:
                logger.debug("Unhandled Dexcom event type '%s', skipping.", event_type)
                continue

            transmitter_id = event.get("transmitterId", "unknown")
            raw_value = float(event.get("value", 0))
            raw_unit = event.get("unit", "mg/dL")

            # Prefer systemTime (UTC) over displayTime (local)
            time_str = event.get("systemTime") or event.get("displayTime")
            recorded_at = normalize_timestamp(datetime.fromisoformat(time_str))

            value, unit = _normalize_dexcom_units(raw_value, raw_unit)

            payloads.append(
                VitalQuestStandardPayload(
                    user_id=user_id,
                    device_id=transmitter_id,
                    manufacturer=self.MANUFACTURER,
                    metric_type=metric_type,
                    value=value,
                    unit=unit,
                    recorded_at=recorded_at,
                    hardware_signature=transmitter_id,  # transmitter ID serves as hardware token
                    raw_source_type=event_type,
                )
            )

        return payloads


def _normalize_dexcom_units(value: float, unit: str) -> tuple[float, str]:
    if unit.lower() in ("mmol/l", "mmol"):
        return mmol_l_to_mg_dl(value), "mg/dL"
    return value, "mg/dL"


# ─── OAuth 2.0 Flow Helpers ───────────────────────────────────────────────────

DEXCOM_TOKEN_URL = "https://api.dexcom.com/v2/oauth2/token"
DEXCOM_AUTH_URL = "https://api.dexcom.com/v2/oauth2/login"


def build_auth_url(redirect_uri: str, state: str) -> str:
    """Returns the URL to redirect the user to for Dexcom OAuth authorization."""
    import urllib.parse
    params = {
        "client_id": settings.dexcom_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "offline_access",
        "state": state,
    }
    return f"{DEXCOM_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.post(
            DEXCOM_TOKEN_URL,
            data={
                "client_id": settings.dexcom_client_id,
                "client_secret": settings.dexcom_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        return response.json()


async def fetch_user_info(access_token: str) -> dict:
    """
    Fetch the authenticated user's Dexcom profile.

    Used by the OAuth callback to populate OAuthToken.provider_user_id
    (audit finding #1). Without this, webhook payloads cannot be reliably
    routed back to the correct VitalQuest user.

    Dexcom's V3 API returns a stable user identifier under the `userId` key.
    """
    import httpx
    url = "https://api.dexcom.com/v3/users/self"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """Use the refresh token to get a new access token before expiry."""
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.post(
            DEXCOM_TOKEN_URL,
            data={
                "client_id": settings.dexcom_client_id,
                "client_secret": settings.dexcom_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        return response.json()
