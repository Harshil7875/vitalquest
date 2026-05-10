"""
Raid Manager

Processes boss damage events and handles loot distribution when a World Boss
is defeated. Called by the subscriber when a GuildDamageEvent arrives.

World Boss schedule: spawns every Wednesday (see master_config.json).
Victory condition: boss_hp_remaining <= 0.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from game_service.core.game_config import get_world_boss_hp
from game_service.core.loot import roll_chest
from game_service.db.lua_runner import runner as lua_runner
from game_service.db.redis_client import add_guild_damage, get_guild_roster

logger = logging.getLogger(__name__)


async def apply_guild_damage(guild_id: int, damage: int, redis: aioredis.Redis) -> bool:
    """
    Deducts damage from the boss HP atomically via boss_damage.lua.

    Phase 8 / fix #12 — the previous Python did HGET → compute → HSET,
    which lost damage under concurrent events. The Lua does HSETNX-init
    plus HINCRBY in one atomic block.

    Phase 8 / fix #24 — initial HP is read via game_config.get_world_boss_hp(),
    not a literal that used to live in this file and in
    guild_manager.create_guild.

    Returns True only when THIS specific damage event drove HP from >0 to
    <=0 — subsequent damage events after the kill don't re-fire loot
    distribution.
    """
    initial_hp = get_world_boss_hp()
    guild_key = f"game:guild:{guild_id}"

    ok, value = await lua_runner.run(
        redis,
        "boss_damage",
        keys=[guild_key],
        args=[damage, initial_hp],
    )
    if not ok:
        logger.error("boss_damage.lua returned error '%s' for guild_id=%d", value, guild_id)
        return False

    new_hp, defeated_flag = value

    # Daily damage progress bar — separate hash field, separate update path.
    # Not in the Lua because progress is a per-day cumulative and the Lua
    # would need the date as another KEY; keeping it as a follow-up call is
    # safe under concurrency for additive counters (HINCRBY is atomic).
    await add_guild_damage(guild_id, damage)

    boss_defeated = bool(defeated_flag)
    if boss_defeated:
        logger.info("World Boss defeated by guild %d (final HP=%d).", guild_id, new_hp)

    return boss_defeated


async def distribute_victory_loot(guild_id: int, redis: aioredis.Redis) -> None:
    """
    When a boss is defeated, iterate all active roster members and deposit
    victory loot into each member's inventory with unique idempotency keys.

    Uses epic chest loot table (as defined in master_config.json).
    """
    config = get_config()
    chest_rarity = config["world_boss"]["victory_loot_chest_rarity"]
    roster = await get_guild_roster(guild_id)
    distributed_count = 0

    for user_id_str in roster:
        # Check member is not in resting/kick_eligible state
        member_status = await redis.hget(
            f"game:guild:{guild_id}:member_status", user_id_str
        )
        if member_status in ("resting", "kick_eligible"):
            logger.debug(
                "Skipping loot distribution for inactive user_id=%s (status=%s)",
                user_id_str, member_status,
            )
            continue

        idempotency_key = f"loot:{guild_id}:{user_id_str}:{_current_raid_week()}"

        # Idempotency: skip if already distributed this week
        if await redis.sismember("game:loot_distributed", idempotency_key):
            continue

        items = roll_chest(chest_rarity)
        item_inventory_key = f"game:inventory:{user_id_str}:items"

        for item in items:
            await redis.hincrby(item_inventory_key, item.item_id, item.quantity)

        await redis.sadd("game:loot_distributed", idempotency_key)
        distributed_count += 1

        logger.debug(
            "Distributed %s loot to user_id=%s: %s",
            chest_rarity,
            user_id_str,
            [(i.item_id, i.quantity) for i in items],
        )

    logger.info(
        "Victory loot distributed to %d/%d members of guild %d.",
        distributed_count, len(roster), guild_id,
    )


def _current_raid_week() -> str:
    """Returns a string key representing the current Wednesday raid week."""
    from datetime import date, timedelta
    today = date.today()
    # Find the most recent Wednesday
    days_since_wednesday = (today.weekday() - 2) % 7
    raid_start = today - timedelta(days=days_since_wednesday)
    return raid_start.isoformat()
