## Architecture Document: Cross-Platform Frontend & UX Strategy

**Project:** VitalQuest

**Version:** 2.0.0

**Focus:** Universal Codebase, Web-Environment Mocking, State Management, and UI Routing

### 1. The Unified Tech Stack (The "Write Once, Run Everywhere" Model)

To maintain a single codebase for iOS, Android, and Chrome, VitalQuest utilizes a universal framework rather than siloed native repositories.

* **Core Framework:** **Expo (React Native Web).** Expo allows the exact same React components to render as native Swift views on iOS, Kotlin views on Android, and standard DOM elements (HTML/CSS) in a Chrome browser.
* **The Game Renderer:** Standard DOM elements are too heavy for game rendering. The app utilizes **React Native Skia** or a lightweight 2D canvas wrapper. This ensures the Sanctuary and Avatar animations run at 60 FPS natively on mobile and compile perfectly to WebGL/Canvas on Chrome.
* **Network Layer:** **React Query (TanStack Query).** This handles all API communication with our backend, automatically managing loading states, retries, and local caching of the Game State and Health logs.

### 2. The Hardware Dilemma: The "Dev-Mock" Architecture

Because the web app cannot access the secure health enclaves of a smartphone, the frontend codebase must dynamically detect its environment and switch data ingestion modes.

* **Environment Detection:** The app runs a global check on boot: `Platform.OS === 'web'`.
* **Mobile Mode (Production):** If iOS/Android, the app invokes the actual native SDKs (e.g., `react-native-health`) to pull real biometric data and package it for the `health_service`.
* **Web Mode (The Sandbox):** If Chrome, the app disables native SDK calls and exposes a hidden "Developer Panel." This panel allows you to manually input mock data (e.g., clicking a button that says "Simulate 5,000 Steps" or "Trigger Dexcom High Alert").
* **The Webhook Bridge:** When a mock button is pressed on the web app, it formats a payload identical to the `VitalQuestStandardPayload` we defined in the backend adapters and fires it to the API Gateway, tricking the server into thinking a real device synced.

### 3. UI/UX Routing: The "Dual-Persona" Interface

VitalQuest is two apps in one: a vibrant game and a sterile medical tool. The navigation architecture must separate these personas so they don't bleed into each other.

* **The Primary View (The Sanctuary):** This is the default, gamified landing screen. It features rich colors, the user's Avatar, 2D/3D building layouts, the Mana inventory, and the Guild Chat slide-out.
* **The Hard Toggle (Doctor Mode):** Accessible via a secure biometric prompt (FaceID/TouchID on mobile, or password on web) to prevent casual viewing of medical data.
* **The Clinical Dashboard:** Once toggled, the entire UI theme changes. Game assets disappear. The color palette shifts to clean whites and blues. The Mana inventory is replaced by interactive charts of A1C trends, medication adherence graphs, and the PDF export generator.
* **Responsive Web Boundaries:** Because mobile is portrait-first and web is landscape, the Chrome web app runs in a "constrained container" (a mobile-width column in the center of the screen) to ensure UI components don't stretch and break during local testing, while utilizing the extra horizontal space for the Developer Panel.

### 4. State Management & Offline Resilience

Chronic illness does not pause when a user loses cell service. The frontend must cache the game state locally so the user can still log their health data offline.

* **Local Storage:** The app utilizes `Zustand` for global state management, persisted to local storage (`AsyncStorage` on mobile, `localStorage` on Chrome).
* **The Action Queue:** If a user logs their medication while offline, the frontend does not crash. It pushes the action to an offline queue.
* **Idempotent Syncing:** Once the network returns, the frontend empties the queue, sending the payloads to the backend. Because we built idempotency into our `reward_processor.py` and backend logic, duplicate sync attempts caused by spotty Wi-Fi will never result in double Mana.

---

## Architecture Document: Universal Frontend Client

**Project:** VitalQuest

**Version:** 2.1.0

**Focus:** Expo Cross-Platform Implementation, State Management, and Environment Mocking

### 1. Core Technologies & Frameworks

To achieve a "Write Once, Run Everywhere" deployment (iOS, Android, and Chrome Web App), the frontend relies on a specific combination of React Native ecosystem tools.

