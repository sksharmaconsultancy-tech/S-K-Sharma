/**
 * IdleLogout — Iter 247 (user request).
 *
 * Auto-logs out portal users (super/sub/company admins) after 10 minutes
 * of NO activity (no touch, click, key press or scroll). Works on desktop
 * web, mobile PWA and native.
 */
import React, { useCallback, useEffect, useRef } from "react";
import { AppState, Platform, View } from "react-native";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";

const IDLE_MS = 10 * 60 * 1000; // 10 minutes

const ADMIN_ROLES = ["super_admin", "sub_admin", "company_admin"];

export default function IdleLogout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const router = useRouter();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const active = !!user && ADMIN_ROLES.includes(user.role || "");
  const activeRef = useRef(active);
  activeRef.current = active;

  const fire = useCallback(async () => {
    try { await logout(); } catch {}
    if (Platform.OS === "web") {
      try { globalThis.alert("Logged out automatically after 10 minutes of inactivity."); } catch {}
    }
    router.replace("/");
  }, [logout, router]);

  const reset = useCallback(() => {
    if (!activeRef.current) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(fire, IDLE_MS);
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
