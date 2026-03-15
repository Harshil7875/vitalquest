## Backend Architecture & Logic Document: VitalQuest

**Version:** 1.1.0 <br>
**Focus:** Server-Side Logic, Data Segregation, and API Integration

### 1. Architectural Philosophy: The "Air-Gap" Model

The most critical aspect of the VitalQuest backend is the strict segregation of Protected Health Information (PHI) from the gaming ecosystem. To comply with global standards like the DPDP Act and HIPAA, the game engine must remain entirely blind to the user's actual medical metrics.

We achieve this using a dual-database architecture:

* **Database A (The Health Vault):** A highly secure, encrypted database (e.g., PostgreSQL) that stores the raw API payloads from Apple Health, Google Fit, or Dexcom.
* **Database B (The Game State):** A high-speed database (e.g., Redis or MongoDB) that tracks avatar levels, inventory, and guild status.

**The Bridge:** When health data is ingested, a secure microservice evaluates it against the user's goals. If the goal is met, it sends a localized, anonymized boolean token (e.g., `award_mana: 50, user_id: 12345`) to Database B. The game database never knows *why* the mana was awarded.

### 2. The Data Ingestion & Validation Flow

When a user opens VitalQuest, the following backend logic executes:

1. **Authentication:** The mobile client sends a secure JWT (JSON Web Token) to the backend.
2. **Payload Reception:** The client pushes the latest verified data from the device's secure enclave (e.g., 5,000 steps logged via Apple Health).
3. **Anti-Cheat Validation:** The backend checks the payload's source metadata and timestamps to ensure it was hardware-generated and not manually spoofed by the user.
4. **Goal Evaluation (Health Vault):** The logic compares the logged data against the user's daily prescribed goal (e.g., target: 4,000 steps).
5. **State Translation:** If the goal is met, the Health Vault logs the medical data securely, then triggers an internal event.
6. **Game Economy Update:** The Game State database receives the event and updates the user's in-game currency ("Mana") balance.

### 3. Core API Endpoints (MVP Scope)

* `POST /api/auth/login`: Authenticates the user and returns a JWT.
* `POST /api/health/sync`: The primary ingestion route. Accepts payloads containing biometric data, validates the source, and triggers game rewards.
* `GET /api/game/state`: Fetches the current inventory, Mana balance, and base-building status for the game client to render.
* `GET /api/clinical/export`: (Pro Feature) Generates a decrypted, time-stamped JSON or PDF of the user's health metrics for their doctor.

---

## Architecture Document: Event & Anti-Cheat Systems

**Project:** VitalQuest
**Version:** 1.2.0
**Focus:** Inter-Service Communication & Validation Logic

### 1. System Communication: The Event Broker Model

