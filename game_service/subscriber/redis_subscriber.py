"""
Redis Subscriber — Game Service side of the reward bus.

Phase 11 / fix #10 — migrated from Redis Pub/Sub (at-most-once delivery
where every event published during a subscriber crash is silently dropped)
to Redis Streams with a consumer group. Process_reward_event still owns
its own atomic SADD-and-branch idempotency, so duplicate redeliveries are
safe.

Lifecycle on each iteration of the loop:
  1. XAUTOCLAIM stale pending entries from prior consumers (e.g. a worker
     that died holding an entry). Anything reclaimed is processed.
  2. XREADGROUP > on the canonical consumer name. Block up to 5s.
  3. For each delivered entry, parse → process → XACK.
  4. On parse/process failure, log and DO NOT XACK. The entry stays in the
     Pending Entries List (PEL); the next XAUTOCLAIM picks it up. After
     enough redelivery attempts an operator can move it to a DLQ stream.
"""

from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from game_service.core.reward_processor import process_reward_event
from game_service.db.redis_client import get_redis
from shared.schemas import GuildDamageEvent, RewardEvent

logger = logging.getLogger(__name__)

REWARDS_STREAM = "health.rewards"
CONSUMER_GROUP = "game-consumers"
CONSUMER_NAME = "game-consumer-1"
BLOCK_MS = 5000  # XREADGROUP block timeout
BATCH_COUNT = 10
RECLAIM_MIN_IDLE_MS = 30_000  # only steal pending entries idle ≥30s
RECLAIM_BATCH = 50


async def _ensure_consumer_group(redis: aioredis.Redis) -> None:
    """Create the consumer group if it doesn't exist. Idempotent —
    BUSYGROUP error means the group already exists, which is fine.
    The MKSTREAM flag ensures the stream itself exists too, so the
    subscriber can start before the publisher emits its first event."""
    try:
        await redis.xgroup_create(
            REWARDS_STREAM, CONSUMER_GROUP, id="$", mkstream=True
        )
        logger.info("Created consumer group '%s' on '%s'.", CONSUMER_GROUP, REWARDS_STREAM)
    except ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            return
        raise


async def _reclaim_stale_pending(redis: aioredis.Redis) -> list[tuple[str, dict]]:
    """XAUTOCLAIM any entries that have been in the PEL for longer than
    RECLAIM_MIN_IDLE_MS — a previous consumer most likely crashed mid-process."""
    try:
        # XAUTOCLAIM returns (next_cursor, claimed_entries, deleted_entries)
        result = await redis.xautoclaim(
            name=REWARDS_STREAM,
            groupname=CONSUMER_GROUP,
            consumername=CONSUMER_NAME,
            min_idle_time=RECLAIM_MIN_IDLE_MS,
            start_id="0-0",
            count=RECLAIM_BATCH,
        )
        # redis-py 5.x returns a 3-tuple; older may return 2-tuple.
        claimed = result[1] if len(result) >= 2 else []
        return claimed or []
    except (ResponseError, AttributeError) as exc:
        logger.debug("XAUTOCLAIM unavailable or no claims: %s", exc)
        return []


async def _process_entry(entry_id: str, fields: dict, redis: aioredis.Redis) -> bool:
    """Parse a Stream entry and dispatch. Returns True on success → ACK."""
    try:
        # XADD writes were `{"payload": json_string}`.
        raw = fields.get("payload") or fields.get(b"payload")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if raw is None:
            logger.error("Stream entry %s missing 'payload' field; skipping.", entry_id)
            return True  # ACK to avoid an infinite retry on a malformed entry.

        data = json.loads(raw)
        event_type = data.get("event_type")
        event = (
            GuildDamageEvent(**data) if event_type == "guild_damage"
            else RewardEvent(**data)
        )
        await process_reward_event(event, redis)
        return True
    except json.JSONDecodeError:
        logger.error("Stream entry %s has invalid JSON; ACKing to drain.", entry_id)
        return True  # ACK to drain malformed payloads — they'll never parse on retry.
    except Exception:
        logger.exception(
            "Stream entry %s failed processing; leaving unacked for redelivery.",
            entry_id,
        )
        return False


async def start_subscriber() -> None:
    """
    Long-running coroutine started as an asyncio.Task in main.py's lifespan.
    Reconnects on Redis failures with exponential-ish backoff.
    """
    logger.info(
        "Game Service subscriber starting on stream '%s' (group=%s, consumer=%s).",
        REWARDS_STREAM, CONSUMER_GROUP, CONSUMER_NAME,
    )

    while True:
        try:
            redis = await get_redis()
            await _ensure_consumer_group(redis)

            # Reclaim any pending entries idle longer than the threshold
            # — happens once per outer-loop iteration so a subscriber that
            # restarts after a crash quickly recovers stranded entries.
            for entry_id, fields in await _reclaim_stale_pending(redis):
                if await _process_entry(entry_id, fields, redis):
                    await redis.xack(REWARDS_STREAM, CONSUMER_GROUP, entry_id)

            # XREADGROUP: read entries newer than this consumer's last ACK
            # ("> id"). Block up to BLOCK_MS waiting for new entries.
            response = await redis.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={REWARDS_STREAM: ">"},
                count=BATCH_COUNT,
                block=BLOCK_MS,
            )
            if not response:
                continue

            # response is [(stream_name, [(entry_id, fields), ...])]
            for _, entries in response:
                for entry_id, fields in entries:
                    if await _process_entry(entry_id, fields, redis):
                        await redis.xack(REWARDS_STREAM, CONSUMER_GROUP, entry_id)

        except asyncio.CancelledError:
            logger.info("Subscriber task cancelled, shutting down.")
            return
        except Exception:
            logger.exception(
                "Subscriber connection lost, reconnecting in 5 seconds..."
            )
            await asyncio.sleep(5)
