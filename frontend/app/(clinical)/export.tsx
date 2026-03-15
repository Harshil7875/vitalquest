import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { router } from 'expo-router';
import { useTheme } from '../../theme/ThemeProvider';
import { HeaderBar } from '../../components/HeaderBar';
import { useExportClinicalQuery } from '../../services/api/hooks';
import { ApiError } from '../../services/api/client';

// ─── Clinical Export Screen ───────────────────────────────────────────────────
// Pro-gated endpoint. Fetches decrypted health history from the backend.
// The query is disabled until the user explicitly triggers it, since the
// backend operation is expensive and returns PHI.

export default function ExportScreen() {
  const { theme } = useTheme();
  const [fetchEnabled, setFetchEnabled] = useState(false);

  const { data, isLoading, isError, error } = useExportClinicalQuery(fetchEnabled);

  const isPaywallError =
    isError && error instanceof ApiError && error.status === 403;

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.background }]}>
      <HeaderBar />

      <ScrollView contentContainerStyle={styles.content}>
        <View style={[styles.headerSection, { borderBottomColor: theme.colors.border }]}>
          <Text style={[styles.title, { color: theme.colors.textPrimary }]}>
            Health Report Export
          </Text>
          <Text style={[styles.subtitle, { color: theme.colors.textSecondary }]}>
            Generate a complete export of your health history for your doctor.
            This file contains full biometric logs and is suitable for clinical review.
          </Text>
        </View>

        {/* Export trigger */}
        {!fetchEnabled && (
          <View style={[styles.card, { backgroundColor: theme.colors.surface, borderColor: theme.colors.border }]}>
            <Text style={[styles.cardTitle, { color: theme.colors.textPrimary }]}>
              Generate Report
            </Text>
            <Text style={[styles.cardBody, { color: theme.colors.textSecondary }]}>
              This will fetch your complete decrypted health record from the server.
              This data is protected and only accessible to you.
            </Text>
            <View style={[styles.formatRow, { borderColor: theme.colors.border }]}>
              <FormatBadge label="JSON" color={theme.colors.primary} theme={theme} />
              <FormatBadge label="PDF (via backend)" color={theme.colors.secondary} theme={theme} />
            </View>
            <TouchableOpacity
              style={[styles.generateButton, { backgroundColor: theme.colors.primary }]}
              onPress={() => setFetchEnabled(true)}
            >
              <Text style={[styles.generateLabel, { color: theme.colors.textOnAccent }]}>
                Generate Export
              </Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Loading state */}
        {isLoading && (
          <View style={styles.center}>
            <ActivityIndicator color={theme.colors.primary} size="large" />
            <Text style={[styles.loadingText, { color: theme.colors.textSecondary }]}>
              Decrypting your health records…
            </Text>
          </View>
        )}

        {/* Paywall */}
        {isPaywallError && (
          <View
            style={[
              styles.card,
              {
                backgroundColor: theme.colors.surface,
                borderColor: theme.colors.warning,
              },
            ]}
          >
            <Text style={styles.lockIcon}>🔒</Text>
            <Text style={[styles.cardTitle, { color: theme.colors.textPrimary }]}>
              Pro Feature
            </Text>
            <Text style={[styles.cardBody, { color: theme.colors.textSecondary }]}>
              Health report export requires a VitalQuest Pro subscription.
              Upgrade to share your data with your healthcare team.
            </Text>
          </View>
        )}

        {/* Other errors */}
        {isError && !isPaywallError && (
          <View
            style={[
              styles.card,
              { backgroundColor: theme.colors.surface, borderColor: theme.colors.danger },
            ]}
          >
            <Text style={[styles.errorTitle, { color: theme.colors.danger }]}>
              Export Failed
            </Text>
            <Text style={[styles.cardBody, { color: theme.colors.textSecondary }]}>
              {(error as Error).message}
            </Text>
            <TouchableOpacity
              style={[styles.retryButton, { borderColor: theme.colors.primary }]}
              onPress={() => {
                setFetchEnabled(false);
                setTimeout(() => setFetchEnabled(true), 100);
              }}
            >
              <Text style={[styles.retryLabel, { color: theme.colors.primary }]}>Retry</Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Success: data preview */}
        {data && (
          <View
            style={[
              styles.card,
              { backgroundColor: theme.colors.surface, borderColor: theme.colors.success },
            ]}
          >
            <Text style={[styles.successTitle, { color: theme.colors.success }]}>
              ✓ Export Ready
            </Text>
            <Text style={[styles.cardBody, { color: theme.colors.textSecondary }]}>
              Your health data has been successfully decrypted and is ready for review.
              In a production build, this would trigger a file download or share sheet.
            </Text>
            <View
              style={[
                styles.dataPreview,
                { backgroundColor: theme.colors.surfaceAlt, borderColor: theme.colors.border },
              ]}
            >
              <Text
                style={[
                  styles.dataPreviewText,
                  { color: theme.colors.textSecondary, fontFamily: 'SpaceMono' },
                ]}
                numberOfLines={8}
              >
                {JSON.stringify(data, null, 2)}
              </Text>
            </View>
          </View>
        )}

        <TouchableOpacity onPress={() => router.back()} style={styles.backButton}>
          <Text style={[styles.backLabel, { color: theme.colors.textMuted }]}>
            ← Back to Dashboard
          </Text>
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
}

function FormatBadge({
  label,
  color,
  theme,
}: {
  label: string;
  color: string;
  theme: ReturnType<typeof useTheme>['theme'];
}) {
  return (
    <View style={[styles.badge, { backgroundColor: color + '22', borderColor: color + '66' }]}>
      <Text style={[styles.badgeText, { color }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  content: { padding: 16, gap: 16, paddingBottom: 48 },
  headerSection: { paddingBottom: 16, borderBottomWidth: StyleSheet.hairlineWidth, gap: 6 },
  title: { fontSize: 20, fontWeight: '700' },
  subtitle: { fontSize: 14, lineHeight: 20 },
  card: { borderRadius: 10, borderWidth: 1, padding: 16, gap: 12 },
  cardTitle: { fontSize: 16, fontWeight: '700' },
  cardBody: { fontSize: 13, lineHeight: 18 },
  formatRow: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 6, borderWidth: 1 },
  badgeText: { fontSize: 11, fontWeight: '700' },
  generateButton: { height: 48, borderRadius: 8, alignItems: 'center', justifyContent: 'center' },
  generateLabel: { fontSize: 15, fontWeight: '700' },
  center: { alignItems: 'center', gap: 12, paddingVertical: 32 },
  loadingText: { fontSize: 14 },
  lockIcon: { fontSize: 36, textAlign: 'center' },
  errorTitle: { fontSize: 15, fontWeight: '700' },
  retryButton: {
    height: 40,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  retryLabel: { fontSize: 14, fontWeight: '600' },
  successTitle: { fontSize: 15, fontWeight: '700' },
  dataPreview: {
    borderRadius: 6,
    borderWidth: 1,
    padding: 12,
    maxHeight: 200,
  },
  dataPreviewText: { fontSize: 11, lineHeight: 16 },
  backButton: { alignItems: 'center', paddingVertical: 8 },
  backLabel: { fontSize: 14 },
});
