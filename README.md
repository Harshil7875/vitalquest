# VitalQuest

A mobile health-RPG that transforms chronic disease management into gameplay. Routine health compliance (steps, glucose checks, medication logs) earns in-game currency ("Mana"), powering avatar progression and asynchronous guild raids.

## Architecture

VitalQuest uses a strict **air-gap model** to comply with HIPAA and India's DPDP Act. The game engine is structurally blind to raw health data.

```
Mobile Client
     │
     ▼
[Nginx API Gateway]  ─── path-based routing ───────────────────────┐
     │                                                               │
     ▼                                                               ▼
[Health Service]  ──── Redis Pub/Sub (one-way) ────►  [Game Service]
  PostgreSQL                health.rewards               Redis only
 (Health Vault)             channel
```

- **Health Service** owns all PHI (PostgreSQL). Handles auth, biometric ingestion, anti-cheat, clinical export, and guild aggregation.
- **Game Service** owns game state (Redis). Receives only anonymized reward tokens — it never knows *why* Mana was awarded.
- **The air-gap**: the `game_service` container has no `POSTGRES_DSN`. Communication is one-way via Redis Pub/Sub.

## API Endpoints

| Method | Path | Service | Description |
|--------|------|---------|-------------|
| `POST` | `/api/auth/register` | Health | Create account, returns JWT |
| `POST` | `/api/auth/login` | Health | Returns JWT |
| `POST` | `/api/health/sync` | Health | Ingest biometric data, award Mana |
| `GET`  | `/api/game/state` | Game | Fetch avatar, Mana balance, guild state |
| `GET`  | `/api/clinical/export` | Health | Export health history (Pro only) |
| `DELETE` | `/api/health/account` | Health | Right to Erasure (GDPR/DPDP) |

## Anti-Cheat Rules Engine

All biometric payloads pass through three rules before a reward is issued:

1. **Hardware Verification** — payload must carry a cryptographic signature from an allowlisted device (Apple HealthKit, Google Fit, Dexcom, etc.). Manual entries are logged clinically but earn no Mana.
2. **Velocity / Plausibility Checks** — values outside physiological limits (e.g. 50,000 steps in 10 min, glucose > 600 mg/dL) are quarantined for physician review.
3. **Daily Mana Cap** — enforced at both services (defense in depth) to prevent unhealthy over-exertion.

## Privacy Features

- **Guild Engine**: individual health metrics are never exposed to other players. A nightly cron aggregates all members' goal completion into a single `boss_damage` integer.
- **Clean Payload Notifications**: health reminders are sent as opaque trigger codes (`ACTION_REQUIRED_01`). Medical text is rendered locally on-device — it never crosses third-party push infrastructure.
- **Right to Erasure**: health PHI is hard-deleted; game state is anonymized as an orphaned record to preserve guild economy integrity.

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI |
| Health DB | PostgreSQL 16 (SQLAlchemy async + Alembic) |
| Game DB | Redis 7 |
| Message Broker | Redis Pub/Sub |
| API Gateway | Nginx |
| Auth | JWT (python-jose) |
| Scheduler | APScheduler (guild cron) |
| Containers | Docker Compose |

## Getting Started

```bash
# 1. Clone the repo
git clone https://github.com/Harshil7875/vitalquest.git
cd vitalquest

# 2. Set up secrets
cp .env.example .env
# Edit .env — generate JWT_SECRET and ENCRYPTION_KEY per the comments

# 3. Run
docker compose up --build

# 4. Run database migrations (first time only)
docker compose exec health_service alembic upgrade head
```

Services will be available at:
- API Gateway: `http://localhost:80`
- Health Service (direct): `http://localhost:8000`
- Game Service (direct): `http://localhost:8001`

## Project Structure

```
vitalquest/
├── shared/                  # Inter-service contracts (JWT, RewardEvent schemas)
├── health_service/
│   ├── api/                 # auth, health sync, clinical export
│   ├── core/                # anti_cheat, goal_evaluator, guild_engine, notification_router
│   ├── db/                  # SQLAlchemy models, async session, Alembic migrations
│   ├── publisher/           # Redis reward event publisher
│   └── tasks/               # Guild aggregation cron job
├── game_service/
│   ├── api/                 # game state endpoint
│   ├── core/                # reward_processor, erasure_handler
│   ├── db/                  # Redis client helpers
│   └── subscriber/          # Redis Pub/Sub listener
├── nginx/
│   └── nginx.conf           # Path-based routing + rate limiting
└── docker-compose.yml
```

## Compliance

VitalQuest is architected from day one for:
- **HIPAA** (US): PHI segregation, access controls, audit logging, right to erasure
- **DPDP Act** (India): data minimization, right to erasure, no PHI in push payloads

> **Note:** This is an MVP/concept implementation. A production deployment requires a formal security audit, Postgres-level encryption (`pgcrypto`), HTTPS/TLS termination, and a penetration test before handling real patient data.
