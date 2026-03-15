import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Building, GameUser, GuildInfo } from '../types';

// ─── State Shape ──────────────────────────────────────────────────────────────
// Mirrors the GameState TypeScript interface from the architecture doc.
// Non-sensitive: Mana balance, Avatar level, Sanctuary buildings, Guild info.
// Safe to hold in standard memory and persist to AsyncStorage.

interface GameState {
  user: GameUser;
  sanctuary: {
    buildings: Building[];
  };
  guild: GuildInfo;

  // Actions
  optimisticAddMana: (amount: number) => void;
  optimisticDeductMana: (amount: number) => void;
  optimisticDeductGems: (amount: number) => void;
  setGameState: (state: { user: GameUser; sanctuary: { buildings: Building[] }; guild: GuildInfo }) => void;
  setBuilding: (building: Building) => void;
  setGuild: (guild: GuildInfo) => void;
  reset: () => void;
}

const DEFAULT_USER: GameUser = {
  avatarLevel: 1,
  totalMana: 0,
  astralGems: 0,
};

const DEFAULT_STATE = {
  user: DEFAULT_USER,
  sanctuary: { buildings: [] },
  guild: { guildId: null, guildName: null, activeBossId: null },
};

export const useGameStore = create<GameState>()(
  persist(
    (set) => ({
      ...DEFAULT_STATE,

      // Optimistically update Mana before server confirmation.
      // If the server rejects, useGameStateQuery() overwrites this on next fetch.
      optimisticAddMana: (amount) =>
        set((state) => ({
          user: {
            ...state.user,
            totalMana: state.user.totalMana + amount,
          },
        })),

      optimisticDeductMana: (amount) =>
        set((state) => ({
          user: {
            ...state.user,
            totalMana: Math.max(0, state.user.totalMana - amount),
          },
        })),

      optimisticDeductGems: (amount) =>
        set((state) => ({
          user: {
            ...state.user,
            astralGems: Math.max(0, state.user.astralGems - amount),
          },
        })),

      // Called after useGameStateQuery() returns – overwrites local optimistic state
      // with the server-authoritative truth.
      setGameState: ({ user, sanctuary, guild }) =>
        set({ user, sanctuary, guild }),

      // Update a single building in the sanctuary list (e.g., after upgrade starts).
      setBuilding: (building) =>
        set((state) => ({
          sanctuary: {
            buildings: state.sanctuary.buildings.map((b) =>
              b.id === building.id ? building : b,
            ),
          },
        })),

      setGuild: (guild) => set({ guild }),

      reset: () => set(DEFAULT_STATE),
    }),
    {
      name: 'vq-game-store',
      storage: createJSONStorage(() => AsyncStorage),
    },
  ),
);
