"""
Health Service — FastAPI Application

Handles all PHI ingestion, anti-cheat validation, goal evaluation,
clinical export, guild aggregation cron, webhook ingestion, and OAuth flows.

The game_service never communicates directly with this service.
All cross-service communication is via the Redis 'health.rewards' channel.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from health_service.adapters.registry import initialize_registry
from health_service.api.auth import router as auth_router
from health_service.api.clinical import router as clinical_router
from health_service.api.clinical import router_account
from health_service.api.health import router as health_router
from health_service.api.webhooks import router as webhooks_router
from health_service.tasks.guild_cron import create_scheduler
from health_service.tasks.oauth_token_rotation import rotate_expiring_tokens


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize adapter registry (singletons per process)
    initialize_registry()

    # Start background schedulers
    scheduler = create_scheduler()
    # OAuth token rotation: every 50 minutes
    scheduler.add_job(
        rotate_expiring_tokens,
        trigger="interval",
        minutes=50,
        id="oauth_token_rotation",
        replace_existing=True,
    )
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="VitalQuest — Health Service",
    version="1.4.0",
    description=(
        "Secure health data ingestion, anti-cheat validation, and clinical portal. "
        "All PHI is stored here and never forwarded to the game service."
    ),
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(health_router)
app.include_router(webhooks_router)
app.include_router(clinical_router)
app.include_router(router_account)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "health_service"}