| Layer | Technology | Justification |
| --- | --- | --- |
| **Framework** | Expo (React Native Web) | Compiles to native mobile views and standard web DOM simultaneously. |
| **Routing** | Expo Router (File-based) | Handles deep linking and secure auth-gating natively across all platforms. |
| **State Management** | Zustand | Lightweight, unopinionated client state (Mana balance, UI toggles). |
| **Data Fetching** | TanStack Query (React Query) | Manages server-state, API caching, automatic retries, and offline queuing. |
| **Game Rendering** | React Native Skia | High-performance 2D rendering for the Sanctuary and Avatars that compiles perfectly to WebGL on Chrome. |

### 2. Directory Architecture & Modular Design

To prevent the "Game" UI from bleeding into the "Clinical" UI, the repository enforces a strict feature-based folder structure.

* `app/` (Expo Router layout)
* `(game)/` (The Sanctuary, Guilds, Avatar customization)
* `(clinical)/` (Auth-gated dashboards, doctor export tools)


* `features/`
* `/auth` (JWT handling, Biometric login prompts)
* `/hardware` (The abstraction layer for HealthKit / Google Fit / Web Mock)


* `services/`
* `/api` (TanStack Query hooks mapped to our backend endpoints)


* `store/` (Zustand state slices)
* `components/` (Shared UI like buttons and modals)

### 3. Hardware Abstraction & The Web "Dev-Mock" Engine

The app must not crash when loaded in Chrome where Apple HealthKit and Google Fit do not exist. The frontend utilizes a **Hardware Abstraction Layer (HAL)**.

* **The Interface:** The app calls a unified function: `Hardware.syncSteps()`.
* **Mobile Execution:** If `Platform.OS !== 'web'`, the HAL triggers the native SDKs, reads the device's secure enclave, signs the payload, and sends it to the backend `health_service`.
* **Web Execution (The Sandbox):** If `Platform.OS === 'web'`, the HAL bypasses native calls. Instead, it renders a persistent **Developer Control Panel** fixed to the right side of the desktop screen.
* **The Dev Panel:** This UI contains buttons and sliders (e.g., "Set Blood Glucose to 110", "Simulate 5,000 Steps"). When clicked, the HAL formats these inputs into the exact JSON shape the backend adapters expect, allowing you to test the entire game economy locally without taking a single physical step.

### 4. UI/UX Routing: The Dual-Persona Interface

The app acts as a game 90% of the time, and a medical tool 10% of the time. The transition must be seamless but secure.

* **The Web Container:** On desktop browsers, the primary app renders inside a constrained, mobile-proportioned container (e.g., 428px wide) centered on the screen. This ensures UI elements do not stretch or break during local testing.
* **The Default State (`/sanctuary`):** Bright color palettes, Skia-rendered animations, floating Mana indicators, and gamified typography.
* **The Clinical Toggle (`/clinical`):** Accessed via a sliding drawer or profile menu. Navigating to this route triggers a local biometric prompt (FaceID/TouchID) or PIN entry.
* **The Clinical State:** The Skia canvas unmounts. The UI switches to a minimalist, high-contrast theme (whites, deep blues). Standard data-visualization charts (e.g., Victory Native or React Native SVG) replace game assets, displaying raw A1C trends and medication adherence graphs.

### 5. Offline Resilience & Optimistic Updates

Because medical tracking must be reliable, the frontend cannot fail if the user is in a subway or out of cell range.

* **The Offline Queue:** If a user manually logs their medication while offline, TanStack Query catches the network failure. It pushes the `POST /api/health/sync` request into an offline mutation queue persisted in local storage.
* **Optimistic UI:** The Zustand store immediately updates the user's local Mana balance and triggers the reward animation on the screen. The user feels the dopamine hit instantly, unaware of the network failure.
* **Background Sync:** Once the network is restored, the queue flushes the payloads to the backend. The backend's idempotency keys ensure that if a request was duplicated during the reconnect, the user is not double-charged or double-rewarded. The server-authoritative state silently overwrites the local Zustand state to ensure perfect alignment.

---

## Architecture Document: Frontend State Models & API Integration

**Project:** VitalQuest

**Version:** 2.2.0

**Focus:** Zustand Store Schemas, TanStack Query Hooks, and Offline-First Mutations

### 1. Architectural Strategy: The "Mirrored Air-Gap"

Just as the backend physically separates the Health DB from the Game DB, the frontend must logically separate its state management. If we mix medical data and game inventory into a single global state object, an accidental `console.log()` or a bug in a game component could expose raw Protected Health Information (PHI).

