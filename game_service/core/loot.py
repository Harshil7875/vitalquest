"""
Server-Side Loot Resolution

Uses cryptographically secure randomness (secrets.SystemRandom) for all
loot rolls. The client plays a cosmetic opening animation based entirely
on what the server decided — it cannot influence the outcome.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from game_service.core.game_config import get_loot_table

_rng = secrets.SystemRandom()


@dataclass
class ItemGrant:
    item_id: str
    quantity: int


def roll_chest(rarity: str) -> list[ItemGrant]:
    """
    Rolls the loot table for the given rarity chest.
    Returns a list of ItemGrants using weighted random selection.
    Rarity: "common" | "rare" | "epic"
    """
    drop_table = get_loot_table(rarity)
    total_weight = sum(entry["weight"] for entry in drop_table)
    roll = _rng.randint(1, total_weight)

    cumulative = 0
    for entry in drop_table:
        cumulative += entry["weight"]
        if roll <= cumulative:
            return [ItemGrant(item_id=entry["item_id"], quantity=entry["quantity"])]

    # Fallback to first item (should never reach here)
    first = drop_table[0]
    return [ItemGrant(item_id=first["item_id"], quantity=first["quantity"])]


def calculate_skip_timer_cost(remaining_minutes: int) -> int:
    """
    Returns the Astral Gem cost to skip the remaining build time.
    Partial hours round up.
    """
    from game_service.core.game_config import get_skip_timer_cost_gems_per_hour
    import math
    cost_per_hour = get_skip_timer_cost_gems_per_hour()
    hours_remaining = math.ceil(remaining_minutes / 60)
    return max(1, hours_remaining * cost_per_hour)
