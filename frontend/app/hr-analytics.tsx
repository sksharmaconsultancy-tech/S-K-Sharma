/**
 * Iter 746 — HR ANALYTICS (user PRD Phase 3).
 * Tabs: Management Dashboard | Attrition KPI | Salary Variance.
 * Sab figures REAL data se (Employee Master + Compliance runs + OT entries).
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Redirect } from "expo-router";
import { api, apiBinary } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

const ym = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const rup = (n: any) => `₹${Number(n || 0).toLocaleString("en-IN")}`;

export default function HrAnalyticsScreen() {
  const { user, loading: authLoading } = useAuth();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [tab, setTab] = useState<"dash" | "attrition" | "variance">("dash");
  const [month, setMonth] = useState(ym());
  const [dash, setDash] = useState<any>(null);
  const [att, setAtt] = useState<any>(null);
  const [varc, setVarc] = useState<any>(null);
  const [openReason, setOpenReason] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const cid = user?.role === "company_admin" ? user.company_id : companyId;

  const load = useCallback(async () => {
    if (!cid) return;
    setBusy(true); setMsg(null);
    try {
      if (tab === "dash") setDash(await api<any>(`/hr/dashboard?company_id=${cid}&month=${month}`));
      if (tab === "attrition") setAtt(await api<any>(`/hr/attrition?company_id=${cid}&to_month=${month}`));
      if (tab === "variance") setVarc(await api<any>(`/hr/salary-variance?company_id=${cid}&month=${month}`));
    } catch (e: any) { setMsg(e?.message || "Load failed"); }
    finally { setBusy(false); }
  }, [cid, tab, month]);
  useEffect(() => { load(); }, [load]);

  if (authLoading) return <View style={st.center}><ActivityIndicator /></View>;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role)) return <Redirect href="/" />;

  const dl = async (kind: string, fmt: string) => {
    try {
      const r = await apiBinary(`/hr/report?kind=${kind}&fmt=${fmt}&company_id=${cid}&month=${month}&to_month=${month}`);
      if (Platform.OS === "web" && (r as any).webBlobUrl) {
        const a = document.createElement("a");
        a.href = (r as any).webBlobUrl; a.download = `${kind}_${month}.${fmt}`; a.click();
      }
    } catch (e: any) { setMsg(e?.message || "Download failed"); }
  };
  const kpi = (label: string, value: any, color?: string) => (
    <View style={st.kpi} key={label}>
      <Text style={[st.kpiVal, color ? { color } : null]}>{value}</Text>
      <Text style={st.kpiLbl}>{label}</Text>
    </View>
  );

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={st.body}>
        <Text style={st.h1}>📊 HR Analytics</Text>
        {user.role !== "company_admin" && <CompanyPicker value={companyId} onChange={setCompanyId} />}
        <View style={st.row}>
          <TextInput style={[st.input, { width: 100 }]} value={month} onChangeText={setMonth} placeholder="YYYY-MM" placeholderTextColor={colors.onSurfaceTertiary} />
          <Pressable style={st.btnSm} onPress={load}><Text style={st.btnTxt}>Load</Text></Pressable>
        </View>
        <View style={st.tabs}>
          {([["dash", "Dashboard"], ["attrition", "Attrition"], ["variance", "Salary Variance"]] as [any, string][]).map(([t, l]) => (
            <Pressable key={t} style={[st.tab, tab === t && st.tabOn]} onPress={() => setTab(t)} testID={`hra-tab-${t}`}>
              <Text style={[st.tabTxt, tab === t && st.tabTxtOn]}>{l}</Text>
            </Pressable>
          ))}
        </View>
        {msg ? <Text style={st.msg}>{msg}</Text> : null}
        {busy ? <ActivityIndicator style={{ marginVertical: 10 }} /> : null}

        {tab === "dash" && dash ? (
          <>
            <View style={st.kpis}>
              {kpi("Total Employees", dash.kpis.total_employees)}
              {kpi("Active", dash.kpis.active_employees, "#7dc97d")}
              {kpi("New Joiners", dash.kpis.new_joiners, "#9fc3ff")}
              {kpi("Exits", dash.kpis.exits, "#ff8a80")}
              {kpi("Attrition %", `${dash.kpis.attrition_pct}%`, "#ffb74d")}
              {kpi("Current Payroll", rup(dash.kpis.current_payroll))}
              {kpi("Variance %", `${dash.kpis.salary_variance_pct}%`, dash.kpis.salary_variance >= 0 ? "#ff8a80" : "#7dc97d")}
              {kpi("OT Hours", dash.kpis.ot_hours)}
              {kpi("OT Cost", rup(dash.kpis.ot_cost))}
              {kpi("Pending OT", dash.kpis.pending_ot_approvals, "#ffb74d")}
            </View>
            {(dash.alerts || []).map((a: any, i: number) => (
              <Text key={i} style={[st.alert, a.level === "error" && { color: "#ff8a80" }]}>⚠️ {a.text}</Text>
            ))}
            <View style={st.card}>
              <Text style={st.h2}>⏱️ OT Section</Text>
              <Text style={st.sum}>Total {dash.ot.attendance_ot}h · Eligible {dash.ot.eligible_ot}h · Approved {dash.ot.approved_ot}h · Pending {dash.ot.pending_ot}h · Rejected {dash.ot.rejected_ot}h · Excess {dash.ot.excess_ot}h · Cost {rup(dash.ot.ot_cost)} · Cap violations {dash.ot.cap_violations}</Text>
            </View>
            <View style={st.card}>
              <Text style={st.h2}>💰 Payroll Analysis</Text>
              <Text style={st.sum}>Previous {rup(dash.kpis.previous_payroll)} → Current {rup(dash.kpis.current_payroll)} · Variance {rup(dash.kpis.salary_variance)} ({dash.kpis.salary_variance_pct}%)</Text>
            </View>
            <View style={st.card}>
              <Text style={st.h2}>🏢 Organization</Text>
              <Text style={st.lbl}>Branch-wise Headcount</Text>
              {(dash.organization.branch_wise || []).map((b: any) => <Text key={b.name} style={st.sum}>{b.name}: {b.count}</Text>)}
              <Text style={st.lbl}>Department-wise Headcount</Text>
              {(dash.organization.department_wise || []).slice(0, 12).map((b: any) => <Text key={b.name} style={st.sum}>{b.name}: {b.count}</Text>)}
              {(dash.organization.manager_teams || []).length ? (<>
                <Text style={st.lbl}>Manager-wise Team Size</Text>
                {dash.organization.manager_teams.map((m: any) => <Text key={m.manager} style={st.sum}>{m.manager}: {m.team_size}</Text>)}
              </>) : null}
            </View>
          </>
        ) : null}

        {tab === "attrition" && att ? (
          <>
            <View style={st.kpis}>
              {kpi("Opening HC", att.period.opening)}
              {kpi("Joiners", att.period.joiners, "#9fc3ff")}
              {kpi("Exits", att.period.exits, "#ff8a80")}
              {kpi("Closing HC", att.period.closing)}
              {kpi("Avg HC", att.period.avg_headcount)}
              {kpi("Attrition %", `${att.period.attrition_pct}%`, "#ffb74d")}
              {kpi("Voluntary", att.voluntary_exits)}
              {kpi("Involuntary", att.involuntary_exits, "#ff8a80")}
            </View>
            <Text style={st.sum}>Period: {att.period.from} → {att.period.to} (12-month trend, real joining/exit records se)</Text>
            <View style={st.card}>
              <Text style={st.h2}>📈 Monthly Trend</Text>
              {(att.monthly_trend || []).map((t: any) => (
                <Text key={t.month} style={st.sum}>{t.month}: open {t.opening} · +{t.joiners} / −{t.exits} · close {t.closing} · attrition {t.attrition_pct}%</Text>
              ))}
            </View>
            <View style={st.card}>
              <Text style={st.h2}>🚪 Exit Reasons</Text>
              {(att.exit_reasons || []).map((r: any) => <Text key={r.reason} style={st.sum}>{r.reason}: {r.count}</Text>)}
              {!att.exit_reasons?.length ? <Text style={st.sum}>Is period me koi exit nahi</Text> : null}
            </View>
            <View style={st.card}>
              <Text style={st.h2}>🗂️ Department / Branch / Designation-wise Exits</Text>
              {(att.department_wise || []).map((r: any) => <Text key={`d${r.name}`} style={st.sum}>Dept {r.name}: {r.exits}</Text>)}
              {(att.branch_wise || []).map((r: any) => <Text key={`b${r.name}`} style={st.sum}>Branch {r.name}: {r.exits}</Text>)}
              {(att.designation_wise || []).map((r: any) => <Text key={`g${r.name}`} style={st.sum}>Desig {r.name}: {r.exits}</Text>)}
            </View>
            <View style={st.rowBtns}>
              <Pressable style={st.btnXs} onPress={() => dl("attrition", "xlsx")}><Text style={st.btnTxt}>Attrition Excel</Text></Pressable>
              <Pressable style={st.btnXs} onPress={() => dl("exit_reasons", "xlsx")}><Text style={st.btnTxt}>Exit Reasons Excel</Text></Pressable>
              <Pressable style={[st.btnXs, { backgroundColor: "#b3261e" }]} onPress={() => dl("attrition", "pdf")}><Text style={st.btnTxt}>PDF</Text></Pressable>
            </View>
          </>
        ) : null}

        {tab === "variance" && varc ? (
          <>
            <View style={st.kpis}>
              {kpi("Previous", rup(varc.previous_payroll))}
              {kpi("Current", rup(varc.current_payroll))}
              {kpi("Variance", rup(varc.variance), varc.variance >= 0 ? "#ff8a80" : "#7dc97d")}
              {kpi("Variance %", `${varc.variance_pct}%`, "#ffb74d")}
              {kpi("Emp Count", `${varc.employee_count_prev} → ${varc.employee_count_cur}`)}
            </View>
            <Text style={st.sum}>{varc.previous_month} → {varc.month} · reason par tap karke employee drill-down dekhein</Text>
            {(varc.reasons || []).map((r: any) => (
              <View key={r.reason} style={st.card}>
                <Pressable onPress={() => setOpenReason(openReason === r.reason ? null : r.reason)} testID={`hra-reason-${r.reason}`}>
                  <Text style={st.h2}>{openReason === r.reason ? "▼" : "▶"} {r.reason} — {rup(r.amount)} ({r.count} emp)</Text>
                </Pressable>
                {openReason === r.reason ? (r.employees || []).map((e: any) => (
                  <Text key={`${r.reason}${e.user_id}`} style={st.sum}>{e.employee_code} · {e.name}: {rup(e.previous)} → {rup(e.current)} ({e.diff >= 0 ? "+" : ""}{rup(e.diff)})</Text>
                )) : null}
              </View>
            ))}
            <View style={st.rowBtns}>
              <Pressable style={st.btnXs} onPress={() => dl("variance", "xlsx")}><Text style={st.btnTxt}>Variance Excel</Text></Pressable>
              <Pressable style={st.btnXs} onPress={() => dl("variance_reasons", "xlsx")}><Text style={st.btnTxt}>Reasons Excel</Text></Pressable>
              <Pressable style={[st.btnXs, { backgroundColor: "#b3261e" }]} onPress={() => dl("variance", "pdf")}><Text style={st.btnTxt}>PDF</Text></Pressable>
            </View>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background },
  body: { padding: spacing.lg, paddingBottom: 80 },
  h1: { fontSize: 20, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  h2: { fontSize: 14, fontWeight: "800", color: colors.onSurface, marginBottom: 6 },
  row: { flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" },
  rowBtns: { flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" },
  tabs: { flexDirection: "row", gap: 8, marginVertical: 10, flexWrap: "wrap" },
  tab: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md, backgroundColor: colors.surfaceElevated },
  tabOn: { backgroundColor: colors.cta },
  tabTxt: { color: colors.onSurfaceSecondary, fontWeight: "700", fontSize: 13 },
  tabTxtOn: { color: "#fff" },
  kpis: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginVertical: 8 },
  kpi: { backgroundColor: colors.surface, borderRadius: radius.md, padding: 12, minWidth: 105, flexGrow: 1 },
  kpiVal: { color: colors.onSurface, fontSize: 16, fontWeight: "800" },
  kpiLbl: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, marginTop: 10 },
  sum: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 3, lineHeight: 17 },
  lbl: { color: colors.onSurface, fontSize: 13, fontWeight: "700", marginTop: 8 },
  alert: { color: "#ffb74d", fontSize: 13, marginTop: 6, fontWeight: "600" },
  msg: { color: "#ffd54f", marginVertical: 6, fontSize: 13 },
  input: { backgroundColor: colors.surfaceElevated, color: colors.onSurface, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 8, fontSize: 13 },
  btnSm: { backgroundColor: colors.cta, borderRadius: radius.md, paddingVertical: 9, paddingHorizontal: 14 },
  btnXs: { backgroundColor: "#2e7d32", borderRadius: radius.sm, paddingVertical: 6, paddingHorizontal: 10 },
  btnTxt: { color: "#fff", fontWeight: "700", fontSize: 12 },
});
