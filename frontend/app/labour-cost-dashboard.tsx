/**
 * Iter 527 (user-approved improvement) — Daily Labour Cost Dashboard.
 *
 * One glance: today's total labour cost, employees present, hours & OT,
 * department-wise cost split and the month-to-date daily cost trend.
 * Costs use the same engine as the Shift Deployment / OT Register reports.
 */
import React, { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Platform,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";
import DateField from "@/src/components/DateField";

type Dept = { department: string; employees: number; hours: number; ot: number; cost: number };
type Dash = {
  firm: string;
  day: string;
  total_cost: number;
  employees_present: number;
  total_hours: number;
  ot_hours: number;
  departments: Dept[];
  trend: { date: string; cost: number }[];
  mtd_cost: number;
};

const inr = (n: number) =>
  `₹${(n ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function LabourCostDashboard() {
  const router = useRouter();
  const { user } = useAuth();
  const { companies, selectedCompanyId } = useSelectedCompany();
  const isAdmin =
    user?.role === "super_admin" || user?.role === "sub_admin" || user?.role === "company_admin";

  const [day, setDay] = useState<string>(todayIso());
  const [firmId, setFirmId] = useState<string>(
    selectedCompanyId || user?.company_id || "");
  const [data, setData] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const fetchDash = async (f = firmId, d = day) => {
    if (!f) {
      setErr("Pick a firm first.");
      return;
    }
    setLoading(true);
    setErr("");
    try {
      const r = await api<Dash>(
        `/admin/labour-cost/dashboard?company_id=${encodeURIComponent(f)}&day=${d}`);
      setData(r);
    } catch (e: any) {
      setErr(e?.message || "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDash(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const firstRun = useRef(true);
  useEffect(() => {
    if (firstRun.current) { firstRun.current = false; return; }
    fetchDash(firmId, day);
  }, [firmId, day]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!isAdmin) {
    return (
      <SafeAreaView style={st.safe} edges={["top"]}>
        <Text style={st.sub}>Admin access only.</Text>
      </SafeAreaView>
    );
  }

  const maxTrend = Math.max(1, ...(data?.trend || []).map((t) => t.cost));
  const maxDept = Math.max(1, ...(data?.departments || []).map((x) => x.cost));

  const CARDS = data ? [
    { lbl: "Total Cost (day)", val: inr(data.total_cost), icon: "cash-outline", c: "#15803D", bg: "#F0FDF4" },
    { lbl: "Employees Present", val: String(data.employees_present), icon: "people-outline", c: "#1D4ED8", bg: "#EFF6FF" },
    { lbl: "Total Hours", val: data.total_hours.toLocaleString("en-IN"), icon: "time-outline", c: "#334155", bg: "#F8FAFC" },
    { lbl: "OT Hours", val: data.ot_hours.toLocaleString("en-IN"), icon: "flash-outline", c: "#B45309", bg: "#FFFBEB" },
    { lbl: "Month-to-Date Cost", val: inr(data.mtd_cost), icon: "trending-up-outline", c: "#7C3AED", bg: "#F5F3FF" },
  ] : [];

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} style={st.backBtn} testID="lcd-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.title}>Daily Labour Cost Dashboard</Text>
          <Text style={st.sub}>Cost as per Firm Master + Employee Policy (same engine as reports)</Text>
        </View>
      </View>

      <View style={st.filterRow}>
        <View style={{ width: 150 }}>
          <Text style={st.lbl}>Date</Text>
          <DateField value={day} onChangeISO={setDay} testID="lcd-day" />
        </View>
        {user?.role !== "company_admin" ? (
          <View style={{ minWidth: 220 }}>
            <Text style={st.lbl}>Firm</Text>
            {Platform.OS === "web" ? (
              <select
                value={firmId}
                onChange={(e) => setFirmId((e.target as HTMLSelectElement).value)}
                style={st.select as any}
                data-testid="lcd-firm"
              >
                <option value="">— pick firm —</option>
                {companies.map((c: any) => (
                  <option key={c.company_id} value={c.company_id}>{c.name}</option>
                ))}
              </select>
            ) : null}
          </View>
        ) : null}
        <Pressable onPress={() => fetchDash()} style={st.applyBtn} testID="lcd-refresh">
          <Ionicons name="refresh-outline" size={15} color="#fff" />
          <Text style={st.applyTxt}>Refresh</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}>
        {loading ? (
          <ActivityIndicator size="large" color={colors.brand} style={{ marginTop: 40 }} />
        ) : err ? (
          <Text style={[st.sub, { textAlign: "center", marginTop: 30 }]}>{err}</Text>
        ) : data ? (
          <>
            <View style={st.grid}>
              {CARDS.map((c) => (
                <View key={c.lbl} style={[st.card, { backgroundColor: c.bg }]}>
                  <Ionicons name={c.icon as any} size={20} color={c.c} />
                  <Text style={[st.cardNum, { color: c.c }]} numberOfLines={1}>{c.val}</Text>
                  <Text style={st.cardLbl}>{c.lbl}</Text>
                </View>
              ))}
            </View>

            {/* Month-to-date trend */}
            <View style={st.panel}>
              <Text style={st.panelTitle}>
                Month-to-Date Daily Cost — {data.day.slice(0, 7)}
              </Text>
              <View style={st.trendRow}>
                {data.trend.map((t) => {
                  const h = Math.max(2, Math.round((t.cost / maxTrend) * 110));
                  const isSel = t.date === data.day;
                  return (
                    <View key={t.date} style={st.trendCol}>
                      <View style={[st.trendBar, {
                        height: h,
                        backgroundColor: isSel ? "#7C3AED" : t.cost > 0 ? "#22C55E" : "#E2E8F0",
                      }]} />
                      <Text style={st.trendLbl}>{t.date.slice(8)}</Text>
                    </View>
                  );
                })}
              </View>
              <Text style={st.trendHint}>
                Peak day: {inr(maxTrend)} · bar = total labour cost of that day
              </Text>
            </View>

            {/* Department split */}
            <View style={st.panel}>
              <Text style={st.panelTitle}>Department-wise Cost — {data.day}</Text>
              {data.departments.length === 0 ? (
                <Text style={st.sub}>No punches on this day.</Text>
              ) : data.departments.map((x) => (
                <View key={x.department} style={st.deptRow}>
                  <View style={{ flex: 1 }}>
                    <View style={st.deptTop}>
                      <Text style={st.deptName} numberOfLines={1}>{x.department}</Text>
                      <Text style={st.deptCost}>{inr(x.cost)}</Text>
                    </View>
                    <View style={st.deptTrack}>
                      <View style={[st.deptFill,
                        { width: `${Math.max(2, (x.cost / maxDept) * 100)}%` as any }]} />
                    </View>
                    <Text style={st.deptMeta}>
                      {x.employees} employee{x.employees === 1 ? "" : "s"} · {x.hours} hrs · OT {x.ot} hrs
                    </Text>
                  </View>
                </View>
              ))}
            </View>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  backBtn: { padding: 6 },
  title: { fontSize: type.lg, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: type.xs, color: colors.onSurfaceSecondary },
  filterRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    flexWrap: "wrap",
    gap: spacing.sm,
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  lbl: { fontSize: type.xs, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  select: {
    height: 38,
    borderRadius: 8,
    border: `1px solid ${colors.border}`,
    paddingHorizontal: 8,
    backgroundColor: colors.surface,
    color: colors.onSurface,
    fontSize: 13,
  },
  applyBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brand,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    height: 38,
  },
  applyTxt: { color: "#fff", fontWeight: "800", fontSize: type.sm },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  card: {
    minWidth: 160,
    flexGrow: 1,
    flexBasis: "18%",
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 4,
  },
  cardNum: { fontSize: 20, fontWeight: "900" },
  cardLbl: { fontSize: type.xs, fontWeight: "700", color: colors.onSurfaceSecondary },
  panel: {
    marginTop: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  panelTitle: { fontSize: type.sm, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  trendRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 3,
    height: 130,
  },
  trendCol: { flex: 1, alignItems: "center", justifyContent: "flex-end" },
  trendBar: { width: "80%", borderRadius: 3 },
  trendLbl: { fontSize: 8, color: colors.onSurfaceTertiary, marginTop: 2 },
  trendHint: { fontSize: type.xs, color: colors.onSurfaceSecondary, marginTop: 8 },
  deptRow: { marginBottom: 12 },
  deptTop: { flexDirection: "row", justifyContent: "space-between", marginBottom: 3 },
  deptName: { fontSize: type.sm, fontWeight: "700", color: colors.onSurface, flex: 1 },
  deptCost: { fontSize: type.sm, fontWeight: "900", color: "#15803D" },
  deptTrack: { height: 8, borderRadius: 999, backgroundColor: "#E2E8F0", overflow: "hidden" },
  deptFill: { height: "100%", backgroundColor: "#22C55E", borderRadius: 999 },
  deptMeta: { fontSize: type.xs, color: colors.onSurfaceSecondary, marginTop: 3 },
});
