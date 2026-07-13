import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  TextInput,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

type Row = {
  user_id: string;
  name: string;
  employee_code?: string | null;
  email?: string | null;
  company_id?: string | null;
  present_days: number;
  absent_days: number;
  off_days: number;
  days_in_month: number;
  working_days: number;
  total_hours: number;
  salary_monthly?: number | null;
  gross: number;
};

type Payload = {
  year: number;
  month: number;
  month_key: string;
  days_in_month: number;
  off_days_total: number;
  rows: Row[];
  totals: {
    employees: number;
    gross_total: number;
    total_hours: number;
  };
};

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function fmtCurrency(n: number): string {
  if (!n) return "₹0";
  try {
    return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
  } catch {
    return `₹${n.toFixed(2)}`;
  }
}

function fmtHours(n: number): string {
  if (!n) return "0 h";
  return `${n.toFixed(1)} h`;
}

export default function PayrollRunScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const now = new Date();
  const [cursor, setCursor] = useState<{ y: number; m: number }>({
    // Default to previous month (assumes payroll is processed after the
    // month closes). If user is early in the month this still makes sense.
    y: now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear(),
    m: now.getMonth() === 0 ? 12 : now.getMonth(),
  });
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [companies, setCompanies] = useState<any[]>([]);
  const [companyFilter, setCompanyFilter] = useState<string | "all">("all");
  const [processed, setProcessed] = useState(false);
  const [search, setSearch] = useState("");

  const isSuper = user?.role === "super_admin";
  const isAdmin = isSuper || user?.role === "company_admin";

  const monthLabel = `${MONTHS[cursor.m - 1]} ${cursor.y}`;
  const canGoNext = (() => {
    // Can't advance past the CURRENT month.
    const currY = now.getFullYear();
    const currM = now.getMonth() + 1;
    return !(cursor.y === currY && cursor.m === currM);
  })();

  const goPrev = () =>
    setCursor((c) => (c.m === 1 ? { y: c.y - 1, m: 12 } : { y: c.y, m: c.m - 1 }));
  const goNext = () => {
    if (!canGoNext) return;
    setCursor((c) => (c.m === 12 ? { y: c.y + 1, m: 1 } : { y: c.y, m: c.m + 1 }));
  };

  useEffect(() => {
    if (isSuper && companies.length === 0) {
      api<{ companies: any[] }>("/companies")
        .then((r) => setCompanies(r.companies || []))
        .catch(() => {});
    }
  }, [isSuper, companies.length]);

  const runPayroll = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({
        year: String(cursor.y),
        month: String(cursor.m),
      });
      if (isSuper && companyFilter !== "all") {
        p.append("company_id", companyFilter);
      }
      const r = await api<Payload>(`/admin/payroll/run?${p.toString()}`);
      setData(r);
      setProcessed(true);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [cursor.y, cursor.m, isSuper, companyFilter]);

  // Reset processed state when month or filter changes so the user must
  // explicitly hit "Process" again — makes the action feel intentional.
  useEffect(() => {
    setProcessed(false);
    setData(null);
  }, [cursor.y, cursor.m, companyFilter]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    if (!q) return data.rows;
    return data.rows.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        (r.employee_code || "").toLowerCase().includes(q) ||
        (r.email || "").toLowerCase().includes(q),
    );
  }, [data, search]);

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]}>
          <View style={styles.header}>
            <Pressable onPress={() => router.back()} hitSlop={8}>
              <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
            </Pressable>
            <Text style={styles.h1}>Process salary</Text>
            <View style={{ width: 26 }} />
          </View>
        </SafeAreaView>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Admins only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Process salary</Text>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <KeyboardAwareScrollView bottomOffset={62}
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              if (!processed) return;
              setRefreshing(true);
              runPayroll();
            }}
            tintColor={colors.brandPrimary}
          />
        }
      >
        {/* Intro */}
        <View style={styles.introCard}>
          <View style={styles.introIcon}>
            <Ionicons name="cash-outline" size={20} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.introTitle}>Monthly salary computation</Text>
            <Text style={styles.introSub}>
              Pick a month, optionally filter by company, then hit{" "}
              <Text style={{ fontWeight: "700" }}>Process</Text>. We&apos;ll
              pro-rate each employee&apos;s monthly salary by their present
              days vs. working days.
            </Text>
          </View>
        </View>

        {/* Month picker */}
        <View style={styles.monthBar} testID="payroll-month-bar">
          <Pressable onPress={goPrev} style={styles.arrowBtn} hitSlop={8} testID="payroll-month-prev">
            <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={styles.monthCenter}>
            <Text style={styles.monthTxt} testID="payroll-month-label">{monthLabel}</Text>
            <Text style={styles.monthSub}>Payroll month</Text>
          </View>
          <Pressable
            onPress={goNext}
            style={[styles.arrowBtn, !canGoNext && styles.arrowBtnDisabled]}
            hitSlop={8}
            disabled={!canGoNext}
            testID="payroll-month-next"
          >
            <Ionicons
              name="chevron-forward"
              size={22}
              color={canGoNext ? colors.onSurface : colors.onSurfaceTertiary}
            />
          </Pressable>
        </View>

        {isSuper && (
          <View style={{ marginBottom: spacing.md }}>
            <CompanyPicker
              testID="payroll-company-picker"
              value={companyFilter}
              onChange={setCompanyFilter}
              companies={companies}
              label=""
              compact={false}
            />
          </View>
        )}

        <Pressable
          onPress={runPayroll}
          disabled={loading}
          style={[styles.processBtn, loading && { opacity: 0.7 }]}
          testID="payroll-process-btn"
        >
          {loading ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <>
              <Ionicons name="calculator-outline" size={18} color="#fff" />
              <Text style={styles.processTxt}>
                {processed ? "Re-process" : "Process"} salary for {monthLabel}
              </Text>
            </>
          )}
        </Pressable>

        {/* Result */}
        {processed && data && (
          <>
            <View style={styles.kpiRow}>
              <View style={styles.kpi}>
                <Text style={styles.kpiValue}>{data.totals.employees}</Text>
                <Text style={styles.kpiLabel}>Employees</Text>
              </View>
              <View style={styles.kpi}>
                <Text style={styles.kpiValue}>{fmtHours(data.totals.total_hours)}</Text>
                <Text style={styles.kpiLabel}>Total hours</Text>
              </View>
              <View style={[styles.kpi, styles.kpiAccent]}>
                <Text style={[styles.kpiValue, { color: colors.brandPrimary }]}>
                  {fmtCurrency(data.totals.gross_total)}
                </Text>
                <Text style={styles.kpiLabel}>Gross total</Text>
              </View>
            </View>

            {data.rows.length === 0 ? (
              <View style={styles.empty} testID="payroll-empty">
                <Ionicons name="people-outline" size={40} color={colors.onSurfaceTertiary} />
                <Text style={styles.emptyT}>No employees in scope</Text>
                <Text style={styles.emptyS}>
                  Add or approve employees for this company first.
                </Text>
              </View>
            ) : (
              <>
                {/* Email actions */}
                <EmailReportBar
                  year={data.year}
                  month={data.month}
                  companyId={
                    isSuper && companyFilter !== "all" ? companyFilter : undefined
                  }
                />

                <View style={styles.searchBox}>
                  <Ionicons name="search" size={14} color={colors.onSurfaceTertiary} />
                  <TextSearch value={search} onChange={setSearch} />
                </View>

                {filtered.map((row) => (
                  <EmployeeCard
                    key={row.user_id}
                    row={row}
                    onPress={() =>
                      router.push({
                        pathname: "/payslip",
                        params: {
                          user_id: row.user_id,
                          year: String(data.year),
                          month: String(data.month),
                        },
                      })
                    }
                  />
                ))}
              </>
            )}
          </>
        )}

        {!processed && (
          <View style={styles.hint}>
            <Text style={styles.hintTxt}>
              Tap <Text style={{ fontWeight: "700" }}>Process</Text> to compute
              this month&apos;s attendance-based salary.
            </Text>
          </View>
        )}

        <View style={{ height: 40 }} />
      </KeyboardAwareScrollView>
    </View>
  );
}

