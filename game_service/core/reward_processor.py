"""
Reward Processor

Applies incoming RewardEvents from the Health Service to the game state.
This is the only mutating logic in the game service.

All state changes are idempotent — duplicate events with the same
idempotency_key are silently dropped.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from game_service.core.erasure_handler import anonymize_user
from game_service.db.redis_client import (
    add_guild_damage,
    get_daily_cap_counter,
    increment_daily_cap,
    increment_mana,
    is_event_processed,
    mark_event_processed,
)
from shared.schemas import GuildDamageEvent, RewardEvent

logger = logging.getLogger(__name__)

# Mirror of health_service daily cap — second line of defense (GDD v1.8)
DAILY_MANA_CAP = 300  # medication=100, steps=50, diet=25 per day max


async def process_reward_event(event: RewardEvent, redis: aioredis.Redis) -> None:
    """
    Dispatches a RewardEvent to the appropriate handler.
    Idempotency check prevents double-processing on subscriber retry.
    """
    if await is_event_processed(event.idempotency_key):
        logger.debug("Skipping already-processed event %s", event.idempotency_key)
        return

    try:
        if event.event_type == "mana_award":
            await _handle_mana_award(event, redis)
        elif event.event_type == "guild_damage":
            await _handle_guild_damage(event, redis)
        elif event.event_type == "erasure":
            await anonymize_user(event.user_id, redis)
        else:
            logger.warning("Unknown event_type '%s', skipping.", event.event_type)
            return

        await mark_event_processed(event.idempotency_key)

    except Exception:
        logger.exception(
            "Failed to process event %s (type=%s, user=%d)",
            event.idempotency_key,
            event.event_type,
            event.user_id,
        )
        # Do not re-raise — subscriber loop must not crash on a single bad event


async def _handle_mana_award(event: RewardEvent, redis: aioredis.Redis) -> None:
    # Second daily cap check at the game layer (defense in depth)
    current_daily = await get_daily_cap_counter(event.user_id)
    if current_daily >= DAILY_MANA_CAP:
        logger.info(
            "Daily Mana cap already reached for user_id=%d, dropping award of %d.",
            event.user_id,
            event.amount,
        )
        return

    # Cap the award to not exceed the daily limit
    amount_to_award = min(event.amount, DAILY_MANA_CAP - current_daily)

    new_balance = await increment_mana(event.user_id, amount_to_award)
    await increment_daily_cap(event.user_id, amount_to_award)

    logger.info(
        "Awarded %d Mana to user_id=%d (new balance: %d, source: %s)",
        amount_to_award,
        event.user_id,
        new_balance,
        event.source,
    )


async def _handle_guild_damage(event: RewardEvent, redis: aioredis.Redis) -> None:
    from game_service.core.raid_manager import apply_guild_damage, distribute_victory_loot

    guild_id = getattr(event, "guild_id", None)
    if guild_id is None:
        logger.error("GuildDamageEvent missing guild_id: %s", event)
        return

    boss_defeated = await apply_guild_damage(guild_id, event.amount, redis)
    logger.info("Guild %d dealt %d boss damage (defeated=%s)", guild_id, event.amount, boss_defeated)

    if boss_defeated:
        await distribute_victory_loot(guild_id, redis)
