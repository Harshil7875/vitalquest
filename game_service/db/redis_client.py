"""
Redis client for the Game Service.

Key conventions:
  game:state:{user_id}              — hash: mana_balance, avatar_level, guild_id, astral_gems
  game:sanctuary:{user_id}          — hash: {building_id} → current_tier
  game:builds:{user_id}             — hash: {building_id}:complete_at, {building_id}:pending_tier
  game:inventory:{user_id}:chests   — hash: common/rare/epic → count
  game:inventory:{user_id}:items    — hash: item_id → quantity
  game:daily_cap:{user_id}:{date}   — int: mana earned today
  game:guild:{guild_id}             — hash: name, boss_hp_remaining, boss_damage_{date}
  game:guild:{guild_id}:roster      — set of user_ids
  game:guild:{guild_id}:chat        — list (last 100 messages, 24h TTL)
  game:processed_events             — set of reward idempotency_keys
  game:processed_txns               — set of economy transaction idempotency_keys (Lua)
  game:economy_ledger:{user_id}     — list of JSON spend entries
"""

from __future__ import annotations

from datetime import date, timedelta

import redis.asyncio as aioredis

from game_service.config import settings
from game_service.db.lua_runner import register_default_scripts, runner as lua_runner

_pool: aioredis.Redis | None = None

# Register every .lua script in game_service/scripts/ with the module-level
# LuaRunner singleton at import time. Idempotent — safe to call repeatedly.
# Tests that want isolated runners construct their own LuaRunner instance.
register_default_scripts()


async def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = await aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20,
        )
    return _pool


# ─── Game State ───────────────────────────────────────────────────────────────

async def get_game_state(user_id: int) -> dict:
    redis = await get_redis()
    data = await redis.hgetall(f"game:state:{user_id}")
    if not data:
        return {
            "mana_balance": "0",
            "avatar_level": "1",
            "guild_id": "",
            "astral_gems": "0",
            "magic": "1",
            "defense": "1",
            "agility": "1",
        }
    return data


async def get_sanctuary_state(user_id: int) -> dict[str, int]:
    """Returns {building_id: current_tier} for all built structures."""
    redis = await get_redis()
    raw = await redis.hgetall(f"game:sanctuary:{user_id}")
    return {k: int(v) for k, v in raw.items()}


async def get_build_timers(user_id: int) -> dict:
    """Returns the active build timer hash for a user."""
    redis = await get_redis()
    return await redis.hgetall(f"game:builds:{user_id}") or {}


async def increment_mana(user_id: int, amount: int) -> int:
    redis = await get_redis()
    return await redis.hincrby(f"game:state:{user_id}", "mana_balance", amount)


# ─── Lua Atomic Transactions ──────────────────────────────────────────────────

async def debit_mana_lua(
    user_id: int, cost: int, idempotency_key: str
) -> int | str:
    """
    Atomically debits Mana. Returns new balance (int) on success or an error
    token (str) like "INSUFFICIENT_MANA" or "DUPLICATE_REQUEST".

    Phase 4 / fix #20 — previously this function read `redis.eval` and
    returned the raw result, but Lua's `return {err = "..."}` raises
    redis.exceptions.ResponseError instead of returning a string. The
    `isinstance(result, str)` checks at every call site never matched, so
    `INSUFFICIENT_MANA` bubbled to FastAPI as a 500. Now routed through
    LuaRunner which catches ResponseError and translates the error token.
    """
    redis = await get_redis()
    ok, value = await lua_runner.run(
        redis,
        "mana_debit",
        keys=[f"game:state:{user_id}"],
        args=[cost, idempotency_key],
    )
    return value  # int on success, str on Lua error — caller does isinstance check.


