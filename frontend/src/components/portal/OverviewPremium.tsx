// Iter 180 — Premium SaaS Overview tab for the Portal Dashboard.
// Matches the user's reference: welcome banner, gradient KPI cards,
// compliance donut, payroll overview, alerts, due dates, top clients,
// trend charts and quick actions. Data comes from the extended
// /admin/portal-dashboard endpoint (+ client-health + alerts).
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import Svg, { Circle } from "react-native-svg";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, shadow } from "@/src/theme";

/* ------------------------------ helpers ------------------------------ */

export function inr(v: number): string {
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  if (v >= 1e3) return `₹${(v / 1e3).toFixed(1)} K`;
  return `₹${Math.round(v)}`;
}

function Donut({ segments, total, label }: {
  segments: { value: number; color: string }[]; total: number; label: string;
}) {
  const R = 52, SW = 16, C = 2 * Math.PI * R;
  let offset = 0;
  const sum = Math.max(1, segments.reduce((a, s) => a + s.value, 0));
  return (
    <View style={{ width: 140, height: 140, alignItems: "center", justifyContent: "center" }}>
      <Svg width={140} height={140} viewBox="0 0 140 140">
        <Circle cx={70} cy={70} r={R} stroke={colors.surfaceTertiary} strokeWidth={SW} fill="none" />
        {segments.map((s, i) => {
          const frac = s.value / sum;
          const dash = `${frac * C} ${C}`;
          const el = (
            <Circle key={i} cx={70} cy={70} r={R} stroke={s.color} strokeWidth={SW}
              fill="none" strokeDasharray={dash} strokeDashoffset={-offset * C}
              strokeLinecap="butt" transform="rotate(-90 70 70)" />
          );
          offset += frac;
          return el;
        })}
      </Svg>
      <View style={{ position: "absolute", alignItems: "center" }}>
        <Text style={{ fontSize: 24, fontWeight: "800", color: colors.onSurface }}>{total}</Text>
        <Text style={{ fontSize: 10, color: colors.onSurfaceTertiary }}>{label}</Text>
      </View>
    </View>
  );
}

export function BarChart({ data, labels, color }: { data: number[]; labels: string[]; color: string }) {
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

function HBarList({ rows, color }: { rows: { label: string; count: number }[]; color: string }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <View style={{ gap: 8 }}>
      {rows.map((r) => (
        <View key={r.label}>
          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
            <Text style={st.hbarLbl} numberOfLines={1}>{r.label}</Text>
            <Text style={st.hbarVal}>{r.count}</Text>
          </View>
          <View style={st.hbarBg}>
            <View style={[st.hbarFg, { width: `${(r.count / max) * 100}%`, backgroundColor: color }]} />
          </View>
        </View>
      ))}
      {rows.length === 0 ? <Text style={st.dim}>No data.</Text> : null}
    </View>
  );
}

/* ------------------------------ types -------------------------------- */

type Dash = any;
type Client = { company_id: string; name: string; score: number; grade: string };

const KPIS: { key: string; label: string; icon: string; grad: [string, string]; route?: string; money?: boolean; soon?: boolean }[] = [
  { key: "firms", label: "Total Clients", icon: "business", grad: ["#2563EB", "#4338CA"], route: "/companies" },
  { key: "total_employees", label: "Total Employees", icon: "people", grad: ["#0891B2", "#2563EB"], route: "/employee-master" },
  { key: "present_today", label: "Today's Attendance", icon: "checkmark-done", grad: ["#059669", "#10B981"], route: "/daily-attendance" },
  { key: "pending_payroll_firms", label: "Pending Payroll", icon: "hourglass", grad: ["#D97706", "#F59E0B"], route: "/compliance-salary-run" },
  { key: "payroll_finalized_firms", label: "Processed Payroll", icon: "shield-checkmark", grad: ["#059669", "#0891B2"], route: "/compliance-salary-run" },
  { key: "pending_punch_approvals", label: "Pending Approvals", icon: "time", grad: ["#B45309", "#D97706"], route: "/punch-approvals" },
  { key: "pending_tasks", label: "Pending Tasks", icon: "clipboard", grad: ["#7C3AED", "#DB2777"] },
  { key: "__revenue", label: "Monthly Revenue", icon: "trending-up", grad: ["#64748B", "#94A3B8"], soon: true },
];

