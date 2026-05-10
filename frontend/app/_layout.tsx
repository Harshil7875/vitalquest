import React, { useEffect, useRef } from 'react';
import { View, StyleSheet, Platform } from 'react-native';
import { Stack } from 'expo-router';
import { QueryClientProvider } from '@tanstack/react-query';
import NetInfo from '@react-native-community/netinfo';
import { ThemeProvider } from '../theme/ThemeProvider';
import { createQueryClient } from '../services/api/hooks';
import { useFlushOfflineQueue } from '../services/api/hooks';
import { registerClinicalStoreAppStateListener } from '../store/useClinicalStore';
import { DevMockPanel } from '../components/DevMockPanel';
import { StatusBar } from 'expo-status-bar';

// Create a single QueryClient instance for the app lifetime
const queryClient = createQueryClient();

// Register the AppState listener for PHI auto-clear once at module level
registerClinicalStoreAppStateListener();

export default function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RootLayoutInner />
      </ThemeProvider>
    </QueryClientProvider>
  );
}

function RootLayoutInner() {
  const { flush } = useFlushOfflineQueue();

  // Listen for network reconnection and flush the offline queue
  useEffect(() => {
    const unsub = NetInfo.addEventListener((state) => {
      if (state.isConnected && state.isInternetReachable) {
        flush();
      }
    });
    return unsub;
  }, [flush]);

  // ─── Web: Dual-column layout (mobile container + Dev Mock Panel)
  if (Platform.OS === 'web') {
    return (
      <View style={styles.webRoot}>
        <StatusBar style="light" />
        {/* Constrained mobile-width app column */}
        <View style={styles.webAppColumn}>
          <Stack screenOptions={{ headerShown: false }} />
        </View>
        {/* Phase 13 / fix #7 — Dev Mock Panel is dev-only.
           Native builds never see it (handled inside the component too) and
           production web builds skip the render entirely. */}
        {__DEV__ && <DevMockPanel />}
      </View>
    );
  }

  // ─── Mobile: Full-screen layout
  return (
    <>
      <StatusBar style="light" />
      <Stack screenOptions={{ headerShown: false }} />
    </>
  );
}

const styles = StyleSheet.create({
  webRoot: {
    flex: 1,
    flexDirection: 'row',
    height: '100vh' as unknown as number,
    overflow: 'hidden' as unknown as 'scroll',
  },
  webAppColumn: {
    flex: 1,
    maxWidth: 428, // Mimic iPhone 14 Pro Max width
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: '#3d1f6e',
    overflow: 'hidden' as unknown as 'scroll',
  },
});
