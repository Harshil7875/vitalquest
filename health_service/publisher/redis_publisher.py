"""
Redis Publisher — Health Service side of the inter-service message bus.

This module is the only place in the health_service that writes to Redis on
the reward-event path. It now uses a transactional outbox: events are written
to the `reward_outbox` Postgres table inside the request transaction, then a
background task drains unpublished rows to Redis after commit. This prevents
the publish-before-commit divergence the audit flagged as #19 — game_service
will never receive a reward whose ManaLedger row was rolled back.

The drain target is currently `redis.publish('health.rewards', ...)`. Phase 11
swaps that for XADD on a Redis Stream so subscriber crashes don't drop events.
The outbox itself is independent of which transport carries the message, so
the Phase 11 change is local to `_publish_one()`.
"""

from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from health_service.config import settings
from health_service.db.models import ManaLedger, RewardOutbox
from shared.schemas import ErasureEvent, GuildDamageEvent, RewardEvent

logger = logging.getLogger(__name__)

REWARDS_CHANNEL = "health.rewards"

_redis_client: aioredis.Redis | None = None
_drainer_task: asyncio.Task | None = None
DRAIN_INTERVAL_SECONDS = 1.0
DRAIN_BATCH_SIZE = 50


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


# ─── Publish path ─────────────────────────────────────────────────────────────


async def publish_event(
    event: RewardEvent | GuildDamageEvent | ErasureEvent,
    db: AsyncSession,
) -> bool:
    """
    Persist an event to the transactional outbox so it gets published to Redis
    after the request transaction commits.

    Behavior:
    - Idempotent on `idempotency_key` against both ManaLedger AND RewardOutbox.
      A duplicate event short-circuits without writing either side.
    - For RewardEvents that aren't guild aggregates and aren't erasures, also
      writes a ManaLedger row (the audit-grade source of truth for awards).
    - The Redis publish itself is not done here — `drain_outbox()` handles it
      after the surrounding transaction commits.

    Returns True if the event was newly enqueued, False on duplicate.

    Phase 5 / fix #18: previously `db.get(ManaLedger, {"idempotency_key": ...})`
    was used as the dedup check. `AsyncSession.get` resolves by primary key
    only — passing a dict keyed on a non-PK column never matched, so the IF
    branch was effectively dead code and retries hit the unique constraint at
    INSERT, surfacing as an unhandled IntegrityError.

    Phase 5 / fix #19: previously `redis.publish()` ran inside the request
    transaction with `db.flush()` (not commit). If the surrounding transaction
    rolled back, the Redis event was already on the wire. Now we write to the
    outbox in the same transaction; the drain task only publishes rows that
    are committed, so a rollback simply leaves no row to drain.
    """
    # Idempotency: was this key already enqueued or applied?
    existing = await _find_existing_idempotency(db, event.idempotency_key)
    if existing:
        logger.debug("Skipping duplicate event %s", event.idempotency_key)
        return False

    # Audit-grade ledger row for Mana awards (NOT for guild aggregates or erasures).
    if isinstance(event, RewardEvent) and not isinstance(event, (GuildDamageEvent, ErasureEvent)):
        ledger_entry = ManaLedger(
            user_id=event.user_id,
            amount=event.amount,
            source=event.source,
            idempotency_key=event.idempotency_key,
        )
        db.add(ledger_entry)

    # Outbox row — same transaction as the ledger insert. The drainer task
    # picks it up after the surrounding request commits.
    outbox_entry = RewardOutbox(
        idempotency_key=event.idempotency_key,
        event_type=event.event_type,
        payload_json=event.model_dump_json(),
    )
    db.add(outbox_entry)
    await db.flush()  # surface UNIQUE conflicts now, not in the drainer.

    logger.info(
        "Enqueued %s event for user_id=%s (key=%s)",
        event.event_type, event.user_id, event.idempotency_key,
    )
    return True


# Backwards-compat alias for callers that still import `publish_reward`.
# Anti-cheat / health.py / clinical.py use it; the rename is a follow-up.
publish_reward = publish_event


