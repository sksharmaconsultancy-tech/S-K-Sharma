/**
 * Reports Center (Iter 358) — one hub for:
 *  · Payroll Reports (comparison, revision, increment, ex-gratia, incentive,
 *    arrear, F&F, CTC, OT reports)
 *  · Government Registers (wage, fine, deduction, advance, gratuity)
 *  · Audit Reports (payroll/attendance trails, salary changes, activity,
 *    logins, modifications, approvals — super/sub admin only)
 *  · Quick links to registers that already exist elsewhere.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import RegisterTable, {
  ExportButtons,
  shared,
} from "@/src/components/RegisterTable";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";

type Kind = { kind: string; title: string; group: string };

const EXISTING = [
  { title: "Salary Register", route: "/salary-register" },
  { title: "PF Contribution (Higher PF / VPF)", route: "/pf-contribution-report" },
  { title: "Yearly Payroll Register", route: "/payroll-register" },
  { title: "Bonus Registers (A, B, D)", route: "/bonus-registers" },
  { title: "Labour Statistics & HR Analytics", route: "/labour-statistics" },
  { title: "Annual Returns", route: "/annual-returns" },
  { title: "Factory & Boilers Registers", route: "/factory-compliance" },
];

const GROUP_BASE: Record<string, string> = {
  payroll: "/admin/payroll-reports",
  govt: "/admin/govt-registers",
  audit: "/admin/audit-reports",
};
// which reports need month vs FY params
const FY_KINDS = new Set([
  "salary-revision",
  "increment",
  "ex-gratia",
  "incentive",
  "arrear",
  "full-and-final",
  "ot-cost-analysis",
]);
// Iter 433 (user request) — employee picker (single/multiple/all)
const EMP_KINDS = new Set([
  "full-and-final",
  "ot-cost-analysis",
  "gratuity-register",
]);
// Iter 433 (user request) — Daily / Periodic (date range) instead of month
const DATE_KINDS = new Set(["ot-daily", "ot-department"]);
// Iter 433 (user request) — Month wise / Periodic month range
const MONTH_RANGE_KINDS = new Set(["fine-register"]);

type EmpLite = { user_id: string; name?: string; employee_code?: string };

export default function ReportsCenterScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [kinds, setKinds] = useState<Kind[]>([]);
  const [sel, setSel] = useState<Kind | null>(null);
  const [month, setMonth] = useState(() =>
    new Date().toISOString().slice(0, 7),
  );
  const [monthB, setMonthB] = useState("");
  const [monthTo, setMonthTo] = useState(""); // fine-register periodic
  const [fineMode, setFineMode] = useState<"month" | "periodic">("month");
  const [otMode, setOtMode] = useState<"daily" | "periodic">("daily");
  const [dateFrom, setDateFrom] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [dateTo, setDateTo] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [emps, setEmps] = useState<EmpLite[]>([]);
  const [selEmps, setSelEmps] = useState<string[]>([]);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const companyId =
    user?.role === "company_admin" ? user.company_id : selectedCompanyId;
  const isSuper = ["super_admin", "sub_admin"].includes(user?.role || "");

  useEffect(() => {
    (async () => {
      const all: Kind[] = [];
      try {
        const p = await api<any>("/admin/payroll-reports/list");
        (p.reports || []).forEach((r: any) =>
          all.push({ ...r, group: "payroll" }),
        );
      } catch {}
      try {
        const g = await api<any>("/admin/govt-registers/list");
        (g.registers || []).forEach((r: any) =>
          all.push({ ...r, group: "govt" }),
        );
      } catch {}
      if (isSuper) {
        try {
          const a = await api<any>("/admin/audit-reports/list");
          (a.reports || []).forEach((r: any) =>
            all.push({ ...r, group: "audit" }),
          );
        } catch {}
      }
      setKinds(all);
      setSel(all[0] || null);
    })();
  }, [isSuper]);

  const fy = useMemo(() => {
    const y = Number(month.slice(0, 4));
    return Number(month.slice(5, 7)) >= 4 ? y : y - 1;
  }, [month]);

  // Iter 433 — employee list for the single/multiple/all picker
  useEffect(() => {
    if (!companyId) return;
    (async () => {
      try {
        const r = await api<{ employees: EmpLite[] }>(
          `/admin/employees?company_id=${companyId}`,
        );
        setEmps(r.employees || []);
      } catch {
        setEmps([]);
      }
    })();
    setSelEmps([]);
  }, [companyId]);

  const qs = useCallback(() => {
    if (!sel) return "";
    const p = new URLSearchParams();
    if (sel.group !== "audit") p.append("company_id", companyId || "");
    if (sel.group === "audit") p.append("limit", "200");
    else if (DATE_KINDS.has(sel.kind)) {
      p.append("month", month);
      p.append("from_date", dateFrom);
      p.append("to_date", otMode === "daily" ? dateFrom : dateTo);
    } else if (FY_KINDS.has(sel.kind)) {
      p.append("fy_start_year", String(fy));
    } else {
      p.append("month", month);
      if (sel.kind === "salary-comparison" && monthB)
        p.append("month_b", monthB);
      if (
        MONTH_RANGE_KINDS.has(sel.kind) &&
        fineMode === "periodic" &&
        /^\d{4}-\d{2}$/.test(monthTo)
      )
        p.append("month_to", monthTo);
    }
    if (EMP_KINDS.has(sel.kind) && selEmps.length)
      p.append("employee_ids", selEmps.join(","));
    return p.toString();
  }, [
    sel,
    companyId,
    month,
    monthB,
    monthTo,
    fineMode,
    otMode,
    dateFrom,
    dateTo,
    selEmps,
    fy,
  ]);

  const load = useCallback(async () => {
    if (!sel || (!companyId && sel.group !== "audit")) return;
    if (!/^\d{4}-\d{2}$/.test(month)) return;
    setLoading(true);
    try {
      setData(await api<any>(`${GROUP_BASE[sel.group]}/${sel.kind}?${qs()}`));
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [sel, companyId, month, qs]);

  useEffect(() => {
    void load();
  }, [load]);

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role))
    return <Redirect href="/" />;

  const groups: [string, string][] = [
    ["payroll", "Payroll Reports"],
    ["govt", "Government Registers"],
    ["audit", "Audit Reports"],
  ];

  return (
    <SafeAreaView style={shared.safe} edges={["top"]}>
      <View style={shared.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="rc-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={shared.headerTitle}>Report Hub</Text>
        {sel ? (
          <ExportButtons
            basePath={`${GROUP_BASE[sel.group]}/${sel.kind}?${qs()}`}
            fileBase={sel.kind}
          />
        ) : (
          <View style={{ width: 40 }} />
        )}
      </View>
      <ScrollView contentContainerStyle={{ padding: 12 }}>
        {groups.map(([gk, glabel]) => {
          const items = kinds.filter((k) => k.group === gk);
          if (!items.length) return null;
          return (
            <View key={gk} style={{ marginBottom: 8 }}>
              <Text style={[shared.cardTitle, { marginBottom: 6 }]}>
                {glabel}
              </Text>
              <View style={shared.tabs}>
                {items.map((k) => (
                  <Pressable
                    key={k.kind}
                    onPress={() => setSel(k)}
                    style={[
                      shared.tab,
                      sel?.kind === k.kind && shared.tabActive,
                    ]}
                    testID={`rc-${k.kind}`}
                  >
                    <Text
                      style={[
                        shared.tabTxt,
                        sel?.kind === k.kind && shared.tabTxtActive,
                      ]}
                    >
                      {k.title}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
          );
        })}

        <View style={{ marginBottom: 8 }}>
          <Text style={[shared.cardTitle, { marginBottom: 6 }]}>
            Already Available (open page)
          </Text>
          <View style={shared.tabs}>
            {EXISTING.map((e) => (
              <Pressable
                key={e.route}
                onPress={() => router.push(e.route as any)}
                style={[shared.tab, { borderStyle: "dashed" }]}
              >
                <Text style={shared.tabTxt}>↗ {e.title}</Text>
              </Pressable>
            ))}
          </View>
        </View>

        {sel && sel.group !== "audit" && DATE_KINDS.has(sel.kind) && (
          <View style={{ marginBottom: 10 }}>
            <View style={[shared.row, { marginBottom: 6 }]}>
              {(["daily", "periodic"] as const).map((m) => (
                <Pressable
                  key={m}
                  onPress={() => setOtMode(m)}
                  style={[shared.tab, otMode === m && shared.tabActive]}
                  testID={`rc-otmode-${m}`}
                >
                  <Text
                    style={[
                      shared.tabTxt,
                      otMode === m && shared.tabTxtActive,
                    ]}
                  >
                    {m === "daily" ? "Daily" : "Periodic"}
                  </Text>
                </Pressable>
              ))}
            </View>
            <View style={shared.row}>
              <Text style={shared.meta}>
                {otMode === "daily" ? "Date:" : "From:"}
              </Text>
              <TextInput
                style={shared.input}
                value={dateFrom}
                onChangeText={setDateFrom}
                placeholder="YYYY-MM-DD"
                testID="rc-date-from"
              />
              {otMode === "periodic" && (
                <>
                  <Text style={shared.meta}>To:</Text>
                  <TextInput
                    style={shared.input}
                    value={dateTo}
                    onChangeText={setDateTo}
                    placeholder="YYYY-MM-DD"
                    testID="rc-date-to"
                  />
                </>
              )}
            </View>
          </View>
        )}

        {sel && sel.group !== "audit" && !DATE_KINDS.has(sel.kind) && (
          <View style={{ marginBottom: 10 }}>
            {MONTH_RANGE_KINDS.has(sel.kind) && (
              <View style={[shared.row, { marginBottom: 6 }]}>
                {(["month", "periodic"] as const).map((m) => (
                  <Pressable
                    key={m}
                    onPress={() => setFineMode(m)}
                    style={[shared.tab, fineMode === m && shared.tabActive]}
                    testID={`rc-finemode-${m}`}
                  >
                    <Text
                      style={[
                        shared.tabTxt,
                        fineMode === m && shared.tabTxtActive,
                      ]}
                    >
                      {m === "month" ? "Month wise" : "Periodic"}
                    </Text>
                  </Pressable>
                ))}
              </View>
            )}
            <View style={shared.row}>
              <Text style={shared.meta}>
                {FY_KINDS.has(sel.kind)
                  ? `FY ${fy}-${String(fy + 1).slice(-2)} (from month)`
                  : MONTH_RANGE_KINDS.has(sel.kind) &&
                      fineMode === "periodic"
                    ? "From Month"
                    : "Month"}
                :
              </Text>
              <TextInput
                style={shared.input}
                value={month}
                onChangeText={setMonth}
                placeholder="YYYY-MM"
                testID="rc-month"
              />
              {MONTH_RANGE_KINDS.has(sel.kind) && fineMode === "periodic" && (
                <>
                  <Text style={shared.meta}>To Month:</Text>
                  <TextInput
                    style={shared.input}
                    value={monthTo}
                    onChangeText={setMonthTo}
                    placeholder="YYYY-MM"
                    testID="rc-month-to"
                  />
                </>
              )}
              {sel.kind === "salary-comparison" && (
                <>
                  <Text style={shared.meta}>Compare with:</Text>
                  <TextInput
                    style={shared.input}
                    value={monthB}
                    onChangeText={setMonthB}
                    placeholder="prev month (auto)"
                    testID="rc-month-b"
                  />
                </>
              )}
            </View>
          </View>
        )}

        {sel && EMP_KINDS.has(sel.kind) && (
          <View style={{ marginBottom: 10 }}>
            <Text style={[shared.meta, { marginBottom: 6 }]}>
              Employees ({selEmps.length ? `${selEmps.length} selected` : "All"}
              ):
            </Text>
            <View style={shared.tabs}>
              <Pressable
                onPress={() => setSelEmps([])}
                style={[shared.tab, !selEmps.length && shared.tabActive]}
                testID="rc-emp-all"
              >
                <Text
                  style={[
                    shared.tabTxt,
                    !selEmps.length && shared.tabTxtActive,
                  ]}
                >
                  All Employees
                </Text>
              </Pressable>
              {emps.map((e) => {
                const on = selEmps.includes(e.user_id);
                return (
                  <Pressable
                    key={e.user_id}
                    onPress={() =>
                      setSelEmps((prev) =>
                        on
                          ? prev.filter((x) => x !== e.user_id)
                          : [...prev, e.user_id],
                      )
                    }
                    style={[shared.tab, on && shared.tabActive]}
                    testID={`rc-emp-${e.user_id}`}
                  >
                    <Text style={[shared.tabTxt, on && shared.tabTxtActive]}>
                      {e.employee_code ? `${e.employee_code} · ` : ""}
                      {e.name || e.user_id}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        )}

        {loading && <ActivityIndicator style={{ marginVertical: 24 }} />}
        {!loading && data && sel && (
          <View style={shared.card}>
            <Text style={shared.cardTitle}>
              {data.title}
              {data.subtitle ? ` — ${data.subtitle}` : ""}
            </Text>
            {!data.rows?.length && data.empty_note ? (
              <Text
                style={{
                  textAlign: "center",
                  paddingVertical: 32,
                  fontSize: 15,
                  fontWeight: "700",
                  color: colors.onSurfaceSecondary,
                }}
                testID="rc-empty-note"
              >
                {data.empty_note}
              </Text>
            ) : (
              <RegisterTable
                columns={data.columns}
                rows={data.rows}
                totals={data.totals}
              />
            )}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
