"""
Health Service — FastAPI Application

Handles all PHI ingestion, anti-cheat validation, goal evaluation,
clinical export, and the guild aggregation cron job.

The game_service never communicates directly with this service.
All cross-service communication is via the Redis 'health.rewards' channel.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from health_service.api.auth import router as auth_router
from health_service.api.clinical import router as clinical_router
from health_service.api.clinical import router_account
from health_service.api.health import router as health_router
from health_service.tasks.guild_cron import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the guild aggregation cron scheduler on service startup
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="VitalQuest — Health Service",
    version="1.0.0",
    description=(
        "Secure health data ingestion, anti-cheat validation, and clinical portal. "
        "All PHI is stored here and never forwarded to the game service."
    ),
    lifespan=lifespan,
    # Disable the default docs UI in production to reduce attack surface
    # docs_url=None, redoc_url=None,
)

app.include_router(auth_router)
app.include_router(health_router)
app.include_router(clinical_router)
app.include_router(router_account)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "health_service"}
