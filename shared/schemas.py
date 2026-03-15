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
    source: Literal["steps", "glucose", "medication", "guild_aggregate", "system"]
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


class TokenPayload(BaseModel):
    """JWT payload — carried by both services."""

    user_id: int
    role: Literal["free", "pro", "admin"]
    exp: int
