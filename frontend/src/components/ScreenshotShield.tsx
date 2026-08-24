/**
 * Iter 708 — firm-wise Screenshot Protection for the Employee PWA.
 * Mounted once in the root layout. When the employee's firm enables
 * screenshot_protection:
 *  - Native builds: expo-screen-capture prevents screenshots/recording.
 *  - Web/PWA: masks content on blur/visibility-change (app-switcher
 *    thumbnails), blocks context-menu/copy/print, detects PrintScreen and
 *    shows "Screenshot is restricted by your organization.", and renders a
 *    light employee-name watermark over the app.
 * Browsers cannot guarantee 100% prevention — strongest supported applied.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Platform } from "react-native";
import * as ScreenCapture from "expo-screen-capture";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";

export default function ScreenshotShield() {
  const { user } = useAuth();
  const [policy, setPolicy] = useState<{ screenshot_protection: boolean; watermark?: string } | null>(null);
  const [masked, setMasked] = useState(false);
  const [warn, setWarn] = useState(false);

  useEffect(() => {
    if (!user || user.role !== "employee") { setPolicy(null); return; }
    api<any>("/pwa-policy").then(setPolicy).catch(() => {});
  }, [user]);

  const on = !!policy?.screenshot_protection && user?.role === "employee";

  // Native prevention (installed app builds).
  useEffect(() => {
    if (Platform.OS === "web" || !on) return;
    ScreenCapture.preventScreenCaptureAsync("sks-shield").catch(() => {});
    const sub = ScreenCapture.addScreenshotListener?.(() => {
      setWarn(true);
      setTimeout(() => setWarn(false), 2500);
    });
    return () => {
      ScreenCapture.allowScreenCaptureAsync("sks-shield").catch(() => {});
      sub?.remove?.();
    };
  }, [on]);

  // Web/PWA protections.
  useEffect(() => {
    if (Platform.OS !== "web" || !on) return;
    const showWarn = () => { setWarn(true); setTimeout(() => setWarn(false), 2500); };
    const onVis = () => setMasked(document.visibilityState === "hidden");
    const onBlur = () => setMasked(true);
    const onFocus = () => setMasked(false);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "PrintScreen") {
        try { navigator.clipboard?.writeText(""); } catch { /* best effort */ }
        showWarn();
      }
      if ((e.ctrlKey || e.metaKey) && ["p", "P"].includes(e.key)) {
        e.preventDefault(); showWarn();
      }
    };
    const block = (e: Event) => { e.preventDefault(); };
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", onFocus);
    window.addEventListener("keyup", onKey);
    window.addEventListener("keydown", onKey);
    document.addEventListener("contextmenu", block);
    document.addEventListener("copy", block);
    const prevSelect = document.body.style.userSelect;
    document.body.style.userSelect = "none";
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("keyup", onKey);
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("contextmenu", block);
      document.removeEventListener("copy", block);
      document.body.style.userSelect = prevSelect;
    };
  }, [on]);

  if (!on) return null;
  const wm = policy?.watermark || "";

  return (
    <>
      {/* Employee watermark — very light, never blocks touches */}
      {wm ? (
        <View pointerEvents="none" style={s.wmWrap}>
          {Array.from({ length: 12 }).map((_, i) => (
            <Text key={i} style={[s.wmTxt, { transform: [{ rotate: "-24deg" }] }]}>{wm}</Text>
          ))}
        </View>
      ) : null}
      {/* Background/app-switcher mask */}
      {masked ? (
        <View style={s.mask} pointerEvents="none">
          <Text style={s.maskT}>🔒 Content hidden</Text>
        </View>
      ) : null}
      {warn ? (
        <View style={s.warn} pointerEvents="none">
          <Text style={s.warnT}>Screenshot is restricted by your organization.</Text>
        </View>
      ) : null}
    </>
  );
}

const s = StyleSheet.create({
  wmWrap: {
    ...StyleSheet.absoluteFillObject, zIndex: 9998, flexDirection: "row",
    flexWrap: "wrap", alignItems: "center", justifyContent: "space-around",
    opacity: 0.05,
  },
  wmTxt: { fontSize: 15, fontWeight: "800", color: "#111", margin: 30 },
  mask: {
    ...StyleSheet.absoluteFillObject, zIndex: 9999, backgroundColor: "#111827",
    alignItems: "center", justifyContent: "center",
  },
  maskT: { color: "#fff", fontSize: 15, fontWeight: "800" },
  warn: {
    position: "absolute", bottom: 90, left: 20, right: 20, zIndex: 10000,
    backgroundColor: "#DC2626", borderRadius: 12, padding: 12, alignItems: "center",
  },
  warnT: { color: "#fff", fontSize: 12.5, fontWeight: "800", textAlign: "center" },
});
