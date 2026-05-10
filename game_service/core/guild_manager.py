"""
Guild Manager

Handles guild lifecycle: creation, joining, member status, and the
Grace Protocol for inactive members.

Structural rule: guild social state lives in game_service Redis.
The health_service Postgres holds only the guild_id → user_id membership
for PHI aggregation purposes (guild_engine.py).
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import redis.asyncio as aioredis

from game_service.core.game_config import get_config, get_world_boss_hp
from game_service.db.redis_client import (
    add_guild_member,
    debit_mana_lua,
    get_game_state,
    get_guild_member_count,
    get_guild_roster,
    get_guild_state,
    get_redis,
    remove_guild_member,
)

logger = logging.getLogger(__name__)

GUILD_MAX_CAPACITY = 50
# Grace Protocol thresholds
RESTING_THRESHOLD_DAYS = 7
KICK_ELIGIBLE_DAYS = 14


@dataclass
class GuildActionResult:
    success: bool
    message: str
    guild_id: int | None = None
    invite_code: str | None = None


async def create_guild(
    user_id: int,
    guild_name: str,
    idempotency_key: str,
    redis: aioredis.Redis,
) -> GuildActionResult:
    """
    Creates a new guild. Deducts Mana atomically.
    Assigns the creating user as Guildmaster.
    """
    config = get_config()
    creation_cost = config["economy"]["guild_creation_cost_mana"]

    result = await debit_mana_lua(user_id, creation_cost, idempotency_key)
    if isinstance(result, str):
        return GuildActionResult(success=False, message=result)

    # Generate a new guild ID (use Redis counter for simplicity)
    guild_id = await redis.incr("game:guild_id_counter")
    invite_code = secrets.token_urlsafe(8)

    await redis.hset(f"game:guild:{guild_id}", mapping={
        "name": guild_name,
        "invite_code": invite_code,
        "guildmaster_user_id": str(user_id),
        # Phase 8 / fix #24 — read boss HP from master_config, not a literal.
        "boss_hp_remaining": str(get_world_boss_hp()),
        "created_at": str(int(time.time())),
    })

    # Register invite code lookup
    await redis.set(f"game:invite:{invite_code}", str(guild_id))

    # Add creator to roster as Guildmaster
    await add_guild_member(guild_id, user_id)
    await redis.hset(f"game:guild:{guild_id}:roles", str(user_id), "guildmaster")
    await _update_last_seen(user_id, redis)

    logger.info("Guild %d '%s' created by user_id=%d", guild_id, guild_name, user_id)
    return GuildActionResult(success=True, message="Guild created.", guild_id=guild_id, invite_code=invite_code)


async def join_guild(
    user_id: int,
    invite_code: str | None = None,
    guild_id: int | None = None,
) -> GuildActionResult:
    """
    Joins a guild by invite code (private) or guild_id (public).
    Enforces the 50-member capacity cap.
    """
    redis = await get_redis()

    if invite_code:
        stored_guild_id = await redis.get(f"game:invite:{invite_code}")
        if not stored_guild_id:
            return GuildActionResult(success=False, message="Invalid invite code.")
        guild_id = int(stored_guild_id)
    elif guild_id is None:
        return GuildActionResult(success=False, message="Must provide invite_code or guild_id.")

    # Capacity check
    current_count = await get_guild_member_count(guild_id)
    if current_count >= GUILD_MAX_CAPACITY:
        return GuildActionResult(success=False, message=f"Guild is full ({GUILD_MAX_CAPACITY} members).")

    # Check user isn't already in a guild
    state = await get_game_state(user_id)
    if state.get("guild_id"):
        return GuildActionResult(success=False, message="You must leave your current guild first.")

    await add_guild_member(guild_id, user_id)
    await redis.hset(f"game:guild:{guild_id}:roles", str(user_id), "member")
    await _update_last_seen(user_id, redis)

    logger.info("user_id=%d joined guild %d", user_id, guild_id)
    return GuildActionResult(success=True, message="Joined guild.", guild_id=guild_id)


async def kick_member(
    requestor_user_id: int,
    target_user_id: int,
    guild_id: int,
) -> GuildActionResult:
    """Only a Guildmaster can kick. Grace Protocol: only kick_eligible members."""
    redis = await get_redis()
    roles = await redis.hgetall(f"game:guild:{guild_id}:roles")

    if roles.get(str(requestor_user_id)) != "guildmaster":
        return GuildActionResult(success=False, message="Only the Guildmaster can kick members.")

    member_status = await redis.hget(f"game:guild:{guild_id}:member_status", str(target_user_id))
    if member_status not in ("resting", "kick_eligible"):
        return GuildActionResult(
            success=False,
            message="Member is active. Grace Protocol: can only kick inactive members.",
        )

    await remove_guild_member(guild_id, target_user_id)
    await redis.hdel(f"game:guild:{guild_id}:roles", str(target_user_id))
    await redis.hdel(f"game:guild:{guild_id}:member_status", str(target_user_id))

    logger.info(
        "user_id=%d kicked from guild %d by guildmaster %d",
        target_user_id, guild_id, requestor_user_id,
    )
    return GuildActionResult(success=True, message="Member removed.")


async def apply_grace_protocol(guild_id: int) -> None:
    """
    Called by the nightly cron. Checks last_seen timestamps for all roster members
    and transitions inactive members through the grace protocol states.
    """
    redis = await get_redis()
    roster = await get_guild_roster(guild_id)
    now = time.time()

    for user_id_str in roster:
        last_seen_str = await redis.hget(f"game:last_seen", user_id_str)
        if not last_seen_str:
            continue

        inactive_days = (now - float(last_seen_str)) / 86400

        if inactive_days >= KICK_ELIGIBLE_DAYS:
            await redis.hset(
                f"game:guild:{guild_id}:member_status", user_id_str, "kick_eligible"
            )
            logger.info("user_id=%s is kick_eligible in guild %d", user_id_str, guild_id)

        elif inactive_days >= RESTING_THRESHOLD_DAYS:
            await redis.hset(
                f"game:guild:{guild_id}:member_status", user_id_str, "resting"
            )
            logger.info("user_id=%s moved to resting in guild %d", user_id_str, guild_id)

        else:
            # Reactivate if they've logged in recently
            await redis.hset(
                f"game:guild:{guild_id}:member_status", user_id_str, "active"
            )


async def _update_last_seen(user_id: int, redis: aioredis.Redis) -> None:
    await redis.hset("game:last_seen", str(user_id), str(time.time()))
