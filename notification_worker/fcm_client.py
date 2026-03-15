"""
FCM Client — Firebase Cloud Messaging (Android)

Uses FCM HTTP v1 API via httpx.
Stream A (health): silent data-only messages with opaque trigger codes.
Stream B (game): rich notification messages.
"""

from __future__ import annotations

import json
import logging

import httpx

from notification_worker.config import settings

logger = logging.getLogger(__name__)

FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"


async def send_silent_push(device_token: str, trigger_code: str) -> bool:
    """
    Stream A: data-only message. No 'notification' key, so Android does not
    display a banner — the VitalQuest app processes it silently in the background.
    """
    message = {
        "message": {
            "token": device_token,
            "data": {"vitalquest_trigger": trigger_code},
            "android": {"priority": "HIGH"},
        }
    }
    return await _send(message)


async def send_rich_push(
    device_token: str,
    title: str,
    body: str,
    badge_count: int = 0,
    sound: str = "default",
) -> bool:
    """Stream B: standard notification with title and body."""
    message = {
        "message": {
            "token": device_token,
            "notification": {"title": title, "body": body},
            "android": {
                "priority": "NORMAL",
                "notification": {"sound": sound},
            },
            "apns": {
                "payload": {"aps": {"badge": badge_count, "sound": sound}},
            },
        }
    }
    return await _send(message)


async def _send(message: dict) -> bool:
    if not settings.fcm_server_key:
        logger.warning("FCM not configured, skipping push.")
        return False

    headers = {
        "Authorization": f"Bearer {settings.fcm_server_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            FCM_SEND_URL,
            headers=headers,
            content=json.dumps(message),
        )

    if response.status_code == 200:
        return True

    logger.error("FCM rejected push: %s %s", response.status_code, response.text)
    return False
