import React, { useState, useRef } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  FlatList,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { useTheme } from '../theme/ThemeProvider';
import { useGuildChatQuery, useSendChatMutation } from '../services/api/hooks';
import type { ChatMessage } from '../types';

interface GuildChatProps {
  guildId: string;
  currentUserId: string;
}

export function GuildChat({ guildId, currentUserId }: GuildChatProps) {
  const { theme } = useTheme();
  const { data: messages = [], isLoading } = useGuildChatQuery(guildId);
  const sendMutation = useSendChatMutation(guildId);
  const [draft, setDraft] = useState('');
  const listRef = useRef<FlatList<ChatMessage>>(null);

  const send = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    sendMutation.mutate(trimmed);
    setDraft('');
  };

  const renderMessage = ({ item }: { item: ChatMessage }) => {
    const isOwn = item.user_id === currentUserId;
    return (
      <View
        style={[
          styles.messageBubble,
          isOwn ? styles.ownBubble : styles.otherBubble,
          {
            backgroundColor: isOwn
              ? theme.colors.primary + '33'
              : theme.colors.surfaceAlt,
            borderColor: isOwn ? theme.colors.primary + '55' : theme.colors.border,
          },
        ]}
      >
        {!isOwn && (
          <Text style={[styles.username, { color: theme.colors.accent }]}>
            {item.username}
          </Text>
        )}
        <Text style={[styles.messageText, { color: theme.colors.textPrimary }]}>
          {item.content}
        </Text>
        <Text style={[styles.timestamp, { color: theme.colors.textMuted }]}>
          {formatTime(item.sent_at)}
        </Text>
      </View>
    );
  };

  return (
    <KeyboardAvoidingView
      style={[styles.container, { backgroundColor: theme.colors.background }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={[styles.header, { borderBottomColor: theme.colors.border }]}>
        <Text style={[styles.headerText, { color: theme.colors.textPrimary }]}>
          Guild Chat
        </Text>
        <View style={[styles.liveBadge, { backgroundColor: theme.colors.success + '33' }]}>
          <View style={[styles.liveDot, { backgroundColor: theme.colors.success }]} />
          <Text style={[styles.liveText, { color: theme.colors.success }]}>LIVE</Text>
        </View>
      </View>

      {isLoading ? (
        <View style={styles.center}>
          <Text style={{ color: theme.colors.textMuted }}>Loading messages…</Text>
        </View>
      ) : (
        <FlatList
          ref={listRef}
          data={messages}
          keyExtractor={(m) => m.message_id}
          renderItem={renderMessage}
          contentContainerStyle={styles.list}
          onContentSizeChange={() => listRef.current?.scrollToEnd()}
        />
      )}

      <View style={[styles.inputRow, { borderTopColor: theme.colors.border }]}>
        <TextInput
          style={[
            styles.input,
            {
              backgroundColor: theme.colors.surfaceAlt,
              color: theme.colors.textPrimary,
              borderColor: theme.colors.border,
            },
          ]}
          placeholder="Message your guild…"
          placeholderTextColor={theme.colors.textMuted}
          value={draft}
          onChangeText={setDraft}
          onSubmitEditing={send}
          returnKeyType="send"
          maxLength={500}
        />
        <TouchableOpacity
          onPress={send}
          disabled={!draft.trim() || sendMutation.isPending}
          style={[
            styles.sendButton,
            { backgroundColor: theme.colors.primary },
            (!draft.trim() || sendMutation.isPending) && { opacity: 0.4 },
          ]}
        >
          <Text style={[styles.sendLabel, { color: theme.colors.textOnAccent }]}>
            ↑
          </Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  headerText: { fontSize: 14, fontWeight: '700' },
  liveBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
  },
  liveDot: { width: 5, height: 5, borderRadius: 3 },
  liveText: { fontSize: 9, fontWeight: '800', letterSpacing: 0.5 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  list: { padding: 12, gap: 8 },
  messageBubble: {
    maxWidth: '80%',
    padding: 10,
    borderRadius: 12,
    borderWidth: 1,
    gap: 2,
  },
  ownBubble: { alignSelf: 'flex-end', borderBottomRightRadius: 3 },
  otherBubble: { alignSelf: 'flex-start', borderBottomLeftRadius: 3 },
  username: { fontSize: 11, fontWeight: '700' },
  messageText: { fontSize: 13 },
  timestamp: { fontSize: 10, alignSelf: 'flex-end', marginTop: 2 },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 8,
    gap: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  input: {
    flex: 1,
    height: 38,
    paddingHorizontal: 12,
    borderRadius: 19,
    borderWidth: 1,
    fontSize: 13,
  },
  sendButton: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendLabel: { fontSize: 18, fontWeight: '700', marginTop: -2 },
});
