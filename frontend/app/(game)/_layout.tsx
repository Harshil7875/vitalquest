import React from 'react';
import { Tabs, Redirect } from 'expo-router';
import { useAuth } from '../../features/auth/useAuth';
import { View, ActivityIndicator, StyleSheet } from 'react-native';
import { useGameStateQuery } from '../../services/api/hooks';

// ─── Game Route Group Layout ──────────────────────────────────────────────────
// Auth-gated: redirects to /login if no token.
// Fetches game state on mount so the Sanctuary has data immediately.
// Tab navigation: Sanctuary | Guild | Avatar

export default function GameLayout() {
  const { isLoading, isAuthenticated } = useAuth();

  // Kick off the authoritative game state fetch while the layout mounts
  useGameStateQuery(isAuthenticated);

  if (isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color="#a855f7" size="large" />
      </View>
    );
  }

  if (!isAuthenticated) {
    return <Redirect href="/login" />;
  }

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          backgroundColor: '#1a0a2e',
          borderTopColor: '#3d1f6e',
          borderTopWidth: 1,
        },
        tabBarActiveTintColor: '#a855f7',
        tabBarInactiveTintColor: '#7c3aed',
        tabBarLabelStyle: { fontSize: 11, fontWeight: '700' },
      }}
    >
      <Tabs.Screen
        name="sanctuary"
        options={{ tabBarLabel: 'Sanctuary', tabBarIcon: () => null }}
      />
      <Tabs.Screen
        name="guild"
        options={{ tabBarLabel: 'Guild', tabBarIcon: () => null }}
      />
      <Tabs.Screen
        name="avatar"
        options={{ tabBarLabel: 'Avatar', tabBarIcon: () => null }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    backgroundColor: '#0d0520',
    alignItems: 'center',
    justifyContent: 'center',
  },
});
