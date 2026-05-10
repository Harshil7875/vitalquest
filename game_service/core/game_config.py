"""
Master Game Config Loader

Loads master_config.json once at startup. All economy and progression
logic reads from this singleton. Changes require redeployment, which
is the right forcing function for economy tuning decisions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_config: dict[str, Any] | None = None

CONFIG_PATH = Path(__file__).parent.parent / "data" / "master_config.json"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    global _config
    with open(path) as f:
        _config = json.load(f)
    logger.info("Master game config loaded from %s", path)
    return _config


def get_config() -> dict[str, Any]:
    if _config is None:
        load_config()
    return _config


def get_building_config(building_id: str) -> dict:
    config = get_config()
    building = config["sanctuary"]["buildings"].get(building_id)
    if building is None:
        raise ValueError(f"Unknown building_id '{building_id}'.")
    return building


def get_tier_config(building_id: str, tier: int) -> dict:
    building = get_building_config(building_id)
    tier_data = building["tiers"].get(str(tier))
    if tier_data is None:
        raise ValueError(f"Building '{building_id}' has no tier {tier}.")
    return tier_data


def get_loot_table(rarity: str) -> list[dict]:
    config = get_config()
    chest = config["loot_chests"].get(rarity)
    if chest is None:
        raise ValueError(f"Unknown chest rarity '{rarity}'.")
    return chest["drop_table"]


def get_skip_timer_cost_gems_per_hour() -> int:
    return get_config()["skip_timer"]["cost_astral_gems_per_hour"]


def get_daily_mana_cap() -> int:
    """Single source of truth for the daily Mana cap.

    Lua scripts read this from `config:daily_mana_cap` in Redis (seeded by
    `sync_to_redis` at boot). Python callers should use this helper so we
    never duplicate the constant.
    """
    return int(get_config()["economy"]["daily_mana_cap"])


def get_world_boss_hp() -> int:
    return int(get_config()["world_boss"]["boss_hp"])


# ─── Redis sync ───────────────────────────────────────────────────────────────


REDIS_KEY_DAILY_MANA_CAP = "config:daily_mana_cap"
REDIS_KEY_WORLD_BOSS_HP = "config:world_boss_hp"


def techtree_key(building_id: str, tier: int | str) -> str:
    """Redis key holding the prereq hash for a given (building, tier)."""
    return f"techtree:{building_id}:tier:{tier}"


async def sync_to_redis(redis: aioredis.Redis) -> None:
    """
    Push master_config values into Redis so Lua scripts can read them.

    Run at game_service startup. Idempotent — safe to re-run after config
    changes. Uses a pipeline (not a transaction) since the consequences of
    a partial sync are recoverable: stale Lua reads will fail gracefully and
    the next sync corrects them.

    Keys written:
      config:daily_mana_cap          — int as string
      config:world_boss_hp           — int as string
      techtree:{building}:tier:{N}   — hash of {prereq_building: required_tier}
    """
    config = get_config()
    pipe = redis.pipeline()

    pipe.set(REDIS_KEY_DAILY_MANA_CAP, str(config["economy"]["daily_mana_cap"]))
    pipe.set(REDIS_KEY_WORLD_BOSS_HP, str(config["world_boss"]["boss_hp"]))

    for building_id, building in config["sanctuary"]["buildings"].items():
        for tier_str, tier_data in building["tiers"].items():
            key = techtree_key(building_id, tier_str)
            # Always DEL first so removed prereqs don't linger from a prior sync.
            pipe.delete(key)
            requires = tier_data.get("requires", {})
            if requires:
                pipe.hset(key, mapping={k: str(v) for k, v in requires.items()})

    await pipe.execute()
    logger.info(
        "Pushed game config to Redis: daily_mana_cap=%d, world_boss_hp=%d, "
        "tech-tree entries written for %d buildings.",
        config["economy"]["daily_mana_cap"],
        config["world_boss"]["boss_hp"],
        len(config["sanctuary"]["buildings"]),
    )
