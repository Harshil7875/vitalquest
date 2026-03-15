import {
  useQuery,
  useMutation,
  useQueryClient,
  QueryClient,
} from '@tanstack/react-query';
import { v4 as uuidv4 } from 'uuid';
import { apiClient } from './client';
import { useGameStore } from '../../store/useGameStore';
import { useClinicalStore } from '../../store/useClinicalStore';
import type {
  AuthResponse,
  GameStateResponse,
  SyncHealthResponse,
  UpgradeBuildingRequest,
  UpgradeBuildingResponse,
  SkipTimerRequest,
  SkipTimerResponse,
  OpenChestResponse,
  GuildState,
  ChatMessage,
  VitalQuestStandardPayload,
} from '../../types';

// ─── Query Keys ───────────────────────────────────────────────────────────────

export const queryKeys = {
  gameState: ['gameState'] as const,
  guildState: (guildId: string) => ['guild', guildId] as const,
  guildChat: (guildId: string) => ['guildChat', guildId] as const,
  clinicalExport: ['clinicalExport'] as const,
};

// ─── Auth Mutations ───────────────────────────────────────────────────────────

export function useLoginMutation() {
  return useMutation({
    mutationFn: (creds: { username: string; password: string }) =>
      apiClient.post<AuthResponse>('/api/auth/login', creds),
  });
}

export function useRegisterMutation() {
  return useMutation({
    mutationFn: (creds: { username: string; password: string; email: string }) =>
      apiClient.post<AuthResponse>('/api/auth/register', creds),
  });
}

// ─── useGameStateQuery ────────────────────────────────────────────────────────
// Fetches the authoritative server-side game state on boot and after mutations.
// Overwrites local Zustand optimistic updates to correct any desynchronisation.

export function useGameStateQuery(enabled = true) {
  const setGameState = useGameStore((s) => s.setGameState);

  return useQuery({
    queryKey: queryKeys.gameState,
    queryFn: async () => {
      const data = await apiClient.get<GameStateResponse>('/api/game/state');
      // Server is authoritative — overwrite optimistic local state
      setGameState(data);
      return data;
    },
    enabled,
    staleTime: 30_000, // Treat as fresh for 30 s to avoid refetch storms
    refetchOnWindowFocus: true,
  });
}

// ─── useSyncHealthMutation ────────────────────────────────────────────────────
// Core health→game pipeline trigger.
// On offline failure: pushes payload to ClinicalStore.offlineQueue.
// On success: applies optimistic Mana from the server response.

export function useSyncHealthMutation() {
  const queryClient = useQueryClient();
  const optimisticAddMana = useGameStore((s) => s.optimisticAddMana);
  const enqueueOffline = useClinicalStore((s) => s.enqueueOffline);
  const setTodayProgress = useClinicalStore((s) => s.setTodayProgress);

  return useMutation({
    mutationFn: (payload: VitalQuestStandardPayload) =>
      apiClient.post<SyncHealthResponse>('/api/health/sync', payload),

    onSuccess: (data, payload) => {
      if (data.status === 'ACCEPTED' && data.game_update) {
        optimisticAddMana(data.mana_awarded);
        // Invalidate so useGameStateQuery re-fetches the authoritative state
        queryClient.invalidateQueries({ queryKey: queryKeys.gameState });
      }
      setTodayProgress({
        currentSteps: payload.steps ?? 0,
        medicationLogged: payload.medication_taken ?? false,
        lastSyncComplete: new Date().toISOString(),
      });
    },

    onError: (_err, payload) => {
      // Network failure — enqueue for replay when connectivity returns
      enqueueOffline({
        id: payload.idempotency_key,
        payload,
        queuedAt: new Date().toISOString(),
      });
      // Still apply optimistic Mana — the server's idempotency key will prevent
      // double-reward when the queue flushes.
      optimisticAddMana(0); // Placeholder; real amount unknown until sync
    },
  });
}

// ─── useFlushOfflineQueue ─────────────────────────────────────────────────────
// Called by the NetInfo listener when the device reconnects.
// Drains the ClinicalStore offline queue one-by-one in FIFO order.

export function useFlushOfflineQueue() {
  const queryClient = useQueryClient();
  const { offlineQueue, dequeueOffline, lockQueue, unlockQueue, isQueueLocked } =
    useClinicalStore();
  const optimisticAddMana = useGameStore((s) => s.optimisticAddMana);

  const flush = async () => {
    if (isQueueLocked || offlineQueue.length === 0) return;

    lockQueue();
    try {
      for (const entry of offlineQueue) {
        try {
          const res = await apiClient.post<SyncHealthResponse>(
            '/api/health/sync',
            entry.payload,
          );
          if (res.status === 'ACCEPTED') {
            optimisticAddMana(res.mana_awarded);
          }
          dequeueOffline(entry.id);
        } catch {
          // If this entry still fails, stop — network might not be stable yet
          break;
        }
      }
      // Re-fetch authoritative game state after batch sync
      queryClient.invalidateQueries({ queryKey: queryKeys.gameState });
    } finally {
      unlockQueue();
    }
  };

  return { flush, queueLength: offlineQueue.length };
}

