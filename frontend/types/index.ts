// ─── VitalQuestStandardPayload ────────────────────────────────────────────────
// The canonical payload shape sent to POST /api/health/sync.
// Mirrors the backend's VitalQuestStandardPayload Pydantic schema.

export type DataSource =
  | 'APPLE_HEALTHKIT'
  | 'GOOGLE_FIT'
  | 'DEXCOM'
  | 'OURA'
  | 'FITBIT'
  | 'MANUAL_WEB';

export interface VitalQuestStandardPayload {
  idempotency_key: string;       // UUID v4, generated at time of capture
  source: DataSource;
  recorded_at: string;           // ISO 8601 UTC
  steps?: number;
  blood_glucose_mg_dl?: number;
  medication_taken?: boolean;
  diet_logged?: boolean;
  heart_rate_bpm?: number;
  sleep_hours?: number;
  hardware_signature?: string;   // Native only – HMAC of payload signed by device
}

// ─── Game State ───────────────────────────────────────────────────────────────

export type BuildingType = 'APOTHECARY' | 'TOWER' | 'GARDEN' | 'FORGE';

export interface Building {
  id: string;
  type: BuildingType;
  tier: number;
  isUpgrading: boolean;
  completesAt: string | null; // ISO UTC
}

export interface GameUser {
  avatarLevel: number;
  totalMana: number;
  astralGems: number;
}

export interface GuildInfo {
  guildId: string | null;
  guildName: string | null;
  activeBossId: string | null;
}

export interface GameStateResponse {
  user: GameUser;
  sanctuary: {
    buildings: Building[];
  };
  guild: GuildInfo;
}

// ─── Clinical State ───────────────────────────────────────────────────────────

export interface DailyGoals {
  targetSteps: number;
  medicationRequired: boolean;
}

export interface TodayProgress {
  currentSteps: number;
  medicationLogged: boolean;
  lastSyncComplete: string | null; // ISO UTC
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

export interface AuthResponse {
  access_token: string;
  token_type: 'bearer';
  user_id: string;
}

// ─── Guild ────────────────────────────────────────────────────────────────────

export interface GuildMember {
  user_id: string;
  username: string;
  avatar_level: number;
  status: 'ACTIVE' | 'RESTING' | 'KICK_ELIGIBLE';
}

export interface GuildState {
  guild_id: string;
  name: string;
  invite_code: string;
  boss_hp_remaining: number;
  boss_hp_max: number;
  members: GuildMember[];
}

export interface ChatMessage {
  message_id: string;
  user_id: string;
  username: string;
  content: string;
  sent_at: string; // ISO UTC
}

// ─── Economy Actions ──────────────────────────────────────────────────────────

export interface UpgradeBuildingRequest {
  building_id: string;
  idempotency_key: string;
}

export interface UpgradeBuildingResponse {
  building: Building;
  mana_spent: number;
  new_mana_balance: number;
}

export interface OpenChestResponse {
  reward_type: 'MANA' | 'ASTRAL_GEMS' | 'COSMETIC';
  amount: number;
  item_id?: string;
  new_mana_balance: number;
  new_astral_gems: number;
}

export interface SkipTimerRequest {
  building_id: string;
  idempotency_key: string;
}

export interface SkipTimerResponse {
  building: Building;
  gems_spent: number;
  new_astral_gems: number;
}

// ─── Sync Response ────────────────────────────────────────────────────────────

export interface SyncHealthResponse {
  status: 'ACCEPTED' | 'DUPLICATE' | 'REJECTED';
  mana_awarded: number;
  game_update?: {
    new_mana_balance: number;
    level_up?: boolean;
    new_level?: number;
  };
}
