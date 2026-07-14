/**
 * Bank Sheet — salary transfer statement (Web + mobile).
 * Net Salary is caught from the Compliance Salary run's net pay.
 * Columns: S.No, Name, Father Name, Bank Name, Name as per Bank, IFSC, Account No, Net Salary.
 * Filters: Finance Year, Employee Type, Month, Pay Mode, Bank Name.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Row = {
  sn: number; name: string; father_name: string; bank_name: string;
  name_as_per_bank: string; ifsc: string; account_no: string; net_salary: number;
};
type Resp = { rows: Row[]; count: number; total_net: number; banks: string[]; has_compliance: boolean };

function financeYears(): { label: string; startYear: number }[] {
  const now = new Date();
  const curFyStart = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  const out: { label: string; startYear: number }[] = [];
  for (let y = curFyStart; y >= curFyStart - 3; y--) {
    out.push({ label: `FY ${y}-${String(y + 1).slice(2)}`, startYear: y });
  }
  return out;
}
function monthsOfFy(startYear: number): { value: string; label: string }[] {
  const names = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"];
  return names.map((nm, i) => {
    const monthIndex = (3 + i) % 12;
    const yr = i < 9 ? startYear : startYear + 1;
    return { value: `${yr}-${String(monthIndex + 1).padStart(2, "0")}`, label: `${nm} ${yr}` };
  });
}

const EMP_TYPES = ["all", "Staff", "Labour"];
const PAY_MODES = ["all", "Bank", "Cash", "Cheque"];

export default function BankSheetScreen() {
  const router = useRouter();
  const { selectedCompanyId } = useSelectedCompany();
  const fyList = useMemo(() => financeYears(), []);
  const [fy, setFy] = useState(fyList[0].startYear);
  const monthOpts = useMemo(() => monthsOfFy(fy), [fy]);
  const [month, setMonth] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [empType, setEmpType] = useState("all");
  const [payMode, setPayMode] = useState("all");
  const [bank, setBank] = useState("all");

  const [data, setData] = useState<Resp | null>(null);
  const [busy, setBusy] = useState(false);
  const [dl, setDl] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    setBusy(true); setErr(null);
    try {
      const params = new URLSearchParams({ month });
      if (selectedCompanyId) params.set("company_id", selectedCompanyId);
      if (empType !== "all") params.set("employee_type", empType);
      if (payMode !== "all") params.set("pay_mode", payMode);
      if (bank !== "all") params.set("bank_name", bank);
      const r = await api<Resp>(`/admin/bank-sheet?${params.toString()}`);
      setData(r);
    } catch (e: any) {
      setErr(e?.message || "Failed to load"); setData(null);
    } finally { setBusy(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [month, empType, payMode, bank, selectedCompanyId]);

  const download = async () => {
    setDl(true);
    try {
      const params = new URLSearchParams({ month });
      if (selectedCompanyId) params.set("company_id", selectedCompanyId);
      if (empType !== "all") params.set("employee_type", empType);
      if (payMode !== "all") params.set("pay_mode", payMode);
      if (bank !== "all") params.set("bank_name", bank);
      const r = await apiBinary(`/admin/bank-sheet.xlsx?${params.toString()}`);
      if (Platform.OS === "web" && r.webBlobUrl) {
        const a = document.createElement("a");
        a.href = r.webBlobUrl; a.download = `bank-sheet-${month}.xlsx`;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(r.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Download failed");
    } finally { setDl(false); }
  };

  const Chips = ({ label, options, value, onChange, render }: {
    label: string; options: string[]; value: string; onChange: (v: string) => void;
    render?: (v: string) => string;
  }) => (
    <View style={{ marginBottom: 10 }}>
      <Text style={styles.filterLbl}>{label}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>
        {options.map((o) => (
          <Pressable key={o} onPress={() => onChange(o)}
            style={[styles.chip, value === o && styles.chipOn]}>
            <Text style={[styles.chipTxt, value === o && styles.chipTxtOn]}>
              {render ? render(o) : (o === "all" ? "All" : o)}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={styles.backBtn}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>🏦 Bank Sheet</Text>
        <View style={{ flex: 1 }} />
        <Pressable onPress={download} disabled={dl || !data?.count}
          style={[styles.dlBtn, (dl || !data?.count) && { opacity: 0.5 }]} testID="bank-sheet-export">
          {dl ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name="download-outline" size={16} color="#fff" />}
          <Text style={styles.dlTxt}>Excel</Text>
        </Pressable>
      </View>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: spacing.md }}>
        <View style={styles.card}>
          <Chips label="Finance Year" options={fyList.map((f) => String(f.startYear))} value={String(fy)}
            onChange={(v) => setFy(Number(v))}
            render={(v) => fyList.find((f) => String(f.startYear) === v)?.label || v} />
          <Chips label="Month" options={monthOpts.map((m) => m.value)} value={month}
            onChange={setMonth} render={(v) => monthOpts.find((m) => m.value === v)?.label || v} />
          <Chips label="Employee Type" options={EMP_TYPES} value={empType} onChange={setEmpType} />
          <Chips label="Pay Mode" options={PAY_MODES} value={payMode} onChange={setPayMode} />
          <Chips label="Bank Name" options={["all", ...(data?.banks || [])]} value={bank} onChange={setBank} />
        </View>

        {busy ? (
          <ActivityIndicator style={{ marginTop: 30 }} color={colors.brandPrimary} size="large" />
        ) : err ? (
          <Text style={styles.err}>{err}</Text>
        ) : !data || data.count === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="document-text-outline" size={40} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyTxt}>
              {data && !data.has_compliance
                ? "No Compliance Salary run found for this month. Process Compliance Salary first — Net Salary is caught from there."
                : "No employees match these filters."}
            </Text>
          </View>
        ) : (
          <View style={styles.card}>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryTxt}>{data.count} employees</Text>
              <Text style={styles.summaryTotal}>Total: ₹{data.total_net.toLocaleString("en-IN")}</Text>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={true}>
              <View>
                <View style={[styles.tr, styles.trHead]}>
                  <Text style={[styles.th, { width: 44 }]}>S.No</Text>
                  <Text style={[styles.th, { width: 150 }]}>Name</Text>
                  <Text style={[styles.th, { width: 140 }]}>Father Name</Text>
                  <Text style={[styles.th, { width: 140 }]}>Bank Name</Text>
                  <Text style={[styles.th, { width: 150 }]}>Name as per Bank</Text>
                  <Text style={[styles.th, { width: 120 }]}>IFSC</Text>
                  <Text style={[styles.th, { width: 140 }]}>Account No.</Text>
                  <Text style={[styles.th, { width: 100, textAlign: "right" }]}>Net Salary</Text>
                </View>
                {data.rows.map((r) => (
                  <View key={r.sn} style={styles.tr}>
                    <Text style={[styles.td, { width: 44 }]}>{r.sn}</Text>
                    <Text style={[styles.td, { width: 150 }]} numberOfLines={1}>{r.name}</Text>
                    <Text style={[styles.td, { width: 140 }]} numberOfLines={1}>{r.father_name || "—"}</Text>
                    <Text style={[styles.td, { width: 140 }]} numberOfLines={1}>{r.bank_name || "—"}</Text>
                    <Text style={[styles.td, { width: 150 }]} numberOfLines={1}>{r.name_as_per_bank || "—"}</Text>
                    <Text style={[styles.td, { width: 120 }]} numberOfLines={1}>{r.ifsc || "—"}</Text>
                    <Text style={[styles.td, { width: 140 }]} numberOfLines={1}>{r.account_no || "—"}</Text>
                    <Text style={[styles.td, { width: 100, textAlign: "right", fontWeight: "700" }]}>
                      ₹{r.net_salary.toLocaleString("en-IN")}
                    </Text>
                  </View>
                ))}
              </View>
            </ScrollView>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: spacing.md,
    paddingVertical: 12, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  backBtn: { padding: 2 },
  title: { ...type.h2, color: colors.onSurface, fontWeight: "800" },
  dlBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.brandPrimary,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md,
  },
  dlTxt: { color: "#fff", fontWeight: "700", fontSize: 13 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md,
  },
  filterLbl: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 6 },
  chip: {
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, borderWidth: 1.5,
    borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  summaryRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  summaryTxt: { fontSize: 13, color: colors.onSurfaceSecondary, fontWeight: "600" },
  summaryTotal: { fontSize: 15, color: colors.brandPrimary, fontWeight: "800" },
  tr: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: "#EEF2F5", paddingVertical: 9 },
  trHead: { backgroundColor: "#F1F5F9", borderTopLeftRadius: 8, borderTopRightRadius: 8 },
  th: { fontSize: 11.5, fontWeight: "800", color: colors.onSurfaceSecondary, paddingHorizontal: 6 },
  td: { fontSize: 12.5, color: colors.onSurface, paddingHorizontal: 6 },
  err: { color: "#B91C1C", textAlign: "center", marginTop: 24 },
  empty: { alignItems: "center", padding: 30, gap: 10 },
  emptyTxt: { color: colors.onSurfaceSecondary, textAlign: "center", fontSize: 13.5, lineHeight: 20 },
});
