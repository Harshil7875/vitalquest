import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useTheme } from '../theme/ThemeProvider';
import { useGameStore } from '../store/useGameStore';

interface HeaderBarProps {
  onPressClinicalToggle?: () => void;
}

export function HeaderBar({ onPressClinicalToggle }: HeaderBarProps) {
  const { theme, mode } = useTheme();
  const { user } = useGameStore();

  const isGame = mode === 'game';

  return (
    <View
      style={[
        styles.container,
        {
          backgroundColor: theme.colors.surface,
          borderBottomColor: theme.colors.border,
        },
      ]}
    >
      {isGame ? (
        // Game Mode: Avatar level + Mana balance
        <View style={styles.row}>
          <View style={styles.pill}>
            <Text style={[styles.label, { color: theme.colors.textSecondary }]}>
              LVL
            </Text>
            <Text
              style={[
                styles.value,
                { color: theme.colors.primary, fontSize: theme.typography.sizeLg },
              ]}
            >
              {user.avatarLevel}
            </Text>
          </View>

          <Text
            style={[
              styles.appName,
              { color: theme.colors.textPrimary, fontFamily: theme.typography.fontHeader },
            ]}
          >
            VitalQuest
          </Text>

          <View style={styles.pill}>
            <Text style={[styles.manaGlyph, { color: theme.colors.accent }]}>✦</Text>
            <Text
              style={[
                styles.value,
                { color: theme.colors.accent, fontSize: theme.typography.sizeLg },
              ]}
            >
              {user.totalMana.toLocaleString()}
            </Text>
          </View>
        </View>
      ) : (
        // Clinical Mode: Clean header with sync status
        <View style={styles.row}>
          <Text
            style={[
              styles.clinicalTitle,
              { color: theme.colors.textPrimary, fontFamily: theme.typography.fontBody },
            ]}
          >
            Clinical Dashboard
          </Text>

          <View
            style={[styles.syncBadge, { backgroundColor: theme.colors.success + '22' }]}
          >
            <View
              style={[styles.syncDot, { backgroundColor: theme.colors.success }]}
            />
            <Text style={[styles.syncLabel, { color: theme.colors.success }]}>
              Synced
            </Text>
          </View>
        </View>
      )}

      {/* Clinical / Game toggle button */}
      {onPressClinicalToggle && (
        <TouchableOpacity
          onPress={onPressClinicalToggle}
          style={[
            styles.toggleButton,
            { borderColor: theme.colors.border, backgroundColor: theme.colors.surfaceAlt },
          ]}
          accessibilityLabel={isGame ? 'Open clinical dashboard' : 'Return to game'}
        >
          <Text style={[styles.toggleLabel, { color: theme.colors.textSecondary }]}>
            {isGame ? '⚕' : '⚔'}
          </Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    height: 56,
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  row: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  label: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1,
  },
  value: {
    fontWeight: '700',
  },
  manaGlyph: {
    fontSize: 14,
  },
  appName: {
    fontSize: 18,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  clinicalTitle: {
    fontSize: 16,
    fontWeight: '600',
  },
  syncBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
  },
  syncDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  syncLabel: {
    fontSize: 11,
    fontWeight: '600',
  },
  toggleButton: {
    width: 36,
    height: 36,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 12,
  },
  toggleLabel: {
    fontSize: 18,
  },
});
