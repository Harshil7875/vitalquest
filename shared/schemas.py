"""
Shared inter-service contracts.

These schemas define the ONLY data that crosses the air-gap between the
Health Vault and the Game State. Nothing here contains raw PHI.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


def _new_idempotency_key() -> str:
    return str(uuid.uuid4())


class RewardEvent(BaseModel):
    """
    Anonymized reward token published by the Health Service to the
    'health.rewards' Redis channel. The Game Service subscribes to this.

    Critically: this schema contains NO diagnosis, drug name, raw metric
    value, or any other PHI. It only carries the game-economy consequence
    of a health action having been verified.
    """

    user_id: int
    event_type: Literal["mana_award", "guild_damage", "erasure"]
    amount: int = Field(ge=0, description="Mana to award, or boss damage points")
    source: Literal["steps", "glucose", "medication", "diet", "guild_aggregate", "system"]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    idempotency_key: str = Field(default_factory=_new_idempotency_key)


class GuildDamageEvent(RewardEvent):
    """Guild-level aggregate event. Individual contributions are not exposed."""

    event_type: Literal["guild_damage"] = "guild_damage"
    guild_id: int
    source: Literal["guild_aggregate"] = "guild_aggregate"


class ErasureEvent(RewardEvent):
    """
    Signals the Game Service to anonymize this user's state.
    Published after the Health Vault has already deleted raw PHI.
    """

    event_type: Literal["erasure"] = "erasure"
    amount: int = 0
    source: Literal["system"] = "system"


class BossDefeatEvent(GuildDamageEvent):
    """
    Published when a World Boss is defeated.
    Triggers loot distribution to all active guild members.
    """

    event_type: Literal["guild_damage"] = "guild_damage"
    boss_defeated: bool = True
    boss_id: str = ""


class NotificationJob(BaseModel):
    """
    PHI-free push notification job. Dropped into Redis queues by both services.
    The notification_worker consumes these and dispatches to APNs/FCM.

    Stream A (health): opaque trigger codes, silent push — PHI never leaves backend.
    Stream B (game): rich media payloads, standard routing.
    """

    stream: Literal["health", "game"]
    user_id: int
    trigger_code: str  # e.g. "ACTION_REQUIRED_01" or "GAME_EVENT_01"
    # Rich-media fields (Stream B only — never used for Stream A)
    title: str = ""
    body: str = ""
    badge_count: int = 0
    sound: str = ""
    idempotency_key: str = Field(default_factory=_new_idempotency_key)


class TokenPayload(BaseModel):
    """JWT payload — carried by both services."""

    user_id: int
    role: Literal["free", "pro", "admin"]
    exp: int