To maintain strict compliance with global data protection frameworks (including HIPAA and India's DPDP Act), VitalQuest utilizes an asynchronous, event-driven architecture to bridge the Health and Game environments.

* **API Gateway:** All incoming client traffic passes through an API Gateway. The Gateway uses path-based routing to ensure biometric payloads (`/api/health/*`) never touch game servers, and game actions (`/api/game/*`) never touch health servers.
* **Message Broker:** The system utilizes a publish/subscribe (Pub/Sub) message broker.
* **Directional Flow:** Communication is strictly one-way for rewards. The Health Service acts as the **Publisher** of reward events. The Game Service acts as the **Subscriber**. The Game Service is explicitly denied permission to query the Health Service directly.

### 2. Data Validation & Anti-Cheat Rules Engine

To protect the integrity of the game economy and the clinical data, the Health Microservice evaluates all incoming biometric payloads against a strict Rules Engine before publishing reward events.

**Rule 1: Hardware Verification**

* **Condition:** The payload must contain a cryptographic signature or a trusted hardware manufacturer ID (e.g., an Apple Watch device ID or an authorized Dexcom API token).
* **Action:** If verified, the data is logged, and the Rules Engine evaluates for game rewards. If flagged as a "Manual Entry", the data is logged in the Clinical Portal only; the reward event is skipped.

**Rule 2: Plausibility Limits (Velocity Checks)**

* **Condition:** The incoming data must fall within human physiological limits to prevent spoofed API calls. For example, a payload claiming 50,000 steps in 10 minutes, or a blood glucose reading of 900 mg/dL.
* **Action:** The data is temporarily quarantined. No game rewards are issued. A flag is generated in the Clinical Portal for user or physician review.

**Rule 3: Daily Reward Caps**

* **Condition:** To prevent unhealthy obsessive behavior (e.g., a user walking 30 miles in a day just to level up their avatar), the Game Service enforces a maximum daily Mana cap.
* **Action:** Once the daily health-to-game conversion cap is reached, further health activities are logged for clinical tracking, but no additional reward events are processed by the Game Service.

---

### Brainstorming: The Remaining Backend Logic

**1. Privacy-Preserving Multiplayer (The Guild Engine)**

* **The Problem:** In a standard RPG, if Player A does 500 damage and Player B does 0, everyone in the guild sees the combat log. In VitalQuest, "doing 0 damage" means someone missed their medication or had a severe glucose crash. Broadcasting that violates medical privacy and creates toxic social pressure.
* **The Logic:** The Health Microservice must act as a "Black Box Aggregator."
* Every night at midnight, the Health Vault calculates the adherence percentage of all 50 guild members.
* It aggregates this into a single, anonymous number (e.g., "Guild Adherence: 85%").
* It then translates that percentage into "Boss Damage" and publishes a single event to the Game State: `{"guild_id": 99, "boss_damage": 8500}`.
* The Game State only receives the total damage. Players see collective success or failure, but individual health metrics remain entirely masked.



**2. Secure Notification Routing (The "Clean Payload" Rule)**

* **The Problem:** Push notifications (via Apple APNs or Google FCM) route through third-party servers. If we send a push saying, "Time to take your Metformin!", we just leaked Protected Health Information (PHI) to Apple/Google, violating HIPAA and India's DPDP Act.
* **The Logic:** The backend must separate notifications into two streams:
* **Game Notifications (Unsecure):** "Your Sanctuary upgrade is complete!" or "The Sloth Demon is attacking your guild!" These can be sent normally.
* **Health Reminders (Secure/Masked):** The backend sends a cryptic payload to the device: `{"trigger": "local_reminder_01"}`. The app *locally* translates that trigger into the specific health reminder. The actual medical text never crosses the open internet.



**3. Compliance Data Lifecycle (The Right to be Forgotten)**

* **The Problem:** Under modern privacy laws (like the DPDP Act in India), users have the right to demand complete deletion of their medical data. But if we delete their data, does their game avatar break? Does the guild lose the points they contributed last month?
* **The Logic:** We need a "Soft-Delete and Anonymize" protocol.
* When a user requests deletion, the Health Vault completely wipes their raw API logs and medical history.
* However, the historical events they triggered (e.g., the 50 Mana they earned in February) remain in the Game State as an orphaned, anonymized record. This ensures the guild's historical raid records don't suddenly recalculate and break the game economy.



---

## Architecture Document: Multiplayer, Notifications & Data Lifecycle

**Project:** VitalQuest
**Version:** 1.3.0
**Focus:** Privacy-Preserving Mechanics & Compliance Workflows

### 1. The Guild Engine: Privacy-Preserving Aggregation

To enable multiplayer mechanics without compromising medical privacy, the backend utilizes an Asynchronous Aggregation pipeline.

* **The Aggregation Cron Job:** The highly secure Health Microservice runs a scheduled task (e.g., daily at 23:59 UTC) to evaluate the daily compliance of all users associated with a specific Guild ID.
* **Data Masking:** Individual adherence metrics (steps, medication logs, glucose stability) are converted into a normalized point system locally within the secure vault.
* **The Output Event:** The points are summed, and a single, aggregate payload is sent to the Game Microservice Message Broker.
* **Player Visibility:** The Game Client displays collective guild progress bars (e.g., "The Guild dealt 10,000 damage today!"). Individual contribution metrics are strictly hidden to prevent medical shaming.

### 2. Secure Notification Routing Logic

VitalQuest employs a strict "Clean Payload" policy for all push notifications to prevent PHI leakage through third-party infrastructure.

* **Game-State Notifications:** Standard routing through Firebase Cloud Messaging (FCM) or Apple Push Notification Service (APNs) for game-related events (guild chats, item drops).
* **Clinical Notifications:** The backend will never inject medical terminology, drug names, or condition statuses into a push payload.
* **Local Translation:** When a health event is triggered, the backend sends a generic trigger code (e.g., `ACTION_REQUIRED_12`). The client-side application decrypts this code locally to display the specific medical prompt (e.g., "Time to log your morning blood pressure").

### 3. Data Lifecycle & Right to Erasure Protocol

To comply with global data protection frameworks, the backend maintains automated workflows for data retention and user-initiated deletion requests.

* **Decoupled Deletion:** When a "Right to be Forgotten" request is authenticated, the Health Vault microservice permanently drops all associated PII (Personally Identifiable Information) and raw biometric logs.
* **Game State Orphan Protocol:** The user's game avatar and Game State data are anonymized (converted to "Deleted_User_X") to preserve the structural integrity of the in-game economy and guild historical data.
* **Data Portability:** The Clinical Portal backend contains an automated export engine, allowing users to download their complete, decrypted medical history in an interoperable format (JSON/PDF) prior to initiating an account deletion.

---

## Architecture Document: Ingestion Adapters & Data Normalization

**Project:** VitalQuest
**Version:** 1.4.0
**Focus:** Third-Party Health API Integration, OAuth 2.0, and Payload Standardization

### 1. Architectural Strategy: The Adapter Pattern

The Health Service utilizes a strict **Adapter Design Pattern** (often called a Wrapper). The core logic of VitalQuest (`anti_cheat.py` and `goal_evaluator.py`) is designed to only understand one language: the `VitalQuestStandardPayload`.

Instead of writing custom logic in our core engine for every new device on the market, we build isolated "Adapters." When a payload arrives, the system identifies the source, routes it to the specific Adapter, translates the proprietary data into our universal format, and *then* passes it to the rules engine.

### 2. The Two Ingestion Pathways

Health data enters the VitalQuest ecosystem through two fundamentally different physical routes. The architecture must handle both seamlessly.

**Pathway A: Device-to-Cloud (Apple HealthKit & Google Health Connect)**

* **The Logic:** Apple and Google prioritize on-device storage. They do not have a centralized cloud API that our servers can query.
* **The Flow:** The VitalQuest mobile app requests OS-level permissions. The app reads the local encrypted health database on the user's phone, packages it into a secure JSON payload, and pushes it to our `POST /api/health/sync` endpoint.
* **The Adapter's Job:** Validates the cryptographic signature from the mobile client to ensure the app itself wasn't tampered with, then standardizes the metrics.

**Pathway B: Cloud-to-Cloud (Dexcom, Oura, Fitbit, Smart Pillboxes)**

* **The Logic:** These are hardware devices that sync directly to their manufacturer's cloud.
* **The Flow (OAuth 2.0):** The user authenticates their Dexcom account inside VitalQuest. Our backend receives an OAuth `access_token` and `refresh_token`.
* **The Ingestion:** The manufacturer's server sends real-time Webhooks to our dedicated ingestion endpoints (e.g., `POST /api/health/webhooks/dexcom`), or our backend runs a polling cron job to fetch new data every 15 minutes.
* **The Adapter's Job:** Verifies the webhook signature against our developer secrets, extracts the raw data, and normalizes it.

### 3. The Data Normalization Pipeline

Regardless of how the data arrives, it must pass through the Normalization Pipeline before any Mana is calculated. The Adapters handle three critical translations:

| Translation Type | The Problem | The Adapter's Solution |
| --- | --- | --- |
| **Unit Conversion** | Apple might send blood glucose in `mg/dL`, while a European device sends it in `mmol/L`. | The Adapter detects the unit metadata and executes a hard mathematical conversion, outputting a strict baseline unit (e.g., always `mg/dL` internally). |
| **Timezone Alignment** | A user flies from New York to London. Their step tracker logs data in UTC, but their daily goal resets at local midnight. | The Adapter extracts the user's current timezone context from the payload and normalizes all timestamps to a UTC baseline, tagging it with the local offset so the `goal_evaluator.py` calculates the "day" correctly. |
| **Metric Mapping** | Google Fit calls a walk `activity_type: 7`, Apple calls it `HKQuantityTypeIdentifierStepCount`. | The Adapter maps these proprietary strings to a universal VitalQuest enum (e.g., `METRIC_STEPS`). |

### 4. Security & Error Handling logic

* **Rate Limiting:** Webhook endpoints are heavily rate-limited via Nginx to prevent DDoS attacks from compromised third-party servers.
* **Dead Letter Queue (DLQ):** If an Adapter fails to parse a payload (e.g., Dexcom pushes a firmware update that changes their JSON structure without warning), the payload is not discarded. It is pushed to a secure DLQ in the Health Vault for manual engineering review, ensuring no patient data is permanently lost due to a parsing error.
* **Token Rotation:** A background worker constantly monitors the OAuth `refresh_tokens` for cloud-to-cloud integrations, automatically requesting new access tokens before the old ones expire to prevent gaps in health tracking.

---

## Architecture Document: The Game Economy & Progression Engine

**Project:** VitalQuest
**Version:** 1.5.0
**Focus:** Server-Authoritative State Management, Transaction Integrity, and Progression Logic

### 1. Architectural Strategy: The Server-Authoritative Paradigm

In standard app development, the frontend often dictates the state. In gaming, trusting the frontend is a catastrophic security flaw. If the VitalQuest mobile client is allowed to tell the server, "I just spent 500 Mana to upgrade my Sanctuary," hackers will intercept that API call, change the payload to "I spent 0 Mana," and unlock everything for free.

To prevent this, the `game_service` operates on a strict **Server-Authoritative Paradigm**:

* **The "Dumb" Client:** The mobile app is merely a visual renderer and an input device. It does not make decisions. It only sends *Intents* (e.g., `POST /api/game/action/upgrade_building`).
* **The "Smart" Server:** The backend validates the intent, checks the user's inventory in Redis, executes the transaction, and returns the *Authoritative State* (e.g., "Transaction successful, 500 Mana deducted, Sanctuary is now Level 2").

### 2. Transaction Integrity & Anti-Fraud Logic

Because Mana represents real-world medical adherence, its in-game value must be protected flawlessly. The backend must handle high-concurrency race conditions (e.g., a user tapping the "Buy" button ten times in a millisecond).

* **Atomic Operations:** All economy transactions are executed using atomic database operations (e.g., utilizing Redis Lua scripts). This ensures that reading the balance, verifying it is sufficient, deducting the cost, and granting the item happen as a single, indivisible server tick. If two requests hit simultaneously, one will queue or fail, preventing a negative balance or double-spending.
* **Idempotency Keys for Actions:** Every purchase request from the client includes a unique UUID. If a user loses network connection right as they buy an item and the client retries the request, the server recognizes the UUID, ignores the duplicate charge, and simply re-sends the successful confirmation.
* **The Economy Ledger:** While Redis handles the real-time speed, every single transaction (Mana earned vs. Mana spent) is asynchronously logged to an append-only ledger. This allows game designers to analyze "faucets" (how fast players earn currency) versus "sinks" (how fast they spend it) to balance the economy over time.

### 3. The Progression State Machine

Leveling up avatars and upgrading base-building elements (The Sanctuary) requires a rigid rules engine to prevent sequence breaking.

* **Tech Tree Validation:** Before approving an upgrade, the engine consults a server-side static configuration file (the "Master Game Config").
* **Dependency Checks:** If a user attempts to build a Level 3 "Healing Garden," the server checks the Config. Does the user have a Level 2 Garden? Do they have enough Mana? Are they at least Avatar Level 10? If any check fails, the transaction is rejected with a `400 Bad Request`.
* **Timers and Skipping:** If an upgrade takes 4 hours to complete in real-time, the server logs an `upgrade_complete_at` UTC timestamp. If the user pays premium currency to "Skip Timer," the server recalculates the timestamp to `now()` and finalizes the state.

### 4. Server-Side RNG (Random Number Generation)

VitalQuest features cosmetic "Loot Chests" earned through perfect health streaks. The logic dictating what drops from these chests must never touch the client.

* **Secure Loot Tables:** When a user opens a chest, the client sends a `POST /api/game/action/open_chest` request.
* **Cryptographic Randomness:** The server uses a secure random number generator (not a basic, predictable math library) to roll against a server-side loot table (e.g., 80% chance for Common Wood, 15% for Rare Iron, 5% for Epic Skin).
* **State Delivery:** The server deducts the chest from the inventory, adds the rolled items, and *then* tells the client what was won. The client plays the flashy opening animation based entirely on the server's immutable decision.

---

## Architecture Document: Guild Management & Social Graph

**Project:** VitalQuest
**Version:** 1.6.0
**Focus:** Social CRUD Operations, Membership Lifecycles, and Safe Chat Logic

### 1. Architectural Strategy: The Isolated Social Graph

Because VitalQuest relies on multiplayer accountability (Guilds) to drive retention, the social graph must be robust. However, to maintain the strict "Air-Gap" compliance, the entire Guild Management system lives *exclusively* within the `game_service`.

The `health_service` only knows that "User 123 belongs to Guild 456" for nightly aggregation. It does not know the guild's name, its chat history, or its banner logo. Conversely, the `game_service` manages all social interactions but has zero visibility into *why* a guild member missed a daily objective.

### 2. Guild CRUD & The Membership Lifecycle

Managing guilds requires strict server-authoritative state checks to prevent database desynchronization (e.g., a user being in two guilds at once or a guild exceeding its member cap).

* **Creation & Joining (CRUD):** * When a user creates a guild (`POST /api/game/guilds/create`), the server deducts the required Mana cost, initializes the Guild object in Redis, and assigns the user the "Guildmaster" role.
* Users can browse public guilds or use unique, server-generated invite codes for private guilds (`POST /api/game/guilds/join`). The server verifies the guild is below the maximum capacity (e.g., 50 members) before appending the user to the roster.


* **The Auto-Kick & Inactivity Logic:** * In standard games, inactive players are kicked to keep the guild competitive. In a health app, inactivity might mean the user is hospitalized.
* **The Grace Protocol:** The server tracks a `last_login_date` in the game state. If a user is inactive for 7 days, they are automatically moved to a "Resting" state. Their lack of progression no longer drags down the guild's collective Boss Damage (preventing social resentment), but they are not removed from the community. A Guildmaster can manually kick them after 14 days, but the system defaults to empathy over penalty.



### 3. The Safe Chat Engine (PII & PHI Prevention)

Providing an in-game chat is highly engaging but represents the single biggest compliance risk. If a user types, "Hey guys, my Dexcom is reading 250 mg/dL today," they have just injected raw Protected Health Information (PHI) into an unencrypted game database, violating HIPAA/DPDP Act rules.

* **The In-Memory Filter:** Before any chat message is committed to the database or broadcasted via WebSockets to other players, it must pass through a synchronous filtering pipeline.
* **Lexical & ML Scrubbing:** The backend utilizes a high-speed Regex dictionary and a lightweight NLP (Natural Language Processing) model trained to detect medical terminology, drug names (e.g., Metformin, Adderall), and numerical health patterns (e.g., "120/80", "A1C").
* **Message Rejection:** If PHI or severe toxicity is detected, the server rejects the payload with a `403 Forbidden` and returns a localized warning to the client: "Message blocked: Please do not share specific medical metrics or personal data in the public chat to protect your privacy." The message is permanently dropped and never touches the database.
* **Ephemeral Storage:** Guild chat history is not stored permanently. The Redis instance is configured to hold only the last 100 messages per guild, with a strict 24-hour TTL (Time-To-Live) expiration.

### 4. Asynchronous Raid Synchronization

When the `health_service` runs its nightly cron job and publishes the aggregate Boss Damage event (as detailed in v1.3.0), the Guild Management module catches it.

* **State Distribution:** The `game_service` receives the `GuildDamageEvent`. It deducts the health from the active World Boss assigned to that Guild.
* **Loot Distribution:** If the boss is defeated, the server automatically iterates through the Guild's active roster and deposits the victory loot (Mana, items) directly into each member's individual inventory, logging the transaction with a unique idempotency key to prevent double-payouts.

---

## Architecture Document: Push Notification Dispatcher & Secure Routing

**Project:** VitalQuest

**Version:** 1.7.0

**Focus:** Asynchronous Worker Queues, APNs/FCM Integration, and PHI Data Masking

### 1. Architectural Strategy: The Dual-Stream Dispatcher

Sending a push notification is a slow, synchronous network request to a third-party server (Apple Push Notification service for iOS, or Firebase Cloud Messaging for Android). If our main API threads wait for Apple to respond, the entire game will lag.

Furthermore, Apple and Google are considered "untrusted" third parties under HIPAA and the DPDP Act. We cannot send Protected Health Information (PHI) through their servers.

To solve both issues, the backend utilizes an **Asynchronous Dual-Stream Dispatcher** powered by a message broker (e.g., Celery, RQ, or AWS SQS) and distinct worker nodes.

### 2. The Message Queue Infrastructure (Worker Nodes)

When an event occurs that requires a notification (e.g., a boss is defeated, or it is time to take medication), the core APIs do not send the push.

* **The Enqueue Process:** The `game_service` or `health_service` simply drops a JSON job into a Redis-backed queue: `{"user_id": 123, "type": "HEALTH_REMINDER", "trigger": "MED_01"}`. This takes less than a millisecond, freeing the API to handle the next player.
* **The Background Workers:** A fleet of dedicated Notification Worker containers constantly listens to this queue. When a job appears, the worker pulls the user's device token from the database, formats the payload according to iOS or Android standards, and handles the slow HTTP request to APNs/FCM.
* **Retry Logic & Dead Letter Queues:** If FCM is down or the user's phone is off the network, the worker utilizes exponential backoff to retry the send. If it fails permanently, the job is moved to a Dead Letter Queue for monitoring, ensuring the main game loop remains completely unaffected.

### 3. Stream A: The Secure Health Stream (PHI-Free Payloads)

This stream originates from the `health_service`. It is strictly used for clinical compliance (medication reminders, glucose logging prompts, telehealth appointment alerts).

* **The Clean Payload Rule:** The worker node *never* constructs a human-readable string containing medical context.
* **Opaque Trigger Codes:** The payload sent to Apple/Google looks like this:
`{"aps": {"content-available": 1}, "data": {"vitalquest_trigger": "MED_REMINDER_8AM"}}`
* **Local Decryption:** This is a "silent" push notification. It wakes up the VitalQuest app in the background. The mobile app contains a secure, local mapping dictionary. The app sees `MED_REMINDER_8AM`, looks up what that means locally, and the *device OS* generates the physical banner: "Time to log your morning stats!" No medical data ever crossed the open internet.

### 4. Stream B: The Game Engagement Stream (Standard Payloads)

This stream originates from the `game_service`. It handles standard retention loops (Mana full, Sanctuary upgrades complete, Guild Boss attacks).

* **Standard Routing:** Because these notifications contain no medical data, they follow standard mobile development practices.
* **Rich Media:** The worker node constructs a full, human-readable payload:
`{"aps": {"alert": {"title": "The Sloth Demon Attacks!", "body": "Your guild needs you. Log in to defend the Sanctuary!"}, "sound": "battle_horn.aiff"}}`
* **Badge Management:** The worker also calculates and pushes the unread badge count (the little red number on the app icon) so the user knows they have unspent Mana or unread safe-chat messages waiting for them.

---