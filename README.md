# VitalQuest

A mobile health-RPG that transforms chronic disease management into engaging gameplay. Routine health compliance — steps, glucose checks, medication logs — earns in-game currency ("Mana") that powers avatar progression, base building, and asynchronous guild raids against World Bosses.

---

## Architecture

VitalQuest uses a strict **air-gap model** to comply with HIPAA and India's DPDP Act. The game engine is structurally blind to raw health data.

```
Mobile Client / Device Hardware
         │
         ▼
[Nginx API Gateway]  ──── path-based routing ──────────────────────────────┐
         │                                                                  │
         ▼                                                                  ▼
 [Health Service]  ──── Redis Pub/Sub (one-way) ──────►  [Game Service]
   PostgreSQL               health.rewards channel          Redis only
  (Health Vault)                                                │
         │                                                      │
         │                                             [Notification Worker]
         │                                              APNs / FCM dispatch
         │
 Device Cloud APIs
 (Dexcom, Oura, Fitbit)
  via Webhooks + OAuth
```

### Services

| Service | Store | Responsibility |
|---------|-------|----------------|
| **health_service** | PostgreSQL | Auth, biometric ingestion, anti-cheat, goal evaluation, clinical export, guild aggregation cron, OAuth/webhook ingestion |
| **game_service** | Redis | Game state, economy actions, guild management, safe chat, Pub/Sub reward subscriber |
| **notification_worker** | — (queue consumer) | APNs/FCM push dispatch; dual-stream: health (silent/PHI-free) and game (rich media) |
| **nginx** | — | API gateway; path-based routing, rate limiting |

**The air-gap**: the `game_service` and `notification_worker` containers have no `POSTGRES_DSN`. Health→Game communication is one-way via Redis Pub/Sub. The only data that crosses the boundary is an anonymized `RewardEvent` — no raw metrics, no diagnoses.

---

## API Endpoints

### Auth & Health (health_service → port 8000)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/auth/register` | — | Create account, returns JWT |
| `POST` | `/api/auth/login` | — | Returns JWT |
| `POST` | `/api/health/sync` | JWT | Ingest biometric data; runs anti-cheat pipeline and awards Mana |
| `POST` | `/api/health/webhooks/{provider}` | HMAC | Receive real-time data from Dexcom, Oura, Fitbit |
| `GET`  | `/api/health/oauth/{provider}/callback` | JWT | Complete OAuth 2.0 flow for cloud-to-cloud device connections |
| `GET`  | `/api/clinical/export` | JWT (Pro) | Export full health history as JSON |
| `DELETE` | `/api/health/account` | JWT | Right to Erasure — permanently deletes PHI |

### Game (game_service → port 8001)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET`  | `/api/game/state` | JWT | Fetch Mana balance, avatar stats, Sanctuary, guild state |
| `POST` | `/api/game/action/upgrade_building` | JWT | Start a Sanctuary building upgrade (server validates tech tree + Mana) |
| `POST` | `/api/game/action/skip_timer` | JWT | Spend Astral Gems to finish a build instantly |
| `POST` | `/api/game/action/open_chest` | JWT | Open a loot chest (server-side RNG, client cannot influence outcome) |
| `POST` | `/api/game/guilds/create` | JWT | Create a guild (costs Mana) |
| `POST` | `/api/game/guilds/join` | JWT | Join by invite code or public guild ID |
| `DELETE` | `/api/game/guilds/{id}/kick/{user_id}` | JWT (Guildmaster) | Kick an inactive member (Grace Protocol enforced) |
| `POST` | `/api/game/guilds/{id}/chat` | JWT | Send a chat message (PHI-filtered, 403 on detection) |
| `GET`  | `/api/game/guilds/{id}/chat` | JWT | Fetch last 50 guild chat messages |
| `GET`  | `/api/game/guilds/{id}` | JWT | Get guild state, member count, boss HP |

---

## Data Ingestion Pathways

### Pathway A — Device-to-Cloud (Apple HealthKit, Google Health Connect)
Apple and Google store health data on-device. The VitalQuest mobile app reads the local encrypted database, packages it with an HMAC signature, and POSTs to `/api/health/sync`. The adapter verifies the app signature and normalizes the payload.

### Pathway B — Cloud-to-Cloud (Dexcom, Oura, Fitbit)
Hardware CGMs and wearables sync to manufacturer clouds, which push real-time webhooks to `/api/health/webhooks/{provider}`. OAuth 2.0 tokens are stored encrypted and rotated automatically before expiry (50-minute cron, 10-minute buffer).

### Normalization Pipeline
All payloads — regardless of source — are translated by a source-specific **Adapter** into a `VitalQuestStandardPayload` before reaching any core logic:

