import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
} from 'react-native';
import { router } from 'expo-router';
import { useTheme } from '../../theme/ThemeProvider';
import { HeaderBar } from '../../components/HeaderBar';
import { useClinicalStore } from '../../store/useClinicalStore';
import { useGameStore } from '../../store/useGameStore';

// ─── Clinical Dashboard ───────────────────────────────────────────────────────
// The "sterile" view. Skia canvas is NOT rendered here.
// Theme automatically switches to clinicalTheme when mode === 'clinical'.
// Shows daily progress, goals, and offline queue status.
// Charts would use victory-native in a full build — placeholders shown here.

export default function ClinicalDashboardScreen() {
  const { theme, setMode } = useTheme();
  const { dailyGoals, todayProgress, offlineQueue } = useClinicalStore();
  const { user } = useGameStore();

  const stepsPct = Math.min(
    1,
    dailyGoals.targetSteps > 0
      ? todayProgress.currentSteps / dailyGoals.targetSteps
      : 0,
  );

  const handleExit = () => {
    setMode('game');
    router.back();
  };

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.background }]}>
      <HeaderBar onPressClinicalToggle={handleExit} />

      <ScrollView contentContainerStyle={styles.content}>
        {/* Patient identifier */}
        <View style={[styles.patientCard, { backgroundColor: theme.colors.surface, borderColor: theme.colors.border }]}>
          <View>
            <Text style={[styles.patientLabel, { color: theme.colors.textMuted }]}>
              PATIENT RECORD
            </Text>
            <Text style={[styles.patientId, { color: theme.colors.textPrimary }]}>
              Avatar Level {user.avatarLevel}
            </Text>
          </View>
          {todayProgress.lastSyncComplete ? (
            <View style={[styles.syncBadge, { backgroundColor: theme.colors.success + '22' }]}>
              <Text style={[styles.syncBadgeText, { color: theme.colors.success }]}>
                Last sync: {formatTime(todayProgress.lastSyncComplete)}
              </Text>
            </View>
          ) : (
            <View style={[styles.syncBadge, { backgroundColor: theme.colors.warning + '22' }]}>
              <Text style={[styles.syncBadgeText, { color: theme.colors.warning }]}>
                Not synced today
              </Text>
            </View>
          )}
        </View>

        {/* Offline queue alert */}
        {offlineQueue.length > 0 && (
          <View
            style={[
              styles.alertCard,
              { backgroundColor: theme.colors.warning + '18', borderColor: theme.colors.warning },
            ]}
          >
            <Text style={[styles.alertTitle, { color: theme.colors.warning }]}>
              {offlineQueue.length} log{offlineQueue.length !== 1 ? 's' : ''} queued offline
            </Text>
            <Text style={[styles.alertSub, { color: theme.colors.textSecondary }]}>
              Data will sync automatically when connection is restored.
            </Text>
          </View>
        )}

        {/* Today's Goals */}
        <View style={[styles.section, { backgroundColor: theme.colors.surface, borderColor: theme.colors.border }]}>
          <Text style={[styles.sectionTitle, { color: theme.colors.textPrimary }]}>
            Today's Goals
          </Text>

          {/* Steps */}
          <View style={styles.goalRow}>
            <View style={styles.goalInfo}>
              <Text style={[styles.goalName, { color: theme.colors.textPrimary }]}>
                Daily Steps
              </Text>
              <Text style={[styles.goalProgress, { color: theme.colors.textSecondary }]}>
                {todayProgress.currentSteps.toLocaleString()} / {dailyGoals.targetSteps.toLocaleString()}
              </Text>
            </View>
            <View style={[styles.goalTrack, { backgroundColor: theme.colors.surfaceAlt }]}>
              <View
                style={[
                  styles.goalFill,
                  {
                    backgroundColor:
                      stepsPct >= 1 ? theme.colors.success : theme.colors.primary,
                    width: `${Math.round(stepsPct * 100)}%` as unknown as number,
                  },
                ]}
              />
            </View>
            <Text style={[styles.goalPct, { color: theme.colors.textMuted }]}>
              {Math.round(stepsPct * 100)}%
            </Text>
          </View>

          {/* Medication */}
          {dailyGoals.medicationRequired && (
            <View style={styles.goalRow}>
              <View style={styles.goalInfo}>
                <Text style={[styles.goalName, { color: theme.colors.textPrimary }]}>
                  Medication
                </Text>
                <Text
                  style={[
                    styles.goalProgress,
                    {
                      color: todayProgress.medicationLogged
                        ? theme.colors.success
                        : theme.colors.danger,
                    },
                  ]}
                >
                  {todayProgress.medicationLogged ? '✓ Logged' : '✗ Not logged yet'}
                </Text>
              </View>
            </View>
          )}
        </View>

        {/* Chart placeholder — replace with VictoryNative in full build */}
        <View style={[styles.chartPlaceholder, { backgroundColor: theme.colors.surface, borderColor: theme.colors.border }]}>
          <Text style={[styles.chartTitle, { color: theme.colors.textPrimary }]}>
            A1C Trend (7 days)
          </Text>
          <View style={styles.chartArea}>
            <Text style={[styles.chartComingSoon, { color: theme.colors.textMuted }]}>
              Chart visualization · VictoryNative
            </Text>
          </View>
        </View>

        {/* Export button */}
        <TouchableOpacity
          onPress={() => router.push('/(clinical)/export')}
          style={[styles.exportButton, { backgroundColor: theme.colors.primary }]}
        >
          <Text style={[styles.exportLabel, { color: theme.colors.textOnAccent }]}>
            Export Health Report (Pro)
          </Text>
        </TouchableOpacity>

        {/* Back to game */}
        <TouchableOpacity onPress={handleExit} style={styles.exitButton}>
          <Text style={[styles.exitLabel, { color: theme.colors.textMuted }]}>
            ← Return to Sanctuary
          </Text>
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  content: { padding: 16, gap: 16, paddingBottom: 48 },
  patientCard: {
    borderRadius: 10,
    borderWidth: 1,
    padding: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  patientLabel: { fontSize: 9, fontWeight: '800', letterSpacing: 1, marginBottom: 2 },
  patientId: { fontSize: 16, fontWeight: '700' },
  syncBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 6,
  },
  syncBadgeText: { fontSize: 11, fontWeight: '600' },
  alertCard: {
    borderRadius: 8,
    borderWidth: 1,
    padding: 14,
    gap: 4,
  },
  alertTitle: { fontSize: 13, fontWeight: '700' },
  alertSub: { fontSize: 12 },
  section: {
    borderRadius: 10,
    borderWidth: 1,
    padding: 16,
    gap: 14,
  },
  sectionTitle: { fontSize: 15, fontWeight: '700', marginBottom: 2 },
  goalRow: { gap: 6 },
  goalInfo: { flexDirection: 'row', justifyContent: 'space-between' },
  goalName: { fontSize: 13, fontWeight: '600' },
  goalProgress: { fontSize: 13 },
  goalTrack: { height: 6, borderRadius: 3, overflow: 'hidden' },
  goalFill: { height: '100%', borderRadius: 3 },
  goalPct: { fontSize: 11, alignSelf: 'flex-end' },
  chartPlaceholder: {
    borderRadius: 10,
    borderWidth: 1,
    padding: 16,
    gap: 10,
  },
  chartTitle: { fontSize: 14, fontWeight: '700' },
  chartArea: {
    height: 140,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 6,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#e2e8f0',
  },
  chartComingSoon: { fontSize: 12 },
  exportButton: {
    height: 50,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  exportLabel: { fontSize: 15, fontWeight: '700' },
  exitButton: { alignItems: 'center', paddingVertical: 8 },
  exitLabel: { fontSize: 14 },
});
