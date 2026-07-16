/**
 * Iter 98 — Leave Report (Reports section).
 * Per employee, per year: CL/PL allowed (Firm Master → Leave Policy),
 * taken (approved leaves) and balance. Sorted by employee code.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };

type LeaveRow = {
  user_id: string;
  employee_code?: string | null;
  name?: string;
  designation?: string | null;
  cl_allowed: number;
  cl_taken: number;
  cl_balance: number;
  pl_allowed: number;
  pl_taken: number;
  pl_balance: number;
  other_taken: number;
  total_taken: number;
};

type Report = {
  company_id: string;
  year: number;
  cl_pl_applicable: boolean;
  cl_allowed: number;
  pl_allowed: number;
  rows: LeaveRow[];
  employees_count: number;
};

const THIS_YEAR = new Date().getFullYear();
const YEARS = [THIS_YEAR, THIS_YEAR - 1, THIS_YEAR - 2];

export default function LeaveReportScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState<string>("");
  const [year, setYear] = useState<number>(THIS_YEAR);
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!user) return;
    (async () => {
      try {
        if (user.role !== "super_admin") {
          setCompanyId(user.company_id || "");
        } else {
          const r = await api<{ companies: Company[] }>("/companies");
          setCompanies(r.companies || []);
          if ((r.companies || []).length === 1) setCompanyId(r.companies[0].company_id);
        }
      } catch {
        setCompanies([]);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.role]);

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      const r = await api<Report>(`/admin/leave-report?company_id=${companyId}&year=${year}`);
      setReport(r);
    } catch {
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, year]);

  useEffect(() => { load(); }, [load]);

  const downloadCsv = () => {
    if (!report || Platform.OS !== "web" || typeof document === "undefined") return;
    const head = [
      "Code", "Name", "Designation",
      "CL Allowed", "CL Taken", "CL Balance",
      "PL Allowed", "PL Taken", "PL Balance",
      "Other Taken", "Total Taken",
    ];
    const lines = [head.join(",")];
    for (const r of report.rows) {
      lines.push([
        r.employee_code ?? "", `"${(r.name || "").replace(/"/g, '""')}"`,
        `"${(r.designation || "").replace(/"/g, '""')}"`,
        r.cl_allowed, r.cl_taken, r.cl_balance,
        r.pl_allowed, r.pl_taken, r.pl_balance,
        r.other_taken, r.total_taken,
      ].join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `LeaveReport_${year}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const firmName = useMemo(
    () => companies.find((c) => c.company_id === companyId)?.name || "",
    [companies, companyId],
  );

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role)) {
    return <Redirect href="/" />;
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="lr-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Leave Report</Text>
        <Pressable
          onPress={() => router.push("/leave-balance-config")}
          hitSlop={10}
          testID="lr-config"
          style={{ marginRight: 14 }}
        >
          <Ionicons name="options-outline" size={20} color={colors.brandPrimary} />
        </Pressable>
        <Pressable onPress={downloadCsv} hitSlop={10} testID="lr-csv">
          <Ionicons name="download-outline" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.body}>
        {/* Firm + Year selectors */}
        {user.role === "super_admin" ? (
          <View style={styles.chipWrap}>
            {companies.map((c) => (
              <Pressable
                key={c.company_id}
                onPress={() => setCompanyId(c.company_id)}
                style={[styles.chip, companyId === c.company_id && styles.chipActive]}
                testID={`lr-firm-${c.company_id}`}
              >
                <Text style={[styles.chipTxt, companyId === c.company_id && styles.chipTxtActive]}>
                  {c.name}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}
        <View style={styles.chipWrap}>
          {YEARS.map((y) => (
            <Pressable
              key={y}
              onPress={() => setYear(y)}
              style={[styles.chip, year === y && styles.chipActive]}
              testID={`lr-year-${y}`}
            >
              <Text style={[styles.chipTxt, year === y && styles.chipTxtActive]}>{y}</Text>
            </Pressable>
          ))}
        </View>

        {!companyId ? (
          <Text style={styles.hint}>Select a firm to view the leave report.</Text>
        ) : loading ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 30 }} />
        ) : !report ? (
          <Text style={styles.hint}>Could not load the report.</Text>
        ) : (
          <>
            <View style={styles.summaryCard}>
              <Text style={styles.summaryTitle}>
                {firmName || report.company_id} · {report.year}
              </Text>
              <Text style={styles.summaryLine}>
                CL/PL Applicable: {report.cl_pl_applicable ? "YES" : "NO"} ·
                {" "}Allowed / year — CL: {report.cl_allowed} · PL: {report.pl_allowed} ·
                {" "}Employees: {report.employees_count}
              </Text>
              {!report.cl_pl_applicable ? (
                <Text style={styles.warnLine}>
                  ⚠ CL/PL is not enabled for this firm — set limits in Firm Master → CL / PL Policy.
                </Text>
              ) : null}
            </View>

            <ScrollView horizontal>
              <View>
                <View style={[styles.tr, styles.trHead]}>
                  <Text style={[styles.th, { width: 60 }]}>Code</Text>
                  <Text style={[styles.th, { width: 180, textAlign: "left" }]}>Name</Text>
                  <Text style={[styles.th, { width: 80 }]}>CL Allow</Text>
                  <Text style={[styles.th, { width: 80 }]}>CL Taken</Text>
                  <Text style={[styles.th, { width: 80 }]}>CL Bal</Text>
                  <Text style={[styles.th, { width: 80 }]}>PL Allow</Text>
                  <Text style={[styles.th, { width: 80 }]}>PL Taken</Text>
                  <Text style={[styles.th, { width: 80 }]}>PL Bal</Text>
                  <Text style={[styles.th, { width: 80 }]}>Other</Text>
                  <Text style={[styles.th, { width: 80 }]}>Total</Text>
                </View>
                {report.rows.map((r, i) => (
                  <View key={r.user_id} style={[styles.tr, i % 2 === 1 && styles.trOdd]}>
                    <Text style={[styles.td, { width: 60 }]}>{r.employee_code || "—"}</Text>
                    <Text style={[styles.td, { width: 180, textAlign: "left", fontWeight: "700" }]} numberOfLines={1}>
                      {r.name}
                    </Text>
                    <Text style={[styles.td, { width: 80 }]}>{r.cl_allowed}</Text>
                    <Text style={[styles.td, { width: 80 }]}>{r.cl_taken}</Text>
                    <Text style={[styles.td, { width: 80, fontWeight: "700", color: r.cl_balance > 0 ? "#166534" : colors.onSurface }]}>{r.cl_balance}</Text>
                    <Text style={[styles.td, { width: 80 }]}>{r.pl_allowed}</Text>
                    <Text style={[styles.td, { width: 80 }]}>{r.pl_taken}</Text>
                    <Text style={[styles.td, { width: 80, fontWeight: "700", color: r.pl_balance > 0 ? "#166534" : colors.onSurface }]}>{r.pl_balance}</Text>
                    <Text style={[styles.td, { width: 80 }]}>{r.other_taken}</Text>
                    <Text style={[styles.td, { width: 80, fontWeight: "800" }]}>{r.total_taken}</Text>
                  </View>
                ))}
              </View>
            </ScrollView>
          </>
        )}
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surfaceSecondary },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  headerTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800" },
  body: { padding: spacing.md },
  hint: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginVertical: 20, textAlign: "center" },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: spacing.sm },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { color: colors.onSurface, fontSize: 12, fontWeight: "600" },
  chipTxtActive: { color: "#fff" },
  summaryCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  summaryTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800" },
  summaryLine: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 4 },
  warnLine: { color: "#B45309", fontSize: 12, marginTop: 6, fontWeight: "600" },
  tr: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  trHead: { backgroundColor: colors.brandTertiary },
  trOdd: { backgroundColor: colors.surfaceSecondary },
  th: { paddingVertical: 9, paddingHorizontal: 6, fontSize: 11, fontWeight: "800", color: colors.brandPrimary, textAlign: "center" },
  td: { paddingVertical: 8, paddingHorizontal: 6, fontSize: 12, color: colors.onSurface, textAlign: "center" },
});
