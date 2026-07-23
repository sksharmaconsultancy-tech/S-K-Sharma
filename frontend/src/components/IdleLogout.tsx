/**
 * IdleLogout — Iter 247 (user request); Iter 266 per-role timeouts.
 *
 * Auto-logs out portal users after a period of NO activity (no touch,
 * click, key press or scroll). Works on desktop web, mobile PWA and native.
 * Iter 266 (user request): Super Admin & Sub Admin idle out after
 * 30 minutes; Company Admin stays at 10 minutes.
 */
import React, { useCallback, useEffect, useRef } from "react";
import { AppState, Platform, View } from "react-native";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";

// Per-role idle timeout (ms). Roles not listed fall back to 10 minutes.
const IDLE_MS_BY_ROLE: Record<string, number> = {
  super_admin: 30 * 60 * 1000, // 30 minutes
  sub_admin: 30 * 60 * 1000,   // 30 minutes
  company_admin: 10 * 60 * 1000, // 10 minutes
};
const DEFAULT_IDLE_MS = 10 * 60 * 1000;

const ADMIN_ROLES = ["super_admin", "sub_admin", "company_admin"];

export default function IdleLogout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const router = useRouter();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const active = !!user && ADMIN_ROLES.includes(user.role || "");
  const activeRef = useRef(active);
  activeRef.current = active;
  const idleMs = IDLE_MS_BY_ROLE[user?.role || ""] ?? DEFAULT_IDLE_MS;
  const idleMsRef = useRef(idleMs);
  idleMsRef.current = idleMs;

  const fire = useCallback(async () => {
    const mins = Math.round(idleMsRef.current / 60000);
    try { await logout(); } catch {}
    if (Platform.OS === "web") {
      try { globalThis.alert(`Logged out automatically after ${mins} minutes of inactivity.`); } catch {}
    }
    router.replace("/");
  }, [logout, router]);

  const reset = useCallback(() => {
    if (!activeRef.current) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(fire, idleMsRef.current);
  }, [fire]);

  useEffect(() => {
    if (!active) {
      if (timer.current) clearTimeout(timer.current);
      return;
    }
    reset();
    if (Platform.OS === "web" && typeof window !== "undefined") {
      const evs = ["mousedown", "keydown", "scroll", "touchstart", "mousemove"];
      let last = 0;
      const onAct = () => {
        const t = Date.now();
        if (t - last > 5000) { last = t; reset(); } // throttle resets
      };
      evs.forEach((e) => window.addEventListener(e, onAct, { passive: true }));
      return () => {
        evs.forEach((e) => window.removeEventListener(e, onAct));
        if (timer.current) clearTimeout(timer.current);
      };
    }
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") reset();
    });
    return () => {
      sub.remove();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [active, reset]);

  // Native: any touch anywhere resets the idle timer (non-blocking capture).
  return (
    <View
      style={{ flex: 1 }}
      onStartShouldSetResponderCapture={() => { reset(); return false; }}
    >
      {children}
    </View>
  );
}
