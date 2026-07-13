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
              <ScrollView horizontal>
                <View>
                  <View style={[styles.tr, styles.trHead]}>
                    {monthly.columns.map((c) => (
                      <Text
                        key={c.key}
                        style={[styles.th, { width: c.key === "name" ? 180 : c.key === "sr" ? 44 : 110 },
                          c.key === "name" && { textAlign: "left" }]}
                      >
                        {c.label}
                      </Text>
                    ))}
                  </View>
                  {monthly.rows.map((r, i) => (
                    <View key={r.user_id || i} style={[styles.tr, i % 2 === 1 && styles.trOdd]}>
                      {monthly.columns.map((c) => (
                        <Text
                          key={c.key}
                          style={[styles.td, { width: c.key === "name" ? 180 : c.key === "sr" ? 44 : 110 },
                            c.key === "name" && { textAlign: "left", fontWeight: "700" },
                            c.key === "total" && { fontWeight: "800" }]}
                          numberOfLines={1}
                        >
                          {c.key === "name" || c.key === "sr" || c.key === "uan_no" || c.key === "esi_ip_no"
                            ? (r[c.key] || "—")
                            : numFmt(r[c.key])}
                        </Text>
                      ))}
                    </View>
                  ))}
                  <View style={[styles.tr, styles.trTotal]}>
                    {monthly.columns.map((c, ci) => (
                      <Text
                        key={c.key}
                        style={[styles.td, styles.tdTotal, { width: c.key === "name" ? 180 : c.key === "sr" ? 44 : 110 }]}
                      >
                        {ci === 1 ? "TOTAL" : monthly.totals[c.key] != null ? numFmt(monthly.totals[c.key]) : ""}
                      </Text>
                    ))}
                  </View>
                </View>
              </ScrollView>
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
            <ScrollView horizontal>
              <View>
                <View style={[styles.tr, styles.trHead]}>
                  <Text style={[styles.th, { width: 44 }]}>Sr.</Text>
                  <Text style={[styles.th, { width: 70 }]}>Code</Text>
                  <Text style={[styles.th, { width: 170, textAlign: "left" }]}>Name</Text>
                  <Text style={[styles.th, { width: 110 }]}>{kind === "pf" ? "UAN No." : "ESIC IP No."}</Text>
                  {yearly.months.map((m) => (
                    <Text key={m.key} style={[styles.th, { width: 80 }]}>{m.label}</Text>
                  ))}
                  <Text style={[styles.th, { width: 100 }]}>Wages Total</Text>
                  <Text style={[styles.th, { width: 100 }]}>EE Total</Text>
                  <Text style={[styles.th, { width: 100 }]}>ER Total</Text>
                  <Text style={[styles.th, { width: 110 }]}>Grand Total</Text>
                </View>
                {yearly.rows.map((r, i) => (
                  <View key={r.user_id || i} style={[styles.tr, i % 2 === 1 && styles.trOdd]}>
                    <Text style={[styles.td, { width: 44 }]}>{r.sr}</Text>
                    <Text style={[styles.td, { width: 70 }]}>{r.employee_code || "—"}</Text>
                    <Text style={[styles.td, { width: 170, textAlign: "left", fontWeight: "700" }]} numberOfLines={1}>
                      {r.name}
                    </Text>
                    <Text style={[styles.td, { width: 110 }]}>
                      {(kind === "pf" ? r.uan_no : r.esi_ip_no) || "—"}
                    </Text>
                    {yearly.months.map((m) => (
                      <Text key={m.key} style={[styles.td, { width: 80 }]}>
                        {numFmt(r.monthly?.[m.key] || 0)}
                      </Text>
                    ))}
                    <Text style={[styles.td, { width: 100 }]}>{numFmt(r.wages_total)}</Text>
                    <Text style={[styles.td, { width: 100 }]}>{numFmt(r.ee_total)}</Text>
                    <Text style={[styles.td, { width: 100 }]}>{numFmt(r.er_total)}</Text>
                    <Text style={[styles.td, { width: 110, fontWeight: "800" }]}>{numFmt(r.grand_total)}</Text>
                  </View>
                ))}
                <View style={[styles.tr, styles.trTotal]}>
                  <Text style={[styles.td, styles.tdTotal, { width: 44 }]} />
                  <Text style={[styles.td, styles.tdTotal, { width: 70 }]} />
                  <Text style={[styles.td, styles.tdTotal, { width: 170, textAlign: "left" }]}>TOTAL</Text>
                  <Text style={[styles.td, styles.tdTotal, { width: 110 }]} />
                  {yearly.months.map((m) => (
                    <Text key={m.key} style={[styles.td, styles.tdTotal, { width: 80 }]}>
                      {numFmt(yearly.totals.monthly?.[m.key] || 0)}
                    </Text>
                  ))}
                  <Text style={[styles.td, styles.tdTotal, { width: 100 }]}>{numFmt(yearly.totals.wages_total)}</Text>
                  <Text style={[styles.td, styles.tdTotal, { width: 100 }]}>{numFmt(yearly.totals.ee_total)}</Text>
                  <Text style={[styles.td, styles.tdTotal, { width: 100 }]}>{numFmt(yearly.totals.er_total)}</Text>
                  <Text style={[styles.td, styles.tdTotal, { width: 110 }]}>{numFmt(yearly.totals.grand_total)}</Text>
                </View>
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