| Translation | Problem | Solution |
|---|---|---|
| Unit conversion | Apple sends `mg/dL`, European devices send `mmol/L` | Adapter converts to internal baseline (`mg/dL`) |
| Timezone alignment | User flies NYC → London; step tracker logs in UTC but goal resets at local midnight | Adapter normalizes all timestamps to UTC, preserving local offset for goal evaluation |
| Metric mapping | Google calls a walk `com.google.step_count.delta`, Apple calls it `HKQuantityTypeIdentifierStepCount` | Adapter maps to internal `MetricType` enum (`STEPS`, `GLUCOSE`, etc.) |

Failed payloads go to a **Dead Letter Queue** (PostgreSQL) for engineering review — no patient data is silently lost.

---

## Anti-Cheat Rules Engine

Every biometric payload passes through three rules before a reward is issued:

1. **Hardware Verification** — payload must carry a cryptographic signature from an allowlisted manufacturer (`APPLE_HEALTHKIT`, `GOOGLE_FIT`, `DEXCOM`, `WITHINGS`, `GARMIN`, `FITBIT`). Manual entries are logged clinically but earn zero Mana.
2. **Velocity / Plausibility Checks** — values outside physiological limits (>50,000 steps per sync, glucose outside 20–600 mg/dL, heart rate outside 20–250 bpm) are quarantined and flagged for physician review.
3. **Daily Mana Cap** — enforced at **both** services (defense in depth). Cap is 300 Mana/day, reflecting the GDD economy: medication log (+100), step goal (+50), diet log (+25).

---

## Game Economy

### Currency
- **Mana** — primary currency earned through verified health actions. Cannot be purchased.
- **Astral Gems** — premium currency for cosmetics and build timer skips. Cannot boost health metrics or raid damage.

### Sources (Earning)
| Action | Mana Earned |
|--------|-------------|
| Daily medication log | +100 |
| Hit step goal | +50 |
| Diet log | +25 |
| Glucose check | +25 |
| **Daily cap** | **300** |

### Sinks (Spending)
Sanctuary upgrades, avatar gear crafting, guild buffs, and guild creation. Costs scale exponentially per tier (e.g. Apothecary Tier 1 = 500 Mana; Tier 5 = 25,000 Mana).

### Server-Authoritative Paradigm
The client sends only **Intents** (e.g. "I want to upgrade the Apothecary"). The server validates the tech tree, checks Mana balance, executes via atomic **Lua scripts** (preventing race conditions on concurrent requests), and returns the **Authoritative State**. Clients cannot spoof economy actions.

---

## Progression Systems

### The Sanctuary (Base Building)
Players build and upgrade structures on a virtual plot of land. Each building has a tech tree — prerequisites must be met before upgrading. Real-time build timers incentivize daily check-ins. Timer skips cost Astral Gems.

**Buildings:** Apothecary, Scout Tower, Healing Garden, Mana Well (up to 5 tiers each).

### The Avatar
Avatar stats are purely fantasy: **Magic**, **Defense**, and **Agility**. They never map to the user's real body (which would be discouraging for chronic illness patients). Stats determine the damage multiplier each user contributes to guild raids.

### Loot Chests
Earned through perfect health streaks. Server uses `secrets.SystemRandom` (cryptographic RNG) to roll against server-side loot tables. The client plays an animation based entirely on the server's immutable decision.

---

## Guild System

### Privacy-Preserving Multiplayer
Direct PvP is excluded by design to prevent toxic comparisons of medical conditions. All social mechanics are cooperative (PvE).

**World Boss Raids** spawn every Wednesday with 100,000 HP. The guild's collective daily health adherence is converted into boss damage by a nightly aggregation cron. Individual contributions are **never exposed** — the Game Service only receives a single `boss_damage` integer per guild.

### Grace Protocol
Chronic illness patients may be hospitalized or experience health crises. Inactivity is treated with empathy:
- **7 days inactive** → moved to "Resting" state (no longer drags down guild DPS)
- **14 days inactive** → marked "Kick Eligible" (Guildmaster may manually remove)
- The system never auto-kicks — a human must make that decision.

### Safe Chat Engine
Guild chat runs through a synchronous PHI/PII filter before any message is stored or broadcast:
- **8 regex patterns** detect blood pressure readings, A1C values, glucose numbers, insulin doses, etc.
- **40+ drug name blocklist** covers common chronic-disease medications (Metformin, Ozempic, Lisinopril, etc.)
- Detected messages are permanently dropped and return `403` with a privacy warning. They never touch the database.
- Chat is ephemeral: last 100 messages per guild, 24-hour TTL.

---

## Push Notifications

VitalQuest uses a **Dual-Stream Dispatcher** running as a dedicated worker service.

