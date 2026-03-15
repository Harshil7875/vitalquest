"""
Redis Subscriber — Game Service side of the message bus.

Listens on the 'health.rewards' channel and dispatches each event
to the reward processor. This is the only entry point for state changes
in the game service.

The subscriber loop is designed to survive individual message failures —
a bad message logs an error but does NOT crash the loop.
"""

from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis

from game_service.core.reward_processor import process_reward_event
from game_service.db.redis_client import get_redis
from shared.schemas import GuildDamageEvent, RewardEvent

logger = logging.getLogger(__name__)

REWARDS_CHANNEL = "health.rewards"


async def start_subscriber() -> None:
    """
    Long-running coroutine. Started as an asyncio.Task in main.py's lifespan.
    Reconnects automatically on Redis connection failures.
    """
    logger.info("Game Service subscriber starting on channel '%s'.", REWARDS_CHANNEL)

    while True:
        try:
            redis = await get_redis()
            pubsub = redis.pubsub()
            await pubsub.subscribe(REWARDS_CHANNEL)

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                await _handle_message(message["data"], redis)

        except asyncio.CancelledError:
            logger.info("Subscriber task cancelled, shutting down.")
            return
        except Exception:
            logger.exception(
                "Subscriber connection lost, reconnecting in 5 seconds..."
            )
            await asyncio.sleep(5)


async def _handle_message(raw: str, redis: aioredis.Redis) -> None:
    try:
        data = json.loads(raw)
        event_type = data.get("event_type")

        if event_type == "guild_damage":
            event = GuildDamageEvent(**data)
        else:
            event = RewardEvent(**data)

        await process_reward_event(event, redis)

    except json.JSONDecodeError:
        logger.error("Received non-JSON message on rewards channel: %r", raw)
    except Exception:
        logger.exception("Failed to process message: %r", raw)
