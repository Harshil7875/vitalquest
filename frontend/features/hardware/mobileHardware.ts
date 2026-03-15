import { v4 as uuidv4 } from 'uuid';
import { Platform } from 'react-native';
import { HardwareModule, HardwareCapabilities } from './hal';
import { VitalQuestStandardPayload } from '../../types';

// ─── Mobile Hardware ──────────────────────────────────────────────────────────
// This module is ONLY loaded on iOS/Android (never on web).
// It interfaces with HealthKit (iOS) and Health Connect (Android) via
// react-native-health / react-native-health-connect.
//
// Both packages require native linking and therefore cannot be statically
// imported at the top level — we use dynamic require() inside each function
// so that Metro can tree-shake them for the web bundle.
//
// NOTE: To use this in a real build, add to package.json:
//   "react-native-health": "^1.20.0"           (iOS HealthKit)
//   "react-native-health-connect": "^2.1.0"    (Android Health Connect)

function nowISO(): string {
  return new Date().toISOString();
}

function basePayload(
  overrides: Partial<VitalQuestStandardPayload>,
): VitalQuestStandardPayload {
  return {
    idempotency_key: uuidv4(),
    source: Platform.OS === 'ios' ? 'APPLE_HEALTHKIT' : 'GOOGLE_FIT',
    recorded_at: nowISO(),
    ...overrides,
  };
}

const capabilities: HardwareCapabilities = {
  supportsSteps: true,
  supportsBloodGlucose: Platform.OS === 'ios', // Android via Dexcom webhook only
  supportsHeartRate: true,
  supportsSleep: true,
  isMock: false,
};

export const mobileHardware: HardwareModule = {
  getCapabilities: () => capabilities,

  requestPermissions: async () => {
    if (Platform.OS === 'ios') {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const AppleHealthKit = require('react-native-health').default;
      const permissions = {
        permissions: {
          read: [
            AppleHealthKit.Constants.Permissions.StepCount,
            AppleHealthKit.Constants.Permissions.BloodGlucose,
            AppleHealthKit.Constants.Permissions.HeartRate,
            AppleHealthKit.Constants.Permissions.SleepAnalysis,
          ],
          write: [],
        },
      };
      return new Promise((resolve) =>
        AppleHealthKit.initHealthKit(permissions, (err: Error) =>
          resolve(!err),
        ),
      );
    }

    // Android: Health Connect runtime permissions
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { requestPermission } = require('react-native-health-connect');
    const granted = await requestPermission([
      { accessType: 'read', recordType: 'Steps' },
      { accessType: 'read', recordType: 'HeartRate' },
      { accessType: 'read', recordType: 'SleepSession' },
    ]);
    return granted.length > 0;
  },

  syncSteps: async () => {
    const today = new Date();
    const startOfDay = new Date(today);
    startOfDay.setHours(0, 0, 0, 0);

    if (Platform.OS === 'ios') {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const AppleHealthKit = require('react-native-health').default;
      return new Promise((resolve) =>
        AppleHealthKit.getStepCount(
          { startDate: startOfDay.toISOString() },
          (err: Error, results: { value: number }) => {
            if (err) { resolve(null); return; }
            resolve(basePayload({ steps: Math.round(results.value) }));
          },
        ),
      );
    }

    // Android
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { readRecords } = require('react-native-health-connect');
    const records = await readRecords('Steps', {
      timeRangeFilter: {
        operator: 'between',
        startTime: startOfDay.toISOString(),
        endTime: today.toISOString(),
      },
    });
    const total = records.reduce(
      (sum: number, r: { count: number }) => sum + r.count,
      0,
    );
    return basePayload({ steps: total });
  },

  syncBloodGlucose: async () => {
    if (Platform.OS !== 'ios') {
      // Android glucose data arrives via Dexcom webhook on the backend
      return null;
    }
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const AppleHealthKit = require('react-native-health').default;
    return new Promise((resolve) =>
      AppleHealthKit.getBloodGlucoseSamples(
        { limit: 1, ascending: false },
        (err: Error, results: Array<{ value: number; startDate: string }>) => {
          if (err || !results.length) { resolve(null); return; }
          const latest = results[0];
          resolve(
            basePayload({
              blood_glucose_mg_dl: latest.value,
              recorded_at: latest.startDate,
            }),
          );
        },
      ),
    );
  },

  syncMedication: async (taken: boolean) =>
    basePayload({ medication_taken: taken }),

  syncDiet: async () =>
    basePayload({ diet_logged: true }),

  buildPayload: async (data) => basePayload(data),
};
