/**
 * Bonus Yearly Summary (Bonus sidebar sub-point).
 * Employee-wise, month-wise summary across the FY (Apr–Mar):
 *   Employee Name, Father Name, Date of Join, Working Days per month,
 *   Earned per month, earning-allowance heads enabled in Firm Master,
 *   Total Working Days + Total Earned.
 * Data source: latest compliance salary run of each month.
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

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Summary = {
  fy_label: string;
  company_name?: string;
  months: { key: string; label: string }[];
  months_covered: string[];
  heads: { key: string; label: string }[];
  rows: any[];
  totals: any;
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

function isoToDDMM(v?: string) {
  const m = (v || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}-${m[2]}-${m[1]}` : "—";
}

export default function BonusYearlySummaryScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId, selectedCompany } = useSelectedCompany();

  const fys = useMemo(() => fyOptions(), []);
  const [fyStart, setFyStart] = useState<number>(fys[0].start);
  const [data, setData] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);

  const companyId = user?.role === "company_admin" ? user.company_id : selectedCompanyId;

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      const r = await api<Summary>(
        `/admin/reports/bonus-yearly-summary?company_id=${companyId}&fy_start_year=${fyStart}`,
      );
      setData(r);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, fyStart]);

  useEffect(() => { void load(); }, [load]);

  const download = async () => {
    if (!companyId) return;
    try {
      const res = await apiBinary(
        `/admin/reports/bonus-yearly-summary.xlsx?company_id=${companyId}&fy_start_year=${fyStart}`,
      );
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = `Bonus_Yearly_Summary_${fyStart}.xlsx`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      if (Platform.OS === "web") globalThis.alert(e?.message || "Download failed");
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
        <Pressable onPress={() => router.back()} hitSlop={10} testID="bys-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Bonus Yearly Summary</Text>
        <Pressable onPress={download} hitSlop={10} testID="bys-xlsx">
          <Ionicons name="download-outline" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.body}>
        <View style={styles.chipWrap}>
          {fys.map((f) => (
            <Pressable
              key={f.start}
              onPress={() => setFyStart(f.start)}
              style={[styles.chip, fyStart === f.start && styles.chipActive]}
              testID={`bys-fy-${f.start}`}
            >
              <Text style={[styles.chipTxt, fyStart === f.start && styles.chipTxtActive]}>{f.label}</Text>
            </Pressable>
          ))}
        </View>

        {!companyId ? (
          <Text style={styles.hint}>Select a firm from the top bar to view this summary.</Text>
        ) : loading ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 30 }} />
        ) : !data ? (
          <Text style={styles.hint}>Could not load the summary.</Text>
        ) : data.rows.length === 0 ? (
          <Text style={styles.hint}>
            No Compliance Salary runs found in {data.fy_label}. Generate monthly runs first —
            this summary reads earned wages from them.
          </Text>
        ) : (
          <>
            <View style={styles.summaryCard}>
              <Text style={styles.summaryTitle}>
                {selectedCompany?.name || data.company_name || companyId} · {data.fy_label}
              </Text>
              <Text style={styles.summaryLine}>
                Employees: {data.employees_count} · Months covered: {data.months_covered.length} ·
                {" "}Total Earned: ₹{numFmt(data.totals.total_earned)} ·
                {" "}Allowance heads (Firm Master): {data.heads.map((h) => h.label).join(", ")}
              </Text>
            </View>

            <ScrollView horizontal>
              <View>
                {/* Two-row header: month labels spanning Days+Earned */}
                <View style={[styles.tr, styles.trHead]}>
                  <Text style={[styles.th, { width: 40 }]}>Sr.</Text>
                  <Text style={[styles.th, { width: 64 }]}>Code</Text>
                  <Text style={[styles.th, { width: 160, textAlign: "left" }]}>Employee Name</Text>
                  <Text style={[styles.th, { width: 140, textAlign: "left" }]}>Father Name</Text>
                  <Text style={[styles.th, { width: 90 }]}>Date of Join</Text>
                  {data.months.map((m) => (
                    <View key={m.key} style={{ width: 140 }}>
                      <Text style={[styles.th, { width: 140, paddingBottom: 0 }]}>{m.label}</Text>
                      <View style={{ flexDirection: "row" }}>
                        <Text style={[styles.thSub, { width: 56 }]}>Days</Text>
                        <Text style={[styles.thSub, { width: 84 }]}>Earned</Text>
                      </View>
                    </View>
                  ))}
                  {data.heads.map((h) => (
                    <Text key={h.key} style={[styles.th, { width: 96 }]}>{h.label} (Yr)</Text>
                  ))}
                  <Text style={[styles.th, { width: 90 }]}>Total Days</Text>
                  <Text style={[styles.th, { width: 110 }]}>Total Earned</Text>
                </View>
                {data.rows.map((r, i) => (
                  <View key={r.user_id || i} style={[styles.tr, i % 2 === 1 && styles.trOdd]}>
                    <Text style={[styles.td, { width: 40 }]}>{r.sr}</Text>
                    <Text style={[styles.td, { width: 64 }]}>{r.employee_code || "—"}</Text>
                    <Text style={[styles.td, { width: 160, textAlign: "left", fontWeight: "700" }]} numberOfLines={1}>
                      {r.name}
                    </Text>
                    <Text style={[styles.td, { width: 140, textAlign: "left" }]} numberOfLines={1}>
                      {r.father_name || "—"}
                    </Text>
                    <Text style={[styles.td, { width: 90 }]}>{isoToDDMM(r.doj)}</Text>
                    {data.months.map((m) => {
                      const cell = r.monthly?.[m.key] || {};
                      return (
                        <View key={m.key} style={{ width: 140, flexDirection: "row" }}>
                          <Text style={[styles.td, { width: 56 }]}>{cell.days ?? 0}</Text>
                          <Text style={[styles.td, { width: 84 }]}>{numFmt(cell.earned ?? 0)}</Text>
                        </View>
                      );
                    })}
                    {data.heads.map((h) => (
                      <Text key={h.key} style={[styles.td, { width: 96 }]}>{numFmt(r[h.key] || 0)}</Text>
                    ))}
                    <Text style={[styles.td, { width: 90, fontWeight: "700" }]}>{r.total_days}</Text>
                    <Text style={[styles.td, { width: 110, fontWeight: "800" }]}>{numFmt(r.total_earned)}</Text>
                  </View>
                ))}
                <View style={[styles.tr, styles.trTotal]}>
                  <Text style={[styles.td, styles.tdTotal, { width: 40 }]} />
                  <Text style={[styles.td, styles.tdTotal, { width: 64 }]} />
                  <Text style={[styles.td, styles.tdTotal, { width: 160, textAlign: "left" }]}>TOTAL</Text>
                  <Text style={[styles.td, styles.tdTotal, { width: 140 }]} />
                  <Text style={[styles.td, styles.tdTotal, { width: 90 }]} />
                  {data.months.map((m) => {
                    const cell = data.totals.monthly?.[m.key] || {};
                    return (
                      <View key={m.key} style={{ width: 140, flexDirection: "row" }}>
                        <Text style={[styles.td, styles.tdTotal, { width: 56 }]}>{cell.days ?? 0}</Text>
                        <Text style={[styles.td, styles.tdTotal, { width: 84 }]}>{numFmt(cell.earned ?? 0)}</Text>
                      </View>
                    );
                  })}
                  {data.heads.map((h) => (
                    <Text key={h.key} style={[styles.td, styles.tdTotal, { width: 96 }]}>
                      {numFmt(data.totals[h.key] || 0)}
                    </Text>
                  ))}
                  <Text style={[styles.td, styles.tdTotal, { width: 90 }]}>{data.totals.total_days}</Text>
                  <Text style={[styles.td, styles.tdTotal, { width: 110 }]}>{numFmt(data.totals.total_earned)}</Text>
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
  tr: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  trHead: { backgroundColor: colors.brandTertiary },
  trOdd: { backgroundColor: colors.surfaceSecondary },
  trTotal: { backgroundColor: "#FEF9C3" },
  th: { paddingVertical: 9, paddingHorizontal: 6, fontSize: 11, fontWeight: "800", color: colors.brandPrimary, textAlign: "center" },
  thSub: { paddingBottom: 6, fontSize: 10, fontWeight: "700", color: colors.brandPrimary, textAlign: "center" },
  td: { paddingVertical: 8, paddingHorizontal: 6, fontSize: 12, color: colors.onSurface, textAlign: "center" },
  tdTotal: { fontWeight: "800" },
});
