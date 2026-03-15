import React, { createContext, useContext, useState } from 'react';
import { gameTheme, clinicalTheme, AppTheme } from './tokens';

type ThemeMode = 'game' | 'clinical';

interface ThemeContextValue {
  theme: AppTheme;
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
  toggleClinical: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>('game');

  const theme = mode === 'game' ? gameTheme : clinicalTheme;

  const toggleClinical = () =>
    setMode((prev) => (prev === 'game' ? 'clinical' : 'game'));

  return (
    <ThemeContext.Provider value={{ theme, mode, setMode, toggleClinical }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>');
  return ctx;
}
