import { Platform } from 'react-native';
import { VitalQuestStandardPayload } from '../../types';

// ─── Hardware Abstraction Layer ───────────────────────────────────────────────
// The app ALWAYS calls these functions. The HAL dynamically routes to the
// correct implementation based on Platform.OS:
//
//   • iOS / Android → mobileHardware  (real HealthKit / Google Fit SDKs)
//   • web           → webMockHardware (Dev Panel injection engine)
//
// This prevents any native SDK import from ever being evaluated in Chrome,
// which would crash the app with "Cannot find module 'react-native-health'".

export interface HardwareCapabilities {
  supportsSteps: boolean;
  supportsBloodGlucose: boolean;
  supportsHeartRate: boolean;
  supportsSleep: boolean;
  isMock: boolean;
}

export interface HardwareModule {
  getCapabilities: () => HardwareCapabilities;
  requestPermissions: () => Promise<boolean>;
  syncSteps: () => Promise<VitalQuestStandardPayload | null>;
  syncBloodGlucose: () => Promise<VitalQuestStandardPayload | null>;
  syncMedication: (taken: boolean) => Promise<VitalQuestStandardPayload>;
  syncDiet: () => Promise<VitalQuestStandardPayload>;
  // Returns a payload signed by the device enclave (mobile only).
  // Web mock returns a payload without hardware_signature.
  buildPayload: (
    data: Partial<VitalQuestStandardPayload>,
  ) => Promise<VitalQuestStandardPayload>;
}

// Lazy-loaded so that native modules are never evaluated on web
let _hal: HardwareModule | null = null;

export async function getHAL(): Promise<HardwareModule> {
  if (_hal) return _hal;

  if (Platform.OS === 'web') {
    const mod = await import('./webMockHardware');
    _hal = mod.webMockHardware;
  } else {
    const mod = await import('./mobileHardware');
    _hal = mod.mobileHardware;
  }

  return _hal;
}

// Convenience re-exports for direct use in components
export const Hardware = {
  syncSteps: async () => (await getHAL()).syncSteps(),
  syncBloodGlucose: async () => (await getHAL()).syncBloodGlucose(),
  syncMedication: async (taken: boolean) => (await getHAL()).syncMedication(taken),
  syncDiet: async () => (await getHAL()).syncDiet(),
  buildPayload: async (data: Partial<VitalQuestStandardPayload>) =>
    (await getHAL()).buildPayload(data),
  getCapabilities: () => {
    if (Platform.OS === 'web') {
      return {
        supportsSteps: false,
        supportsBloodGlucose: false,
        supportsHeartRate: false,
        supportsSleep: false,
        isMock: true,
      };
    }
    return {
      supportsSteps: true,
      supportsBloodGlucose: true,
      supportsHeartRate: true,
      supportsSleep: true,
      isMock: false,
    };
  },
};
