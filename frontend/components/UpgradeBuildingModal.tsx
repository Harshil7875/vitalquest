import React from 'react';
import {
  Modal,
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  TouchableWithoutFeedback,
} from 'react-native';
import { v4 as uuidv4 } from 'uuid';
import { useTheme } from '../theme/ThemeProvider';
import {
  useUpgradeBuildingMutation,
  useSkipTimerMutation,
} from '../services/api/hooks';
import { useGameStore } from '../store/useGameStore';
import type { Building } from '../types';

const TIER_COSTS: Record<number, number> = {
  1: 50,
  2: 100,
  3: 200,
  4: 400,
};

const BUILDING_LABELS: Record<string, string> = {
  APOTHECARY: 'Apothecary',
  TOWER: 'Watchtower',
  GARDEN: 'Mana Garden',
  FORGE: 'Crystal Forge',
};

interface UpgradeBuildingModalProps {
  building: Building | null;
  onClose: () => void;
}

export function UpgradeBuildingModal({ building, onClose }: UpgradeBuildingModalProps) {
  const { theme } = useTheme();
  const upgradeMutation = useUpgradeBuildingMutation();
  const skipMutation = useSkipTimerMutation();
  const { user } = useGameStore();

  if (!building) return null;

  const upgradeCost = TIER_COSTS[building.tier] ?? 800;
  const canAfford = user.totalMana >= upgradeCost;
  const isMaxTier = building.tier >= 5;
  const isUpgrading = building.isUpgrading;
  const skipCost = 10; // Astral Gems
  const canAffordSkip = user.astralGems >= skipCost;

  const handleUpgrade = () => {
    upgradeMutation.mutate(
      { building_id: building.id, idempotency_key: uuidv4() },
      { onSuccess: onClose },
    );
  };

  const handleSkip = () => {
    skipMutation.mutate(
      { building_id: building.id, idempotency_key: uuidv4() },
      { onSuccess: onClose },
    );
  };

  return (
    <Modal
      visible={!!building}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <TouchableWithoutFeedback onPress={onClose}>
        <View style={styles.overlay}>
          <TouchableWithoutFeedback>
            <View
              style={[
                styles.sheet,
                {
                  backgroundColor: theme.colors.surface,
                  borderColor: theme.colors.border,
                  ...theme.shadows.card,
                },
              ]}
            >
              {/* Building name + tier */}
              <Text style={[styles.title, { color: theme.colors.textPrimary }]}>
                {BUILDING_LABELS[building.type] ?? building.type}
              </Text>
              <View style={styles.tierRow}>
                {Array.from({ length: 5 }).map((_, i) => (
                  <View
                    key={i}
                    style={[
                      styles.tierDot,
                      {
                        backgroundColor:
                          i < building.tier
                            ? theme.colors.accent
                            : theme.colors.border,
                      },
                    ]}
                  />
                ))}
                <Text style={[styles.tierLabel, { color: theme.colors.textSecondary }]}>
                  Tier {building.tier} / 5
                </Text>
              </View>

              <View style={[styles.divider, { backgroundColor: theme.colors.border }]} />

              {/* Status */}
              {isUpgrading ? (
                <>
                  <Text style={[styles.statusText, { color: theme.colors.warning }]}>
                    Construction in progress…
                  </Text>
                  {building.completesAt && (
                    <Text style={[styles.timerText, { color: theme.colors.textMuted }]}>
                      Completes {formatRelativeTime(building.completesAt)}
                    </Text>
                  )}
                  <ActionButton
                    label={`Skip Timer · ${skipCost} 💎`}
                    onPress={handleSkip}
                    loading={skipMutation.isPending}
                    disabled={!canAffordSkip}
                    color={theme.colors.accent}
                    disabledReason={canAffordSkip ? undefined : 'Not enough Astral Gems'}
                    theme={theme}
                  />
                </>
              ) : isMaxTier ? (
                <Text style={[styles.statusText, { color: theme.colors.success }]}>
                  Max tier reached ✓
                </Text>
              ) : (
                <>
                  <Text style={[styles.costLabel, { color: theme.colors.textSecondary }]}>
                    Upgrade cost
                  </Text>
                  <Text style={[styles.costValue, { color: theme.colors.accent }]}>
                    ✦ {upgradeCost.toLocaleString()} Mana
                  </Text>
                  <Text style={[styles.balanceText, { color: theme.colors.textMuted }]}>
                    Balance: {user.totalMana.toLocaleString()} Mana
                  </Text>

                  <ActionButton
                    label={`Upgrade to Tier ${building.tier + 1}`}
                    onPress={handleUpgrade}
                    loading={upgradeMutation.isPending}
                    disabled={!canAfford}
                    color={theme.colors.primary}
                    disabledReason={canAfford ? undefined : 'Insufficient Mana'}
                    theme={theme}
                  />
                </>
              )}

              {/* Error feedback */}
              {(upgradeMutation.isError || skipMutation.isError) && (
                <Text style={[styles.errorText, { color: theme.colors.danger }]}>
                  {(upgradeMutation.error as Error)?.message ??
                    (skipMutation.error as Error)?.message}
                </Text>
              )}

              <TouchableOpacity onPress={onClose} style={styles.closeButton}>
                <Text style={[styles.closeLabel, { color: theme.colors.textMuted }]}>
                  Close
                </Text>
              </TouchableOpacity>
            </View>
          </TouchableWithoutFeedback>
        </View>
      </TouchableWithoutFeedback>
    </Modal>
  );
}

