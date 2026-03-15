"""
Goal Evaluator

Compares an incoming biometric payload against the user's stored health goal
to determine whether a reward should be issued and how much Mana to award.

This module never returns raw PHI — only a GoalResult with game-economy values.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from health_service.core.anti_cheat import SyncPayload
from health_service.db.models import UserGoal


@dataclass
class GoalResult:
    met: bool
    mana_to_award: int
    goal_found: bool = True


async def evaluate(payload: SyncPayload, db: AsyncSession) -> GoalResult:
    """
    Returns GoalResult. If no active goal exists for this data_type, returns
    met=False so clinical logging still proceeds but no reward is issued.
    """
    stmt = select(UserGoal).where(
        UserGoal.user_id == payload.user_id,
        UserGoal.data_type == payload.data_type,
        UserGoal.active == True,
    )
    result = await db.execute(stmt)
    goal: UserGoal | None = result.scalar_one_or_none()

    if goal is None:
        return GoalResult(met=False, mana_to_award=0, goal_found=False)

    # MVP: binary model — goal is fully met or not. No partial credit.
    met = payload.value >= goal.target_value
    return GoalResult(
        met=met,
        mana_to_award=goal.mana_reward if met else 0,
        goal_found=True,
    )
