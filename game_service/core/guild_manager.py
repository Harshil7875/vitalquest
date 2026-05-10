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

import redis.asyncio as aioredis

from game_service.core.game_config import get_config, get_world_boss_hp
from game_service.db.lua_runner import runner as lua_runner
from game_service.db.redis_client import (
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
    Creates a new guild atomically via guild_create.lua.

    Phase 9c / fix #21 — the previous flow debit'd Mana via debit_mana_lua
    (atomic), then ran 5 separate writes (HSET guild hash, SET invite, SADD
    roster, HSET role, HSET state). A crash between the debit and the
    follow-up writes left the user with no guild and no Mana refund —
    the idempotency_key was already consumed so retries returned
    DUPLICATE_REQUEST. The single Lua now folds debit + every write
    into one block, so partial failure is impossible.
    """
    config = get_config()
    creation_cost = config["economy"]["guild_creation_cost_mana"]
    invite_code = secrets.token_urlsafe(8)
    now = str(int(time.time()))

    ok, value = await lua_runner.run(
        redis,
        "guild_create",
        keys=[
            f"game:state:{user_id}",
            "game:guild_id_counter",
        ],
        args=[
            creation_cost,
            guild_name,
            invite_code,
            idempotency_key,
            str(get_world_boss_hp()),
            str(user_id),
            now,
        ],
    )
    if not ok:
        message_map = {
            "DUPLICATE_REQUEST": "Guild creation already processed.",
            "INSUFFICIENT_MANA": f"Insufficient Mana to create a guild ({creation_cost} required).",
        }
        return GuildActionResult(success=False, message=message_map.get(value, value))

    new_balance, new_guild_id = value
    logger.info(
        "Guild %d '%s' created by user_id=%d (Mana balance now %d).",
        new_guild_id, guild_name, user_id, new_balance,
    )
    return GuildActionResult(
        success=True,
        message="Guild created.",
        guild_id=new_guild_id,
        invite_code=invite_code,
    )


async def join_guild(
    user_id: int,
    invite_code: str | None = None,
    guild_id: int | None = None,
) -> GuildActionResult:
    """
    Joins a guild atomically via guild_join.lua.

    Phase 9c / fix #21 — capacity-check + already-in-guild + roster-add are
    now one indivisible block. The previous SCARD → HGET → SADD sequence
    let 50 users joining a guild with 1 slot all pass the SCARD check
    before any of them SADD'd, and a double-clicking user could land in
    two guilds (the second HSET state.guild_id clobbered the first but
    the user remained in both rosters).
    """
    redis = await get_redis()

    if invite_code:
        stored_guild_id = await redis.get(f"game:invite:{invite_code}")
        if not stored_guild_id:
            return GuildActionResult(success=False, message="Invalid invite code.")
        guild_id = int(stored_guild_id)
    elif guild_id is None:
        return GuildActionResult(success=False, message="Must provide invite_code or guild_id.")

    now = str(int(time.time()))
    ok, value = await lua_runner.run(
        redis,
        "guild_join",
        keys=[
            f"game:state:{user_id}",
            f"game:guild:{guild_id}:roster",
            f"game:guild:{guild_id}:roles",
            "game:last_seen",
        ],
        args=[
            str(user_id),
            str(guild_id),
            GUILD_MAX_CAPACITY,
            now,
        ],
    )
    if not ok:
        message_map = {
            "ALREADY_IN_GUILD": "You must leave your current guild first.",
            "GUILD_FULL": f"Guild is full ({GUILD_MAX_CAPACITY} members).",
        }
        return GuildActionResult(success=False, message=message_map.get(value, value))

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
    Called by the nightly cron. Checks last_seen timestamps for all roster
    members and transitions inactive members through the grace protocol states.
    """
    redis = await get_redis()
    roster = await get_guild_roster(guild_id)
    now = time.time()

    for user_id_str in roster:
        last_seen_str = await redis.hget("game:last_seen", user_id_str)
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
            await redis.hset(
                f"game:guild:{guild_id}:member_status", user_id_str, "active"
            )


async def _update_last_seen(user_id: int, redis: aioredis.Redis) -> None:
    """Kept for non-Lua call sites that need to refresh last_seen."""
    await redis.hset("game:last_seen", str(user_id), str(time.time()))