async def set_build_timer_lua(
    user_id: int,
    building_id: str,
    mana_cost: int,
    complete_at_unix: int,
    next_tier: int,
    idempotency_key: str,
    redis: aioredis.Redis | None = None,
) -> int | str:
    """
    Atomically validates tech-tree prereqs, debits Mana, and sets the build
    timer. Returns new balance (int) or an error token (str).

    Phase 9d / fix #22 — prereq validation is now INSIDE the Lua, reading
    techtree:{building_id}:tier:{N} hashes seeded by sync_to_redis at boot.
    Previously can_upgrade() ran in Python before the Lua call, leaving a
    TOCTOU window where a concurrent skip_build_timer could change
    sanctuary tiers between the check and the debit.
    """
    if redis is None:
        redis = await get_redis()
    ok, value = await lua_runner.run(
        redis,
        "build_timer_set",
        keys=[
            f"game:state:{user_id}",
            f"game:builds:{user_id}",
            f"game:sanctuary:{user_id}",
            f"techtree:{building_id}:tier:{next_tier}",
        ],
        args=[mana_cost, building_id, complete_at_unix, next_tier, idempotency_key],
    )
    return value


# ─── Economy Ledger (spend side) ──────────────────────────────────────────────

async def append_economy_ledger(user_id: int, entry_json: str) -> None:
    """Append-only spend log. Used by analysts to balance economy faucets/sinks."""
    redis = await get_redis()
    await redis.rpush(f"game:economy_ledger:{user_id}", entry_json)


# ─── Daily Mana Cap ───────────────────────────────────────────────────────────

async def get_daily_cap_counter(user_id: int) -> int:
    redis = await get_redis()
    val = await redis.get(f"game:daily_cap:{user_id}:{date.today().isoformat()}")
    return int(val) if val else 0


async def increment_daily_cap(user_id: int, amount: int) -> int:
    redis = await get_redis()
    key = f"game:daily_cap:{user_id}:{date.today().isoformat()}"
    pipe = redis.pipeline()
    pipe.incrby(key, amount)
    pipe.expire(key, int(timedelta(hours=25).total_seconds()))
    results = await pipe.execute()
    return results[0]


# ─── Guild State ──────────────────────────────────────────────────────────────

async def add_guild_damage(guild_id: int, amount: int) -> int:
    redis = await get_redis()
    today = date.today().isoformat()
    return await redis.hincrby(f"game:guild:{guild_id}", f"boss_damage_{today}", amount)


async def get_guild_state(guild_id: int) -> dict:
    redis = await get_redis()
    return await redis.hgetall(f"game:guild:{guild_id}") or {}


async def get_guild_roster(guild_id: int) -> set[str]:
    redis = await get_redis()
    return await redis.smembers(f"game:guild:{guild_id}:roster")


async def add_guild_member(guild_id: int, user_id: int) -> None:
    redis = await get_redis()
    await redis.sadd(f"game:guild:{guild_id}:roster", str(user_id))
    await redis.hset(f"game:state:{user_id}", "guild_id", str(guild_id))


async def remove_guild_member(guild_id: int, user_id: int) -> None:
    redis = await get_redis()
    await redis.srem(f"game:guild:{guild_id}:roster", str(user_id))
    await redis.hset(f"game:state:{user_id}", "guild_id", "")


async def get_guild_member_count(guild_id: int) -> int:
    redis = await get_redis()
    return await redis.scard(f"game:guild:{guild_id}:roster")


# ─── Guild Chat ───────────────────────────────────────────────────────────────

CHAT_MAX_MESSAGES = 100
CHAT_TTL_SECONDS = 60 * 60 * 24  # 24 hours


async def push_chat_message(guild_id: int, message_json: str) -> None:
    """Prepend message and trim to last 100. Resets 24h TTL on every write."""
    redis = await get_redis()
    key = f"game:guild:{guild_id}:chat"
    pipe = redis.pipeline()
    pipe.lpush(key, message_json)
    pipe.ltrim(key, 0, CHAT_MAX_MESSAGES - 1)
    pipe.expire(key, CHAT_TTL_SECONDS)
    await pipe.execute()


async def get_chat_messages(guild_id: int, limit: int = 50) -> list[str]:
    redis = await get_redis()
    return await redis.lrange(f"game:guild:{guild_id}:chat", 0, limit - 1)


# ─── Idempotency (reward events) ──────────────────────────────────────────────

PROCESSED_EVENTS_KEY = "game:processed_events"


async def is_event_processed(idempotency_key: str) -> bool:
    redis = await get_redis()
    return bool(await redis.sismember(PROCESSED_EVENTS_KEY, idempotency_key))


async def mark_event_processed(idempotency_key: str) -> None:
    redis = await get_redis()
    await redis.sadd(PROCESSED_EVENTS_KEY, idempotency_key)
