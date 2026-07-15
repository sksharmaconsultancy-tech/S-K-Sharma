/**
 * Actual Salary Process (Iter 84) — Web Portal only.
 *
 * A 20-column inline-editable data grid that computes payroll using the
 * formulas agreed with the client:
 *
 *   Basic Salary    = Basic × (P Days / Month Days)
 *   W.Basic Salary  = Basic × P Hours / (Month Days × Duty HRS)
 *   Total Gross     = W.Basic Salary + Oth. Allo.
 *   EPF / ESI       = SYNCED from the Compliance Salary run for the same
 *                     month + firm (0 until compliance is processed).
 *   Net Pay         = Total Gross − (EPF + ESI + Adv + TDS)
 *
 * Attendance Source Toggle:
 *   • "Biometric" → P Days & P Hours are fetched from the monthly grid
 *     and locked (read-only tokens in the grid).
 *   • "Manual"    → P Days & P Hours default to 0 and admins can type
 *     them in-line.
 *
 * Save Behavior: Both — every field edit auto-saves via PATCH, and the
 * admin can tap "Finalize Run" to freeze the batch (subsequent edits
 * return 409).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ActivityIndicator,
  ScrollView,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { confirmYesNo } from "@/src/utils/confirm";
import { useLiveSync } from "@/src/api/live-sync";
import { useAuth } from "@/src/context/AuthContext";
import { useOnRefresh } from "@/src/context/RefreshBusContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import MonthPicker from "@/src/components/MonthPicker";
import { colors, radius, spacing, type } from "@/src/theme";
import MasterSelect from "@/src/components/MasterSelect";

/* ------------------------------------------------------------------- */
/*  Types                                                              */
/* ------------------------------------------------------------------- */

type AttendanceSource = "biometric" | "manual";

type ActualRow = {
  user_id: string;
  employee_code?: string | null;
  name?: string | null;
  father_name?: string | null;
  designation?: string | null;
  employee_type?: string | null;
  is_onroll?: boolean;
  duty_hrs: number;
  basic: number;
  p_days: number;
  p_hours: number;
  oth_allo: number;
  adv: number;
  tds: number;
  basic_salary: number;
  w_basic_salary: number;
  total_gross: number;
  epf: number;
  esi: number;
  net_pay: number;
};

type ActualRun = {
  run_id: string;
  run_type: "actual";
  month: string;
  month_days: number;
  default_month_days: number;
  attendance_source: AttendanceSource;
  company_id?: string | null;
  employee_type?: string | null;
  rows: ActualRow[];
  totals: Record<string, number>;
  employees_count: number;
  finalized?: boolean;
  finalized_at?: string;
  generated_at?: string;
};

type PastRunSummary = {
  run_id: string;
  month: string;
  employees_count: number;
  totals?: Record<string, number>;
  attendance_source?: AttendanceSource;
  run_type?: string;
  finalized?: boolean;
  generated_at?: string;
  // Iter 85 — Audit fields exposed by /admin/salary-runs.
  generated_by_name?: string;
  generated_by_role?: string;
  finalized_at?: string;
  finalized_by_name?: string;
};

/* ------------------------------------------------------------------- */
/*  Small helpers                                                      */
/* ------------------------------------------------------------------- */

function currentMonth(): string {
  // Iter 126h — salary is processed for the PREVIOUS month by default.
  const d = new Date();
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function fmtInr(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "0";
  // User directive — plain numbers, NO thousands separators (commas).
  return String(Math.round(n));
}

function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "0";
  return Number(n).toFixed(digits);
}

/** Pure client-side re-compute (mirrors backend so edits feel instant
 *  even before the auto-save PATCH round-trips). Salary-mode aware
 *  per Iter 85 pt 6. */
function computeRow(r: ActualRow, monthDays: number): ActualRow {
  const md = Math.max(1, Math.floor(monthDays || 30));
  const mode = (r as any).salary_mode || "monthly";
  let basicSalary: number;
  let wBasic: number;
  if (mode === "daily") {
    basicSalary = r.basic * r.p_days;
    wBasic = r.duty_hrs > 0 ? (r.basic * r.p_hours) / r.duty_hrs : 0;
  } else if (mode === "hourly") {
    basicSalary = r.basic * r.p_hours;
    wBasic = basicSalary;
  } else {
    basicSalary = r.basic * (r.p_days / md);
    const denomHrs = md * (r.duty_hrs || 0);
    wBasic = denomHrs > 0 ? (r.basic * r.p_hours) / denomHrs : 0;
  }
  const totalGross = wBasic + r.oth_allo;
  // Iter 96q — PF (EPF) & ESIC are NOT computed here. They are SYNCED from
  // the matching Compliance Salary run by the backend (0 when compliance
  // hasn't been processed for this month/firm). We simply carry the row's
  // values through and deduct them from Net Pay.
  const epf = Number(r.epf) || 0;
  const esi = Number(r.esi) || 0;
  const net = totalGross - (epf + esi + r.adv + r.tds);
  return {
    ...r,
    basic_salary: Math.round(basicSalary * 100) / 100,
    w_basic_salary: Math.round(wBasic * 100) / 100,
    total_gross: Math.round(totalGross * 100) / 100,
    epf: Math.round(epf * 100) / 100,
    esi: Math.round(esi * 100) / 100,
    net_pay: Math.round(net * 100) / 100,
  };
}

function sumTotals(rows: ActualRow[]): Record<string, number> {
  const keys: (keyof ActualRow)[] = [
    "basic_salary", "w_basic_salary", "total_gross",
    "epf", "esi", "adv", "tds", "net_pay",
  ];
  const out: Record<string, number> = {};
  for (const k of keys) {
    out[k as string] = Math.round(
      rows.reduce((s, r) => s + (Number(r[k]) || 0), 0) * 100,
    ) / 100;
  }
  return out;
}