We achieve this by utilizing two entirely independent Zustand stores:

1. `useGameStore`: Manages non-sensitive UI rendering (Mana, Avatar, Base-building).
2. `useClinicalStore`: Manages highly sensitive data, requiring biometric re-authentication to even mount the components that consume it.

### 2. Local State Data Models (Zustand)

Below are the exact TypeScript interfaces/JSON schemas the frontend will use to cache data locally.

**The Game State Schema (`useGameStore`)**
This data is safe to hold in standard memory and dictates what the Skia game engine renders.

```typescript
interface GameState {
  user: {
    avatarLevel: number;
    totalMana: number;
    astralGems: number;
  };
  sanctuary: {
    buildings: Array<{
      id: string;
      type: "APOTHECARY" | "TOWER" | "GARDEN";
      tier: number;
      isUpgrading: boolean;
      completesAt: string | null; // ISO UTC string
    }>;
  };
  guild: {
    guildId: string | null;
    guildName: string | null;
    activeBossId: string | null;
  };
  // Optimistic UI updates are applied here before the server confirms
  optimisticAddMana: (amount: number) => void; 
}

```

**The Clinical State Schema (`useClinicalStore`)**
This store is volatile. It clears itself from memory when the user backgrounds the app, ensuring PHI isn't left hanging in the device's RAM.

```typescript
interface ClinicalState {
  dailyGoals: {
    targetSteps: number;
    medicationRequired: boolean;
  };
  todayProgress: {
    currentSteps: number;
    medicationLogged: boolean;
    lastSyncComplete: string | null; // ISO UTC string
  };
  // Holds the exact payloads waiting for network connection
  offlineQueue: Array<{
    id: string; // UUID for idempotency
    payload: VitalQuestStandardPayload;
    queuedAt: string;
  }>;
}

```

### 3. The API Integration Layer (TanStack Query)

The frontend uses React Query (TanStack Query) to interface with the backend services you built. This handles all the heavy lifting for caching, background refetching, and error handling.

Here is the exact hook mapping to the backend API routes:

| Frontend Hook | Backend Endpoint | Operational Logic |
| --- | --- | --- |
| **`useSyncHealthMutation()`** | `POST /api/health/sync` | Pushes the `VitalQuestStandardPayload`. If offline, intercepts the failure and pushes to `ClinicalState.offlineQueue`. Upon success, checks response for `gameUpdate` and triggers `useGameStore.optimisticAddMana()`. |
| **`useGameStateQuery()`** | `GET /api/game/state` | Fetches the authoritative game inventory on app boot. Overwrites local `useGameStore` to correct any client-side desynchronization. |
| **`useUpgradeBuildingMutation()`** | `POST /api/game/action/upgrade` | Sends Intent + Idempotency Key. Triggers optimistic UI update (deducts Mana locally immediately). Reverts UI if the server returns a 400 (e.g., insufficient funds). |
| **`useGuildChatQuery()`** | `GET /api/game/guilds/{id}/chat` | Polls every 5 seconds (or uses WebSockets) to fetch the ephemeral, PHI-scrubbed chat history. |
| **`useExportClinicalQuery()`** | `GET /api/clinical/export` | Strictly gated behind the Pro subscription check. Fetches the decrypted JSON/PDF stream for the doctor. |

### 4. The Offline-First Sync Cycle

When the device detects a transition from Offline to Online (`NetInfo.addEventListener` in React Native), the following sequence executes to ensure no health data is lost and no game economy rules are broken:

1. **Network Restored:** The app detects Wi-Fi or Cellular connection.
2. **Queue Lock:** The `useClinicalStore` locks the `offlineQueue` to prevent race conditions.
3. **Batch Dispatch:** The app iterates through the queue, firing the payloads to `POST /api/health/sync` one by one, utilizing the UUIDs generated at the exact time of the offline action.
4. **Server Processing:** The backend's `anti_cheat.py` validates the timestamps (ensuring the data is historically accurate, not spoofed). The `reward_processor.py` processes the idempotency keys to ensure it hasn't seen this UUID before.
5. **State Reconciliation:** The backend returns the total Mana earned from the batch. TanStack Query invalidates the local cache, triggers a fresh `useGameStateQuery()`, and the user's Mana jumps up accurately.

