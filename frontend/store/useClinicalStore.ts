import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { AppState, AppStateStatus } from 'react-native';
import { DailyGoals, TodayProgress, VitalQuestStandardPayload } from '../types';

// ─── Offline Queue Entry ──────────────────────────────────────────────────────

export interface OfflineQueueEntry {
  id: string;                       // UUID – used as idempotency_key on replay
  payload: VitalQuestStandardPayload;
  queuedAt: string;                 // ISO UTC
}

// ─── State Shape ──────────────────────────────────────────────────────────────
// Volatile store: clears on app-background to ensure PHI isn't left in RAM.
// Persisted offline queue survives app restarts (the payloads are non-PHI game
// data, not raw biometric records).

interface ClinicalState {
  dailyGoals: DailyGoals;
  todayProgress: TodayProgress;
  offlineQueue: OfflineQueueEntry[];
  isQueueLocked: boolean;           // Prevents race conditions during sync

  // Actions
  setDailyGoals: (goals: DailyGoals) => void;
  setTodayProgress: (progress: TodayProgress) => void;
  enqueueOffline: (entry: OfflineQueueEntry) => void;
  dequeueOffline: (id: string) => void;
  lockQueue: () => void;
  unlockQueue: () => void;
  clearSensitiveData: () => void;   // Called on app-background
}

const DEFAULT_GOALS: DailyGoals = {
  targetSteps: 5000,
  medicationRequired: false,
};

const DEFAULT_PROGRESS: TodayProgress = {
  currentSteps: 0,
  medicationLogged: false,
  lastSyncComplete: null,
};

export const useClinicalStore = create<ClinicalState>()(
  persist(
    (set) => ({
      dailyGoals: DEFAULT_GOALS,
      todayProgress: DEFAULT_PROGRESS,
      offlineQueue: [],
      isQueueLocked: false,

      setDailyGoals: (dailyGoals) => set({ dailyGoals }),

      setTodayProgress: (todayProgress) => set({ todayProgress }),

      enqueueOffline: (entry) =>
        set((state) => ({
          offlineQueue: [...state.offlineQueue, entry],
        })),

      dequeueOffline: (id) =>
        set((state) => ({
          offlineQueue: state.offlineQueue.filter((e) => e.id !== id),
        })),

      lockQueue: () => set({ isQueueLocked: true }),
      unlockQueue: () => set({ isQueueLocked: false }),

      // Wipes in-memory sensitive daily progress when the user backgrounds the app.
      // The offline queue is intentionally preserved — it holds payloads awaiting
      // delivery, not displayed health values.
      clearSensitiveData: () =>
        set({
          todayProgress: DEFAULT_PROGRESS,
        }),
    }),
    {
      name: 'vq-clinical-store',
      storage: createJSONStorage(() => AsyncStorage),
      // Only persist the offline queue — daily progress is re-fetched on foreground
      partialize: (state) => ({
        offlineQueue: state.offlineQueue,
        dailyGoals: state.dailyGoals,
      }),
    },
  ),
);

// ─── PHI Auto-Clear on Background ────────────────────────────────────────────
// Register once at module level. When the app goes to background, wipe the
// sensitive in-memory progress so it isn't left in the device's RAM.

let _appStateSubscription: ReturnType<typeof AppState.addEventListener> | null = null;

export function registerClinicalStoreAppStateListener() {
  if (_appStateSubscription) return; // Already registered

  _appStateSubscription = AppState.addEventListener(
    'change',
    (nextState: AppStateStatus) => {
      if (nextState === 'background' || nextState === 'inactive') {
        useClinicalStore.getState().clearSensitiveData();
      }
    },
  );
}
