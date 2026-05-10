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
from health_service.api.devices import router as devices_router
from health_service.api.health import router as health_router
from health_service.api.webhooks import router as webhooks_router
from health_service.db.session import async_session_factory
from health_service.publisher.redis_publisher import start_outbox_drainer
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

    # Outbox drainer (Phase 5 / fix #19): publishes RewardOutbox rows to Redis
    # AFTER the originating transaction commits. Without this, a publish that
    # races a transaction rollback would award Mana on the game side without
    # a corresponding ManaLedger row.
    drainer_task = start_outbox_drainer(async_session_factory)

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        drainer_task.cancel()


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
app.include_router(devices_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "health_service"}