/**
 * Inline "Email report" bar that lets Employer pick report kind
 * (attendance/salary/combined) + recipients (self/employees/both) and fire
 * the /admin/payroll/email-report endpoint. Kept co-located because it is
 * only used from this screen.
 */
function EmailReportBar({
  year, month, companyId,
}: {
  year: number;
  month: number;
  companyId?: string;
}) {
  const [kind, setKind] = useState<"attendance" | "salary" | "combined">("combined");
  const [recipients, setRecipients] = useState<"self" | "employees" | "both">("self");
  const [sending, setSending] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [result, setResult] = useState<{
    delivered: number; failed: number; sends: any[];
  } | null>(null);

  const showMsg = (msg: string) => {
    if (Platform.OS === "web") window.alert(msg);
    else Alert.alert("Email report", msg);
  };

  const send = async () => {
    setSending(true);
    setResult(null);
    try {
      const body: any = {
        year, month, report_kind: kind, recipients,
      };
      if (companyId) body.company_id = companyId;
      const r = await api<{ delivered: number; failed: number; sends: any[] }>(
        "/admin/payroll/email-report",
        { method: "POST", body },
      );
      setResult(r);
      showMsg(
        r.failed === 0
          ? `Emailed ${r.delivered} recipient${r.delivered > 1 ? "s" : ""} ✓`
          : `Emailed ${r.delivered}, failed ${r.failed}. See details below.`,
      );
    } catch (e: any) {
      showMsg(e?.message || "Send failed");
    } finally {
      setSending(false);
    }
  };

  return (
    <View style={emailStyles.card} testID="email-report-bar">
      <Pressable
        onPress={() => setExpanded((x) => !x)}
        style={emailStyles.head}
      >
        <Ionicons name="mail-outline" size={18} color={colors.brandPrimary} />
        <View style={{ flex: 1 }}>
          <Text style={emailStyles.title}>Email monthly report</Text>
          <Text style={emailStyles.sub}>
            Send attendance / salary sheets via email.
          </Text>
        </View>
        <Ionicons
          name={expanded ? "chevron-up" : "chevron-down"}
          size={20}
          color={colors.onSurfaceTertiary}
        />
      </Pressable>

      {expanded && (
        <View style={emailStyles.body}>
          <Text style={emailStyles.section}>What to include</Text>
          <View style={emailStyles.chipsRow}>
            {(["combined", "attendance", "salary"] as const).map((k) => (
              <Pressable
                key={k}
                onPress={() => setKind(k)}
                style={[emailStyles.chip, kind === k && emailStyles.chipActive]}
                testID={`email-kind-${k}`}
              >
                <Text
                  style={[
                    emailStyles.chipTxt,
                    kind === k && emailStyles.chipTxtActive,
                  ]}
                >
                  {k === "combined"
                    ? "Both (attendance + salary)"
                    : k === "attendance"
                      ? "Punch sheet only"
                      : "Salary only"}
                </Text>
              </Pressable>
            ))}
          </View>

          <Text style={emailStyles.section}>Send to</Text>
          <View style={emailStyles.chipsRow}>
            {(["self", "employees", "both"] as const).map((r) => (
              <Pressable
                key={r}
                onPress={() => setRecipients(r)}
                style={[emailStyles.chip, recipients === r && emailStyles.chipActive]}
                testID={`email-recipients-${r}`}
              >
                <Text
                  style={[
                    emailStyles.chipTxt,
                    recipients === r && emailStyles.chipTxtActive,
                  ]}
                >
                  {r === "self"
                    ? "Me only"
                    : r === "employees"
                      ? "Each employee"
                      : "Me + each employee"}
                </Text>
              </Pressable>
            ))}
          </View>

          <Pressable
            onPress={send}
            disabled={sending}
            style={[emailStyles.sendBtn, sending && { opacity: 0.7 }]}
            testID="email-send-btn"
          >
            {sending ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <>
                <Ionicons name="paper-plane-outline" size={16} color="#fff" />
                <Text style={emailStyles.sendTxt}>Send report</Text>
              </>
            )}
          </Pressable>

          {result && (
            <View style={emailStyles.resultBox}>
              <Text style={emailStyles.resultTitle}>
                {result.delivered} sent{result.failed ? `, ${result.failed} failed` : ""}
              </Text>
              {result.sends.slice(0, 8).map((s, i) => (
                <Text
                  key={i}
                  style={[
                    emailStyles.resultLine,
                    !s.delivered && { color: colors.error },
                  ]}
                >
                  {s.delivered ? "✓" : "✗"} {s.to || "—"}
                  {s.error ? ` — ${String(s.error).slice(0, 60)}` : ""}
                </Text>
              ))}
              {result.sends.length > 8 && (
                <Text style={emailStyles.resultMore}>
                  … and {result.sends.length - 8} more.
                </Text>
              )}
            </View>
          )}
        </View>
      )}
    </View>
  );
}

