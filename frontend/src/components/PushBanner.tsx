/**
 * Iter 145 — "Enable notifications" banner (PWA / web only).
 *
 *  • Hidden on native, unsupported browsers, or when permission is denied.
 *  • If permission is already granted → silently (re)syncs the subscription
 *    with the backend and renders nothing.
 *  • Otherwise shows a small dismissible card; tapping "Enable" triggers
 *    the native permission prompt (user-gesture requirement).
 */
import React, { useEffect, useState } from "react";
import { View, Text, Pressable, StyleSheet, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import {
  isPushSupported,
  pushPermission,
  isSubscribed,
  subscribeToPush,
} from "@/src/utils/push";
import { radius, spacing } from "@/src/theme";

const DISMISS_KEY = "sks_push_banner_dismissed";

export default function PushBanner() {
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isPushSupported()) return;
    (async () => {
      const perm = pushPermission();
      if (perm === "denied") return;
      if (perm === "granted") {
        // Permission already granted — just make sure the backend has the
        // (current user's) subscription, then stay hidden.
        if (!(await isSubscribed())) await subscribeToPush();
        else await subscribeToPush(); // re-binds endpoint to current login
        return;
      }
      // permission === "default" → offer to enable, unless dismissed before.
      try {
        if (globalThis.localStorage?.getItem(DISMISS_KEY) === "1") return;
      } catch {}
      setVisible(true);
    })();
  }, []);

  if (!visible || Platform.OS !== "web") return null;

  const enable = async () => {
    setBusy(true);
    const res = await subscribeToPush();
    setBusy(false);
    if (res.ok || res.reason === "denied" || res.reason === "no_sw") setVisible(false);
  };

  const dismiss = () => {
    try {
      globalThis.localStorage?.setItem(DISMISS_KEY, "1");
    } catch {}
    setVisible(false);
  };

  return (
    <View style={styles.card}>
      <View style={styles.iconWrap}>
        <Ionicons name="notifications-outline" size={20} color="#fff" />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.title}>Enable notifications</Text>
        <Text style={styles.sub}>
          Get alerts for punch approvals, leave decisions & joining requests.
        </Text>
      </View>
      <Pressable style={styles.btn} onPress={enable} disabled={busy}>
        <Text style={styles.btnText}>{busy ? "…" : "Enable"}</Text>
      </Pressable>
      <Pressable onPress={dismiss} hitSlop={8} style={styles.close}>
        <Ionicons name="close" size={18} color="#94a3b8" />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing?.sm ?? 10,
    backgroundColor: "#eef2ff",
    borderColor: "#c7d2fe",
    borderWidth: 1,
    borderRadius: radius?.lg ?? 14,
    paddingVertical: 10,
    paddingHorizontal: 12,
    marginHorizontal: 16,
    marginBottom: 10,
  },
  iconWrap: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: "#6366f1",
    alignItems: "center",
    justifyContent: "center",
  },
  title: { fontWeight: "700", fontSize: 13.5, color: "#1e1b4b" },
  sub: { fontSize: 11.5, color: "#4338ca", marginTop: 1 },
  btn: {
    backgroundColor: "#6366f1",
    borderRadius: 10,
    paddingVertical: 8,
    paddingHorizontal: 14,
    minHeight: 36,
    justifyContent: "center",
  },
  btnText: { color: "#fff", fontWeight: "700", fontSize: 12.5 },
  close: { padding: 4 },
});
