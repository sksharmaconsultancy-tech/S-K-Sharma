/**
 * Past Salary Runs — Iter 91 (Utilities).
 *
 * Per user direction the "Past Actual Runs" list was removed from the
 * bottom of the Salary Process screen and lives here as a separate
 * utility. Two tabs: Actual runs and Compliance runs. Tapping a run
 * opens it on its own process screen (?run_id= deep link).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

type RunSummary = {
  run_id: string;
  month: string;
  employees_count?: number;
  finalized?: boolean;
  finalized_at?: string | null;
  finalized_by_name?: string | null;
  attendance_source?: string;
  generated_at?: string;
  generated_by_name?: string | null;
  generated_by_role?: string | null;
  totals?: Record<string, number>;
};

const fmtInr = (n?: number | null) =>
  n === undefined || n === null ? "—" : `₹${Math.round(n).toLocaleString("en-IN")}`;

const fmtDT = (iso?: string | null) => {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const p = (x: number) => String(x).padStart(2, "0");
    return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
  } catch { return iso; }
};

export default function PastSalaryRunsScreen() {
  const { user } = useAuth();
  const isAdmin = ["company_admin", "super_admin", "sub_admin"].includes(user?.role || "");
  const [tab, setTab] = useState<"actual" | "compliance">("actual");
  const [loading, setLoading] = useState(false);
  const [actualRuns, setActualRuns] = useState<RunSummary[]>([]);
  const [compRuns, setCompRuns] = useState<RunSummary[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, c] = await Promise.all([
        api<{ runs: RunSummary[] }>("/admin/salary-runs").catch(() => ({ runs: [] })),
        api<{ runs: RunSummary[] }>("/admin/compliance-salary-runs").catch(() => ({ runs: [] })),
      ]);
      setActualRuns(a.runs || []);
      setCompRuns(c.runs || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { if (isAdmin) load(); }, [isAdmin, load]);

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.dimTxt}>Admins only</Text>
        </View>
      </View>
    );
  }

  const runs = tab === "actual" ? actualRuns : compRuns;

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>Past Salary Runs</Text>
            <Text style={styles.hsub}>Utilities · Open, review or reprocess earlier runs</Text>
          </View>
          <Pressable onPress={load} hitSlop={8}>
            <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
          </Pressable>
        </View>
      </SafeAreaView>

      <View style={styles.tabs}>
        {(["actual", "compliance"] as const).map((t) => (
          <Pressable
            key={t}
            onPress={() => setTab(t)}
            style={[styles.tabBtn, tab === t && styles.tabBtnOn]}
            testID={`psr-tab-${t}`}
          >
            <Text style={[styles.tabTxt, tab === t && styles.tabTxtOn]}>
              {t === "actual" ? "Actual Salary Runs" : "Compliance Salary Runs"}
            </Text>
          </Pressable>
        ))}
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        {loading ? (
          <ActivityIndicator style={{ margin: 40 }} color={colors.brandPrimary} />
        ) : runs.length === 0 ? (
          <View style={styles.center}>
            <Ionicons name="albums-outline" size={36} color={colors.onSurfaceTertiary} />
            <Text style={styles.dimTxt}>No {tab} runs yet.</Text>
          </View>
        ) : (
          <View style={styles.card}>
            {runs.map((r) => (
              <Pressable
                key={r.run_id}
                testID={`psr-run-${r.run_id}`}
                onPress={() =>
                  router.push(
                    tab === "actual"
                      ? `/salary-run?run_id=${encodeURIComponent(r.run_id)}`
                      : `/compliance-salary-run?run_id=${encodeURIComponent(r.run_id)}`,
                  )
                }
                style={styles.row}
              >
                <View style={styles.rowIcon}>
                  <Ionicons
                    name={tab === "actual" ? "cash-outline" : "briefcase-outline"}
                    size={18}
                    color={colors.brandPrimary}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>
                    {r.month}  ·  {r.employees_count ?? "—"} employees
                    {r.finalized ? "  ·  Finalized 🔒" : "  ·  Draft"}
                  </Text>
                  <Text style={styles.rowMeta}>
                    Net {fmtInr(r.totals?.net_pay ?? (r.totals as any)?.net)}
                    {r.attendance_source ? `  ·  ${r.attendance_source === "biometric" ? "Biometric" : "Manual"}` : ""}
                  </Text>
                  {(r.generated_at || r.generated_by_name) ? (
                    <Text style={styles.rowMeta}>
                      {fmtDT(r.generated_at)}
                      {r.generated_by_name ? ` · ${r.generated_by_name}` : ""}
                      {r.generated_by_role ? ` (${r.generated_by_role})` : ""}
                    </Text>
                  ) : null}
                </View>
                <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
              </Pressable>
            ))}
          </View>
        )}
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: spacing.md, paddingVertical: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  h1: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  hsub: { fontSize: 11, color: colors.onSurfaceTertiary },
  tabs: {
    flexDirection: "row", gap: 8,
    paddingHorizontal: spacing.md, paddingVertical: 10,
  },
  tabBtn: {
    paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  tabBtnOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtOn: { color: "#fff" },
  scroll: { padding: spacing.md, ...(Platform.OS === "web" ? { maxWidth: 1100, width: "100%", alignSelf: "center" } : {}) },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
    overflow: "hidden",
  },
  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 14, paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  rowIcon: {
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: "#EEF2FF",
    alignItems: "center", justifyContent: "center",
  },
  rowTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  rowMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 1 },
  center: { alignItems: "center", gap: 8, padding: 40 },
  dimTxt: { color: colors.onSurfaceTertiary, fontSize: 13 },
});
