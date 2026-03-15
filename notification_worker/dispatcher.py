"""
Notification Dispatcher

Routes NotificationJob objects to the correct send path:
  - Stream A (health): silent push with opaque trigger code
  - Stream B (game): rich-media push with title/body

The dispatcher is called by the consumer — it never touches Postgres or
any PHI. It only reads the device_token from the job (passed in by the
health_service when enqueueing, never stored in game_service).
"""

from __future__ import annotations

import logging

from notification_worker import apns_client, fcm_client
from shared.schemas import NotificationJob

logger = logging.getLogger(__name__)


async def dispatch(job: NotificationJob, device_token: str, platform: str) -> bool:
    """
    Sends the notification to the appropriate push service.

    Args:
        job: The notification job containing stream, trigger code, and game metadata.
        device_token: The APNs/FCM device token (fetched by the consumer from the queue payload).
        platform: "apns" (iOS) or "fcm" (Android).

    Returns True on success, False on failure (caller handles retry).
    """
    if job.stream == "health":
        return await _dispatch_health_stream(job, device_token, platform)
    elif job.stream == "game":
        return await _dispatch_game_stream(job, device_token, platform)
    else:
        logger.error("Unknown stream '%s' in job %s", job.stream, job.idempotency_key)
        return False


async def _dispatch_health_stream(
    job: NotificationJob, device_token: str, platform: str
) -> bool:
    """
    Stream A: PHI-free silent push.
    Only the opaque trigger_code is sent. The device app decodes it locally.
    """
    logger.debug(
        "Dispatching health trigger '%s' to user_id=%d via %s",
        job.trigger_code, job.user_id, platform,
    )
    if platform == "apns":
        return await apns_client.send_silent_push(device_token, job.trigger_code)
    else:
        return await fcm_client.send_silent_push(device_token, job.trigger_code)


async def _dispatch_game_stream(
    job: NotificationJob, device_token: str, platform: str
) -> bool:
    """Stream B: Rich-media game engagement notification."""
    logger.debug(
        "Dispatching game notification '%s' to user_id=%d via %s",
        job.title, job.user_id, platform,
    )
    if platform == "apns":
        return await apns_client.send_rich_push(
            device_token, job.title, job.body, job.badge_count, job.sound or "default"
        )
    else:
        return await fcm_client.send_rich_push(
            device_token, job.title, job.body, job.badge_count, job.sound or "default"
        )
