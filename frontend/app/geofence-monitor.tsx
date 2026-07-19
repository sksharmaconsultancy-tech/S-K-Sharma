/**
 * Geofence Monitor — employer dashboard for the geofence/offline engine.
 *
 * KPI cards (offline-synced, fake GPS, outside geofence, no-GPS, pending)
 * + register tabs with CSV export. Data: /api/admin/geofence/monitor and
 * /api/admin/geofence/report.
 */
import { Ionicons } from "@expo/vector-icons";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Redirect } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius } from "@/src/theme";

type MonitorResp = {
  from: string; to: string;
  counts: { total: number; offline: number; mock: number; outside: number; no_gps: number; pending: number; flagged: number };
  by_mode: Record<string, number>;
  recent_flagged: any[];
};
type ReportRow = Record<string, any>;

const TABS: { key: string; label: string; icon: any; color: string }[] = [
  { key: "flagged", label: "All Flagged", icon: "flag-outline", color: "#DC2626" },
  { key: "offline", label: "Offline Punches", icon: "cloud-offline-outline", color: "#B45309" },
  { key: "mock", label: "Fake GPS", icon: "warning-outline", color: "#7C3AED" },
  { key: "outside", label: "Outside Geofence", icon: "navigate-outline", color: "#2563EB" },
  { key: "no_gps", label: "No GPS", icon: "cellular-outline", color: "#64748B" },
  { key: "pending", label: "Pending Approval", icon: "hourglass-outline", color: "#D97706" },
];

const RANGES = [
  { key: "month", label: "This Month" },
  { key: "prev", label: "Last Month" },
  { key: "7d", label: "Last 7 Days" },
];

function rangeDates(key: string): { from: string; to: string } {
  const now = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  if (key === "7d") {
    const from = new Date(now); from.setDate(now.getDate() - 6);
    return { from: iso(from), to: iso(now) };
  }
  if (key === "prev") {
    const first = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const last = new Date(now.getFullYear(), now.getMonth(), 0);
    return { from: iso(first), to: iso(last) };
  }
  return { from: iso(new Date(now.getFullYear(), now.getMonth(), 1)), to: iso(now) };
}

