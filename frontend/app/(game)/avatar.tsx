import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
} from 'react-native';
import { useTheme } from '../../theme/ThemeProvider';
import { HeaderBar } from '../../components/HeaderBar';
import { useGameStore } from '../../store/useGameStore';
import { useOpenChestMutation } from '../../services/api/hooks';

const XP_PER_LEVEL = 500; // Visual only — server is authoritative

export default function AvatarScreen() {
  const { theme } = useTheme();
  const { user } = useGameStore();
  const openChestMutation = useOpenChestMutation();

  const progress = (user.totalMana % XP_PER_LEVEL) / XP_PER_LEVEL;
  const progressPct = Math.round(progress * 100);

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.background }]}>
      <HeaderBar />

      <ScrollView contentContainerStyle={styles.content}>
        {/* Avatar display */}
        <View style={[styles.avatarCard, { backgroundColor: theme.colors.surface, borderColor: theme.colors.border }]}>
          <View style={[styles.avatarCircle, { borderColor: theme.colors.primary }]}>
            <Text style={styles.avatarEmoji}>🧙</Text>
          </View>

          <Text style={[styles.levelBadge, { color: theme.colors.accent }]}>
            Level {user.avatarLevel}
          </Text>

          {/* XP bar */}
          <View style={styles.xpRow}>
            <Text style={[styles.xpLabel, { color: theme.colors.textSecondary }]}>
              Mana Progress
            </Text>
            <Text style={[styles.xpPct, { color: theme.colors.textMuted }]}>
              {progressPct}%
            </Text>
          </View>
          <View style={[styles.xpTrack, { backgroundColor: theme.colors.surfaceAlt }]}>
            <View
              style={[
                styles.xpFill,
                {
                  backgroundColor: theme.colors.accent,
                  width: `${progressPct}%` as unknown as number,
                },
              ]}
            />
          </View>
          <Text style={[styles.xpHint, { color: theme.colors.textMuted }]}>
            {user.totalMana.toLocaleString()} total Mana earned
          </Text>
        </View>

        {/* Currency summary */}
        <View style={[styles.currencyRow, { backgroundColor: theme.colors.surface, borderColor: theme.colors.border }]}>
          <View style={styles.currencyItem}>
            <Text style={[styles.currencyIcon, { color: theme.colors.accent }]}>✦</Text>
            <Text style={[styles.currencyValue, { color: theme.colors.accent }]}>
              {user.totalMana.toLocaleString()}
            </Text>
            <Text style={[styles.currencyLabel, { color: theme.colors.textMuted }]}>Mana</Text>
          </View>
          <View style={[styles.currencyDivider, { backgroundColor: theme.colors.border }]} />
          <View style={styles.currencyItem}>
            <Text style={styles.currencyIcon}>💎</Text>
            <Text style={[styles.currencyValue, { color: theme.colors.primaryLight }]}>
              {user.astralGems.toLocaleString()}
            </Text>
            <Text style={[styles.currencyLabel, { color: theme.colors.textMuted }]}>
              Astral Gems
            </Text>
          </View>
        </View>

        {/* Loot Chest */}
        <View style={[styles.chestSection, { backgroundColor: theme.colors.surface, borderColor: theme.colors.border }]}>
          <Text style={[styles.chestTitle, { color: theme.colors.textPrimary }]}>
            Loot Chest
          </Text>
          <Text style={[styles.chestSub, { color: theme.colors.textSecondary }]}>
            Spend Mana to open a chest. Rewards include bonus Mana, Astral Gems,
            and cosmetic items. Outcome determined by server-side RNG.
          </Text>

          {openChestMutation.isSuccess && (
            <View style={[styles.rewardBanner, { backgroundColor: theme.colors.accent + '22', borderColor: theme.colors.accent }]}>
              <Text style={[styles.rewardText, { color: theme.colors.accent }]}>
                {openChestMutation.data.reward_type === 'MANA'
                  ? `✦ +${openChestMutation.data.amount} Mana!`
                  : openChestMutation.data.reward_type === 'ASTRAL_GEMS'
                  ? `💎 +${openChestMutation.data.amount} Astral Gems!`
                  : `✨ Rare cosmetic unlocked!`}
              </Text>
            </View>
          )}

          {openChestMutation.isError && (
            <Text style={[styles.errorText, { color: theme.colors.danger }]}>
              {(openChestMutation.error as Error).message}
            </Text>
          )}

          <TouchableOpacity
            style={[
              styles.chestButton,
              { backgroundColor: theme.colors.accent },
              openChestMutation.isPending && { opacity: 0.5 },
            ]}
            onPress={() => openChestMutation.mutate()}
            disabled={openChestMutation.isPending}
          >
            <Text style={[styles.chestButtonLabel, { color: theme.colors.textOnAccent }]}>
              {openChestMutation.isPending ? 'Opening…' : '🎁  Open Chest'}
            </Text>
          </TouchableOpacity>
        </View>

        {/* Mana cap info */}
        <View style={[styles.infoCard, { backgroundColor: theme.colors.surfaceAlt, borderColor: theme.colors.border }]}>
          <Text style={[styles.infoTitle, { color: theme.colors.textSecondary }]}>
            Daily Mana Cap
          </Text>
          <Text style={[styles.infoBody, { color: theme.colors.textMuted }]}>
            You can earn up to 300 Mana per day from health activities.
            Medication logs: +100 · Steps goal: +50 · Diet log: +25 · Stable glucose: +25
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  content: { padding: 16, gap: 16, paddingBottom: 40 },
  avatarCard: {
    borderRadius: 16,
    borderWidth: 1,
    padding: 24,
    alignItems: 'center',
    gap: 8,
  },
  avatarCircle: {
    width: 100,
    height: 100,
    borderRadius: 50,
    borderWidth: 3,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 4,
  },
  avatarEmoji: { fontSize: 52 },
  levelBadge: { fontSize: 22, fontWeight: '800' },
  xpRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    width: '100%',
    marginTop: 8,
  },
  xpLabel: { fontSize: 12 },
  xpPct: { fontSize: 12, fontWeight: '700' },
  xpTrack: {
    width: '100%',
    height: 8,
    borderRadius: 4,
    overflow: 'hidden',
  },
  xpFill: { height: '100%', borderRadius: 4 },
  xpHint: { fontSize: 11, marginTop: 2 },
  currencyRow: {
    flexDirection: 'row',
    borderRadius: 12,
    borderWidth: 1,
    padding: 16,
    justifyContent: 'space-around',
  },
  currencyItem: { alignItems: 'center', gap: 4 },
  currencyIcon: { fontSize: 22 },
  currencyValue: { fontSize: 20, fontWeight: '800' },
  currencyLabel: { fontSize: 10, fontWeight: '600', letterSpacing: 0.5 },
  currencyDivider: { width: 1 },
  chestSection: {
    borderRadius: 16,
    borderWidth: 1,
    padding: 20,
    gap: 12,
  },
  chestTitle: { fontSize: 18, fontWeight: '700' },
  chestSub: { fontSize: 13, lineHeight: 18 },
  rewardBanner: {
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: 'center',
  },
  rewardText: { fontSize: 18, fontWeight: '700' },
  errorText: { fontSize: 13, textAlign: 'center' },
  chestButton: {
    height: 50,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chestButtonLabel: { fontSize: 16, fontWeight: '800' },
  infoCard: {
    borderRadius: 12,
    borderWidth: 1,
    padding: 14,
    gap: 6,
  },
  infoTitle: { fontSize: 12, fontWeight: '700', letterSpacing: 0.3 },
  infoBody: { fontSize: 12, lineHeight: 18 },
});
