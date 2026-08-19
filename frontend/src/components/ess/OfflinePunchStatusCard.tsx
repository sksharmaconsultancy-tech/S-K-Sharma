/**
 * Iter 615 (ESS Phase 2) — Offline punch queue visibility on the employee
 * home screen. Shows queued (unsynced) punches, last sync time, network
 * state and a manual "Sync now" action. Renders only when the firm allows
 * offline punching OR punches are actually waiting in the queue.
 */
import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import {
  flushPunchQueue, isOnline, offlinePunchAllowed, onSyncResult, queuedPunchCount,
} from "@/src/sdk/offlineQueue";
import { getLastSync } from "@/src/utils/offlinePunch";
import { colors, radius, shadow, spacing } from "@/src/theme";

export default function OfflinePunchStatusCard() {
  const [enabled, setEnabled] = useState(false);
  const [pending, setPending] = useState(0);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [online, setOnline] = useState(isOnline());
  const [syncing, setSyncing] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setPending(await queuedPunchCount());
      setLastSync(await getLastSync());
    } catch { /* non-fatal */ }
  }, []);

  useEffect(() => {
    offlinePunchAllowed().then(setEnabled).catch(() => {});
    refresh();
    const unsub = onSyncResult((r) => {
      setPending(r.remaining);
      getLastSync().then(setLastSync).catch(() => {});
    });
    let offWeb: (() => void) | undefined;
    if (Platform.OS === "web" && typeof window !== "undefined") {
      const on = () => { setOnline(true); refresh(); };
      const off = () => setOnline(false);
      window.addEventListener("online", on);
      window.addEventListener("offline", off);
      offWeb = () => {
        window.removeEventListener("online", on);
        window.removeEventListener("offline", off);
      };
    }
    return () => { unsub(); offWeb?.(); };
  }, [refresh]);

  const syncNow = async () => {
    if (syncing) return;
    setSyncing(true);
    try { await flushPunchQueue(); } catch { /* result via onSyncResult */ }
    await refresh();
    setSyncing(false);
  };

  if (!enabled && pending === 0) return null;

  const allSynced = pending === 0;
  return (
    <View
      style={[s.card, !allSynced && { borderColor: "#FDE68A", backgroundColor: "#FFFBEB" }]}
      testID="ess-offline-punch-card"
    >
      <View style={s.headRow}>
        <Ionicons
          name={allSynced ? "cloud-done-outline" : "cloud-offline-outline"}
          size={16}
          color={allSynced ? "#059669" : "#B45309"}
        />
        <Text style={s.title}>
          {allSynced ? "Offline punches — all synced" : `${pending} punch${pending > 1 ? "es" : ""} waiting to sync`}
        </Text>
        <View style={{ flex: 1 }} />
        <View style={[s.netDot, { backgroundColor: online ? "#059669" : "#DC2626" }]} />
        <Text style={s.netTxt}>{online ? "Online" : "Offline"}</Text>
      </View>
      <View style={s.row}>
        <Text style={s.sub}>
          {lastSync
            ? `Last sync ${new Date(lastSync).toLocaleString("en-IN", {
                day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
              })}`
            : "No sync yet"}
        </Text>
        <View style={{ flex: 1 }} />
        {pending > 0 ? (
          <Pressable
            style={[s.btn, (!online || syncing) && { opacity: 0.5 }]}
            onPress={syncNow}
            disabled={!online || syncing}
            testID="ess-offline-sync-now"
          >
            {syncing ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Ionicons name="sync-outline" size={14} color="#fff" />
            )}
            <Text style={s.btnTxt}>Sync now</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.borderLight, padding: spacing.md, gap: 8,
    marginBottom: spacing.sm, ...shadow.sm,
  },
  headRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  row: { flexDirection: "row", alignItems: "center" },
  sub: { fontSize: 11, color: colors.onSurfaceSecondary },
  netDot: { width: 7, height: 7, borderRadius: 4 },
  netTxt: { fontSize: 10.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginLeft: 4 },
  btn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 8, minHeight: 34,
  },
  btnTxt: { color: "#fff", fontSize: 12, fontWeight: "700" },
});
