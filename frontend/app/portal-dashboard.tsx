// Iter 178 — Modern SaaS Portal Dashboard (Phase 1).
// KPI cards · attendance & payroll trend charts · per-firm compliance
// status · statutory compliance calendar · quick actions. Role-aware
// (super admin = all firms, company admin = own firm). Zoho/RazorpayX
// inspired clean layout using the active theme.
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  ScrollView,
  RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Dash = {
  generated_at: string;
  month: string;
  kpis: Record<string, number>;
  attendance_trend: { date: string; present: number }[];
  payroll_trend: { month: string; net_total: number }[];
  compliance_status: { company_id: string; name: string; status: string }[];
  compliance_calendar: { date: string; title: string; kind: string }[];
};

const KPI_DEFS: { key: string; label: string; icon: string; color: string; route?: string }[] = [
  { key: "total_employees", label: "Active Employees", icon: "people-outline", color: "#1D4ED8", route: "/employee-master" },
  { key: "present_today", label: "Present Today", icon: "checkmark-circle-outline", color: "#16A34A", route: "/daily-attendance" },
  { key: "absent_today", label: "Absent Today", icon: "close-circle-outline", color: "#B91C1C" },
  { key: "pending_punch_approvals", label: "Pending Punch Approvals", icon: "time-outline", color: "#B45309", route: "/punch-approvals" },
  { key: "pending_leaves", label: "Pending Leaves", icon: "calendar-outline", color: "#7C3AED", route: "/leave-approvals" },
  { key: "open_tickets", label: "Open Tickets", icon: "chatbubbles-outline", color: "#0891B2", route: "/tickets" },
  { key: "expiring_documents_30d", label: "Docs Expiring (30d)", icon: "document-text-outline", color: "#DB2777" },
  { key: "payroll_finalized_firms", label: "Payroll Finalized Firms", icon: "shield-checkmark-outline", color: "#059669", route: "/compliance-salary-run" },
];

const STATUS_UI: Record<string, { label: string; bg: string; fg: string }> = {
  finalized: { label: "FINALIZED", bg: "#F0FDF4", fg: "#16A34A" },
  processed: { label: "DRAFT", bg: "#FFFBEB", fg: "#B45309" },
  not_processed: { label: "NOT PROCESSED", bg: "#FEF2F2", fg: "#B91C1C" },
};

function BarChart({ data, labels, color }: { data: number[]; labels: string[]; color: string }) {
  const max = Math.max(1, ...data);
  return (
    <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 4, height: 110 }}>
      {data.map((v, i) => (
        <View key={i} style={{ flex: 1, alignItems: "center", gap: 2 }}>
          <Text style={{ fontSize: 8, color: colors.onSurfaceTertiary }}>{v ? v : ""}</Text>
          <View style={{
            width: "72%", borderTopLeftRadius: 3, borderTopRightRadius: 3,
            height: Math.max(2, (v / max) * 80), backgroundColor: color, opacity: 0.9,
          }} />
          <Text style={{ fontSize: 7.5, color: colors.onSurfaceTertiary }} numberOfLines={1}>
            {labels[i]}
          </Text>
        </View>
      ))}
    </View>
  );
}

