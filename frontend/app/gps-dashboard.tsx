/**
 * Iter 417 — GPS DIAGNOSTICS DASHBOARD (Super Admin / Company Admin).
 * Color-coded feed of every GPS attempt from employee devices:
 *   Green = success · Yellow = weak GPS · Red = failed.
 * Filters: firm, date, status. Excel export.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  ActivityIndicator, RefreshControl, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { api, apiBinary } from "@/src/api/client";
import { colors, type } from "@/src/theme";
import AdminWebShell from "@/src/components/AdminWebShell";
import CompanyPicker from "@/src/components/CompanyPicker";

type Row = {
  diag_id: string; name?: string; employee_code?: string;
  outcome: string; accuracy?: number | null; retry_count?: number;
  permission_status?: string; gps_enabled?: boolean | null;
  mock_location?: boolean; network_status?: string;
  failure_reason?: string; platform?: string; device?: string;
  created_at?: string;
};

const OUTCOME_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
  success: { bg: "#dcfce7", fg: "#166534", label: "SUCCESS" },
  weak: { bg: "#fef9c3", fg: "#854d0e", label: "WEAK GPS" },
  failed: { bg: "#fee2e2", fg: "#991b1b", label: "FAILED" },
};

export default function GpsDashboard() {
  const [rows, setRows] = useState<Row[]>([]);
  const [counts, setCounts] = useState<{ success: number; weak: number; failed: number }>({ success: 0, weak: 0, failed: 0 });
  const [rate, setRate] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [companyId, setCompanyId] = useState<string>("");
  const [date, setDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [outcome, setOutcome] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (companyId) qs.set("company_id", companyId);
      if (date) qs.set("date", date);
      if (outcome) qs.set("outcome", outcome);
      const r = await api<{ rows: Row[]; counts: any; success_rate: number }>(
        `/admin/gps-diagnostics?${qs.toString()}`);
      setRows(r.rows || []);
      setCounts(r.counts || { success: 0, weak: 0, failed: 0 });
      setRate(r.success_rate ?? null);
    } catch { /* noop */ } finally { setLoading(false); }
  }, [companyId, date, outcome]);

  useEffect(() => { load(); }, [load]);

  const exportXlsx = useCallback(async () => {
    const qs = new URLSearchParams();
    if (companyId) qs.set("company_id", companyId);
    if (date) qs.set("date", date);
    if (outcome) qs.set("outcome", outcome);
    try {
      const r = await apiBinary(`/admin/gps-diagnostics.xlsx?${qs.toString()}`);
      if (Platform.OS === "web" && r.webBlobUrl) {
        const a = document.createElement("a");
        a.href = r.webBlobUrl;
        a.download = "GPS_Diagnostics.xlsx";
        a.click();
        URL.revokeObjectURL(r.webBlobUrl);
      }
    } catch { /* noop */ }
  }, [companyId, date, outcome]);

  const body = (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.surface }}
      contentContainerStyle={{ padding: 16, paddingBottom: 48 }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
    >
      <View style={styles.headRow}>
        <Pressable onPress={() => router.back()} style={styles.backBtn}>
          <Ionicons name="arrow-back" size={20} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>GPS Diagnostics Dashboard</Text>
        <Pressable style={styles.exportBtn} onPress={exportXlsx}>
          <Ionicons name="download-outline" size={16} color="#fff" />
          <Text style={styles.exportTxt}>Excel</Text>
        </Pressable>
      </View>

      {/* Summary cards */}
      <View style={styles.cards}>
        <View style={[styles.card, { backgroundColor: "#dcfce7" }]}>
          <Text style={[styles.cardNum, { color: "#166534" }]}>{counts.success}</Text>
          <Text style={styles.cardLbl}>Success</Text>
        </View>
        <View style={[styles.card, { backgroundColor: "#fef9c3" }]}>
          <Text style={[styles.cardNum, { color: "#854d0e" }]}>{counts.weak}</Text>
          <Text style={styles.cardLbl}>Weak GPS</Text>
        </View>
        <View style={[styles.card, { backgroundColor: "#fee2e2" }]}>
          <Text style={[styles.cardNum, { color: "#991b1b" }]}>{counts.failed}</Text>
          <Text style={styles.cardLbl}>Failed</Text>
        </View>
        <View style={[styles.card, { backgroundColor: "#e0f2fe" }]}>
          <Text style={[styles.cardNum, { color: "#075985" }]}>{rate == null ? "—" : `${rate}%`}</Text>
          <Text style={styles.cardLbl}>Success Rate</Text>
        </View>
      </View>

      {/* Filters */}
      <View style={styles.filters}>
        <View style={{ flex: 1, minWidth: 220 }}>
          <CompanyPicker
            value={companyId || "all"}
            onChange={(v) => setCompanyId(v === "all" ? "" : (v as string))}
            label="Firm"
          />
        </View>
        {(["", "success", "weak", "failed"] as const).map((o) => (
          <Pressable
            key={o || "all"}
            style={[styles.chip, outcome === o && styles.chipOn]}
            onPress={() => setOutcome(o)}
          >
            <Text style={[styles.chipTxt, outcome === o && styles.chipTxtOn]}>
              {o === "" ? "All" : OUTCOME_STYLE[o].label}
            </Text>
          </Pressable>
        ))}
        <Pressable style={styles.chip} onPress={() => setDate(date ? "" : new Date().toISOString().slice(0, 10))}>
          <Text style={styles.chipTxt}>{date ? `📅 ${date} ✕` : "All dates"}</Text>
        </Pressable>
      </View>

      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
      ) : rows.length === 0 ? (
        <Text style={styles.empty}>No GPS diagnostics yet — logs appear as employees punch.</Text>
      ) : (
        rows.map((r) => {
          const st = OUTCOME_STYLE[r.outcome] || OUTCOME_STYLE.failed;
          return (
            <View key={r.diag_id} style={styles.row}>
              <View style={[styles.badge, { backgroundColor: st.bg }]}>
                <Text style={[styles.badgeTxt, { color: st.fg }]}>{st.label}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowName}>
                  {r.name || "—"}{r.employee_code ? ` · #${r.employee_code}` : ""}
                </Text>
                <Text style={styles.rowMeta}>
                  {(r.created_at || "").slice(0, 19).replace("T", " ")}
                  {r.accuracy != null ? ` · ±${Math.round(r.accuracy)}m` : ""}
                  {r.retry_count ? ` · ${r.retry_count} retries` : ""}
                  {r.network_status ? ` · ${r.network_status}` : ""}
                  {r.platform ? ` · ${r.platform}` : ""}
                </Text>
                {r.failure_reason ? (
                  <Text style={styles.rowReason}>Reason: {r.failure_reason}</Text>
                ) : null}
                {r.mock_location ? (
                  <Text style={styles.rowMock}>⚠️ MOCK LOCATION detected</Text>
                ) : null}
              </View>
            </View>
          );
        })
      )}
    </ScrollView>
  );

  if (Platform.OS === "web") return <AdminWebShell>{body}</AdminWebShell>;
  return <SafeAreaView style={{ flex: 1 }}>{body}</SafeAreaView>;
}

