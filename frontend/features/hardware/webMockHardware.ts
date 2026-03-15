import { v4 as uuidv4 } from 'uuid';
import { HardwareModule, HardwareCapabilities } from './hal';
import { VitalQuestStandardPayload } from '../../types';

// ─── Web Mock Hardware ────────────────────────────────────────────────────────
// This module is ONLY ever loaded when Platform.OS === 'web'.
// It provides the same interface as mobileHardware but generates synthetic
// payloads that match the exact shape the backend adapters expect.
//
// The Dev Panel component (components/DevMockPanel.tsx) calls these functions
// when the user clicks a mock button, effectively "tricking" the backend into
// thinking a real device synced.

// In-memory mock values — updated by the Dev Panel via the mockStore below
export interface MockStore {
  steps: number;
  bloodGlucose: number;
  heartRate: number;
  sleepHours: number;
}

let mockStore: MockStore = {
  steps: 0,
  bloodGlucose: 100,
  heartRate: 72,
  sleepHours: 7,
};

export function updateMockStore(partial: Partial<MockStore>) {
  mockStore = { ...mockStore, ...partial };
}

export function getMockStore(): MockStore {
  return { ...mockStore };
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function nowISO(): string {
  return new Date().toISOString();
}

function basePayload(
  overrides: Partial<VitalQuestStandardPayload>,
): VitalQuestStandardPayload {
  return {
    idempotency_key: uuidv4(),
    source: 'MANUAL_WEB',
    recorded_at: nowISO(),
    ...overrides,
  };
}

// ─── Module Implementation ────────────────────────────────────────────────────

const capabilities: HardwareCapabilities = {
  supportsSteps: false,
  supportsBloodGlucose: false,
  supportsHeartRate: false,
  supportsSleep: false,
  isMock: true,
};

export const webMockHardware: HardwareModule = {
  getCapabilities: () => capabilities,

  requestPermissions: async () => true, // No-op on web

  syncSteps: async () =>
    basePayload({ steps: mockStore.steps }),

  syncBloodGlucose: async () =>
    basePayload({ blood_glucose_mg_dl: mockStore.bloodGlucose }),

  syncMedication: async (taken: boolean) =>
    basePayload({ medication_taken: taken }),

  syncDiet: async () =>
    basePayload({ diet_logged: true }),

  buildPayload: async (data) => basePayload(data),
};
