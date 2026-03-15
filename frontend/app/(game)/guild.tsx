import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  TextInput,
  Modal,
  FlatList,
} from 'react-native';
import { useTheme } from '../../theme/ThemeProvider';
import { HeaderBar } from '../../components/HeaderBar';
import { GuildChat } from '../../components/GuildChat';
import { useGameStore } from '../../store/useGameStore';
import { useAuth } from '../../features/auth/useAuth';
import {
  useGuildStateQuery,
  useCreateGuildMutation,
  useJoinGuildMutation,
} from '../../services/api/hooks';
import type { GuildMember } from '../../types';

export default function GuildScreen() {
  const { theme } = useTheme();
  const { guild } = useGameStore();
  const { userId } = useAuth();

  const [showCreate, setShowCreate] = useState(false);
  const [showJoin, setShowJoin] = useState(false);
  const [guildName, setGuildName] = useState('');
  const [inviteCode, setInviteCode] = useState('');

  const createMutation = useCreateGuildMutation();
  const joinMutation = useJoinGuildMutation();
  const { data: guildState } = useGuildStateQuery(guild.guildId);

  const handleCreate = async () => {
    if (!guildName.trim()) return;
    await createMutation.mutateAsync(guildName.trim());
    setShowCreate(false);
    setGuildName('');
  };

  const handleJoin = async () => {
    if (!inviteCode.trim()) return;
    await joinMutation.mutateAsync(inviteCode.trim().toUpperCase());
    setShowJoin(false);
    setInviteCode('');
  };

  if (!guild.guildId) {
    return (
      <View style={[styles.root, { backgroundColor: theme.colors.background }]}>
        <HeaderBar />
        <View style={styles.noGuild}>
          <Text style={styles.noGuildIcon}>⚔</Text>
          <Text style={[styles.noGuildTitle, { color: theme.colors.textPrimary }]}>
            No Guild Yet
          </Text>
          <Text style={[styles.noGuildSub, { color: theme.colors.textSecondary }]}>
            Join forces with other adventurers. Guild members deal bonus boss damage
            based on collective health adherence.
          </Text>

          <TouchableOpacity
            style={[styles.actionButton, { backgroundColor: theme.colors.primary }]}
            onPress={() => setShowCreate(true)}
          >
            <Text style={[styles.actionLabel, { color: theme.colors.textOnAccent }]}>
              Create Guild · 500 Mana
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[
              styles.actionButton,
              { backgroundColor: 'transparent', borderWidth: 1, borderColor: theme.colors.border },
            ]}
            onPress={() => setShowJoin(true)}
          >
            <Text style={[styles.actionLabel, { color: theme.colors.textPrimary }]}>
              Join with Invite Code
            </Text>
          </TouchableOpacity>
        </View>

        {/* Create Guild Modal */}
        <Modal visible={showCreate} transparent animationType="slide" onRequestClose={() => setShowCreate(false)}>
          <View style={styles.modalOverlay}>
            <View style={[styles.modalSheet, { backgroundColor: theme.colors.surface, borderColor: theme.colors.border }]}>
              <Text style={[styles.modalTitle, { color: theme.colors.textPrimary }]}>Name Your Guild</Text>
              <TextInput
                style={[styles.modalInput, { backgroundColor: theme.colors.surfaceAlt, color: theme.colors.textPrimary, borderColor: theme.colors.border }]}
                placeholder="Guild name…"
                placeholderTextColor={theme.colors.textMuted}
                value={guildName}
                onChangeText={setGuildName}
                maxLength={32}
              />
              <TouchableOpacity
                style={[styles.modalButton, { backgroundColor: theme.colors.primary }]}
                onPress={handleCreate}
                disabled={createMutation.isPending}
              >
                <Text style={[styles.actionLabel, { color: theme.colors.textOnAccent }]}>
                  {createMutation.isPending ? 'Creating…' : 'Create Guild'}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => setShowCreate(false)}>
                <Text style={[styles.cancelLabel, { color: theme.colors.textMuted }]}>Cancel</Text>
              </TouchableOpacity>
            </View>
          </View>
        </Modal>

        {/* Join Guild Modal */}
        <Modal visible={showJoin} transparent animationType="slide" onRequestClose={() => setShowJoin(false)}>
          <View style={styles.modalOverlay}>
            <View style={[styles.modalSheet, { backgroundColor: theme.colors.surface, borderColor: theme.colors.border }]}>
              <Text style={[styles.modalTitle, { color: theme.colors.textPrimary }]}>Enter Invite Code</Text>
              <TextInput
                style={[styles.modalInput, { backgroundColor: theme.colors.surfaceAlt, color: theme.colors.textPrimary, borderColor: theme.colors.border }]}
                placeholder="XXXX-XXXX"
                placeholderTextColor={theme.colors.textMuted}
                value={inviteCode}
                onChangeText={setInviteCode}
                autoCapitalize="characters"
                maxLength={9}
              />
              <TouchableOpacity
                style={[styles.modalButton, { backgroundColor: theme.colors.primary }]}
                onPress={handleJoin}
                disabled={joinMutation.isPending}
              >
                <Text style={[styles.actionLabel, { color: theme.colors.textOnAccent }]}>
                  {joinMutation.isPending ? 'Joining…' : 'Join Guild'}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => setShowJoin(false)}>
                <Text style={[styles.cancelLabel, { color: theme.colors.textMuted }]}>Cancel</Text>
              </TouchableOpacity>
            </View>
          </View>
        </Modal>
      </View>
    );
  }

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.background }]}>
      <HeaderBar />

      {/* Guild info header */}
      <View style={[styles.guildHeader, { backgroundColor: theme.colors.surface, borderBottomColor: theme.colors.border }]}>
        <View>
          <Text style={[styles.guildName, { color: theme.colors.primary }]}>
            {guildState?.name ?? guild.guildName}
          </Text>
          <Text style={[styles.memberCount, { color: theme.colors.textSecondary }]}>
            {guildState?.members.length ?? '?'} members
          </Text>
        </View>
        {guildState && (
          <View style={styles.bossBar}>
            <Text style={[styles.bossLabel, { color: theme.colors.danger }]}>
              Boss HP
            </Text>
            <View style={[styles.bossTrack, { backgroundColor: theme.colors.surfaceAlt }]}>
              <View
                style={[
                  styles.bossFill,
                  {
                    backgroundColor: theme.colors.danger,
                    width: `${(guildState.boss_hp_remaining / guildState.boss_hp_max) * 100}%` as unknown as number,
                  },
                ]}
              />
            </View>
            <Text style={[styles.bossHpText, { color: theme.colors.textMuted }]}>
              {guildState.boss_hp_remaining.toLocaleString()} / {guildState.boss_hp_max.toLocaleString()}
            </Text>
          </View>
        )}
      </View>

      {/* Split view: member list + chat */}
      <View style={styles.splitView}>
        {/* Member list */}
        <View style={[styles.memberList, { borderRightColor: theme.colors.border }]}>
          <Text style={[styles.sectionTitle, { color: theme.colors.textSecondary }]}>Members</Text>
          <FlatList
            data={guildState?.members ?? []}
            keyExtractor={(m) => m.user_id}
            renderItem={({ item }: { item: GuildMember }) => (
              <View style={[styles.memberRow, { borderBottomColor: theme.colors.border }]}>
                <View
                  style={[
                    styles.statusDot,
                    {
                      backgroundColor:
                        item.status === 'ACTIVE'
                          ? theme.colors.success
                          : item.status === 'RESTING'
                          ? theme.colors.warning
                          : theme.colors.danger,
                    },
                  ]}
                />
                <View>
                  <Text style={[styles.memberName, { color: theme.colors.textPrimary }]}>
                    {item.username}
                  </Text>
                  <Text style={[styles.memberLevel, { color: theme.colors.textMuted }]}>
                    Lvl {item.avatar_level}
                  </Text>
                </View>
              </View>
            )}
          />
        </View>

        {/* Guild chat */}
        <View style={styles.chatPane}>
          <GuildChat guildId={guild.guildId} currentUserId={userId ?? ''} />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  noGuild: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, gap: 16 },
  noGuildIcon: { fontSize: 56 },
  noGuildTitle: { fontSize: 22, fontWeight: '700' },
  noGuildSub: { fontSize: 14, textAlign: 'center', lineHeight: 20 },
  actionButton: {
    width: '100%',
    height: 50,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionLabel: { fontSize: 15, fontWeight: '700' },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'flex-end',
  },
  modalSheet: {
    padding: 24,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    borderWidth: 1,
    gap: 14,
  },
  modalTitle: { fontSize: 18, fontWeight: '700' },
  modalInput: {
    height: 46,
    borderRadius: 10,
    borderWidth: 1,
    paddingHorizontal: 14,
    fontSize: 15,
  },
  modalButton: {
    height: 50,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelLabel: { fontSize: 14, textAlign: 'center' },
  guildHeader: {
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderBottomWidth: 1,
  },
  guildName: { fontSize: 16, fontWeight: '700' },
  memberCount: { fontSize: 12, marginTop: 2 },
  bossBar: { alignItems: 'flex-end', gap: 4 },
  bossLabel: { fontSize: 10, fontWeight: '700', letterSpacing: 0.5 },
  bossTrack: {
    width: 120,
    height: 6,
    borderRadius: 3,
    overflow: 'hidden',
  },
  bossFill: { height: '100%', borderRadius: 3 },
  bossHpText: { fontSize: 9 },
  splitView: { flex: 1, flexDirection: 'row' },
  memberList: { width: 120, borderRightWidth: 1, paddingTop: 8 },
  sectionTitle: {
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.5,
    paddingHorizontal: 10,
    marginBottom: 6,
  },
  memberRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  statusDot: { width: 6, height: 6, borderRadius: 3 },
  memberName: { fontSize: 12, fontWeight: '600' },
  memberLevel: { fontSize: 10 },
  chatPane: { flex: 1 },
});
