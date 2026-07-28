/**
 * Labour Statistics & HR Analytics (Phase B).
 * Tabs: HR Dashboard · Department Register · Category Manpower ·
 * Monthly Labour Return · Turnover Analysis · Welfare & Compliance.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
  StyleSheet,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import RegisterTable, {
  ExportButtons,
  shared,
} from "@/src/components/RegisterTable";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";

const TABS = [
  { key: "dashboard", label: "HR Dashboard" },
  { key: "department", label: "Department Register" },
  { key: "category", label: "Category Manpower" },
  { key: "monthly-return", label: "Monthly Return" },
  { key: "turnover", label: "Turnover" },
  { key: "welfare", label: "Welfare & Compliance" },
];

export default function LabourStatisticsScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [tab, setTab] = useState("dashboard");
  const [month, setMonth] = useState(() =>
    new Date().toISOString().slice(0, 7),
  );
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const companyId =
    user?.role === "company_admin" ? user.company_id : selectedCompanyId;

  const load = useCallback(async () => {
    if (!companyId || !/^\d{4}-\d{2}$/.test(month)) return;
    setLoading(true);
    try {
      const fy =
        Number(month.slice(5, 7)) >= 4
          ? Number(month.slice(0, 4))
          : Number(month.slice(0, 4)) - 1;
      const q =
        tab === "turnover"
          ? `fy_start_year=${fy}`
          : `month=${month}`;
      const r = await api<any>(
        `/admin/labour-stats/${tab}?company_id=${companyId}&${q}`,
      );
      setData(r);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, tab, month]);

  useEffect(() => {
    void load();
  }, [load]);

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role))
    return <Redirect href="/" />;

  const k = data?.kpis || {};
  const kpiCards: [string, any][] = [
    ["Total Employees", k.total_employees],
    ["Today Present", k.today_present],
    ["Today Absent", k.today_absent],
    ["OT Employees", k.ot_employees],
    ["Salary Cost", k.salary_cost != null ? `₹${Number(k.salary_cost).toLocaleString("en-IN")}` : "—"],
    ["Labour Cost", k.labour_cost != null ? `₹${Number(k.labour_cost).toLocaleString("en-IN")}` : "—"],
    ["Avg Salary", k.avg_salary != null ? `₹${Number(k.avg_salary).toLocaleString("en-IN")}` : "—"],
    ["Joining / Exit", `${k.joining ?? 0} / ${k.exit ?? 0}`],
    ["Attrition %", `${k.attrition_pct ?? 0}%`],
    ["Gender Ratio", k.gender_ratio],
    ["PF %", `${k.pf_pct ?? 0}%`],
    ["ESIC %", `${k.esic_pct ?? 0}%`],
  ];
  const deptMax = Math.max(
    1,
    ...Object.values<number>(data?.department_strength || {}),
  );

  return (
    <SafeAreaView style={shared.safe} edges={["top"]}>
      <View style={shared.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="ls-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={shared.headerTitle}>Labour Statistics & HR Analytics</Text>
        {tab !== "dashboard" && companyId ? (
          <ExportButtons
            basePath={`/admin/labour-stats/${tab}?company_id=${companyId}&month=${month}`}
            fileBase={`${tab}_${month}`}
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
              testID={`ls-tab-${t.key}`}
            >
              <Text
                style={[shared.tabTxt, tab === t.key && shared.tabTxtActive]}
              >
                {t.label}
              </Text>
            </Pressable>
          ))}
        </View>
        <View style={shared.row}>
          <Text style={shared.meta}>Month (YYYY-MM):</Text>
          <TextInput
            style={shared.input}
            value={month}
            onChangeText={setMonth}
            placeholder="2026-07"
            testID="ls-month"
          />
        </View>
        {loading && <ActivityIndicator style={{ marginVertical: 24 }} />}

        {!loading && tab === "dashboard" && data && (
          <>
            <View style={st.kpiWrap}>
              {kpiCards.map(([lbl, v]) => (
                <View key={lbl} style={st.kpi}>
                  <Text style={st.kpiVal}>{v ?? "—"}</Text>
                  <Text style={st.kpiLbl}>{lbl}</Text>
                </View>
              ))}
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>⚡ AI Insights</Text>
              {(data.insights || []).map((i: any, idx: number) => (
                <Text
                  key={idx}
                  style={[
                    st.insight,
                    i.level === "high" && { color: "#B91C1C" },
                    i.level === "medium" && { color: "#B45309" },
                    i.level === "ok" && { color: "#15803D" },
                  ]}
                >
                  {i.level === "high" ? "🔴" : i.level === "medium" ? "🟠" : "🟢"}{" "}
                  {i.text}
                </Text>
              ))}
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Department Strength</Text>
              {Object.entries<number>(data.department_strength || {}).map(
                ([d, n]) => (
                  <View key={d} style={st.barRow}>
                    <Text style={st.barLbl}>{d}</Text>
                    <View style={st.barTrack}>
                      <View
                        style={[st.bar, { width: `${(n / deptMax) * 100}%` }]}
                      />
                    </View>
                    <Text style={st.barVal}>{n}</Text>
                  </View>
                ),
              )}
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Age Distribution</Text>
              {Object.entries<number>(data.age_distribution || {}).map(
                ([b, n]) => (
                  <View key={b} style={st.barRow}>
                    <Text style={st.barLbl}>{b}</Text>
                    <View style={st.barTrack}>
                      <View
                        style={[
                          st.bar,
                          {
                            backgroundColor: "#8B5CF6",
                            width: `${
                              (n /
                                Math.max(
                                  1,
                                  ...Object.values<number>(
                                    data.age_distribution || {},
                                  ),
                                )) *
                              100
                            }%`,
                          },
                        ]}
                      />
                    </View>
                    <Text style={st.barVal}>{n}</Text>
                  </View>
                ),
              )}
            </View>
          </>
        )}

        {!loading && tab === "turnover" && data && (
          <>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>
                Monthly Turnover — FY {data.fy_start_year}-
                {String((data.fy_start_year || 0) + 1).slice(-2)}
              </Text>
              <RegisterTable columns={data.columns} rows={data.rows} />
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Department-wise Attrition</Text>
              <RegisterTable
                columns={[
                  { key: "department", label: "Department" },
                  { key: "employees", label: "Employees" },
                  { key: "exits", label: "Exits" },
                  { key: "attrition_pct", label: "Attrition %" },
                ]}
                rows={data.department_attrition || []}
              />
            </View>
          </>
        )}

        {!loading &&
          tab !== "dashboard" &&
          tab !== "turnover" &&
          data && (
            <View style={shared.card}>
              <Text style={shared.cardTitle}>{data.title}</Text>
              <RegisterTable
                columns={data.columns}
                rows={data.rows}
                totals={data.totals}
              />
            </View>
          )}
      </ScrollView>
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
  kpiVal: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  kpiLbl: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  insight: { fontSize: 12.5, marginBottom: 5, color: colors.onSurface },
  barRow: { flexDirection: "row", alignItems: "center", marginBottom: 5 },
  barLbl: { width: 120, fontSize: 11.5, color: colors.onSurfaceSecondary },
  barTrack: {
    flex: 1,
    height: 12,
    backgroundColor: "#EEF2F7",
    borderRadius: 6,
    overflow: "hidden",
  },
  bar: { height: 12, backgroundColor: colors.brandPrimary, borderRadius: 6 },
  barVal: {
    width: 44,
    fontSize: 11.5,
    textAlign: "right",
    color: colors.onSurface,
    fontWeight: "700",
  },
});