const emailStyles = StyleSheet.create({
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
    overflow: "hidden",
  },
  head: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 12, paddingHorizontal: 14,
  },
  title: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  sub: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },
  body: { padding: 12, gap: 8, borderTopWidth: 1, borderTopColor: colors.border },
  section: { color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.5 },
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: {
    paddingVertical: 8, paddingHorizontal: 12,
    borderRadius: 999,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { color: colors.onSurfaceSecondary, fontSize: 12, fontWeight: "600" },
  chipTxtActive: { color: "#fff" },
  sendBtn: {
    marginTop: 8,
    backgroundColor: colors.cta,
    borderRadius: radius.md,
    paddingVertical: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  sendTxt: { color: "#fff", fontSize: type.sm, fontWeight: "700" },
  resultBox: {
    marginTop: 8,
    padding: 10,
    backgroundColor: colors.surface,
    borderRadius: radius.sm,
    borderWidth: 1, borderColor: colors.border,
  },
  resultTitle: { color: colors.onSurface, fontSize: 12, fontWeight: "700", marginBottom: 4 },
  resultLine: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 2 },
  resultMore: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 4, fontStyle: "italic" },
});

/**
 * Small inline search input to avoid pulling in a heavier component.
 */
function TextSearch({
  value, onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <TextInput
      testID="payroll-search"
      placeholder="Search by name / code / email"
      placeholderTextColor={colors.onSurfaceTertiary}
      value={value}
      onChangeText={onChange}
      style={{
        flex: 1,
        color: colors.onSurface,
        fontSize: 13,
        paddingVertical: 6,
        marginLeft: 6,
      }}
      returnKeyType="search"
    />
  );
}

