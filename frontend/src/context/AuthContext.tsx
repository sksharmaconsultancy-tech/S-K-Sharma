import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
} from "react";
import { AppState, Platform } from "react-native";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import { router } from "expo-router";
import { api, saveToken, clearToken } from "@/src/api/client";
import {
  authenticateBiometric,
  getBiometricCapability,
  isBiometricEnabled,
  setBiometricEnabled as persistBiometricEnabled,
} from "@/src/utils/biometric";
import {
  refreshRemindersOnBoot,
  setReminderFirmName,
} from "@/src/utils/punchReminders";

export type Role = "employee" | "company_admin" | "super_admin";

export interface AuthUser {
  user_id: string;
  email: string;
  name: string;
  picture?: string | null;
  role: Role;
  company_id?: string | null;
  department?: string | null;
  position?: string | null;
  employee_code?: string | null;
  father_name?: string | null;
  dob?: string | null;
  doj?: string | null;
  shift_start?: string | null;
  shift_end?: string | null;
  salary_monthly?: number | null;
  half_day_hrs?: number | null;
  full_day_hrs?: number | null;
  onboarded?: boolean;
  exit_date?: string | null;
  offboarded?: boolean;
  company_name?: string | null;
  company?: {
    company_id: string;
    name?: string | null;
    address?: string | null;
    office_lat?: number | null;
    office_lng?: number | null;
    geofence_radius_m?: number | null;
    auto_punch_enabled?: boolean;
    face_match_enabled?: boolean;
  } | null;
  approval_status?: "pending" | "approved" | "rejected" | null;
  approval_pending?: boolean;
  approval_rejected?: boolean;
  approval_note?: string | null;
  phone?: string | null;
  has_pin?: boolean;
  pin_must_change?: boolean;
  is_live_in?: boolean;
  // Per-employee override of auto-punch (None = inherit company)
  auto_punch_enabled?: boolean | null;
  // Server-computed effective setting: company + per-user + live-in
  effective_auto_punch?: boolean;
}

interface AuthCtx {
  user: AuthUser | null;
  loading: boolean;
  authError: string | null;
  login: () => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  clearAuthError: () => void;
  // Biometric unlock
  biometricEnabled: boolean;
  biometricSupported: boolean;
  biometricLabel: string;
  biometricLocked: boolean;
  enableBiometric: () => Promise<boolean>;
  disableBiometric: () => Promise<void>;
  unlockWithBiometric: () => Promise<boolean>;
}

const Ctx = createContext<AuthCtx>({
  user: null,
  loading: true,
  authError: null,
  login: async () => {},
  logout: async () => {},
  refresh: async () => {},
  clearAuthError: () => {},
  biometricEnabled: false,
  biometricSupported: false,
  biometricLabel: "Biometric",
  biometricLocked: false,
  enableBiometric: async () => false,
  disableBiometric: async () => {},
  unlockWithBiometric: async () => false,
});

export function useAuth() {
  return useContext(Ctx);
}