const styles = StyleSheet.create({
  headRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 12 },
  backBtn: { padding: 6 },
  title: { flex: 1, fontSize: type.xl, fontWeight: "700", color: colors.onSurface },
  exportBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#0f766e", paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: 10,
  },
  exportTxt: { color: "#fff", fontWeight: "700", fontSize: type.sm },
  cards: { flexDirection: "row", gap: 10, flexWrap: "wrap", marginBottom: 12 },
  card: { flex: 1, minWidth: 120, borderRadius: 12, padding: 12, alignItems: "center" },
  cardNum: { fontSize: 22, fontWeight: "800" },
  cardLbl: { fontSize: type.sm, color: "#334155", marginTop: 2 },
  filters: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "flex-end", marginBottom: 12 },
  chip: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 16,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: type.sm, color: colors.onSurface },
  chipTxtOn: { color: "#fff", fontWeight: "700" },
  empty: { textAlign: "center", marginTop: 40, color: colors.onSurfaceSecondary },
  row: {
    flexDirection: "row", gap: 10, padding: 12, borderRadius: 12,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    marginBottom: 8, alignItems: "flex-start",
  },
  badge: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, minWidth: 76, alignItems: "center" },
  badgeTxt: { fontSize: 10, fontWeight: "800" },
  rowName: { fontSize: type.md, fontWeight: "600", color: colors.onSurface },
  rowMeta: { fontSize: type.sm, color: colors.onSurfaceSecondary, marginTop: 2 },
  rowReason: { fontSize: type.sm, color: "#b45309", marginTop: 2 },
  rowMock: { fontSize: type.sm, color: "#dc2626", fontWeight: "700", marginTop: 2 },
});