### Stream A — Health Reminders (PHI-Free)
Apple/Google are untrusted third parties under HIPAA/DPDP. Health reminders are **never sent as human-readable text** through their servers.

The worker sends a **silent push** containing only an opaque trigger code:
```json
{"aps": {"content-available": 1}, "data": {"vitalquest_trigger": "ACTION_REQUIRED_01"}}
```
The VitalQuest app wakes in the background, looks up the code in a local mapping dictionary, and the **device OS** generates the banner — e.g. "Time to log your morning stats." No medical text ever crosses the open internet.

### Stream B — Game Engagement (Standard)
Guild attacks, Sanctuary completions, and Mana-full alerts are safe to send as rich-media notifications with title and body text — they contain no PHI.

### Infrastructure
Jobs are enqueued to Redis lists (`notify:stream_a`, `notify:stream_b`) in under 1ms, freeing the API immediately. The worker consumes with `BLPOP`, retries with exponential backoff, and moves permanently failed jobs to a Dead Letter Queue.

---

## Privacy & Compliance

| Feature | Implementation |
|---------|----------------|
| PHI air-gap | `game_service` has no `POSTGRES_DSN`; only anonymized tokens cross the boundary |
| Audit logging | All anti-cheat flags and rule violations written to `AuditLog` table |
| Right to Erasure | Hard-deletes all `BiometricLog` rows; game state anonymized to `deleted_user_{hash}` |
| Push PHI masking | Silent push with opaque trigger codes; medical text rendered locally on-device |
| Guild privacy | Individual adherence never leaves the Health Vault; only aggregate boss damage published |
| Safe chat | Synchronous PHI/drug filter; non-compliant messages permanently dropped, never stored |
| OAuth tokens | Encrypted at rest; auto-rotated before expiry via background cron |
| Manual entry | Logged clinically but earn zero Mana (flagged as `clinical_log_only`) |

Architected from day one for **HIPAA** (US) and **DPDP Act** (India).

---

## Tech Stack

### Backend

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI |
| Health DB | PostgreSQL 16 — SQLAlchemy async, Alembic migrations |
| Game DB | Redis 7 — atomic Lua scripts for economy transactions |
| Message Broker | Redis Pub/Sub (`health.rewards` channel) |
| Notification Queue | Redis Lists (`notify:stream_a`, `notify:stream_b`) |
| Push (iOS) | APNs HTTP/2 with JWT provider auth (.p8 key) |
| Push (Android) | Firebase Cloud Messaging v1 API |
| API Gateway | Nginx — path-based routing, per-endpoint rate limiting |
| Auth | JWT — `python-jose`, verified independently by each service |
| Scheduler | APScheduler — guild cron (23:59 UTC), OAuth token rotation (every 50 min) |
| Containers | Docker Compose — 4 services, network-segmented |

### Frontend

| Layer | Technology |
|-------|-----------|
| Framework | Expo 51 (React Native Web) — single codebase for iOS, Android, and Chrome |
| Routing | Expo Router (file-based) — deep linking, auth-gating, biometric-gating |
| Game Rendering | React Native Skia — 60 FPS Sanctuary canvas; compiles to WebGL on web |
| Animations | React Native Reanimated — shared values on the native UI thread |
| State (game) | Zustand — Mana, buildings, guild; persisted to AsyncStorage |
| State (clinical) | Zustand — daily goals, offline queue; PHI auto-cleared on app-background |
| Data Fetching | TanStack Query (React Query) — caching, retries, optimistic updates |
| Secure Storage | expo-secure-store (iOS/Android) / sessionStorage (web) |
| Auth | expo-local-authentication — FaceID/TouchID biometric gate for clinical routes |
| Offline | NetInfo listener + idempotency-key offline queue with background flush |
| Web Dev Tooling | Dev Mock Panel — simulates health hardware in Chrome without a real device |

---

## Getting Started

### Backend

```bash
# 1. Clone
git clone https://github.com/Harshil7875/vitalquest.git
cd vitalquest

# 2. Configure secrets
cp .env.example .env
# Fill in POSTGRES_PASSWORD, REDIS_PASSWORD, JWT_SECRET, ENCRYPTION_KEY
# See comments in .env.example for generation commands

# 3. Build and run
docker compose up --build

# 4. Run database migrations (first time only)
docker compose exec health_service alembic upgrade head
```

Services:
- API Gateway: `http://localhost:80`
- Health Service (direct): `http://localhost:8000`
- Game Service (direct): `http://localhost:8001`

APNs and FCM credentials are optional for local development — the notification worker gracefully skips sends if keys are absent.

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start on web (recommended for local dev — enables the Dev Mock Panel)
npm run web

# Start on iOS simulator
npm run ios

