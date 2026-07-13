/**
 * Iter 100 — Attendance Master (Super Admin + Sub Super Admins ONLY).
 * Compliance worksheet per firm + month: employee statutory identifiers,
 * compliance salary breakdown, manual Present Days + Other Deductions,
 * computed Gross Earning. Web-portal-oriented grid.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  TextInput,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };

type Row = {
  user_id: string;
  pf_no?: string | null;
  uan_no?: string | null;
  esic_no?: string | null;
  employee_code?: string | null;
  name?: string;
  father_name?: string | null;
  designation?: string | null;
  doj?: string | null;
  salary_mode?: string;
  basic: number;
  hra: number;
  conveyance: number;
  medical: number;
  special: number;
  others: number;
  total_salary: number;
  present_days: number;
  deduction_head: string;
  deduction_amount: number;
  gross_earning: number;
};

const now = new Date();
const DEFAULT_MONTH = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;

export default function AttendanceMasterScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [month, setMonth] = useState(DEFAULT_MONTH);
  const [monthDays, setMonthDays] = useState("26");
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const showToast = (m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 2800);
  };

  useEffect(() => {
    if (!user) return;
    (async () => {
      try {
        const r = await api<{ companies: Company[] }>("/companies");
        setCompanies(r.companies || []);
        if ((r.companies || []).length === 1) setCompanyId(r.companies[0].company_id);
      } catch {
        setCompanies([]);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.role]);

  const load = useCallback(async () => {
    if (!companyId || !/^\d{4}-\d{2}$/.test(month)) return;
    setLoading(true);
    try {
      const r = await api<{ rows: Row[] }>(
        `/admin/attendance-master?company_id=${companyId}&month=${month}&month_days=${Number(monthDays) || 26}`,
      );
      setRows(r.rows || []);
    } catch (e: any) {
      showToast(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [companyId, month, monthDays]);

  useEffect(() => { load(); }, [load]);

  const md = Math.max(1, Number(monthDays) || 26);
  const recompute = (r: Row): number => {
    const g = r.salary_mode === "daily"
      ? r.total_salary * (Number(r.present_days) || 0)
      : (r.total_salary * (Number(r.present_days) || 0)) / md;
    return Math.round(g * 100) / 100;
  };

  const setCell = (uid: string, patch: Partial<Row>) => {
    setRows((prev) =>
      prev.map((r) => {
        if (r.user_id !== uid) return r;
        const nr = { ...r, ...patch };
        nr.gross_earning = recompute(nr);
        return nr;
      }),
    );
  };

  const saveAll = async () => {
    if (!companyId) return;
    setSaving(true);
    try {
      await api("/admin/attendance-master", {
        method: "PATCH",
        body: {
          company_id: companyId,
          month,
          entries: rows.map((r) => ({
            user_id: r.user_id,
            present_days: Number(r.present_days) || 0,
            deduction_head: r.deduction_head || "",
            deduction_amount: Number(r.deduction_amount) || 0,
          })),
        },
      });
      showToast("Saved ✓");
    } catch (e: any) {
      showToast(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const downloadCsv = () => {
    if (Platform.OS !== "web" || typeof document === "undefined") return;
    const head = [
      "PF No", "UAN No", "ESIC No", "Emp ID", "Name", "Father Name",
      "Designation", "DOJ", "Basic", "HRA", "Conv", "Medical", "Special",
      "Others", "Total Salary", "Present Days", "Deduction Head",
      "Deduction Amt", "Gross Earning",
    ];
    const lines = [head.join(",")];
    const esc = (s: any) => `"${String(s ?? "").replace(/"/g, '""')}"`;
    for (const r of rows) {
      lines.push([
        esc(r.pf_no), esc(r.uan_no), esc(r.esic_no), esc(r.employee_code),
        esc(r.name), esc(r.father_name), esc(r.designation), esc(r.doj),
        r.basic, r.hra, r.conveyance, r.medical, r.special, r.others,
        r.total_salary, r.present_days, esc(r.deduction_head),
        r.deduction_amount, r.gross_earning,
      ].join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `AttendanceMaster_${month}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  if (authLoading) return null;
  // Super Admin + Sub Super Admins ONLY.
  if (!user || !["super_admin", "sub_admin"].includes(user.role)) {
    return <Redirect href="/" />;
  }

  const totals = rows.reduce(
    (a, r) => ({
      salary: a.salary + (r.total_salary || 0),
      present: a.present + (Number(r.present_days) || 0),
      ded: a.ded + (Number(r.deduction_amount) || 0),
      gross: a.gross + (r.gross_earning || 0),
    }),
    { salary: 0, present: 0, ded: 0, gross: 0 },
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="am-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Attendance Master</Text>
        <View style={{ flexDirection: "row", gap: 14 }}>
          <Pressable onPress={downloadCsv} hitSlop={10} testID="am-csv">
            <Ionicons name="download-outline" size={20} color={colors.brandPrimary} />
          </Pressable>
          <Pressable onPress={saveAll} hitSlop={10} disabled={saving} testID="am-save">
            <Ionicons name={saving ? "hourglass-outline" : "save-outline"} size={20} color={colors.brandPrimary} />
          </Pressable>
        </View>
      </View>

      <ScrollView contentContainerStyle={styles.body}>
        {/* Filters */}
        <View style={styles.filterRow}>
          <View style={styles.chipWrap}>
            {companies.map((c) => (
              <Pressable
                key={c.company_id}
                onPress={() => setCompanyId(c.company_id)}
                style={[styles.chip, companyId === c.company_id && styles.chipActive]}
                testID={`am-firm-${c.company_id}`}
              >
                <Text style={[styles.chipTxt, companyId === c.company_id && styles.chipTxtActive]}>
                  {c.name}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>
        <View style={styles.filterRow}>
          <View style={styles.inpBox}>
            <Text style={styles.inpLbl}>Month (YYYY-MM)</Text>
            <TextInput
              style={styles.inp}
              value={month}
              onChangeText={setMonth}
              placeholder="2026-06"
              placeholderTextColor={colors.onSurfaceTertiary}
              testID="am-month"
            />
          </View>
          <View style={styles.inpBox}>
            <Text style={styles.inpLbl}>Month Days</Text>
            <TextInput
              style={styles.inp}
              value={monthDays}
              onChangeText={(v) => setMonthDays(v.replace(/[^0-9]/g, ""))}
              keyboardType="numeric"
              testID="am-month-days"
            />
          </View>
          <Pressable style={styles.saveBtn} onPress={saveAll} disabled={saving} testID="am-save-btn">
            <Ionicons name="save-outline" size={15} color="#fff" />
            <Text style={styles.saveBtnTxt}>{saving ? "Saving…" : "Save All"}</Text>
          </Pressable>
        </View>

        {loading ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 30 }} />
        ) : !companyId ? (
          <Text style={styles.hint}>Select a firm to load the Attendance Master.</Text>
        ) : (
          <ScrollView horizontal>
            <View>
              <View style={[styles.tr, styles.trHead]}>
                <Text style={[styles.th, { width: 100 }]}>PF No.</Text>
                <Text style={[styles.th, { width: 110 }]}>UAN No.</Text>
                <Text style={[styles.th, { width: 100 }]}>ESIC No.</Text>
                <Text style={[styles.th, { width: 60 }]}>ID</Text>
                <Text style={[styles.th, { width: 160, textAlign: "left" }]}>Name</Text>
                <Text style={[styles.th, { width: 140, textAlign: "left" }]}>Father Name</Text>
                <Text style={[styles.th, { width: 110 }]}>Designation</Text>
                <Text style={[styles.th, { width: 90 }]}>DOJ</Text>
                <Text style={[styles.th, { width: 80 }]}>Basic</Text>
                <Text style={[styles.th, { width: 70 }]}>HRA</Text>
                <Text style={[styles.th, { width: 70 }]}>Conv.</Text>
                <Text style={[styles.th, { width: 80 }]}>Other Allow.</Text>
                <Text style={[styles.th, { width: 90 }]}>Total Salary</Text>
                <Text style={[styles.th, { width: 80 }]}>Present Days</Text>
                <Text style={[styles.th, { width: 120 }]}>Deduction Head</Text>
                <Text style={[styles.th, { width: 90 }]}>Deduction Amt</Text>
                <Text style={[styles.th, { width: 100 }]}>Gross Earning</Text>
              </View>
              {rows.map((r, i) => (
                <View key={r.user_id} style={[styles.tr, i % 2 === 1 && styles.trOdd]}>
                  <Text style={[styles.td, { width: 100 }]} numberOfLines={1}>{r.pf_no || "—"}</Text>
                  <Text style={[styles.td, { width: 110 }]} numberOfLines={1}>{r.uan_no || "—"}</Text>
                  <Text style={[styles.td, { width: 100 }]} numberOfLines={1}>{r.esic_no || "—"}</Text>
                  <Text style={[styles.td, { width: 60 }]}>{r.employee_code || "—"}</Text>
                  <Text style={[styles.td, { width: 160, textAlign: "left", fontWeight: "700" }]} numberOfLines={1}>{r.name}</Text>
                  <Text style={[styles.td, { width: 140, textAlign: "left" }]} numberOfLines={1}>{r.father_name || "—"}</Text>
                  <Text style={[styles.td, { width: 110 }]} numberOfLines={1}>{r.designation || "—"}</Text>
                  <Text style={[styles.td, { width: 90 }]}>{r.doj || "—"}</Text>
                  <Text style={[styles.td, { width: 80 }]}>{r.basic}</Text>
                  <Text style={[styles.td, { width: 70 }]}>{r.hra}</Text>
                  <Text style={[styles.td, { width: 70 }]}>{r.conveyance}</Text>
                  <Text style={[styles.td, { width: 80 }]}>{Math.round((r.medical + r.special + r.others) * 100) / 100}</Text>
                  <Text style={[styles.td, { width: 90, fontWeight: "800" }]}>{r.total_salary}</Text>
                  <TextInput
                    style={[styles.tdInput, { width: 80 }]}
                    value={String(r.present_days ?? "")}
                    onChangeText={(v) => setCell(r.user_id, { present_days: (v.replace(/[^0-9.]/g, "") as any) })}
                    keyboardType="numeric"
                    testID={`am-present-${r.user_id}`}
                  />
                  <TextInput
                    style={[styles.tdInput, { width: 120 }]}
                    value={r.deduction_head}
                    onChangeText={(v) => setCell(r.user_id, { deduction_head: v })}
                    placeholder="Advance / TDS…"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    testID={`am-dedhead-${r.user_id}`}
                  />
                  <TextInput
                    style={[styles.tdInput, { width: 90 }]}
                    value={String(r.deduction_amount ?? "")}
                    onChangeText={(v) => setCell(r.user_id, { deduction_amount: (v.replace(/[^0-9.]/g, "") as any) })}
                    keyboardType="numeric"
                    testID={`am-dedamt-${r.user_id}`}
                  />
                  <Text style={[styles.td, { width: 100, fontWeight: "800", color: colors.brandPrimary }]}>
                    {r.gross_earning}
                  </Text>
                </View>
              ))}
              {/* Totals */}
              <View style={[styles.tr, styles.trTotal]}>
                <Text style={[styles.td, { width: 1120, textAlign: "right", fontWeight: "800" }]}>
                  TOTAL — Salary: ₹{Math.round(totals.salary)} · Present: {totals.present}
                </Text>
                <Text style={[styles.td, { width: 210, fontWeight: "800" }]}>Ded: ₹{Math.round(totals.ded)}</Text>
                <Text style={[styles.td, { width: 100, fontWeight: "900", color: colors.brandPrimary }]}>
                  ₹{Math.round(totals.gross)}
                </Text>
              </View>
            </View>
          </ScrollView>
        )}
        <View style={{ height: 60 }} />
      </ScrollView>

      {toast ? (
        <View style={styles.toast}><Text style={styles.toastTxt}>{toast}</Text></View>
      ) : null}
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
  filterRow: { flexDirection: "row", alignItems: "flex-end", gap: 10, marginBottom: spacing.sm, flexWrap: "wrap" },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
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
  inpBox: { gap: 4 },
  inpLbl: { color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "700" },
  inp: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 7,
    color: colors.onSurface,
    fontSize: 13,
    backgroundColor: colors.surface,
    width: 130,
  },
  saveBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: radius.sm,
  },
  saveBtnTxt: { color: "#fff", fontSize: 12.5, fontWeight: "800" },
  tr: { flexDirection: "row", alignItems: "center", borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  trHead: { backgroundColor: colors.brandTertiary },
  trOdd: { backgroundColor: colors.surfaceSecondary },
  trTotal: { backgroundColor: colors.brandTertiary },
  th: { paddingVertical: 9, paddingHorizontal: 6, fontSize: 10.5, fontWeight: "800", color: colors.brandPrimary, textAlign: "center" },
  td: { paddingVertical: 8, paddingHorizontal: 6, fontSize: 11.5, color: colors.onSurface, textAlign: "center" },
  tdInput: {
    marginVertical: 3,
    marginHorizontal: 4,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 5,
    fontSize: 11.5,
    color: colors.onSurface,
    backgroundColor: "#FFFDF4",
    textAlign: "center",
  },
  toast: {
    position: "absolute",
    bottom: 26,
    alignSelf: "center",
    backgroundColor: "#111827",
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: 999,
  },
  toastTxt: { color: "#fff", fontSize: type.sm },
});
