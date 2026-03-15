import { useState, useEffect, useCallback } from 'react';
import { authStorage } from './authStorage';
import { useGameStore } from '../../store/useGameStore';
import { useClinicalStore } from '../../store/useClinicalStore';

// ─── Auth State ───────────────────────────────────────────────────────────────

interface AuthState {
  token: string | null;
  userId: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

interface UseAuthReturn extends AuthState {
  signIn: (token: string, userId: string) => Promise<void>;
  signOut: () => Promise<void>;
}

// ─── useAuth ──────────────────────────────────────────────────────────────────
// Minimal hook that manages JWT storage and exposes auth state to the app.
// Actual login/register API calls are handled by the TanStack Query mutations
// in services/api/hooks.ts — this hook is purely for reading/writing the token.

export function useAuth(): UseAuthReturn {
  const [state, setState] = useState<AuthState>({
    token: null,
    userId: null,
    isLoading: true,
    isAuthenticated: false,
  });

  const resetGameStore = useGameStore((s) => s.reset);
  const clearClinicalData = useClinicalStore((s) => s.clearSensitiveData);

  // Hydrate from secure storage on mount
  useEffect(() => {
    (async () => {
      const [token, userId] = await Promise.all([
        authStorage.getToken(),
        authStorage.getUserId(),
      ]);

      setState({
        token,
        userId,
        isLoading: false,
        isAuthenticated: !!token,
      });
    })();
  }, []);

  const signIn = useCallback(async (token: string, userId: string) => {
    await authStorage.saveToken(token);
    await authStorage.saveUserId(userId);
    setState({ token, userId, isLoading: false, isAuthenticated: true });
  }, []);

  const signOut = useCallback(async () => {
    await authStorage.clear();
    resetGameStore();
    clearClinicalData();
    setState({ token: null, userId: null, isLoading: false, isAuthenticated: false });
  }, [resetGameStore, clearClinicalData]);

  return { ...state, signIn, signOut };
}