/* ---------------------------- component ------------------------------ */

export default function OverviewPremium({
  dash, alertsCount, onGoTab, userName,
}: {
  dash: Dash; alertsCount: number; onGoTab: (tab: string) => void; userName: string;
}) {
  const router = useRouter();
  const [clients, setClients] = useState<Client[]>([]);
  useEffect(() => {
    api<{ clients: Client[] }>("/admin/portal-dashboard/client-health")
      .then((r) => setClients([...r.clients].sort((a, b) => b.score - a.score).slice(0, 5)))
      .catch(() => {});
  }, [dash?.generated_at]);

  const k = dash?.kpis || {};
  const liab = dash?.liabilities || {};
  const donut = dash?.compliance_donut || {};
  const today = new Date().toISOString().slice(0, 10);

  return (
    <View>
      {/* Welcome banner */}
      <View style={st.welcome}>
        <View style={{ flex: 1 }}>
          <Text style={st.welcomeTitle}>Welcome back, {userName.split(" ")[0]}! 👋</Text>
          <Text style={st.welcomeSub}>
            Here&apos;s what&apos;s happening with your compliance management today.
          </Text>
        </View>
      </View>

      {/* KPI cards */}
      <View style={st.kpiGrid}>
        {KPIS.map((d) => (
          <Pressable key={d.key}
            onPress={() => d.route && router.push(d.route as any)}
            style={({ pressed, hovered }: any) => [
              st.kpiCard, pressed && { transform: [{ scale: 0.97 }] },
              hovered && Platform.OS === "web" && { transform: [{ scale: 1.02 }] }]}
            testID={`pd-kpi-${d.key}`}>
            <LinearGradient colors={d.grad} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
              style={st.kpiIcon}>
              <Ionicons name={`${d.icon}-outline` as any} size={17} color="#fff" />
            </LinearGradient>
            <Text style={st.kpiVal}>{d.soon ? "—" : (k[d.key] ?? "—")}</Text>
            <Text style={st.kpiLbl} numberOfLines={1}>{d.label}</Text>
            {d.soon ? <Text style={st.kpiSoon}>COMING SOON</Text> : null}
          </Pressable>
        ))}
      </View>

      {/* Row: compliance donut · payroll overview · liabilities */}
      <View style={st.twoCol}>
        <View style={[st.card, { flex: 1 }]} testID="pd-compliance-donut">
          <Text style={st.cardTitle}>🛡️ Compliance Overview — {dash?.month}</Text>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <Donut
              total={donut.total ?? 0}
              label="Firms"
              segments={[
                { value: donut.complied || 0, color: "#10B981" },
                { value: donut.due_soon || 0, color: "#F59E0B" },
                { value: (donut.overdue || 0) + (donut.pending || 0), color: donut.overdue ? "#EF4444" : "#CBD5E1" },
              ]}
            />
            <View style={{ gap: 8, flex: 1, minWidth: 120 }}>
              {[
                { c: "#10B981", l: "Complied (finalized)", v: donut.complied || 0 },
                { c: "#F59E0B", l: "In progress (draft)", v: donut.due_soon || 0 },
                { c: "#EF4444", l: "Overdue", v: donut.overdue || 0 },
                { c: "#CBD5E1", l: "Not started", v: donut.pending || 0 },
              ].map((x) => (
                <View key={x.l} style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <View style={{ width: 9, height: 9, borderRadius: 3, backgroundColor: x.c }} />
                  <Text style={st.legendTxt} numberOfLines={1}>{x.l}</Text>
                  <Text style={st.legendVal}>{x.v}</Text>
                </View>
              ))}
            </View>
          </View>
        </View>

        <View style={[st.card, { flex: 1 }]} testID="pd-payroll-overview">
          <Text style={st.cardTitle}>💰 Payroll Overview (This Month)</Text>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 16 }}>
            <View style={{ flex: 1 }}>
              <Text style={st.bigPct}>{dash?.payroll_processed_pct ?? 0}%</Text>
              <Text style={st.dimSm}>Payroll Processed</Text>
              <View style={st.pctBarBg}>
                <View style={[st.pctBarFg, { width: `${dash?.payroll_processed_pct ?? 0}%` }]} />
              </View>
            </View>
            <View style={{ alignItems: "center" }}>
              <Text style={[st.bigPct, { color: "#D97706" }]}>{k.pending_payroll_firms ?? 0}</Text>
              <Text style={st.dimSm}>Pending Firms</Text>
            </View>
          </View>
          <View style={st.liabRow}>
            {[
              { l: "PF Liability", v: liab.pf, bg: "#EFF6FF", fg: "#1D4ED8" },
              { l: "ESIC Liability", v: liab.esic, bg: "#FEF2F2", fg: "#B91C1C" },
              { l: "TDS Liability", v: liab.tds, bg: "#EEF2FF", fg: "#4338CA" },
              { l: "PT", v: liab.pt, bg: "#F0FDF4", fg: "#059669" },
            ].map((x) => (
              <View key={x.l} style={[st.liabChip, { backgroundColor: x.bg }]}>
                <Text style={[st.liabVal, { color: x.fg }]}>{inr(x.v || 0)}</Text>
                <Text style={[st.liabLbl, { color: x.fg }]}>{x.l}</Text>
              </View>
            ))}
          </View>
          <Pressable onPress={() => router.push("/compliance-salary-run" as any)}>
            <Text style={st.link}>View payroll dashboard →</Text>
          </Pressable>
        </View>

        {/* Important alerts + due dates */}
        <View style={[st.card, { flex: 1 }]} testID="pd-due-dates">
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <Text style={st.cardTitle}>📌 Upcoming Due Dates</Text>
            <Pressable onPress={() => onGoTab("calendar")}>
              <Text style={st.link}>View Calendar</Text>
            </Pressable>
          </View>
          {(dash?.compliance_calendar || []).map((e: any, i: number) => {
            const overdue = e.date < today;
            return (
              <View key={i} style={st.dueRow}>
                <View style={[st.dueDate, overdue && { backgroundColor: "#FEF2F2" }]}>
                  <Text style={[st.dueDay, overdue && { color: "#B91C1C" }]}>{e.date.slice(8)}</Text>
                  <Text style={st.dueKind}>{e.kind}</Text>
                </View>
                <Text style={st.dueTitle} numberOfLines={2}>{e.title}</Text>
              </View>
            );
          })}
          <Pressable onPress={() => onGoTab("tasks")} style={st.alertsBtn} testID="pd-alerts-shortcut">
            <Ionicons name="alert-circle-outline" size={14} color="#B91C1C" />
            <Text style={st.alertsBtnTxt}>{alertsCount} alert(s) need attention</Text>
            <Ionicons name="chevron-forward" size={13} color="#B91C1C" />
          </Pressable>
        </View>
      </View>

      {/* Row: trends + top clients */}
      <View style={st.twoCol}>
        <View style={[st.card, { flex: 1.4 }]} testID="pd-attendance-chart">
          <Text style={st.cardTitle}>📈 Attendance — last 14 days</Text>
          <BarChart
            data={(dash?.attendance_trend || []).map((d: any) => d.present)}
            labels={(dash?.attendance_trend || []).map((d: any) => d.date.slice(8))}
            color="#2563EB"
          />
        </View>
        <View style={[st.card, { flex: 1 }]} testID="pd-payroll-chart">
          <Text style={st.cardTitle}>💸 Payroll Trend (6 months)</Text>
          <BarChart
            data={(dash?.payroll_trend || []).map((d: any) => d.net_total)}
            labels={(dash?.payroll_trend || []).map((d: any) => d.month.slice(5))}
            color="#059669"
          />
        </View>
        <View style={[st.card, { flex: 1 }]} testID="pd-top-clients">
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <Text style={st.cardTitle}>🏆 Top 5 Clients — Health</Text>
            <Pressable onPress={() => onGoTab("clients")}>
              <Text style={st.link}>View all</Text>
            </Pressable>
          </View>
          {clients.map((c) => (
            <View key={c.company_id} style={{ marginBottom: 8 }}>
              <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <Text style={st.hbarLbl} numberOfLines={1}>{c.name}</Text>
                <Text style={[st.hbarVal, { color: c.score >= 70 ? "#059669" : c.score >= 50 ? "#D97706" : "#B91C1C" }]}>
                  {c.score}%
                </Text>
              </View>
              <View style={st.hbarBg}>
                <View style={[st.hbarFg, {
                  width: `${c.score}%`,
                  backgroundColor: c.score >= 70 ? "#10B981" : c.score >= 50 ? "#F59E0B" : "#EF4444",
                }]} />
              </View>
            </View>
          ))}
          {clients.length === 0 ? <Text style={st.dim}>No firms.</Text> : null}
        </View>
      </View>

      {/* Row: growth + distributions */}
      <View style={st.twoCol}>
        <View style={[st.card, { flex: 1.2 }]} testID="pd-growth-chart">
          <Text style={st.cardTitle}>👥 Employee Growth (6 months)</Text>
          <BarChart
            data={(dash?.employee_growth || []).map((d: any) => d.employees)}
            labels={(dash?.employee_growth || []).map((d: any) => d.month.slice(5))}
            color="#4338CA"
          />
        </View>
        <View style={[st.card, { flex: 1 }]} testID="pd-state-clients">
          <Text style={st.cardTitle}>🗺️ State-wise Clients</Text>
          <HBarList rows={dash?.clients_by_state || []} color="#2563EB" />
        </View>
        <View style={[st.card, { flex: 1 }]} testID="pd-industry-clients">
          <Text style={st.cardTitle}>🏭 Industry-wise Clients</Text>
          <HBarList rows={dash?.clients_by_industry || []} color="#0891B2" />
        </View>
      </View>

      {/* Quick actions */}
      <View style={st.card}>
        <Text style={st.cardTitle}>⚡ Quick Actions</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
          {[
            { label: "Add Client", route: "/company-register", icon: "business-outline" },
            { label: "Add Employee", route: "/employee-add", icon: "person-add-outline" },
            { label: "Upload Attendance", route: "/zk-dat-import", icon: "cloud-upload-outline" },
            { label: "Generate Payroll", route: "/compliance-salary-run", icon: "cash-outline" },
            { label: "Generate ECR / Challan", route: "/challans", icon: "document-outline" },
            { label: "Labour Law Reports", route: "/labour-reports", icon: "library-outline" },
            { label: "Punch Approvals", route: "/punch-approvals", icon: "checkmark-done-outline" },
            { label: "Firm Master", route: "/firm-master", icon: "settings-outline" },
          ].map((a) => (
            <Pressable key={a.label} onPress={() => router.push(a.route as any)}
              style={({ pressed }) => [st.qaBtn, pressed && { transform: [{ scale: 0.96 }] }]}
              testID={`pd-qa-${a.route.slice(1)}`}>
              <Ionicons name={a.icon as any} size={13} color={colors.brandPrimary} />
              <Text style={st.qaTxt}>{a.label}</Text>
            </Pressable>
          ))}
        </View>
      </View>
    </View>
  );
}

