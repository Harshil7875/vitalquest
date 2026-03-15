// ─── Design Token System ──────────────────────────────────────────────────────
// Two discrete themes toggled by routing state (game vs clinical).
// Consumers import `useTheme()` from ThemeProvider — never hardcode colors.

export const gameTheme = {
  name: 'game' as const,

  colors: {
    // Primaries
    background: '#0d0520',
    surface: '#1a0a2e',
    surfaceAlt: '#251040',
    border: '#3d1f6e',

    // Brand
    primary: '#a855f7',       // Mystic Purple
    primaryLight: '#c084fc',
    secondary: '#10b981',     // Deep Emerald
    secondaryLight: '#34d399',
    accent: '#f59e0b',        // Gold / Mana colour
    accentLight: '#fbbf24',

    // Semantic
    success: '#22c55e',
    warning: '#f59e0b',
    danger: '#ef4444',
    info: '#3b82f6',

    // Text
    textPrimary: '#f3e8ff',
    textSecondary: '#c4b5fd',
    textMuted: '#7c3aed',
    textOnAccent: '#0d0520',
  },

  typography: {
    fontHeader: 'Merriweather',      // Stylised serif – loaded via expo-font
    fontBody: 'Merriweather',
    fontMono: 'SpaceMono',

    sizeXs: 11,
    sizeSm: 13,
    sizeMd: 15,
    sizeLg: 18,
    sizeXl: 24,
    size2xl: 32,
    size3xl: 48,

    weightRegular: '400' as const,
    weightBold: '700' as const,
    weightBlack: '900' as const,
  },

  spacing: {
    xs: 4,
    sm: 8,
    md: 16,
    lg: 24,
    xl: 32,
    xxl: 48,
  },

  radii: {
    sm: 8,
    md: 16,
    lg: 24,
    full: 9999,
  },

  shadows: {
    card: {
      shadowColor: '#a855f7',
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 0.4,
      shadowRadius: 12,
      elevation: 8,
    },
    glow: {
      shadowColor: '#f59e0b',
      shadowOffset: { width: 0, height: 0 },
      shadowOpacity: 0.8,
      shadowRadius: 16,
      elevation: 12,
    },
  },

  animation: {
    // Spring physics for game feel
    spring: { damping: 10, stiffness: 200, mass: 1 },
    duration: { fast: 150, normal: 300, slow: 500 },
  },
} as const;

export const clinicalTheme = {
  name: 'clinical' as const,

  colors: {
    background: '#f8fafc',
    surface: '#ffffff',
    surfaceAlt: '#f1f5f9',
    border: '#e2e8f0',

    primary: '#1d4ed8',       // Trust Blue
    primaryLight: '#3b82f6',
    secondary: '#0f766e',     // Teal
    secondaryLight: '#14b8a6',
    accent: '#0369a1',
    accentLight: '#0284c7',

    success: '#16a34a',
    warning: '#d97706',
    danger: '#dc2626',
    info: '#0369a1',

    textPrimary: '#0f172a',
    textSecondary: '#475569',
    textMuted: '#94a3b8',
    textOnAccent: '#ffffff',
  },

  typography: {
    fontHeader: 'Inter',
    fontBody: 'Inter',
    fontMono: 'SpaceMono',

    sizeXs: 11,
    sizeSm: 13,
    sizeMd: 15,
    sizeLg: 18,
    sizeXl: 22,
    size2xl: 28,
    size3xl: 36,

    weightRegular: '400' as const,
    weightBold: '600' as const,
    weightBlack: '800' as const,
  },

  spacing: {
    xs: 4,
    sm: 8,
    md: 16,
    lg: 24,
    xl: 32,
    xxl: 48,
  },

  radii: {
    sm: 2,
    md: 4,
    lg: 8,
    full: 9999,
  },

  shadows: {
    card: {
      shadowColor: '#94a3b8',
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.12,
      shadowRadius: 4,
      elevation: 2,
    },
    glow: {
      shadowColor: '#1d4ed8',
      shadowOffset: { width: 0, height: 0 },
      shadowOpacity: 0.1,
      shadowRadius: 6,
      elevation: 3,
    },
  },

  animation: {
    // Minimal linear fades – no distracting motion near medical data
    spring: { damping: 30, stiffness: 400, mass: 1 },
    duration: { fast: 100, normal: 200, slow: 350 },
  },
} as const;

export type GameTheme = typeof gameTheme;
export type ClinicalTheme = typeof clinicalTheme;
export type AppTheme = GameTheme | ClinicalTheme;
