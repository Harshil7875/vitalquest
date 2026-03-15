"""
Notification Worker — Entry Point

Runs two concurrent consumer loops (one per stream) as asyncio tasks.
Does NOT expose an HTTP server — it's a pure background worker.
"""

from __future__ import annotations

import asyncio
import logging
import signal

import redis.asyncio as aioredis

from notification_worker.config import settings
from notification_worker.consumer import consume_stream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Notification worker starting.")
    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)

    tasks = [
        asyncio.create_task(
            consume_stream(redis, settings.notification_queue_health_key),
            name="stream_a_health",
        ),
        asyncio.create_task(
            consume_stream(redis, settings.notification_queue_game_key),
            name="stream_b_game",
        ),
    ]

    loop = asyncio.get_running_loop()

    def _shutdown(signum, frame):
        logger.info("Shutdown signal received, cancelling consumers.")
        for t in tasks:
            t.cancel()

    loop.add_signal_handler(signal.SIGTERM, _shutdown, signal.SIGTERM, None)
    loop.add_signal_handler(signal.SIGINT, _shutdown, signal.SIGINT, None)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        await redis.aclose()
        logger.info("Notification worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())
