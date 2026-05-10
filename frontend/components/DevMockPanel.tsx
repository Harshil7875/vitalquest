import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  TextInput,
  Platform,
} from 'react-native';
import { v4 as uuidv4 } from 'uuid';
import { useTheme } from '../theme/ThemeProvider';
import { useSyncHealthMutation } from '../services/api/hooks';
import { updateMockStore, getMockStore } from '../features/hardware/webMockHardware';
import type { VitalQuestStandardPayload } from '../types';

// ─── Dev Mock Panel ───────────────────────────────────────────────────────────
// Only mounts when Platform.OS === 'web'.
// Fixed to the right 30% of the viewport on desktop.
// Allows developers to inject synthetic health payloads into the backend
// without physical hardware, testing the entire game economy loop locally.

function SliderRow({
  label,
  min,
  max,
  value,
  onChange,
  color,
}: {
  label: string;
  min: number;
  max: number;
  value: number;
  onChange: (v: number) => void;
  color: string;
}) {
  const { theme } = useTheme();

  // Web uses <input type="range"> inside RN Web
  return (
    <View style={styles.sliderRow}>
      <View style={styles.sliderHeader}>
        <Text style={[styles.sliderLabel, { color: theme.colors.textSecondary }]}>
          {label}
        </Text>
        <Text style={[styles.sliderValue, { color }]}>{value}</Text>
      </View>
      {Platform.OS === 'web' && (
        // @ts-ignore — web-only element
        <input
          type="range"
          min={min}
          max={max}
          value={value}
          style={{ width: '100%', accentColor: color }}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            onChange(Number(e.target.value))
          }
        />
      )}
    </View>
  );
}

