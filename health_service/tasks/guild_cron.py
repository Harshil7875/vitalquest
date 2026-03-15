"""
Guild Aggregation Cron Job

Runs daily at GUILD_CRON_HOUR:GUILD_CRON_MINUTE UTC.
For each active guild, calls the guild engine to compute collective
boss damage and publishes a GuildDamageEvent to the message broker.

The APScheduler instance is registered in main.py's lifespan context.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from health_service.config import settings
from health_service.core.guild_engine import compute_guild_damage, get_active_guild_ids
from health_service.db.session import async_session_factory
from health_service.publisher.redis_publisher import publish_reward

logger = logging.getLogger(__name__)


async def run_guild_aggregation() -> None:
    """
    Called by APScheduler. Iterates over all active guilds, computes
    boss damage, and publishes reward events. Individual health metrics
    are never included in the published events.
    """
    logger.info("Guild aggregation cron starting.")
    async with async_session_factory() as db:
        try:
            guild_ids = await get_active_guild_ids(db)
            logger.info("Processing %d active guilds.", len(guild_ids))

            for guild_id in guild_ids:
                event = await compute_guild_damage(guild_id, db)
                if event:
                    await publish_reward(event, db)

            await db.commit()
            logger.info("Guild aggregation cron complete.")
        except Exception:
            await db.rollback()
            logger.exception("Guild aggregation cron failed.")


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_guild_aggregation,
        trigger="cron",
        hour=settings.guild_cron_hour,
        minute=settings.guild_cron_minute,
        misfire_grace_time=300,  # tolerate up to 5-minute startup delays
        id="guild_aggregation",
        replace_existing=True,
    )
    return scheduler
