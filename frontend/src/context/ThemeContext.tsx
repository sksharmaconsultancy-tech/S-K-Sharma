/**
 * Iter 85 — Theme Switcher context.
 *
 * Persists the admin's chosen theme id to AsyncStorage and mutates the
 * exported `colors` / `shadow` objects in-place via `applyThemePreset`.
 * A `version` counter is exposed so callers can key the root layout and
 * force every screen to re-mount with the new palette in a single frame.
 */
import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

import {
  applyThemePreset,
  DEFAULT_THEME_ID,
  THEME_PRESETS,
  ThemeId,
} from "@/src/theme";

const STORAGE_KEY = "sksharma.theme.id.v1";

type ThemeCtx = {
  themeId: ThemeId;
  themeName: string;
  version: number;
  ready: boolean;
  setThemeId: (id: ThemeId) => Promise<void>;
  presets: typeof THEME_PRESETS;
};

const ThemeContext = createContext<ThemeCtx | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [themeId, _setThemeId] = useState<ThemeId>(DEFAULT_THEME_ID);
  const [version, setVersion] = useState(0);
  const [ready, setReady] = useState(false);

  // Boot: read persisted id, apply it, then release the children.
  useEffect(() => {
    (async () => {
      try {
        const saved = await AsyncStorage.getItem(STORAGE_KEY);
        const id = (saved as ThemeId) || DEFAULT_THEME_ID;
        if (THEME_PRESETS.find(p => p.id === id)) {
          applyThemePreset(id);
          _setThemeId(id);
        }
      } catch {
        /* ignore — default palette is already applied */
      } finally {
        setReady(true);
      }
    })();
  }, []);

  const setThemeId = useCallback(async (id: ThemeId) => {
    applyThemePreset(id);
    _setThemeId(id);
    setVersion((v) => v + 1);
    try {
      await AsyncStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* non-fatal */
    }
    // Iter 85 (fix) — StyleSheet.create() snapshots colors at module load
    // time, so mutating `colors` alone does not restyle already-compiled
    // sheets. On the Web Portal we ALSO persist directly to localStorage
    // (theme.ts reads it synchronously at module boot), then force a
    // hard reload so every module re-evaluates and picks up the new
    // palette instantly.
    if (Platform.OS === "web") {
      try {
        (globalThis as any).localStorage?.setItem?.(STORAGE_KEY, id);
      } catch { /* noop */ }
      setTimeout(() => {
        try { (globalThis as any).location?.reload?.(); } catch { /* noop */ }
      }, 120);
    }
  }, []);

  const value = useMemo<ThemeCtx>(() => ({
    themeId,
    themeName: THEME_PRESETS.find(p => p.id === themeId)?.name || "Corporate Deep Teal",
    version,
    ready,
    setThemeId,
    presets: THEME_PRESETS,
  }), [themeId, version, ready, setThemeId]);

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    // Fallback so screens rendered outside the provider still work.
    return {
      themeId: DEFAULT_THEME_ID,
      themeName: "Corporate Deep Teal",
      version: 0,
      ready: true,
      setThemeId: async () => {},
      presets: THEME_PRESETS,
    };
  }
  return ctx;
}
