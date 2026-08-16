/**
 * Iter 587 — Export History (RBAC Phase 2).
 * Central audit trail of every data export (Excel/CSV/PDF): who exported
 * what, when, for which firm/period, how many records — plus DENIED
 * attempts (blocked by the export permission gate). Values are never
 * stored, only metadata.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

const FILTERS = [
  { key: "", label: "All" },
  { key: "SUCCESS", label: "Successful" },
  { key: "DENIED", label: "Denied" },
];

export default function ExportHistoryScreen() {
  const router = useRouter();
  const [filter, setFilter] = useState("");
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (f: string) => {
    setLoading(true); setError(null);
    try {
      const r = await api<{ exports: any[] }>(
        `/admin/export-history${f ? `?status=${f}` : ""}`);
      setRows(r.exports || []);
    } catch (e: any) { setError(e.message || "Failed to load export history"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(filter); }, [filter, load]);

  const fmtAt = (iso?: string) => {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return `${d.toLocaleDateString("en-IN")} ${d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`;
    } catch { return iso; }
  };

  return (
    <SafeAreaView style={st.root} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} style={{ padding: 6 }}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.h1}>Export History</Text>
          <Text style={st.sub}>Every export & denied attempt — full audit trail</Text>
        </View>
      </View>
      <View style={st.tabs}>
        {FILTERS.map((f) => (
          <Pressable key={f.key} onPress={() => setFilter(f.key)}
            style={[st.tab, filter === f.key && st.tabOn]}
            testID={`eh-tab-${f.label}`}>
            <Text style={[st.tabTxt, filter === f.key && st.tabTxtOn]}>{f.label}</Text>
          </Pressable>
        ))}
      </View>
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, gap: 10, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={false} onRefresh={() => void load(filter)} />}
      >
        {loading ? <ActivityIndicator color={colors.brandPrimary} /> : null}
        {error ? <Text style={{ color: "#DC2626" }}>{error}</Text> : null}
        {!loading && rows.length === 0 ? (
          <Text style={st.empty}>No export activity yet.</Text>
        ) : null}
        {rows.map((r, i) => {
          const denied = r.action === "EXPORT_DENIED";
          const d = r.detail || {};
          return (
            <View key={r.log_id || i} style={[st.card, denied && st.cardDenied]}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <Ionicons
                  name={denied ? "close-circle" : "download-outline"}
                  size={18} color={denied ? "#DC2626" : "#16A34A"} />
                <Text style={st.name}>{d.report || "Export"}</Text>
                <View style={[st.badge, { backgroundColor: denied ? "#FEE2E2" : "#DCFCE7" }]}>
                  <Text style={[st.badgeTxt, { color: denied ? "#B91C1C" : "#166534" }]}>
                    {denied ? "DENIED" : "SUCCESS"}
                  </Text>
                </View>
              </View>
              <Text style={st.line}>
                {r.user_name || r.user_id} ({r.role}) · {fmtAt(r.at)}
              </Text>
              <Text style={st.line}>
                {d.export_id ? `ID ${d.export_id} · ` : ""}
                Format {String(d.format || "—").toUpperCase()}
                {d.period ? ` · Period ${d.period}` : ""}
                {typeof d.records === "number" && !denied ? ` · ${d.records} records` : ""}
              </Text>
              {d.company_id ? <Text style={st.line}>Firm: {d.company_id}</Text> : null}
              {denied && d.reason ? (
                <Text style={st.reason}>Reason: {d.reason}</Text>
              ) : null}
            </View>
          );
        })}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  h1: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceTertiary },
  tabs: {
    flexDirection: "row", gap: 8, paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  tab: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  tabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtOn: { color: "#fff" },
  empty: { color: colors.onSurfaceTertiary, fontSize: 13, textAlign: "center", marginTop: 30 },
  card: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 12, gap: 4, backgroundColor: colors.surfaceSecondary,
  },
  cardDenied: { borderColor: "#FCA5A5" },
  name: { fontSize: 14, fontWeight: "800", color: colors.onSurface, flex: 1 },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 99 },
  badgeTxt: { fontSize: 10, fontWeight: "800" },
  line: { fontSize: 12, color: colors.onSurfaceSecondary },
  reason: { fontSize: 12, color: "#B91C1C", fontWeight: "600" },
});
