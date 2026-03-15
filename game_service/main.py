"""
Game Service — FastAPI Application

Handles game state queries and processes reward events from the Health Service.
This service has NO access to the PostgreSQL Health Vault.
All state is stored in Redis.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from game_service.api.game import router as game_router
from game_service.subscriber.redis_subscriber import start_subscriber


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the Redis subscriber as a background task
    subscriber_task = asyncio.create_task(start_subscriber())
    yield
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="VitalQuest — Game Service",
    version="1.0.0",
    description=(
        "Game state management and reward processing. "
        "Receives anonymized reward events from the Health Service via Redis Pub/Sub. "
        "No PHI is stored or accessible here."
    ),
    lifespan=lifespan,
)

app.include_router(game_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "game_service"}
