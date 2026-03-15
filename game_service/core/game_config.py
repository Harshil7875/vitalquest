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
