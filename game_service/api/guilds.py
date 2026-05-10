"""
Guild Management API

POST /api/game/guilds/create                 — create a guild (costs Mana)
POST /api/game/guilds/join                   — join by invite code or guild_id
DELETE /api/game/guilds/{guild_id}/kick/{user_id} — Guildmaster kicks a member
POST /api/game/guilds/{guild_id}/chat        — send a chat message (PHI-filtered)
GET  /api/game/guilds/{guild_id}/chat        — fetch recent chat messages
GET  /api/game/guilds/{guild_id}             — get guild state / roster
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from game_service.api.game import get_current_user
from game_service.core.chat_filter import filter_message
from game_service.core.game_config import get_world_boss_hp
from game_service.core.guild_manager import create_guild, join_guild, kick_member
from game_service.db.redis_client import (
    get_chat_messages,
    get_guild_roster,
    get_guild_state,
    get_redis,
    push_chat_message,
)
from shared.schemas import TokenPayload

router = APIRouter(prefix="/api/game/guilds", tags=["guilds"])


# ─── Request / Response Models ────────────────────────────────────────────────

class CreateGuildRequest(BaseModel):
    name: str
    idempotency_key: str


class JoinGuildRequest(BaseModel):
    invite_code: str | None = None
    guild_id: int | None = None


class ChatRequest(BaseModel):
    message: str


class ChatMessage(BaseModel):
    user_id: str
    message: str
    sent_at: float


class GuildResponse(BaseModel):
    guild_id: int
    name: str
    member_count: int
    boss_hp_remaining: int
    invite_code: str | None = None


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_guild_endpoint(
    body: CreateGuildRequest,
    current_user: TokenPayload = Depends(get_current_user),
):
    redis = await get_redis()
    result = await create_guild(
        user_id=current_user.user_id,
        guild_name=body.name,
        idempotency_key=body.idempotency_key,
        redis=redis,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)
    return {"guild_id": result.guild_id, "invite_code": result.invite_code}


@router.post("/join")
async def join_guild_endpoint(
    body: JoinGuildRequest,
    current_user: TokenPayload = Depends(get_current_user),
):
    result = await join_guild(
        user_id=current_user.user_id,
        invite_code=body.invite_code,
        guild_id=body.guild_id,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)
    return {"guild_id": result.guild_id}


@router.delete("/{guild_id}/kick/{target_user_id}")
async def kick_member_endpoint(
    guild_id: int,
    target_user_id: int,
    current_user: TokenPayload = Depends(get_current_user),
):
    result = await kick_member(
        requestor_user_id=current_user.user_id,
        target_user_id=target_user_id,
        guild_id=guild_id,
    )
    if not result.success:
        raise HTTPException(status_code=403, detail=result.message)
    return {"detail": result.message}


@router.post("/{guild_id}/chat", status_code=status.HTTP_201_CREATED)
async def send_chat_message(
    guild_id: int,
    body: ChatRequest,
    current_user: TokenPayload = Depends(get_current_user),
):
    """
    PHI/PII Safe Chat. Messages are filtered before storage.
    If PHI is detected, return 403 with a privacy warning — never store.
    """
    filter_result = filter_message(body.message)
    if not filter_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Message blocked: Please do not share specific medical metrics "
                "or personal data in the public chat to protect your privacy."
            ),
        )

    # Verify sender is in this guild
    roster = await get_guild_roster(guild_id)
    if str(current_user.user_id) not in roster:
        raise HTTPException(status_code=403, detail="You are not a member of this guild.")

    message_data = json.dumps({
        "user_id": str(current_user.user_id),
        "message": body.message,
        "sent_at": time.time(),
    })
    await push_chat_message(guild_id, message_data)
    return {"status": "sent"}


@router.get("/{guild_id}/chat", response_model=list[ChatMessage])
async def get_chat_history(
    guild_id: int,
    current_user: TokenPayload = Depends(get_current_user),
):
    roster = await get_guild_roster(guild_id)
    if str(current_user.user_id) not in roster:
        raise HTTPException(status_code=403, detail="You are not a member of this guild.")

    raw_messages = await get_chat_messages(guild_id)
    return [ChatMessage(**json.loads(m)) for m in raw_messages]


@router.get("/{guild_id}", response_model=GuildResponse)
async def get_guild(
    guild_id: int,
    current_user: TokenPayload = Depends(get_current_user),
):
    state = await get_guild_state(guild_id)
    if not state:
        raise HTTPException(status_code=404, detail="Guild not found.")

    roster = await get_guild_roster(guild_id)

    # Only reveal invite_code to guild members
    invite_code = None
    if str(current_user.user_id) in roster:
        invite_code = state.get("invite_code")

    return GuildResponse(
        guild_id=guild_id,
        name=state.get("name", "Unknown"),
        member_count=len(roster),
        boss_hp_remaining=int(state.get("boss_hp_remaining", get_world_boss_hp())),
        invite_code=invite_code,
    )
