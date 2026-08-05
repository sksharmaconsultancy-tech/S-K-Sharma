/**
 * P.F. / E.S.I. Contribution Sheets (Reports).
 *  • Month-wise per-employee contribution sheet
 *  • Employee-wise yearly report (FY Apr–Mar matrix)
 * Data comes from the LATEST compliance salary run of each month.
 * Open as /contribution-sheets?kind=pf or ?kind=esi
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
import { Redirect, useRouter, useLocalSearchParams } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import ReportTable, { ReportCol } from "@/src/components/ReportTable";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import MonthPicker from "@/src/components/MonthPicker";
import { colors, radius, spacing, type } from "@/src/theme";

type Col = { key: string; label: string };
type MonthlyData = {
  kind: string; month: string; run_found: boolean;
  columns: Col[]; rows: any[]; totals: Record<string, number>;
  employees_count: number;
};
type YearlyData = {
  kind: string; fy_label: string;
  months: { key: string; label: string }[];
  months_covered: string[];
  rows: any[];
  totals: { wages_total: number; ee_total: number; er_total: number; grand_total: number; monthly: Record<string, number> };
  employees_count: number;
};

function fyOptions(): { start: number; label: string }[] {
  const now = new Date();
  const y = now.getFullYear();
  const currentStart = now.getMonth() >= 3 ? y : y - 1;
  const out: { start: number; label: string }[] = [];
  for (let i = 0; i <= 3; i++) {
    const s = currentStart - i;
    out.push({ start: s, label: `FY ${s}-${String(s + 1).slice(-2)}` });
  }
  return out;
}

function thisMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

async function downloadXlsx(path: string, filename: string) {
  try {
    const res = await apiBinary(path);
    if (Platform.OS === "web" && res.webBlobUrl) {
      const a = document.createElement("a");
      a.href = res.webBlobUrl;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
    }
  } catch (e: any) {
    if (Platform.OS === "web") globalThis.alert(e?.message || "Download failed");
  }
}

export default function ContributionSheetsScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ kind?: string }>();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId, selectedCompany } = useSelectedCompany();

  const [kind, setKind] = useState<"pf" | "esi">(
    (params.kind || "pf").toString().toLowerCase() === "esi" ? "esi" : "pf",
  );
  useEffect(() => {
    const k = (params.kind || "").toString().toLowerCase();
    if (k === "pf" || k === "esi") setKind(k);
  }, [params.kind]);

  const [mode, setMode] = useState<"monthly" | "yearly">("monthly");
  const [month, setMonth] = useState<string>(thisMonth());
  const fys = useMemo(() => fyOptions(), []);
  const [fyStart, setFyStart] = useState<number>(fys[0].start);

  const [monthly, setMonthly] = useState<MonthlyData | null>(null);
  const [yearly, setYearly] = useState<YearlyData | null>(null);
  const [loading, setLoading] = useState(false);

  const companyId = user?.role === "company_admin" ? user.company_id : selectedCompanyId;

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      if (mode === "monthly") {
        const r = await api<MonthlyData>(
          `/admin/reports/contribution?kind=${kind}&company_id=${companyId}&month=${month}`,
        );
        setMonthly(r);
      } else {
        const r = await api<YearlyData>(
          `/admin/reports/contribution-yearly?kind=${kind}&company_id=${companyId}&fy_start_year=${fyStart}`,
        );
        setYearly(r);
      }
    } catch {
      if (mode === "monthly") setMonthly(null);
      else setYearly(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, kind, mode, month, fyStart]);

  useEffect(() => { void load(); }, [load]);

  const label = kind === "pf" ? "P.F. Contribution Sheet" : "E.S.I. Contribution Sheet";

  const doDownload = () => {
    if (!companyId) return;
    if (mode === "monthly") {
      void downloadXlsx(
        `/admin/reports/contribution.xlsx?kind=${kind}&company_id=${companyId}&month=${month}`,
        `${kind.toUpperCase()}_Contribution_${month}.xlsx`,
      );
    } else {
      void downloadXlsx(
        `/admin/reports/contribution-yearly.xlsx?kind=${kind}&company_id=${companyId}&fy_start_year=${fyStart}`,
        `${kind.toUpperCase()}_Contribution_Yearly_${fyStart}.xlsx`,
      );
    }
  };

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role)) {
    return <Redirect href="/" />;
  }

  const numFmt = (v: any) =>
    typeof v === "number" ? v.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : (v ?? "—");

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="cs-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>{label}</Text>
        <Pressable onPress={doDownload} hitSlop={10} testID="cs-xlsx">
          <Ionicons name="download-outline" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.body}>
        {/* PF / ESI toggle */}
        <View style={styles.chipWrap}>
          {(["pf", "esi"] as const).map((k) => (
            <Pressable
              key={k}
              onPress={() => setKind(k)}
              style={[styles.chip, kind === k && styles.chipActive]}
              testID={`cs-kind-${k}`}
            >
              <Text style={[styles.chipTxt, kind === k && styles.chipTxtActive]}>
                {k === "pf" ? "P.F." : "E.S.I."}
              </Text>
            </Pressable>
          ))}
          <View style={{ width: 12 }} />
          {(["monthly", "yearly"] as const).map((m) => (
            <Pressable
              key={m}
              onPress={() => setMode(m)}
              style={[styles.chip, mode === m && styles.chipActive]}
              testID={`cs-mode-${m}`}
            >
              <Text style={[styles.chipTxt, mode === m && styles.chipTxtActive]}>
                {m === "monthly" ? "Month-wise" : "Employee-wise Yearly"}
              </Text>
            </Pressable>
          ))}
        </View>

        {mode === "monthly" ? (
          <View style={{ marginBottom: spacing.sm, maxWidth: 340 }}>
            <MonthPicker value={month} onChange={setMonth} />
          </View>
        ) : (
          <View style={styles.chipWrap}>
            {fys.map((f) => (
              <Pressable
                key={f.start}
                onPress={() => setFyStart(f.start)}
                style={[styles.chip, fyStart === f.start && styles.chipActive]}
                testID={`cs-fy-${f.start}`}
              >
                <Text style={[styles.chipTxt, fyStart === f.start && styles.chipTxtActive]}>{f.label}</Text>
              </Pressable>
            ))}
          </View>
        )}

        {!companyId ? (
          <Text style={styles.hint}>Select a firm from the top bar to view this report.</Text>
        ) : loading ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 30 }} />
        ) : mode === "monthly" ? (
          !monthly ? (
            <Text style={styles.hint}>Could not load the report.</Text>
          ) : !monthly.run_found ? (
            <Text style={styles.hint}>
              No Compliance Salary run found for {month}. Generate one in Compliance Salary Process first.
            </Text>
          ) : (
            <>
              <View style={styles.summaryCard}>
                <Text style={styles.summaryTitle}>
                  {selectedCompany?.name || companyId} · {month}
                </Text>
                <Text style={styles.summaryLine}>
                  Employees: {monthly.employees_count} · Total Contribution: ₹
                  {numFmt(monthly.totals.total)}
                </Text>
              </View>
              {/* Iter 497 — Universal Report Table engine (monthly) */}
              <ReportTable
                reportKey={`contrib_${kind}_monthly`}
                columns={monthly.columns.map((c): ReportCol<any> => ({
                  key: c.key,
                  label: c.label,
                  type: c.key === "name" ? "text"
                    : c.key === "sr" ? "center"
                    : (c.key === "uan_no" || c.key === "esi_ip_no") ? "center" : "num",
                  ...(c.key === "name" ? { min: 200, max: 300, sticky: true }
                    : c.key === "sr" ? { min: 44, max: 60, sticky: true }
                    : { min: 100, max: 150 }),
                  value: (r) =>
                    c.key === "name" || c.key === "sr" || c.key === "uan_no" || c.key === "esi_ip_no"
                      ? String(r[c.key] || "—")
                      : numFmt(r[c.key]),
                  textStyle: c.key === "name"
                    ? () => ({ fontWeight: "700" })
                    : c.key === "total" ? () => ({ fontWeight: "800" }) : undefined,
                }))}
                rows={monthly.rows}
                maxHeight={560}
                pdfTitle={`${kind === "pf" ? "PF" : "ESIC"} Contribution Sheet — ${month}`}
                pdfSubtitle={selectedCompany?.name || ""}
                footer={{
                  label: "TOTAL",
                  values: {
                    sr: " ",
                    ...Object.fromEntries(
                      monthly.columns
                        .filter((c) => monthly.totals[c.key] != null)
                        .map((c) => [c.key, numFmt(monthly.totals[c.key])]),
                    ),
                  },
                }}
              />
            </>
          )
        ) : !yearly ? (
          <Text style={styles.hint}>Could not load the report.</Text>
        ) : yearly.rows.length === 0 ? (
          <Text style={styles.hint}>
            No Compliance Salary runs found in {yearly.fy_label}. Generate monthly runs first.
          </Text>
        ) : (
          <>
            <View style={styles.summaryCard}>
              <Text style={styles.summaryTitle}>
                {selectedCompany?.name || companyId} · {yearly.fy_label}
              </Text>
              <Text style={styles.summaryLine}>
                Employees: {yearly.employees_count} · Months covered: {yearly.months_covered.length} ·
                {" "}Grand Total: ₹{numFmt(yearly.totals.grand_total)}
              </Text>
            </View>
            {/* Iter 497 — Universal Report Table engine (yearly) */}
            <ReportTable
              reportKey={`contrib_${kind}_yearly`}
              columns={[
                { key: "sr", label: "Sr.", type: "center", min: 44, max: 60, sticky: true },
                { key: "employee_code", label: "Code", type: "center", min: 64, sticky: true },
                { key: "name", label: "Name", min: 200, max: 300, sticky: true, textStyle: () => ({ fontWeight: "700" }) },
                {
                  key: "__id", label: kind === "pf" ? "UAN No." : "ESIC IP No.", type: "center", min: 110,
                  value: (r: any) => String((kind === "pf" ? r.uan_no : r.esi_ip_no) || "—"),
                },
                ...yearly.months.map((m): ReportCol<any> => ({
                  key: `m_${m.key}`, label: m.label, type: "num", min: 80, max: 120,
                  value: (r: any) => numFmt(r.monthly?.[m.key] || 0),
                })),
                { key: "wages_total", label: "Wages Total", type: "num", min: 100, value: (r: any) => numFmt(r.wages_total) },
                { key: "ee_total", label: "EE Total", type: "num", min: 96, value: (r: any) => numFmt(r.ee_total) },
                { key: "er_total", label: "ER Total", type: "num", min: 96, value: (r: any) => numFmt(r.er_total) },
                { key: "grand_total", label: "Grand Total", type: "num", min: 110, value: (r: any) => numFmt(r.grand_total), textStyle: () => ({ fontWeight: "800" }) },
              ]}
              rows={yearly.rows}
              maxHeight={560}
              pdfTitle={`${kind === "pf" ? "PF" : "ESIC"} Yearly Contribution — ${yearly.fy_label}`}
              pdfSubtitle={selectedCompany?.name || ""}
              footer={{
                label: "TOTAL",
                values: {
                  sr: " ", employee_code: " ",
                  ...Object.fromEntries(yearly.months.map((m) => [
                    `m_${m.key}`, numFmt(yearly.totals.monthly?.[m.key] || 0),
                  ])),
                  wages_total: numFmt(yearly.totals.wages_total),
                  ee_total: numFmt(yearly.totals.ee_total),
                  er_total: numFmt(yearly.totals.er_total),
                  grand_total: numFmt(yearly.totals.grand_total),
                },
              }}
            />
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
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: spacing.sm, alignItems: "center" },
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
  tr: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  trHead: { backgroundColor: colors.brandTertiary },
  trOdd: { backgroundColor: colors.surfaceSecondary },
  trTotal: { backgroundColor: "#FEF9C3" },
  th: { paddingVertical: 9, paddingHorizontal: 6, fontSize: 11, fontWeight: "800", color: colors.brandPrimary, textAlign: "center" },
  td: { paddingVertical: 8, paddingHorizontal: 6, fontSize: 12, color: colors.onSurface, textAlign: "center" },
  tdTotal: { fontWeight: "800" },
});
