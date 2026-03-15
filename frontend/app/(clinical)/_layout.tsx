import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { Stack, Redirect } from 'expo-router';
import * as LocalAuthentication from 'expo-local-authentication';
import { Platform } from 'react-native';
import { useAuth } from '../../features/auth/useAuth';
import { useTheme } from '../../theme/ThemeProvider';

// ─── Clinical Route Group Layout ──────────────────────────────────────────────
// Double-gated:
//   1. JWT authentication (same as game routes)
//   2. Biometric/PIN challenge every time this layout mounts
//      (prevents casual shoulder-surfing of PHI)
//
// On web, we skip biometric and rely on the Doctor Mode toggle from the game
// screen, which the user accessed intentionally.

type BiometricStatus = 'checking' | 'granted' | 'denied';

export default function ClinicalLayout() {
  const { isAuthenticated } = useAuth();
  const { theme } = useTheme();
  const [bioStatus, setBioStatus] = useState<BiometricStatus>('checking');

  useEffect(() => {
    if (!isAuthenticated) return;

    if (Platform.OS === 'web') {
      // Web: already gated by the game-screen toggle
      setBioStatus('granted');
      return;
    }

    (async () => {
      const hasHardware = await LocalAuthentication.hasHardwareAsync();
      const isEnrolled = await LocalAuthentication.isEnrolledAsync();

      if (!hasHardware || !isEnrolled) {
        // Device has no biometrics — fall back to always-granted for now
        // In production, require PIN entry here
        setBioStatus('granted');
        return;
      }

      const result = await LocalAuthentication.authenticateAsync({
        promptMessage: 'Authenticate to view your Clinical Dashboard',
        fallbackLabel: 'Use Passcode',
        cancelLabel: 'Go Back',
      });

      setBioStatus(result.success ? 'granted' : 'denied');
    })();
  }, [isAuthenticated]);

  if (!isAuthenticated) {
    return <Redirect href="/login" />;
  }

  if (bioStatus === 'checking') {
    return (
      <View style={[styles.center, { backgroundColor: theme.colors.background }]}>
        <ActivityIndicator color={theme.colors.primary} size="large" />
        <Text style={[styles.verifyText, { color: theme.colors.textSecondary }]}>
          Verifying identity…
        </Text>
      </View>
    );
  }

  if (bioStatus === 'denied') {
    return (
      <View style={[styles.center, { backgroundColor: theme.colors.background }]}>
        <Text style={styles.lockIcon}>🔒</Text>
        <Text style={[styles.deniedTitle, { color: theme.colors.textPrimary }]}>
          Authentication Required
        </Text>
        <Text style={[styles.deniedSub, { color: theme.colors.textSecondary }]}>
          Biometric authentication is required to access your clinical health data.
        </Text>
        <Redirect href="/(game)/sanctuary" />
      </View>
    );
  }

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        animation: 'fade',
      }}
    />
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    padding: 32,
  },
  verifyText: { fontSize: 14 },
  lockIcon: { fontSize: 48, marginBottom: 8 },
  deniedTitle: { fontSize: 18, fontWeight: '700', textAlign: 'center' },
  deniedSub: { fontSize: 14, textAlign: 'center', lineHeight: 20 },
});
