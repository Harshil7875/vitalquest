# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

VitalQuest is a mobile health-RPG. The most important fact about the architecture is the **air-gap**: PHI (Protected Health Info) lives only in the `health_service` PostgreSQL "Health Vault." The `game_service` and `notification_worker` containers do not receive `POSTGRES_DSN` and have no path to PHI. The only data crossing the boundary is the anonymized `RewardEvent` (and a few sibling events) defined in `shared/schemas.py`, published one-way via the Redis `health.rewards` Pub/Sub channel.

When making any change, ask: "Does this leak PHI across the air-gap?" If a change to `game_service` or `notification_worker` would require a Postgres connection, a diagnosis string, a drug name, or a raw biometric value, the design is wrong — re-route through `shared/schemas.py` events instead.

The full conceptual model (anti-cheat rules, economy tuning, Grace Protocol, dual-stream push, Safe Chat, Sanctuary tech tree) is documented in `README.md` and `docs/`. Read those before designing new features.

## Common commands

### Backend (Docker Compose, repo root)

```bash
# Build and start all services (postgres, redis, health_service, game_service,
# notification_worker, nginx). Gateway listens on :80.
docker compose up --build

# Apply database migrations — REQUIRED on first boot and after any model change.
docker compose exec health_service alembic upgrade head

# Generate a new migration from ORM model changes (autogenerate diffs against
# health_service.db.models.Base.metadata).
docker compose exec health_service alembic revision --autogenerate -m "describe change"

# Tail logs for a specific service
docker compose logs -f health_service
docker compose logs -f game_service
docker compose logs -f notification_worker

# Open a Python shell inside a running service (useful for poking at game state)
docker compose exec game_service python
docker compose exec health_service python
```

The Dockerfiles use `context: .` (repo root) on purpose because each image must `COPY shared/` alongside the service folder. Don't rewrite them to use a per-service build context.

There is no automated test suite in this repository yet. Don't claim tests pass — there's nothing to run. If you add tests, wire them into the appropriate service container so they run with the same `PYTHONPATH=/app` layout.

### Frontend (Expo, in `frontend/`)

```bash
cd frontend
npm install
npm run web      # Chrome, port 8081 — enables the Dev Mock Panel
npm run ios      # iOS simulator
npm run android  # Android emulator
npm run lint     # eslint (TypeScript files)
```

The frontend points at `http://localhost:80` (the Nginx gateway) by default. Override with `EXPO_PUBLIC_API_URL` in `frontend/.env.local`. The backend must be running before starting the frontend.

`DevMockPanel` is web-only — it's how you exercise the full sync → reward → Mana flow without real hardware. Use `npm run web` whenever you're testing health-data ingestion paths end-to-end.

### Configuration

