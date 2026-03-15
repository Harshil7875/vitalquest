"""
Guild Engine — Privacy-Preserving Aggregation

Runs as a cron job (daily at 23:59 UTC). Computes collective guild
performance without exposing any individual's health metrics.

Output: a single GuildDamageEvent per guild containing only the total
boss_damage integer. Individual contributions are never exposed.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from health_service.db.models import BiometricLog, User, UserGoal
from shared.schemas import GuildDamageEvent

logger = logging.getLogger(__name__)

# Conversion rate: normalized adherence points → boss damage
_POINTS_PER_GOAL_MET = 200


async def compute_guild_damage(
    guild_id: int,
    db: AsyncSession,
) -> GuildDamageEvent | None:
    """
    For a given guild, aggregates today's goal adherence across all members
    and returns a single GuildDamageEvent.

    Returns None if the guild has no active members.
    """
    today = date.today()

    # Fetch all active (non-deleted) users in this guild
    members_stmt = select(User.id).where(
        User.guild_id == guild_id,
        User.deleted_at.is_(None),
    )
    members_result = await db.execute(members_stmt)
    member_ids = [row[0] for row in members_result.fetchall()]

    if not member_ids:
        logger.info("Guild %d has no active members, skipping.", guild_id)
        return None

    total_points = 0

    for user_id in member_ids:
        # For each member, check how many of their active goals were met today.
        # We only check the boolean (met/not met) — the raw values are irrelevant
        # to the guild output and are never included in the return value.
        goals_stmt = select(UserGoal).where(
            UserGoal.user_id == user_id,
            UserGoal.active == True,
        )
        goals_result = await db.execute(goals_stmt)
        goals = goals_result.scalars().all()

        for goal in goals:
            logs_stmt = select(func.max(BiometricLog.value)).where(
                BiometricLog.user_id == user_id,
                BiometricLog.data_type == goal.data_type,
                func.date(BiometricLog.recorded_at) == today,
                BiometricLog.quarantined == False,
            )
            log_result = await db.execute(logs_stmt)
            best_value: float | None = log_result.scalar_one_or_none()

            if best_value is not None and best_value >= goal.target_value:
                total_points += _POINTS_PER_GOAL_MET

    logger.info(
        "Guild %d | members=%d | total_boss_damage=%d",
        guild_id,
        len(member_ids),
        total_points,
    )

    return GuildDamageEvent(
        user_id=0,  # guild events are not tied to any individual user
        guild_id=guild_id,
        amount=total_points,
    )


async def get_active_guild_ids(db: AsyncSession) -> list[int]:
    """Returns all guild IDs that have at least one active member."""
    stmt = (
        select(User.guild_id)
        .where(User.guild_id.is_not(None), User.deleted_at.is_(None))
        .distinct()
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.fetchall()]
