"""
Reward Processor

Applies incoming RewardEvents from the Health Service to the game state.
This is the only mutating logic in the game service.

Phase 7 / fixes #9, #15, #23:
- Idempotency for ALL event types is now an atomic SADD-and-branch on
  `game:processed_events`. The previous `is_event_processed → handler →
  mark_event_processed` pattern was a TOCTOU race: two parallel deliveries
  of the same event both passed the SISMEMBER check and double-applied.
- Mana awards run through `reward_apply.lua` so the cap-check + credit +
  counter-increment are a single atomic operation, fixing the
  GET-then-INCR race the audit flagged.
- The hardcoded `DAILY_MANA_CAP = 300` constant is gone. Cap is read via
  `game_config.get_daily_mana_cap()` so master_config.json stays the
  single source of truth.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import redis.asyncio as aioredis

from game_service.core.erasure_handler import anonymize_user
from game_service.core.game_config import get_daily_mana_cap
from game_service.db.lua_runner import runner as lua_runner
from game_service.db.redis_client import (
    PROCESSED_EVENTS_KEY,
    get_redis,
)
from shared.schemas import GuildDamageEvent, RewardEvent

logger = logging.getLogger(__name__)

DAILY_COUNTER_TTL_SECONDS = int(timedelta(hours=25).total_seconds())


async def process_reward_event(event: RewardEvent, redis: aioredis.Redis) -> None:
    """
    Applies a RewardEvent. Atomic-idempotent: a duplicate event with the
    same idempotency_key is a single Redis SADD that returns 0 and exits.

    All exceptions are caught so the subscriber loop never dies on a single
    bad event. We do NOT undo the SADD on failure — that's intentional
    at-most-once semantics. Each handler below either fully succeeds (atomic
    Lua) or has logically-idempotent state changes (anonymize_user is a
    HDEL/SET sweep that's safe to repeat).
    """
    # Atomic SADD: returns 1 if newly added, 0 if already present. The
    # entire idempotency check + mark is one Redis op, so two concurrent
    # deliveries of the same event will see exactly one is_new=1.
    is_new = await redis.sadd(PROCESSED_EVENTS_KEY, event.idempotency_key)
    if not is_new:
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
    except Exception:
        logger.exception(
            "Failed to process event %s (type=%s, user=%d). State may be partially "
            "applied; the event will NOT retry (idempotency key already marked).",
            event.idempotency_key, event.event_type, event.user_id,
        )


async def _handle_mana_award(event: RewardEvent, redis: aioredis.Redis) -> None:
    """
    Atomic cap-and-credit via reward_apply.lua. The script returns
    {new_balance, awarded} — `awarded == 0` means the daily cap was hit.
    """
    daily_cap = get_daily_mana_cap()
    today = date.today().isoformat()
    state_key = f"game:state:{event.user_id}"
    daily_key = f"game:daily_cap:{event.user_id}:{today}"

    ok, value = await lua_runner.run(
        redis,
        "reward_apply",
        keys=[state_key, daily_key],
        args=[event.amount, daily_cap, DAILY_COUNTER_TTL_SECONDS],
    )
    if not ok:
        logger.error(
            "reward_apply.lua returned error '%s' for user_id=%d",
            value, event.user_id,
        )
        return

    new_balance, awarded = value
    if awarded == 0:
        logger.info(
            "Daily Mana cap (%d) already reached for user_id=%d; dropped award of %d.",
            daily_cap, event.user_id, event.amount,
        )
    else:
        logger.info(
            "Awarded %d Mana to user_id=%d (new balance: %d, source: %s, "
            "clamped from %d).",
            awarded, event.user_id, new_balance, event.source, event.amount,
        )


async def _handle_guild_damage(event: RewardEvent, redis: aioredis.Redis) -> None:
    from game_service.core.raid_manager import apply_guild_damage, distribute_victory_loot

    guild_id = getattr(event, "guild_id", None)
    if guild_id is None:
        logger.error("GuildDamageEvent missing guild_id: %s", event)
        return

    boss_defeated = await apply_guild_damage(guild_id, event.amount, redis)
    logger.info(
        "Guild %d dealt %d boss damage (defeated=%s)",
        guild_id, event.amount, boss_defeated,
    )

    if boss_defeated:
        await distribute_victory_loot(guild_id, redis)
