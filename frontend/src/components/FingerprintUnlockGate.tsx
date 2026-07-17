/**
 * Iter 165 — App-unlock fingerprint gate for the Employee PWA.
 *
 * Shown once per app session for employees whose admin enabled
 * "Fingerprint verification" (and the firm has Bio Matrix Attendance ON).
 * Unsupported devices/browsers skip the gate silently.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import {
  fingerprintSupported, verifyFingerprint, enrollFingerprint,
} from "@/src/utils/fingerprintGate";
import { colors, radius, spacing } from "@/src/theme";

// Module-level: unlocked once per loaded session (resets on PWA reload).
let unlockedThisSession = false;

export default function FingerprintUnlockGate({
  userId, userName, children,
}: { userId: string; userName: string; children: React.ReactNode }) {
  const [state, setState] = useState<"checking" | "locked" | "open">(
    unlockedThisSession ? "open" : "checking");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const autoTried = useRef(false);

  const attempt = useCallback(async () => {
    setBusy(true); setMsg("");
    try {
      let r = await verifyFingerprint(userId, "Unlock the app");
      if (!r.ok && r.message === "NOT_ENROLLED") {
        const e = await enrollFingerprint(userId, userName);
        if (e.ok) {
          api("/me/fingerprint/enrolled", {
            method: "POST",
            body: { device: Platform.OS === "web" ? "web-pwa" : Platform.OS },
          }).catch(() => {});
          r = { ok: true, supported: true };
        } else {
          setMsg(e.message || "Fingerprint setup failed");
          setBusy(false);
          return;
        }
      }
      if (r.ok) {
        unlockedThisSession = true;
        setState("open");
      } else {
        setMsg(r.message || "Fingerprint failed — try again");
      }
    } finally { setBusy(false); }
  }, [userId, userName]);

  useEffect(() => {
    if (unlockedThisSession) return;
    (async () => {
      const supported = await fingerprintSupported();
      if (!supported) {
        // Silent fallback — device/browser has no fingerprint capability.
        unlockedThisSession = true;
        setState("open");
        return;
      }
      setState("locked");
    })();
  }, []);

  // Auto-trigger the prompt once when the lock screen first shows.
  useEffect(() => {
    if (state === "locked" && !autoTried.current) {
      autoTried.current = true;
      attempt();
    }
  }, [state, attempt]);

  if (state === "open") return <>{children}</>;
  if (state === "checking") {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={colors.brandPrimary} />
      </View>
    );
  }
  return (
    <View style={styles.center} testID="fp-unlock-gate">
      <View style={styles.iconWrap}>
        <Ionicons name="finger-print" size={56} color={colors.brandPrimary} />
      </View>
      <Text style={styles.title}>Fingerprint required</Text>
      <Text style={styles.sub}>
        Your employer requires fingerprint verification to open the app.
      </Text>
      {msg ? <Text style={styles.err}>{msg}</Text> : null}
      <Pressable
        onPress={attempt}
        disabled={busy}
        style={[styles.btn, busy && { opacity: 0.6 }]}
        testID="fp-unlock-btn"
      >
        {busy ? <ActivityIndicator color="#fff" /> : (
          <>
            <Ionicons name="finger-print" size={18} color="#fff" />
            <Text style={styles.btnTxt}>Unlock with fingerprint</Text>
          </>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface, padding: spacing.xl, gap: 10,
  },
  iconWrap: {
    width: 110, height: 110, borderRadius: 55,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center", justifyContent: "center", marginBottom: 6,
    borderWidth: 1, borderColor: colors.border,
  },
  title: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  sub: {
    fontSize: 13, color: colors.onSurfaceSecondary, textAlign: "center",
    maxWidth: 300,
  },
  err: { fontSize: 12.5, fontWeight: "600", color: "#DC2626", textAlign: "center" },
  btn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.brandPrimary, paddingHorizontal: 22,
    paddingVertical: 13, borderRadius: radius.md, marginTop: 10,
    minWidth: 220, justifyContent: "center",
  },
  btnTxt: { color: "#fff", fontSize: 14.5, fontWeight: "700" },
});