# Start on Android emulator
npm run android
```

The web build launches at `http://localhost:8081`. It renders the app in a constrained 428 px mobile-width column with the **Dev Mock Panel** docked to the right — click any button on the panel to inject synthetic health payloads into the running backend and watch the Mana balance update in real time.

> **Prerequisite:** the backend must be running (`docker compose up`) before starting the frontend. The frontend points to `http://localhost:80` (the Nginx gateway) by default. Override with `EXPO_PUBLIC_API_URL` in `frontend/.env.local`.

---

## Project Structure

```
vitalquest/
├── shared/                        # Inter-service contracts (no PHI)
│   ├── schemas.py                 # RewardEvent, NotificationJob, TokenPayload
│   └── jwt_utils.py               # Shared JWT encode/verify
│
├── health_service/
│   ├── adapters/                  # Adapter pattern: HealthKit, Google Fit, Dexcom
│   ├── api/                       # auth, health sync, webhooks, OAuth, clinical export
│   ├── core/                      # anti_cheat, goal_evaluator, guild_engine, notification_router
│   ├── db/                        # SQLAlchemy ORM models, async session, Alembic
│   ├── publisher/                 # Redis reward event + notification queue publisher
│   └── tasks/                     # Guild aggregation cron, OAuth token rotation
│
├── game_service/
│   ├── api/                       # game state, economy actions, guild endpoints
│   ├── core/                      # tech_tree, loot, economy_actions, guild_manager,
│   │                              #   chat_filter, raid_manager, reward_processor
│   ├── data/                      # master_config.json (single source of truth for economy)
│   ├── db/                        # Redis client (Lua script wrappers, typed helpers)
│   ├── scripts/                   # mana_debit.lua, build_timer_set.lua (atomic ops)
│   └── subscriber/                # Redis Pub/Sub listener
│
├── notification_worker/
│   ├── apns_client.py             # APNs HTTP/2 client
│   ├── fcm_client.py              # FCM v1 client
│   ├── dispatcher.py              # Routes Stream A (silent) vs Stream B (rich)
│   └── consumer.py                # BLPOP loop, exponential backoff, DLQ
│
├── nginx/
│   └── nginx.conf                 # Routing + rate limiting (webhooks, auth, health, game)
│
├── frontend/                      # Expo (React Native Web) — iOS, Android, Chrome
│   ├── app/                       # Expo Router file-based routes
│   │   ├── _layout.tsx            # Root: QueryClient, ThemeProvider, NetInfo flush
│   │   ├── index.tsx              # Auth-gate redirect (→ sanctuary or login)
│   │   ├── login.tsx
│   │   ├── register.tsx
│   │   ├── (game)/                # Auth-gated game routes
│   │   │   ├── sanctuary.tsx      # Skia canvas, stat bar, manual sync
│   │   │   ├── guild.tsx          # Guild management + live chat
│   │   │   └── avatar.tsx         # Level, currencies, loot chest
│   │   └── (clinical)/            # Biometric-double-gated clinical routes
│   │       ├── dashboard.tsx      # Goals, progress, A1C chart placeholder
│   │       └── export.tsx         # Pro-gated health report export
│   ├── components/
│   │   ├── HeaderBar.tsx          # Dual mode: game (Mana/Level) vs clinical (sync status)
│   │   ├── DevMockPanel.tsx       # Web-only: injects synthetic health payloads
│   │   ├── SanctuaryCanvas.tsx    # React Native Skia 2×2 building grid
│   │   ├── UpgradeBuildingModal.tsx
│   │   └── GuildChat.tsx          # 5-second polling, PHI-scrubbed
│   ├── features/
│   │   ├── auth/                  # useAuth hook, SecureStore token storage
│   │   └── hardware/              # HAL: lazy-loads mobile or web-mock implementation
│   ├── services/api/
│   │   ├── client.ts              # Fetch wrapper with auto-JWT + typed ApiError
│   │   └── hooks.ts               # All TanStack Query hooks (game, health, guild, clinical)
│   ├── store/
│   │   ├── useGameStore.ts        # Zustand: Mana, buildings, guild (persisted)
│   │   └── useClinicalStore.ts    # Zustand: goals, offline queue (PHI auto-clear)
│   ├── theme/
│   │   ├── tokens.ts              # gameTheme (purples/gold) + clinicalTheme (whites/blues)
│   │   └── ThemeProvider.tsx      # Context toggled by routing state
│   └── types/index.ts             # Shared TypeScript interfaces (mirrors backend schemas)
│
└── docker-compose.yml             # 4 containers; network-segmented (health_net / game_net)
```

---

> **Note:** This is an MVP/concept implementation. A production deployment requires a formal security audit, Postgres-level column encryption (`pgcrypto`), HTTPS/TLS termination at the load balancer, HSM-backed key management, and a penetration test before handling real patient data.