/* ------------------------------------------------------------------- */
/*  Screen                                                             */
/* ------------------------------------------------------------------- */

export default function ActualSalaryProcessScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin =
    user?.role === "super_admin" ||
    user?.role === "sub_admin" ||
    user?.role === "company_admin";
  const {
    selectedCompanyId,
    setSelectedCompanyId,
    companies: allCompanies,
  } = useSelectedCompany();

  // ---- Config state ----
  const [month, setMonth] = useState<string>(currentMonth());
  const [monthDaysOverride, setMonthDaysOverride] = useState<string>("");
  const [empType, setEmpType] = useState<string>("all");
  const [rollFilter, setRollFilter] = useState<"all" | "on" | "off">("all");
  const [attendanceSource, setAttendanceSource] = useState<AttendanceSource>("biometric");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<ActualRun | null>(null);

  // User directive — changing the FIRM must fully reset the form so the
  // previous company's run/employees never linger on screen.
  const prevCidRef = useRef<string | null>(null);
  useEffect(() => {
    if (prevCidRef.current && prevCidRef.current !== selectedCompanyId) {
      setRun(null);
      setEmpType("all");
    }
    prevCidRef.current = selectedCompanyId;
  }, [selectedCompanyId]);
  const [finalizing, setFinalizing] = useState(false);
  const [savingRow, setSavingRow] = useState<string | null>(null);

  const showMsg = (msg: string, title = "Salary Process") => {
    if (Platform.OS === "web") globalThis.alert(msg);
    else Alert.alert(title, msg);
  };

  /* ----- Past runs list moved to Utilities → Past Salary Runs (Iter 91) ----- */
  const loadRuns = useCallback(async () => {}, []);

  useEffect(() => {
    if (isAdmin) loadRuns();
  }, [isAdmin, loadRuns]);
  useOnRefresh(() => { if (isAdmin) loadRuns(); });

  useLiveSync(selectedCompanyId, (ev) => {
    if (ev?.type?.startsWith("salary.run.") && isAdmin) loadRuns();
  });

  /* ----- Generate a new run ----- */
  const generate = async () => {
    if (busy) return;
    // Iter 85 (fix) — Super Admin must pick a firm from the top bar
    // before generating. Without a firm scope we can't fetch the
    // biometric grid, and cross-firm compliance math is undefined.
    if (!selectedCompanyId && (user?.role === "super_admin" || user?.role === "sub_admin")) {
      showMsg("Please select a firm from the list above before generating the salary process.");
      return;
    }
    // Iter 91 — Employee Type / Group is REQUIRED after choosing
    // On-roll / Off-roll. Processing always targets one type.
    if (!empType || empType === "all") {
      showMsg("Please select an Employee Type / Group (after choosing On-roll / Off-roll) before generating.");
      return;
    }
    setBusy(true);
    try {
      const body: any = {
        month,
        attendance_source: attendanceSource,
      };
      if (selectedCompanyId) body.company_id = selectedCompanyId;
      if (monthDaysOverride.trim()) body.month_days = Number(monthDaysOverride);
      if (empType !== "all") body.employee_type = empType;
      if (rollFilter !== "all") body.is_onroll = rollFilter === "on";

      // Iter 129e (user directive) — if a run for this firm + month already
      // exists, ask before reprocessing. "No" reloads the page unchanged.
      try {
        const prev = await api<{ runs: any[] }>("/admin/salary-runs");
        const existing = (prev.runs || []).find(
          (r) => r.month === month && (!selectedCompanyId || r.company_id === selectedCompanyId),
        );
        if (existing) {
          if (existing.finalized) {
            showMsg(
              "This month's salary is already FINALIZED for this firm — it cannot be processed again. Unlock (de-finalize) it first.",
            );
            setBusy(false);
            return;
          }
          const ok = await confirmYesNo(
            "This salary was already processed for this firm & month.\nDo you want to REPROCESS this salary again?",
          );
          if (!ok) {
            setBusy(false);
            if (Platform.OS === "web") window.location.reload();
            return;
          }
        }
      } catch {
        // list unavailable — proceed without the guard
      }

      const r = await api<{ run: ActualRun }>("/admin/actual-salary-process", {
        method: "POST",
        body,
      });
      setRun(r.run);
      await loadRuns();
      if ((r.run.employees_count ?? 0) === 0) {
        showMsg(
          "No employees matched the current filter.\n\n" +
          "• Check that the selected firm has active employees for this month\n" +
          "• Verify their date-of-joining is on/before the run month\n" +
          "• Try clearing the Employee Type filter",
        );
      } else {
        showMsg(
          `Run created for ${r.run.employees_count} employees. Net Pay: ${fmtInr(r.run.totals?.net_pay)}`,
        );
      }
    } catch (e: any) {
      showMsg(e?.message || "Failed to create salary run");
    } finally {
      setBusy(false);
    }
  };

  /* ----- Open a past run ----- */
  /* ----- Open a past run ----- */
  const openPastRun = async (r: PastRunSummary) => {
    try {
      const j = await api<{ run: ActualRun }>(`/admin/salary-runs/${r.run_id}`);
      setRun(j.run);
      setMonth(j.run.month);
      setMonthDaysOverride(String(j.run.month_days));
      setEmpType(j.run.employee_type || "all");
      setAttendanceSource(j.run.attendance_source || "biometric");
    } catch (e: any) {
      showMsg(e?.message || "Failed to open run");
    }
  };

  // Iter 91 — deep link from Utilities → Past Salary Runs (?run_id=…)
  const params = useLocalSearchParams<{ run_id?: string }>();
  useEffect(() => {
    if (params.run_id && isAdmin) {
      openPastRun({ run_id: String(params.run_id) } as PastRunSummary);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.run_id, isAdmin]);

  /* ----- Auto-save (debounced) ----- */
  const patchTimersRef = useRef<Record<string, any>>({});
  const pendingRef = useRef<Record<string, Partial<ActualRow>>>({});

  const scheduleSave = useCallback((user_id: string, changes: Partial<ActualRow>) => {
    if (!run || run.finalized) return;
    // Accumulate changes for this user then flush after a short debounce.
    pendingRef.current[user_id] = { ...(pendingRef.current[user_id] || {}), ...changes };
    if (patchTimersRef.current[user_id]) clearTimeout(patchTimersRef.current[user_id]);
    patchTimersRef.current[user_id] = setTimeout(async () => {
      const changesToSend = pendingRef.current[user_id];
      pendingRef.current[user_id] = {};
      if (!changesToSend || Object.keys(changesToSend).length === 0) return;
      setSavingRow(user_id);
      try {
        const body: any = { user_id, ...changesToSend };
        const r = await api<{ row: ActualRow; totals: Record<string, number> }>(
          `/admin/actual-salary-process/${run.run_id}/row`,
          { method: "PATCH", body },
        );
        setRun((prev) => {
          if (!prev) return prev;
          const rows = prev.rows.map(x => x.user_id === user_id ? r.row : x);
          return { ...prev, rows, totals: r.totals };
        });
      } catch (e: any) {
        showMsg(e?.message || "Auto-save failed");
      } finally {
        setSavingRow(null);
      }
    }, 450);
  }, [run]);

  /* ----- Local edit handler (updates UI immediately, then debounced save) ----- */
  const editField = useCallback((
    user_id: string,
    field: keyof ActualRow,
    value: number,
  ) => {
    setRun((prev) => {
      if (!prev) return prev;
      const rows = prev.rows.map(r => {
        if (r.user_id !== user_id) return r;
        const patched: ActualRow = { ...r, [field]: value } as ActualRow;
        return computeRow(patched, prev.month_days);
      });
      const totals = sumTotals(rows);
      return { ...prev, rows, totals };
    });
    scheduleSave(user_id, { [field]: value } as Partial<ActualRow>);
  }, [scheduleSave]);

  /* ----- Finalize the run ----- */
  const finalize = async () => {
    if (!run || finalizing) return;
    if (Platform.OS === "web") {
      const ok = globalThis.confirm(
        `Finalize this run? After finalizing, no further row edits are allowed.`,
      );
      if (!ok) return;
    }
    setFinalizing(true);
    try {
      await api(`/admin/actual-salary-process/${run.run_id}/finalize`, {
        method: "POST",
      });
      setRun((prev) => prev ? { ...prev, finalized: true } : prev);
      await loadRuns();
      showMsg("Run finalized ✓");
    } catch (e: any) {
      showMsg(e?.message || "Finalize failed");
    } finally {
      setFinalizing(false);
    }
  };

  /* ----- CSV export (client-side) ----- */
  const exportCsv = () => {
    if (!run) return;
    const header = [
      "SN", "Code", "Name", "Father", "Designation", "Type", "Roll", "Duty HRS",
      "Month Days", "P Days", "P Hours", "Basic",
      "Basic Salary", "W.Basic Salary", "Oth. Allo.", "Total Gross",
      "EPF", "ESI", "Adv", "TDS", "Net Pay",
    ];
    const rowsCsv = run.rows.map((r, i) => [
      i + 1,
      r.employee_code || "",
      r.name || "",
      r.father_name || "",
      r.designation || "",
      r.employee_type || "",
      r.is_onroll ? "On" : "Off",
      r.duty_hrs,
      run.month_days,
      r.p_days,
      r.p_hours,
      r.basic,
      r.basic_salary,
      r.w_basic_salary,
      r.oth_allo,
      r.total_gross,
      r.epf,
      r.esi,
      r.adv,
      r.tds,
      r.net_pay,
    ]);
    const escape = (v: any) => {
      const s = String(v ?? "");
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const csv = [header, ...rowsCsv]
      .map(r => r.map(escape).join(","))
      .join("\n");
    if (Platform.OS === "web") {
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `ActualSalary_${run.month}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    }
  };

  /* ================================================================= */
  /*  Render                                                           */
  /* ================================================================= */

  if (!isAdmin) {
    return (
      <View style={styles.root}>
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
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>Actual Salary Process</Text>
            <Text style={styles.hsub}>
              {Platform.OS === "web"
                ? "Web portal · Inline editable payroll grid"
                : "Best used on desktop / web portal"}
            </Text>
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Iter 91 — In-screen firm picker for Super Admin. Shows ALL
            active firms regardless of attendance source. */}
        {user?.role === "super_admin" || user?.role === "sub_admin" ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Select firm</Text>
            <Text style={styles.smallHint}>
              Pick one firm — the salary process runs for its employees only.
            </Text>
            <View style={styles.chipStrip}>
              {(allCompanies || []).map((c) => (
                <TypeChip
                  key={c.company_id}
                  label={c.name || c.company_id}
                  active={selectedCompanyId === c.company_id}
                  onPress={() => setSelectedCompanyId(c.company_id)}
                />
              ))}
              {(allCompanies || []).length === 0 ? (
                <Text style={styles.smallHint}>No firms found.</Text>
              ) : null}
            </View>
          </View>
        ) : null}

        {/* --- Config card --- */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Configure batch</Text>

          <View style={styles.gridRow}>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Month</Text>
              <MonthPicker
                value={month}
                onChange={setMonth}
                allowEmpty={false}
                testID="asp-month"
              />
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Month days (override)</Text>
              <TextInput
                testID="asp-days"
                value={monthDaysOverride}
                onChangeText={setMonthDaysOverride}
                placeholder="Auto (default)"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.input}
                keyboardType="numeric"
              />
            </View>
          </View>

          <View style={styles.gridRow}>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Attendance Source</Text>
              <View style={styles.chipStrip}>
                <TypeChip
                  label="Biometric (auto)"
                  active={attendanceSource === "biometric"}
                  onPress={() => setAttendanceSource("biometric")}
                />
                <TypeChip
                  label="Manual"
                  active={attendanceSource === "manual"}
                  onPress={() => setAttendanceSource("manual")}
                />
              </View>
              <Text style={styles.chipHint}>
                {attendanceSource === "biometric"
                  ? "P Days & P Hours are pre-filled from the attendance grid — you can still edit any row inline before finalizing."
                  : "P Days & P Hours default to 0 — type them in-line per employee."}
              </Text>
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Roll</Text>
              <View style={styles.chipStrip}>
                {(["all", "on", "off"] as const).map((v) => (
                  <TypeChip
                    key={v}
                    label={v === "all" ? "All" : v === "on" ? "On-roll" : "Off-roll"}
                    active={rollFilter === v}
                    onPress={() => setRollFilter(v)}
                  />
                ))}
              </View>
            </View>
          </View>

          <View style={[styles.gridRow, { zIndex: 50 }]}>
            <View style={styles.gridCol}>
              {/* Iter 91 — Dropdown (not chips): the Group master can hold
                  lots of entries, a collapsed dropdown keeps it manageable. */}
              <MasterSelect
                label="Employee Type / Group (required)"
                masterType="group"
                companyId={selectedCompanyId}
                value={empType === "all" ? "" : empType}
                onChange={(v) => setEmpType(v || "all")}
                placeholder="Select employee type / group…"
                testID="asp-emp-type"
              />
            </View>
          </View>

          <Pressable
            testID="asp-generate"
            onPress={generate}
            disabled={busy}
            style={[styles.primaryBtn, busy && { opacity: 0.6 }]}
          >
            {busy ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="cash-outline" size={16} color="#fff" />
                <Text style={styles.primaryBtnTxt}>Salary Process</Text>
              </>
            )}
          </Pressable>
        </View>

        {/* --- Result grid --- */}
        {run ? (
          <ResultGrid
            run={run}
            editField={editField}
            savingRow={savingRow}
            onFinalize={finalize}
            finalizing={finalizing}
            onExportCsv={exportCsv}
          />
        ) : null}

        {/* --- Past runs — moved to Utilities → Past Salary Runs (Iter 91) --- */}
        <Pressable
          onPress={() => router.push("/past-salary-runs")}
          style={styles.pastRow}
          testID="asp-open-past-runs"
        >
          <View style={styles.pastIcon}>
            <Ionicons name="albums-outline" size={18} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.pastTitle}>Past runs</Text>
            <Text style={styles.pastMeta}>
              Open earlier runs from Utilities → Past Salary Runs
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
        </Pressable>

        {/* Iter 96u — Bank Sheet (salary transfer statement) */}
        <Pressable
          onPress={() => router.push("/bank-sheet")}
          style={styles.pastRow}
          testID="asp-open-bank-sheet"
        >
          <View style={styles.pastIcon}>
            <Ionicons name="card-outline" size={18} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.pastTitle}>Bank Sheet</Text>
            <Text style={styles.pastMeta}>
              Salary transfer statement — Net pay from Compliance Salary
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
        </Pressable>

        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

/* ------------------------------------------------------------------- */
/*  Result grid component                                              */
/* ------------------------------------------------------------------- */

const BASE_COL_WIDTHS = {
  sn: 40, code: 80, name: 150, type: 80, roll: 50,
  duty: 70, md: 70, pdays: 70, phours: 80,
  basic: 90, bsalary: 100, wbasic: 100, othallo: 90,
  gross: 100, epf: 80, esi: 80, adv: 80, tds: 80, net: 100,
  actions: 40,
};

function ResultGrid({
  run, editField, savingRow, onFinalize, finalizing, onExportCsv,
}: {
  run: ActualRun;
  editField: (uid: string, field: keyof ActualRow, val: number) => void;
  savingRow: string | null;
  onFinalize: () => void;
  finalizing: boolean;
  onExportCsv: () => void;
}) {
  const readOnly = !!run.finalized;
  // Iter 85 — Biometric lock removed; P Days & P Hours always editable.

  // Iter 127e — AUTO-ADJUST every column to its widest content so nothing
  // is cut off (user request; replaces the wrap-text experiment). Shadows
  // the BASE_COL_WIDTHS minimums.
  const COL_WIDTHS = useMemo(() => {
    const rows = run.rows || [];
    const px = (v: any) => String(v ?? "").length * 7.2 + 20;
    const fit = (base: number, label: string, vals: any[], maxW = 280) => {
      let m = Math.max(base, px(label));
      for (const v of vals) {
        const p = px(v);
        if (p > m) m = p;
      }
      return Math.round(Math.min(maxW, m));
    };
    return {
      ...BASE_COL_WIDTHS,
      code: fit(56, "Code", rows.map((r) => r.employee_code)),
      name: fit(110, "Name", rows.map((r) => r.name)),
      type: fit(56, "Type", rows.map((r) => r.employee_type)),
      duty: fit(56, "Duty HRS", rows.map((r) => fmtNum(r.duty_hrs, 2))),
      pdays: fit(60, "P Days", rows.map((r) => fmtNum(r.p_days, 2))),
      phours: fit(60, "P Hours", rows.map((r) => fmtNum(r.p_hours, 2))),
      basic: fit(72, "Basic", rows.map((r) => fmtInr(r.basic))),
      bsalary: fit(80, "B.Salary", rows.map((r) => fmtInr(r.basic_salary))),
      wbasic: fit(80, "W.Basic", rows.map((r) => fmtInr(r.w_basic_salary))),
      othallo: fit(72, "Oth Allo", rows.map((r) => fmtInr(r.oth_allo))),
      gross: fit(80, "Gross", rows.map((r) => fmtInr(r.total_gross))),
      epf: fit(64, "EPF", rows.map((r) => fmtInr(r.epf))),
      esi: fit(64, "ESI", rows.map((r) => fmtInr(r.esi))),
      adv: fit(64, "Advance", rows.map((r) => fmtInr(r.adv))),
      tds: fit(64, "TDS", rows.map((r) => fmtInr(r.tds))),
      net: fit(80, "Net Pay", rows.map((r) => fmtInr(r.net_pay))),
    };
  }, [run.rows]);

  // Iter 91 — grid keyboard navigation (↑ ↓ ← → / Enter) between cells.
  const cellRefs = useRef<Map<string, any>>(new Map());
  const gridNav = (row: number, col: number, key: string) => {
    let r = row, c = col;
    if (key === "ArrowUp") r -= 1;
    else if (key === "ArrowDown" || key === "Enter") r += 1;
    else if (key === "ArrowLeft") c -= 1;
    else if (key === "ArrowRight") c += 1;
    const el = cellRefs.current.get(`${r}:${c}`);
    el?.focus?.();
  };

  const totalMinWidth = useMemo(
    () => Object.values(COL_WIDTHS).reduce((a, b) => a + b, 0),
    [COL_WIDTHS],
  );

  // Iter 98 — display sorting for the process grid.
  const [sortBy, setSortBy] = useState<string>("");
  const sortRows = (rows: ActualRow[]) => {
    if (!sortBy) return rows;
    const num = (v: any) => Number(v ?? 0);
    const arr = [...rows];
    if (sortBy === "name") arr.sort((a: any, b: any) => String(a.name || "").localeCompare(String(b.name || "")));
    else if (sortBy === "code") arr.sort((a: any, b: any) => num(a.employee_code) - num(b.employee_code));
    else if (sortBy === "net") arr.sort((a: any, b: any) => num(b.net_pay ?? b.net) - num(a.net_pay ?? a.net));
    else if (sortBy === "gross") arr.sort((a: any, b: any) => num(b.total_gross ?? b.gross) - num(a.total_gross ?? a.gross));
    return arr;
  };

  return (
    <View style={styles.card}>
      <View style={styles.rowBetween}>
        <View style={{ flex: 1 }}>
          <Text style={styles.cardTitle}>
            {run.month}  ·  {run.employees_count} employees
            {run.finalized ? "  ·  Finalized 🔒" : "  ·  Draft ✏️"}
          </Text>
          <Text style={styles.smallHint}>
            month_days = {run.month_days}  ·  source = {run.attendance_source}
            {"  ·  "}Net {fmtInr(run.totals?.net_pay)}
            {"  ·  "}EPF {fmtInr(run.totals?.epf)}
            {"  ·  "}ESI {fmtInr(run.totals?.esi)}
          </Text>
        </View>
        <View style={{ flexDirection: "row", gap: 6 }}>
          <ActionBtn icon="download-outline" label="Export CSV" onPress={onExportCsv} />
          {!run.finalized ? (
            <ActionBtn
              icon="lock-closed-outline"
              label="Finalize"
              busy={finalizing}
              onPress={onFinalize}
              primary
            />
          ) : null}
        </View>
      </View>

      {/* Iter 98 — sort chips */}
      <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
        <Text style={{ color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "700" }}>Sort:</Text>
        {[["", "Default"], ["name", "Name"], ["code", "Code"], ["net", "Net ↓"], ["gross", "Gross ↓"]].map(([val, lab]) => (
          <Pressable
            key={val || "d"}
            onPress={() => setSortBy(val)}
            style={{
              paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, borderWidth: 1,
              borderColor: sortBy === val ? colors.brandPrimary : colors.border,
              backgroundColor: sortBy === val ? colors.brandPrimary : colors.surface,
            }}
            testID={`asal-sort-${val || "default"}`}
          >
            <Text style={{ fontSize: 11, fontWeight: "700", color: sortBy === val ? "#fff" : colors.onSurfaceSecondary }}>{lab}</Text>
          </Pressable>
        ))}
      </View>

      <ScrollView horizontal style={{ marginTop: 8 }}>
        <View style={{ minWidth: totalMinWidth }}>
          {/* header */}
          <View style={[styles.tblRow, styles.tblHeader]}>
            <HdrCell w={COL_WIDTHS.sn}>SN</HdrCell>
            <HdrCell w={COL_WIDTHS.code}>Code</HdrCell>
            <HdrCell w={COL_WIDTHS.name} align="left">Name</HdrCell>
            <HdrCell w={COL_WIDTHS.type}>Type</HdrCell>
            <HdrCell w={COL_WIDTHS.roll}>Roll</HdrCell>
            <HdrCell w={COL_WIDTHS.duty} bg={GRP.master}>Duty HRS</HdrCell>
            <HdrCell w={COL_WIDTHS.md} bg={GRP.master}>M.Days</HdrCell>
            <HdrCell w={COL_WIDTHS.pdays} bg={GRP.master}>P Days</HdrCell>
            <HdrCell w={COL_WIDTHS.phours} bg={GRP.master}>P Hours</HdrCell>
            <HdrCell w={COL_WIDTHS.basic} bg={GRP.master}>Basic (Master)</HdrCell>
            <HdrCell w={COL_WIDTHS.bsalary} bg={GRP.calc}>Basic Sal</HdrCell>
            <HdrCell w={COL_WIDTHS.wbasic} bg={GRP.calc}>W.Basic Sal</HdrCell>
            <HdrCell w={COL_WIDTHS.othallo} bg={GRP.calc}>Oth.Allo</HdrCell>
            <HdrCell w={COL_WIDTHS.gross} bg={GRP.calc}>Total Gross</HdrCell>
            <HdrCell w={COL_WIDTHS.epf} bg={GRP.ded}>EPF</HdrCell>
            <HdrCell w={COL_WIDTHS.esi} bg={GRP.ded}>ESI</HdrCell>
            <HdrCell w={COL_WIDTHS.adv} bg={GRP.ded}>Adv</HdrCell>
            <HdrCell w={COL_WIDTHS.tds} bg={GRP.ded}>TDS</HdrCell>
            <HdrCell w={COL_WIDTHS.net}>Net Pay</HdrCell>
            <HdrCell w={COL_WIDTHS.actions}>·</HdrCell>
          </View>

          {sortRows(run.rows).map((r, idx) => {
            // Iter 86 — Row highlight per employee. Strong zebra stripes
            // + a colored left accent bar + bolded Code/Name make each
            // employee row easy to scan across the 20-column grid.
            const isOdd = idx % 2 === 1;
            const accentPalette = [
              colors.brandPrimary,
              "#f59e0b", // amber
              "#10b981", // emerald
              "#3b82f6", // blue
              "#a855f7", // violet
              "#ec4899", // pink
            ];
            const accent = accentPalette[idx % accentPalette.length];
            return (
            <View
              key={r.user_id}
              style={[
                styles.tblRow,
                styles.empRow,
                isOdd ? styles.empRowOdd : styles.empRowEven,
                { borderLeftWidth: 4, borderLeftColor: accent },
              ]}
            >
              <ReadCell w={COL_WIDTHS.sn}>{idx + 1}</ReadCell>
              <View style={{ width: COL_WIDTHS.code, paddingHorizontal: 6, paddingVertical: 4, justifyContent: "center" }}>
                <Text style={[styles.readTxt, styles.empIdent, { textAlign: "center" }]} numberOfLines={1}>
                  {r.employee_code || "—"}
                </Text>
              </View>
              <View style={{ width: COL_WIDTHS.name, paddingHorizontal: 6, paddingVertical: 4, justifyContent: "center" }}>
                <Text style={[styles.readTxt, styles.empIdent, { textAlign: "left" }]} numberOfLines={1}>
                  {r.name || "—"}
                </Text>
              </View>
              <ReadCell w={COL_WIDTHS.type}>{r.employee_type || "—"}</ReadCell>
              <ReadCell w={COL_WIDTHS.roll}>{r.is_onroll ? "On" : "Off"}</ReadCell>

              <ReadCell w={COL_WIDTHS.duty} bg={GRP.master}>
                {fmtNum(r.duty_hrs, 2)}
              </ReadCell>
              <ReadCell w={COL_WIDTHS.md} bg={GRP.master}>{run.month_days}</ReadCell>
              <EditCell
                w={COL_WIDTHS.pdays}
                value={r.p_days}
                onChange={(v) => editField(r.user_id, "p_days", Math.round(v * 2) / 2)}
                disabled={readOnly}
                digits={2}
                gridRow={idx} gridCol={1} cellRefs={cellRefs} onArrow={gridNav} bg={GRP.master}
              />
              <EditCell
                w={COL_WIDTHS.phours}
                value={r.p_hours}
                onChange={(v) => editField(r.user_id, "p_hours", v)}
                disabled={readOnly}
                digits={2}
                gridRow={idx} gridCol={2} cellRefs={cellRefs} onArrow={gridNav} bg={GRP.master}
              />

              <EditCell
                w={COL_WIDTHS.basic}
                value={r.basic}
                onChange={(v) => editField(r.user_id, "basic", v)}
                disabled={readOnly}
                money
                gridRow={idx} gridCol={3} cellRefs={cellRefs} onArrow={gridNav} bg={GRP.master}
              />
              <ReadCell w={COL_WIDTHS.bsalary} bg={GRP.calc}>{fmtInr(r.basic_salary)}</ReadCell>
              <ReadCell w={COL_WIDTHS.wbasic} bg={GRP.calc}>{fmtInr(r.w_basic_salary)}</ReadCell>
              <EditCell
                w={COL_WIDTHS.othallo}
                value={r.oth_allo}
                onChange={(v) => editField(r.user_id, "oth_allo", v)}
                disabled={readOnly}
                money
                gridRow={idx} gridCol={4} cellRefs={cellRefs} onArrow={gridNav} bg={GRP.calc}
              />
              <ReadCell w={COL_WIDTHS.gross} bg={GRP.calc}>{fmtInr(r.total_gross)}</ReadCell>
              <ReadCell w={COL_WIDTHS.epf} bg={GRP.ded}>{fmtInr(r.epf)}</ReadCell>
              <ReadCell w={COL_WIDTHS.esi} bg={GRP.ded}>{fmtInr(r.esi)}</ReadCell>
              <EditCell
                w={COL_WIDTHS.adv}
                value={r.adv}
                onChange={(v) => editField(r.user_id, "adv", v)}
                disabled={readOnly}
                money
                gridRow={idx} gridCol={5} cellRefs={cellRefs} onArrow={gridNav} bg={GRP.ded}
              />
              <EditCell
                w={COL_WIDTHS.tds}
                value={r.tds}
                onChange={(v) => editField(r.user_id, "tds", v)}
                disabled={readOnly}
                money
                gridRow={idx} gridCol={6} cellRefs={cellRefs} onArrow={gridNav} bg={GRP.ded}
              />
              <View style={{ width: COL_WIDTHS.net, paddingHorizontal: 6, paddingVertical: 4, justifyContent: "center" }}>
                <Text style={[styles.readTxt, { textAlign: "right", fontWeight: "700" }]}>
                  {fmtInr(r.net_pay)}
                </Text>
              </View>
              <View style={{ width: COL_WIDTHS.actions, alignItems: "center", justifyContent: "center" }}>
                {savingRow === r.user_id ? (
                  <ActivityIndicator size="small" color={colors.brandPrimary} />
                ) : (
                  <Ionicons name="checkmark" size={12} color={colors.onSurfaceTertiary} />
                )}
              </View>
            </View>
            );
          })}

          {/* Totals row */}
          <View style={[styles.tblRow, { backgroundColor: colors.brandTertiary }]}>
            <ReadCell w={COL_WIDTHS.sn}></ReadCell>
            <ReadCell w={COL_WIDTHS.code}></ReadCell>
            <View style={{ width: COL_WIDTHS.name, paddingHorizontal: 6, paddingVertical: 4 }}>
              <Text style={[styles.readTxt, { fontWeight: "800" }]}>TOTAL</Text>
            </View>
            <ReadCell w={COL_WIDTHS.type}></ReadCell>
            <ReadCell w={COL_WIDTHS.roll}></ReadCell>
            <ReadCell w={COL_WIDTHS.duty}></ReadCell>
            <ReadCell w={COL_WIDTHS.md}></ReadCell>
            <ReadCell w={COL_WIDTHS.pdays}></ReadCell>
            <ReadCell w={COL_WIDTHS.phours}></ReadCell>
            <ReadCell w={COL_WIDTHS.basic}></ReadCell>
            <BoldRead w={COL_WIDTHS.bsalary}>{fmtInr(run.totals?.basic_salary)}</BoldRead>
            <BoldRead w={COL_WIDTHS.wbasic}>{fmtInr(run.totals?.w_basic_salary)}</BoldRead>
            <ReadCell w={COL_WIDTHS.othallo}></ReadCell>
            <BoldRead w={COL_WIDTHS.gross}>{fmtInr(run.totals?.total_gross)}</BoldRead>
            <BoldRead w={COL_WIDTHS.epf}>{fmtInr(run.totals?.epf)}</BoldRead>
            <BoldRead w={COL_WIDTHS.esi}>{fmtInr(run.totals?.esi)}</BoldRead>
            <BoldRead w={COL_WIDTHS.adv}>{fmtInr(run.totals?.adv)}</BoldRead>
            <BoldRead w={COL_WIDTHS.tds}>{fmtInr(run.totals?.tds)}</BoldRead>
            <BoldRead w={COL_WIDTHS.net}>{fmtInr(run.totals?.net_pay)}</BoldRead>
            <View style={{ width: COL_WIDTHS.actions }} />
          </View>
        </View>
      </ScrollView>

      {/* Iter 85 — Biometric-lock hint removed per user request.  P Days
          and P Hours are now ALWAYS editable regardless of attendance
          source. Biometric-derived values are simply pre-filled and the
          admin can override any row. */}
    </View>
  );
}

/* ------------------------------------------------------------------- */
/*  Reusable cells & chips                                             */
/* ------------------------------------------------------------------- */

// Iter 91 — column-group highlight tints: Master salary inputs (blue),
// calculated salary (green), deductions (red) — visually separated.
const GRP = {
  master: "#EFF6FF",
  calc: "#F0FDF4",
  ded: "#FEF2F2",
};

function HdrCell({ w, children, align = "right" as "left" | "right", bg }: any) {
  return (
    <View style={{ width: w, paddingHorizontal: 6, paddingVertical: 6, backgroundColor: bg || "transparent" }}>
      <Text
        style={[
          styles.tblHeaderTxt,
          align === "left" ? styles.alignLeft : styles.alignRight,
          // Light group tints need dark text — white would be invisible.
          bg ? { color: "#1E293B" } : null,
        ]}
        numberOfLines={1}
      >
        {children}
      </Text>
    </View>
  );
}

function ReadCell({ w, children, align = "right" as "left" | "right", bg }: any) {
  return (
    <View style={{ width: w, paddingHorizontal: 6, paddingVertical: 6, justifyContent: "center", backgroundColor: bg || "transparent" }}>
      <Text
        style={[styles.readTxt, align === "left" ? styles.alignLeft : styles.alignRight]}
        numberOfLines={1}
      >
        {children}
      </Text>
    </View>
  );
}

function BoldRead({ w, children }: any) {
  return (
    <View style={{ width: w, paddingHorizontal: 6, paddingVertical: 6 }}>
      <Text style={[styles.readTxt, styles.alignRight, { fontWeight: "800" }]} numberOfLines={1}>
        {children}
      </Text>
    </View>
  );
}

function EditCell({
  w, value, onChange, disabled, money, digits = 2,
  gridRow, gridCol, cellRefs, onArrow, bg,
}: {
  w: number; value: number; onChange: (v: number) => void;
  disabled?: boolean; money?: boolean; digits?: number;
  /** Iter 91 — grid keyboard navigation (web): arrow keys move focus. */
  gridRow?: number; gridCol?: number;
  cellRefs?: React.MutableRefObject<Map<string, any>>;
  onArrow?: (row: number, col: number, key: string) => void;
  bg?: string;
}) {
  const [txt, setTxt] = useState<string>(String(value ?? 0));
  // Iter 91 — while the admin is typing (focused), NEVER overwrite the
  // text from external row recomputes — that made the cell "refresh"
  // mid-edit (e.g. after double-clicking P Hours).
  const focusedRef = useRef(false);

  useEffect(() => {
    if (focusedRef.current) return;
    const parsed = Number(txt);
    if (!Number.isNaN(parsed) && Math.abs(parsed - (value || 0)) < 0.005) return;
    setTxt(money ? String(Math.round(value || 0)) : fmtNum(value, digits));
  }, [value, money, digits]);  // eslint-disable-line react-hooks/exhaustive-deps

  const commit = () => {
    const n = Number(txt);
    if (Number.isNaN(n) || n < 0) {
      setTxt(money ? String(Math.round(value || 0)) : fmtNum(value, digits));
      return;
    }
    onChange(n);
  };

  return (
    <View style={{ width: w, paddingHorizontal: 4, paddingVertical: 4, justifyContent: "center", backgroundColor: bg || "transparent" }}>
      <TextInput
        ref={(el: any) => {
          if (!cellRefs || gridRow === undefined || gridCol === undefined) return;
          const k = `${gridRow}:${gridCol}`;
          if (el) cellRefs.current.set(k, el);
          else cellRefs.current.delete(k);
        }}
        value={txt}
        onChangeText={setTxt}
        onFocus={() => { focusedRef.current = true; }}
        onBlur={() => { focusedRef.current = false; commit(); }}
        onEndEditing={commit}
        onKeyPress={(e: any) => {
          const key = e?.nativeEvent?.key;
          if (
            onArrow &&
            gridRow !== undefined && gridCol !== undefined &&
            ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter"].includes(key)
          ) {
            e.preventDefault?.();
            commit();
            onArrow(gridRow, gridCol, key);
          }
        }}
        editable={!disabled}
        keyboardType="numeric"
        style={[
          styles.editInput,
          disabled && styles.editInputDisabled,
        ]}
      />
    </View>
  );
}

function TypeChip({
  label, active, onPress,
}: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      style={[styles.chip, active && styles.chipActive]}
    >
      <Text style={[styles.chipTxt, active && styles.chipTxtActive]}>{label}</Text>
    </Pressable>
  );
}

function ActionBtn({
  icon, label, onPress, busy, primary,
}: { icon: any; label: string; onPress: () => void; busy?: boolean; primary?: boolean }) {
  return (
    <Pressable
      onPress={onPress}
      disabled={busy}
      style={[
        styles.actionBtn,
        primary && styles.actionBtnPrimary,
        busy && { opacity: 0.6 },
      ]}
    >
      {busy ? (
        <ActivityIndicator size="small" color={primary ? "#fff" : colors.brandPrimary} />
      ) : (
        <>
          <Ionicons name={icon} size={13} color={primary ? "#fff" : colors.brandPrimary} />
          <Text style={[styles.actionBtnTxt, primary && styles.actionBtnTxtPrimary]}>
            {label}
          </Text>
        </>
      )}
    </Pressable>
  );
}

/* ------------------------------------------------------------------- */
/*  Styles                                                             */
/* ------------------------------------------------------------------- */

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    paddingHorizontal: spacing.md,
    height: 52,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
  },
  h1: { ...type.h5, color: colors.onSurface, fontWeight: "700" },
  hsub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },
  scroll: { padding: spacing.md, paddingBottom: 40 },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: { marginTop: 8, color: colors.onSurfaceTertiary, ...type.body },

  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cardTitle: {
    ...type.h6,
    color: colors.onSurface,
    fontWeight: "700",
    marginBottom: 6,
  },
  smallHint: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },

  gridRow: { flexDirection: "row", gap: 10, flexWrap: "wrap", marginBottom: 6 },
  gridCol: { flex: 1, minWidth: 220 },
  label: {
    ...type.tiny,
    color: colors.onSurfaceSecondary,
    fontWeight: "700",
    marginBottom: 4,
    marginTop: 4,
    textTransform: "uppercase",
  },
  input: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.onSurface,
    marginBottom: 4,
    backgroundColor: colors.surface,
  },
  chipStrip: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 4 },
  chipHint: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 2, fontStyle: "italic" },
  chip: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 14,
    borderWidth: 1, borderColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
  chipActive: { borderColor: colors.brandPrimary, backgroundColor: colors.brandPrimary },
  chipTxt: { color: colors.onSurfaceSecondary, fontWeight: "600", fontSize: 12 },
  chipTxtActive: { color: "#fff" },

  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    marginTop: 8,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "700" },

  rowBetween: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 6,
  },
  actionBtn: {
    paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8,
    flexDirection: "row", alignItems: "center", gap: 4,
    borderWidth: 1, borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  actionBtnPrimary: { backgroundColor: colors.brandPrimary },
  actionBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  actionBtnTxtPrimary: { color: "#fff" },

  tblRow: {
    flexDirection: "row",
    paddingHorizontal: 4,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
    alignItems: "stretch",
  },
  tblHeader: {
    backgroundColor: colors.brandPrimary,
    borderTopLeftRadius: 6, borderTopRightRadius: 6,
    borderBottomWidth: 0,
  },
  tblHeaderTxt: { color: "#fff", fontWeight: "800", fontSize: 11 },
  readTxt: { fontSize: 11, color: colors.onSurface },
  alignLeft: { textAlign: "left" },
  alignRight: { textAlign: "right" },

  // Iter 86 — Row-wise employee highlight in Actual Salary grid.
  // Strong zebra stripes + 4px coloured left accent + bolded Code/Name.
  empRow: {
    minHeight: 32,
    alignItems: "center",
  },
  empRowEven: { backgroundColor: colors.surface },
  empRowOdd:  { backgroundColor: colors.surfaceSecondary },
  empIdent:   { fontWeight: "800", color: colors.onSurface, fontSize: 11 },

  editInput: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: 4,
    paddingHorizontal: 4,
    paddingVertical: 3,
    fontSize: 11,
    color: colors.onSurface,
    backgroundColor: colors.surface,
    textAlign: "right",
    minHeight: 26,
  },
  editInputDisabled: {
    backgroundColor: colors.surfaceSecondary,
    color: colors.onSurfaceSecondary,
    borderStyle: "dashed",
  },

  pastRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  pastIcon: {
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  pastTitle: { ...type.body, color: colors.onSurface, fontWeight: "600" },
  pastMeta: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 1 },
});