export function DevMockPanel() {
  const { theme } = useTheme();
  const syncMutation = useSyncHealthMutation();

  const [steps, setSteps] = useState(getMockStore().steps);
  const [glucose, setGlucose] = useState(getMockStore().bloodGlucose);
  const [lastResult, setLastResult] = useState<string | null>(null);

  // Phase 13 / fix #7 — never render in production builds, even on web.
  // Without this gate the prod web bundle ships a panel that lets any
  // visitor inject synthetic biometrics into the live backend, distorting
  // the Mana economy and clinical sync state.
  if (Platform.OS !== 'web' || !__DEV__) return null;

  const sync = async (payload: Omit<VitalQuestStandardPayload, 'idempotency_key' | 'recorded_at' | 'source'>) => {
    const full: VitalQuestStandardPayload = {
      idempotency_key: uuidv4(),
      source: 'MANUAL_WEB',
      recorded_at: new Date().toISOString(),
      ...payload,
    };
    try {
      const res = await syncMutation.mutateAsync(full);
      setLastResult(`✓ ${res.status} · +${res.mana_awarded} Mana`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      setLastResult(`✗ ${msg}`);
    }
  };

  const handleStepsChange = (v: number) => {
    setSteps(v);
    updateMockStore({ steps: v });
  };

  const handleGlucoseChange = (v: number) => {
    setGlucose(v);
    updateMockStore({ bloodGlucose: v });
  };

  const isSyncing = syncMutation.isPending;

  return (
    <View
      style={[
        styles.panel,
        {
          backgroundColor: theme.colors.surface,
          borderLeftColor: theme.colors.border,
        },
      ]}
    >
      {/* Header */}
      <View
        style={[styles.header, { borderBottomColor: theme.colors.border }]}
      >
        <Text style={[styles.headerTitle, { color: theme.colors.primary }]}>
          Dev Mock Panel
        </Text>
        <View
          style={[styles.badge, { backgroundColor: theme.colors.warning + '33' }]}
        >
          <Text style={[styles.badgeText, { color: theme.colors.warning }]}>
            WEB SANDBOX
          </Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>

        {/* Steps Simulator */}
        <View style={[styles.section, { borderColor: theme.colors.border }]}>
          <Text style={[styles.sectionTitle, { color: theme.colors.textPrimary }]}>
            Step Count
          </Text>
          <SliderRow
            label="Daily steps"
            min={0}
            max={20000}
            value={steps}
            onChange={handleStepsChange}
            color={theme.colors.secondary}
          />
          <MockButton
            label={`Sync ${steps.toLocaleString()} Steps`}
            color={theme.colors.secondary}
            loading={isSyncing}
            onPress={() => sync({ steps })}
          />
        </View>

        {/* Blood Glucose Simulator */}
        <View style={[styles.section, { borderColor: theme.colors.border }]}>
          <Text style={[styles.sectionTitle, { color: theme.colors.textPrimary }]}>
            Blood Glucose (mg/dL)
          </Text>
          <SliderRow
            label="BG level"
            min={40}
            max={400}
            value={glucose}
            onChange={handleGlucoseChange}
            color={glucoseColour(glucose, theme.colors)}
          />
          <View style={styles.glucoseLabels}>
            <Text style={[styles.glucoseZone, { color: theme.colors.danger }]}>Low &lt;70</Text>
            <Text style={[styles.glucoseZone, { color: theme.colors.success }]}>OK 70–180</Text>
            <Text style={[styles.glucoseZone, { color: theme.colors.warning }]}>High &gt;180</Text>
          </View>
          <MockButton
            label={`Sync BG: ${glucose} mg/dL`}
            color={glucoseColour(glucose, theme.colors)}
            loading={isSyncing}
            onPress={() => sync({ blood_glucose_mg_dl: glucose })}
          />
        </View>

        {/* Quick Actions */}
        <View style={[styles.section, { borderColor: theme.colors.border }]}>
          <Text style={[styles.sectionTitle, { color: theme.colors.textPrimary }]}>
            Quick Actions
          </Text>
          <MockButton
            label="Log Medication ✓"
            color={theme.colors.accent}
            loading={isSyncing}
            onPress={() => sync({ medication_taken: true })}
          />
          <MockButton
            label="Log Diet ✓"
            color={theme.colors.primary}
            loading={isSyncing}
            onPress={() => sync({ diet_logged: true })}
          />
          <MockButton
            label="Simulate 5,000 Steps"
            color={theme.colors.secondary}
            loading={isSyncing}
            onPress={() => { handleStepsChange(5000); sync({ steps: 5000 }); }}
          />
          <MockButton
            label="Trigger Dexcom High Alert (250)"
            color={theme.colors.danger}
            loading={isSyncing}
            onPress={() => { handleGlucoseChange(250); sync({ blood_glucose_mg_dl: 250 }); }}
          />
        </View>

        {/* Last Result */}
        {lastResult && (
          <View
            style={[
              styles.resultBanner,
              {
                backgroundColor: lastResult.startsWith('✓')
                  ? theme.colors.success + '22'
                  : theme.colors.danger + '22',
              },
            ]}
          >
            <Text
              style={{
                color: lastResult.startsWith('✓')
                  ? theme.colors.success
                  : theme.colors.danger,
                fontFamily: theme.typography.fontMono,
                fontSize: theme.typography.sizeSm,
              }}
            >
              {lastResult}
            </Text>
          </View>
        )}
      </ScrollView>
    </View>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function MockButton({
  label,
  color,
  loading,
  onPress,
}: {
  label: string;
  color: string;
  loading: boolean;
  onPress: () => void;
}) {
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={loading}
      style={[
        styles.mockButton,
        { backgroundColor: color + '22', borderColor: color + '66' },
        loading && styles.mockButtonDisabled,
      ]}
    >
      <Text style={[styles.mockButtonText, { color }]}>
        {loading ? 'Syncing…' : label}
      </Text>
    </TouchableOpacity>
  );
}

function glucoseColour(
  value: number,
  colors: { danger: string; success: string; warning: string },
): string {
  if (value < 70) return colors.danger;
  if (value > 180) return colors.warning;
  return colors.success;
}

const styles = StyleSheet.create({
  panel: {
    width: '30%',
    maxWidth: 320,
    minWidth: 240,
    height: '100%',
    borderLeftWidth: 1,
  },
  header: {
    padding: 12,
    borderBottomWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerTitle: {
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  badge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  badgeText: {
    fontSize: 9,
    fontWeight: '800',
    letterSpacing: 1,
  },
  scroll: {
    padding: 12,
    gap: 12,
  },
  section: {
    borderWidth: 1,
    borderRadius: 8,
    padding: 10,
    gap: 8,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.3,
    marginBottom: 2,
  },
  sliderRow: {
    gap: 4,
  },
  sliderHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  sliderLabel: {
    fontSize: 11,
  },
  sliderValue: {
    fontSize: 12,
    fontWeight: '700',
  },
  glucoseLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  glucoseZone: {
    fontSize: 9,
    fontWeight: '600',
  },
  mockButton: {
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 6,
    borderWidth: 1,
    alignItems: 'center',
  },
  mockButtonDisabled: {
    opacity: 0.5,
  },
  mockButtonText: {
    fontSize: 12,
    fontWeight: '600',
  },
  resultBanner: {
    padding: 10,
    borderRadius: 6,
    alignItems: 'center',
  },
});
