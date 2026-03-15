"""
Queue Consumer

Uses Redis BLPOP to pull NotificationJobs from the two queues (Stream A health,
Stream B game). Dispatches to the push notification provider. Retries with
exponential backoff on failure. Moves permanently failed jobs to a DLQ.
"""

from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis

from notification_worker.config import settings
from notification_worker.dispatcher import dispatch
from shared.schemas import NotificationJob

logger = logging.getLogger(__name__)


async def consume_stream(redis: aioredis.Redis, queue_key: str) -> None:
    """
    Long-running consumer coroutine for one queue.
    BLPOP blocks until a job is available, then dispatches it.
    Auto-reconnects on connection loss.
    """
    logger.info("Consumer starting on queue '%s'.", queue_key)

    while True:
        try:
            result = await redis.blpop(queue_key, timeout=30)
            if result is None:
                continue  # timeout, loop again

            _, raw = result
            await _process_job(raw, redis)

        except asyncio.CancelledError:
            return
        except aioredis.ConnectionError:
            logger.warning("Redis connection lost on '%s', reconnecting in 3s.", queue_key)
            await asyncio.sleep(3)
        except Exception:
            logger.exception("Unexpected error in consumer loop for '%s'.", queue_key)
            await asyncio.sleep(1)


async def _process_job(raw: str, redis: aioredis.Redis) -> None:
    """Deserializes a job, fetches the device token, and dispatches with retries."""
    try:
        data = json.loads(raw)
        job = NotificationJob(**data)
    except Exception:
        logger.error("Failed to deserialize notification job: %r", raw[:200])
        await _to_dlq(raw, "deserialization_error", redis)
        return

    # Device token is embedded in the queue payload (not fetched from DB here)
    # The health_service includes it when enqueueing to avoid cross-service DB reads
    device_token = data.get("device_token", "")
    platform = data.get("platform", "apns")

    if not device_token:
        logger.warning("Job %s has no device_token, dropping.", job.idempotency_key)
        return

    for attempt in range(1, settings.max_retries + 1):
        try:
            success = await dispatch(job, device_token, platform)
            if success:
                logger.info(
                    "Sent %s notification to user_id=%d (attempt %d/%d)",
                    job.stream, job.user_id, attempt, settings.max_retries,
                )
                return
        except Exception:
            logger.exception(
                "Dispatch failed for job %s (attempt %d/%d)",
                job.idempotency_key, attempt, settings.max_retries,
            )

        if attempt < settings.max_retries:
            delay = settings.retry_base_delay_seconds * (2 ** (attempt - 1))
            logger.info("Retrying in %ds...", delay)
            await asyncio.sleep(delay)

    logger.error(
        "Job %s permanently failed after %d attempts. Moving to DLQ.",
        job.idempotency_key, settings.max_retries,
    )
    await _to_dlq(raw, "max_retries_exceeded", redis)


async def _to_dlq(raw: str, reason: str, redis: aioredis.Redis) -> None:
    entry = json.dumps({"raw": raw, "reason": reason})
    await redis.rpush(settings.notification_dlq_key, entry)
