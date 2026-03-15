import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from 'react-native';
import { router, Link } from 'expo-router';
import { useRegisterMutation } from '../services/api/hooks';
import { useAuth } from '../features/auth/useAuth';
import { ApiError } from '../services/api/client';

export default function RegisterScreen() {
  const { signIn } = useAuth();
  const registerMutation = useRegisterMutation();

  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleRegister = async () => {
    if (!username.trim() || !email.trim() || !password.trim()) {
      setError('All fields are required.');
      return;
    }
    setError(null);
    try {
      const res = await registerMutation.mutateAsync({ username, email, password });
      await signIn(res.access_token, res.user_id);
      router.replace('/(game)/sanctuary');
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError('That username or email is already taken.');
      } else {
        setError('Registration failed. Please try again.');
      }
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.brand}>
          <Text style={styles.logo}>⚗</Text>
          <Text style={styles.appName}>VitalQuest</Text>
          <Text style={styles.tagline}>Begin your legend</Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Create Account</Text>

          <Text style={styles.fieldLabel}>Username</Text>
          <TextInput
            style={styles.input}
            value={username}
            onChangeText={setUsername}
            autoCapitalize="none"
            autoCorrect={false}
            placeholder="hero_name"
            placeholderTextColor="#7c3aed"
          />

          <Text style={styles.fieldLabel}>Email</Text>
          <TextInput
            style={styles.input}
            value={email}
            onChangeText={setEmail}
            keyboardType="email-address"
            autoCapitalize="none"
            autoCorrect={false}
            placeholder="hero@realm.com"
            placeholderTextColor="#7c3aed"
          />

          <Text style={styles.fieldLabel}>Password</Text>
          <TextInput
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            placeholder="••••••••"
            placeholderTextColor="#7c3aed"
            returnKeyType="done"
            onSubmitEditing={handleRegister}
          />

          {error && <Text style={styles.errorText}>{error}</Text>}

          <TouchableOpacity
            style={[styles.button, registerMutation.isPending && styles.buttonDisabled]}
            onPress={handleRegister}
            disabled={registerMutation.isPending}
          >
            <Text style={styles.buttonLabel}>
              {registerMutation.isPending ? 'Creating…' : 'Begin Quest'}
            </Text>
          </TouchableOpacity>

          <View style={styles.footerRow}>
            <Text style={styles.footerText}>Already a hero? </Text>
            <Link href="/login" style={styles.footerLink}>
              Sign in
            </Link>
          </View>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0d0520' },
  scroll: {
    flexGrow: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 32,
  },
  brand: { alignItems: 'center', gap: 8 },
  logo: { fontSize: 64 },
  appName: { fontSize: 36, fontWeight: '900', color: '#f3e8ff', letterSpacing: 1 },
  tagline: { fontSize: 14, color: '#c4b5fd', letterSpacing: 0.5 },
  card: {
    width: '100%',
    maxWidth: 360,
    backgroundColor: '#1a0a2e',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#3d1f6e',
    padding: 24,
    gap: 12,
  },
  cardTitle: { fontSize: 20, fontWeight: '700', color: '#f3e8ff', marginBottom: 4 },
  fieldLabel: { fontSize: 12, fontWeight: '600', color: '#c4b5fd', marginBottom: -6 },
  input: {
    height: 46,
    backgroundColor: '#251040',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#3d1f6e',
    paddingHorizontal: 14,
    color: '#f3e8ff',
    fontSize: 15,
  },
  errorText: { color: '#ef4444', fontSize: 13, textAlign: 'center' },
  button: {
    height: 50,
    backgroundColor: '#a855f7',
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 4,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonLabel: { color: '#0d0520', fontSize: 16, fontWeight: '800' },
  footerRow: { flexDirection: 'row', justifyContent: 'center', marginTop: 4 },
  footerText: { color: '#7c3aed', fontSize: 13 },
  footerLink: { color: '#c084fc', fontSize: 13, fontWeight: '600' },
});