/* ------------------------------ styles ------------------------------- */

const st = StyleSheet.create({
  dim: { fontSize: 12, color: colors.onSurfaceSecondary },
  dimSm: { fontSize: 10, color: colors.onSurfaceTertiary, marginTop: 2 },
  welcome: {
    flexDirection: "row", alignItems: "center", marginBottom: 12,
    backgroundColor: colors.surfaceSecondary, borderRadius: 16, padding: 16,
    borderWidth: 1, borderColor: colors.border, ...shadow.card,
  },
  welcomeTitle: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  welcomeSub: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 3 },
  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  kpiCard: {
    minWidth: 150, flexGrow: 1, flexBasis: "22%", backgroundColor: colors.surfaceSecondary,
    borderRadius: 16, borderWidth: 1, borderColor: colors.border, padding: 12,
    ...shadow.card,
  },
  kpiIcon: {
    width: 34, height: 34, borderRadius: 10, alignItems: "center",
    justifyContent: "center", marginBottom: 8,
  },
  kpiVal: { fontSize: 22, fontWeight: "800", color: colors.onSurface },
  kpiLbl: { fontSize: 10.5, color: colors.onSurfaceSecondary, marginTop: 2 },
  kpiSoon: { fontSize: 7.5, fontWeight: "800", color: colors.warning, marginTop: 2, letterSpacing: 0.5 },
  twoCol: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 10, marginBottom: 0 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 16, borderWidth: 1,
    borderColor: colors.border, padding: 14, minWidth: 300, ...shadow.card,
  },
  cardTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  legendTxt: { fontSize: 10.5, color: colors.onSurfaceSecondary, flex: 1 },
  legendVal: { fontSize: 11, fontWeight: "800", color: colors.onSurface },
  bigPct: { fontSize: 28, fontWeight: "800", color: "#059669" },
  pctBarBg: { height: 6, backgroundColor: colors.surfaceTertiary, borderRadius: 3, marginTop: 8, overflow: "hidden" },
  pctBarFg: { height: 6, backgroundColor: "#10B981", borderRadius: 3 },
  liabRow: { flexDirection: "row", gap: 6, marginTop: 12, flexWrap: "wrap" },
  liabChip: { flex: 1, minWidth: 76, borderRadius: 10, padding: 8, alignItems: "center" },
  liabVal: { fontSize: 12, fontWeight: "800" },
  liabLbl: { fontSize: 8, fontWeight: "700", marginTop: 2, textAlign: "center" },
  link: { fontSize: 11, fontWeight: "700", color: colors.brandPrimary, marginTop: 8 },
  dueRow: { flexDirection: "row", gap: 10, alignItems: "center", paddingVertical: 5 },
  dueDate: {
    width: 42, alignItems: "center", backgroundColor: colors.surfaceTertiary,
    borderRadius: radius.md, paddingVertical: 4,
  },
  dueDay: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  dueKind: { fontSize: 7.5, fontWeight: "700", color: colors.onSurfaceTertiary },
  dueTitle: { fontSize: 11, color: colors.onSurfaceSecondary, flex: 1 },
  alertsBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8,
    backgroundColor: "#FEF2F2", borderRadius: radius.md, padding: 8,
  },
  alertsBtnTxt: { flex: 1, fontSize: 11, fontWeight: "700", color: "#B91C1C" },
  hbarLbl: { fontSize: 11, fontWeight: "600", color: colors.onSurface, flex: 1, marginRight: 8 },
  hbarVal: { fontSize: 11, fontWeight: "800", color: colors.onSurface },
  hbarBg: { height: 6, backgroundColor: colors.surfaceTertiary, borderRadius: 3, marginTop: 3, overflow: "hidden" },
  hbarFg: { height: 6, borderRadius: 3 },
  qaBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1,
    borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 8,
  },
  qaTxt: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },
});
