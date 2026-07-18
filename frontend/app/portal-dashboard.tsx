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
import TasksPanel from "@/src/components/portal/TasksPanel";
import ClientHealthPanel from "@/src/components/portal/ClientHealthPanel";
import DocumentExpiryPanel from "@/src/components/portal/DocumentExpiryPanel";
import CalendarPanel from "@/src/components/portal/CalendarPanel";
import AlertsModal from "@/src/components/portal/AlertsModal";
import OverviewPremium from "@/src/components/portal/OverviewPremium";

const TABS: { key: string; label: string; icon: string }[] = [
  { key: "overview", label: "Overview", icon: "grid-outline" },
  { key: "tasks", label: "Tasks", icon: "clipboard-outline" },
  { key: "clients", label: "Client Health", icon: "pulse-outline" },
  { key: "documents", label: "Documents", icon: "document-text-outline" },
  { key: "calendar", label: "Calendar", icon: "calendar-outline" },
];

type Dash = Record<string, any>;

export default function PortalDashboardScreen() {
  const { user } = useAuth();
  const { selectedCompanyId, companies } = useSelectedCompany();
  const canView =
    user?.role === "super_admin" || user?.role === "company_admin" || user?.role === "sub_admin";
  const canPickFirm = user?.role !== "company_admin";

  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("overview");
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [alertCount, setAlertCount] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = selectedCompanyId ? `?company_id=${encodeURIComponent(selectedCompanyId)}` : "";
      setDash(await api<Dash>(`/admin/portal-dashboard${q}`));
    } catch { setDash(null); }
    setLoading(false);
    // best-effort alert badge refresh
    try {
      const r = await api<{ alerts: any[] }>("/admin/portal-dashboard/alerts");
      setAlertCount(r.alerts.length);
    } catch { /* noop */ }
  }, [selectedCompanyId]);

  useEffect(() => { load(); }, [load]);

  if (!canView) return <View style={st.center}><Text style={st.dim}>Admins only.</Text></View>;

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
          <Pressable onPress={() => setAlertsOpen(true)} style={st.refreshBtn} testID="pd-bell">
            <Ionicons name="notifications-outline" size={16} color={colors.brandPrimary} />
            {alertCount > 0 ? (
              <View style={st.bellBadge}>
                <Text style={st.bellBadgeTxt}>{alertCount > 9 ? "9+" : alertCount}</Text>
              </View>
            ) : null}
          </Pressable>
          <Pressable onPress={load} style={st.refreshBtn} testID="pd-refresh">
            <Ionicons name="refresh-outline" size={16} color={colors.brandPrimary} />
          </Pressable>
        </View>
        {/* Tab strip */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          contentContainerStyle={st.tabStrip}>
          {TABS.map((t) => (
            <Pressable key={t.key} onPress={() => setTab(t.key)}
              style={[st.tabBtn, tab === t.key && st.tabBtnOn]} testID={`pd-tab-${t.key}`}>
              <Ionicons name={t.icon as any} size={13}
                color={tab === t.key ? colors.brandPrimary : colors.onSurfaceSecondary} />
              <Text style={[st.tabTxt, tab === t.key && st.tabTxtOn]}>{t.label}</Text>
            </Pressable>
          ))}
        </ScrollView>
      </SafeAreaView>

      <AlertsModal visible={alertsOpen} onClose={() => setAlertsOpen(false)}
        onGoTab={(k) => setTab(k)} />

      {tab !== "overview" ? (
        <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}>
          {tab === "tasks" ? (
            <TasksPanel companyId={selectedCompanyId} companies={companies} canPickFirm={canPickFirm} />
          ) : tab === "clients" ? (
            <ClientHealthPanel />
          ) : tab === "documents" ? (
            <DocumentExpiryPanel companyId={selectedCompanyId} companies={companies} canPickFirm={canPickFirm} />
          ) : (
            <CalendarPanel companyId={selectedCompanyId} />
          )}
        </ScrollView>
      ) : loading && !dash ? (
        <View style={st.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}
          refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
        >
          <OverviewPremium
            dash={dash}
            alertsCount={alertCount}
            onGoTab={(t) => setTab(t)}
            userName={user?.name || "Admin"}
          />
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
  bellBadge: {
    position: "absolute", top: -5, right: -5, backgroundColor: "#B91C1C",
    borderRadius: 8, minWidth: 16, height: 16, alignItems: "center",
    justifyContent: "center", paddingHorizontal: 3,
  },
  bellBadgeTxt: { fontSize: 8.5, fontWeight: "800", color: "#fff" },
  tabStrip: {
    flexDirection: "row", gap: 6, paddingHorizontal: spacing.md, paddingBottom: 10,
  },
  tabBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, borderRadius: 999,
    borderWidth: 1, borderColor: colors.divider, paddingHorizontal: 12,
    paddingVertical: 7, backgroundColor: colors.surface,
  },
  tabBtnOn: { borderColor: colors.brandPrimary, backgroundColor: `${colors.brandPrimary}12` },
  tabTxt: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtOn: { color: colors.brandPrimary },
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