export default function PortalDashboardScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const canView =
    user?.role === "super_admin" || user?.role === "company_admin" || user?.role === "sub_admin";

  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = selectedCompanyId ? `?company_id=${encodeURIComponent(selectedCompanyId)}` : "";
      setDash(await api<Dash>(`/admin/portal-dashboard${q}`));
    } catch { setDash(null); }
    setLoading(false);
  }, [selectedCompanyId]);

  useEffect(() => { load(); }, [load]);

  if (!canView) return <View style={st.center}><Text style={st.dim}>Admins only.</Text></View>;

  const k = dash?.kpis || {};
  const today = new Date().toISOString().slice(0, 10);

  return (
    <View style={st.root} testID="portal-dashboard-screen">
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={st.head}>
          <View style={{ flex: 1 }}>
            <Text style={st.title}>Portal Dashboard</Text>
            <Text style={st.sub}>
              {selectedCompanyId ? "Firm view" : "All firms"} · Updated {dash?.generated_at || "—"}
            </Text>
          </View>
          <Pressable onPress={load} style={st.refreshBtn} testID="pd-refresh">
            <Ionicons name="refresh-outline" size={16} color={colors.brandPrimary} />
          </Pressable>
        </View>
      </SafeAreaView>

      {loading && !dash ? (
        <View style={st.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}
          refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
        >
          {/* KPI cards */}
          <View style={st.kpiGrid}>
            {KPI_DEFS.map((d) => (
              <Pressable
                key={d.key}
                onPress={() => d.route && router.push(d.route as any)}
                style={st.kpiCard}
                testID={`pd-kpi-${d.key}`}
              >
                <View style={[st.kpiIcon, { backgroundColor: `${d.color}18` }]}>
                  <Ionicons name={d.icon as any} size={17} color={d.color} />
                </View>
                <Text style={st.kpiVal}>{k[d.key] ?? "—"}</Text>
                <Text style={st.kpiLbl} numberOfLines={2}>{d.label}</Text>
              </Pressable>
            ))}
          </View>

          {/* Charts row */}
          <View style={st.twoCol}>
            <View style={[st.card, { flex: 1.3 }]} testID="pd-attendance-chart">
              <Text style={st.cardTitle}>📈 Attendance — last 14 days (present)</Text>
              <BarChart
                data={(dash?.attendance_trend || []).map((d) => d.present)}
                labels={(dash?.attendance_trend || []).map((d) => d.date.slice(8))}
                color="#1D4ED8"
              />
            </View>
            <View style={[st.card, { flex: 1 }]} testID="pd-payroll-chart">
              <Text style={st.cardTitle}>💰 Payroll — net total (6 months)</Text>
              <BarChart
                data={(dash?.payroll_trend || []).map((d) => d.net_total)}
                labels={(dash?.payroll_trend || []).map((d) => d.month.slice(5))}
                color="#059669"
              />
            </View>
          </View>

          <View style={st.twoCol}>
            {/* Compliance status per firm */}
            <View style={[st.card, { flex: 1.3 }]} testID="pd-compliance-status">
              <Text style={st.cardTitle}>🛡️ Compliance Status — {dash?.month}</Text>
              {(dash?.compliance_status || []).slice(0, 12).map((c) => {
                const sui = STATUS_UI[c.status] || STATUS_UI.not_processed;
                return (
                  <View key={c.company_id} style={st.statusRow}>
                    <Text style={st.statusName} numberOfLines={1}>{c.name}</Text>
                    <Text style={[st.statusChip, { backgroundColor: sui.bg, color: sui.fg }]}>
                      {sui.label}
                    </Text>
                  </View>
                );
              })}
              {!dash?.compliance_status?.length ? <Text style={st.dim}>No firms.</Text> : null}
            </View>

            {/* Statutory calendar */}
            <View style={[st.card, { flex: 1 }]} testID="pd-calendar">
              <Text style={st.cardTitle}>📅 Compliance Calendar — {dash?.month}</Text>
              {(dash?.compliance_calendar || []).map((e, i) => {
                const overdue = e.date < today;
                return (
                  <View key={i} style={st.calRow}>
                    <View style={[st.calDate, overdue && { backgroundColor: "#FEF2F2" }]}>
                      <Text style={[st.calDay, overdue && { color: "#B91C1C" }]}>{e.date.slice(8)}</Text>
                      <Text style={st.calKind}>{e.kind}</Text>
                    </View>
                    <Text style={st.calTitle} numberOfLines={2}>{e.title}</Text>
                  </View>
                );
              })}
            </View>
          </View>

          {/* Quick actions */}
          <View style={st.card}>
            <Text style={st.cardTitle}>⚡ Quick Actions</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
              {[
                { label: "Punch Approvals", route: "/punch-approvals", icon: "checkmark-done-outline" },
                { label: "Contractor Punches", route: "/contractor-punches", icon: "briefcase-outline" },
                { label: "Compliance Salary", route: "/compliance-salary-run", icon: "cash-outline" },
                { label: "Labour Law Reports", route: "/labour-reports", icon: "library-outline" },
                { label: "EPFO / ESIC Automation", route: "/challans", icon: "cog-outline" },
                { label: "Employee Master", route: "/employee-master", icon: "people-outline" },
                { label: "Firm Master", route: "/firm-master", icon: "business-outline" },
              ].map((a) => (
                <Pressable key={a.route} onPress={() => router.push(a.route as any)}
                  style={st.qaBtn} testID={`pd-qa-${a.route.slice(1)}`}>
                  <Ionicons name={a.icon as any} size={13} color={colors.brandPrimary} />
                  <Text style={st.qaTxt}>{a.label}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        </ScrollView>
      )}
    </View>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  dim: { fontSize: 12.5, color: colors.onSurfaceSecondary },
  head: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: spacing.md, paddingVertical: 10 },
  title: { ...type.h3, color: colors.onSurface },
  sub: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  refreshBtn: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md,
    padding: 8, backgroundColor: colors.surface,
  },
  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  kpiCard: {
    minWidth: 150, flexGrow: 1, flexBasis: "22%", backgroundColor: colors.surface,
    borderRadius: radius.lg, borderWidth: 1, borderColor: colors.divider, padding: 12,
  },
  kpiIcon: {
    width: 32, height: 32, borderRadius: 9, alignItems: "center",
    justifyContent: "center", marginBottom: 8,
  },
  kpiVal: { fontSize: 22, fontWeight: "800", color: colors.onSurface },
  kpiLbl: { fontSize: 10.5, color: colors.onSurfaceSecondary, marginTop: 2 },
  twoCol: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 10 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.divider, padding: 12, minWidth: 280, marginTop: 0,
  },
  cardTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  statusRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 6, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
  },
  statusName: { fontSize: 12, fontWeight: "600", color: colors.onSurface, flex: 1, marginRight: 8 },
  statusChip: {
    fontSize: 9, fontWeight: "800", borderRadius: 6, overflow: "hidden",
    paddingHorizontal: 7, paddingVertical: 3,
  },
  calRow: { flexDirection: "row", gap: 10, alignItems: "center", paddingVertical: 6 },
  calDate: {
    width: 44, alignItems: "center", backgroundColor: colors.background,
    borderRadius: radius.md, paddingVertical: 5,
  },
  calDay: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  calKind: { fontSize: 8, fontWeight: "700", color: colors.onSurfaceTertiary },
  calTitle: { fontSize: 11.5, color: colors.onSurfaceSecondary, flex: 1 },
  qaBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1,
    borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 8,
  },
  qaTxt: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },
});
