"""
Economy Actions — Server-Authoritative State Mutations

Handles building upgrades and chest openings via atomic Lua scripts.
The client sends an Intent; the server validates, executes, and returns
the Authoritative State. Clients cannot skip validation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import redis.asyncio as aioredis

from game_service.core.game_config import get_skip_timer_cost_gems_per_hour
from game_service.core.loot import ItemGrant, calculate_skip_timer_cost, roll_chest
from game_service.core.tech_tree import can_upgrade
from game_service.db.lua_runner import runner as lua_runner
from game_service.db.redis_client import (
    debit_mana_lua,
    get_build_timers,
    get_game_state,
    set_build_timer_lua,
    get_sanctuary_state,
)

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    success: bool
    message: str
    new_mana_balance: int = 0
    items_granted: list[ItemGrant] = None
    build_complete_at: int | None = None  # Unix timestamp

    def __post_init__(self):
        if self.items_granted is None:
            self.items_granted = []


async def upgrade_building(
    user_id: int,
    building_id: str,
    idempotency_key: str,
    redis: aioredis.Redis,
) -> ActionResult:
    """
    Validates and executes a building upgrade.
    Steps: tech tree check → Lua atomic debit + timer set → return authoritative state.
    """
    raw_state = await get_game_state(user_id)
    mana_balance = int(raw_state.get("mana_balance", 0))
    sanctuary = await get_sanctuary_state(user_id)

    # Check for in-progress build
    timers = await get_build_timers(user_id)
    complete_at_key = f"{building_id}:complete_at"
    if complete_at_key in timers:
        complete_at_ts = int(timers[complete_at_key])
        if complete_at_ts > int(time.time()):
            return ActionResult(
                success=False,
                message=f"Build already in progress for '{building_id}'.",
                new_mana_balance=mana_balance,
            )

    # Tech tree validation
    check = can_upgrade(building_id, sanctuary, mana_balance)
    if not check.allowed:
        return ActionResult(
            success=False,
            message=check.reason,
            new_mana_balance=mana_balance,
        )

    complete_at_unix = int(time.time()) + (check.build_time_minutes * 60)

    # Atomic debit + timer set
    new_balance = await set_build_timer_lua(
        user_id=user_id,
        building_id=building_id,
        mana_cost=check.cost_mana,
        complete_at_unix=complete_at_unix,
        next_tier=check.next_tier,
        idempotency_key=idempotency_key,
        redis=redis,
    )

    if isinstance(new_balance, str):  # Lua returned error string
        return ActionResult(success=False, message=new_balance, new_mana_balance=mana_balance)

    logger.info(
        "user_id=%d started %s tier %d, costs %d Mana, completes at %d",
        user_id, building_id, check.next_tier, check.cost_mana, complete_at_unix,
    )
    return ActionResult(
        success=True,
        message=f"{building_id} upgrade to tier {check.next_tier} started.",
        new_mana_balance=int(new_balance),
        build_complete_at=complete_at_unix,
    )


async def skip_build_timer(
    user_id: int,
    building_id: str,
    idempotency_key: str,
    redis: aioredis.Redis,
) -> ActionResult:
    """
    Pays Astral Gems to immediately complete a build timer.

    Phase 9a / fix #13 — atomic via skip_timer.lua. The previous version was
    four sequential commands and ignored the idempotency_key, so retries
    double-charged gems and a crash mid-sequence corrupted state (gems gone
    but tier not promoted, or tier promoted but timer not cleared blocking
    the next upgrade). The Lua does idempotency-check + gem-debit + tier-
    promote + timer-clear in one block.
    """
    timers = await get_build_timers(user_id)
    complete_at_key = f"{building_id}:complete_at"
    tier_key = f"{building_id}:pending_tier"

    if complete_at_key not in timers:
        return ActionResult(success=False, message="No active build timer for this building.")

    complete_at = int(timers[complete_at_key])
    remaining_minutes = max(0, (complete_at - int(time.time())) // 60)
    gem_cost = calculate_skip_timer_cost(remaining_minutes)
    next_tier = int(timers.get(tier_key, 1))

    ok, value = await lua_runner.run(
        redis,
        "skip_timer",
        keys=[
            f"game:state:{user_id}",
            f"game:builds:{user_id}",
            f"game:sanctuary:{user_id}",
        ],
        args=[building_id, gem_cost, next_tier, idempotency_key],
    )

    if not ok:
        # Translate Lua error tokens to user-facing messages.
        message_map = {
            "DUPLICATE_REQUEST": "Skip timer already processed.",
            "INSUFFICIENT_GEMS": f"Insufficient Astral Gems: need {gem_cost}.",
            "TIMER_NOT_ACTIVE": "No active build timer for this building.",
        }
        return ActionResult(
            success=False, message=message_map.get(value, value),
        )

    new_gem_balance, applied_tier = value
    raw_state = await get_game_state(user_id)
    logger.info(
        "user_id=%d skipped timer for %s tier %d, spent %d Astral Gems",
        user_id, building_id, applied_tier, gem_cost,
    )
    return ActionResult(
        success=True,
        message=f"{building_id} upgraded to tier {applied_tier} instantly.",
        new_mana_balance=int(raw_state.get("mana_balance", 0)),
    )


async def open_chest(
    user_id: int,
    chest_rarity: str,
    idempotency_key: str,
    redis: aioredis.Redis,
) -> ActionResult:
    """
    Opens a loot chest. Deducts the chest from inventory, rolls loot server-side,
    deposits items. The client has no influence over what drops.
    """
    inventory_key = f"game:inventory:{user_id}:chests"
    chest_count = int(await redis.hget(inventory_key, chest_rarity) or 0)

    if chest_count <= 0:
        return ActionResult(
            success=False,
            message=f"No {chest_rarity} chests in inventory.",
        )

    # Deduct chest atomically
    new_count = await redis.hincrby(inventory_key, chest_rarity, -1)
    if new_count < 0:
        # Race condition guard: restore if someone else took the last chest
        await redis.hincrby(inventory_key, chest_rarity, 1)
        return ActionResult(success=False, message="Chest no longer available.")

    # Roll loot (server-side, cryptographic RNG)
    items = roll_chest(chest_rarity)

    # Deposit items into inventory
    item_inventory_key = f"game:inventory:{user_id}:items"
    for item in items:
        await redis.hincrby(item_inventory_key, item.item_id, item.quantity)

    raw_state = await get_game_state(user_id)
    logger.info(
        "user_id=%d opened %s chest, received: %s",
        user_id, chest_rarity, [(i.item_id, i.quantity) for i in items],
    )
    return ActionResult(
        success=True,
        message="Chest opened.",
        new_mana_balance=int(raw_state.get("mana_balance", 0)),
        items_granted=items,
    )
