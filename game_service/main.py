"""
Game Service — FastAPI Application

Handles game state queries, economy actions, guild management,
and processes reward events from the Health Service.
This service has NO access to the PostgreSQL Health Vault.
All state is stored in Redis.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from game_service.api.actions import router as actions_router
from game_service.api.game import router as game_router
from game_service.api.guilds import router as guilds_router
from game_service.core.game_config import load_config, sync_to_redis
from game_service.db.lua_runner import register_default_scripts
from game_service.db.redis_client import get_redis
from game_service.subscriber.redis_subscriber import start_subscriber


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load master game config once at startup
    load_config()

    # Push config keys (daily Mana cap, world boss HP, tech-tree prereqs) into
    # Redis so Lua scripts can read them without re-marshalling JSON per call.
    redis = await get_redis()
    await sync_to_redis(redis)

    # Register all .lua scripts so EVALSHA paths are warm before the first request.
    register_default_scripts()

    # Start the Redis reward subscriber as a background task
    subscriber_task = asyncio.create_task(start_subscriber())
    yield
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="VitalQuest — Game Service",
    version="1.5.0",
    description=(
        "Server-authoritative game state, economy actions, and guild management. "
        "Receives anonymized reward events from the Health Service via Redis Pub/Sub. "
        "No PHI is stored or accessible here."
    ),
    lifespan=lifespan,
)

app.include_router(game_router)
app.include_router(actions_router)
app.include_router(guilds_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "game_service"}
