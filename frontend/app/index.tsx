import { useEffect } from 'react';
import { Redirect } from 'expo-router';
import { useAuth } from '../features/auth/useAuth';
import { View, ActivityIndicator, StyleSheet } from 'react-native';

// ─── Root Index ───────────────────────────────────────────────────────────────
// Determines the initial route on app launch based on auth state.
// Shows a loading spinner while the token is being hydrated from secure storage.

export default function Index() {
  const { isLoading, isAuthenticated } = useAuth();

  if (isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#a855f7" />
      </View>
    );
  }

  if (isAuthenticated) {
    return <Redirect href="/(game)/sanctuary" />;
  }

  return <Redirect href="/login" />;
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    backgroundColor: '#0d0520',
    alignItems: 'center',
    justifyContent: 'center',
  },
});
