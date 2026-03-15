"""
Redis client for the Game Service.

All game state is stored in Redis. Key conventions:
  game:state:{user_id}         — hash: mana_balance, avatar_level, guild_id
  game:inventory:{user_id}     — list of item IDs
  game:daily_cap:{user_id}:{date} — int counter for daily Mana cap
  game:guild:{guild_id}        — hash: boss_damage, member_count
  game:processed_events        — set of idempotency_keys (30-day TTL)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import redis.asyncio as aioredis

from game_service.config import settings

_pool: aioredis.Redis | None = None


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
    key = f"game:state:{user_id}"
    data = await redis.hgetall(key)
    if not data:
        # Default new-player state
        return {
            "mana_balance": "0",
            "avatar_level": "1",
            "guild_id": "",
            "sanctuary_tier": "1",
        }
    return data


async def increment_mana(user_id: int, amount: int) -> int:
    """Atomically increments mana_balance. Returns the new total."""
    redis = await get_redis()
    new_total = await redis.hincrby(f"game:state:{user_id}", "mana_balance", amount)
    return new_total


# ─── Daily Cap ────────────────────────────────────────────────────────────────

async def get_daily_cap_counter(user_id: int) -> int:
    redis = await get_redis()
    key = f"game:daily_cap:{user_id}:{date.today().isoformat()}"
    val = await redis.get(key)
    return int(val) if val else 0


async def increment_daily_cap(user_id: int, amount: int) -> int:
    """Increments the daily Mana counter with a 25-hour TTL."""
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
    key = f"game:guild:{guild_id}"
    today = date.today().isoformat()
    new_total = await redis.hincrby(key, f"boss_damage_{today}", amount)
    return new_total


async def get_guild_state(guild_id: int) -> dict:
    redis = await get_redis()
    return await redis.hgetall(f"game:guild:{guild_id}") or {}


# ─── Idempotency ──────────────────────────────────────────────────────────────

PROCESSED_EVENTS_KEY = "game:processed_events"
IDEMPOTENCY_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


async def is_event_processed(idempotency_key: str) -> bool:
    redis = await get_redis()
    return bool(await redis.sismember(PROCESSED_EVENTS_KEY, idempotency_key))


async def mark_event_processed(idempotency_key: str) -> None:
    redis = await get_redis()
    await redis.sadd(PROCESSED_EVENTS_KEY, idempotency_key)
    # Note: SADD on a set doesn't support per-member TTLs in Redis.
    # For production, use a Redis Hash or sorted set with score=timestamp
    # and a periodic cleanup job. For MVP, the set grows slowly.
