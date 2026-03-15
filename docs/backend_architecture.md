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