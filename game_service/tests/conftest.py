"""
pytest fixtures shared by all game_service tests.

Sets minimum env vars so `game_service.config.Settings` instantiates cleanly,
and exposes a `redis_container` fixture that spins up a real redis:7-alpine
testcontainer for tests that need actual Lua execution. We use real Redis
because fakeredis does not faithfully implement EVALSHA.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")


@pytest_asyncio.fixture
async def redis_container() -> AsyncIterator[aioredis.Redis]:
    """
    Spin up a real Redis instance via testcontainers and yield an async client
    pointed at it. The container is torn down automatically when the test exits.
    """
    from testcontainers.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        client = await aioredis.from_url(f"redis://{host}:{port}/0", decode_responses=True)
        try:
            yield client
        finally:
            await client.aclose()