---

## Architecture Document: UI Component Architecture & Design System

**Project:** VitalQuest

**Version:** 2.3.0

**Focus:** Design Tokens, Component Hierarchy, Skia Integration, and Dev-Mock Rendering

### 1. Architectural Strategy: The Dual-Theme Design System

Because VitalQuest shifts between a vibrant RPG and a sterile clinical tool, hardcoding colors into components will create a maintenance nightmare. The UI relies on a strict **Design Token System** managed via a `ThemeProvider` (e.g., using Restyle or NativeWind).

The system maintains two distinct themes that the app toggles between based on the active routing state:

| Token Category | Game Theme (`/sanctuary`) | Clinical Theme (`/clinical`) |
| --- | --- | --- |
| **Primary Palette** | Fantasy tones: Deep Emerald, Mystic Purple, Gold | Trust tones: Clinical White, Slate Grey, Trust Blue |
| **Typography** | Stylized, readable serif headers (e.g., Merriweather); chunky sans-serif numbers. | Clean, highly legible sans-serif (e.g., Inter or Roboto); monospace for medical data points. |
| **Spacing/Borders** | Organic shapes, rounded corners (`borderRadius: 16`), heavy drop shadows for depth. | Sharp, structured grids, minimal borders (`borderRadius: 4`), flat UI to maximize data density. |
| **Animations** | Bouncy spring physics, particle effects on button presses, high-energy transitions. | Linear, subtle fades. No distracting motion when viewing medical charts. |

### 2. The Component Hierarchy

The React tree is designed to prevent unnecessary re-renders, separating the heavy game canvas from the standard UI overlays.

* **`AppNavigator` (Root)**
* **`DevMockPanel`**: (Only mounts if `Platform.OS === 'web'`). Fixed to the right 30% of the viewport.
* **`MainContainer`**: (Constrained to 428px max-width on the web to mimic a phone screen; 100% width on mobile).
* **`HeaderBar`**: Displays Avatar Level and Mana (Game Mode) or Patient Name and Sync Status (Clinical Mode).
* **`CanvasLayer`**: The React Native Skia environment. This is where the Sanctuary base-building and Avatars live. It sits at the absolute bottom of the z-index.
* **`UILayer`**: Standard React Native components (Views, Text, ScrollViews) layered over the canvas. This holds the interactive menus, the Guild Chat drawer, and the upgrade modals.


### 3. The React Native Skia Integration (Game View)

Rendering a town builder with standard React `<View>` components will cause the app to drop frames instantly. We isolate the game graphics to the `CanvasLayer` using React Native Skia.

* **Declarative Graphics:** The Sanctuary is rendered as a single `<Canvas>` element. The buildings and avatars are drawn using Skia's `<Image>`, `<Circle>`, and `<Path>` primitives.
* **Shared Values (Reanimated):** To animate the game (e.g., an Avatar walking, or a building constructing), we use `react-native-reanimated` shared values tied directly to Skia. This pushes all animation math to the native UI thread, entirely bypassing the React JavaScript bridge, ensuring a locked 60 FPS on mobile devices.
* **Touch Handling:** Skia canvas interactions are handled via Skia's native gesture system. When a user taps a building, the canvas calculates the intersection of the tap coordinates with the building's bounding box and triggers the React UI overlay (e.g., opening the "Upgrade Building" modal).

### 4. The Web "Dev-Mock" Panel Rendering

The Dev-Mock panel is the secret weapon for building this app locally. It renders entirely outside the mobile boundaries on a desktop browser.

* **Layout:** Using standard CSS Flexbox, the screen splits: the center column is the app, and the right column is the `DevMockPanel`.
* **The Injection Engine:** The panel contains a series of form inputs mimicking the native hardware APIs.
* *Example Component:* `<StepSimulator />` features a slider from 0 to 10,000 steps and a "Sync" button.
* *The Action:* Clicking "Sync" formats the data into the exact `VitalQuestStandardPayload` expected by our backend adapters, wraps it in the user's local JWT, and fires it through TanStack Query directly to the `POST /api/health/sync` endpoint.


* **Real-Time Feedback:** Because the app is using Zustand and TanStack Query, clicking a button on the Dev-Mock panel will instantly update the Mana balance inside the mobile container on the same screen, allowing you to test the entire game loop without touching a mobile device.

---
