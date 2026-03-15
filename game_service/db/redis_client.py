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
from pathlib import Path

import redis.asyncio as aioredis

from game_service.config import settings

_pool: aioredis.Redis | None = None

# Load Lua scripts at module level (registered on first use)
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_MANA_DEBIT_SCRIPT = (_SCRIPTS_DIR / "mana_debit.lua").read_text()
_BUILD_TIMER_SCRIPT = (_SCRIPTS_DIR / "build_timer_set.lua").read_text()


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
    Atomically debits Mana. Returns new balance (int) or an error string.
    Uses mana_debit.lua — reads, validates, and deducts in a single EVAL.
    """
    redis = await get_redis()
    result = await redis.eval(
        _MANA_DEBIT_SCRIPT,
        1,
        f"game:state:{user_id}",
        cost,
        idempotency_key,
    )
    return result


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
    Atomically debits Mana and sets build timer. Returns new balance or error string.
    """
    if redis is None:
        redis = await get_redis()
    result = await redis.eval(
        _BUILD_TIMER_SCRIPT,
        2,
        f"game:state:{user_id}",
        f"game:builds:{user_id}",
        mana_cost,
        building_id,
        complete_at_unix,
        next_tier,
        idempotency_key,
    )
    return result


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
