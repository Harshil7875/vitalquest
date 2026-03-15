import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

// ─── Secure Token Storage ─────────────────────────────────────────────────────
// On iOS/Android we use expo-secure-store (backed by the Secure Enclave / Keystore).
// On web we fall back to sessionStorage – tokens are cleared when the tab closes,
// which is acceptable for the local dev sandbox.

const TOKEN_KEY = 'vq_access_token';
const USER_ID_KEY = 'vq_user_id';

async function set(key: string, value: string): Promise<void> {
  if (Platform.OS === 'web') {
    sessionStorage.setItem(key, value);
  } else {
    await SecureStore.setItemAsync(key, value);
  }
}

async function get(key: string): Promise<string | null> {
  if (Platform.OS === 'web') {
    return sessionStorage.getItem(key);
  }
  return SecureStore.getItemAsync(key);
}

async function remove(key: string): Promise<void> {
  if (Platform.OS === 'web') {
    sessionStorage.removeItem(key);
  } else {
    await SecureStore.deleteItemAsync(key);
  }
}

export const authStorage = {
  saveToken: (token: string) => set(TOKEN_KEY, token),
  getToken: () => get(TOKEN_KEY),
  removeToken: () => remove(TOKEN_KEY),

  saveUserId: (id: string) => set(USER_ID_KEY, id),
  getUserId: () => get(USER_ID_KEY),
  removeUserId: () => remove(USER_ID_KEY),

  clear: async () => {
    await remove(TOKEN_KEY);
    await remove(USER_ID_KEY);
  },
};