function ActionButton({
  label,
  onPress,
  loading,
  disabled,
  color,
  disabledReason,
  theme,
}: {
  label: string;
  onPress: () => void;
  loading: boolean;
  disabled: boolean;
  color: string;
  disabledReason?: string;
  theme: ReturnType<typeof useTheme>['theme'];
}) {
  return (
    <>
      <TouchableOpacity
        onPress={onPress}
        disabled={disabled || loading}
        style={[
          styles.actionButton,
          { backgroundColor: color },
          (disabled || loading) && { opacity: 0.4 },
        ]}
      >
        <Text style={[styles.actionLabel, { color: theme.colors.textOnAccent }]}>
          {loading ? 'Working…' : label}
        </Text>
      </TouchableOpacity>
      {disabledReason && (
        <Text style={[styles.disabledReason, { color: theme.colors.danger }]}>
          {disabledReason}
        </Text>
      )}
    </>
  );
}

function formatRelativeTime(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  if (diff <= 0) return 'soon';
  const hours = Math.floor(diff / 3_600_000);
  const minutes = Math.floor((diff % 3_600_000) / 60_000);
  if (hours > 0) return `in ${hours}h ${minutes}m`;
  return `in ${minutes}m`;
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.6)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sheet: {
    width: 320,
    borderRadius: 16,
    borderWidth: 1,
    padding: 24,
    gap: 10,
  },
  title: { fontSize: 20, fontWeight: '700' },
  tierRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  tierDot: { width: 8, height: 8, borderRadius: 4 },
  tierLabel: { fontSize: 12, marginLeft: 4 },
  divider: { height: 1, marginVertical: 4 },
  statusText: { fontSize: 14, fontWeight: '600' },
  timerText: { fontSize: 12 },
  costLabel: { fontSize: 12 },
  costValue: { fontSize: 22, fontWeight: '700' },
  balanceText: { fontSize: 11 },
  actionButton: {
    height: 44,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 4,
  },
  actionLabel: { fontSize: 15, fontWeight: '700' },
  disabledReason: { fontSize: 11, textAlign: 'center' },
  errorText: { fontSize: 12, textAlign: 'center' },
  closeButton: { alignItems: 'center', paddingTop: 4 },
  closeLabel: { fontSize: 13 },
});
