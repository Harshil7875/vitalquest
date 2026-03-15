"""
Server-Authoritative Game Actions

POST /api/game/action/upgrade_building  — start a Sanctuary building upgrade
POST /api/game/action/skip_timer        — pay Astral Gems to finish immediately
POST /api/game/action/open_chest        — open a loot chest (server-side RNG)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from game_service.api.game import get_current_user
from game_service.core.economy_actions import (
    open_chest,
    skip_build_timer,
    upgrade_building,
)
from game_service.db.redis_client import get_redis
from shared.schemas import TokenPayload

router = APIRouter(prefix="/api/game/action", tags=["actions"])


# ─── Request / Response models ────────────────────────────────────────────────

class UpgradeBuildingRequest(BaseModel):
    building_id: str


class SkipTimerRequest(BaseModel):
    building_id: str


class OpenChestRequest(BaseModel):
    chest_rarity: str  # "common" | "rare" | "epic"


class ActionResponse(BaseModel):
    success: bool
    message: str
    new_mana_balance: int = 0
    items_granted: list[dict] = []
    build_complete_at: int | None = None


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/upgrade_building", response_model=ActionResponse)
async def action_upgrade_building(
    body: UpgradeBuildingRequest,
    current_user: TokenPayload = Depends(get_current_user),
    x_idempotency_key: str = Header(alias="X-Idempotency-Key"),
):
    redis = await get_redis()
    result = await upgrade_building(
        user_id=current_user.user_id,
        building_id=body.building_id,
        idempotency_key=x_idempotency_key,
        redis=redis,
    )
    if not result.success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)

    return ActionResponse(
        success=result.success,
        message=result.message,
        new_mana_balance=result.new_mana_balance,
        build_complete_at=result.build_complete_at,
    )


@router.post("/skip_timer", response_model=ActionResponse)
async def action_skip_timer(
    body: SkipTimerRequest,
    current_user: TokenPayload = Depends(get_current_user),
    x_idempotency_key: str = Header(alias="X-Idempotency-Key"),
):
    redis = await get_redis()
    result = await skip_build_timer(
        user_id=current_user.user_id,
        building_id=body.building_id,
        idempotency_key=x_idempotency_key,
        redis=redis,
    )
    if not result.success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)
    return ActionResponse(success=result.success, message=result.message,
                          new_mana_balance=result.new_mana_balance)


@router.post("/open_chest", response_model=ActionResponse)
async def action_open_chest(
    body: OpenChestRequest,
    current_user: TokenPayload = Depends(get_current_user),
    x_idempotency_key: str = Header(alias="X-Idempotency-Key"),
):
    if body.chest_rarity not in ("common", "rare", "epic"):
        raise HTTPException(status_code=400, detail="Invalid chest rarity.")

    redis = await get_redis()
    result = await open_chest(
        user_id=current_user.user_id,
        chest_rarity=body.chest_rarity,
        idempotency_key=x_idempotency_key,
        redis=redis,
    )
    if not result.success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)

    return ActionResponse(
        success=result.success,
        message=result.message,
        new_mana_balance=result.new_mana_balance,
        items_granted=[{"item_id": i.item_id, "quantity": i.quantity} for i in result.items_granted],
    )
