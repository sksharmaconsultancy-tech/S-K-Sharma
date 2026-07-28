/**
 * Employee-Wise Yearly Payroll Register (Bonus-Register style).
 * Months Apr–Mar across the top, salary heads as rows per employee block,
 * Total line after each employee, Grand Total at the end.
 * PDF (A3 landscape) + Excel exports keep the exact same layout.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing } from "@/src/theme";

type RegisterData = {
  company_name?: string;
  fy_label: string;
  months: { key: string; label: string }[];
  months_covered: string[];
  heads: { key: string; label: string; kind: string }[];
  rows: any[];
  grand: Record<string, number>;
  total_employees: number;
  print_date: string;
};

function fyOptions(): { start: number; label: string }[] {
  const now = new Date();
  const y = now.getFullYear();
  const currentStart = now.getMonth() >= 3 ? y : y - 1;
  const out: { start: number; label: string }[] = [];
  for (let i = 0; i <= 5; i++) {
    const s = currentStart - i;
    out.push({ start: s, label: `FY ${s}-${String(s + 1).slice(-2)}` });
  }
  return out;
}

const FLAG_LABELS: Record<string, string> = {
  pf_mismatch: "PF mismatch",
  esic_mismatch: "ESIC mismatch",
  negative_net: "Negative net",
  gross_mismatch: "Gross mismatch",
  missing_attendance: "Missing attendance",
  loan_recovery_error: "Loan recovery error",
  duplicate_employee: "Duplicate employee",
};

export default function PayrollRegisterScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();

  const fys = useMemo(() => fyOptions(), []);
  const [fyStart, setFyStart] = useState<number>(fys[0].start);
  const [fyYears, setFyYears] = useState<number>(1);
  const [dept, setDept] = useState("");
  const [desig, setDesig] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const [data, setData] = useState<RegisterData | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState("");
  const PAGE = 10;

  const companyId =
    user?.role === "company_admin" ? user.company_id : selectedCompanyId;

  const qs = useCallback(() => {
    const p = new URLSearchParams({
      company_id: companyId || "",
      fy_start_year: String(fyStart),
      fy_years: String(fyYears),
    });
    if (dept) p.append("department", dept);
    if (desig) p.append("designation", desig);
    if (category) p.append("category", category);
    if (status) p.append("status", status);
    return p.toString();
  }, [companyId, fyStart, fyYears, dept, desig, category, status]);

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      const r = await api<RegisterData>(
        `/admin/reports/payroll-register?${qs()}&skip=${page * PAGE}&limit=${PAGE}`,
      );
      setData(r);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, qs, page]);

  useEffect(() => {
    void load();
  }, [load]);

  const download = async (kind: "pdf" | "xlsx") => {
    if (!companyId) return;
    setExporting(kind);
    try {
      const res = await apiBinary(
        `/admin/reports/payroll-register.${kind}?${qs()}`,
      );
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = `Payroll_Register_${fyStart}.${kind}`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      if (Platform.OS === "web") globalThis.alert(e?.message || "Export failed");
    } finally {
      setExporting("");
    }
  };

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role)) {
    return <Redirect href="/" />;
  }

  const fmt = (v: any) =>
    typeof v === "number" && v
      ? v.toLocaleString("en-IN", { maximumFractionDigits: 0 })
      : "";
  const months = data?.months || [];
  const heads = data?.heads || [];
  const totalPages = Math.max(1, Math.ceil((data?.total_employees || 0) / PAGE));

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="pr-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Yearly Payroll Register</Text>
        <View style={{ flexDirection: "row", gap: 14 }}>
          <Pressable
            onPress={() => download("pdf")}
            hitSlop={10}
            testID="pr-pdf"
            disabled={!!exporting}
          >
            {exporting === "pdf" ? (
              <ActivityIndicator size="small" />
            ) : (
              <Ionicons name="document-outline" size={20} color="#C0392B" />
            )}
          </Pressable>
          <Pressable
            onPress={() => download("xlsx")}
            hitSlop={10}
            testID="pr-xlsx"
            disabled={!!exporting}
          >
            {exporting === "xlsx" ? (
              <ActivityIndicator size="small" />
            ) : (
              <Ionicons name="download-outline" size={20} color={colors.brandPrimary} />
            )}
          </Pressable>
        </View>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        {/* Filters */}
        <View style={styles.filterRow}>
          {Platform.OS === "web" && (
            <>
              <select
                data-testid="pr-fy"
                value={fyStart}
                onChange={(e) => {
                  setPage(0);
                  setFyStart(Number((e.target as HTMLSelectElement).value));
                }}
                style={selStyle as any}
              >
                {fys.map((f) => (
                  <option key={f.start} value={f.start}>
                    {f.label}
                  </option>
                ))}
              </select>
              <select
                data-testid="pr-years"
                value={fyYears}
                onChange={(e) => {
                  setPage(0);
                  setFyYears(Number((e.target as HTMLSelectElement).value));
                }}
                style={selStyle as any}
              >
                {[1, 2, 3].map((n) => (
                  <option key={n} value={n}>
                    {n} Financial Year{n > 1 ? "s" : ""}
                  </option>
                ))}
              </select>
              <select
                data-testid="pr-status"
                value={status}
                onChange={(e) => {
                  setPage(0);
                  setStatus((e.target as HTMLSelectElement).value);
                }}
                style={selStyle as any}
              >
                <option value="">All Employees</option>
                <option value="active">Active only</option>
                <option value="left">Left / Resigned</option>
              </select>
            </>
          )}
          <TextInput
            style={styles.input}
            placeholder="Department…"
            value={dept}
            onChangeText={(t) => {
              setPage(0);
              setDept(t);
            }}
            testID="pr-dept"
          />
          <TextInput
            style={styles.input}
            placeholder="Designation…"
            value={desig}
            onChangeText={(t) => {
              setPage(0);
              setDesig(t);
            }}
            testID="pr-desig"
          />
          <TextInput
            style={styles.input}
            placeholder="Category…"
            value={category}
            onChangeText={(t) => {
              setPage(0);
              setCategory(t);
            }}
            testID="pr-cat"
          />
        </View>

        {loading && <ActivityIndicator style={{ marginVertical: 30 }} />}
        {!loading && data && (
          <>
            <Text style={styles.meta}>
              {data.company_name} · {data.fy_label} · {data.total_employees}{" "}
              employees · Months with salary data: {data.months_covered.length}
            </Text>
            <Text style={styles.legend}>
              🟥 highlighted cells = AI validation (PF/ESIC/Gross mismatch,
              negative net, missing attendance, loan recovery error)
            </Text>

            {data.rows.map((emp) => (
              <View key={emp.user_id} style={styles.empBlock}>
                <View style={styles.empInfo}>
                  <Text style={styles.empName}>
                    {emp.sr}. [{emp.employee_code || "—"}] {emp.name}
                    {emp.flags?._employee ? "  ⚠ DUPLICATE" : ""}
                  </Text>
                  <Text style={styles.empSub}>
                    F/H: {emp.father_name || "—"} · {emp.designation || "—"} ·
                    Dept {emp.department || "—"} · DOJ {emp.doj || "—"} · DOL{" "}
                    {emp.dol || "—"}
                  </Text>
                  <Text style={styles.empSub}>
                    PF {emp.pf_no || "—"} · ESIC {emp.esic_no || "—"} · UAN{" "}
                    {emp.uan || "—"} · Bank {emp.bank_name || "—"} · A/c{" "}
                    {emp.account_no || "—"} · IFSC {emp.ifsc || "—"}
                  </Text>
                </View>
                <ScrollView horizontal showsHorizontalScrollIndicator>
                  <View>
                    <View style={styles.tr}>
                      <Text style={[styles.th, styles.headCol]}>Particulars</Text>
                      {months.map((m) => (
                        <Text key={m.key} style={styles.th}>
                          {m.label}
                        </Text>
                      ))}
                      <Text style={[styles.th, styles.totCol]}>TOTAL</Text>
                    </View>
                    {heads.map((h) => (
                      <View key={h.key} style={styles.tr}>
                        <Text
                          style={[
                            styles.tdHead,
                            styles.headCol,
                            (h.kind === "total" || h.kind === "net") &&
                              styles.bold,
                          ]}
                        >
                          {h.label}
                        </Text>
                        {months.map((m) => {
                          const v = emp.months?.[m.key]?.[h.key];
                          const flagged =
                            h.key !== "days" &&
                            (emp.flags?.[m.key] || []).length > 0;
                          return (
                            <Text
                              key={m.key}
                              style={[styles.td, flagged && styles.tdErr]}
                            >
                              {h.key === "days" ? v || "" : fmt(v)}
                            </Text>
                          );
                        })}
                        <Text style={[styles.td, styles.totCol, styles.bold]}>
                          {h.key === "days"
                            ? emp.totals?.[h.key] || ""
                            : fmt(emp.totals?.[h.key])}
                        </Text>
                      </View>
                    ))}
                  </View>
                </ScrollView>
                <Text style={styles.empTotal}>
                  EMPLOYEE TOTAL — Gross ₹{fmt(emp.totals?.gross)} · Deduction ₹
                  {fmt(emp.totals?.total_ded)} · Net ₹{fmt(emp.totals?.net)}
                </Text>
                {Object.entries(emp.flags || {})
                  .filter(([k]) => k !== "_employee")
                  .slice(0, 3)
                  .map(([mk, fl]: any) => (
                    <Text key={mk} style={styles.flagLine}>
                      ⚠ {mk}: {(fl as string[]).map((f) => FLAG_LABELS[f] || f).join(", ")}
                    </Text>
                  ))}
              </View>
            ))}

            {/* Pagination */}
            <View style={styles.pager}>
              <Pressable
                disabled={page <= 0}
                onPress={() => setPage((p) => p - 1)}
                style={[styles.pageBtn, page <= 0 && { opacity: 0.4 }]}
                testID="pr-prev"
              >
                <Text style={styles.pageBtnTxt}>‹ Prev</Text>
              </Pressable>
              <Text style={styles.meta}>
                Page {page + 1} / {totalPages}
              </Text>
              <Pressable
                disabled={page + 1 >= totalPages}
                onPress={() => setPage((p) => p + 1)}
                style={[styles.pageBtn, page + 1 >= totalPages && { opacity: 0.4 }]}
                testID="pr-next"
              >
                <Text style={styles.pageBtnTxt}>Next ›</Text>
              </Pressable>
            </View>

            {/* Grand totals */}
            <View style={styles.grand}>
              <Text style={styles.grandTitle}>
                GRAND TOTAL ({data.total_employees} employees)
              </Text>
              {[
                ["Total Days", data.grand.days],
                ["Total Basic", data.grand.basic],
                ["Total Gross", data.grand.gross],
                ["Total Overtime", data.grand.ot],
                ["Total PF", data.grand.pf_ee],
                ["Total ESIC", data.grand.esic_ee],
                ["Total PT", data.grand.pt],
                ["Total TDS", data.grand.tds],
                ["Grand Total Deduction", data.grand.total_ded],
                ["Grand Net Salary", data.grand.net],
                ["Employer PF", data.grand.pf_er],
                ["Employer ESIC", data.grand.esic_er],
                ["Total CTC", data.grand.ctc],
              ].map(([lbl, v]: any) => (
                <View key={lbl} style={styles.grandRow}>
                  <Text style={styles.grandLbl}>{lbl}</Text>
                  <Text style={styles.grandVal}>₹{fmt(v)}</Text>
                </View>
              ))}
            </View>
          </>
        )}
        {!loading && data && data.rows.length === 0 && (
          <Text style={styles.meta}>
            No salary runs found for this Financial Year.
          </Text>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const selStyle = {
  padding: 8,
  borderRadius: 8,
  borderColor: "#CBD5E1",
  borderWidth: 1,
  fontSize: 13,
};

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
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
  headerTitle: { fontSize: 16, fontWeight: "700", color: colors.onSurface },
  filterRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginBottom: spacing.sm,
    alignItems: "center",
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 10,
    paddingVertical: 7,
    fontSize: 13,
    minWidth: 130,
    backgroundColor: colors.surface,
  },
  meta: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginBottom: 6 },
  legend: { fontSize: 11.5, color: "#B45309", marginBottom: 10 },
  empBlock: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
    padding: spacing.sm,
  },
  empInfo: {
    backgroundColor: "#EFF6FF",
    borderRadius: radius.sm,
    padding: 8,
    marginBottom: 6,
  },
  empName: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  empSub: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 2 },
  tr: { flexDirection: "row" },
  th: {
    width: 78,
    padding: 5,
    fontSize: 11,
    fontWeight: "800",
    textAlign: "center",
    backgroundColor: "#DDEBF7",
    borderWidth: 0.5,
    borderColor: "#CBD5E1",
    color: colors.onSurface,
  },
  headCol: { width: 150, textAlign: "left" },
  totCol: { backgroundColor: "#FFF7E0" },
  tdHead: {
    width: 150,
    padding: 5,
    fontSize: 11,
    borderWidth: 0.5,
    borderColor: "#E2E8F0",
    color: colors.onSurface,
  },
  td: {
    width: 78,
    padding: 5,
    fontSize: 11,
    textAlign: "right",
    borderWidth: 0.5,
    borderColor: "#E2E8F0",
    color: colors.onSurface,
  },
  tdErr: { backgroundColor: "#FDDCD3" },
  bold: { fontWeight: "800" },
  empTotal: {
    marginTop: 6,
    backgroundColor: "#FFF2CC",
    borderRadius: radius.sm,
    padding: 8,
    fontSize: 12.5,
    fontWeight: "800",
    color: colors.onSurface,
  },
  flagLine: { fontSize: 11, color: "#B91C1C", marginTop: 3 },
  pager: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 16,
    marginVertical: spacing.sm,
  },
  pageBtn: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.sm,
  },
  pageBtnTxt: { color: "#fff", fontWeight: "700", fontSize: 12.5 },
  grand: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: "#F1C40F",
    padding: spacing.md,
    marginBottom: 40,
  },
  grandTitle: {
    fontSize: 14,
    fontWeight: "800",
    marginBottom: 8,
    color: colors.onSurface,
  },
  grandRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 3,
    borderBottomWidth: 0.5,
    borderBottomColor: colors.border,
  },
  grandLbl: { fontSize: 12.5, color: colors.onSurfaceSecondary },
  grandVal: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
});
