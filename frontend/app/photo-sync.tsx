/**
 * Iter 524 (user request) — Photo Sync / Reconciliation dashboard.
 *
 * Shows how many biometric punches have their punch-time photo, how many
 * are still syncing, and how many will never have one. "Retry Photo Sync"
 * re-runs the async Photo Matching Queue (parked ATTPHOTOs → punches).
 */
import React, { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Platform,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";
import DateField from "@/src/components/DateField";

type Stats = {
  total_punches: number;
  photos_received: number;
  photos_pending: number;
  photos_missing: number;
  failed_photo_sync: number;
  parked_photos: number;
};

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}
function daysAgoIso(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

const CARDS: {
  key: keyof Stats;
  label: string;
  icon: string;
  color: string;
  bg: string;
  hint: string;
}[] = [
  { key: "total_punches", label: "Total Punches", icon: "finger-print-outline",
    color: "#1E293B", bg: "#F1F5F9", hint: "Machine punches in the date range" },
  { key: "photos_received", label: "Photos Received", icon: "checkmark-circle-outline",
    color: "#15803D", bg: "#F0FDF4", hint: "Punch photo captured & linked ✓" },
  { key: "photos_pending", label: "Photos Pending", icon: "hourglass-outline",
    color: "#B45309", bg: "#FFFBEB", hint: "Photo arrived, matching in progress ⏳" },
  { key: "photos_missing", label: "Photos Missing", icon: "close-circle-outline",
    color: "#64748B", bg: "#F8FAFC", hint: "Device sent no photo for these punches" },
  { key: "failed_photo_sync", label: "Failed Photo Sync", icon: "alert-circle-outline",
    color: "#B91C1C", bg: "#FEF2F2", hint: "Parked photos older than 48h, never matched" },
  { key: "parked_photos", label: "Parked Photos (queue)", icon: "images-outline",
    color: "#7C3AED", bg: "#F5F3FF", hint: "Photos waiting in the matching queue" },
];

export default function PhotoSyncScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { companies, selectedCompanyId } = useSelectedCompany();
  const isAdmin =
    user?.role === "super_admin" || user?.role === "sub_admin" || user?.role === "company_admin";

  const [fromDate, setFromDate] = useState<string>(daysAgoIso(7));
  const [toDate, setToDate] = useState<string>(todayIso());
  const [firmId, setFirmId] = useState<string>(selectedCompanyId || "");
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [lastRetry, setLastRetry] = useState<string>("");

  const showMsg = (m: string) => {
    if (Platform.OS === "web") globalThis.alert(m);
  };

  const fetchStats = async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (fromDate) p.set("from_date", fromDate);
      if (toDate) p.set("to_date", toDate);
      if (firmId) p.set("company_id", firmId);
      const r = await api<Stats>(`/admin/punch-photos/reconciliation?${p.toString()}`);
      setStats(r);
    } catch (e: any) {
      showMsg(e?.message || "Failed to load photo sync stats");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStats(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const firmFirstRun = useRef(true);
  useEffect(() => {
    if (firmFirstRun.current) { firmFirstRun.current = false; return; }
    fetchStats();
  }, [firmId]);  // eslint-disable-line react-hooks/exhaustive-deps

  const retrySync = async () => {
    if (retrying) return;
    setRetrying(true);
    try {
      const r = await api<{ ok: boolean; scanned: number; matched: number }>(
        "/admin/punch-photos/retry-match", { method: "POST" });
      setLastRetry(`Re-scanned ${r.scanned} parked photo${r.scanned === 1 ? "" : "s"} · matched ${r.matched} to punches`);
      await fetchStats();
    } catch (e: any) {
      showMsg(e?.message || "Retry sync failed");
    } finally {
      setRetrying(false);
    }
  };

  if (!isAdmin) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <Text style={styles.subtitle}>Admin access only.</Text>
      </SafeAreaView>
    );
  }

  const pct = stats && stats.total_punches > 0
    ? Math.round((stats.photos_received / stats.total_punches) * 100)
    : 0;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="psync-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Photo Sync / Reconciliation</Text>
          <Text style={styles.subtitle}>
            Punch-time photo coverage — received, pending, missing &amp; failed
          </Text>
        </View>
        {user?.role !== "company_admin" ? (
          <Pressable
            onPress={retrySync}
            style={[styles.retryBtn, retrying && { opacity: 0.6 }]}
            disabled={retrying}
            testID="psync-retry"
          >
            {retrying ? (
              <ActivityIndicator color="#fff" size="small" />
            ) : (
              <Ionicons name="refresh-outline" size={16} color="#fff" />
            )}
            <Text style={styles.retryTxt}>Retry Photo Sync</Text>
          </Pressable>
        ) : null}
      </View>

      {/* Filters */}
      <View style={styles.filterCard}>
        <View style={styles.filterRow}>
          <View style={{ width: 150 }}>
            <Text style={styles.lbl}>From</Text>
            <DateField value={fromDate} onChangeISO={setFromDate} testID="psync-from" />
          </View>
          <View style={{ width: 150 }}>
            <Text style={styles.lbl}>To</Text>
            <DateField value={toDate} onChangeISO={setToDate} testID="psync-to" />
          </View>
          {user?.role !== "company_admin" ? (
            <View style={{ minWidth: 200 }}>
              <Text style={styles.lbl}>Firm</Text>
              {Platform.OS === "web" ? (
                <select
                  value={firmId}
                  onChange={(e) => setFirmId((e.target as HTMLSelectElement).value)}
                  style={styles.select as any}
                >
                  <option value="">All firms</option>
                  {companies.map((c: any) => (
                    <option key={c.company_id} value={c.company_id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              ) : null}
            </View>
          ) : null}
          <Pressable onPress={fetchStats} style={styles.applyBtn} testID="psync-apply">
            <Ionicons name="search-outline" size={15} color="#fff" />
            <Text style={styles.applyTxt}>Apply</Text>
          </Pressable>
        </View>
        {lastRetry ? <Text style={styles.retryInfo}>🔄 {lastRetry}</Text> : null}
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}>
        {loading ? (
          <ActivityIndicator size="large" color={colors.brand} style={{ marginTop: 40 }} />
        ) : stats ? (
          <>
            {/* Coverage bar */}
            <View style={styles.coverCard}>
              <Text style={styles.coverTitle}>
                Photo coverage: {pct}% of machine punches have a punch-time photo
              </Text>
              <View style={styles.coverTrack}>
                <View style={[styles.coverFill, { width: `${pct}%` as any }]} />
              </View>
            </View>

            <View style={styles.grid}>
              {CARDS.map((c) => (
                <Pressable
                  key={c.key}
                  style={[styles.card, { backgroundColor: c.bg }]}
                  testID={`psync-card-${c.key}`}
                  onPress={() => {
                    // deep-link the punch log filtered to the relevant state
                    const f = c.key === "photos_received" ? "available"
                      : c.key === "photos_pending" ? "pending"
                        : c.key === "photos_missing" ? "missing" : "";
                    if (f || c.key === "total_punches") {
                      router.push("/punch-log-report" as any);
                    }
                  }}
                >
                  <Ionicons name={c.icon as any} size={22} color={c.color} />
                  <Text style={[styles.cardNum, { color: c.color }]}>
                    {(stats[c.key] ?? 0).toLocaleString("en-IN")}
                  </Text>
                  <Text style={styles.cardLbl}>{c.label}</Text>
                  <Text style={styles.cardHint}>{c.hint}</Text>
                </Pressable>
              ))}
            </View>

            <View style={styles.noteBox}>
              <Ionicons name="information-circle-outline" size={16} color="#475569" />
              <Text style={styles.noteTxt}>
                Photos sync asynchronously — attendance is NEVER blocked or delayed if a
                photo is late. When a machine pushes the photo separately from the punch,
                it is parked in the matching queue and linked automatically (same machine +
                bio code, timestamp ±90s). Use &quot;Retry Photo Sync&quot; to re-run the queue
                manually.
              </Text>
            </View>
          </>
        ) : (
          <Text style={styles.empty}>No data.</Text>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  backBtn: { padding: 6 },
  title: { fontSize: type.lg, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: type.xs, color: colors.onSurfaceSecondary },
  retryBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#7C3AED",
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  retryTxt: { color: "#fff", fontWeight: "800", fontSize: type.sm },
  filterCard: {
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  filterRow: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, flexWrap: "wrap" },
  lbl: { fontSize: type.xs, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  select: {
    height: 38,
    borderRadius: 8,
    border: `1px solid ${colors.border}`,
    paddingHorizontal: 8,
    paddingVertical: 0,
    backgroundColor: colors.surface,
    color: colors.onSurface,
    fontSize: 13,
  },
  applyBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brand,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    height: 38,
  },
  applyTxt: { color: "#fff", fontWeight: "800", fontSize: type.sm },
  retryInfo: { marginTop: 8, fontSize: type.xs, fontWeight: "700", color: "#7C3AED" },
  coverCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  coverTitle: { fontSize: type.sm, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  coverTrack: {
    height: 10,
    borderRadius: 999,
    backgroundColor: "#E2E8F0",
    overflow: "hidden",
  },
  coverFill: { height: "100%", backgroundColor: "#15803D", borderRadius: 999 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  card: {
    minWidth: 180,
    flexGrow: 1,
    flexBasis: "30%",
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 4,
  },
  cardNum: { fontSize: 26, fontWeight: "900" },
  cardLbl: { fontSize: type.sm, fontWeight: "800", color: colors.onSurface },
  cardHint: { fontSize: type.xs, color: colors.onSurfaceSecondary },
  noteBox: {
    flexDirection: "row",
    gap: 8,
    marginTop: spacing.md,
    backgroundColor: "#F8FAFC",
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  noteTxt: { flex: 1, fontSize: type.xs, color: "#475569", lineHeight: 17 },
  empty: { textAlign: "center", marginTop: 40, color: colors.onSurfaceTertiary, fontSize: type.sm },
});