function EmployeeCard({ row, onPress }: { row: Row; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      style={styles.empCard}
      testID={`payroll-row-${row.user_id}`}
    >
      <View style={styles.empHead}>
        <View style={styles.avatar}>
          <Text style={styles.avatarTxt}>
            {(row.name || "?").slice(0, 1).toUpperCase()}
          </Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.empName}>{row.name}</Text>
          <Text style={styles.empSub}>
            {row.employee_code || "—"}
            {row.email ? ` · ${row.email}` : ""}
          </Text>
        </View>
        <View style={styles.grossPill}>
          <Text style={styles.grossTxt}>{fmtCurrency(row.gross)}</Text>
        </View>
      </View>
      <View style={styles.empGrid}>
        <MiniStat label="Present" value={`${row.present_days}d`} />
        <MiniStat label="Absent" value={`${row.absent_days}d`} tone="danger" />
        <MiniStat label="Off" value={`${row.off_days}d`} tone="muted" />
        <MiniStat label="Hours" value={fmtHours(row.total_hours)} />
      </View>
      {row.salary_monthly ? (
        <Text style={styles.salaryNote}>
          Base salary: {fmtCurrency(row.salary_monthly)} → pro-rated{" "}
          {row.present_days}/{row.working_days || 0} working days
        </Text>
      ) : (
        <Text style={styles.salaryWarn}>
          ⚠ No base salary set — gross shown as ₹0. Set it from the employee
          record.
        </Text>
      )}
    </Pressable>
  );
}

