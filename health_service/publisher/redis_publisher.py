"""
Redis Publisher — Health Service side of the inter-service message bus.

This module is the ONLY place in the health_service that writes to Redis.
It publishes RewardEvents to the 'health.rewards' Pub/Sub channel.

Idempotency is enforced here via the ManaLedger table to prevent double-publish
on retries.
"""

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from health_service.config import settings
from health_service.db.models import ManaLedger
from shared.schemas import GuildDamageEvent, RewardEvent

logger = logging.getLogger(__name__)

REWARDS_CHANNEL = "health.rewards"

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


async def publish_reward(event: RewardEvent, db: AsyncSession) -> bool:
    """
    Publishes a RewardEvent to the message broker.

    Returns True if published, False if skipped due to idempotency.
    The ManaLedger entry is written to Postgres before publishing to Redis
    so that a Redis failure doesn't result in an un-recorded award.
    """
    # Idempotency check: if this key already exists, skip
    existing = await db.get(ManaLedger, {"idempotency_key": event.idempotency_key})
    if existing:
        logger.debug("Skipping duplicate event %s", event.idempotency_key)
        return False

    # Write to Postgres ledger first (source of truth)
    if not isinstance(event, GuildDamageEvent):
        ledger_entry = ManaLedger(
            user_id=event.user_id,
            amount=event.amount,
            source=event.source,
            idempotency_key=event.idempotency_key,
        )
        db.add(ledger_entry)
        await db.flush()  # write to DB within the current transaction

    # Publish to Redis Pub/Sub
    redis = await get_redis()
    payload = event.model_dump_json()
    await redis.publish(REWARDS_CHANNEL, payload)

    logger.info(
        "Published %s event for user_id=%s (key=%s)",
        event.event_type,
        event.user_id,
        event.idempotency_key,
    )
    return True
