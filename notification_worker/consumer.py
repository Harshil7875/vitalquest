"""
Queue Consumer with at-least-once durability.

Phase 12 / fix #11 — switched from BLPOP (destructively dequeues into
worker memory; SIGKILL/OOM during retry loses the job permanently) to
BLMOVE-into-processing-list (job stays in Redis under a per-worker key
until success or DLQ). On worker startup, any jobs left in the processing
list from a prior crash are moved back into the head of the main queue
and replayed.
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

# Per-worker processing list. We use a constant suffix today (single worker
# per queue), but a future multi-worker deployment can rotate the consumer
# id into this name to avoid two workers sharing one processing list.
PROCESSING_SUFFIX = ":processing"


def processing_key(queue_key: str) -> str:
    return f"{queue_key}{PROCESSING_SUFFIX}"


async def replay_stranded_jobs(redis: aioredis.Redis, queue_key: str) -> int:
    """
    Drain the processing list back to the head of the main queue.

    Called once at consumer boot. Any jobs left here belong to a previous
    worker that died mid-processing — moving them back to the queue replays
    them on the new consumer.

    Uses non-blocking LMOVE so this returns quickly if the list is empty.
    """
    proc_key = processing_key(queue_key)
    moved = 0
    while True:
        # LMOVE proc_key queue_key RIGHT LEFT
        # → pop from RIGHT of proc list (oldest pending), push to LEFT of
        # main queue (re-deliver next).
        res = await redis.lmove(proc_key, queue_key, src="RIGHT", dest="LEFT")
        if res is None:
            break
        moved += 1
    if moved:
        logger.warning(
            "Replayed %d stranded notification jobs from %s back into %s.",
            moved, proc_key, queue_key,
        )
    return moved


async def consume_stream(redis: aioredis.Redis, queue_key: str) -> None:
    """
    Long-running consumer coroutine for one queue.

    BLMOVE atomically pops from the queue into the per-worker processing
    list, so a SIGKILL/OOM between the move and the dispatch leaves the
    job in the processing list — picked back up by replay_stranded_jobs
    on the next worker boot.

    Auto-reconnects on connection loss.
    """
    logger.info("Consumer starting on queue '%s'.", queue_key)

    # Recover any jobs left in flight by a prior worker process.
    await replay_stranded_jobs(redis, queue_key)

    proc_key = processing_key(queue_key)

    while True:
        try:
            # BLMOVE blocks until a job is available; atomically moves it
            # from the queue's LEFT (head) to processing's RIGHT (tail).
            raw = await redis.blmove(
                queue_key, proc_key, timeout=30, src="LEFT", dest="RIGHT",
            )
            if raw is None:
                continue  # timeout, loop again

            try:
                await _process_job(raw, redis)
            finally:
                # Whether dispatch succeeded or DLQ'd, the job is no longer
                # in flight in this worker. Remove it from the processing
                # list. LREM count=1 strips exactly one matching entry —
                # if duplicates ever exist, we only clear our own.
                await redis.lrem(proc_key, 1, raw)

        except asyncio.CancelledError:
            return
        except aioredis.ConnectionError:
            logger.warning("Redis connection lost on '%s', reconnecting in 3s.", queue_key)
            await asyncio.sleep(3)
        except Exception:
            logger.exception("Unexpected error in consumer loop for '%s'.", queue_key)
            await asyncio.sleep(1)


async def _process_job(raw: str, redis: aioredis.Redis) -> None:
    """Deserializes a job, fetches the device token, and dispatches with retries.

    On permanent failure (max_retries exceeded or deserialization error), the
    job moves to the DLQ. The caller in consume_stream LREM's it from the
    processing list whether we succeed or DLQ — either outcome is "no
    longer in flight."
    """
    try:
        data = json.loads(raw)
        job = NotificationJob(**data)
    except Exception:
        logger.error("Failed to deserialize notification job: %r", raw[:200])
        await _to_dlq(raw, "deserialization_error", redis)
        return

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
