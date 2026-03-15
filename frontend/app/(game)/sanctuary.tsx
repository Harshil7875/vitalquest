import React, { useState } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  RefreshControl,
} from 'react-native';
import { router } from 'expo-router';
import * as LocalAuthentication from 'expo-local-authentication';
import { Platform } from 'react-native';
import { useTheme } from '../../theme/ThemeProvider';
import { HeaderBar } from '../../components/HeaderBar';
import { SanctuaryCanvas } from '../../components/SanctuaryCanvas';
import { useGameStore } from '../../store/useGameStore';
import { useGameStateQuery, useSyncHealthMutation } from '../../services/api/hooks';
import { Hardware } from '../../features/hardware/hal';

export default function SanctuaryScreen() {
  const { theme, setMode } = useTheme();
  const { user, guild } = useGameStore();
  const { refetch, isRefetching } = useGameStateQuery();
  const syncMutation = useSyncHealthMutation();
  const [syncStatus, setSyncStatus] = useState<string | null>(null);

  const handleClinicalToggle = async () => {
    // Biometric prompt on mobile; skip on web (password required at the route level)
    if (Platform.OS !== 'web') {
      const result = await LocalAuthentication.authenticateAsync({
        promptMessage: 'Verify identity to access Clinical Dashboard',
        fallbackLabel: 'Use Passcode',
      });
      if (!result.success) return;
    }
    setMode('clinical');
    router.push('/(clinical)/dashboard');
  };

  const handleManualSync = async () => {
    const payload = await Hardware.syncSteps();
    if (!payload) return;
    try {
      const res = await syncMutation.mutateAsync(payload);
      setSyncStatus(`✓ Synced · +${res.mana_awarded} Mana`);
      setTimeout(() => setSyncStatus(null), 3000);
    } catch {
      setSyncStatus('✗ Sync failed — queued for retry');
      setTimeout(() => setSyncStatus(null), 3000);
    }
  };

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.background }]}>
      <HeaderBar onPressClinicalToggle={handleClinicalToggle} />

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={isRefetching}
            onRefresh={refetch}
            tintColor={theme.colors.primary}
          />
        }
      >
        {/* Sanctuary canvas — Skia-rendered game view */}
        <SanctuaryCanvas />

        {/* Mana + Gems summary bar */}
        <View style={[styles.statBar, { backgroundColor: theme.colors.surface, borderColor: theme.colors.border }]}>
          <View style={styles.statItem}>
            <Text style={[styles.statIcon, { color: theme.colors.accent }]}>✦</Text>
            <View>
              <Text style={[styles.statValue, { color: theme.colors.accent }]}>
                {user.totalMana.toLocaleString()}
              </Text>
              <Text style={[styles.statLabel, { color: theme.colors.textMuted }]}>Mana</Text>
            </View>
          </View>

          <View style={[styles.statDivider, { backgroundColor: theme.colors.border }]} />

          <View style={styles.statItem}>
            <Text style={styles.statIcon}>💎</Text>
            <View>
              <Text style={[styles.statValue, { color: theme.colors.primaryLight }]}>
                {user.astralGems.toLocaleString()}
              </Text>
              <Text style={[styles.statLabel, { color: theme.colors.textMuted }]}>
                Astral Gems
              </Text>
            </View>
          </View>

          <View style={[styles.statDivider, { backgroundColor: theme.colors.border }]} />

          <View style={styles.statItem}>
            <Text style={styles.statIcon}>⚔</Text>
            <View>
              <Text style={[styles.statValue, { color: theme.colors.textPrimary }]}>
                {user.avatarLevel}
              </Text>
              <Text style={[styles.statLabel, { color: theme.colors.textMuted }]}>Level</Text>
            </View>
          </View>
        </View>

        {/* Guild mini-card */}
        {guild.guildId && (
          <TouchableOpacity
            onPress={() => router.push('/(game)/guild')}
            style={[
              styles.guildCard,
              { backgroundColor: theme.colors.surface, borderColor: theme.colors.border },
            ]}
          >
            <View>
              <Text style={[styles.guildName, { color: theme.colors.primary }]}>
                {guild.guildName ?? 'Your Guild'}
              </Text>
              {guild.activeBossId && (
                <Text style={[styles.bossLabel, { color: theme.colors.danger }]}>
                  ⚔ Boss raid active
                </Text>
              )}
            </View>
            <Text style={[styles.chevron, { color: theme.colors.textMuted }]}>›</Text>
          </TouchableOpacity>
        )}

        {/* Sync button */}
        <TouchableOpacity
          style={[
            styles.syncButton,
            { backgroundColor: theme.colors.secondary },
            syncMutation.isPending && { opacity: 0.6 },
          ]}
          onPress={handleManualSync}
          disabled={syncMutation.isPending}
        >
          <Text style={[styles.syncLabel, { color: '#0d0520' }]}>
            {syncMutation.isPending ? 'Syncing…' : '⟳  Sync Health Data'}
          </Text>
        </TouchableOpacity>

        {syncStatus && (
          <Text
            style={[
              styles.syncStatus,
              {
                color: syncStatus.startsWith('✓')
                  ? theme.colors.success
                  : theme.colors.danger,
              },
            ]}
          >
            {syncStatus}
          </Text>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  scroll: { flex: 1 },
  content: { paddingBottom: 32, gap: 16 },
  statBar: {
    flexDirection: 'row',
    marginHorizontal: 16,
    borderRadius: 12,
    borderWidth: 1,
    padding: 16,
    justifyContent: 'space-around',
  },
  statItem: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  statIcon: { fontSize: 20 },
  statValue: { fontSize: 18, fontWeight: '700' },
  statLabel: { fontSize: 10, fontWeight: '600', letterSpacing: 0.5, marginTop: 1 },
  statDivider: { width: 1, height: '100%' },
  guildCard: {
    marginHorizontal: 16,
    borderRadius: 12,
    borderWidth: 1,
    padding: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  guildName: { fontSize: 15, fontWeight: '700' },
  bossLabel: { fontSize: 11, marginTop: 2 },
  chevron: { fontSize: 22, fontWeight: '300' },
  syncButton: {
    marginHorizontal: 16,
    height: 50,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  syncLabel: { fontSize: 15, fontWeight: '700' },
  syncStatus: { textAlign: 'center', fontSize: 13 },
});
