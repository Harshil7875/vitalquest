"""
APNs Client — Apple Push Notification Service

Uses HTTP/2 with JWT provider authentication (.p8 key file).
Handles both:
  - Silent pushes (Stream A: health reminders as opaque trigger codes)
  - Rich-media pushes (Stream B: game engagement notifications)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx
import jwt  # PyJWT

from notification_worker.config import settings

logger = logging.getLogger(__name__)

APNS_PRODUCTION_HOST = "https://api.push.apple.com"
APNS_SANDBOX_HOST = "https://api.sandbox.push.apple.com"

_apns_token_cache: dict = {"token": None, "generated_at": 0}
_TOKEN_TTL_SECONDS = 3000  # APNs tokens are valid for 60 min; refresh at 50 min


def _get_apns_host() -> str:
    return APNS_SANDBOX_HOST if settings.apns_use_sandbox else APNS_PRODUCTION_HOST


def _generate_apns_token() -> str:
    """JWT signed with the .p8 key for APNs provider authentication."""
    now = int(time.time())
    if _apns_token_cache["token"] and (now - _apns_token_cache["generated_at"]) < _TOKEN_TTL_SECONDS:
        return _apns_token_cache["token"]

    key_path = Path(settings.apns_key_path)
    if not key_path.exists():
        raise FileNotFoundError(f"APNs key not found at {settings.apns_key_path}")

    key = key_path.read_text()
    token = jwt.encode(
        {"iss": settings.apns_team_id, "iat": now},
        key,
        algorithm="ES256",
        headers={"kid": settings.apns_key_id},
    )
    _apns_token_cache["token"] = token
    _apns_token_cache["generated_at"] = now
    return token


async def send_silent_push(device_token: str, trigger_code: str) -> bool:
    """
    Stream A: sends a content-available silent push with only an opaque trigger code.
    No medical text ever reaches the APNs servers.
    """
    payload = {
        "aps": {"content-available": 1},
        "data": {"vitalquest_trigger": trigger_code},
    }
    return await _send(device_token, payload, push_type="background")


async def send_rich_push(
    device_token: str,
    title: str,
    body: str,
    badge_count: int = 0,
    sound: str = "default",
) -> bool:
    """Stream B: standard rich-media push for game engagement notifications."""
    payload = {
        "aps": {
            "alert": {"title": title, "body": body},
            "badge": badge_count,
            "sound": sound,
        }
    }
    return await _send(device_token, payload, push_type="alert")


async def _send(device_token: str, payload: dict, push_type: str) -> bool:
    if not settings.apns_key_path:
        logger.warning("APNs not configured, skipping push.")
        return False

    host = _get_apns_host()
    url = f"{host}/3/device/{device_token}"
    headers = {
        "authorization": f"bearer {_generate_apns_token()}",
        "apns-topic": settings.apns_bundle_id,
        "apns-push-type": push_type,
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(http2=True) as client:
        response = await client.post(url, headers=headers, content=json.dumps(payload))

    if response.status_code == 200:
        return True

    logger.error("APNs rejected push for device %s: %s %s", device_token[:8], response.status_code, response.text)
    return False