function MiniStat({
  label, value, tone,
}: {
  label: string; value: string; tone?: "danger" | "muted";
}) {
  return (
    <View style={styles.mini}>
      <Text
        style={[
          styles.miniV,
          tone === "danger" && { color: colors.error },
          tone === "muted" && { color: colors.onSurfaceTertiary },
        ]}
      >
        {value}
      </Text>
      <Text style={styles.miniL}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { fontSize: type.lg, color: colors.onSurface, fontWeight: "700", flex: 1, textAlign: "center" },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xl },

  introCard: {
    flexDirection: "row", gap: 10,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md, padding: spacing.md,
    marginBottom: spacing.md,
  },
  introIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.surface,
    alignItems: "center", justifyContent: "center",
  },
  introTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  introSub: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 4, lineHeight: 17 },

  monthBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    paddingVertical: 10, paddingHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  arrowBtn: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface,
  },
  arrowBtnDisabled: { opacity: 0.4 },
  monthCenter: { alignItems: "center", flex: 1 },
  monthTxt: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  monthSub: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },

  processBtn: {
    backgroundColor: colors.cta,
    borderRadius: radius.md,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    marginBottom: spacing.md,
  },
  processTxt: { color: "#fff", fontSize: type.base, fontWeight: "700" },

  hint: {
    marginTop: spacing.md,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
    alignItems: "center",
  },
  hintTxt: { color: colors.onSurfaceSecondary, fontSize: type.sm, textAlign: "center" },

  kpiRow: { flexDirection: "row", gap: 8, marginTop: spacing.md, marginBottom: spacing.md },
  kpi: {
    flex: 1,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    alignItems: "center",
  },
  kpiAccent: { backgroundColor: colors.brandTertiary, borderColor: colors.brandPrimary },
  kpiValue: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800" },
  kpiLabel: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2, fontWeight: "600" },

  searchBox: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: 10,
    marginBottom: spacing.sm,
  },

  empty: { alignItems: "center", gap: 8, paddingVertical: 40 },
  emptyT: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  emptyS: { color: colors.onSurfaceTertiary, fontSize: type.sm },

  empCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
    marginBottom: 10,
  },
  empHead: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 8 },
  avatar: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  avatarTxt: { color: "#fff", fontSize: 15, fontWeight: "800" },
  empName: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  empSub: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },
  grossPill: {
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: 999,
  },
  grossTxt: { color: "#fff", fontSize: 13, fontWeight: "800" },

  empGrid: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 4,
  },
  mini: { flex: 1, alignItems: "center" },
  miniV: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  miniL: { color: colors.onSurfaceTertiary, fontSize: 10, marginTop: 2, fontWeight: "600" },

  salaryNote: {
    marginTop: 10,
    color: colors.onSurfaceSecondary,
    fontSize: 11,
    fontStyle: "italic",
  },
  salaryWarn: {
    marginTop: 10,
    color: colors.warning || "#B45309",
    fontSize: 11,
    fontWeight: "600",
  },

  forb: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  forbT: { color: colors.onSurface, fontSize: type.lg, fontWeight: "600" },
});