function extractSessionId(url: string): string | null {
  try {
    const hashIdx = url.indexOf("#");
    const hash = hashIdx >= 0 ? url.substring(hashIdx + 1) : "";
    const hp = new URLSearchParams(hash);
    if (hp.get("session_id")) return hp.get("session_id");
    const qIdx = url.indexOf("?");
    if (qIdx >= 0) {
      const qp = new URLSearchParams(url.substring(qIdx + 1));
      if (qp.get("session_id")) return qp.get("session_id");
    }
  } catch {}
  return null;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);

  // Biometric state
  const [biometricEnabled, setBiometricEnabledState] = useState(false);
  const [biometricSupported, setBiometricSupported] = useState(false);
  const [biometricLabel, setBiometricLabel] = useState("Biometric");
  const [biometricLocked, setBiometricLocked] = useState(false);
  const appStateRef = useRef(AppState.currentState);
  const backgroundedAtRef = useRef<number | null>(null);

  /**
   * Iter 70 — Whenever the user object changes we push the firm name
   * to AsyncStorage so the daily punch-reminder notification body
   * always names the correct employer (e.g. "Welcome to Sri Rajaneshwari
   * Textiles ☀️" instead of the hard-coded parent brand).  We also
   * re-run the boot scheduler so a live firm-switch reschedules the
   * daily notifications with the new copy immediately — no restart
   * required.
   */
  useEffect(() => {
    (async () => {
      try {
        const firm =
          (user?.company_name as any) ||
          (user as any)?.company?.name ||
          null;
        await setReminderFirmName(firm || null);
        if (user) {
          // Re-schedule so any live text update takes effect.
          await refreshRemindersOnBoot();
        }
      } catch {
        // Never let a notification blip break the auth flow.
      }
    })();
  }, [user?.user_id, user?.company_id]);

  const clearAuthError = useCallback(() => setAuthError(null), []);

  const refresh = useCallback(async () => {
    try {
      const res = await api<{ user: AuthUser }>("/auth/me");
      setUser(res.user);
    } catch (e: any) {
      // Only sign the user out on a true authentication failure (401 /
      // "Invalid token"). Transient issues (network drops, 5xx, offline)
      // should NOT auto-logout — we keep the previous user in state.
      const msg = (e?.message || "").toLowerCase();
      const isAuthFailure =
        msg.includes("401") ||
        msg.includes("invalid token") ||
        msg.includes("invalid session") ||
        msg.includes("session expired") ||
        msg.includes("not authenticated") ||
        msg.includes("missing bearer");
      if (isAuthFailure) {
        await clearToken();
        // Iter 95h — an EXPIRED/INVALID session used to leave the user
        // stranded on admin screens showing "Admins only" with no way
        // out ("Not able to open ..."). On web, hard-navigate to the
        // login page so they can sign in again. NEVER redirect when we
        // are already at "/", or the login page reload-loops forever.
        if (Platform.OS === "web") {
          try {
            const path = window.location.pathname || "/";
            // Public entry / login routes are reachable without a session —
            // never bounce the user off them (would break the /employer &
            // /employee deep links and reload-loop on the login pages).
            const PUBLIC_PREFIXES = [
              "/employer", "/employee", "/admin-pin-login", "/pin-login",
              "/company-login", "/company-register", "/emp-code-login",
              "/employee-signup", "/admin-set-password", "/firm-select",
            ];
            const isPublic = path === "/" || path === "" ||
              PUBLIC_PREFIXES.some((p) => path === p || path.startsWith(p + "/"));
            if (!isPublic) {
              window.location.assign("/");
              return;
            }
          } catch {}
        }
        setUser(null);
      }
      // else: keep the existing user; the app can retry silently.
    }
  }, []);

  const exchange = useCallback(async (sessionId: string) => {
    try {
      const res = await api<{ session_token: string; user: AuthUser }>(
        "/auth/session",
        { method: "POST", body: { session_id: sessionId }, auth: false }
      );
      await saveToken(res.session_token);
      setUser(res.user);
      setAuthError(null);
    } catch (e: any) {
      const msg =
        (e && e.message) ||
        "We couldn't complete your sign-in. Please try again.";
      setAuthError(msg);
      throw e;
    }
  }, []);

  // ------------------------------------------------------------------
  // Biometric unlock
  // ------------------------------------------------------------------
  const enableBiometric = useCallback(async (): Promise<boolean> => {
    const cap = await getBiometricCapability();
    if (!cap.supported) return false;
    // Ask the user to authenticate once — this proves the device biometric
    // matches whoever is currently signed in before we persist the flag.
    const ok = await authenticateBiometric(
      `Enable ${cap.primaryLabel} unlock for S.K. Sharma & Co.`,
    );
    if (!ok) return false;
    await persistBiometricEnabled(true);
    setBiometricEnabledState(true);
    setBiometricSupported(true);
    setBiometricLabel(cap.primaryLabel);
    return true;
  }, []);

  const disableBiometric = useCallback(async () => {
    await persistBiometricEnabled(false);
    setBiometricEnabledState(false);
    setBiometricLocked(false);
  }, []);

  const unlockWithBiometric = useCallback(async (): Promise<boolean> => {
    const cap = await getBiometricCapability();
    if (!cap.supported) {
      setBiometricLocked(false);
      return false;
    }
    const ok = await authenticateBiometric(
      `Unlock S.K. Sharma & Co. with ${cap.primaryLabel}`,
    );
    if (ok) {
      setBiometricLocked(false);
    }
    return ok;
  }, []);

  useEffect(() => {
    (async () => {
      try {
        if (Platform.OS === "web") {
          const url = window.location.href;
          const sid = extractSessionId(url);
          if (sid) {
            try {
              await exchange(sid);
            } catch {}
            try {
              window.history.replaceState(null, "", window.location.pathname);
            } catch {}
            setLoading(false);
            return;
          }
        } else {
          const initial = await Linking.getInitialURL();
          if (initial) {
            const sid = extractSessionId(initial);
            if (sid) {
              try {
                await exchange(sid);
              } catch {}
              setLoading(false);
              return;
            }
          }
        }
        await refresh();
      } finally {
        setLoading(false);
      }

      // Once auth state is settled, initialise biometric capability + lock.
      try {
        const [cap, enabled] = await Promise.all([
          getBiometricCapability(),
          isBiometricEnabled(),
        ]);
        setBiometricSupported(cap.supported);
        setBiometricLabel(cap.primaryLabel);
        // Only lock if the feature is enabled AND the device still supports
        // it AND we actually have an authenticated user (checked via token).
        if (cap.supported && enabled) {
          setBiometricEnabledState(true);
          // Read token indirectly via /auth/me — if refresh succeeded, we
          // already have a user in state. Lock only when user is present.
          setBiometricLocked(true);
        } else {
          setBiometricEnabledState(!!enabled);
        }
      } catch {}
    })();

    const sub = Linking.addEventListener("url", async ({ url }) => {
      const sid = extractSessionId(url);
      if (sid) {
        try {
          await exchange(sid);
        } catch (e) {
          console.warn("exchange failed", e);
        }
      }
    });
    return () => sub.remove();
  }, [exchange, refresh]);

  // Re-lock when the app is brought back to the foreground after a long
  // pause (>= 30 s). This keeps the UX snappy for quick task-switches while
  // still protecting content when the user leaves for a while.
  useEffect(() => {
    if (Platform.OS === "web") return;
    const sub = AppState.addEventListener("change", (next) => {
      const prev = appStateRef.current;
      if (prev.match(/active/) && next.match(/inactive|background/)) {
        backgroundedAtRef.current = Date.now();
      } else if (
        (prev === "background" || prev === "inactive") &&
        next === "active"
      ) {
        const backgroundedAt = backgroundedAtRef.current;
        backgroundedAtRef.current = null;
        if (
          user &&
          biometricEnabled &&
          biometricSupported &&
          backgroundedAt &&
          Date.now() - backgroundedAt >= 30_000
        ) {
          setBiometricLocked(true);
        }
      }
      appStateRef.current = next;
    });
    return () => sub.remove();
  }, [biometricEnabled, biometricSupported, user]);

  const login = useCallback(async () => {
    // NOTE: We must redirect back to the app root ("/") so Expo Router lands on
    // the index screen (which already handles session_id extraction via
    // AuthContext). Redirecting to "/auth" caused "Unmatched Route" on Expo Go
    // because no /auth screen exists.
    const redirect =
      Platform.OS === "web"
        ? window.location.origin + "/"
        : Linking.createURL("/");
    const authUrl = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirect)}`;

    if (Platform.OS === "web") {
      window.location.href = authUrl;
      return;
    }

    const result = await WebBrowser.openAuthSessionAsync(authUrl, redirect);
    if (result.type === "success" && result.url) {
      const sid = extractSessionId(result.url);
      if (sid) {
        await exchange(sid);
      }
    }
  }, [exchange]);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {}
    await clearToken();
    setBiometricLocked(false);
    // Iter 67 — Wipe the persisted firm selection on logout so the next
    // Sub-Admin sign-in lands cleanly on the firm-select gate.
    if (Platform.OS === "web") {
      try {
        (globalThis as any).localStorage?.removeItem("skc:selected_company");
        // Iter 94 — also drop the session-lock flag; a stale lock without
        // a selection used to block the firm picker after re-login.
        (globalThis as any).localStorage?.removeItem("skc:selected_company_locked");
      } catch {}
    }
    // On web, hard-navigate FIRST (before setUser(null)) so mounted guarded
    // components don't briefly re-render with user=null and trigger a render
    // loop before the full-page reload takes effect.
    if (Platform.OS === "web") {
      try {
        window.location.assign("/");
        return;
      } catch {}
    }
    setUser(null);
    setAuthError(null);
    try {
      (router as any).dismissAll?.();
    } catch {}
    try {
      router.replace("/");
    } catch {}
  }, []);

  return (
    <Ctx.Provider
      value={{
        user,
        loading,
        authError,
        login,
        logout,
        refresh,
        clearAuthError,
        biometricEnabled,
        biometricSupported,
        biometricLabel,
        biometricLocked,
        enableBiometric,
        disableBiometric,
        unlockWithBiometric,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}