Copy `.env.example` to `.env` before the first `docker compose up`. The four secrets that must be set for anything to work are `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `JWT_SECRET` (32+ chars), and `ENCRYPTION_KEY` (base64-encoded 32 bytes). APNs/FCM credentials are optional — the worker logs and skips dispatch when they're absent.

## Architecture invariants

These are constraints that aren't obvious from any single file. Violating them breaks the threat model.

- **`game_service` and `notification_worker` must never gain a Postgres connection.** This is enforced by the absence of `POSTGRES_DSN` in their `docker-compose.yml` env blocks, and the comments there exist for a reason. If you find yourself wanting to query Postgres from `game_service`, the answer is "publish a new event from `health_service` to Redis."
- **Mana caps and economy validation are enforced at both services** (defense in depth — health_service won't award past the daily cap, game_service won't accept a reward event that would exceed it). Don't simplify by removing one side.
- **All economy mutations in `game_service` go through Lua scripts** (`game_service/scripts/*.lua`) — Mana debits, build timer sets — to keep them atomic and idempotent under concurrent requests. Each script enforces idempotency via a `processed_txns` set keyed on the request's `idempotency_key`. Don't replace these with sequences of `HGET`/`HSET` calls.
- **`game_service/data/master_config.json` is the single source of truth** for economy tuning (Mana sources, building costs, tech-tree prerequisites, world boss HP, loot tables). Hard-coded numbers elsewhere in `game_service` are bugs — read from `game_config.py` instead.
- **Cross-service contracts live in `shared/schemas.py`** (`RewardEvent`, `GuildDamageEvent`, `ErasureEvent`, `BossDefeatEvent`, `NotificationJob`, `TokenPayload`). Both services import from this module — when the schema changes, both sides need to update in lockstep within the same change. Never put PHI in any of these schemas.
- **Stream A push notifications are silent and PHI-free.** `notification_worker/dispatcher.py` sends an opaque `vitalquest_trigger` code; the device looks the code up locally to render text. Adding `title`/`body` to a Stream A `NotificationJob` defeats the privacy design. Stream B (game) is fine to send rich text on.
- **JWT verification is independent per service.** `shared/jwt_utils.py` is shared, but each service decodes the token itself with its own `JWT_SECRET` env var. Don't add a "trust upstream" header bypass.
- **Anti-cheat (`health_service/core/anti_cheat.py`) is a pipeline of discrete rules.** New cheat checks should be added as new rule classes composed into `run_pipeline`, not inlined into existing rules.
- **Right to Erasure is a two-step flow:** `health_service` cascades a bulk SQL `DELETE` across every PHI/PII table (`BiometricLog`, `OAuthToken`, `ManaLedger`, `AuditLog`, `DeviceToken`, `DeviceAttestation`), anonymizes the `User` row in place, and publishes an `ErasureEvent` so `game_service` anonymizes its Redis state to `deleted_user_{hash}`. The cascade uses bulk SQL (not ORM `delete()` per row) so corrupted ciphertext can't block deletion. Both halves must run for a deletion to be complete.
- **Hardware-attested `/sync` requires device enrollment first.** The anti-cheat `HardwareVerificationRule` HMAC-verifies every payload against a per-device key from `device_attestations`. A `/sync` from a never-enrolled device returns `clinical_log_only=true` and zero Mana — it's not a bug, it's the safe default. Mobile-app onboarding must `POST /api/health/devices/enroll` (gets a 32-byte HMAC key in the response, exactly once) and store the key in `expo-secure-store`. Re-enrollment of an active device returns 409; rotation requires `DELETE /api/health/devices/{manufacturer}/{device_id}` first. Soft-revoke preserves the row for audit; the partial unique index `uq_active_device_attestation` only enforces uniqueness on rows where `revoked_at IS NULL`.

## Service-by-service quick map

- **`health_service/`** — FastAPI on `:8000`. Routers: `auth`, `health`, `webhooks`, `clinical`, `devices`. Background jobs run via APScheduler in `tasks/` (guild aggregation cron at 23:59 UTC, OAuth token rotation every 50 min) plus the reward-outbox drainer (every ~1s, publishes committed `RewardOutbox` rows to the `health.rewards` Redis Stream). Adapters in `adapters/` translate provider payloads (Apple HealthKit, Google Fit, Dexcom, …) into the internal `VitalQuestStandardPayload`. PHI columns (`*_encrypted`) use the `EncryptedString` TypeDecorator from `core/crypto.py` — ORM reads return plaintext, raw SELECT returns Fernet ciphertext.
- **`game_service/`** — FastAPI on `:8001`. Routers: `game` (state), `actions` (economy intents), `guilds`. `subscriber/redis_subscriber.py` listens on `health.rewards` and dispatches to `core/reward_processor.py`. State is Redis-only — no ORM, no migrations.
- **`notification_worker/`** — No HTTP server. `main.py` runs two `BLPOP` consumer loops (Stream A, Stream B) against Redis lists, dispatches to `apns_client.py` / `fcm_client.py`, and pushes permanent failures to a DLQ.
- **`nginx/nginx.conf`** — Path-based routing: `/api/auth/`, `/api/health/`, `/api/health/webhooks/`, `/api/health/oauth/`, `/api/clinical/` → health_service; `/api/game/` → game_service. Per-zone rate limits are defined here.
- **`shared/`** — Schemas and JWT helpers imported by all services. The Dockerfiles `COPY shared/` into `/app/shared`, so the import path is `from shared.schemas import …`.
- **`frontend/`** — Expo Router app. `app/(game)/` is auth-gated; `app/(clinical)/` is biometric-double-gated (FaceID/TouchID). `services/api/client.ts` is the typed fetch wrapper; `services/api/hooks.ts` defines all TanStack Query hooks. Game state is in `store/useGameStore.ts` (persisted); clinical state is in `store/useClinicalStore.ts` (auto-cleared on app-background to keep PHI off the UI when the user task-switches).

## Working with the database

Alembic config is at the repo root (`alembic.ini`); migration scripts live under `health_service/db/migrations/versions/`. `alembic.ini` intentionally leaves `sqlalchemy.url` blank — `env.py` reads `POSTGRES_DSN` from `health_service.config.Settings` at runtime, so you must run Alembic *inside the health_service container* (or with the same env vars set) for it to find the database. Models are in `health_service/db/models.py`; `target_metadata = Base.metadata` is wired up for `--autogenerate`.
