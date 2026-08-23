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
import Svg, { Circle, G, Path, Polyline, Text as SvgText } from "react-native-svg";
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
  { key: "charts", label: "📈 Charts" },
  { key: "formats", label: "🏛 Official Formats" },
  { key: "validation", label: "Validation" },
];

const PIE_COLORS = ["#2563EB", "#F59E0B", "#10B981", "#EF4444", "#8B5CF6",
  "#0EA5E9", "#F97316", "#14B8A6", "#E11D48", "#84CC16"];

/** Compact SVG line chart for Apr→Mar trends (Iter 687). */
function LineChart({ rows, valKey, color }: { rows: any[]; valKey: string; color: string }) {
  const W = 640;
  const H = 180;
  const P = 28;
  const vals = rows.map((m) => Number(m[valKey]) || 0);
  const mx = Math.max(1, ...vals);
  const pts = vals
    .map((v, i) => `${P + (i * (W - 2 * P)) / 11},${H - P - (v / mx) * (H - 2 * P)}`)
    .join(" ");
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false}>
      <Svg width={W} height={H + 16}>
        <Polyline points={pts} fill="none" stroke={color} strokeWidth={2.5} />
        {vals.map((v, i) => {
          const x = P + (i * (W - 2 * P)) / 11;
          const y = H - P - (v / mx) * (H - 2 * P);
          return (
            <G key={i}>
              <Circle cx={x} cy={y} r={3.5} fill={color} />
              <SvgText x={x} y={y - 8} fontSize={9} fill={colors.onSurface} textAnchor="middle">
                {v >= 1000 ? `${Math.round(v / 1000)}k` : v}
              </SvgText>
              <SvgText x={x} y={H + 8} fontSize={9} fill={colors.onSurfaceSecondary} textAnchor="middle">
                {String(rows[i].month).slice(0, 3)}
              </SvgText>
            </G>
          );
        })}
      </Svg>
    </ScrollView>
  );
}

/** Compact SVG pie chart with legend (Iter 687). */
function PieChart({ slices }: { slices: { label: string; value: number }[] }) {
  const total = Math.max(1, slices.reduce((s, x) => s + x.value, 0));
  const R = 78;
  const C = 90;
  let ang = -Math.PI / 2;
  const paths = slices.map((s, i) => {
    const frac = s.value / total;
    const a2 = ang + frac * 2 * Math.PI;
    const large = frac > 0.5 ? 1 : 0;
    const p = `M${C},${C} L${C + R * Math.cos(ang)},${C + R * Math.sin(ang)} ` +
      `A${R},${R} 0 ${large} 1 ${C + R * Math.cos(a2)},${C + R * Math.sin(a2)} Z`;
    ang = a2;
    return <Path key={i} d={frac >= 0.999 ? `M${C - R},${C} a${R},${R} 0 1 0 ${2 * R},0 a${R},${R} 0 1 0 ${-2 * R},0` : p} fill={PIE_COLORS[i % PIE_COLORS.length]} />;
  });
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 14 }}>
      <Svg width={180} height={180}>{paths}</Svg>
      <View style={{ flex: 1, minWidth: 180 }}>
        {slices.map((s, i) => (
          <View key={s.label} style={{ flexDirection: "row", alignItems: "center", marginBottom: 4 }}>
            <View style={{ width: 11, height: 11, borderRadius: 3, backgroundColor: PIE_COLORS[i % PIE_COLORS.length], marginRight: 6 }} />
            <Text style={{ fontSize: 11.5, color: colors.onSurface, flex: 1 }} numberOfLines={1}>
              {s.label}
            </Text>
            <Text style={{ fontSize: 11.5, fontWeight: "700", color: colors.onSurface }}>
              {Math.round((s.value / total) * 100)}%
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}

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
  // Iter 687 — Official Formats (ASI-style mapping layer)
  const [formats, setFormats] = useState<any[]>([]);
  const [fmtRender, setFmtRender] = useState<any>(null);
  const [fmtLoading, setFmtLoading] = useState(false);

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

  useEffect(() => {
    if (tab !== "formats" || formats.length) return;
    void (async () => {
      try {
        const r = await api<any>(`/admin/central-stats/formats`);
        setFormats(r.formats || []);
      } catch {}
    })();
  }, [tab, formats.length]);

  const renderFormat = useCallback(
    async (defId: string) => {
      if (!companyId) return;
      setFmtLoading(true);
      try {
        const r = await api<any>(
          `/admin/central-stats/formats/${defId}/render?company_id=${companyId}&fy_start_year=${fy}`,
        );
        setFmtRender(r);
      } catch {
        setFmtRender(null);
      } finally {
        setFmtLoading(false);
      }
    },
    [companyId, fy],
  );

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

        {!loading && data && tab === "charts" && (
          <>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>📈 Employment Trend (Apr → Mar)</Text>
              <LineChart rows={data.monthly || []} valKey="opening" color="#2563EB" />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>💰 Salary Cost Trend</Text>
              <LineChart rows={data.monthly || []} valKey="gross" color="#0EA5E9" />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>🏗 Labour Cost Trend</Text>
              <LineChart rows={data.monthly || []} valKey="labour_cost" color="#E11D48" />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>🕒 OT Hours Trend</Text>
              <LineChart rows={data.monthly || []} valKey="ot_hours" color="#F59E0B" />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>✅ Attendance % Trend</Text>
              <LineChart rows={data.monthly || []} valKey="attendance_pct" color="#10B981" />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>🥧 Labour Cost by Department</Text>
              <PieChart
                slices={(data.departments || [])
                  .filter((d: any) => d.labour_cost > 0)
                  .slice(0, 10)
                  .map((d: any) => ({ label: d.department, value: d.labour_cost }))}
              />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>🥧 Employment by Category</Text>
              <PieChart
                slices={(data.categories || [])
                  .filter((c: any) => c.group === "Employee Category" && c.employees > 0)
                  .map((c: any) => ({ label: c.category, value: c.employees }))}
              />
            </View>
          </>
        )}

        {!loading && data && tab === "formats" && (
          <>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>🏛 Official Statistical Formats</Text>
              <Text style={st.sub}>
                Survey line-items mapped from existing payroll data — no re-entry, no
                recalculation. Not an official government return unless the exact
                notified format is configured.
              </Text>
              {formats.map((f) => (
                <Pressable
                  key={f.definition_id}
                  onPress={() => void renderFormat(f.definition_id)}
                  style={[st.chip, { marginTop: 6, alignSelf: "flex-start" }]}
                  testID={`cs-fmt-${f.definition_id}`}
                >
                  <Text style={st.chipTxt}>
                    {f.builtin ? "📋 " : "🛠 "}
                    {f.name}
                  </Text>
                </Pressable>
              ))}
            </View>
            {fmtLoading && <ActivityIndicator style={{ marginVertical: 16 }} />}
            {!fmtLoading && fmtRender && (
              <View style={shared.card}>
                <Text style={shared.cardTitle}>{fmtRender.format?.name}</Text>
                <Text style={st.sub}>
                  {fmtRender.company?.name} · {fmtRender.fy}
                </Text>
                <RegisterTable
                  columns={[
                    { key: "code", label: "Code" },
                    { key: "label", label: "Item" },
                    { key: "value", label: "Value" },
                  ]}
                  rows={fmtRender.rows || []}
                />
                <ExportButtons
                  basePath={`/admin/central-stats/formats/${fmtRender.format?.definition_id}/render?company_id=${companyId}&fy_start_year=${fy}`}
                  fileBase={`${fmtRender.format?.definition_id}-${fy}`}
                  xlsxOnly
                />
              </View>
            )}
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
