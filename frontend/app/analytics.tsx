/**
 * Iter 709 — 📊 READ-ONLY Payroll Charts & Analytics dashboard.
 * Visualization ONLY on top of already-computed data (salary runs,
 * attendance, employees, leaves, expenses, approvals). Never writes,
 * never recalculates, never triggers any payroll/attendance process.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors } from "@/src/theme";
import {
  KpiCard, ChartCard, HBar, TrendLine, Donut, StackedBars, fmtMoney,
} from "@/src/components/charts";

const TABS = [["payroll", "Payroll"], ["attendance", "Attendance"], ["people", "People & More"]] as const;
const monthShift = (m: string, d: number) => {
  const [y, mm] = m.split("-").map(Number);
  const dt = new Date(y, mm - 1 + d, 1);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`;
};

export default function Analytics() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const role = user?.role as string;
  const [companyId, setCompanyId] = useState<string>(
    role === "company_admin" ? (user?.company_id || "") : (selectedCompanyId || ""));
  const [tab, setTab] = useState<string>("payroll");
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [pay, setPay] = useState<any>(null);
  const [att, setAtt] = useState<any>(null);
  const [ppl, setPpl] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (role !== "company_admin" && selectedCompanyId) setCompanyId(selectedCompanyId);
  }, [selectedCompanyId, role]);

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      if (tab === "payroll") setPay(await api<any>(`/analytics/payroll?company_id=${companyId}&month=${month}`));
      if (tab === "attendance") setAtt(await api<any>(`/analytics/attendance?company_id=${companyId}&month=${month}`));
      if (tab === "people") setPpl(await api<any>(`/analytics/people?company_id=${companyId}`));
    } catch { /* read-only view; keep last */ }
    finally { setLoading(false); }
  }, [companyId, month, tab]);
  useEffect(() => { load(); }, [load]);

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) return <Redirect href="/" />;

  const printCharts = () => { if (Platform.OS === "web") window.print(); };

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.hBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>📊 Charts &amp; Analytics</Text>
          <Text style={s.subtitle}>Read-only visualization — no process is ever triggered</Text>
        </View>
        {Platform.OS === "web" ? (
          <Pressable onPress={printCharts} hitSlop={10} style={s.hBtn} testID="charts-print">
            <Ionicons name="print-outline" size={20} color={colors.brandPrimary} />
          </Pressable>
        ) : null}
      </View>

      <ScrollView contentContainerStyle={s.body}>
        {role !== "company_admin" ? (
          <View style={{ marginBottom: 12 }}>
            <CompanyPicker value={companyId} onChange={(v: any) => setCompanyId(v || "")} />
          </View>
        ) : null}

        <View style={s.tabs}>
          {TABS.map(([k, l]) => (
            <Pressable key={k} style={[s.tab, tab === k && s.tabOn]} onPress={() => setTab(k)} testID={`an-tab-${k}`}>
              <Text style={[s.tabT, tab === k && s.tabTOn]}>{l}</Text>
            </Pressable>
          ))}
          {tab !== "people" ? (
            <View style={s.mRow}>
              <Pressable style={s.mBtn} onPress={() => setMonth(monthShift(month, -1))} testID="an-prev">
                <Ionicons name="chevron-back" size={15} color={colors.brandPrimary} />
              </Pressable>
              <Text style={s.mTxt}>{month}</Text>
              <Pressable style={s.mBtn} onPress={() => setMonth(monthShift(month, 1))} testID="an-next">
                <Ionicons name="chevron-forward" size={15} color={colors.brandPrimary} />
              </Pressable>
            </View>
          ) : null}
        </View>

        {!companyId ? <Text style={s.empty}>Select a firm to view analytics.</Text> : null}
        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 30 }} /> : null}

        {!loading && tab === "payroll" && pay ? (
          !pay.has_data && !pay.trend.some((t: any) => t.gross) ? (
            <Text style={s.empty}>No salary run found for {month} — process salary from the existing Salary module first (charts only visualize existing data).</Text>
          ) : (
            <>
              <View style={s.kpiRow}>
                <KpiCard label="Employees" value={String(pay.kpis.employees)} tint="#2563EB" />
                <KpiCard label="Gross Salary" value={fmtMoney(pay.kpis.gross)} tint="#059669" />
                <KpiCard label="Net Salary" value={fmtMoney(pay.kpis.net)} tint="#0D9488" />
                <KpiCard label="Deductions" value={fmtMoney(pay.kpis.deductions)} tint="#DC2626" />
                <KpiCard label="PF" value={fmtMoney(pay.kpis.pf)} tint="#7C3AED" />
                <KpiCard label="ESIC" value={fmtMoney(pay.kpis.esic)} tint="#D97706" />
              </View>
              <ChartCard title="Monthly Payroll Trend (Gross)">
                <TrendLine points={pay.trend.map((t: any) => t.gross)}
                  labels={pay.trend.map((t: any) => t.month)} money />
              </ChartCard>
              <ChartCard title="Department-wise Payroll (Gross)">
                <HBar data={pay.dept_bar.map((d: any) => ({ label: d.label, value: d.gross }))} money />
              </ChartCard>
              <ChartCard title="Earnings vs Deductions (monthly)">
                <StackedBars
                  data={pay.earn_vs_ded.map((t: any) => ({ label: t.month, a: t.net, b: t.deductions }))}
                  keys={["Net Pay", "Deductions"]} />
              </ChartCard>
              <ChartCard title="Salary Components"><Donut data={pay.components} money /></ChartCard>
              <ChartCard title="Deduction Split"><Donut data={pay.deduction_split} money /></ChartCard>
              <ChartCard title="PF / ESIC — Employee vs Employer (Compliance run)">
                {pay.pf_esic.source === "none"
                  ? <Text style={s.empty}>No compliance salary run for {month}.</Text>
                  : <HBar money data={[
                      { label: "PF — Employee", value: pay.pf_esic.pf_employee },
                      { label: "PF — Employer", value: pay.pf_esic.pf_employer },
                      { label: "ESIC — Employee", value: pay.pf_esic.esic_employee },
                      { label: "ESIC — Employer", value: pay.pf_esic.esic_employer }]} />}
              </ChartCard>
            </>
          )
        ) : null}

        {!loading && tab === "attendance" && att ? (
          <>
            <View style={s.kpiRow}>
              <KpiCard label="Employees" value={String(att.kpis.employees)} tint="#2563EB" />
              <KpiCard label="Present Days" value={String(att.kpis.present_days)} tint="#059669" />
              <KpiCard label="Leave Days" value={String(att.kpis.leave_days)} tint="#D97706" />
              <KpiCard label="Avg Daily Present" value={String(att.kpis.avg_daily_present)} tint="#7C3AED" />
            </View>
            <ChartCard title="Daily Attendance Trend">
              <TrendLine points={att.daily.map((d: any) => d.present)}
                labels={att.daily.filter((_: any, i: number) => i % Math.ceil(att.daily.length / 6 || 1) === 0).map((d: any) => d.date)}
                color="#059669" />
            </ChartCard>
            <ChartCard title="Present vs Leave vs Absent (day-wise total)"><Donut data={att.status_donut} /></ChartCard>
            {att.leave_types.length ? <ChartCard title="Leave Types"><Donut data={att.leave_types} /></ChartCard> : null}
            <ChartCard title="Punch Sources"><HBar data={att.sources} /></ChartCard>
          </>
        ) : null}

        {!loading && tab === "people" && ppl ? (
          <>
            <View style={s.kpiRow}>
              <KpiCard label="Total Employees" value={String(ppl.kpis.total)} tint="#2563EB" />
              <KpiCard label="Active" value={String(ppl.kpis.active)} tint="#059669" />
              <KpiCard label="UAN Available" value={String(ppl.kpis.uan_available)} tint="#7C3AED" />
              <KpiCard label="ESIC IP Available" value={String(ppl.kpis.esic_available)} tint="#D97706" />
            </View>
            <ChartCard title="Department-wise Employees"><HBar data={ppl.dept_bar} /></ChartCard>
            <ChartCard title="Designation-wise Employees"><HBar data={ppl.designation_bar} /></ChartCard>
            <ChartCard title="Joining Trend">
              <TrendLine points={ppl.joining_trend.map((j: any) => j.joins)}
                labels={ppl.joining_trend.map((j: any) => j.month)} color="#7C3AED" />
            </ChartCard>
            <ChartCard title="PF / UAN Availability"><Donut data={ppl.uan_donut} /></ChartCard>
            <ChartCard title="ESIC IP Availability"><Donut data={ppl.esic_donut} /></ChartCard>
            {ppl.expense_categories.length ? (
              <ChartCard title="Expenses by Category (₹)"><Donut data={ppl.expense_categories} money /></ChartCard>
            ) : null}
            {ppl.expense_status.length ? (
              <ChartCard title="Expense Claims by Status"><HBar data={ppl.expense_status} /></ChartCard>
            ) : null}
            {ppl.approvals.length ? (
              <ChartCard title="Approval Workflow Status"><Donut data={ppl.approvals} /></ChartCard>
            ) : null}
            {ppl.advances.length ? (
              <ChartCard title="Advances (₹ by status)"><HBar money data={ppl.advances} /></ChartCard>
            ) : null}
          </>
        ) : null}
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surfaceSecondary, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  hBtn: { width: 38, height: 38, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceTertiary },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 1 },
  body: { padding: 16, width: "100%", maxWidth: 900, alignSelf: "center" },
  tabs: { flexDirection: "row", gap: 6, marginBottom: 12, flexWrap: "wrap", alignItems: "center" },
  tab: {
    paddingHorizontal: 12, paddingVertical: 9, borderRadius: 10, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  tabOn: { backgroundColor: "rgba(37,99,235,0.1)", borderColor: colors.brandPrimary },
  tabT: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTOn: { color: colors.brandPrimary },
  mRow: { flexDirection: "row", alignItems: "center", gap: 6, marginLeft: "auto" },
  mBtn: {
    width: 30, height: 30, borderRadius: 8, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary, alignItems: "center", justifyContent: "center",
  },
  mTxt: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  kpiRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  empty: { fontSize: 12.5, color: colors.onSurfaceTertiary, textAlign: "center", marginVertical: 24, paddingHorizontal: 16 },
});