async def _find_existing_idempotency(db: AsyncSession, key: str) -> bool:
    """True if an event with this idempotency_key has already been enqueued."""
    # Check both tables — RewardOutbox covers all event types, ManaLedger is
    # the historical source-of-truth and may have rows older than the outbox
    # (in case the outbox is ever flushed for a maintenance migration).
    outbox_stmt = select(RewardOutbox.id).where(
        RewardOutbox.idempotency_key == key
    ).limit(1)
    if (await db.execute(outbox_stmt)).first() is not None:
        return True
    ledger_stmt = select(ManaLedger.id).where(
        ManaLedger.idempotency_key == key
    ).limit(1)
    return (await db.execute(ledger_stmt)).first() is not None


# ─── Outbox drainer ───────────────────────────────────────────────────────────


async def drain_outbox(db: AsyncSession) -> int:
    """
    One drain pass. Reads up to DRAIN_BATCH_SIZE unpublished rows ordered by
    age, publishes each, and marks them published_at = now().

    Returns the number of rows published in this pass.

    The drainer is per-row "at-least-once": if the publish succeeds but the
    UPDATE fails (e.g., crash mid-pass), the row reappears as unpublished
    next time and gets published again. game_service deduplicates on
    idempotency_key (Phase 7 / reward_apply.lua), so duplicate publishes
    are safe.
    """
    from datetime import datetime

    redis = await get_redis()

    stmt = (
        select(RewardOutbox)
        .where(RewardOutbox.published_at.is_(None))
        .order_by(RewardOutbox.created_at)
        .limit(DRAIN_BATCH_SIZE)
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return 0

    published = 0
    for row in rows:
        try:
            await _publish_one(redis, row)
            row.published_at = datetime.utcnow()
            published += 1
        except Exception:
            # Don't let a single bad row stall the drainer. Log and move on;
            # the row stays unpublished and we'll retry on the next pass.
            logger.exception(
                "Failed to publish outbox row id=%s (idempotency_key=%s); "
                "will retry on next drain.",
                row.id, row.idempotency_key,
            )

    if published:
        await db.commit()
    return published


async def _publish_one(redis: aioredis.Redis, row: RewardOutbox) -> None:
    """Transport-specific publish. Swapped in Phase 11 for `redis.xadd`."""
    await redis.publish(REWARDS_CHANNEL, row.payload_json)


async def _drainer_loop(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Background task: invokes drain_outbox once per DRAIN_INTERVAL_SECONDS."""
    while True:
        try:
            async with session_factory() as session:
                async with session.begin():
                    n = await drain_outbox(session)
                    if n:
                        logger.debug("Drained %d outbox rows.", n)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Outbox drainer iteration failed; will retry.")
        await asyncio.sleep(DRAIN_INTERVAL_SECONDS)


def start_outbox_drainer(session_factory: async_sessionmaker[AsyncSession]) -> asyncio.Task:
    """Spawn the drainer task. Idempotent — safe to call from FastAPI lifespan."""
    global _drainer_task
    if _drainer_task is not None and not _drainer_task.done():
        return _drainer_task
    _drainer_task = asyncio.create_task(_drainer_loop(session_factory))
    return _drainer_task


# ─── Notification queue (unchanged) ───────────────────────────────────────────


async def enqueue_notification(job: "NotificationJob", device_token: str, platform: str) -> None:
    """
    Enqueues a push notification job to the appropriate Redis queue.
    Stream A (health): silent push, PHI-free trigger codes only.
    Stream B (game): rich title/body payloads.
    """
    from shared.schemas import NotificationJob

    redis = await get_redis()
    queue_key = (
        settings.notification_queue_health_key
        if job.stream == "health"
        else settings.notification_queue_game_key
    )
    payload = job.model_dump()
    payload["device_token"] = device_token
    payload["platform"] = platform
    await redis.rpush(queue_key, json.dumps(payload))
