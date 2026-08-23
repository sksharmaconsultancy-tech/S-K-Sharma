/**
 * Iter 686 — CENTRAL STATISTICAL · Annual Labour Statistics (user spec).
 * Aggregation-only reporting layer on top of existing payroll/attendance
 * data. Tabs: Overview · Department · Employee · Category · Monthly ·
 * Validation. FY = April→March. Excel / PDF export, finalize snapshots,
 * previous-FY comparison, employee drill-down.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
  Modal,
  StyleSheet,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import RegisterTable, { ExportButtons, shared } from "@/src/components/RegisterTable";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "department", label: "Department" },
  { key: "employee", label: "Employee" },
  { key: "category", label: "Category" },
  { key: "monthly", label: "Monthly" },
  { key: "validation", label: "Validation" },
];

const inr = (v: any) => (v == null ? "—" : `₹${Number(v).toLocaleString("en-IN")}`);

export default function CentralStatisticalScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [tab, setTab] = useState("overview");
  const now = new Date();
  const defFy = now.getMonth() + 1 >= 4 ? now.getFullYear() : now.getFullYear() - 1;
  const [fy, setFy] = useState(String(defFy));
  const [dept, setDept] = useState("");
  const [search, setSearch] = useState("");
  const [comparePrev, setComparePrev] = useState(false);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [snaps, setSnaps] = useState<any[]>([]);
  const [drill, setDrill] = useState<any>(null);
  const [drillLoading, setDrillLoading] = useState(false);
  const [finalizing, setFinalizing] = useState(false);

  const companyId =
    user?.role === "company_admin" ? user.company_id : selectedCompanyId;

  const load = useCallback(async () => {
    if (!companyId || !/^\d{4}$/.test(fy)) return;
    setLoading(true);
    try {
      const r = await api<any>(
        `/admin/central-stats/annual?company_id=${companyId}&fy_start_year=${fy}` +
          `${dept ? `&department=${encodeURIComponent(dept)}` : ""}` +
          `${comparePrev ? "&compare_prev=true" : ""}`,
      );
      setData(r);
      const s = await api<any>(`/admin/central-stats/snapshots?company_id=${companyId}`);
      setSnaps(s.snapshots || []);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, fy, dept, comparePrev]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDrill = useCallback(
    async (uid: string) => {
      setDrillLoading(true);
      setDrill({});
      try {
        const r = await api<any>(
          `/admin/central-stats/employee-detail?company_id=${companyId}` +
            `&fy_start_year=${fy}&user_id=${uid}`,
        );
        setDrill(r);
      } catch {
        setDrill(null);
      } finally {
        setDrillLoading(false);
      }
    },
    [companyId, fy],
  );

  const finalize = useCallback(async () => {
    if (!companyId) return;
    setFinalizing(true);
    try {
      await api<any>(`/admin/central-stats/finalize`, {
        method: "POST",
        body: JSON.stringify({ company_id: companyId, fy_start_year: Number(fy) }),
      });
      await load();
    } finally {
      setFinalizing(false);
    }
  }, [companyId, fy, load]);

  const employees = useMemo(() => {
    let rows = data?.employees || [];
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(
        (e: any) =>
          e.name.toLowerCase().includes(q) ||
          String(e.employee_code).toLowerCase().includes(q) ||
          e.department.toLowerCase().includes(q),
      );
    }
    return rows;
  }, [data, search]);

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role))
    return <Redirect href="/" />;

  const k = data?.kpis || {};
  const kpiCards: [string, any][] = [
    ["Total Employment", k.total_employment],
    ["Average Employment", k.avg_employment],
    ["Total Man-days", k.total_mandays],
    ["Avg Attendance %", `${k.avg_attendance_pct ?? 0}%`],
    ["Total Salary/Wages", inr(k.total_gross)],
    ["Total OT Cost", inr(k.total_ot_cost)],
    ["Total Labour Cost", inr(k.total_labour_cost)],
    ["Avg Cost / Employee", inr(k.avg_labour_cost_per_emp)],
    ["Joining / Exit", `${k.joining ?? 0} / ${k.exit ?? 0}`],
    ["Attrition %", `${k.attrition_pct ?? 0}%`],
  ];

  const Bar = ({ rows, valKey, color }: any) => {
    const mx = Math.max(1, ...rows.map((m: any) => Number(m[valKey]) || 0));
    return (
      <>
        {rows.map((m: any) => (
          <View key={m.key} style={st.barRow}>
            <Text style={st.barLbl}>{m.month}</Text>
            <View style={st.barTrack}>
              <View
                style={[st.bar, { backgroundColor: color, width: `${((Number(m[valKey]) || 0) / mx) * 100}%` }]}
              />
            </View>
            <Text style={st.barVal}>{m[valKey]}</Text>
          </View>
        ))}
      </>
    );
  };

  return (
    <SafeAreaView style={shared.safe} edges={["top"]}>
      <View style={shared.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="cs-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={shared.headerTitle}>Central Statistical — Annual Labour</Text>
        {companyId ? (
          <ExportButtons
            basePath={`/admin/central-stats/annual?company_id=${companyId}&fy_start_year=${fy}`}
            fileBase={`annual-labour-stats-${fy}`}
          />
        ) : (
          <View style={{ width: 40 }} />
        )}
      </View>
      <ScrollView contentContainerStyle={{ padding: 12 }}>
        <View style={shared.tabs}>
          {TABS.map((t) => (
            <Pressable
              key={t.key}
              onPress={() => setTab(t.key)}
              style={[shared.tab, tab === t.key && shared.tabActive]}
              testID={`cs-tab-${t.key}`}
            >
              <Text style={[shared.tabTxt, tab === t.key && shared.tabTxtActive]}>
                {t.label}
              </Text>
            </Pressable>
          ))}
        </View>

        <View style={[shared.row, { flexWrap: "wrap", gap: 8 }]}>
          <Text style={shared.meta}>FY (Apr–Mar):</Text>
          <TextInput
            style={[shared.input, { width: 74 }]}
            value={fy}
            onChangeText={setFy}
            keyboardType="number-pad"
            maxLength={4}
            testID="cs-fy"
          />
          <Text style={shared.meta}>Dept:</Text>
          <TextInput
            style={[shared.input, { width: 130 }]}
            value={dept}
            onChangeText={setDept}
            placeholder="All"
            testID="cs-dept"
          />
          <Pressable
            onPress={() => setComparePrev((v) => !v)}
            style={[st.chip, comparePrev && st.chipOn]}
            testID="cs-compare"
          >
            <Text style={[st.chipTxt, comparePrev && st.chipTxtOn]}>
              {comparePrev ? "✓ " : ""}Compare Prev FY
            </Text>
          </Pressable>
          <Pressable onPress={() => void load()} style={st.chip} testID="cs-refresh">
            <Text style={st.chipTxt}>↻ Refresh</Text>
          </Pressable>
          <Pressable
            onPress={() => void finalize()}
            style={[st.chip, { backgroundColor: "#065F46", borderColor: "#065F46" }]}
            disabled={finalizing}
            testID="cs-finalize"
          >
            <Text style={[st.chipTxt, { color: "#fff" }]}>
              {finalizing ? "Finalizing…" : "🔒 Finalize"}
            </Text>
          </Pressable>
        </View>

        {loading && <ActivityIndicator style={{ marginVertical: 24 }} />}
        {!loading && !data && (
          <Text style={{ color: colors.onSurfaceSecondary, marginTop: 20 }}>
            Select a company and financial year, then Refresh.
          </Text>
        )}

        {!loading && data && tab === "overview" && (
          <>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>
                {data.company?.name} · {data.fy}
              </Text>
              <Text style={st.sub}>
                {data.company?.address || ""} {data.company?.state || ""} · Generated{" "}
                {String(data.generated_at).slice(0, 16).replace("T", " ")}
              </Text>
            </View>
            <View style={st.kpiWrap}>
              {kpiCards.map(([lbl, v]) => (
                <View key={lbl} style={st.kpi}>
                  <Text style={st.kpiVal}>{v ?? "—"}</Text>
                  <Text style={st.kpiLbl}>{lbl}</Text>
                </View>
              ))}
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Employment Summary</Text>
              <RegisterTable
                columns={[
                  { key: "particular", label: "Particular" },
                  { key: "male", label: "Male" },
                  { key: "female", label: "Female" },
                  { key: "other", label: "Other" },
                  { key: "total", label: "Total" },
                ]}
                rows={data.employment_summary || []}
              />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Skill-wise Summary</Text>
              <RegisterTable
                columns={[
                  { key: "particular", label: "Skill Category" },
                  { key: "male", label: "Male" },
                  { key: "female", label: "Female" },
                  { key: "other", label: "Other" },
                  { key: "total", label: "Total" },
                ]}
                rows={data.skill_summary || []}
              />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Attendance / Man-days Summary</Text>
              {Object.entries(data.attendance_summary || {}).map(([kk, vv]: any) => (
                <View key={kk} style={st.kvRow}>
                  <Text style={st.kvLbl}>{kk.replace(/_/g, " ")}</Text>
                  <Text style={st.kvVal}>{String(vv)}</Text>
                </View>
              ))}
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Wage & Salary Summary (Annual · Monthly Avg)</Text>
              {Object.entries(data.wage_summary || {}).map(([kk, vv]: any) => (
                <View key={kk} style={st.kvRow}>
                  <Text style={st.kvLbl}>{kk.replace(/_/g, " ")}</Text>
                  <Text style={st.kvVal}>
                    {inr(vv)} · {inr((data.wage_monthly_avg || {})[kk])}
                  </Text>
                </View>
              ))}
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>PF / ESIC / Statutory Employer Cost</Text>
              <RegisterTable
                columns={[
                  { key: "particular", label: "Particular" },
                  { key: "employee", label: "Employee Contribution" },
                  { key: "employer", label: "Employer Contribution" },
                  { key: "annual", label: "Annual Amount" },
                ]}
                rows={data.statutory_summary || []}
              />
            </View>
            {data.prev_fy_comparison ? (
              <View style={shared.card}>
                <Text style={shared.cardTitle}>Current FY vs Previous FY</Text>
                <RegisterTable
                  columns={[
                    { key: "particular", label: "Particular" },
                    { key: "current", label: "Current FY" },
                    { key: "previous", label: "Previous FY" },
                    { key: "change_pct", label: "% Change" },
                  ]}
                  rows={data.prev_fy_comparison}
                />
              </View>
            ) : null}
            {snaps.length ? (
              <View style={shared.card}>
                <Text style={shared.cardTitle}>🔒 Finalized Reports</Text>
                {snaps.map((s) => (
                  <Text key={s.snapshot_id} style={st.sub}>
                    v{s.version} · FY {s.fy_start_year}-{String(s.fy_start_year + 1).slice(-2)} ·{" "}
                    {String(s.finalized_at).slice(0, 16).replace("T", " ")} · by {s.generated_by}
                  </Text>
                ))}
              </View>
            ) : null}
          </>
        )}

        {!loading && data && tab === "department" && (
          <View style={shared.card}>
            <Text style={shared.cardTitle}>Department-wise Annual Report</Text>
            <Text style={st.sub}>Tap a department to see its employees.</Text>
            <RegisterTable
              columns={[
                { key: "department", label: "Department" },
                { key: "strength", label: "Strength" },
                { key: "male", label: "Male" },
                { key: "female", label: "Female" },
                { key: "mandays", label: "Man-days" },
                { key: "ot_hours", label: "OT Hrs" },
                { key: "gross", label: "Salary Cost" },
                { key: "labour_cost", label: "Labour Cost" },
                { key: "joining", label: "Joining" },
                { key: "exit", label: "Exit" },
                { key: "attrition_pct", label: "Attrition %" },
              ]}
              rows={data.departments || []}
              onRowPress={(r: any) => {
                setDept(r.department === "—" ? "" : r.department);
                setTab("employee");
              }}
            />
          </View>
        )}

        {!loading && data && tab === "employee" && (
          <View style={shared.card}>
            <Text style={shared.cardTitle}>Employee-wise Annual Summary</Text>
            <TextInput
              style={[shared.input, { marginBottom: 8, width: "100%" }]}
              value={search}
              onChangeText={setSearch}
              placeholder="Search name / code / department…"
              testID="cs-emp-search"
            />
            <Text style={st.sub}>Tap an employee for month-wise drill-down.</Text>
            <RegisterTable
              columns={[
                { key: "employee_code", label: "Code" },
                { key: "name", label: "Name" },
                { key: "gender", label: "Gender" },
                { key: "department", label: "Department" },
                { key: "employment_type", label: "Type" },
                { key: "category", label: "Category" },
                { key: "skill", label: "Skill" },
                { key: "mandays", label: "Man-days" },
                { key: "ot_hours", label: "OT Hrs" },
                { key: "gross", label: "Gross" },
                { key: "pf_er", label: "PF ER" },
                { key: "esic_er", label: "ESIC ER" },
                { key: "labour_cost", label: "Labour Cost" },
              ]}
              rows={employees}
              onRowPress={(r: any) => void openDrill(r.user_id)}
            />
          </View>
        )}

        {!loading && data && tab === "category" && (
          <View style={shared.card}>
            <Text style={shared.cardTitle}>Category-wise Analysis</Text>
            <RegisterTable
              columns={[
                { key: "group", label: "Group" },
                { key: "category", label: "Category" },
                { key: "employees", label: "Employees" },
                { key: "mandays", label: "Man-days" },
                { key: "ot_hours", label: "OT Hrs" },
                { key: "gross", label: "Salary/Wages" },
                { key: "labour_cost", label: "Labour Cost" },
              ]}
              rows={data.categories || []}
            />
          </View>
        )}

        {!loading && data && tab === "monthly" && (
          <>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Monthly Employment Summary (Apr → Mar)</Text>
              <RegisterTable
                columns={[
                  { key: "month", label: "Month" },
                  { key: "opening", label: "Opening" },
                  { key: "joining", label: "Joining" },
                  { key: "exit", label: "Exit" },
                  { key: "closing", label: "Closing" },
                  { key: "mandays", label: "Man-days" },
                  { key: "paid_days", label: "Paid Days" },
                  { key: "ot_hours", label: "OT Hours" },
                  { key: "attendance_pct", label: "Attendance %" },
                ]}
                rows={data.monthly || []}
              />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Employment Trend</Text>
              <Bar rows={data.monthly || []} valKey="opening" color={colors.brandPrimary} />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Man-days Trend</Text>
              <Bar rows={data.monthly || []} valKey="mandays" color="#8B5CF6" />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>OT Trend</Text>
              <Bar rows={data.monthly || []} valKey="ot_hours" color="#F59E0B" />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Attendance % Trend</Text>
              <Bar rows={data.monthly || []} valKey="attendance_pct" color="#10B981" />
            </View>
          </>
        )}

        {!loading && data && tab === "validation" && (
          <>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Report Validation</Text>
              {[
                ["Employee Master", data.validation?.employee_master],
                ["Attendance coverage", data.validation?.attendance],
                ["Salary coverage", data.validation?.salary],
              ].map(([lbl, v]: any) => (
                <View key={lbl} style={st.kvRow}>
                  <Text style={st.kvLbl}>{lbl}</Text>
                  <Text style={st.kvVal}>{v}</Text>
                </View>
              ))}
              {(data.validation?.mismatch_attendance || []).length ? (
                <Text style={st.warn}>
                  ⚠ {data.validation.mismatch_attendance.length} employee(s) have no
                  attendance in this FY: {data.validation.mismatch_attendance.join(", ")}
                </Text>
              ) : null}
              {(data.validation?.mismatch_salary || []).length ? (
                <Text style={st.warn}>
                  ⚠ {data.validation.mismatch_salary.length} employee(s) have no salary
                  run row in this FY: {data.validation.mismatch_salary.join(", ")}
                </Text>
              ) : (
                <Text style={st.ok}>✓ All employees covered in salary runs</Text>
              )}
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Data Quality Checks</Text>
              {(data.validation?.data_quality || []).length ? (
                (data.validation.data_quality || []).map((q: any) => (
                  <Text key={q.check} style={st.warn}>
                    ⚠ {q.check}: {q.count}
                  </Text>
                ))
              ) : (
                <Text style={st.ok}>✓ No data quality issues found</Text>
              )}
            </View>
          </>
        )}
      </ScrollView>

      <Modal visible={drill !== null} transparent animationType="slide">
        <View style={st.modalWrap}>
          <View style={st.modalCard}>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={shared.cardTitle}>
                {drill?.employee
                  ? `${drill.employee.name} (${drill.employee.employee_code})`
                  : "Employee Detail"}
              </Text>
              <Pressable onPress={() => setDrill(null)} hitSlop={10} testID="cs-drill-close">
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            {drill?.employee ? (
              <Text style={st.sub}>
                {drill.employee.department || "—"} · {drill.employee.designation || "—"} · DOJ{" "}
                {drill.employee.doj || "—"}
              </Text>
            ) : null}
            {drillLoading ? (
              <ActivityIndicator style={{ marginVertical: 20 }} />
            ) : drill?.rows ? (
              <ScrollView style={{ maxHeight: 440 }}>
                <RegisterTable
                  columns={[
                    { key: "month", label: "Month" },
                    { key: "days", label: "Days" },
                    { key: "present", label: "Present" },
                    { key: "paid", label: "Paid" },
                    { key: "absent", label: "Absent" },
                    { key: "ot_hours", label: "OT Hrs" },
                    { key: "gross", label: "Gross" },
                    { key: "ot_wages", label: "OT Wages" },
                    { key: "employer_cost", label: "Employer Cost" },
                  ]}
                  rows={drill.rows}
                  totals={{ month: "Annual Total", ...drill.annual_total }}
                />
              </ScrollView>
            ) : null}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  kpiWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  kpi: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    padding: 10,
    minWidth: 130,
    flexGrow: 1,
  },
  kpiVal: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  kpiLbl: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  sub: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginBottom: 6 },
  chip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 7,
    backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: "#1D4ED8", borderColor: "#1D4ED8" },
  chipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  chipTxtOn: { color: "#fff" },
  kvRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 4,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  kvLbl: { fontSize: 12, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  kvVal: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  warn: { fontSize: 12, color: "#B45309", marginTop: 5 },
  ok: { fontSize: 12, color: "#15803D", marginTop: 5 },
  barRow: { flexDirection: "row", alignItems: "center", marginBottom: 5 },
  barLbl: { width: 84, fontSize: 11.5, color: colors.onSurfaceSecondary },
  barTrack: {
    flex: 1,
    height: 12,
    backgroundColor: "#EEF2F7",
    borderRadius: 6,
    overflow: "hidden",
  },
  bar: { height: 12, borderRadius: 6 },
  barVal: {
    width: 66,
    fontSize: 11,
    textAlign: "right",
    color: colors.onSurface,
    fontWeight: "700",
  },
  modalWrap: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "flex-end",
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    padding: 16,
    maxHeight: "88%",
  },
});
