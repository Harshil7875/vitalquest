"""
Game State API — GET /api/game/state

Returns the current game state for the authenticated user.
This endpoint reads from Redis only — no PHI database access.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from game_service.db.redis_client import get_game_state, get_guild_state
from shared.jwt_utils import verify_token
from shared.schemas import TokenPayload

router = APIRouter(prefix="/api/game", tags=["game"])
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> TokenPayload:
    payload = verify_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
    return payload


class GuildState(BaseModel):
    guild_id: str
    boss_damage_today: int


class GameStateResponse(BaseModel):
    user_id: int
    mana_balance: int
    avatar_level: int
    sanctuary_tier: int
    guild: GuildState | None


@router.get("/state", response_model=GameStateResponse)
async def get_state(current_user: TokenPayload = Depends(get_current_user)):
    raw = await get_game_state(current_user.user_id)

    guild_id = raw.get("guild_id", "")
    guild = None
    if guild_id:
        guild_raw = await get_guild_state(int(guild_id))
        # Sum all daily boss_damage keys in the guild hash
        boss_damage = sum(
            int(v) for k, v in guild_raw.items() if k.startswith("boss_damage_")
        )
        guild = GuildState(guild_id=guild_id, boss_damage_today=boss_damage)

    return GameStateResponse(
        user_id=current_user.user_id,
        mana_balance=int(raw.get("mana_balance", 0)),
        avatar_level=int(raw.get("avatar_level", 1)),
        sanctuary_tier=int(raw.get("sanctuary_tier", 1)),
        guild=guild,
    )
