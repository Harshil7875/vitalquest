"""
Tech Tree State Machine

Validates whether a building upgrade is allowed given the user's current
Sanctuary state and Mana balance. All checks happen server-side — the
client only sends an Intent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from game_service.core.game_config import get_building_config, get_tier_config

logger = logging.getLogger(__name__)


@dataclass
class UpgradeCheckResult:
    allowed: bool
    reason: str = ""
    cost_mana: int = 0
    cost_materials: dict[str, int] = None
    build_time_minutes: int = 0
    next_tier: int = 0

    def __post_init__(self):
        if self.cost_materials is None:
            self.cost_materials = {}


def can_upgrade(
    building_id: str,
    current_sanctuary: dict[str, int],  # {"apothecary": 2, "scout_tower": 1, ...}
    mana_balance: int,
) -> UpgradeCheckResult:
    """
    Returns UpgradeCheckResult. Checks:
      1. Building exists in config
      2. Not already at max tier
      3. All prerequisite buildings meet their minimum tier
      4. User has enough Mana

    Does NOT deduct Mana — that is handled atomically by the Lua script.
    """
    try:
        building_cfg = get_building_config(building_id)
    except ValueError as e:
        return UpgradeCheckResult(allowed=False, reason=str(e))

    current_tier = current_sanctuary.get(building_id, 0)
    next_tier = current_tier + 1
    max_tier = building_cfg["max_tier"]

    if current_tier >= max_tier:
        return UpgradeCheckResult(
            allowed=False,
            reason=f"{building_id} is already at max tier ({max_tier}).",
        )

    # Check if a build is already in progress for this building
    # (caller is responsible for checking game:builds:{user_id} in Redis before calling this)

    try:
        tier_cfg = get_tier_config(building_id, next_tier)
    except ValueError as e:
        return UpgradeCheckResult(allowed=False, reason=str(e))

    # Prerequisite check
    for prereq_building, required_tier in tier_cfg.get("requires", {}).items():
        actual_tier = current_sanctuary.get(prereq_building, 0)
        if actual_tier < required_tier:
            return UpgradeCheckResult(
                allowed=False,
                reason=(
                    f"Requires {prereq_building} at tier {required_tier} "
                    f"(currently tier {actual_tier})."
                ),
            )

    cost_mana = tier_cfg.get("cost_mana", 0)
    if mana_balance < cost_mana:
        return UpgradeCheckResult(
            allowed=False,
            reason=f"Insufficient Mana: need {cost_mana}, have {mana_balance}.",
            cost_mana=cost_mana,
        )

    # Extract material costs (all keys except cost_mana, build_time_minutes, requires)
    cost_materials = {
        k: v for k, v in tier_cfg.items()
        if k.startswith("cost_") and k != "cost_mana"
    }
    # Strip the "cost_" prefix for cleaner API response
    cost_materials = {k[5:]: v for k, v in cost_materials.items()}

    return UpgradeCheckResult(
        allowed=True,
        cost_mana=cost_mana,
        cost_materials=cost_materials,
        build_time_minutes=tier_cfg.get("build_time_minutes", 0),
        next_tier=next_tier,
    )