// ─── useUpgradeBuildingMutation ───────────────────────────────────────────────
// Sends the upgrade intent. Applies optimistic Mana deduction immediately.
// Reverts if server returns 400 (e.g. insufficient funds / tech tree blocked).

export function useUpgradeBuildingMutation() {
  const queryClient = useQueryClient();
  const optimisticDeductMana = useGameStore((s) => s.optimisticDeductMana);
  const setBuilding = useGameStore((s) => s.setBuilding);
  const gameState = useGameStore((s) => s.sanctuary.buildings);

  return useMutation({
    mutationFn: (req: UpgradeBuildingRequest) =>
      apiClient.post<UpgradeBuildingResponse>('/api/game/action/upgrade_building', req),

    onMutate: (req) => {
      const building = gameState.find((b) => b.id === req.building_id);
      return { prevBuilding: building };
    },

    onSuccess: (data) => {
      optimisticDeductMana(data.mana_spent);
      setBuilding(data.building);
      queryClient.invalidateQueries({ queryKey: queryKeys.gameState });
    },

    onError: (_err, _req, context) => {
      // Revert optimistic building change
      if (context?.prevBuilding) {
        setBuilding(context.prevBuilding);
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.gameState });
    },
  });
}

// ─── useSkipTimerMutation ─────────────────────────────────────────────────────

export function useSkipTimerMutation() {
  const queryClient = useQueryClient();
  const optimisticDeductGems = useGameStore((s) => s.optimisticDeductGems);
  const setBuilding = useGameStore((s) => s.setBuilding);

  return useMutation({
    mutationFn: (req: SkipTimerRequest) =>
      apiClient.post<SkipTimerResponse>('/api/game/action/skip_timer', req),

    onSuccess: (data) => {
      optimisticDeductGems(data.gems_spent);
      setBuilding(data.building);
      queryClient.invalidateQueries({ queryKey: queryKeys.gameState });
    },

    onError: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.gameState });
    },
  });
}

// ─── useOpenChestMutation ─────────────────────────────────────────────────────

export function useOpenChestMutation() {
  const queryClient = useQueryClient();
  const optimisticAddMana = useGameStore((s) => s.optimisticAddMana);

  return useMutation({
    mutationFn: () =>
      apiClient.post<OpenChestResponse>('/api/game/action/open_chest', {
        idempotency_key: uuidv4(),
      }),

    onSuccess: (data) => {
      if (data.reward_type === 'MANA') {
        optimisticAddMana(data.amount);
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.gameState });
    },
  });
}

// ─── useGuildStateQuery ───────────────────────────────────────────────────────

export function useGuildStateQuery(guildId: string | null) {
  return useQuery({
    queryKey: queryKeys.guildState(guildId ?? ''),
    queryFn: () =>
      apiClient.get<GuildState>(`/api/game/guilds/${guildId}`),
    enabled: !!guildId,
    staleTime: 60_000,
  });
}

// ─── useGuildChatQuery ────────────────────────────────────────────────────────
// Polls every 5 seconds. The backend returns PHI-scrubbed messages only.

export function useGuildChatQuery(guildId: string | null) {
  return useQuery({
    queryKey: queryKeys.guildChat(guildId ?? ''),
    queryFn: () =>
      apiClient.get<ChatMessage[]>(`/api/game/guilds/${guildId}/chat`),
    enabled: !!guildId,
    refetchInterval: 5_000,
    staleTime: 0,
  });
}

// ─── useSendChatMutation ──────────────────────────────────────────────────────

export function useSendChatMutation(guildId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (content: string) =>
      apiClient.post(`/api/game/guilds/${guildId}/chat`, { content }),

    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.guildChat(guildId) });
    },
  });
}

// ─── useCreateGuildMutation ───────────────────────────────────────────────────

export function useCreateGuildMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (name: string) =>
      apiClient.post<GuildState>('/api/game/guilds/create', { name }),

    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.gameState });
    },
  });
}

// ─── useJoinGuildMutation ─────────────────────────────────────────────────────

export function useJoinGuildMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (invite_code: string) =>
      apiClient.post<GuildState>('/api/game/guilds/join', { invite_code }),

    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.gameState });
    },
  });
}

// ─── useExportClinicalQuery ───────────────────────────────────────────────────
// Pro-gated. Returns the decrypted health history JSON.
// Only mounts inside the (clinical) route group after biometric auth.

export function useExportClinicalQuery(enabled = false) {
  return useQuery({
    queryKey: queryKeys.clinicalExport,
    queryFn: () => apiClient.get('/api/clinical/export'),
    enabled,
    staleTime: Infinity, // Export is expensive — never auto-refetch
    retry: false,
  });
}

// ─── useDeleteAccountMutation ─────────────────────────────────────────────────

export function useDeleteAccountMutation() {
  return useMutation({
    mutationFn: () => apiClient.delete('/api/health/account'),
  });
}

// ─── QueryClient factory ──────────────────────────────────────────────────────
// Called once in _layout.tsx to create the shared QueryClient instance.

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 2,
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 30_000),
        staleTime: 15_000,
      },
      mutations: {
        retry: 0,
      },
    },
  });
}
