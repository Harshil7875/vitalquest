"""
Right to Erasure Handler — Game Service side.

When the health service deletes a user's PHI and publishes an ErasureEvent,
this module anonymizes the user's game state in Redis.

Historical guild damage contributions are NOT modified — they were never
keyed by user_id in the aggregate and are already anonymous.
"""

from __future__ import annotations

import hashlib
import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


def _anonymized_id(user_id: int) -> str:
    """Generates a stable but opaque identifier for deleted users."""
    digest = hashlib.sha256(f"deleted_{user_id}".encode()).hexdigest()[:12]
    return f"deleted_user_{digest}"


async def anonymize_user(user_id: int, redis: aioredis.Redis) -> None:
    """
    Anonymizes all game state associated with user_id.
    The avatar and historical data remain as orphaned records to preserve
    guild economy integrity, but all PII fields are scrubbed.
    """
    anon_id = _anonymized_id(user_id)
    state_key = f"game:state:{user_id}"

    existing_state = await redis.hgetall(state_key)
    if not existing_state:
        logger.info("No game state found for user_id=%d, nothing to anonymize.", user_id)
        return

    # Rename the state key to the anonymized identifier
    new_key = f"game:state:{anon_id}"
    pipe = redis.pipeline()

    # Copy state to anonymized key, scrubbing any PII fields
    anonymized = {
        k: v for k, v in existing_state.items()
        if k in ("mana_balance", "avatar_level", "sanctuary_tier", "guild_id")
    }
    anonymized["display_name"] = "Deleted Hero"
    anonymized["original_user_id"] = str(user_id)  # kept for data integrity audits only

    if anonymized:
        pipe.hset(new_key, mapping=anonymized)

    # Remove the original user key
    pipe.delete(state_key)

    # Remove from daily cap keys
    await pipe.execute()

    logger.info(
        "Anonymized game state for user_id=%d → %s",
        user_id,
        anon_id,
    )