export default function GeofenceMonitorScreen() {
  const { user, loading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [range, setRange] = useState("month");
  const [tab, setTab] = useState("flagged");
  const [mon, setMon] = useState<MonitorResp | null>(null);
  const [rows, setRows] = useState<ReportRow[]>([]);
  const [busy, setBusy] = useState(true);
  const [rowsBusy, setRowsBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const cid = selectedCompanyId;
  const { from, to } = useMemo(() => rangeDates(range), [range]);

  const loadMonitor = useCallback(async () => {
    if (!cid) { setBusy(false); return; }
    setBusy(true); setMsg(null);
    try {
      setMon(await api<MonitorResp>(
        `/admin/geofence/monitor?company_id=${cid}&from=${from}&to=${to}`));
    } catch (e: any) { setMsg(e?.message || "Failed to load."); }
    finally { setBusy(false); }
  }, [cid, from, to]);

  const loadRows = useCallback(async () => {
    if (!cid) return;
    setRowsBusy(true);
    try {
      const r = await api<{ rows: ReportRow[] }>(
        `/admin/geofence/report?type=${tab}&company_id=${cid}&from=${from}&to=${to}`);
      setRows(r.rows || []);
    } catch (e: any) { setMsg(e?.message || "Failed to load register."); }
    finally { setRowsBusy(false); }
  }, [cid, tab, from, to]);

  useEffect(() => { void loadMonitor(); }, [loadMonitor]);
  useEffect(() => { void loadRows(); }, [loadRows]);

  const exportCsv = useCallback(async () => {
    if (!cid) return;
    try {
      const { webBlobUrl } = await apiBinary(
        `/admin/geofence/report?type=${tab}&company_id=${cid}&from=${from}&to=${to}&format=csv`);
      if (Platform.OS === "web" && webBlobUrl) {
        const a = document.createElement("a");
        a.href = webBlobUrl; a.download = `geofence_${tab}_${from}_${to}.csv`; a.click();
        setTimeout(() => URL.revokeObjectURL(webBlobUrl), 30000);
      }
    } catch (e: any) { setMsg(e?.message || "Export failed."); }
  }, [cid, tab, from, to]);

  if (loading) return null;
  const role = user?.role as string;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }

  const c = mon?.counts;
  const kpis = [
    { label: "Total Punches", value: c?.total ?? "—", color: colors.brandPrimary, icon: "finger-print-outline" },
    { label: "Offline Synced", value: c?.offline ?? "—", color: "#B45309", icon: "cloud-offline-outline" },
    { label: "Fake GPS Flagged", value: c?.mock ?? "—", color: "#7C3AED", icon: "warning-outline" },
    { label: "Outside Geofence", value: c?.outside ?? "—", color: "#2563EB", icon: "navigate-outline" },
    { label: "No GPS", value: c?.no_gps ?? "—", color: "#64748B", icon: "cellular-outline" },
    { label: "Pending Approval", value: c?.pending ?? "—", color: "#D97706", icon: "hourglass-outline" },
  ];

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={st.wrap}>
        <View style={st.headRow}>
          <View style={{ flex: 1 }}>
            <Text style={st.title}>Geofence Monitor</Text>
            <Text style={st.subtitle}>
              Offline punches, fake-GPS flags & geofence violations · {mon?.from || from} → {mon?.to || to}
            </Text>
          </View>
          <Pressable style={st.expBtn} onPress={exportCsv} testID="geo-export-csv">
            <Ionicons name="download-outline" size={15} color={colors.brandPrimary} />
            <Text style={st.expTxt}>CSV</Text>
          </Pressable>
        </View>

        {!cid ? (
          <Text style={st.empty}>Select a firm from the top bar to view its geofence activity.</Text>
        ) : null}
        {msg ? (
          <View style={st.msgBox}><Text style={st.msgTxt}>{msg}</Text></View>
        ) : null}

        {/* Range presets */}
        <View style={st.pillRow}>
          {RANGES.map((r) => (
            <Pressable key={r.key} onPress={() => setRange(r.key)}
              style={[st.pill, range === r.key && st.pillActive]} testID={`geo-range-${r.key}`}>
              <Text style={[st.pillTxt, range === r.key && st.pillTxtActive]}>{r.label}</Text>
            </Pressable>
          ))}
        </View>

        {/* KPI cards */}
        {busy ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 12 }} /> : (
          <View style={st.kpiRow}>
            {kpis.map((k) => (
              <View key={k.label} style={st.kpi} testID={`geo-kpi-${k.label}`}>
                <Ionicons name={k.icon as any} size={17} color={k.color} />
                <Text style={[st.kpiVal, { color: k.color }]}>{String(k.value)}</Text>
                <Text style={st.kpiLbl}>{k.label}</Text>
              </View>
            ))}
          </View>
        )}

        {/* Mode breakdown */}
        {mon && Object.keys(mon.by_mode || {}).length ? (
          <View style={st.modeRow}>
            {Object.entries(mon.by_mode).map(([m, n]) => (
              <View key={m} style={st.modeChip}>
                <Text style={st.modeTxt}>{m}: {n}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {/* Register tabs */}
        <View style={st.tabRow}>
          {TABS.map((t) => (
            <Pressable key={t.key} onPress={() => setTab(t.key)}
              style={[st.tab, tab === t.key && { backgroundColor: t.color + "18", borderColor: t.color }]}
              testID={`geo-tab-${t.key}`}>
              <Ionicons name={t.icon} size={14} color={tab === t.key ? t.color : colors.textSecondary} />
              <Text style={[st.tabTxt, tab === t.key && { color: t.color }]}>{t.label}</Text>
            </Pressable>
          ))}
        </View>

        {/* Register rows */}
        {rowsBusy ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 12 }} />
        ) : rows.length === 0 ? (
          <Text style={st.empty}>No records in this register for the selected period. ✅</Text>
        ) : (
          <View style={st.tableCard}>
            <View style={[st.tr, st.trHead]}>
              {["Date", "Employee", "Kind", "Time", "Worksite", "Dist (m)", "Flags", "Status"].map((h) => (
                <Text key={h} style={[st.th, h === "Employee" && { flex: 1.6 }, h === "Worksite" && { flex: 1.3 }, h === "Flags" && { flex: 1.5 }]}>{h}</Text>
              ))}
            </View>
            {rows.slice(0, 300).map((r, i) => (
              <View key={`${r.date}-${r.employee_code}-${i}`} style={[st.tr, i % 2 === 1 && { backgroundColor: colors.surfaceSecondary }]}>
                <Text style={st.td}>{r.date}</Text>
                <Text style={[st.td, { flex: 1.6 }]} numberOfLines={1}>
                  {r.employee_name || "—"}{r.employee_code ? ` (${r.employee_code})` : ""}
                </Text>
                <Text style={[st.td, { textTransform: "uppercase", fontWeight: "700", color: r.kind === "in" ? "#059669" : "#DC2626" }]}>{r.kind}</Text>
                <Text style={st.td}>{r.time || "—"}</Text>
                <Text style={[st.td, { flex: 1.3 }]} numberOfLines={1}>{r.worksite || "—"}</Text>
                <Text style={st.td}>{r.distance_m != null ? Math.round(r.distance_m) : "—"}</Text>
                <View style={[st.tdFlags, { flex: 1.5 }]}>
                  {r.offline_punch ? <Text style={[st.flag, { color: "#B45309", backgroundColor: "#FEF3C7" }]}>OFFLINE</Text> : null}
                  {r.mock_location ? <Text style={[st.flag, { color: "#7C3AED", backgroundColor: "#EDE9FE" }]}>FAKE GPS</Text> : null}
                  {r.outside_geofence ? <Text style={[st.flag, { color: "#2563EB", backgroundColor: "#DBEAFE" }]}>OUTSIDE</Text> : null}
                </View>
                <Text style={[st.td, { textTransform: "capitalize" }]} numberOfLines={1}>
                  {String(r.status || "—").replace(/_/g, " ")}
                </Text>
              </View>
            ))}
            {rows.length > 300 ? (
              <Text style={st.moreTxt}>Showing first 300 of {rows.length} — download CSV for the full register.</Text>
            ) : null}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  wrap: { padding: 20, gap: 12, width: "100%" },
  headRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  title: { fontSize: 22, fontWeight: "800", color: colors.textPrimary },
  subtitle: { fontSize: 12.5, color: colors.textSecondary, marginTop: 2 },
  expBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1,
    borderColor: colors.brandPrimary, borderRadius: 8, paddingVertical: 8, paddingHorizontal: 12,
  },
  expTxt: { color: colors.brandPrimary, fontSize: 12.5, fontWeight: "800" },
  msgBox: { backgroundColor: "#FEF2F2", borderRadius: 10, padding: 10 },
  msgTxt: { color: "#B91C1C", fontSize: 12.5 },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pill: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingVertical: 6, paddingHorizontal: 12, backgroundColor: colors.surface,
  },
  pillActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  pillTxt: { fontSize: 12, fontWeight: "700", color: colors.textSecondary },
  pillTxtActive: { color: "#fff" },
  kpiRow: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  kpi: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: 14, minWidth: 148, flexGrow: 1, gap: 4,
  },
  kpiVal: { fontSize: 22, fontWeight: "800" },
  kpiLbl: { fontSize: 11.5, color: colors.textSecondary, fontWeight: "600" },
  modeRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  modeChip: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 999, borderWidth: 1,
    borderColor: colors.border, paddingVertical: 4, paddingHorizontal: 10,
  },
  modeTxt: { fontSize: 11, color: colors.textSecondary, fontWeight: "700", textTransform: "capitalize" },
  tabRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  tab: {
    flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1,
    borderColor: colors.border, borderRadius: 8, paddingVertical: 8, paddingHorizontal: 12,
    backgroundColor: colors.surface,
  },
  tabTxt: { fontSize: 12, fontWeight: "700", color: colors.textSecondary },
  tableCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, overflow: "hidden",
  },
  tr: { flexDirection: "row", alignItems: "center", paddingVertical: 9, paddingHorizontal: 12, gap: 8 },
  trHead: { backgroundColor: colors.surfaceSecondary, borderBottomWidth: 1, borderBottomColor: colors.border },
  th: { flex: 1, fontSize: 11, fontWeight: "800", color: colors.textSecondary, textTransform: "uppercase" },
  td: { flex: 1, fontSize: 12, color: colors.textPrimary },
  tdFlags: { flexDirection: "row", flexWrap: "wrap", gap: 4 },
  flag: {
    fontSize: 9.5, fontWeight: "800", borderRadius: 4,
    paddingHorizontal: 5, paddingVertical: 2, overflow: "hidden",
  },
  moreTxt: { fontSize: 11.5, color: colors.textSecondary, padding: 10, textAlign: "center" },
  empty: { fontSize: 13, color: colors.textSecondary, marginTop: 12, textAlign: "center" },
});
