/**
 * Compliance Salary Process — Web Portal only.
 *
 * Dedicated statutory payroll: PF / ESIC / PT / TDS.
 * Runs completely separate from the base Salary Process.
 *
 * Under the new labour code, the wage base for BOTH PF and ESIC is:
 *   max(Basic, 50% of Gross Earning)   — capped at ₹15,000 for PF only.
 *
 * Admins can:
 *   • Configure a batch: month, month_days, employee_type filter,
 *     on/off-roll filter, structure %, statutory rates.
 *   • Preview computed rows per employee (basic, hra, conv, med, spl,
 *     gross, wage base, PF (E/Er), ESIC (E/Er), PT, TDS, net).
 *   • Download CSV or PDF Compliance Register.
 *   • Push into per-employee compliance payslips.
 *   • Reprocess a batch.
 *   • Configure per-employee overrides in a modal editor.
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
  Modal,
  Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as DocumentPicker from "expo-document-picker";

import { api, apiBinary } from "@/src/api/client";
import { registerShortcuts } from "@/src/utils/shortcuts";
import { confirmYesNo, confirmChoice, showToast } from "@/src/utils/confirm";
import { EmployeeListSkeleton } from "@/src/components/EmployeeStatsBar";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
  
import MonthPicker from "@/src/components/MonthPicker";
import ProcessCommandCenter from "@/src/components/salary/ProcessCommandCenter";
import ReportsShareModal, { type ReportFormat } from "@/src/components/salary/ReportsShareModal";
import TotalsFooter from "@/src/components/salary/TotalsFooter";
import GridFilterChips, { GRID_FILTER_DEFAULT, rowMatchesFilters, type GridFilters } from "@/src/components/GridFilterChips";
import { GridScroller, stickyCol, stickyColRight, stickyHeader } from "@/src/components/GridFreeze";
import { rowPassesColFilters } from "@/src/utils/colFilter";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { sortEmployeeTypes } from "@/src/utils/employeeTypes";

const PT_STATES = [
  "None", "Maharashtra", "Karnataka", "West Bengal", "Gujarat",
  "Tamil Nadu", "Telangana", "Andhra Pradesh", "Madhya Pradesh",
  "Kerala", "Odisha", "Assam", "Bihar", "Punjab",
  "Delhi", "Uttar Pradesh", "Rajasthan", "Haryana", "Chandigarh",
];

type CompRow = {
  user_id: string;
  name?: string | null;
  employee_code?: string | null;
  employee_type?: string | null;
  is_onroll?: boolean;
  present_days: number;
  half_days: number;
  basic: number;
  hra: number;
  conveyance: number;
  medical: number;
  special: number;
  others: number;
  monthly_gross: number;
  ot_pay: number;
  gross_paid: number;
  stat_wage_base: number;
  pf_applicable: boolean;
  pf_wages: number;
  pf_employee: number;
  pf_employer_epf: number;
  pf_employer_eps: number;
  pf_employer_total: number;
  esic_applicable: boolean;
  esic_wage_base: number;
  esic_employee: number;
  esic_employer: number;
  pt_state: string;
  pt: number;
  tds: number;
  total_deduction: number;
  net: number;
  company_id?: string | null;
  company_name?: string | null;
};

type CompRun = {
  run_id: string;
  month: string;
  month_days: number;
  default_month_days: number;
  employee_type?: string | null;
  is_onroll_filter?: boolean | null;
  rows: CompRow[];
  totals: Record<string, number>;
  employees_count: number;
  generated_at?: string;
  // Iter 85 — Audit tracking on the past-runs list.
  generated_by?: string;
  generated_by_name?: string;
  generated_by_role?: string;
  finalized_at?: string;
  finalized_by_name?: string;
  reprocessed_from_at?: string;
  payslips_generated_at?: string;
  payslips_count?: number;
  structure_pct?: Record<string, number>;
  statutory_cfg?: Record<string, number>;
};

type EmployeeLite = {
  user_id: string;
  name?: string | null;
  employee_code?: string | null;
  employee_type?: string | null;
  is_onroll?: boolean | null;
  pf_applicable?: boolean | null;
  esic_applicable?: boolean | null;
  basic_amount?: number | null;
  hra_amount?: number | null;
  conv_amount?: number | null;
  medical_amount?: number | null;
  special_amount?: number | null;
  others_amount?: number | null;
  pt_state?: string | null;
  pt_amount_override?: number | null;
  tds_amount?: number | null;
};

function currentMonth(): string {
  // Iter 126h — salary is processed for the PREVIOUS month by default.
  // Iter 371 (user request) — AFTER the 25th the default flips to the
  // CURRENT month (next salary-prep cycle starts then).
  const d = new Date();
  if (d.getDate() <= 25) d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * Iter 86 — Calendar days in a YYYY-MM month string.
 * Used to CAP the "Month days (override)" input in Compliance Salary
 * so the operator cannot enter a value larger than the actual number
 * of days in the selected month (e.g. > 30 for November, > 28/29 for
 * February). Falls back to 31 for unparseable strings.
 */
function calendarDaysInMonth(monthStr: string): number {
  if (!monthStr || !/^\d{4}-\d{2}$/.test(monthStr)) return 31;
  const [y, m] = monthStr.split("-").map(Number);
  if (!y || !m || m < 1 || m > 12) return 31;
  return new Date(y, m, 0).getDate();
}
function fmtInr(n?: number | null): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  // User directive — plain numbers, NO thousands separators (commas).
  return String(Math.round(n));
}
function showMsg(msg: string, title = "Compliance salary") {
  // Iter 345 (user bug) — window.alert can be SUPPRESSED by the browser
  // ("prevent additional dialogs"), leaving the user with zero feedback.
  // The in-app toast is always visible.
  showToast(msg, title);
}

// Iter 346 (user request) — header-wise column filters: label → row value.
const COL_FILTER_GETTERS: Record<string, (r: any) => any> = {
  "Name": (r) => r.name,
  "Father Name": (r) => r.father_name,
  "Designation": (r) => r.designation,
  "UAN No.": (r) => r.uan_no,
  "ESIC No.": (r) => r.esi_ip_no,
  "Present Days": (r) => r.present_days,
  "ESIC Leave": (r) => r.esic_leave_days,
  "M.Basic": (r) => r.basic_master,
  "M.HRA": (r) => r.hra_master,
  "M.Conv": (r) => r.conveyance_master,
  "M.Med": (r) => r.medical_master,
  "M.Oth Allow": (r) => r.special_master,
  "M.Others": (r) => r.others_master,
  "M.Gross": (r) => r.gross_master,
  "Basic": (r) => r.basic,
  "HRA": (r) => r.hra,
  "Conv": (r) => r.conveyance,
  "Med": (r) => r.medical,
  "Oth Allow*": (r) => r.special,
  "Others*": (r) => r.others,
  "OT Amt*": (r) => r.ot_pay,
  "OT Hrs": (r) => {
    const hr = Number(r.ot_hourly_rate) || 0;
    return hr > 0 ? (Number(r.ot_pay) || 0) / hr : Number(r.ot_hours) || 0;
  },
  "Gross": (r) => r.gross_paid,
  "Freeze Salary": (r) => r.imported_gross,
  "Wage Base": (r) => r.stat_wage_base,
  "PF (E)": (r) => r.pf_employee,
  "PF (Er)": (r) => r.pf_employer_total,
  "ESI (E)": (r) => r.esic_employee,
  "ESI (Er)": (r) => r.esic_employer,
  "PT": (r) => r.pt,
  "TDS": (r) => r.tds,
  "Advance*": (r) => (r as any).advance_recovery,
  "Other*": (r) => r.other_deduction,
  "Total Ded.": (r) => r.total_deduction,
  "Net": (r) => r.net,
};

// Iter 656 (user bug — "switching workspace tabs wipes the grid") — the
// workspace tab bar REMOUNTS this screen on every tab switch (refresh
// nonce in the route), losing the open run + any unsaved grid edits.
// A module-level snapshot survives the remount (same SPA document) and
// is restored when the admin switches back. Cleared on Finalize/Delete/
// explicit clear. Max age 6 h.
let compRunKeepAlive: {
  companyId: string | null; run: any; month: string; monthDays: string;
  empType: string; unsaved: boolean; ts: number;
} | null = null;

export default function ComplianceSalaryRunScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin =
    user?.role === "super_admin" ||
    user?.role === "sub_admin" ||
    user?.role === "company_admin";

  const [month, setMonth] = useState(currentMonth());
  // Iter 172 — firm dropdown state
  const [firmDdOpen, setFirmDdOpen] = useState(false);
  const [firmSearch, setFirmSearch] = useState("");
  // Iter 96s — Month days defaults to 26 (standard duty days). Admins can
  // change it; it's still clamped to the month's calendar days below.
  const [monthDaysOverride, setMonthDaysOverride] = useState("26");
  // Iter 86 — When the selected month changes, ensure any previously
  // entered override that is larger than the new month's calendar days
  // is clamped down (e.g. 31 → 28 for February).
  useEffect(() => {
    if (!monthDaysOverride) return;
    const max = calendarDaysInMonth(month);
    const n = Number(monthDaysOverride);
    if (Number.isFinite(n) && n > max) {
      setMonthDaysOverride(String(max));
    }
  }, [month, monthDaysOverride]);
  const [empType, setEmpType] = useState<string>("all");
  // Iter 85 — Compliance Salary Process is strictly ON-ROLL only.
  // The "All" / "Off-roll" chips were removed per user request; keep the
  // state fixed to "on" so downstream body construction still sends
  // is_onroll=true.
  const [rollFilter] = useState<"on">("on");

  // Structure % config (company-wide default; per-employee overrides go through the employee editor).
  const [basicPct, setBasicPct] = useState("40");
  const [hraPct, setHraPct] = useState("20");
  const [convPct, setConvPct] = useState("5");
  const [medicalPct, setMedicalPct] = useState("3");
  const [specialPct, setSpecialPct] = useState("32");
  const [othersPct, setOthersPct] = useState("0");

  // Statutory config
  const [pfCap, setPfCap] = useState("15000");
  const [pfPctEmp, setPfPctEmp] = useState("12");
  const [esiThreshold, setEsiThreshold] = useState("21000");
  const [statFloorPct, setStatFloorPct] = useState("50");

  const [types, setTypes] = useState<{ name: string; count: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<CompRun | null>(null);
  const [runs, setRuns] = useState<CompRun[]>([]);
  const [downloading, setDownloading] = useState(false);
  // Iter 324 (user request) — PDF sorting & grouping choices.
  const [pdfSort, setPdfSort] = useState("");
  const [pushing, setPushing] = useState(false);
  const [waBlasting, setWaBlasting] = useState(false);
  const [showConfig, setShowConfig] = useState(false);

  // ── Iter 61: Multi-firm batch mode ─────────────────────────────────────
  const isSuper = user?.role === "super_admin" || user?.role === "sub_admin";
  const [batchMode, setBatchMode] = useState(false);
  const { selectedCompanyId: globalCid, companies: ctxCompanies } = useSelectedCompany();
  const [companies, setCompanies] = useState<{ company_id: string; name: string }[]>([]);
  const [selectedCids, setSelectedCids] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [activeBatch, setActiveBatch] = useState<any | null>(null);
  // Iter 91 — In-screen firm selection: pick from ALL active firms here
  // instead of relying on the top-bar picker.
  const [localCid, setLocalCid] = useState<string | null>(null);
  const [finalizing, setFinalizing] = useState(false);
  // Iter 101 — imported salary sheet (file upload / Gmail attachment)
  // replaces the old Attendance Master link.
  const [useImportedSheet, setUseImportedSheet] = useState(false);
  const [importStatus, setImportStatus] = useState<{ count: number; source?: string; filename?: string } | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [mailModal, setMailModal] = useState(false);
  // Iter 438 (user request) — after Save / Finalize offer to Download or
  // Mail the run's reports (PDF / Excel / CSV / All).
  const [reportsFor, setReportsFor] = useState<
    { run_id: string; month: string; note: string; group?: string } | null
  >(null);
  const [mailMsgs, setMailMsgs] = useState<any[]>([]);
  const [mailLoading, setMailLoading] = useState(false);
  // Iter 98 — display sorting for the compliance grid.
  const [sortBy, setSortBy] = useState<string>("");
  // Iter 370 (user request) — click ANY column header to sort (asc → desc
  // → off). Takes precedence over the sort chips while active.
  const [colSort, setColSort] = useState<{ label: string; dir: "asc" | "desc" } | null>(null);
  const toggleColSort = (label: string) => {
    if (!COL_FILTER_GETTERS[label]) return;
    setColSort((cur) =>
      !cur || cur.label !== label
        ? { label, dir: "asc" }
        : cur.dir === "asc"
          ? { label, dir: "desc" }
          : null);
  };
  // Iter 182 — instant employee search + audit log
  const [empSearch, setEmpSearch] = useState("");
  const empSearchRef = useRef<TextInput | null>(null);
  // Iter 380 (user accepted improvement) — one-click filter that shows
  // ONLY the employees whose Freeze Salary differs from the calculated
  // Gross (imported/frozen runs).
  const [onlyMismatch, setOnlyMismatch] = useState(false);
  const rowIsMismatch = (r: any) =>
    r.imported_gross != null &&
    Math.abs(Number(r.imported_gross) - Number(r.gross_paid || 0)) > 0.5;
  // Iter 183 — Branch / Dept / Contractor filter chips.
  const [gridFilters, setGridFilters] = useState<GridFilters>(GRID_FILTER_DEFAULT);
  // Iter 306 (user #8) — tap a row to HIGHLIGHT it across the wide grid.
  const [hlRow, setHlRow] = useState<string | null>(null);
  // Iter 657 (user request) — measure the grid's real top offset so its
  // height always fits the viewport (frozen header + visible h-scrollbar).
  const gridWrapRef = useRef<any>(null);
  const [gridTopPx, setGridTopPx] = useState(170);
  // Iter 346 (user request) — Excel-style per-column header filters.
  const [colFilters, setColFilters] = useState<Record<string, string>>({});
  // Iter 127e — AUTO-ADJUST every column to its widest content so nothing
  // is cut off (user request; replaces the wrap-text experiment).
  const colW = useMemo(() => {
    const rows = run?.rows || [];
    // Iter 643 (user request) — grid font reduced to 12px, so auto-fit
    // columns tighten too (~7.2 px/char + padding). Layout-only change.
    const px = (v: any) => String(v ?? "").length * 7.2 + 20;
    const fit = (label: string, vals: any[], base = 88, maxW = 280) => {
      let m = Math.max(base, px(label));
      for (const v of vals) {
        const p = px(v);
        if (p > m) m = p;
      }
      return Math.round(Math.min(maxW, m));
    };
    const nums: any[] = [];
    for (const r of rows as any[]) {
      nums.push(fmtInr(r.gross_master), fmtInr(r.gross_paid), fmtInr(r.net),
                fmtInr(r.stat_wage_base), fmtInr(r.total_deduction));
    }
    return {
      sr: 52, // Iter 379 (user request) — Sr. No first column
      name: fit("Name", rows.map((r: any) => r.name), 140),
      father: fit("Father Name", rows.map((r: any) => r.father_name), 120),
      desg: fit("Designation", rows.map((r: any) => r.designation), 110),
      uan: fit("UAN No.", rows.map((r: any) => r.uan_no), 96),
      esi: fit("ESIC No.", rows.map((r: any) => r.esi_ip_no), 96),
      pd: 84, // PresentDaysCell input is fixed-width
      el: 84, // Iter 306 (user #20) — ESIC Leave days input
      num: fit("Wage Base", nums, 88, 150),
    };
  }, [run?.rows]);
  // Iter 310 — Freeze Salary columns are shown only for imported-sheet
  // (frozen) runs where at least one row carries the imported gross.
  const hasFrz = !!run && (run.rows || []).some((r: any) => r.imported_gross != null);

  const sortRows = (rows: CompRow[]) => {
    // Iter 183 — branch/dept/contractor chips filter first…
    let base = rows.filter((r) => rowMatchesFilters(r, gridFilters));
    // Iter 380 — "Show only mismatches" (Freeze ≠ Gross) toggle.
    if (onlyMismatch) base = base.filter(rowIsMismatch);
    // …then Iter 182 — instant search filters the grid before sorting.
    const q = empSearch.trim().toLowerCase();
    if (q) {
      base = base.filter((r: any) =>
        [r.name, r.employee_code, r.uan_no, r.esi_ip_no, r.designation, r.father_name]
          .some((v) => String(v || "").toLowerCase().includes(q)));
    }
    if (!sortBy && !colSort) return base;
    const num = (v: any) => Number(v ?? 0);
    const arr = [...base];
    if (sortBy === "name") arr.sort((a: any, b: any) => String(a.name || "").localeCompare(String(b.name || "")));
    else if (sortBy === "code") arr.sort((a: any, b: any) => num(a.employee_code) - num(b.employee_code));
    else if (sortBy === "net") arr.sort((a: any, b: any) => num(b.net) - num(a.net));
    else if (sortBy === "gross") arr.sort((a: any, b: any) => num(b.gross) - num(a.gross));
    // Iter 370 (user request) — header-click sorting on EVERY column.
    if (colSort) {
      const g = COL_FILTER_GETTERS[colSort.label];
      if (g) {
        const dir = colSort.dir === "asc" ? 1 : -1;
        arr.sort((a: any, b: any) => {
          const va = g(a);
          const vb = g(b);
          const na = Number(va);
          const nb = Number(vb);
          const aNum = va !== null && va !== undefined && va !== "" && Number.isFinite(na);
          const bNum = vb !== null && vb !== undefined && vb !== "" && Number.isFinite(nb);
          if (aNum && bNum) return (na - nb) * dir;
          if (aNum !== bNum) return (aNum ? -1 : 1) * dir; // numbers before blanks
          return String(va ?? "").localeCompare(String(vb ?? "")) * dir;
        });
      }
    }
    return arr;
  };


  // Iter 370 (user request) — head-wise column totals for the footer row.
  // Iter 662 (user bug — "while using filter total showing wrong") — the
  // TOTAL row must sum ONLY the rows visible after the column filters.
  const visibleRows = React.useMemo(
    () => (run?.rows || []).filter((r: any) =>
      rowPassesColFilters(r, colFilters, COL_FILTER_GETTERS)),
    [run, colFilters],
  );
  const sumCol = (k: string) =>
    visibleRows.reduce((s: number, r: any) => s + (Number(r[k]) || 0), 0);
  const fmtDaysTotal = (v: number) => (v % 1 ? v.toFixed(1) : String(v));

  // Iter 182 — keyboard shortcuts (web): "/" focuses employee search,
  // Ctrl/Cmd+S saves the draft.
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const onKey = (e: any) => {
      const tag = (e.target?.tagName || "").toLowerCase();
      const typing = tag === "input" || tag === "textarea";
      if (e.key === "/" && !typing) {
        e.preventDefault();
        empSearchRef.current?.focus();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (run && !(run as any).finalized) saveAsDraft();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run]);

  // Prefill from global picker whenever batch mode is turned on.
  useEffect(() => {
    if (batchMode && globalCid && selectedCids.size === 0) {
      setSelectedCids(new Set([globalCid]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchMode]);

  useEffect(() => {
    // Use the cached context list to avoid a redundant fetch.
    if (ctxCompanies.length > 0) setCompanies(ctxCompanies);
  }, [ctxCompanies]);

  // Poll active batch every 3s while running
  useEffect(() => {
    if (!activeBatch?.batch_id) return;
    if (["completed", "completed_with_errors"].includes(activeBatch.status)) return;
    let stopped = false;
    const tick = async () => {
      try {
        const b = await api<any>(`/admin/compliance-batches/${activeBatch.batch_id}`);
        if (stopped) return;
        setActiveBatch(b);
        if (["completed", "completed_with_errors"].includes(b.status)) return;
        setTimeout(tick, 3000);
      } catch {
        // stop
      }
    };
    setTimeout(tick, 3000);
    return () => {
      stopped = true;
    };
  }, [activeBatch?.batch_id, activeBatch?.status]);

  const toggleCid = (cid: string) => {
    setSelectedCids((prev) => {
      const next = new Set(prev);
      if (next.has(cid)) next.delete(cid);
      else next.add(cid);
      return next;
    });
  };

  void toggleCid; // batch multi-firm mode removed (Iter 96t) — helper retained

  useEffect(() => {
    (async () => {
      try {
        // Iter 129l (user directive) — counts are for the SELECTED firm
        // only, never the whole portal. Iter 130 — reacts to the local
        // firm chips too, not just the global picker.
        const cid = localCid || globalCid;
        const qs = cid ? `?company_id=${encodeURIComponent(cid)}` : "";
        const r = await api<{ types: { name: string; count: number }[] }>(
          `/admin/employee-types${qs}`,
        );
        // Iter 85 — Compliance Salary Process shows only active types.
        const filtered = sortEmployeeTypes(r.types || [], { activeOnly: true });
        setTypes(filtered);
        if (filtered.length > 0) {
          setEmpType((cur) =>
            cur !== "all" && filtered.some((t) => t.name === cur) ? cur : filtered[0].name,
          );
        }
      } catch { /* ignore */ }
    })();
  }, [globalCid, localCid]);

  // Iter 68 — Compliance Salary should NEVER be a place where allowances /
  // statutory config are edited.  Load the firm's compliance policy on
  // firm change and populate the (now read-only) fields from it.  Users
  // wanting to change these values are redirected to Firm Settings
  // (/compliance-policy) where the change persists and applies to every
  // subsequent run.
  const activeCompanyId = localCid || globalCid || user?.company_id || null;

  // User directive — changing the FIRM must fully reset the form so the
  // previous company's run/employees never linger on screen.
  const prevCidRef = useRef<string | null>(null);
  useEffect(() => {
    if (prevCidRef.current && prevCidRef.current !== activeCompanyId) {
      setRun(null);
      setActiveBatch(null);
      setEmpType("all");
    }
    prevCidRef.current = activeCompanyId;
  }, [activeCompanyId]);

  // Iter 370 (user bug) — the firm policy fetch is ASYNC: clicking
  // "Salary Process" right after opening the page / switching firm used
  // to RACE it, sending the hard-coded defaults instead of the firm's
  // saved statutory numbers — PF/ESIC looked "not calculated" until a
  // second click. generate() now AWAITS this loader on the first click
  // and uses the freshly returned values directly.
  const policyReadyRef = useRef(false);
  const loadPolicy = useCallback(async (): Promise<Record<string, string> | null> => {
    if (!activeCompanyId) return null;
    try {
      const r = await api<{ policy: any }>(
        `/admin/companies/${activeCompanyId}/compliance-policy`,
      );
      const p = r.policy || {};
      const v = (x: any, d: string) => (x !== undefined ? String(x) : d);
      // Salary structure + statutory — fall back to hard-coded defaults.
      const vals: Record<string, string> = {
        basicPct: v(p.basic_pct, "40"),
        hraPct: v(p.hra_pct, "20"),
        convPct: v(p.conveyance_pct, "5"),
        medicalPct: v(p.medical_pct, "3"),
        specialPct: v(p.special_pct, "32"),
        othersPct: v(p.others_pct, "0"),
        pfCap: v(p.pf_wage_cap, "15000"),
        pfPctEmp: v(p.pf_employee_rate, "12"),
        esiThreshold: v(p.esic_wage_threshold, "21000"),
        statFloorPct: v(p.stat_wage_floor_pct, "50"),
      };
      setBasicPct(vals.basicPct);
      setHraPct(vals.hraPct);
      setConvPct(vals.convPct);
      setMedicalPct(vals.medicalPct);
      setSpecialPct(vals.specialPct);
      setOthersPct(vals.othersPct);
      setPfCap(vals.pfCap);
      setPfPctEmp(vals.pfPctEmp);
      setEsiThreshold(vals.esiThreshold);
      setStatFloorPct(vals.statFloorPct);
      policyReadyRef.current = true;
      return vals;
    } catch {
      // If the firm has no policy override yet, keep the hard-coded
      // defaults already set in the initial state.
      policyReadyRef.current = true;
      return null;
    }
  }, [activeCompanyId]);

  useEffect(() => {
    policyReadyRef.current = false;
    if (!activeCompanyId) return;
    loadPolicy();
  }, [activeCompanyId, loadPolicy]);

  // Iter 427b (user clarification) — when the firm's Salary Process method
  // is FIXED DAYS (26/30/31), the "Month days (override)" field FETCHES the
  // firm's fixed figure automatically.
  useEffect(() => {
    if (!activeCompanyId) return;
    let alive = true;
    api<any>(`/admin/firm-master/${activeCompanyId}`)
      .then((r) => {
        const sp = ((r?.master || r?.firm || r) as any)?.salary_process || {};
        if (alive && String(sp.days_calc_method || "") === "fixed") {
          setMonthDaysOverride(String(sp.days_calc_fixed || 26));
        }
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [activeCompanyId]);

  const loadRuns = useCallback(async () => {
    try {
      const r = await api<{ runs: CompRun[] }>("/admin/compliance-salary-runs");
      setRuns(r.runs || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { if (isAdmin) loadRuns(); }, [isAdmin, loadRuns]);

  // Iter 371 (user request) — Configure batch shows an UNLOCK button when
  // the selected month's salary is already processed & FINALIZED for this
  // firm + employee group (Super / Sub Admins only).
  const finalizedExisting = useMemo(() => {
    const grp = (empType !== "all" ? empType : "").trim().toUpperCase();
    return (runs as any[]).find(
      (r: any) =>
        r.month === month &&
        (!activeCompanyId || r.company_id === activeCompanyId) &&
        String(r.employee_type || "").trim().toUpperCase() === grp &&
        r.finalized,
    ) || null;
  }, [runs, month, activeCompanyId, empType]);

  // Iter 426 (user request) — ANY existing run (draft OR finalized) for
  // this firm + month + group locks the "Month days" input: a reprocess
  // must proceed with the SAME days already processed.
  const existingAny = useMemo(() => {
    const grp = (empType !== "all" ? empType : "").trim().toUpperCase();
    return (runs as any[]).find(
      (r: any) =>
        r.month === month &&
        (!activeCompanyId || r.company_id === activeCompanyId) &&
        String(r.employee_type || "").trim().toUpperCase() === grp,
    ) || null;
  }, [runs, month, activeCompanyId, empType]);

  // Iter 370 — ``pv`` carries the freshly loaded firm policy values when
  // the state hasn't caught up yet (first click after page open).
  const buildBody = (pv?: Record<string, string> | null) => {
    const g = (k: string, sv: string) => (pv && pv[k] !== undefined ? pv[k] : sv);
    const body: any = {
      month,
      structure_pct: {
        basic: Number(g("basicPct", basicPct)) || 0,
        hra: Number(g("hraPct", hraPct)) || 0,
        conveyance: Number(g("convPct", convPct)) || 0,
        medical: Number(g("medicalPct", medicalPct)) || 0,
        special: Number(g("specialPct", specialPct)) || 0,
        others: Number(g("othersPct", othersPct)) || 0,
      },
      statutory_cfg: {
        pf_wage_cap: Number(g("pfCap", pfCap)) || 15000,
        pf_percent_employee: Number(g("pfPctEmp", pfPctEmp)) || 12,
        esic_gross_threshold: Number(g("esiThreshold", esiThreshold)) || 21000,
        stat_wage_floor_pct: Number(g("statFloorPct", statFloorPct)) || 50,
      },
    };
    if (monthDaysOverride.trim()) body.month_days = Number(monthDaysOverride);
    if (empType !== "all") body.employee_type = empType;
    if (rollFilter !== "all") body.is_onroll = rollFilter === "on";
    if (activeCompanyId) body.company_id = activeCompanyId;
    if (useImportedSheet) body.use_imported_sheet = true;
    return body;
  };

  // Iter 101 — imported-sheet helpers -----------------------------------
  const loadImportStatus = useCallback(async () => {
    if (!activeCompanyId || !month) { setImportStatus(null); return; }
    try {
      const r = await api<{ count: number; source?: string; filename?: string }>(
        `/admin/compliance-import/status?company_id=${encodeURIComponent(activeCompanyId)}&month=${encodeURIComponent(month)}`,
      );
      setImportStatus(r);
    } catch {
      setImportStatus(null);
    }
  }, [activeCompanyId, month]);
  useEffect(() => { loadImportStatus(); }, [loadImportStatus]);

  const fileToBase64 = async (uri: string): Promise<string> => {
    const res = await fetch(uri);
    const blob = await res.blob();
    return await new Promise<string>((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => {
        const s = String(fr.result || "");
        resolve(s.includes(",") ? s.split(",")[1] : s);
      };
      fr.onerror = reject;
      fr.readAsDataURL(blob);
    });
  };

  const pickAndUpload = async () => {
    if (!activeCompanyId) { showMsg("Select a firm first"); return; }
    // Iter 616 (user rule) — Month Days MUST be filled before importing:
    // the imported sheet's days derivation divides by this value.
    if (!monthDaysOverride.trim() || !(Number(monthDaysOverride) > 0)) {
      showMsg("⚠ Enter Month Days (Override) first — the sheet import calculates salary using these days.");
      return;
    }
    const res = await DocumentPicker.getDocumentAsync({
      type: [
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      ],
      copyToCacheDirectory: true,
    });
    if (res.canceled || !res.assets?.length) return;
    const asset = res.assets[0];
    setImportBusy(true);
    try {
      const b64 = await fileToBase64(asset.uri);
      const r = await api<any>("/admin/compliance-import/upload", {
        method: "POST",
        body: {
          company_id: activeCompanyId, month, filename: asset.name, content_base64: b64,
          // Iter 661 (user bug) — the auto-reprocess after import must keep
          // the SAME Employee Group + Month Days chosen in Configure Batch.
          employee_type: empType,
          month_days: Number(monthDaysOverride) || undefined,
        },
      });
      setUseImportedSheet(true);
      await loadImportStatus();
      // Iter 335 (user request) — the month is AUTO-REPROCESSED right
      // after the import (Freeze Salary): show the fresh run directly.
      if (r.auto_run?.ok && r.auto_run.run) {
        setRun(r.auto_run.run);
        await loadRuns();
        const t = r.auto_run.run.totals || {};
        showMsg(
          `Imported ${r.matched} of ${r.total_rows} rows` +
          (r.unmatched_count ? ` (${r.unmatched_count} unmatched)` : "") +
          ` — salary auto-processed: Net ${fmtInr(t.net)}, PF ${fmtInr(t.pf_employee)}, ESIC ${fmtInr(t.esic_employee)}.` +
          (t.difference ? ` Freeze difference ${fmtInr(t.difference)} allocated to OT/Other Allowances.` : ""),
        );
      } else {
        showMsg(
          `Imported ${r.matched} of ${r.total_rows} rows` +
          (r.unmatched_count ? ` — ${r.unmatched_count} row(s) had no matching employee.` : ".") +
          (r.auto_run?.error ? ` Auto-process failed: ${r.auto_run.error}` : ""),
        );
      }
    } catch (e: any) {
      // Iter 458 (user bug — "Server never uploads the sheet") — nginx's
      // 1 MB default body limit rejected big Excel files with 413 before
      // the backend saw them; surface a clear message.
      const msg = String(e?.message || "");
      showMsg(
        /413|too large|entity/i.test(msg)
          ? "The file is too large for the server's upload limit — run the latest deploy script (it raises the nginx limit to 100 MB) and try again."
          : msg || "Import failed",
      );
    } finally { setImportBusy(false); }
  };

  const openMailPicker = async () => {
    if (!activeCompanyId) { showMsg("Select a firm first"); return; }
    setMailModal(true);
    setMailLoading(true);
    try {
      const r = await api<{ messages: any[] }>("/gmail/spreadsheet-attachments");
      setMailMsgs(r.messages || []);
    } catch (e: any) {
      setMailModal(false);
      showMsg(e?.message || "Could not load the mailbox. Is Gmail connected? (Mailbox → Connect)");
    } finally { setMailLoading(false); }
  };

  const importFromMail = async (msg: any, att: any) => {
    // Iter 616 (user rule) — Month Days MUST be filled before importing.
    if (!monthDaysOverride.trim() || !(Number(monthDaysOverride) > 0)) {
      showMsg("⚠ Enter Month Days (Override) first — the sheet import calculates salary using these days.");
      return;
    }
    setMailModal(false);
    setImportBusy(true);
    try {
      const r = await api<any>("/admin/compliance-import/from-gmail", {
        method: "POST",
        body: {
          company_id: activeCompanyId, month,
          message_id: msg.message_id, attachment_id: att.attachment_id,
          filename: att.filename,
        },
      });
      setUseImportedSheet(true);
      await loadImportStatus();
      // Iter 335 — auto-reprocessed after Gmail import too.
      if (r.auto_run?.ok && r.auto_run.run) {
        setRun(r.auto_run.run);
        await loadRuns();
        const t = r.auto_run.run.totals || {};
        showMsg(
          `Imported ${r.matched} of ${r.total_rows} rows from "${att.filename}"` +
          ` — salary auto-processed: Net ${fmtInr(t.net)}, PF ${fmtInr(t.pf_employee)}, ESIC ${fmtInr(t.esic_employee)}.`,
        );
      } else {
        showMsg(
          `Imported ${r.matched} of ${r.total_rows} rows from "${att.filename}"` +
          (r.unmatched_count ? ` — ${r.unmatched_count} row(s) had no matching employee.` : ".") +
          (r.auto_run?.error ? ` Auto-process failed: ${r.auto_run.error}` : ""),
        );
      }
    } catch (e: any) {
      showMsg(e?.message || "Import failed");
    } finally { setImportBusy(false); }
  };

  // Iter 595 — F5 = recalculate / process salary (keyboard shortcuts Phase 2).
  const generateRef = useRef<() => void>(() => {});
  useEffect(
    () =>
      registerShortcuts("compliance-salary-run", [
        {
          combo: "f5",
          label: "Recalculate / process compliance salary",
          category: "Salary Processing",
          allowInInput: true,
          handler: () => generateRef.current(),
        },
      ]),
    [],
  );
  const generate = async () => {
    if (busy) return;
    // Iter 426 (user request) — Employee Group selection is MANDATORY:
    // processing ALL groups together is no longer allowed.
    if (empType === "all") {
      showMsg("Please select an Employee Group first — group selection is mandatory before Salary Process.");
      return;
    }
    // Iter 370 (user bug) — first click after opening the page: WAIT for
    // the firm policy before processing so PF/ESIC use the firm's saved
    // statutory numbers (not the defaults) on the very first click.
    let pv: Record<string, string> | null = null;
    if (activeCompanyId && !policyReadyRef.current) pv = await loadPolicy();
    // Iter 129e (user directive) — if a run for this firm + month already
    // exists, ask before reprocessing. "No" reloads the page unchanged.
    // Iter 257 (user bug) — the check is scoped to the SAME employee group,
    // so finalizing one group never blocks processing another.
    const q: any = buildBody(pv);
    const qGrp = String(q.employee_type || "").trim().toUpperCase();
    const existing = runs.find(
      (r: any) =>
        r.month === q.month &&
        (!q.company_id || r.company_id === q.company_id) &&
        String((r as any).employee_type || "").trim().toUpperCase() === qGrp,
    );
    if (existing) {
      if ((existing as any).finalized) {
        // Iter 373 (user request) — offer the UNLOCK right here for
        // Super / Sub Admins instead of a dead-end message.
        if (isSuper) {
          const okU = await confirmYesNo(
            "This month's salary is already FINALIZED for this employee group.\n\n" +
            "UNLOCK it now so it can be edited / reprocessed?",
          );
          if (okU) {
            try {
              const ur = await api<{ ok: boolean; unlocked?: boolean; message?: string }>(
                `/admin/compliance-salary-runs/${(existing as any).run_id}/unlock-request`,
                { method: "POST", body: { reason: "Unlocked from Salary Process" } },
              );
              if (ur.unlocked) {
                if (run?.run_id === (existing as any).run_id) {
                  setRun({ ...(run as any), finalized: false } as any);
                }
                await loadRuns();
                showMsg("Salary unlocked ✓ — click Salary Process again to reprocess.");
              } else {
                showMsg(ur.message || "Unlock request sent for approval.");
              }
            } catch (e: any) {
              showMsg(e?.message || "Unlock failed");
            }
          }
          return;
        }
        showMsg(
          "This month's salary is already FINALIZED for this employee group — it cannot be processed again. Use Unlock Request to de-finalize first.",
        );
        return;
      }
      const choice = await confirmChoice(
        "A salary sheet for this month already exists.\nHow do you want to reprocess?",
        "Reprocess Salary",
        [
          {
            label: "With EXISTING Data — entered days & edits are KEPT",
            value: "existing", color: "#2563EB",
          },
          {
            label: "From BLANK — fresh rebuild from attendance & master (edits discarded)",
            value: "blank", color: "#DC2626",
          },
        ],
      );
      // Iter 345 (user bug — "page just refreshes") — a cancel must never
      // RELOAD the page.
      if (!choice) return;
      // Iter 728 (user bug — "Reprocess with existing data hides the
      // Freeze Salary column") — an imported-sheet run keeps its sheet
      // source on the EXISTING-data reprocess even when the form toggle
      // reset to OFF after a reload (backend inherits it too).
      if (choice === "existing" && (existing as any)?.attendance_source === "imported_sheet") {
        q.use_imported_sheet = true;
      }
      if (choice === "blank") {
        const sure = await confirmYesNo(
          "Reprocess from BLANK will DISCARD all manually entered days & edits on the existing sheet.\n\nContinue?",
        );
        if (!sure) return;
        q.fresh = true;
      }
      // Iter 429 (user request) — Month days stays EDITABLE: when the typed
      // value differs from the already-processed days, ASK which to use.
      const prevMd = Number((existing as any).month_days || 0);
      const newMd = Number(monthDaysOverride || 0);
      if (prevMd > 0 && newMd > 0 && newMd !== prevMd) {
        const mdc = await confirmChoice(
          `This month was already processed with ${prevMd} days, but the form now says ${newMd} days.\nWhich should the reprocess use?`,
          "Month Days Changed",
          [
            { label: `Keep processed days (${prevMd})`, value: "keep", color: "#2563EB" },
            { label: `Use NEW days (${newMd})`, value: "new", color: "#D97706" },
          ],
        );
        if (!mdc) return;
        if (mdc === "new") q.override_month_days = true;
      }
    }
    setBusy(true);
    try {
      const r = await api<{ run: CompRun }>("/admin/compliance-salary-runs", {
        method: "POST",
        body: q,
      });
      setRun(r.run);
      await loadRuns();
      showMsg(
        `Compliance run generated for ${r.run.employees_count} employees. Net payout: ${fmtInr(r.run.totals?.net)}. Statutory total: ${fmtInr(r.run.totals?.total_deduction)}`,
      );
    } catch (e: any) {
      showMsg(e?.message || "Failed to generate compliance run");
    } finally { setBusy(false); }
  };
  generateRef.current = generate;

  // Iter 330 (user request) — Copy Last Month Salary into this month.
  const copyLastMonth = async () => {
    if (busy) return;
    // Iter 426 (user request) — group selection mandatory here too.
    if (empType === "all") {
      showMsg("Please select an Employee Group first — group selection is mandatory before processing.");
      return;
    }
    const q: any = buildBody();
    const [yy, mm] = String(q.month || "").split("-").map(Number);
    const prevMonth = mm === 1
      ? `${yy - 1}-12`
      : `${yy}-${String(mm - 1).padStart(2, "0")}`;
    const qGrp = String(q.employee_type || "").trim().toUpperCase();
    const existing = runs.find(
      (r: any) =>
        r.month === q.month &&
        (!q.company_id || r.company_id === q.company_id) &&
        String((r as any).employee_type || "").trim().toUpperCase() === qGrp,
    );
    if (existing && (existing as any).finalized) {
      showMsg(
        "This month's salary is already FINALIZED for this employee group — it cannot be processed again. Use Unlock Request to de-finalize first.",
      );
      return;
    }
    // Iter 391 (user request) — the copy confirmation lists only the
    // Firm-Master-enabled deduction heads.
    const _edm = fmMask.ed as string[] | undefined;
    const _dedTxt = [
      (!_edm || _edm.includes("pf")) && "PF",
      (!_edm || _edm.includes("esi")) && "ESIC",
      (!_edm || _edm.includes("pt")) && "PT",
      (!_edm || _edm.includes("tds")) && "TDS",
    ].filter(Boolean).join("/");
    const ok = await confirmYesNo(
      `Copy LAST MONTH's salary (${prevMonth}) into ${q.month}?\n\n` +
      `• Present Days, Gross, ${_dedTxt} and Net are copied EXACTLY as last month.\n` +
      "• Employees who exited before this month are dropped; new joiners are not added.\n" +
      "• The copied run is a normal editable draft — you can edit, save and finalize it." +
      (existing ? "\n\n⚠ The existing draft for this month will be REPLACED." : ""),
    );
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api<{ run: CompRun }>("/admin/compliance-salary-runs", {
        method: "POST",
        body: { ...q, copy_last_month: true },
      });
      setRun(r.run);
      await loadRuns();
      const skipped = ((r.run as any).copied_skipped || []).length;
      showMsg(
        `Copied ${prevMonth} → ${q.month} for ${r.run.employees_count} employees. Net payout: ${fmtInr(r.run.totals?.net)}.` +
        (skipped ? ` ${skipped} exited/disabled employee(s) were dropped.` : ""),
      );
    } catch (e: any) {
      showMsg(e?.message || "Copy Last Month failed");
    } finally { setBusy(false); }
  };

  // Iter 230 (user request) — Reprocess: reload the LAST SAVED data of
  // this run from the server (discards unsaved local edits).
  const reprocessRun = async () => {
    if (!run) return;
    const ok = await confirmYesNo(
      "Reprocess — reload the previously SAVED salary data for this run?\nAny unsaved edits on screen will be replaced.",
    );
    if (!ok) return;
    try {
      const j = await api<{ run: CompRun }>(`/admin/compliance-salary-runs/${run.run_id}`);
      hydratedRunsRef.current[run.run_id] = true;
      setRun(j.run);
      showMsg("Reprocessed ✓ — showing the last saved salary data.");
    } catch (e: any) {
      showMsg(e?.message || "Reprocess failed");
    }
  };

  // Iter 485 — SUPER-ADMIN ONLY: replace the frozen payroll master
  // snapshot with the CURRENT Employee Master (new version, full history
  // kept) and reprocess the sheet on the refreshed values.
  const [refreshingSnap, setRefreshingSnap] = useState(false);
  // Iter 486 — snapshot badge data for the run header.
  const [snapInfo, setSnapInfo] = useState<any>(null);
  useEffect(() => {
    let alive = true;
    (async () => {
      if (!run?.run_id) { setSnapInfo(null); return; }
      try {
        const r = await api<any>(`/admin/compliance-salary-runs/${run.run_id}/master-snapshot-info`);
        if (alive) setSnapInfo(r);
      } catch { if (alive) setSnapInfo(null); }
    })();
    return () => { alive = false; };
  }, [run?.run_id, refreshingSnap]);
  const refreshMasterSnapshot = async () => {
    if (!run || !isSuper) return;
    const ok = await confirmYesNo(
      "This action will replace the existing payroll snapshot with the current Employee Master. Historical payroll values may change. Continue?",
    );
    if (!ok) return;
    let reason: string | null = null;
    if (Platform.OS === "web") {
      reason = window.prompt("Reason for refreshing the master snapshot (recorded in the audit trail):", "");
      if (reason === null) return; // cancelled
    }
    setRefreshingSnap(true);
    try {
      const j = await api<{ run: CompRun; snapshot: any }>(
        `/admin/compliance-salary-runs/${run.run_id}/refresh-master-snapshot`,
        { method: "POST", body: { reason } });
      hydratedRunsRef.current[run.run_id] = true;
      setRun(j.run);
      showMsg(`Master snapshot refreshed ✓ — now on version v${j.snapshot?.new_version}. Sheet reprocessed on the current Employee Master.`);
    } catch (e: any) {
      showMsg(e?.message || "Refresh Master failed");
    } finally {
      setRefreshingSnap(false);
    }
  };

  // Iter 230 (user request) — Delete the salary run (asks TWICE).
  const deleteRun = async () => {
    if (!run) return;
    const ok1 = await confirmYesNo(
      `DELETE this Compliance Salary run (${run.month})?\nThis cannot be undone.`,
    );
    if (!ok1) return;
    const ok2 = await confirmYesNo(
      "Are you REALLY sure? Confirm once more to DELETE this salary permanently.",
    );
    if (!ok2) return;
    try {
      const r = await api<{ deleted?: boolean; approval_required?: boolean; message?: string }>(
        `/admin/compliance-salary-runs/${run.run_id}`, { method: "DELETE" },
      );
      if (r.deleted) {
        setRun(null);
        // Iter 620 (user bug) — refresh the runs list so "Salary Process"
        // doesn't offer the "already exists → Reprocess?" dialog for the
        // just-deleted sheet.
        await loadRuns();
        showMsg("Salary run DELETED ✓");
      } else {
        showMsg(r.message || "Deletion sent to the Super Admin for approval.");
      }
    } catch (e: any) {
      showMsg(e?.message || "Delete failed");
    }
  };

  // Iter 388 (Phase 3) — Pre-lock PF/ESIC validation result modal.
  const [lockCheck, setLockCheck] = useState<any | null>(null);

  const doFinalize = async (allowWarnings: boolean, allowErrors = false) => {
    if (!run) return;
    setFinalizing(true);
    try {
      // Iter 650 — hard timeout so a hung request can't freeze the button.
      const r = await withTimeout(api<{ ok: boolean; finalized_at?: string }>(
        `/admin/compliance-salary-runs/${run.run_id}/finalize`,
        { method: "POST", body: { allow_warnings: allowWarnings, allow_errors: allowErrors } },
      ), 90000, "Finalize & Lock");
      void r;
      setLockCheck(null);
      // Iter 256 (user request) — after Finalize & Lock the front page is
      // CLEARED so the next batch starts fresh (run stays in Past Runs).
      setRun(null);
      setEmpType("all");
      await loadRuns();
      showMsg("Run finalized ✓ — locked & moved to Past Runs. Page cleared for the next batch.");
      setReportsFor({
        run_id: run.run_id, month: run.month, note: "Finalized 🔒",
        group: (run as any).employee_type || (empType !== "all" ? empType : "All Groups"),
      });
    } catch (e: any) {
      // Iter 654 (user bug — "Still not able to Lock") — NEVER blame the
      // PF/ESIC validation (it is non-blocking since Iter 423b). Show the
      // REAL failure so the admin knows what actually went wrong.
      const status = e?.status;
      let why = typeof e?.message === "string" && e.message
        ? e.message : "Unknown error";
      if (status === 401 || status === 403) {
        why = "Your login session expired — please log in again and retry the lock.";
      } else if (status === 413) {
        why = "The salary sheet is too large for the server to accept (HTTP 413) — please retry; if it repeats, contact support.";
      }
      showMsg(`Salary Lock FAILED — ${why}${status ? ` (HTTP ${status})` : ""}`);
    } finally { setFinalizing(false); }
  };

  // Iter 650 (user bug — "press Lock, nothing happens") — a hung request
  // could leave `finalizing` stuck true, silently swallowing every later
  // click. Every finalize step now has a hard timeout and the guard talks.
  const withTimeout = <T,>(p: Promise<T>, ms: number, what: string) =>
    Promise.race([
      p,
      new Promise<never>((_, rej) =>
        setTimeout(() => rej(new Error(`${what} timed out — please retry`)), ms)),
    ]);

  const finalizeRun = async () => {
    if (!run) return;
    if (finalizing) {
      showToast("Finalize already in progress — please wait…");
      return;
    }
    const okGo = await confirmYesNo(
      "Finalize this compliance run? It becomes LOCKED — nobody can change it without Super Admin approval.",
    );
    if (!okGo) return;
    setFinalizing(true);
    try {
      // Iter 374 (user bug) — FLUSH pending grid edits BEFORE locking
      // (Finalize is an explicit action, so saving here is expected).
      try {
        await withTimeout(api(`/admin/compliance-salary-runs/${run.run_id}/save-rows`, {
          method: "POST",
          body: { rows: run.rows, totals: run.totals },
        }), 90000, "Saving the grid");
        setUnsavedEdits(false);
      } catch (e: any) {
        // Iter 650 — never silent: tell the admin and continue to lock.
        showToast(`Grid save skipped (${e?.message || "error"}) — continuing to lock`);
      }
      // Iter 388 (Phase 3) — automatic PF/ESIC validation before the lock.
      // Errors ALWAYS block; warnings block unless a Super Admin overrides.
      try {
        const v = await withTimeout(
          api<any>(`/admin/compliance-salary-runs/${run.run_id}/validate`),
          45000, "PF/ESIC validation");
        if ((v?.errors_count || 0) > 0 || (v?.warnings_count || 0) > 0) {
          setLockCheck(v);
          setFinalizing(false);
          return;
        }
      } catch { /* validation fetch failed — the server re-validates on finalize */ }
    } catch { /* noop */ }
    await doFinalize(false);
  };

  // Iter 126h — Draft / lock workflow.
  // Iter 145 (P0 fix) — "Save as Draft" now actually PERSISTS the edited
  // grid (Present Days / Others / Other Deduction) to the backend. It used
  // to be a no-op, so every edit vanished when the run was reopened.
  const [savingDraft, setSavingDraft] = useState(false);
  // Iter 616 (user rule) — AUTO-SAVE REMOVED. The sheet is stored ONLY
  // when the admin explicitly clicks "Save as Draft" (Finalize still
  // flushes the grid first, since that is an explicit action too). We
  // now just track a dirty flag to warn about unsaved edits.
  const [unsavedEdits, setUnsavedEdits] = useState(false);
  // Iter 636 (user request) — compact header state: auto-collapse the
  // setup cards whenever a run is loaded on screen.
  const [setupCollapsed, setSetupCollapsed] = useState(false);
  const runIdOnScreen = (run as any)?.run_id || null;
  useEffect(() => { setSetupCollapsed(!!runIdOnScreen); }, [runIdOnScreen]);
  // Iter 657 — re-measure the grid's top offset whenever the layout above
  // it changes (run loaded / setup cards collapsed).
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const t = setTimeout(() => {
      try {
        const el: any = gridWrapRef.current;
        const rect = el?.getBoundingClientRect?.();
        if (rect && rect.top > 40 && rect.top < 600) setGridTopPx(Math.round(rect.top));
      } catch { /* keep default */ }
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, setupCollapsed]);
  const dirtyRunRef = useRef<string | null>(null);
  useEffect(() => {
    if (run && dirtyRunRef.current !== run.run_id) {
      dirtyRunRef.current = run.run_id;
      setUnsavedEdits(false); // fresh run opened/computed — nothing edited yet
    }
  }, [run]);
  const saveAsDraft = async () => {
    if (!run || savingDraft) return;
    if ((run as any).finalized) {
      showMsg("This run is FINALIZED — Save as Draft is not allowed. Use Unlock Request to de-finalize first.");
      return;
    }
    setSavingDraft(true);
    try {
      await api(`/admin/compliance-salary-runs/${run.run_id}/save-rows`, {
        method: "POST",
        body: { rows: run.rows, totals: run.totals },
      });
      await loadRuns();
      setUnsavedEdits(false);
      showMsg("Saved as draft ✓ — your edits are stored and will be there when you reopen this run.");
      setReportsFor({
        run_id: run.run_id, month: run.month, note: "Saved as draft ✓",
        group: (run as any).employee_type || (empType !== "all" ? empType : "All Groups"),
      });
    } catch (e: any) {
      showMsg(e?.message || "Draft save failed");
    } finally { setSavingDraft(false); }
  };

  // Iter 616 (user rule) — the old 2.5s debounced auto-save is GONE:
  // grid edits now only mark the sheet as having unsaved changes.
  const markGridDirty = useCallback(() => setUnsavedEdits(true), []);

  // Iter 634 (user request) — AUTO-SAVE RESTORED as a 1-MINUTE timer:
  // while a run with unsaved edits is open, the sheet is silently
  // persisted every 60 seconds (same save-rows call as "Save as Draft"),
  // so work is never lost to a refresh or closed tab. Finalized runs are
  // never touched; a failed autosave retries next minute.
  const runRef = useRef<any>(null);
  useEffect(() => { runRef.current = run; }, [run]);
  const unsavedRef = useRef(false);
  useEffect(() => { unsavedRef.current = unsavedEdits; }, [unsavedEdits]);
  const [lastAutoSave, setLastAutoSave] = useState<string>("");
  const autoSaveBusy = useRef(false);
  useEffect(() => {
    const id = setInterval(async () => {
      const r = runRef.current;
      if (!r || (r as any).finalized || !unsavedRef.current || autoSaveBusy.current) return;
      autoSaveBusy.current = true;
      try {
        await api(`/admin/compliance-salary-runs/${r.run_id}/save-rows`, {
          method: "POST", body: { rows: r.rows, totals: r.totals },
        });
        setUnsavedEdits(false);
        setLastAutoSave(new Date().toLocaleTimeString("en-IN",
          { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
      } catch { /* silent — retried next minute; manual Save still works */ }
      finally { autoSaveBusy.current = false; }
    }, 60000);
    return () => clearInterval(id);
  }, []);

  // Iter 634 (user request) — UNSAVED CHANGES PROTECTION: refreshing or
  // closing the browser tab with unsaved grid edits asks for confirmation.
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const w = (globalThis as any).window;
    if (!w?.addEventListener) return;
    const h = (e: any) => {
      if (unsavedRef.current) { e.preventDefault(); e.returnValue = ""; }
    };
    w.addEventListener("beforeunload", h);
    return () => w.removeEventListener("beforeunload", h);
  }, []);

  const [unlockBusy, setUnlockBusy] = useState(false);
  const [pendingUnlockReq, setPendingUnlockReq] = useState<any | null>(null);
  const checkUnlockRequests = useCallback(async (runId: string) => {
    try {
      const r = await api<{ requests: any[] }>(
        `/admin/salary-unlock-requests?run_id=${runId}&status=pending`,
      );
      setPendingUnlockReq((r.requests || [])[0] || null);
    } catch { setPendingUnlockReq(null); }
  }, []);
  const runFinalized = !!(run as any)?.finalized;
  useEffect(() => {
    if (run?.run_id && runFinalized) checkUnlockRequests(run.run_id);
    else setPendingUnlockReq(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.run_id, runFinalized, checkUnlockRequests]);

  const requestUnlock = async () => {
    if (!run || unlockBusy) return;
    let reason = "";
    if (Platform.OS === "web") {
      const v = globalThis.prompt(
        "Why do you need to change this FINALIZED salary? (sent to the Super Admin for approval)",
      );
      if (v === null) return;
      reason = v;
    }
    setUnlockBusy(true);
    try {
      const r = await api<{ ok: boolean; unlocked?: boolean; pending?: boolean; message?: string }>(
        `/admin/compliance-salary-runs/${run.run_id}/unlock-request`,
        { method: "POST", body: { reason } },
      );
      if (r.unlocked) {
        setRun({ ...(run as any), finalized: false } as any);
        await loadRuns();
        showMsg("Run unlocked ✓ — you can make changes now.");
      } else {
        showMsg(r.message || "Unlock request sent for Super Admin approval.");
        checkUnlockRequests(run.run_id);
      }
    } catch (e: any) {
      showMsg(e?.message || "Unlock request failed");
    } finally { setUnlockBusy(false); }
  };

  const decideUnlock = async (approve: boolean) => {
    if (!pendingUnlockReq || unlockBusy) return;
    setUnlockBusy(true);
    try {
      await api(`/admin/salary-unlock-requests/${pendingUnlockReq.req_id}/decide`, {
        method: "POST", body: { approve },
      });
      if (approve && run) {
        setRun({ ...(run as any), finalized: false } as any);
        await loadRuns();
      }
      setPendingUnlockReq(null);
      showMsg(approve ? "Unlock APPROVED ✓ — run is editable again." : "Unlock request rejected.");
    } catch (e: any) {
      showMsg(e?.message || "Decision failed");
    } finally { setUnlockBusy(false); }
  };

  // Iter 371 (user request) — one-tap unlock of the month's FINALIZED run
  // straight from the Configure batch card (Super / Sub Admins).
  const unlockExisting = async () => {
    if (!finalizedExisting || unlockBusy) return;
    const ok = await confirmYesNo(
      `UNLOCK the FINALIZED salary for ${finalizedExisting.month}?\n\n` +
      "The run becomes editable again and can be reprocessed.",
    );
    if (!ok) return;
    setUnlockBusy(true);
    try {
      const r = await api<{ ok: boolean; unlocked?: boolean; message?: string }>(
        `/admin/compliance-salary-runs/${finalizedExisting.run_id}/unlock-request`,
        { method: "POST", body: { reason: "Unlocked from Configure batch" } },
      );
      if (r.unlocked) {
        if (run?.run_id === finalizedExisting.run_id) {
          setRun({ ...(run as any), finalized: false } as any);
        }
        await loadRuns();
        showMsg("Salary unlocked ✓ — you can process/edit this month again.");
      } else {
        showMsg(r.message || "Unlock request sent for approval.");
      }
    } catch (e: any) {
      showMsg(e?.message || "Unlock failed");
    } finally { setUnlockBusy(false); }
  };

  const downloadFile = async (kind: "csv" | "pdf" | "pdf2" | "xlsx" | "ecr" | "esic-mc" | "esic-reg") => {
    if (!run || downloading) return;
    setDownloading(true);
    try {
      const _pg = `sort_by=${pdfSort}&group_by=`;
      const url =
        kind === "csv"
          ? `/admin/compliance-salary-runs/${run.run_id}/export.csv`
          : kind === "xlsx"
            ? `/admin/compliance-salary-runs/${run.run_id}/export.xlsx`
            : kind === "pdf"
              ? `/admin/compliance-salary-runs/${run.run_id}/register.pdf?${_pg}`
              : kind === "pdf2"
                ? `/admin/compliance-salary-runs/${run.run_id}/register.pdf?variant=2&${_pg}`
                : kind === "ecr"
                  ? `/admin/compliance-salary-runs/${run.run_id}/pf-ecr.txt`
                  : kind === "esic-mc"
                    ? `/admin/compliance-salary-runs/${run.run_id}/esic-mc.csv`
                    : `/admin/compliance-salary-runs/${run.run_id}/esic-ip-reg.csv`;
      const res = await apiBinary(url);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download =
          kind === "csv"
            ? `ComplianceSalary_${run.month}.csv`
            : kind === "xlsx"
              ? `ComplianceSalary_${run.month}.xlsx`
              : kind === "pdf"
                ? `ComplianceSalaryRegister_${run.month}.pdf`
                : kind === "pdf2"
                  ? `ComplianceSalaryRegister_Option2_${run.month}.pdf`
                  : kind === "ecr"
                    // Iter 446 — EPFO rejects non-word chars in filenames.
                    ? `PF_ECR_${String(run.month || "").replace(/^(\d{4})-(\d{2})$/, "$2$1")}.txt`
                    : kind === "esic-mc"
                      ? `ESIC_MC_${run.month}.csv`
                      : `ESIC_IP_Registration_${run.month}.csv`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      showMsg(e?.message || "Download failed");
    } finally { setDownloading(false); }
  };

  // Iter 633 (user request) — export EXACTLY what is displayed on screen
  // (including edits not yet saved as draft). Nothing is persisted.
  const exportDisplayed = async () => {
    if (!run || downloading) return;
    setDownloading(true);
    try {
      const res = await apiBinary("/admin/compliance-salary-runs/export-display.xlsx", {
        method: "POST",
        body: {
          month: run.month,
          company_id: (run as any).company_id || undefined,
          rows: (run as any).rows || [],
        },
      });
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = `ComplianceSalary_Displayed_${run.month}.xlsx`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      showMsg(e?.message || "Export failed");
    } finally { setDownloading(false); }
  };

  // Iter 438 — download reports by run id (works even after Finalize
  // clears the page — the modal keeps the finalized run's id).
  const downloadRunReports = async (
    runId: string,
    m: string,
    formats: ReportFormat[],
  ) => {
    for (const f of formats) {
      const url = f === "pdf" || f === "pdf2"
        ? `/admin/compliance-salary-runs/${runId}/register.pdf?variant=${f === "pdf2" ? 2 : 1}&sort_by=${pdfSort}&group_by=`
        : `/admin/compliance-salary-runs/${runId}/export.${f}`;
      const res = await apiBinary(url);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = f === "pdf"
          ? `ComplianceSalaryRegister_${m}.pdf`
          : f === "pdf2"
            ? `ComplianceSalaryRegister_Option2_${m}.pdf`
            : `ComplianceSalary_${m}.${f}`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    }
  };

  const pushToPayslips = async () => {
    if (!run || pushing) return;
    setPushing(true);
    try {
      const r = await api<{ ok: boolean; payslips_count: number }>(
        `/admin/compliance-salary-runs/${run.run_id}/generate-payslips`,
        { method: "POST" },
      );
      await loadRuns();
      showMsg(
        `${r.payslips_count} compliance payslips pushed. Employees can now see them on the Documents → Payslips tab.`,
      );
    } catch (e: any) {
      showMsg(e?.message || "Push failed");
    } finally { setPushing(false); }
  };

  // Iter 396 — one-click WhatsApp payslip blast for this run's month.
  const sendWhatsAppBlast = async () => {
    if (!run || waBlasting) return;
    setWaBlasting(true);
    try {
      const cid = (run as any).company_id || activeCompanyId;
      const r = await api<{ ok: boolean; queued: number; skipped: number }>(
        `/admin/whatsapp/send-salary-slips?company_id=${encodeURIComponent(cid || "")}`,
        { method: "POST", body: { month: run.month } },
      );
      showMsg(
        `WhatsApp blast queued: ${r.queued} payslip PDF(s) for ${run.month}` +
        (r.skipped ? ` (${r.skipped} skipped — no number)` : "") +
        ". Track them in WhatsApp Center → History.",
      );
    } catch (e: any) {
      showMsg(e?.message || "WhatsApp blast failed");
    } finally { setWaBlasting(false); }
  };


  const openPastRun = async (r: CompRun) => {
    try {
      const j = await api<{ run: CompRun }>(
        `/admin/compliance-salary-runs/${r.run_id}`,
      );
      setRun(j.run);
      setMonth(j.run.month);
      setMonthDaysOverride(String(j.run.month_days));
      setEmpType(j.run.employee_type || "all");
      // Iter 85 — rollFilter is now hard-locked to "on" (see state
      // declaration), so we no longer restore it from past runs.
      // Structure % + statutory config restoration continues below.
    } catch (e: any) {
      showMsg(e?.message || "Failed to load run");
    }
  };

  // Iter 91 — deep link from Utilities → Past Salary Runs (?run_id=…)
  const urlParams = useLocalSearchParams<{ run_id?: string }>();
  useEffect(() => {
    if (urlParams.run_id && isAdmin) {
      // Iter 656 — if the keep-alive snapshot holds this exact run
      // (workspace tab switch), let the restore effect below bring it
      // back WITH the unsaved edits instead of refetching a stale copy.
      if (compRunKeepAlive?.run?.run_id === String(urlParams.run_id)) return;
      openPastRun({ run_id: String(urlParams.run_id) } as CompRun);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlParams.run_id, isAdmin]);

  // Iter 656 — restore the run that was on screen before a workspace tab
  // switch remounted us (deep links via ?run_id= take precedence).
  const keepAliveRestoredRef = useRef(false);
  useEffect(() => {
    if (!isAdmin || keepAliveRestoredRef.current) return;
    const snap = compRunKeepAlive;
    if (!snap?.run) return;
    if (urlParams.run_id && String(urlParams.run_id) !== snap.run.run_id) return;
    if (Date.now() - snap.ts > 6 * 3600 * 1000) { compRunKeepAlive = null; return; }
    if (!activeCompanyId || (snap.companyId && snap.companyId !== activeCompanyId)) return;
    keepAliveRestoredRef.current = true;
    setRun(snap.run);
    setMonth(snap.month);
    setMonthDaysOverride(snap.monthDays);
    setEmpType(snap.empType);
    if (snap.unsaved) {
      setUnsavedEdits(true);
      showToast("Restored your open run with UNSAVED edits — remember to Save as Draft / Finalize.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin, activeCompanyId]);

  // Iter 656 — keep the snapshot in sync with what's on screen.
  const hadRunRef = useRef(false);
  useEffect(() => {
    if (run && !(run as any).finalized) {
      hadRunRef.current = true;
      compRunKeepAlive = {
        companyId: activeCompanyId, run, month,
        monthDays: monthDaysOverride, empType,
        unsaved: unsavedEdits, ts: Date.now(),
      };
    } else if (!run && hadRunRef.current) {
      // Run explicitly cleared this session (Finalize / Delete / firm
      // change) — drop the snapshot so it doesn't come back.
      compRunKeepAlive = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, month, monthDaysOverride, empType, unsavedEdits]);

  // Iter 162 auto-opened the LAST processed run on screen load. Iter 306
  // (user request #6) — REMOVED: the Compliance Salary screen must show
  // data ONLY after the admin presses "Process" (deep links from Past
  // Salary Runs still open a specific run via ?run_id=).

  /**
   * Iter 85 — Client-side re-computation when the admin edits an
   * employee's Present Days in the Compliance Salary grid.
   *
   * The backend originally derived every head (basic, hra, …, PF, ESIC,
   * PT, TDS, net) from ``present_days`` + firm structure %s. We mirror
   * that math here so the grid updates instantly and totals stay in
   * sync until the admin re-saves the run to the backend.
   *
   * Assumptions (kept simple):
   *   • Full monthly heads are stored as-is on the row.
   *   • Actual paid amount = full × (present_days / month_days).
   *   • PF wages & ESIC wage base are also pro-rated by PD.
   *   • Rates for PF (12% + 12% + 0.5%) and ESIC (0.75% + 3.25%) come
   *     from the run's statutory_cfg when present, else fall back to
   *     statutory defaults.
   */
  /* --- Iter 85 helpers used by the Compliance Grid --- */
  // Refs to each editable "Present Days" input so Arrow-Up/Down can
  // move focus between rows on the web portal.
  const pdRefs = useRef<Record<number, any>>({});

  // Iter 649 (user request) — ↑/↓ ARROW-KEY row navigation (web only).
  // Iter 651 (user request) — ENTER opens the highlighted row's Present
  // Days cell; Ctrl+S saves; Ctrl+L opens Finalize & Lock. Pure UI.
  useEffect(() => {
    if (Platform.OS !== "web" || !run) return;
    const onKey = (e: any) => {
      // Ctrl+S / Ctrl+L work even while typing in a cell.
      if ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === "s") {
        e.preventDefault();
        if (!savingDraft) void saveAsDraft();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === "l") {
        e.preventDefault();
        if (!(run as any).finalized) void finalizeRun();
        return;
      }
      const isNav = e.key === "ArrowDown" || e.key === "ArrowUp";
      if (!isNav && e.key !== "Enter") return;
      const tag = String(e.target?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      const rows = sortRows(run.rows.filter((r) =>
        rowPassesColFilters(r, colFilters, COL_FILTER_GETTERS)));
      if (!rows.length) return;
      if (e.key === "Enter") {
        const cur = rows.findIndex((r) => r.user_id === hlRow);
        if (cur < 0) return;
        e.preventDefault();
        pdRefs.current[cur]?.focus?.();
        return;
      }
      e.preventDefault();
      const cur = rows.findIndex((r) => r.user_id === hlRow);
      const next = cur < 0
        ? (e.key === "ArrowDown" ? 0 : rows.length - 1)
        : Math.max(0, Math.min(rows.length - 1,
            cur + (e.key === "ArrowDown" ? 1 : -1)));
      const uid = rows[next].user_id;
      setHlRow(uid);
      setTimeout(() => {
        (globalThis as any).document?.getElementById?.(`csr-row-${uid}`)
          ?.scrollIntoView?.({ block: "nearest" });
      }, 0);
    };
    (globalThis as any).document?.addEventListener?.("keydown", onKey);
    return () => (globalThis as any).document?.removeEventListener?.("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, hlRow, colFilters, colSort, savingDraft, finalizing]);
  // Iter 256 (user request) — spreadsheet-style Arrow key navigation
  // across ALL editable cells (Present Days → Others → OT Amt → TDS →
  // Other), following the Firm Master's enabled heads.
  const cellRefs = useRef<Record<string, any>>({});
  // Iter 377 (user request) — the grid must ALWAYS follow the Firm
  // Master's enabled Allowances/Deductions, for BOTH the Master Salary
  // and the Calculated Salary columns. Runs saved before the masks were
  // stamped on rows (old / copied / legacy runs) fall back to this
  // live Firm Master mask.
  const [fmMask, setFmMask] = useState<{ en?: string[]; ed?: string[] }>({});
  const fmMaskCid = (run?.rows?.[0] as any)?.company_id
    || (run as any)?.company_id || activeCompanyId;

  // Iter 621 (user-approved improvement) — active PF Proration Method label
  // so admins instantly see which rule the PF column follows.
  const pfMethodLabel = (() => {
    if (!run) return "";
    const m = String(
      (((run as any).statutory_effective || run.statutory_cfg || {}) as any)
        .pf_proration_method || "calendar_days",
    ).toLowerCase();
    return m === "working_days" ? "PF ÷26 (Working Days)"
      : m === "attendance_days" ? "PF ÷30 (Attendance Days)"
      : m === "paid_days" ? "PF full wages (Paid Days)"
      : m === "none" ? "PF no proration"
      : `PF ÷${run.month_days} (Month Days)`;
  })();
  useEffect(() => {
    if (!fmMaskCid) {
      setFmMask({});
      return;
    }
    api<any>(`/admin/firm-master/${fmMaskCid}`)
      .then((res) => {
        const f = res?.master || {};
        // Only a STORED firm master drives the mask (mirrors the backend
        // rule: "None only when never configured").
        const stored = !!(f.updated_at || f.updated_by);
        const allow = f.allowances || {};
        const ded = f.deductions || {};
        const AMAP: Record<string, string> = {
          "HRA": "hra", "CONV.": "conveyance",
          "MEDICAL ALLOWANCES": "medical", "OTH. ALLOW.": "special",
          "OTHER MISC.ALLOWANCE": "others",
          // Iter 644 — OVER TIME toggle drives the OT columns.
          "OVER TIME": "ot",
        };
        const en = stored
          ? ["basic",
             ...Object.entries(AMAP).filter(([lbl]) => !!allow[lbl]).map(([, k]) => k)]
          : undefined;
        const epfAp = (f.epf || {}).applicable;
        const esiAp = (f.esi || {}).applicable;
        const ed2: string[] = [];
        if (epfAp != null ? epfAp : !!ded.PF) ed2.push("pf");
        if (esiAp != null ? esiAp : !!ded.ESI) ed2.push("esi");
        if (ded.PT) ed2.push("pt");
        if (ded.TDS || ded["I. TAX"]) ed2.push("tds");
        // Iter 443 — Master-linked ADVANCE / OTH. DEDUC. columns.
        if (ded.ADVANCE) ed2.push("advance");
        if (ded["OTH. DEDUC."]) ed2.push("other");
        setFmMask({ en, ed: stored ? ed2 : undefined });
      })
      .catch(() => setFmMask({}));
  }, [fmMaskCid]);
  // Iter 644 (user bug — "OT not allowed but showing") — the OT Hrs /
  // OT Amt* columns follow the Firm-Master "OVER TIME" toggle. Legacy runs
  // whose rows carry OT amounts keep the columns so old data stays visible.
  const hasOtCol = useMemo(() => {
    const rows: any[] = (run?.rows as any[]) || [];
    const en = (rows[0]?.enabled_allowances ?? fmMask.en) as string[] | undefined;
    return !en || en.includes("ot")
      || rows.some((r) => (Number(r.ot_pay) || 0) !== 0 || (Number(r.ot_hours) || 0) !== 0);
  }, [run, fmMask]);
  // Iter 644 (user request — "INCENTIVE ticked but not showing") — dynamic
  // custom allowance head columns (decomposed out of the Others bucket by
  // the backend; the Others columns display the remainder).
  const allowLabels = useMemo(
    () => (((run?.rows?.[0] as any)?.allowance_head_labels as string[]) || []),
    [run],
  );
  const allowHeadsPaid = (r: any) => allowLabels.reduce(
    (s, l) => s + (Number(((r as any).allowance_heads || {})[l]) || 0), 0);
  const allowHeadsMaster = (r: any) => allowLabels.reduce(
    (s, l) => s + (Number(((r as any).allowance_heads_master || {})[l]) || 0), 0);
  const navCols = useMemo(() => {
    const r0: any = run?.rows?.[0] || {};
    const en = (r0.enabled_allowances ?? fmMask.en) as string[] | undefined;
    const ed = (r0.enabled_deductions ?? fmMask.ed) as string[] | undefined;
    const cols: string[] = ["pd"];
    // Iter 727 — "OTH. ALLOW." (special) is editable too.
    if (!en || en.includes("special")) cols.push("special");
    if (!en || en.includes("others")) cols.push("others");
    if (hasOtCol) cols.push("ot_pay");
    if (!ed || ed.includes("tds")) cols.push("tds");
    if (!ed || ed.includes("advance")) cols.push("advance_recovery");
    if (!ed || ed.includes("other")) cols.push("other_deduction");
    return cols;
  }, [run, fmMask, hasOtCol]);
  const focusCell = (col: string, idx: number) => {
    const el: any = col === "pd" ? pdRefs.current[idx] : cellRefs.current[`${col}:${idx}`];
    if (el && typeof el.focus === "function") el.focus();
  };
  // Iter 618 (user P0 — data integrity) — Excel-style navigation: arrow
  // keys ONLY move focus between cells and can NEVER mutate a value.
  const navigateFrom = (col: string, idx: number, key: string) => {
    if (key === "ArrowUp" || key === "ArrowDown") {
      focusCell(col, idx + (key === "ArrowDown" ? 1 : -1));
    } else if (key === "ArrowLeft" || key === "ArrowRight") {
      const ci = navCols.indexOf(col);
      const next = navCols[ci + (key === "ArrowRight" ? 1 : -1)];
      if (next) focusCell(next, idx);
    }
  };

  // Iter 620 (user bug — SEO GROWTH "PF changed after Save + Reprocess") —
  // the grid's client-side PF recompute used present ÷ month_days ALWAYS,
  // but the server honours the firm's PF Proration Method (working_days
  // ÷26, attendance_days ÷30, paid_days, none). The mismatch made PF flip
  // between the on-screen value and the server value on save/reprocess.
  // Mirrors utils/compliance_salary.py::_proration_factor.
  const pfProrationFactor = (method: any, pd: number, monthDays: number) => {
    const m = String(method || "calendar_days").trim().toLowerCase();
    if (m === "none") return 1;
    if (m === "paid_days") return pd > 0 ? 1 : 0;
    const div = m === "working_days" ? 26
      : m === "attendance_days" ? 30
      : Math.max(1, monthDays);
    return Math.min(1, pd / div);
  };

  // Client-side setter for individual row fields (Others allowance,
  // Other deduction, OT Amount, TDS — Iter 230). Recomputes Gross + Net
  // locally so the grid stays in sync while editing.
  // Iter 647 (user request — "Allow us to edit Incentive column") —
  // editing a custom allowance head cell adjusts that head AND the row's
  // Others bucket total (gross/net/PF/ESIC refresh via the same pipeline
  // as an Others* edit). The edit is stamped manual so reprocess keeps it.
  const updateAllowanceHead = (userId: string, label: string, value: number) => {
    const r = (run?.rows || []).find((x) => x.user_id === userId) as any;
    if (!r) return;
    const old = Number((r.allowance_heads || {})[label]) || 0;
    const delta = value - old;
    setRun((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        rows: prev.rows.map((x) => x.user_id === userId
          ? ({
              ...x,
              allowance_heads: { ...(((x as any).allowance_heads) || {}), [label]: value },
              manual_fields: Array.from(new Set([...((((x as any).manual_fields) as string[]) || []), "allowance_heads"])),
              manual_override: true,
            } as any)
          : x),
      } as any;
    });
    if (delta) updateRowField(userId, "others", (Number(r.others) || 0) + delta);
  };

  const updateRowField = (
    userId: string,
    key: "others" | "special" | "other_deduction" | "advance_recovery" | "ot_pay" | "tds" | "esic_leave_days",
    value: number,
  ) => {
    setRun((prev) => {
      if (!prev) return prev;
      const rows = prev.rows.map((r) => {
        if (r.user_id !== userId) return r;
        const next = { ...r, [key]: value } as any;
        // Iter 374 (user bug) — EVERY manual edit is stamped on the row so
        // a reprocess (e.g. after unlock) NEVER removes the typed amount.
        next.manual_override = true;
        next.manual_fields = Array.from(
          new Set([...(((r as any).manual_fields) || []), key]),
        );
        // Iter 343b (user request) — imported (Freeze) runs: manual edits
        // to OT / Other Allowances STICK (reprocess keeps them); the Freeze
        // salary stays as display-only comparison data.
        if ((key === "ot_pay" || key === "others" || key === "special") && (r as any).imported_gross != null) {
          next.difference_allocation_head = "Manual";
        }
        if (key === "others" || key === "special") {
          const gross = (next.basic || 0) + (next.hra || 0) + (next.conveyance || 0)
            + (next.medical || 0) + (next.special || 0) + (next.others || 0);
          next.monthly_gross = Math.round(gross);
          next.gross_paid = Math.round(gross + (next.ot_pay || 0));
        }
        if (key === "ot_pay") {
          // Gross Paid = Monthly Gross (heads) + OT Amount.
          next.gross_paid = Math.round((next.monthly_gross || 0) + value);
        }
        // Iter 406 (user rule — "Gross Earning includes OT") — editing the
        // OT Amt / Others also refreshes the PF & ESIC wage bases on the
        // FULL Gross Earning including OT (mirrors utils/compliance_salary.py).
        if (key === "ot_pay" || key === "others" || key === "special") {
          const stat = ((prev as any).statutory_effective || (prev as any).statutory_cfg || {}) as any;
          const floorPct = Number(stat.stat_wage_floor_pct ?? 50) / 100;
          const wageRuleOn = stat.wage_definition_rule_enabled !== false;
          const pfCap = Number(stat.pf_wage_cap ?? 15000);
          // Iter 597 — Contractor Wage-Based PF mirror (utils/compliance_salary.py).
          const contractorOn = String(stat.contractor_pf_mode || "standard") === "contractor_wage_based";
          const contractorFixed = String(stat.contractor_partial_month_rule || "adopted_wage") === "adopted_wage";
          const grossEarn = Number(next.gross_paid || 0);
          const monthDays2 = Math.max(1, Number((prev as any).month_days) || 30);
          // Iter 620 — PF honours the configured proration method.
          const pfRatio2 = pfProrationFactor(
            stat.pf_proration_method, Number(next.present_days) || 0, monthDays2);
          const pfBasicFull = Number(next.pf_basic || 0);
          const pfOn = (next.pf_eligible !== undefined
            ? next.pf_eligible !== false : next.pf_applicable !== false)
            && pfBasicFull > 0 && grossEarn > 0;
          if (pfOn) {
            // Iter 471 (user bug — daily-rate) — daily-rated rows: PF Basic
            // is a PER-DAY figure; earned = rate × days, ceiling checks use
            // the full-month equivalent (mirrors utils/compliance_salary.py).
            const pd471b = Number(next.present_days) || 0;
            const pfBasicPro = next.salary_mode === "monthly" ? pfBasicFull * pfRatio2
              : next.salary_mode === "daily" ? pfBasicFull * pd471b : pfBasicFull;
            const pfBasicMonth = next.salary_mode === "daily"
              ? pfBasicFull * monthDays2 : pfBasicFull;
            const pfBase = pfBasicMonth < pfCap && wageRuleOn
              ? Math.max(pfBasicPro, grossEarn * floorPct) : pfBasicPro;
            // Iter 456 (user final PF Engine spec) — PF Basic ≤ cap → PF
            // wage = max(earned PF Basic, floor% Gross) capped at the
            // ceiling; PF Basic ABOVE the cap → ADOPTED: PF on the FULL
            // earned PF Basic (no cap).
            // Iter 457 (MILAP bug) — Higher PF on the employee's OWN wage:
            // Higher PF Wage (pro-rated) → earned PF Basic → wage base.
            const hiActive1 = (next as any).pf_higher_active === true ||
              String((next as any).pf_contribution_type || "").toLowerCase() === "higher";
            const hiWage1 = Number((next as any).higher_pf_wage || 0);
            const pfWages = hiActive1
              ? (hiWage1 > 0
                // Iter 729 (user final rule) — Higher PF (Actual Wages) vs
                // floor% Gross: PF on WHICHEVER IS HIGHER (extras included).
                ? Math.max(
                  grossEarn * floorPct,
                  contractorOn && contractorFixed
                    ? hiWage1 // Iter 597 Rule 4 — fixed adopted wage (company policy)
                    : (next.salary_mode === "monthly" ? hiWage1 * pfRatio2 : hiWage1))
                : (pfBasicFull > 0
                // Iter 729b — adopted PF Basic also competes with floor% Gross.
                ? Math.max(
                  grossEarn * floorPct,
                  contractorOn && contractorFixed ? pfBasicMonth : pfBasicPro)
                : Math.max(pfBase, Number(next.basic || 0), grossEarn * floorPct)))
              : (next.intl_worker
                ? pfBase
                // Iter 597 Rules 1-3 — contractor mode: PF on the earned PF
                // Basic only (no 50% floor), capped at the ceiling.
                : contractorOn
                  ? Math.min(pfBasicPro, pfCap)
                  : (pfBasicMonth > pfCap
                    ? Math.max(pfBasicPro, grossEarn * floorPct)
                    : Math.min(pfBase, pfCap)));
            const pfEmpRate = Number(stat.pf_percent_employee ?? 12) / 100;
            const pfErEpfRate = Number(stat.pf_percent_employer_epf ?? 3.67) / 100;
            const pfErEpsRate = Number(stat.pf_percent_employer_eps ?? 8.33) / 100;
            // Iter 456 — EPS always capped at the ceiling; wages above the
            // cap follow the ECR split (ER total 12%, remainder → ER EPF).
            const epsWages1 = next.higher_pension ? pfBase : Math.min(pfWages, pfCap);
            let eps = epsWages1 * pfErEpsRate;
            let epf = (pfWages > pfCap && !next.higher_pension)
              ? pfWages * (pfErEpfRate + pfErEpsRate) - eps
              : pfWages * pfErEpfRate;
            if (next.eps_disabled) { epf += eps; eps = 0; }
            next.pf_wages = Math.round(pfWages);
            // Iter 616 (user report — "PF wrong then auto-rectifies") — the
            // OT/Others quick-recalc DROPPED the employee's VPF from PF(E);
            // the server added it back on save/reprocess. Mirror the server.
            next.pf_employee = Math.round(
              pfWages * pfEmpRate + (Number((next as any).vpf_amount) || 0));
            next.pf_employer_epf = Math.round(epf);
            next.pf_employer_eps = Math.round(eps);
            next.pf_employer_total = next.pf_employer_epf + next.pf_employer_eps;
            next.stat_wage_base = Math.round(Math.max(
              Number(next.basic || 0), grossEarn * floorPct));
          } else if (grossEarn <= 0) {
            // Iter 616 — zero-pay row: statutory must drop to 0 immediately
            // (stale figures previously lingered until the server recompute).
            next.pf_wages = next.pf_employee = 0;
            next.pf_employer_epf = next.pf_employer_eps = 0;
            next.pf_employer_total = 0;
            next.stat_wage_base = 0;
          }
          const esiOn = (next.esic_eligible !== undefined
            ? next.esic_eligible !== false : next.esic_applicable !== false)
            && grossEarn > 0;
          if (esiOn && Number(next.esic_employee || 0) >= 0 && next.esic_applicable !== false) {
            const hm = stat.head_mapping || null;
            const esicHeadOn = (k: string) => !hm || (hm[k] || {}).esic !== false;
            const esiActual = (["basic", "hra", "conveyance", "medical", "special", "others"] as const)
              .reduce((n, k) => n + (esicHeadOn(k) ? Number((next as any)[k] || 0) : 0), 0)
              + (esicHeadOn("ot") ? Number(next.ot_pay || 0) : 0);
            // Iter 456 (user rollback) — ESIC stays on the LEGACY rule:
            // max(Basic earned, floor% of Gross); the configurable ESIC
            // Wage Calculation Method was removed.
            const esiBase = wageRuleOn
              ? Math.max(Number(next.basic || 0), grossEarn * floorPct)
              : esiActual;
            const esiEmpRate = Number(stat.esic_percent_employee ?? 0.75) / 100;
            const esiErRate = Number(stat.esic_percent_employer ?? 3.25) / 100;
            next.esic_wage_base = Math.round(esiBase);
            next.esic_employee = Math.ceil(esiBase * esiEmpRate);
            next.esic_employer = Math.ceil(esiBase * esiErRate);
          } else if (grossEarn <= 0) {
            // Iter 616 — zero-pay row: ESIC drops to 0 immediately too.
            next.esic_wage_base = next.esic_employee = next.esic_employer = 0;
          }
        }
        const dedTotal = (next.pf_employee || 0) + (next.esic_employee || 0)
          + (next.pt || 0) + (next.tds || 0) + (next.other_deduction || 0)
          + (next.advance_recovery || 0);
        next.total_deduction = Math.round(dedTotal);
        next.net = Math.round((next.gross_paid || 0) - dedTotal);
        // Iter 343b — keep the Freeze comparison (display-only) in sync.
        if ((next as any).imported_gross != null) {
          (next as any).calculated_gross = next.gross_paid;
          (next as any).difference =
            Math.round(((next as any).imported_gross - (next.gross_paid || 0)) * 100) / 100;
          (next as any).freeze_status =
            Math.abs((next as any).difference) < 1 ? "matched" : "diff";
        }
        return next;
      });
      // Keep the totals strip in sync for the edited keys.
      const totals = { ...(prev.totals || {}) } as Record<string, number>;
      for (const k of ["others", "other_deduction", "advance_recovery", "ot_pay", "tds",
                       "monthly_gross", "gross_paid", "total_deduction", "net",
                       "pf_wages", "pf_employee", "pf_employer_epf",
                       "pf_employer_eps", "pf_employer_total",
                       "esic_wage_base", "esic_employee", "esic_employer"]) {
        totals[k] = Math.round(rows.reduce((s, r) => s + (Number((r as any)[k]) || 0), 0));
      }
      return { ...prev, rows, totals: totals as any };
    });
    markGridDirty(); // Iter 616 — mark unsaved (no auto-save)
  };

  const updatePresentDays = (userId: string, newPd: number) => {
    if (!run) return;
    const monthDays = Math.max(1, run.month_days || 30);
    // Iter 387 — prefer the FULL effective statutory snapshot saved on the
    // run (standard + firm overrides + per-run cfg); fall back to the old
    // per-run cfg for runs created before Iter 387.
    const stat = ((run as any).statutory_effective || run.statutory_cfg || {}) as any;
    const pfEmpRate = Number(stat.pf_percent_employee ?? stat.pf_employee_rate ?? 12) / 100;
    const pfErEpfRate = Number(stat.pf_percent_employer_epf ?? 3.67) / 100;
    const pfErEpsRate = Number(stat.pf_percent_employer_eps ?? 8.33) / 100;
    const pfCap = Number(stat.pf_wage_cap ?? 15000);
    const esiEmpRate = Number(stat.esic_percent_employee ?? stat.esic_employee_rate ?? 0.75) / 100;
    const esiErRate  = Number(stat.esic_percent_employer ?? stat.esic_employer_rate ?? 3.25) / 100;
    const esiThresh  = Number(stat.esic_gross_threshold ?? stat.esic_wage_threshold ?? 21000);

    setRun((prev) => {
      if (!prev) return prev;
      const rows = prev.rows.map((r) => {
        if (r.user_id !== userId) return r;

        // Iter 219 (user request) — allow HALF-DAY manual input: value is
        // clamped to half-day steps (.0 / .5) and the month-days cap.
        const pd = Math.max(0, Math.min(monthDays, Math.round((Number(newPd) || 0) * 2) / 2));
        const ratio = pd / monthDays;
        // Iter 620 — PF honours the configured proration method (the
        // earnings heads stay on present ÷ month_days).
        const pfRatio = pfProrationFactor(stat.pf_proration_method, pd, monthDays);

        // FULL monthly heads. The MASTER columns (basic_master, …) are the
        // authoritative full-month values — using them fixes rows that start
        // at 0 Present Days (no biometric attendance), where the old
        // "re-hydrate from paid ÷ oldRatio" approach yielded 0 forever.
        const heads: (keyof CompRow)[] = [
          "basic", "hra", "conveyance", "medical", "special", "others",
        ];
        const oldRatio = r.present_days / monthDays;
        const fullByHead: Record<string, number> = {};
        for (const h of heads) {
          const master = Number((r as any)[`${h as string}_master`] || 0);
          if (master > 0) {
            fullByHead[h as string] = master;
            continue;
          }
          const paid = Number((r as any)[h] || 0);
          fullByHead[h as string] = oldRatio > 0.001 ? paid / oldRatio : paid;
        }

        const paidBasic = fullByHead.basic * ratio;
        const paidHra = fullByHead.hra * ratio;
        const paidConv = fullByHead.conveyance * ratio;
        const paidMed = fullByHead.medical * ratio;
        const paidSpl = fullByHead.special * ratio;
        const paidOth = fullByHead.others * ratio;
        // Iter 230 (user bug) — whole-rupee consistency: Gross must equal
        // the SUM of the displayed (rounded) heads, never ₹1 off.
        const rHeads = {
          basic: Math.round(paidBasic), hra: Math.round(paidHra),
          conveyance: Math.round(paidConv), medical: Math.round(paidMed),
          special: Math.round(paidSpl), others: Math.round(paidOth),
        };
        const grossPaid = rHeads.basic + rHeads.hra + rHeads.conveyance
          + rHeads.medical + rHeads.special + rHeads.others;

        // Statutory wage base — mirrors utils/compliance_salary.py:
        // Iter 376 (user rule, replaces Iter 254) — PF wage base:
        //   • PF Basic BELOW the ₹15,000 cap → floor applies:
        //     wages = max(PF Basic, floor% of Gross Earning), capped at
        //     the PF wage cap.
        //   • PF Basic AT/ABOVE the cap → wages = the cap (₹15,000).
        // Iter 370 (user bug) — a 0-day first process stored
        // pf_applicable=false (zero-pay guard), which FROZE this client
        // recompute: typing days never brought PF/ESIC back until a second
        // "Salary Process" click. Use the days-independent eligibility
        // flags from the backend when present (old runs fall back to the
        // stored applicable flag).
        const pfBasicFull = Number((r as any).pf_basic || 0);
        const pfMasterOk = (r as any).pf_eligible !== undefined
          ? (r as any).pf_eligible !== false
          : r.pf_applicable !== false;
        const pfOn = pfMasterOk && pfBasicFull > 0;
        // Iter 471 (user bug — daily-rate) — daily rows: PF Basic is a
        // PER-DAY figure; earned = rate × days, ceiling checks on the
        // full-month equivalent (mirrors utils/compliance_salary.py).
        const pfBasicPro = (r as any).salary_mode === "monthly" ? pfBasicFull * pfRatio
          : (r as any).salary_mode === "daily" ? pfBasicFull * pd : pfBasicFull;
        const pfBasicMonth = (r as any).salary_mode === "daily"
          ? pfBasicFull * monthDays : pfBasicFull;
        const floorPct = Number(stat.stat_wage_floor_pct ?? 50) / 100;
        const grossEarn = grossPaid + Number((r as any).ot_pay || 0);
        // Iter 387 — Wage Definition Rule switch mirrors the engine.
        const wageRuleOn = stat.wage_definition_rule_enabled !== false;
        // Iter 597 — Contractor Wage-Based PF mirror (utils/compliance_salary.py).
        const contractorOn2 = String(stat.contractor_pf_mode || "standard") === "contractor_wage_based";
        const contractorFixed2 = String(stat.contractor_partial_month_rule || "adopted_wage") === "adopted_wage";
        const pfBase = pfBasicMonth < pfCap && wageRuleOn
          ? Math.max(pfBasicPro, grossEarn * floorPct)
          : pfBasicPro;
        // Iter 387 — International Worker: EPF without the wage ceiling.
        // Iter 427 (user bug — "PF correct only on SECOND process") — the
        // grid recompute now mirrors the engine's HIGHER PF rule: PF on the
        // WAGE BASE (max(Basic, floor% Gross)) with NO ceiling, so the very
        // FIRST process + typed days already show the right PF.
        const hiActive = (r as any).pf_higher_active === true ||
          String((r as any).pf_contribution_type || "").toLowerCase() === "higher";
        // Iter 457 (MILAP bug — Basic 2,30,000 / PF Basic 1,70,000 showed
        // PF 27,600) — Higher PF contributes on the employee's OWN PF wage:
        // Higher PF Wage (pro-rated) → earned PF Basic → wage base.
        const hiWageFull = Number((r as any).higher_pf_wage || 0);
        const pfWagesNew = pfOn
          ? (hiActive
            ? (hiWageFull > 0
              // Iter 729 (user final rule) — Higher PF (Actual Wages) vs
              // floor% Gross: PF on WHICHEVER IS HIGHER (extras included).
              ? Math.max(
                grossEarn * floorPct,
                contractorOn2 && contractorFixed2
                  ? hiWageFull // Iter 597 Rule 4 — fixed adopted wage (company policy)
                  : ((r as any).salary_mode === "monthly" ? hiWageFull * pfRatio : hiWageFull))
              : (pfBasicFull > 0
                // Iter 729b — adopted PF Basic also competes with floor% Gross.
                ? Math.max(
                  grossEarn * floorPct,
                  contractorOn2 && contractorFixed2 ? pfBasicMonth : pfBasicPro)
                : Math.max(pfBase, paidBasic, grossEarn * floorPct)))
            : ((r as any).intl_worker
              ? pfBase
              // Iter 597 Rules 1-3 — contractor mode: PF on the earned PF
              // Basic only (no 50% floor), capped at the ceiling.
              : contractorOn2
                ? Math.min(pfBasicPro, pfCap)
              // Iter 456 (user final PF Engine spec) — PF Basic ABOVE the
              // ceiling = ADOPTED Higher PF: PF on the FULL earned PF Basic
              // (no cap). Below/at the ceiling: PF wage = max(earned PF
              // Basic, floor% of Gross) capped at the ceiling.
              : (pfBasicMonth > pfCap
                // Iter 729b — adopted wage competes with floor% Gross.
                ? Math.max(pfBasicPro, grossEarn * floorPct)
                : Math.min(pfBase, pfCap))))
          : 0;
        // Iter 427 — VPF (employee side) survives the grid recompute:
        // scale the server-computed VPF with the new PF wages.
        const vpfPrev = Number((r as any).vpf_amount || 0);
        const pfWagesOld = Number((r as any).pf_wages || 0);
        const vpfNew = vpfPrev > 0 && pfWagesOld > 0
          ? vpfPrev * (pfWagesNew / pfWagesOld)
          : vpfPrev;
        const pfEmp = pfWagesNew * pfEmpRate + vpfNew;
        let pfErEpf: number;
        let pfErEps: number;
        if (hiActive) {
          // Iter 427 — mirror the engine's ECR split for Higher PF:
          // employer total on the FULL higher wage; EPS stays on the
          // statutory ceiling (unless Higher Pension); EPF = remainder.
          const erTot = pfWagesNew * (pfErEpfRate + pfErEpsRate);
          const epsWages = (r as any).higher_pension ? pfWagesNew : Math.min(pfWagesNew, pfCap);
          pfErEps = epsWages * pfErEpsRate;
          pfErEpf = erTot - pfErEps;
        } else {
          // Iter 456 — EPS always capped at the ceiling; statutory wages
          // ABOVE the cap (adopted PF Basic) follow the ECR split: ER total
          // 12% of the adopted wage, EPS capped, remainder → Employer EPF.
          const epsWages2 = (r as any).higher_pension && pfOn
            ? pfBase : Math.min(pfWagesNew, pfCap);
          pfErEps = epsWages2 * pfErEpsRate;
          pfErEpf = (pfWagesNew > pfCap && !(r as any).higher_pension)
            ? pfWagesNew * (pfErEpfRate + pfErEpsRate) - pfErEps
            : pfWagesNew * pfErEpfRate;
        }
        // Iter 341 — EPS Disable: full employer share goes to EPF.
        if ((r as any).eps_disabled) {
          pfErEpf += pfErEps;
          pfErEps = 0;
        }
        const pfErTot = pfErEpf + pfErEps;

        // ESIC (Iter 254 user directive): eligibility by the Employee
        // Master's Compliance Basic Salary ≤ the Compliance Settings limit
        // (falls back to full-month Basic when blank). Calculated ON
        // earned basic.
        // Iter 471 — daily/hourly rows carry a PER-DAY/PER-HOUR Compliance
        // Basic: eligibility compares the FULL-MONTH equivalent.
        const esiEligBasic0 = Number((r as any).compliance_basic || 0);
        const esiEligBasic = esiEligBasic0 > 0
          ? ((r as any).salary_mode === "daily" ? esiEligBasic0 * monthDays
            : esiEligBasic0)
          : fullByHead.basic;
        // Iter 370 — days-independent ESIC eligibility (see PF above).
        const esiMasterOk = (r as any).esic_eligible !== undefined
          ? (r as any).esic_eligible !== false
          : r.esic_applicable !== false;
        const esiApplicable = esiMasterOk && grossPaid > 0 && esiEligBasic <= esiThresh;
        // Iter 385 (user confirmed rule) — ESIC wage base = max(Basic,
        // floor% of Gross Earning): Basic when it exceeds 50% of gross,
        // else 50% of gross. Mirrors utils/compliance_salary.py.
        // Iter 387 — Wage Definition Rule OFF ⇒ base = Σ heads flagged
        // "ESIC Wage" in the Salary Head Mapping (+ OT when mapped).
        const hm = stat.head_mapping || null;
        const esicHeadOn = (k: string) => !hm || (hm[k] || {}).esic !== false;
        const esiActual2 = (["basic", "hra", "conveyance", "medical", "special", "others"] as const)
          .reduce((n, k) => n + (esicHeadOn(k) ? Number((rHeads as any)[k] || 0) : 0), 0)
          + (esicHeadOn("ot") ? Number((r as any).ot_pay || 0) : 0);
        // Iter 456 (user rollback) — ESIC stays on the LEGACY rule only:
        // max(Basic earned, floor% of Gross); Wage Rule OFF ⇒ Σ ESI heads.
        const esiBase = esiApplicable
          ? (wageRuleOn
            ? Math.max(paidBasic, grossEarn * floorPct)
            : esiActual2)
          : 0;
        const esiEmp = esiApplicable ? Math.ceil(esiBase * esiEmpRate) : 0;
        const esiEr  = esiApplicable ? Math.ceil(esiBase * esiErRate)  : 0;

        const pt = Number(r.pt || 0);   // keep PT slab as-is
        const tds = Number(r.tds || 0); // keep TDS as-is
        const otherDed = Number((r as any).other_deduction || 0);
        const advDed = Number((r as any).advance_recovery || 0);
        const totalDed = Math.round(pfEmp) + esiEmp + pt + tds + otherDed + advDed;
        const net = grossPaid - totalDed;

        return {
          ...r,
          // Iter 723 (user bug) — stamp manual day edits so a reprocess
          // ("With EXISTING Data") NEVER reverts the typed Present Days,
          // including on Freeze-as-Actual-Gross firms.
          manual_override: true,
          manual_fields: Array.from(
            new Set([...((((r as any).manual_fields) as string[]) || []), "present_days"]),
          ),
          present_days: pd,
          basic: rHeads.basic,
          hra: rHeads.hra,
          conveyance: rHeads.conveyance,
          medical: rHeads.medical,
          special: rHeads.special,
          others: rHeads.others,
          monthly_gross: grossPaid,
          gross_paid: grossPaid,
          // Iter 620 (user bug — "Wage Base not showing on first process") —
          // rows that start at 0 days carry stat_wage_base 0 from the
          // server; typing days must rebuild it (max(Basic, floor% Gross)),
          // like the server does on reprocess.
          stat_wage_base: grossEarn > 0
            ? Math.round(Math.max(rHeads.basic, grossEarn * floorPct))
            : 0,
          pf_applicable: pfOn,
          pf_wages: Math.round(pfWagesNew),
          pf_employee: Math.round(pfEmp),
          vpf_amount: Math.round(vpfNew),
          pf_employer_epf: Math.round(pfErEpf),
          pf_employer_eps: Math.round(pfErEps),
          pf_employer_total: Math.round(pfErTot),
          esic_applicable: esiApplicable,
          esic_wage_base: Math.round(esiBase),
          esic_employee: esiEmp,
          esic_employer: esiEr,
          total_deduction: Math.round(totalDed),
          net: Math.round(net),
        } as CompRow;
      });

      // Recompute totals
      const totals = { ...(prev.totals || {}) } as Record<string, number>;
      const sumKeys: (keyof CompRow)[] = [
        "basic","hra","conveyance","medical","special","others",
        "monthly_gross","gross_paid","ot_pay",
        "pf_wages","pf_employee","pf_employer_epf","pf_employer_eps","pf_employer_total",
        "esic_wage_base","esic_employee","esic_employer",
        "pt","tds","total_deduction","net",
      ];
      for (const k of sumKeys) {
        totals[k as string] = Math.round(rows.reduce((s, r) => s + (Number((r as any)[k]) || 0), 0));
      }
      return { ...prev, rows, totals };
    });
    markGridDirty(); // Iter 616 — mark unsaved (no auto-save)
  };

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
            <Text style={styles.h1}>Compliance Salary Process</Text>
            <Text style={styles.hsub}>
              {Platform.OS === "web"
                ? (() => {
                  // Iter 390 (user request) — subtitle lists only the
                  // Firm-Master-enabled deduction heads.
                  const ed = ((run?.rows?.[0] as any)?.enabled_deductions ?? fmMask.ed) as string[] | undefined;
                  const parts = [
                    (!ed || ed.includes("pf")) && "PF",
                    (!ed || ed.includes("esi")) && "ESIC",
                    (!ed || ed.includes("pt")) && "PT",
                    (!ed || ed.includes("tds")) && "TDS",
                  ].filter(Boolean);
                  return `${parts.join(" · ")}  —  New labour-code wage base`;
                })()
                : "Best used on desktop / web portal"}
            </Text>
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Iter 426 (user request) — the "Active Firm / Firm Settings"
            banner is HIDDEN on this screen. */}

        {/* Enterprise Process Command Center — KPI cards, workflow stepper
            and live compliance validation. Iter 370 (user request) —
            moved from the top of the page to the BOTTOM. */}

        {/* Iter 636 (user request) — COMPACT HEADER: once a run is on
            screen, the Select-firm + Configure-batch cards collapse into
            one slim bar so the salary grid starts right at the top.
            Iter 643 (user request) — the Select-firm + Configure-Batch
            cards are FROZEN at the top of the page (sticky, web only) so
            they never scroll away. */}
        <View style={styles.stickyHeaderWrap}>
        {run && setupCollapsed ? (
          <Pressable
            testID="csr-setup-expand"
            style={styles.compactBar}
            onPress={() => setSetupCollapsed(false)}
          >
            <Ionicons name="options-outline" size={16} color={colors.brandPrimary} />
            <Text style={styles.compactBarTxt} numberOfLines={1}>
              {(ctxCompanies || []).find((c: any) => c.company_id === activeCompanyId)?.name || "Firm"}
              {"  ·  "}{run.month}{"  ·  "}{(run as any).employee_type || "All Groups"}
            </Text>
            <Text style={styles.compactBarHint}>Change firm / month ▾</Text>
          </Pressable>
        ) : (
        <>
        {/* Iter 91 — In-screen firm selection: ALL active firms listed,
            pick ONE and the salary process runs for that firm. */}
        {isSuper ? (
          <View style={styles.card}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Ionicons name="business-outline" size={18} color={colors.brandPrimary} />
              <Text style={styles.cardTitle}>Select firm</Text>
            </View>
            <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2, marginBottom: 8 }}>
              Pick one firm from all active firms — the compliance salary
              will be processed for its employees after selection.
            </Text>
            {/* Iter 172 (user request) — dropdown list instead of chip
                cloud: scales to many firms, with search. */}
            <Pressable
              onPress={() => setFirmDdOpen((v) => !v)}
              style={{
                flexDirection: "row", alignItems: "center", justifyContent: "space-between",
                borderWidth: 1, borderColor: colors.divider, borderRadius: 10,
                paddingHorizontal: 12, paddingVertical: 10, backgroundColor: colors.surface,
              }}
              testID="csr-firm-dropdown"
            >
              <Text style={{ fontSize: 13, fontWeight: "700", color: activeCompanyId ? colors.onSurface : colors.onSurfaceTertiary }}>
                {(ctxCompanies || []).find((c: any) => c.company_id === activeCompanyId)?.name || "— Select firm —"}
              </Text>
              <Ionicons name={firmDdOpen ? "chevron-up" : "chevron-down"} size={16} color={colors.onSurfaceSecondary} />
            </Pressable>
            {firmDdOpen ? (
              <View style={{
                borderWidth: 1, borderColor: colors.divider, borderRadius: 10,
                marginTop: 4, backgroundColor: colors.surface, maxHeight: 260, overflow: "hidden",
              }}>
                <TextInput
                  value={firmSearch}
                  onChangeText={setFirmSearch}
                  placeholder="Search firm…"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={{
                    borderBottomWidth: 1, borderBottomColor: colors.divider,
                    paddingHorizontal: 12, paddingVertical: 8, fontSize: 12.5, color: colors.onSurface,
                  }}
                  testID="csr-firm-search"
                />
                <ScrollView style={{ maxHeight: 210 }} nestedScrollEnabled>
                  {(ctxCompanies || [])
                    .filter((c: any) => !firmSearch.trim() ||
                      String(c.name || "").toLowerCase().includes(firmSearch.trim().toLowerCase()))
                    .map((c: any) => {
                      const on = activeCompanyId === c.company_id;
                      return (
                        <Pressable
                          key={c.company_id}
                          onPress={() => { setLocalCid(c.company_id); setFirmDdOpen(false); setFirmSearch(""); }}
                          style={{
                            flexDirection: "row", alignItems: "center", justifyContent: "space-between",
                            paddingHorizontal: 12, paddingVertical: 10,
                            backgroundColor: on ? colors.brandTertiary : "transparent",
                            borderBottomWidth: 1, borderBottomColor: colors.divider,
                          }}
                          testID={`csr-firm-${c.company_id}`}
                        >
                          <Text style={{ fontSize: 12.5, fontWeight: on ? "800" : "600", color: colors.onSurface }}>
                            {c.name || c.company_id}
                          </Text>
                          {on ? <Ionicons name="checkmark" size={15} color={colors.brandPrimary} /> : null}
                        </Pressable>
                      );
                    })}
                  {(ctxCompanies || []).length === 0 ? (
                    <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary, padding: 12 }}>No firms found.</Text>
                  ) : null}
                </ScrollView>
              </View>
            ) : null}
          </View>
        ) : null}

        {/* Iter 114 — duplicate "Firm" selector card REMOVED (user rule):
            only ONE firm selector ("Select firm" card above) remains. */}

        {/* Config card — Iter 637 (user request): compact single-line
            "Configure Batch" toolbar. VIEW-ONLY redesign — every control,
            value and button keeps its exact existing behaviour. */}
        <View style={styles.card}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <Ionicons name="settings-outline" size={20} color={colors.brandPrimary} />
            <Text style={styles.batchTitle}>Configure Batch</Text>
          </View>

          <View style={styles.batchLine}>
            <View style={[styles.batchCol, { minWidth: 300, maxWidth: 420 }]}>
              <Text style={styles.batchLabel}>Month (FY-wise)</Text>
              <MonthPicker
                value={month}
                onChange={setMonth}
                allowEmpty={false}
                fyMode
                yearsBack={20}
                testID="csr-month"
              />
            </View>
            <View style={[styles.batchCol, { minWidth: 110, maxWidth: 130 }]}>
              {/* Iter 640 (user request) — label renamed to just
                  "Month Days"; 2-digit input, narrow column. */}
              <Text style={styles.batchLabel}>Month Days</Text>
              <TextInput
                testID="csr-days"
                value={monthDaysOverride}
                onChangeText={(v) => {
                  // Iter 86 — Cap to actual calendar days in the selected month.
                  const cleaned = v.replace(/[^0-9]/g, "");
                  if (!cleaned) {
                    setMonthDaysOverride("");
                    return;
                  }
                  const max = calendarDaysInMonth(month);
                  const n = Math.min(max, Math.max(1, Number(cleaned)));
                  setMonthDaysOverride(String(n));
                }}
                placeholder={`Auto (${calendarDaysInMonth(month)})`}
                placeholderTextColor={colors.onSurfaceTertiary}
                style={[styles.input, { height: 42, paddingVertical: 0, marginBottom: 0 }]}
                keyboardType="numeric"
                maxLength={2}
              />
            </View>
            <View style={styles.batchCol}>
              {/* Iter 255 (user request) — Employee Group DROPDOWN placed
                  right after Month days (override). */}
              <Text style={styles.batchLabel}>Employee group</Text>
              {Platform.OS === "web" ? (
                // @ts-ignore web-only element
                <select
                  data-testid="csr-group-select"
                  value={empType}
                  onChange={(e: any) => setEmpType(e.target.value)}
                  style={{
                    height: 42, borderRadius: 10, border: `1px solid ${colors.divider}`,
                    background: colors.surface, color: colors.onSurface,
                    fontSize: 14, fontWeight: 600, padding: "0 10px", width: "100%",
                  } as any}
                >
                  <option value="all">— Select group (mandatory) —</option>
                  {types.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.name} ({t.count})
                    </option>
                  ))}
                </select>
              ) : (
                <View style={styles.chipStrip}>
                  {types.map((t) => (
                    <TypeChip
                      key={t.name}
                      label={`${t.name} (${t.count})`}
                      active={empType === t.name}
                      onPress={() => setEmpType(t.name)}
                    />
                  ))}
                </View>
              )}
            </View>

            {/* Iter 637 — display-only summary cards (same existing data:
                group counts + the run already on screen). */}
            {(() => {
              const total = empType !== "all"
                ? (types.find((t) => t.name === empType)?.count ?? 0)
                : types.reduce((s, t) => s + (t.count || 0), 0);
              const processed = run && (run as any).month === month
                ? ((run as any).rows || []).length : 0;
              const pending = Math.max(0, total - processed);
              return (
                <>
                  <View style={[styles.sumCard, { borderColor: "#93C5FD", backgroundColor: "#EFF6FF" }]}>
                    <Text style={styles.sumLabel}>Total Employees</Text>
                    <Text style={[styles.sumVal, { color: "#1D4ED8" }]}>{total}</Text>
                  </View>
                  <View style={[styles.sumCard, { borderColor: "#86EFAC", backgroundColor: "#F0FDF4" }]}>
                    <Text style={styles.sumLabel}>Processed</Text>
                    <Text style={[styles.sumVal, { color: "#15803D" }]}>{processed} ✓</Text>
                  </View>
                  <View style={[styles.sumCard, { borderColor: "#FDBA74", backgroundColor: "#FFF7ED" }]}>
                    <Text style={styles.sumLabel}>Pending</Text>
                    <Text style={[styles.sumVal, { color: "#C2410C" }]}>{pending} ◷</Text>
                  </View>
                </>
              );
            })()}
          </View>

          {/* Iter 637 — month-days info moved BELOW the toolbar into a
              subtle light-blue panel (same text, same confirmation flow). */}
          {existingAny && (existingAny as any).month_days ? (
            <View style={styles.infoPanel}>
              <Ionicons name="information-circle-outline" size={14} color="#0369A1" />
              <Text style={styles.infoPanelTxt}>
                Already processed with {(existingAny as any).month_days} days — a different value will ask for confirmation.
              </Text>
            </View>
          ) : null}

          {/* Iter 85 — Roll filter removed. Compliance Salary Process
              is intentionally locked to ON-ROLL employees only, so the
              chip strip and All/Off-roll options are no longer shown. */}

          {/* Iter 85 — Salary Structure + Statutory Config read-only
              chip strips hidden per user request. The Firm Settings
              button at the TOP of this screen already surfaces these
              values on the Compliance Policy page, so showing them again
              here was redundant. */}

          {/* Iter 255 (user request) — Import Salary Sheet moved to the
              BOTTOM of the page (see below, before the footer). */}


          {/* Iter 101 — Gmail attachment picker */}
          <Modal
            visible={mailModal}
            transparent
            animationType="fade"
            onRequestClose={() => setMailModal(false)}
          >
            <View
              style={{
                flex: 1, backgroundColor: "rgba(15,23,42,0.45)",
                alignItems: "center", justifyContent: "center", padding: 20,
              }}
            >
              <View
                style={{
                  backgroundColor: colors.surface, borderRadius: 14, padding: 16,
                  width: "100%", maxWidth: 560, maxHeight: "80%",
                }}
              >
                <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 10 }}>
                  <Ionicons name="mail-open-outline" size={18} color={colors.brandPrimary} />
                  <Text style={{ flex: 1, marginLeft: 8, fontWeight: "800", color: colors.onSurface, fontSize: 14 }}>
                    Pick a sheet from your email
                  </Text>
                  <Pressable onPress={() => setMailModal(false)} testID="csr-mail-close">
                    <Ionicons name="close" size={20} color={colors.onSurfaceTertiary} />
                  </Pressable>
                </View>
                {mailLoading ? (
                  <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 24 }} />
                ) : mailMsgs.length === 0 ? (
                  <Text style={{ color: colors.onSurfaceTertiary, fontSize: 12.5, marginVertical: 16 }}>
                    No recent emails with Excel/CSV attachments found in the connected mailbox.
                  </Text>
                ) : (
                  <ScrollView style={{ maxHeight: 420 }}>
                    {mailMsgs.map((m: any) => (
                      <View
                        key={m.message_id}
                        style={{
                          borderWidth: 1, borderColor: colors.divider,
                          borderRadius: 10, padding: 10, marginBottom: 8,
                        }}
                      >
                        <Text style={{ fontWeight: "700", color: colors.onSurface, fontSize: 12.5 }} numberOfLines={1}>
                          {m.subject || "(no subject)"}
                        </Text>
                        <Text style={{ color: colors.onSurfaceTertiary, fontSize: 11 }} numberOfLines={1}>
                          {m.from} · {m.date}
                        </Text>
                        {(m.attachments || []).map((a: any) => (
                          <Pressable
                            key={a.attachment_id}
                            onPress={() => importFromMail(m, a)}
                            style={{
                              flexDirection: "row", alignItems: "center", gap: 6,
                              marginTop: 6, paddingVertical: 7, paddingHorizontal: 10,
                              borderRadius: 8, backgroundColor: colors.brandTertiary,
                            }}
                            testID={`csr-mail-att-${a.attachment_id}`}
                          >
                            <Ionicons name="document-outline" size={14} color={colors.brandPrimary} />
                            <Text style={{ color: colors.brandPrimary, fontWeight: "700", fontSize: 12 }} numberOfLines={1}>
                              {a.filename}
                            </Text>
                          </Pressable>
                        ))}
                      </View>
                    ))}
                  </ScrollView>
                )}
              </View>
            </View>
          </Modal>

          {/* Iter 230 (user request) — "Configure employees" button removed
              from the Compliance Salary Process screen. */}
          {/* Iter 638 (user request) — compact buttons, one line, no full-
              width stretch. Same actions. */}
          <View style={{ flexDirection: "row", gap: 10, marginTop: 8, flexWrap: "wrap" }}>
            <Pressable
              testID="csr-generate"
              onPress={generate}
              disabled={busy}
              style={[styles.primaryBtn, busy && { opacity: 0.6 },
                { backgroundColor: "#16A34A", minHeight: 46, borderRadius: 10,
                  paddingHorizontal: 14, paddingVertical: 6, alignSelf: "flex-start" }]}
            >
              {busy ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="shield-checkmark-outline" size={15} color="#fff" />
                  <Text style={[styles.primaryBtnTxt, { fontSize: 12.5, lineHeight: 16, textAlign: "center" }]}>
                    Salary{"\n"}Process
                  </Text>
                </>
              )}
            </Pressable>
            {/* Iter 330 (user request) — Copy Last Month Salary.
                Iter 640 (user request) — smaller button, label on 2 lines. */}
            <Pressable
              testID="csr-copy-last-month"
              onPress={copyLastMonth}
              disabled={busy}
              style={[
                styles.primaryBtn, busy && { opacity: 0.6 },
                { backgroundColor: "#7C3AED", minHeight: 46, borderRadius: 10,
                  paddingHorizontal: 14, paddingVertical: 6, alignSelf: "flex-start" },
              ]}
            >
              <Ionicons name="copy-outline" size={15} color="#fff" />
              <Text style={[styles.primaryBtnTxt, { fontSize: 12.5, lineHeight: 16, textAlign: "center" }]}>
                Copy Last Month{"\n"}Salary
              </Text>
            </Pressable>
          </View>
          {/* Iter 371 (user request) — the month is already processed &
              FINALIZED → Super / Sub Admins get a one-tap UNLOCK here. */}
          {finalizedExisting && isSuper ? (
            <Pressable
              testID="csr-unlock-existing"
              onPress={unlockExisting}
              disabled={unlockBusy}
              style={[
                styles.primaryBtn,
                { marginTop: 8, backgroundColor: "#D97706" },
                unlockBusy && { opacity: 0.6 },
              ]}
            >
              {unlockBusy ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="lock-open-outline" size={16} color="#fff" />
                  <Text style={styles.primaryBtnTxt}>
                    Unlock Salary — {finalizedExisting.month} is Finalized 🔒
                  </Text>
                </>
              )}
            </Pressable>
          ) : null}
          {run ? (
            <Pressable
              testID="csr-setup-collapse"
              onPress={() => setSetupCollapsed(true)}
              style={{ marginTop: 8, alignSelf: "center", flexDirection: "row", alignItems: "center", gap: 4 }}
            >
              <Ionicons name="chevron-up" size={14} color={colors.brandPrimary} />
              <Text style={{ fontSize: 12, fontWeight: "800", color: colors.brandPrimary }}>Collapse setup — jump to grid</Text>
            </Pressable>
          ) : null}
        </View>
        </>
        )}
        </View>

        {/* Iter 644 (user bug — "Not able to Lock") — these modals used to
            live inside the collapsible Configure-Batch branch, so once a run
            was on screen (setup auto-collapsed) they NEVER mounted: clicking
            Finalize & Lock with validation findings silently did nothing.
            Moved here so they are ALWAYS mounted. */}
          {/* Iter 388 (Phase 3) — Pre-Lock PF/ESIC Validation results */}
          <Modal
            visible={!!lockCheck}
            transparent
            animationType="fade"
            onRequestClose={() => setLockCheck(null)}
          >
            <View style={{
              flex: 1, backgroundColor: "rgba(15,23,42,0.45)",
              alignItems: "center", justifyContent: "center", padding: 20,
            }}>
              <View style={{
                backgroundColor: colors.surfaceSecondary, borderRadius: 16, padding: 16,
                width: "100%", maxWidth: 640, maxHeight: "85%",
                borderWidth: 1, borderColor: colors.border,
              }}>
                <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                  <Text style={{ fontSize: 15, fontWeight: "800", color: colors.onSurface }}>
                    🔒 Salary Lock — PF/ESIC Validation
                  </Text>
                  <Pressable onPress={() => setLockCheck(null)} hitSlop={10} testID="lock-check-close">
                    <Ionicons name="close" size={18} color={colors.onSurfaceSecondary} />
                  </Pressable>
                </View>
                <View style={{ flexDirection: "row", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
                  <View style={{ backgroundColor: "#FEE2E2", borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 }}>
                    <Text style={{ fontSize: 11, fontWeight: "800", color: "#B91C1C" }}>
                      {lockCheck?.errors_count || 0} error(s) — review below
                    </Text>
                  </View>
                  <View style={{ backgroundColor: "#FEF3C7", borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 }}>
                    <Text style={{ fontSize: 11, fontWeight: "800", color: "#92400E" }}>
                      {lockCheck?.warnings_count || 0} warning(s)
                    </Text>
                  </View>
                  <View style={{ backgroundColor: "#E0F2FE", borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 }}>
                    <Text style={{ fontSize: 11, fontWeight: "800", color: "#075985" }}>
                      {lockCheck?.employees_flagged || 0} / {lockCheck?.employees_total || 0} employees flagged
                    </Text>
                  </View>
                </View>
                <ScrollView style={{ maxHeight: 420 }}>
                  {(lockCheck?.global_issues || []).map((g: any, i: number) => (
                    <View key={`g${i}`} style={{
                      flexDirection: "row", gap: 8, padding: 8, borderRadius: 8, marginBottom: 6,
                      backgroundColor: g.level === "error" ? "#FEF2F2" : "#FFFBEB",
                      borderWidth: 1, borderColor: g.level === "error" ? "#FCA5A5" : "#FCD34D",
                    }}>
                      <Ionicons name={g.level === "error" ? "close-circle" : "warning"} size={16}
                        color={g.level === "error" ? "#DC2626" : "#D97706"} style={{ marginTop: 1 }} />
                      <View style={{ flex: 1 }}>
                        <Text style={{ fontSize: 12, fontWeight: "700", color: colors.onSurface }}>{g.message}</Text>
                        <Text style={{ fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 1 }}>→ {g.suggestion}</Text>
                      </View>
                    </View>
                  ))}
                  {(lockCheck?.rows || []).map((er: any) => (
                    <View key={er.user_id} style={{
                      borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
                      paddingVertical: 8,
                    }}>
                      <Text style={{ fontSize: 12.5, fontWeight: "800", color: colors.onSurface }}>
                        {er.employee_code ? `${er.employee_code} · ` : ""}{er.name}
                        <Text style={{ fontWeight: "400", color: colors.onSurfaceTertiary }}>
                          {"   "}Gross ₹{Number(er.gross_paid || 0).toLocaleString("en-IN")} · {er.present_days} days
                        </Text>
                      </Text>
                      {(er.issues || []).map((is: any, j: number) => (
                        <View key={j} style={{ flexDirection: "row", gap: 6, marginTop: 4, marginLeft: 2 }}>
                          <Ionicons name={is.level === "error" ? "close-circle" : "warning"} size={14}
                            color={is.level === "error" ? "#DC2626" : "#D97706"} style={{ marginTop: 1 }} />
                          <View style={{ flex: 1 }}>
                            <Text style={{ fontSize: 11.5, color: is.level === "error" ? "#B91C1C" : "#92400E", fontWeight: "600" }}>
                              [{is.code}] {is.message}
                            </Text>
                            <Text style={{ fontSize: 10.5, color: colors.onSurfaceSecondary }}>→ {is.suggestion}</Text>
                          </View>
                        </View>
                      ))}
                    </View>
                  ))}
                </ScrollView>
                <View style={{ flexDirection: "row", gap: 8, marginTop: 12, justifyContent: "flex-end", flexWrap: "wrap" }}>
                  <Pressable
                    onPress={() => setLockCheck(null)}
                    style={{ paddingHorizontal: 16, paddingVertical: 10, borderRadius: 10, borderWidth: 1, borderColor: colors.border }}
                    testID="lock-check-cancel"
                  >
                    <Text style={{ fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary }}>Fix issues first</Text>
                  </Pressable>
                  {/* Iter 423b (user directive) — the validation NEVER
                      blocks the lock: findings are informational and the
                      Finalize button is always available to every admin. */}
                  <Pressable
                    onPress={() => doFinalize(true, true)}
                    disabled={finalizing}
                    style={{
                      flexDirection: "row", alignItems: "center", gap: 6,
                      paddingHorizontal: 16, paddingVertical: 10, borderRadius: 10,
                      backgroundColor: "#059669", opacity: finalizing ? 0.6 : 1,
                    }}
                    testID="lock-anyway"
                  >
                    {finalizing ? <ActivityIndicator size="small" color="#fff" /> : (
                      <Ionicons name="lock-closed" size={14} color="#fff" />
                    )}
                    <Text style={{ fontSize: 13, fontWeight: "800", color: "#fff" }}>
                      Finalize &amp; Lock Now
                    </Text>
                  </Pressable>
                </View>
                {(lockCheck?.errors_count || 0) > 0 ? (
                  <Text style={{ fontSize: 10.5, color: "#B91C1C", marginTop: 8 }}>
                    {user?.role === "super_admin"
                      ? "Review the employee-wise errors above — as Super Admin you can still lock with the red override button (recorded on the run + audit trail)."
                      : "Errors must be fixed before the Salary Lock — only a Super Admin can override errors."}
                  </Text>
                ) : null}
              </View>
            </View>
          </Modal>

          {/* Iter 438 (user request) — post Save / Finalize: Download or
              Mail the reports (PDF / Excel / CSV / All). */}
          <ReportsShareModal
            visible={!!reportsFor}
            onClose={() => setReportsFor(null)}
            title={`Compliance Salary — ${reportsFor?.month || ""}`}
            subtitle={reportsFor?.note}
            employeeGroup={reportsFor?.group}
            formatOptions={[
              { key: "pdf", label: "PDF Format 1" },
              { key: "pdf2", label: "PDF Format 2" },
              { key: "xlsx", label: "Excel" },
              { key: "csv", label: "CSV" },
            ]}
            defaultEmail={(user as any)?.email || ""}
            companyId={(run as any)?.company_id || activeCompanyId || ""}
            emailEndpoint={reportsFor
              ? `/admin/compliance-salary-runs/${reportsFor.run_id}/email-report`
              : ""}
            onDownload={async (fmts) => {
              if (reportsFor) {
                await downloadRunReports(reportsFor.run_id, reportsFor.month, fmts);
              }
            }}
          />

        {/* Iter 182 — loading skeleton while a run computes */}
        {busy && !run ? <EmployeeListSkeleton rows={6} /> : null}

        {/* Result table */}
        {run ? (
          <View style={styles.card}>
            {/* Iter 643 (user request) — INFO NOTES (Master Snapshot, PF
                rule, Freeze/Copied tags) moved to their OWN line so the
                action buttons below stay undisturbed. */}
            {(snapInfo?.exists || (run as any).frozen || (run as any).copied_from_month
              || pfMethodLabel) ? (
              <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                {/* Iter 486 — Master Snapshot badge: which frozen master
                    version this sheet was calculated on. */}
                {snapInfo?.exists ? (
                  <View testID="snapshot-badge" style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, backgroundColor: "#E0F2FE", borderRadius: 999 }}>
                    <Ionicons name="lock-closed" size={12} color="#0369A1" />
                    <Text style={{ fontSize: 11, fontWeight: "800", color: "#0369A1" }}>
                      MASTER SNAPSHOT v{snapInfo.version} — frozen {String(snapInfo.created_at || "").slice(0, 10).split("-").reverse().join("-")}
                      {snapInfo.source === "refresh_master" ? " (refreshed)" : ""}
                    </Text>
                  </View>
                ) : null}
                {/* Iter 621 (user-approved) — which PF proration rule the
                    PF column follows (hidden when the firm disables PF). */}
                {(() => {
                  const ed0 = ((run.rows?.[0] as any)?.enabled_deductions
                    ?? (fmMask as any).ed) as string[] | undefined;
                  if (ed0 && !ed0.includes("pf")) return null;
                  return (
                    <View testID="pf-proration-badge" style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, backgroundColor: "#FFEDD5", borderRadius: 999 }}>
                      <Ionicons name="calculator-outline" size={12} color="#9A3412" />
                      <Text style={{ fontSize: 11, fontWeight: "800", color: "#9A3412" }}>
                        {pfMethodLabel.toUpperCase()}
                      </Text>
                    </View>
                  );
                })()}
                {(run as any).frozen ? (
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, backgroundColor: "#EDE9FE", borderRadius: 999 }}>
                    <Ionicons name="snow-outline" size={12} color="#5B21B6" />
                    <Text style={{ fontSize: 11, fontWeight: "800", color: "#5B21B6" }}>FREEZE SALARY · IMPORTED</Text>
                  </View>
                ) : null}
                {(run as any).copied_from_month ? (
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, backgroundColor: "#F3E8FF", borderRadius: 999 }}>
                    <Ionicons name="copy-outline" size={12} color="#7C3AED" />
                    <Text style={{ fontSize: 11, fontWeight: "800", color: "#7C3AED" }}>COPIED FROM {(run as any).copied_from_month}</Text>
                  </View>
                ) : null}
              </View>
            ) : null}
            <View style={styles.rowBetween}>
              {/* Iter 427 (user request) — the run summary (month · employees
                  · net · month_days · PF/ESIC/TDS totals) moved to the sticky
                  FOOTER strip at the bottom of the screen. */}
              <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
                {(run as any).finalized ? (
                  <>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, backgroundColor: "#DCFCE7", borderRadius: 999 }}>
                      <Ionicons name="lock-closed" size={12} color="#166534" />
                      <Text style={{ fontSize: 11, fontWeight: "800", color: "#166534" }}>FINALIZED · LOCKED</Text>
                    </View>
                    {user?.role === "super_admin" && pendingUnlockReq ? (
                      <>
                        <View style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, backgroundColor: "#FEF3C7", borderRadius: 999 }}>
                          <Ionicons name="alert-circle-outline" size={12} color="#92400E" />
                          <Text style={{ fontSize: 11, fontWeight: "800", color: "#92400E" }}>
                            UNLOCK REQUESTED{pendingUnlockReq.requested_by_name ? ` · ${pendingUnlockReq.requested_by_name}` : ""}
                          </Text>
                        </View>
                        <ActionBtn icon="checkmark-circle-outline" label="Approve Unlock" busy={unlockBusy} onPress={() => decideUnlock(true)} primary />
                        <ActionBtn icon="close-circle-outline" label="Reject" busy={unlockBusy} onPress={() => decideUnlock(false)} />
                      </>
                    ) : pendingUnlockReq ? (
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, backgroundColor: "#FEF3C7", borderRadius: 999 }}>
                        <Ionicons name="hourglass-outline" size={12} color="#92400E" />
                        <Text style={{ fontSize: 11, fontWeight: "800", color: "#92400E" }}>UNLOCK PENDING APPROVAL</Text>
                      </View>
                    ) : (
                      <ActionBtn
                        icon="lock-open-outline"
                        label={user?.role === "super_admin" ? "Unlock" : "Request Change"}
                        busy={unlockBusy}
                        onPress={requestUnlock}
                      />
                    )}
                  </>
                ) : (
                  <>
                    {/* Iter 230 (user request) — 4-button lifecycle: Save /
                        Reprocess / Delete / Finalize & Lock. */}
                    <ActionBtn icon="save-outline" label="Save" onPress={saveAsDraft} />
                    <ActionBtn icon="refresh-circle-outline" label="Reprocess" onPress={reprocessRun} />
                    {isSuper ? (
                      <ActionBtn icon="sync-circle-outline" label="Refresh Master"
                                 busy={refreshingSnap} onPress={refreshMasterSnapshot} />
                    ) : null}
                    <ActionBtn icon="trash-outline" label="Delete" onPress={deleteRun} />
                    <ActionBtn icon="checkmark-done-outline" label="Finalize & Lock" busy={finalizing} onPress={finalizeRun} primary testID="btn-finalize-lock" />
                  </>
                )}
                <ActionBtn icon="grid-outline" label="Excel" busy={downloading} onPress={() => downloadFile("xlsx")} />
                <ActionBtn icon="eye-outline" label={unsavedEdits ? "Excel (Displayed*)" : "Excel (Displayed)"}
                  testID="btn-export-displayed" busy={downloading} onPress={() => void exportDisplayed()} />
                <ActionBtn icon="document-text-outline" label="PDF" busy={downloading} onPress={() => downloadFile("pdf")} />
                <ActionBtn icon="document-outline" label="PDF (Option 2)" busy={downloading} onPress={() => downloadFile("pdf2")} />
                <ActionBtn icon="download-outline" label="CSV" busy={downloading} onPress={() => downloadFile("csv")} />
                {unsavedEdits && !(run as any)?.finalized ? (
                  <Text style={{ fontSize: 9.5, color: "#B45309", fontWeight: "800", alignSelf: "center" }}>
                    ● Unsaved changes — auto-saves within 1 min
                  </Text>
                ) : lastAutoSave && !(run as any)?.finalized ? (
                  <Text style={{ fontSize: 9.5, color: "#15803D", fontWeight: "800", alignSelf: "center" }}>
                    ✓ Auto-saved {lastAutoSave}
                  </Text>
                ) : null}
                <ActionBtn icon="paper-plane-outline" label="Push payslips" busy={pushing} onPress={pushToPayslips} primary />
                {/* Iter 396 — WhatsApp payslip blast */}
                <ActionBtn icon="logo-whatsapp" label="WhatsApp Payslips" testID="btn-wa-blast"
                  busy={waBlasting} onPress={sendWhatsAppBlast} primary />
              </View>
              {/* Iter 324 (user request) — PDF Sorting & Grouping */}
              {Platform.OS === "web" ? (
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                  <Text style={{ fontSize: 11.5, fontWeight: "800", color: colors.onSurfaceSecondary }}>
                    📄 PDF Sort by:
                  </Text>
                  <select
                    data-testid="pdf-sort"
                    value={pdfSort}
                    onChange={(e) => setPdfSort((e.target as HTMLSelectElement).value)}
                    style={{
                      padding: "5px 8px", borderRadius: 8, fontSize: 12,
                      border: `1px solid ${colors.border}`, background: colors.surface,
                      color: colors.onSurface,
                    } as any}
                  >
                    <option value="">Default order</option>
                    <option value="name">Employee Name (A–Z)</option>
                    <option value="code">Employee Code</option>
                    <option value="designation">Designation</option>
                    <option value="department">Department</option>
                  </select>
                  {/* Iter 427 (user request) — "Group by" option removed. */}
                </View>
              ) : null}
            </View>

            {/* Iter 98 — sort chips + Iter 182 instant search */}
            <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
              <View style={{
                flexDirection: "row", alignItems: "center", gap: 6, flexGrow: 1, minWidth: 190,
                maxWidth: 320, borderWidth: 1, borderColor: colors.border, borderRadius: 999,
                paddingHorizontal: 12, paddingVertical: 6, backgroundColor: colors.surface,
              }}>
                <Ionicons name="search-outline" size={13} color={colors.onSurfaceTertiary} />
                <TextInput
                  ref={empSearchRef}
                  value={empSearch}
                  onChangeText={setEmpSearch}
                  placeholder='Search employee…  (press "/")'
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={{ flex: 1, fontSize: 11.5, color: colors.onSurface, paddingVertical: 0,
                    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null) }}
                  testID="comp-emp-search"
                />
                {empSearch ? (
                  <Pressable onPress={() => setEmpSearch("")} hitSlop={6}>
                    <Ionicons name="close-circle" size={13} color={colors.onSurfaceTertiary} />
                  </Pressable>
                ) : null}
              </View>
              {empSearch.trim() ? (
                <Text style={{ fontSize: 10.5, fontWeight: "700", color: colors.brandPrimary }}>
                  {sortRows(run.rows).length}/{run.rows.length} match
                </Text>
              ) : null}
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
                  testID={`comp-sort-${val || "default"}`}
                >
                  <Text style={{ fontSize: 11, fontWeight: "700", color: sortBy === val ? "#fff" : colors.onSurfaceSecondary }}>{lab}</Text>
                </Pressable>
              ))}
              {/* Iter 380 (user accepted improvement) — show only the
                  employees where Freeze Salary ≠ Gross. */}
              {hasFrz ? (() => {
                const n = (run.rows || []).filter(rowIsMismatch).length;
                return (
                  <Pressable
                    onPress={() => setOnlyMismatch((v) => !v)}
                    style={{
                      flexDirection: "row", alignItems: "center", gap: 4,
                      paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, borderWidth: 1,
                      borderColor: onlyMismatch ? "#DC2626" : n > 0 ? "#FCA5A5" : colors.border,
                      backgroundColor: onlyMismatch ? "#DC2626" : n > 0 ? "#FEF2F2" : colors.surface,
                    }}
                    testID="comp-only-mismatch"
                  >
                    <Ionicons name="warning-outline" size={12}
                      color={onlyMismatch ? "#fff" : n > 0 ? "#DC2626" : colors.onSurfaceTertiary} />
                    <Text style={{ fontSize: 11, fontWeight: "800",
                      color: onlyMismatch ? "#fff" : n > 0 ? "#B91C1C" : colors.onSurfaceSecondary }}>
                      Mismatch only ({n})
                    </Text>
                  </Pressable>
                );
              })() : null}
            </View>

            {/* Iter 255 (user request) — Dept chips hidden on the
                Compliance Salary Process (Branch/Contractor remain). */}
            <GridFilterChips rows={run.rows} filters={gridFilters} onChange={setGridFilters} testPrefix="comp" hide={["dept"]} />

            {/* Iter 657 (user request) — the grid height is measured from
                its real on-screen top so it ALWAYS fits the viewport: the
                sticky header stays visible and the horizontal scrollbar
                sits at the bottom of the screen (no page-scroll needed). */}
            <View ref={gridWrapRef as any}>
            <GridScroller maxHeight={Platform.OS === "web" ? `calc(100vh - ${gridTopPx + 66}px)` : 640}>
                {/* Iter 85 pt 1 — Column-hide by firm's enabled_allowances.
                    Both header and data cells honor the same mask so
                    columns stay aligned. `basic` is always kept.
                    Iter 86 — Section group header row (Master / Calculated
                    / Deductions) added above the column headers so admins
                    can visually parse the 3 zones of the grid at a glance. */}
                {/* Iter 140 — both header rows frozen on top while
                    scrolling down (web). */}
                <View style={stickyHeader(colors.surface)}>
                {(() => {
                  const en = ((run.rows[0] as any)?.enabled_allowances ?? fmMask.en) as string[] | undefined;
                  const has = (k: string) => !en || en.includes(k) || k === "basic";
                  const CELL_W = colW.num;
                  // Iter 379 (user request) — column order: Sr → UAN →
                  // ESIC → Name → Father → Designation.
                  // Iter 477 (user request) — OT Hrs column moved right
                  // after Present Days, so its width belongs to the info
                  // zone and the CALC band shrinks by one cell.
                  const INFO_W = colW.sr + colW.uan + colW.esi + colW.name + colW.father + colW.desg + colW.pd + CELL_W + colW.el;
                  const FROZEN_W = colW.sr + colW.uan + colW.esi + colW.name;
                  const optKeys = ["basic","hra","conveyance","medical","special","others"].filter((k) => has(k));
                  const masterCount = optKeys.length + 1; // +M.Gross
                  // Iter 306 — +Gross AND +OT Amt (the band was one cell
                  // short, so DEDUCTIONS & NET started over the OT column).
                  // Iter 335 — +Freeze Salary column beside Gross on
                  // imported (frozen) runs. Iter 477 — OT Hrs moved to info.
                  const calcCount = optKeys.length + 2 + (hasFrz ? 1 : 0);
                  // Iter 171 — deduction columns follow Firm Master Deductions
                  const ed = ((run.rows[0] as any)?.enabled_deductions ?? fmMask.ed) as string[] | undefined;
                  const hasDed = (k: string) => !ed || ed.includes(k);
                  const dedCount = 3 // WageBase, TotalDed, Net
                    + (hasDed("pf") ? 2 : 0) + (hasDed("esi") ? 2 : 0)
                    + (hasDed("pt") ? 1 : 0) + (hasDed("tds") ? 1 : 0)
                    // Iter 443 — Master-linked Advance* / Other* columns.
                    + (hasDed("advance") ? 1 : 0) + (hasDed("other") ? 1 : 0);
                  return (
                    <View style={[styles.tblRow, styles.groupHdrRow]}>
                      <View style={[{ width: FROZEN_W }, stickyCol(0, colors.surface)]} />
                      <View style={{ width: INFO_W - FROZEN_W }} />
                      <View style={[styles.groupHdrCell, styles.groupHdrMaster, { width: masterCount * CELL_W }]}>
                        <Text style={styles.groupHdrTxt}>MASTER SALARY (Full Month)</Text>
                      </View>
                      <View style={[styles.groupHdrCell, styles.groupHdrCalc, { width: calcCount * CELL_W }]}>
                        <Text style={styles.groupHdrTxt}>CALCULATED SALARY (× PD/MD)</Text>
                      </View>
                      <View style={[styles.groupHdrCell, styles.groupHdrDed, { width: dedCount * CELL_W }]}>
                        <Text style={styles.groupHdrTxt}>DEDUCTIONS & NET</Text>
                      </View>
                      {/* Iter 339c (user request) — trailing FREEZE SALARY
                          (IMPORTED) band removed; diff rows are HIGHLIGHTED
                          in the grid instead. */}
                    </View>
                  );
                })()}
                {(() => {
                  const en = ((run.rows[0] as any)?.enabled_allowances ?? fmMask.en) as string[] | undefined;
                  const has = (k: string) => !en || en.includes(k) || k === "basic";
                  const ed = ((run.rows[0] as any)?.enabled_deductions ?? fmMask.ed) as string[] | undefined;
                  const hasDed = (k: string) => !ed || ed.includes(k);
                  const headers: { label: string; group: "info" | "master" | "calc" | "ded"; w?: number }[] = [
                    // User directive — Employee Code HIDDEN; show Father
                    // Name, Designation, UAN No. & ESIC No. instead.
                    // Iter 379 (user request) — Sr. No first, then UAN No.
                    // and ESIC No., THEN the Employee Name.
                    { label: "Sr", group: "info", w: colW.sr },
                    { label: "UAN No.", group: "info", w: colW.uan },
                    { label: "ESIC No.", group: "info", w: colW.esi },
                    { label: "Name", group: "info", w: colW.name },
                    { label: "Father Name", group: "info", w: colW.father },
                    { label: "Designation", group: "info", w: colW.desg },
                    { label: "Present Days", group: "info", w: colW.pd },
                    // Iter 477 (user request) — OT Hrs shifted right after
                    // Present Days. Iter 644 — hidden when OVER TIME is off.
                    ...(hasOtCol ? [{ label: "OT Hrs", group: "calc" as const, w: colW.num }] : []),
                    // Iter 306 (user #20) — editable ESIC Leave days.
                    { label: "ESIC Leave", group: "info", w: colW.el },
                  ];
                  if (has("basic")) headers.push({ label: "M.Basic", group: "master" });
                  if (has("hra")) headers.push({ label: "M.HRA", group: "master" });
                  if (has("conveyance")) headers.push({ label: "M.Conv", group: "master" });
                  if (has("medical")) headers.push({ label: "M.Med", group: "master" });
                  {/* Iter 727 (user request) — the Firm-Master head
                      "OTH. ALLOW." maps to the engine's `special` key;
                      the sheet now labels it Other Allowances. */}
                  if (has("special")) headers.push({ label: "M.Oth Allow", group: "master" });
                  if (has("others")) headers.push({ label: "M.Others", group: "master" });
                  // Iter 644 — dynamic custom allowance heads (INCENTIVE …).
                  for (const l of allowLabels) headers.push({ label: `M.${l}`, group: "master" });
                  headers.push({ label: "M.Gross", group: "master" });
                  if (has("basic")) headers.push({ label: "Basic", group: "calc" });
                  if (has("hra")) headers.push({ label: "HRA", group: "calc" });
                  if (has("conveyance")) headers.push({ label: "Conv", group: "calc" });
                  if (has("medical")) headers.push({ label: "Med", group: "calc" });
                  if (has("special")) headers.push({ label: "Oth Allow*", group: "calc" });
                  if (has("others")) headers.push({ label: "Others*", group: "calc" });
                  for (const l of allowLabels) headers.push({ label: l, group: "calc" });
                  // Iter 230 (user request) — editable OT Amount column.
                  // Iter 339c (user request) — OT Amt* moved BEFORE Gross.
                  // Iter 644 — hidden when the OVER TIME head is disabled.
                  if (hasOtCol) headers.push({ label: "OT Amt*", group: "calc" });
                  headers.push({ label: "Gross", group: "calc" });
                  // Iter 335 (user request) — Freeze Salary column right
                  // next to Gross (imported/frozen gross per employee).
                  if (hasFrz) headers.push({ label: "Freeze Salary", group: "calc" });
                  const dedLabels = [
                    "Wage Base",
                    // Iter 171 — deduction columns follow Firm Master Deductions
                    ...(hasDed("pf") ? ["PF (E)", "PF (Er)"] : []),
                    ...(hasDed("esi") ? ["ESI (E)", "ESI (Er)"] : []),
                    ...(hasDed("pt") ? ["PT"] : []),
                    ...(hasDed("tds") ? ["TDS"] : []),
                    // Iter 420 (user request) — one dynamic column per
                    // custom deduction head enabled in the Firm Master.
                    ...(((run?.rows?.[0] as any)?.deduction_head_labels as string[]) || []),
                    // Iter 422 (user request) — editable Advance deduction.
                    // Iter 443 — Master-linked: hidden when disabled.
                    ...(hasDed("advance") ? ["Advance*"] : []),
                    ...(hasDed("other") ? ["Other*"] : []),
                    "Total Ded.", "Net",
                  ];
                  for (const d of dedLabels) headers.push({ label: d, group: "ded" });
                  const stickyOff = [0, colW.sr, colW.sr + colW.uan, colW.sr + colW.uan + colW.esi];
                  return (
                    <>
                    <View style={[styles.tblRow, styles.tblHeader]}>
                      {headers.map((h, i) => (
                        <Text
                          key={i}
                          numberOfLines={1}
                          // Iter 370 (user request) — tap ANY header to sort
                          // (asc → desc → off).
                          onPress={() => toggleColSort(h.label)}
                          style={[
                            styles.tblCell,
                            { width: h.w ?? colW.num },
                            styles.tblHeaderTxt,
                            i >= 6 && { textAlign: "right" },
                            h.group === "master" && styles.groupHdrCellHeaderMaster,
                            h.group === "calc" && styles.groupHdrCellHeaderCalc,
                            h.group === "ded" && styles.groupHdrCellHeaderDed,
                            // Iter 379 (user request) — highlight the Gross
                            // and Freeze Salary column headers.
                            h.label === "Gross" && { backgroundColor: "#B45309", color: "#FEF3C7" },
                            h.label === "Freeze Salary" && { backgroundColor: "#5B21B6", color: "#EDE9FE" },
                            i < 4 && stickyCol(stickyOff[i], colors.brandPrimary),
                            // Iter 657 (user request) — Present Days frozen
                            // beside the Name block; Net frozen at the right.
                            h.label === "Present Days" && stickyCol(stickyOff[3] + colW.name, colors.brandPrimary),
                            h.label === "Net" && stickyColRight(colors.brandPrimary),
                          ]}
                        >
                          {h.label}
                          {colSort?.label === h.label ? (colSort.dir === "asc" ? " ▲" : " ▼") : ""}
                        </Text>
                      ))}
                    </View>
                    {/* Iter 346 (user request) — Excel-style header-wise
                        filter boxes. Text = contains; numbers support
                        >n <n >=n <=n =n. */}
                    <View style={[styles.tblRow, { backgroundColor: "#EFF6FF" }]}>
                      {headers.map((h, i) => (
                        <View
                          key={i}
                          style={[
                            { width: h.w ?? colW.num, paddingHorizontal: 2, paddingVertical: 2 },
                            i < 4 && stickyCol(stickyOff[i], "#EFF6FF"),
                            h.label === "Present Days" && stickyCol(stickyOff[3] + colW.name, "#EFF6FF"),
                            h.label === "Net" && stickyColRight("#EFF6FF"),
                          ]}
                        >
                          {COL_FILTER_GETTERS[h.label] ? (
                            <TextInput
                              value={colFilters[h.label] || ""}
                              onChangeText={(v) => setColFilters((f) => ({ ...f, [h.label]: v }))}
                              placeholder="Filter…"
                              placeholderTextColor="#94A3B8"
                              style={{
                                borderWidth: 1, borderColor: "#BFDBFE", borderRadius: 6,
                                backgroundColor: "#fff", fontSize: 10.5, color: "#0F172A",
                                paddingVertical: 3, paddingHorizontal: 5,
                                ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
                              }}
                              testID={`comp-colfilter-${i}`}
                            />
                          ) : null}
                        </View>
                      ))}
                    </View>
                    </>
                  );
                })()}
                </View>
                {sortRows(run.rows.filter((r) =>
                  rowPassesColFilters(r, colFilters, COL_FILTER_GETTERS))).map((r, idx) => {
                  const isHl = hlRow === r.user_id;
                  // Iter 339c / Iter 379 (user request) — Gross vs Freeze
                  // mismatch: compare the VALUES directly (live, updates as
                  // days/OT are edited) and highlight the whole employee row.
                  const frzDiff = hasFrz && (r as any).imported_gross != null
                    && Math.abs(Number((r as any).imported_gross) - Number(r.gross_paid || 0)) > 0.5;
                  const rowBg = isHl ? "#FEF3C7" : frzDiff ? "#FEE2E2"
                    : idx % 2 === 0 ? colors.surfaceSecondary : colors.surface;
                  return (
                  <Pressable
                    onPress={() => setHlRow(isHl ? null : r.user_id)}
                    key={r.user_id}
                    nativeID={`csr-row-${r.user_id}`}
                    style={[
                      styles.tblRow,
                      { backgroundColor: rowBg },
                      isHl && { borderLeftWidth: 3, borderLeftColor: "#D97706" },
                      !isHl && frzDiff && { borderLeftWidth: 3, borderLeftColor: "#DC2626" },
                    ]}
                  >
                    {/* Iter 379 (user request) — Sr → UAN → ESIC → Name;
                        first four columns frozen while scrolling. */}
                    <Text style={[styles.tblCell, { width: colW.sr, color: "#64748B" }, stickyCol(0, rowBg)]}>{idx + 1}</Text>
                    <Text style={[styles.tblCell, { width: colW.uan }, stickyCol(colW.sr, rowBg)]} numberOfLines={1}>{(r as any).uan_no || "—"}</Text>
                    <Text style={[styles.tblCell, { width: colW.esi }, stickyCol(colW.sr + colW.uan, rowBg)]} numberOfLines={1}>{(r as any).esi_ip_no || "—"}</Text>
                    <Text style={[styles.tblCell, { width: colW.name }, frzDiff && { color: "#B91C1C", fontWeight: "800" }, stickyCol(colW.sr + colW.uan + colW.esi, rowBg)]} numberOfLines={1}>{r.name || "—"}</Text>
                    <Text style={[styles.tblCell, { width: colW.father }]} numberOfLines={1}>{(r as any).father_name || "—"}</Text>
                    <Text style={[styles.tblCell, { width: colW.desg }]} numberOfLines={1}>{(r as any).designation || "—"}</Text>
                    {/* Iter 85 — Editable Present Days. Admin can override
                        the biometric-derived value; the row is recomputed
                        client-side via ``updatePresentDays()`` so PF /
                        ESIC / Net Pay reflect the tweak immediately.
                        Iter 93 — local text state: value is committed
                        (and clamped to month days) on blur/Enter only, so
                        typing "26.5" or 3 keystrokes no longer gets
                        clamped mid-edit to "31".
                        Web-only: Arrow Up/Down move focus between rows,
                        Enter blurs (commits) the current edit. */}
                    <PresentDaysCell
                      idx={idx}
                      value={r.present_days ?? 0}
                      pdRefs={pdRefs}
                      onCommit={(n) => updatePresentDays(r.user_id, n)}
                      onFocused={() => setHlRow(r.user_id)}
                      frozen={stickyCol(colW.sr + colW.uan + colW.esi + colW.name, rowBg)}
                      onNav={(key) => {
                        // Iter 256 — ArrowRight jumps to the next editable
                        // column of the same row (Others / OT / TDS / Other).
                        const next = navCols[navCols.indexOf("pd") + (key === "ArrowRight" ? 1 : -1)];
                        if (next) focusCell(next, idx);
                      }}
                    />
                    {/* Iter 340 (user request) — OT Hours: READ-ONLY on
                        imported (Freeze) runs (auto: OT Amt ÷ per-hour OT
                        rate); MANUALLY editable on normal runs when Firm
                        Master Overtime is allowed (hours × rate → OT Amt).
                        Iter 644 — hidden when OVER TIME is disabled. */}
                    {hasOtCol ? (() => {
                      const hrRate = Number((r as any).ot_hourly_rate) || 0;
                      const otHrs = hrRate > 0
                        ? (Number(r.ot_pay) || 0) / hrRate
                        : Number((r as any).ot_hours) || 0;
                      const canEditHrs = !hasFrz && !!(r as any).firm_ot_allowed && hrRate > 0;
                      if (canEditHrs) {
                        return (
                          <OTHoursCell
                            width={colW.num}
                            value={Math.round(otHrs * 100) / 100}
                            onFocused={() => setHlRow(r.user_id)}
                            onCommit={(n) => updateRowField(
                              r.user_id, "ot_pay",
                              Math.round(n * hrRate * 100) / 100)}
                          />
                        );
                      }
                      return (
                        <Text style={[styles.tblCell, styles.rightCell, { width: colW.num, color: "#5B21B6", fontWeight: "600" }]}>
                          {otHrs > 0 ? otHrs.toFixed(1) : "0"}
                        </Text>
                      );
                    })() : null}
                    {/* Iter 306 (user #20) — ESIC Leave days.
                        Iter 477 (user request) — READ-ONLY: days are
                        fetched from the ESIC Leave Master (approved
                        entries) at process time, not typed here. */}
                    <Text style={[styles.tblCell, styles.rightCell, { width: colW.el, color: "#0369A1", fontWeight: "600" }]}>
                      {Number((r as any).esic_leave_days || 0) || 0}
                    </Text>
                    {/* Iter 85 pt 1 — Master (full-month) heads,
                        conditionally rendered per firm allowance mask. */}
                    {(() => {
                      const en = ((r as any).enabled_allowances ?? fmMask.en) as string[] | undefined;
                      const has = (k: string) => !en || en.includes(k) || k === "basic";
                      return (
                        <>
                          {has("basic") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).basic_master)}</Text> : null}
                          {has("hra") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).hra_master)}</Text> : null}
                          {has("conveyance") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).conveyance_master)}</Text> : null}
                          {has("medical") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).medical_master)}</Text> : null}
                          {has("special") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).special_master)}</Text> : null}
                          {has("others") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(((r as any).others_master || 0) - allowHeadsMaster(r))}</Text> : null}
                          {/* Iter 644 — dynamic custom allowance heads
                              (master, decomposed out of M.Others). */}
                          {allowLabels.map((l) => (
                            <Text key={`am-${l}`} style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>
                              {fmtInr((((r as any).allowance_heads_master || {})[l]) || 0)}
                            </Text>
                          ))}
                          <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).gross_master)}</Text>
                          {/* Calculated (pro-rated by Present Days). */}
                          {has("basic") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.basic)}</Text> : null}
                          {has("hra") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.hra)}</Text> : null}
                          {has("conveyance") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.conveyance)}</Text> : null}
                          {has("medical") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.medical)}</Text> : null}
                          {/* Iter 727 (user request) — OTH. ALLOW. (special)
                              is EDITABLE like Others*. */}
                          {has("special") ? (
                            <EditableGridCell
                              col="special" idx={idx} width={colW.num}
                              value={r.special || 0}
                              cellRefs={cellRefs}
                              onCommit={(n) => updateRowField(r.user_id, "special", n)}
                              onNav={navigateFrom}
                              onFocused={() => setHlRow(r.user_id)}
                            />
                          ) : null}
                          {has("others") ? (
                            <EditableGridCell
                              col="others" idx={idx} width={colW.num}
                              value={Math.max(0, (r.others || 0) - allowHeadsPaid(r))}
                              cellRefs={cellRefs}
                              onCommit={(n) => updateRowField(r.user_id, "others", n + allowHeadsPaid(r))}
                              onNav={navigateFrom}
                              onFocused={() => setHlRow(r.user_id)}
                            />
                          ) : null}
                          {/* Iter 644 — dynamic custom allowance head cells
                              (paid, decomposed out of Others*).
                              Iter 647 (user request) — EDITABLE.
                              Iter 681 (user rule) — FOOD heads are ALWAYS
                              read-only for every firm (sheet/master values
                              show, but cannot be typed over). */}
                          {allowLabels.map((l) => (
                            String(l).toUpperCase().includes("FOOD") ? (
                              <Text key={`ap-${l}`}
                                style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>
                                {fmtInr((((r as any).allowance_heads || {})[l]) || 0)}
                              </Text>
                            ) : (
                            <EditableGridCell
                              key={`ap-${l}`}
                              col={`allow::${l}`} idx={idx} width={colW.num}
                              value={(((r as any).allowance_heads || {})[l]) || 0}
                              cellRefs={cellRefs}
                              onCommit={(n) => updateAllowanceHead(r.user_id, l, n)}
                              onNav={navigateFrom}
                              onFocused={() => setHlRow(r.user_id)}
                            />
                            )
                          ))}
                        </>
                      );
                    })()}
                    {/* Iter 230 (user request) — editable OT Amount.
                        Iter 339c (user request) — shown BEFORE Gross.
                        Iter 644 — hidden when OVER TIME is disabled. */}
                    {hasOtCol ? (
                      <EditableGridCell
                        col="ot_pay" idx={idx} width={colW.num}
                        value={r.ot_pay || 0}
                        cellRefs={cellRefs}
                        onCommit={(n) => updateRowField(r.user_id, "ot_pay", n)}
                        onNav={navigateFrom}
                              onFocused={() => setHlRow(r.user_id)}
                      />
                    ) : null}
                    {/* Iter 379 (user request) — Gross column HIGHLIGHTED;
                        red when it differs from the Freeze Salary. */}
                    <Text style={[styles.tblCell, styles.rightCell, { width: colW.num, fontWeight: "800" },
                      frzDiff
                        ? { backgroundColor: "#FECACA", color: "#991B1B" }
                        : { backgroundColor: "#FEF3C7", color: "#92400E" }]}>
                      {fmtInr(r.gross_paid)}
                    </Text>
                    {/* Iter 335 (user request) — Freeze Salary shown right
                        NEXT TO the Gross column. Iter 379 — red highlight
                        when it differs from the calculated Gross. */}
                    {hasFrz ? (
                      <Text style={[styles.tblCell, styles.rightCell, { width: colW.num, fontWeight: "700" },
                        frzDiff
                          ? { backgroundColor: "#FECACA", color: "#991B1B" }
                          : { backgroundColor: "#F5F3FF", color: "#5B21B6" }]}>
                        {(r as any).imported_gross != null ? fmtInr((r as any).imported_gross) : "—"}
                      </Text>
                    ) : null}
                    <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.stat_wage_base)}</Text>
                    {/* Iter 171 — deduction cells follow Firm Master Deductions */}
                    {(() => {
                      const ed = ((r as any).enabled_deductions ?? fmMask.ed) as string[] | undefined;
                      const hasDed = (k: string) => !ed || ed.includes(k);
                      return (
                        <>
                          {hasDed("pf") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{r.pf_applicable ? fmtInr(r.pf_employee) : "—"}</Text> : null}
                          {hasDed("pf") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{r.pf_applicable ? fmtInr(r.pf_employer_total) : "—"}</Text> : null}
                          {hasDed("esi") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{r.esic_applicable ? fmtInr(r.esic_employee) : "—"}</Text> : null}
                          {hasDed("esi") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{r.esic_applicable ? fmtInr(r.esic_employer) : "—"}</Text> : null}
                          {hasDed("pt") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.pt)}</Text> : null}
                          {/* Iter 230 (user request) — editable TDS. */}
                          {hasDed("tds") ? (
                            <EditableGridCell
                              col="tds" idx={idx} width={colW.num}
                              value={r.tds || 0}
                              cellRefs={cellRefs}
                              onCommit={(n) => updateRowField(r.user_id, "tds", n)}
                              onNav={navigateFrom}
                              onFocused={() => setHlRow(r.user_id)}
                            />
                          ) : null}
                        </>
                      );
                    })()}
                    {/* Iter 420 — dynamic Firm-Master deduction head cells
                        (amounts come from the Employee Master heads). */}
                    {((((run?.rows?.[0] as any)?.deduction_head_labels as string[]) || []).map((dl) => (
                      <Text key={dl} style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>
                        {fmtInr(((r as any).deduction_heads || {})[dl] || 0)}
                      </Text>
                    )))}
                    {/* Iter 422 (user request) — Editable Advance deduction.
                        Auto-filled from the Advance ledger; admins can
                        override it inline (stamped on manual_fields so a
                        reprocess keeps the typed amount).
                        Iter 443 — Master-linked: Advance* and Other* cells
                        hide when the head is disabled in the Firm Master. */}
                    {(() => {
                      const ed = ((r as any).enabled_deductions ?? fmMask.ed) as string[] | undefined;
                      const hasDed = (k: string) => !ed || ed.includes(k);
                      return (
                        <>
                          {hasDed("advance") ? (
                            <EditableGridCell
                              col="advance_recovery" idx={idx} width={colW.num}
                              value={(r as any).advance_recovery || 0}
                              cellRefs={cellRefs}
                              onCommit={(n) => updateRowField(r.user_id, "advance_recovery", n)}
                              onNav={navigateFrom}
                              onFocused={() => setHlRow(r.user_id)}
                            />
                          ) : null}
                          {/* Iter 85 — Editable "Other" deduction. */}
                          {hasDed("other") ? (
                            <EditableGridCell
                              col="other_deduction" idx={idx} width={colW.num}
                              value={(r as any).other_deduction || 0}
                              cellRefs={cellRefs}
                              onCommit={(n) => updateRowField(r.user_id, "other_deduction", n)}
                              onNav={navigateFrom}
                              onFocused={() => setHlRow(r.user_id)}
                            />
                          ) : null}
                        </>
                      );
                    })()}
                    {/* Iter 136 (user request) — Total Deduction before Net Pay */}
                    <Text style={[styles.tblCell, styles.rightCell, { width: colW.num, fontWeight: "700" }]}>{fmtInr(r.total_deduction)}</Text>
                    <Text style={[styles.tblCell, styles.rightCell, { width: colW.num, fontWeight: "700" }, stickyColRight(rowBg)]}>{fmtInr(r.net)}</Text>
                  </Pressable>
                  );
                })}
                <View style={[styles.tblRow, { backgroundColor: colors.brandTertiary }]}>
                  {/* Iter 379 — totals row follows Sr → UAN → ESIC → Name. */}
                  <Text style={[styles.tblCell, { width: colW.sr }, stickyCol(0, colors.brandTertiary)]}>—</Text>
                  <Text style={[styles.tblCell, { width: colW.uan }, stickyCol(colW.sr, colors.brandTertiary)]}>—</Text>
                  <Text style={[styles.tblCell, { width: colW.esi }, stickyCol(colW.sr + colW.uan, colors.brandTertiary)]}>—</Text>
                  <Text style={[styles.tblCell, { width: colW.name, fontWeight: "700" }, stickyCol(colW.sr + colW.uan + colW.esi, colors.brandTertiary)]}>TOTAL</Text>
                  <Text style={[styles.tblCell, { width: colW.father }]}>—</Text>
                  <Text style={[styles.tblCell, { width: colW.desg }]}>—</Text>
                  {/* Iter 370 (user request) — totals under EVERY column. */}
                  <Text style={[styles.tblCell, styles.rightCell, { width: colW.pd, fontWeight: "700" }, stickyCol(colW.sr + colW.uan + colW.esi + colW.name, colors.brandTertiary)]}>{fmtDaysTotal(sumCol("present_days"))}</Text>
                  {/* Iter 340 — OT Hours total.
                      Iter 644 — hidden when OVER TIME is disabled. */}
                  {hasOtCol ? (
                    <Text style={[styles.tblCell, styles.rightCell, { width: colW.num, fontWeight: "700" }]}>
                      {visibleRows.reduce((s, r) => {
                        const hr = Number((r as any).ot_hourly_rate) || 0;
                        return s + (hr > 0 ? (Number(r.ot_pay) || 0) / hr : Number((r as any).ot_hours) || 0);
                      }, 0).toFixed(1)}
                    </Text>
                  ) : null}
                  <Text style={[styles.tblCell, styles.rightCell, { width: colW.el, fontWeight: "700" }]}>{fmtDaysTotal(sumCol("esic_leave_days"))}</Text>
                  {/* Iter 171 — totals row follows the same column masks so
                      every figure lands under its own header. */}
                  {(() => {
                    const en = ((run.rows[0] as any)?.enabled_allowances ?? fmMask.en) as string[] | undefined;
                    const has = (k: string) => !en || en.includes(k) || k === "basic";
                    const ed = ((run.rows[0] as any)?.enabled_deductions ?? fmMask.ed) as string[] | undefined;
                    const hasDed = (k: string) => !ed || ed.includes(k);
                    const opt = ["basic", "hra", "conveyance", "medical", "special", "others"].filter(has);
                    const num = (v: any) => (
                      <Text style={[styles.tblCell, styles.rightCell, { width: colW.num, fontWeight: "700" }]}>{fmtInr(v)}</Text>
                    );
                    return (
                      <>
                        {/* Master group — Iter 370 (user request): head-wise
                            totals under EVERY column (were dashes). */}
                        {opt.map((k) => <React.Fragment key={`tm-${k}`}>{num(
                          k === "others"
                            ? sumCol("others_master") - visibleRows.reduce((s, r) => s + allowHeadsMaster(r), 0)
                            : sumCol(`${k}_master`))}</React.Fragment>)}
                        {/* Iter 644 — custom allowance head totals. */}
                        {allowLabels.map((l) => (
                          <React.Fragment key={`tam-${l}`}>{num(
                            visibleRows.reduce((s, r) => s + (Number(((r as any).allowance_heads_master || {})[l]) || 0), 0))}</React.Fragment>
                        ))}
                        {num(sumCol("gross_master"))}
                        {/* Calculated group totals (+Gross) */}
                        {opt.map((k) => <React.Fragment key={`tc-${k}`}>{num(
                          k === "others"
                            ? sumCol("others") - visibleRows.reduce((s, r) => s + allowHeadsPaid(r), 0)
                            : sumCol(k as any))}</React.Fragment>)}
                        {allowLabels.map((l) => (
                          <React.Fragment key={`tap-${l}`}>{num(
                            visibleRows.reduce((s, r) => s + (Number(((r as any).allowance_heads || {})[l]) || 0), 0))}</React.Fragment>
                        ))}
                        {/* Iter 339c — OT Amt total BEFORE Gross.
                            Iter 650 (user bug — "totals not proper head
                            wise") — EVERY total below is now the live SUM
                            of the displayed rows (was run.totals, which
                            could go stale after grid edits). */}
                        {hasOtCol ? num(sumCol("ot_pay")) : null}
                        {num(sumCol("gross_paid"))}
                        {/* Iter 335 — Freeze Salary total next to Gross. */}
                        {hasFrz ? num(sumCol("imported_gross" as any)) : null}
                        {/* Deductions group — Iter 370: Wage Base total too. */}
                        {num(sumCol("stat_wage_base"))}
                        {hasDed("pf") ? num(sumCol("pf_employee")) : null}
                        {hasDed("pf") ? num(sumCol("pf_employer_total" as any)) : null}
                        {hasDed("esi") ? num(sumCol("esic_employee")) : null}
                        {hasDed("esi") ? num(sumCol("esic_employer" as any)) : null}
                        {hasDed("pt") ? num(sumCol("pt" as any)) : null}
                        {hasDed("tds") ? num(sumCol("tds")) : null}
                        {/* Iter 644 (alignment fix) — totals under the
                            dynamic custom DEDUCTION head columns too. */}
                        {((((run.rows[0] as any)?.deduction_head_labels as string[]) || []).map((dl) => (
                          <React.Fragment key={`tdh-${dl}`}>{num(
                            visibleRows.reduce((s, r) => s + (Number(((r as any).deduction_heads || {})[dl]) || 0), 0))}</React.Fragment>
                        )))}
                        {hasDed("advance") ? num(visibleRows.reduce((s, r) => s + (Number((r as any).advance_recovery) || 0), 0)) : null}
                        {hasDed("other") ? num(visibleRows.reduce((s, r) => s + (Number((r as any).other_deduction) || 0), 0)) : null}
                        {num(sumCol("total_deduction"))}
                        <Text style={[styles.tblCell, styles.rightCell, { width: colW.num, fontWeight: "700" }, stickyColRight(colors.brandTertiary)]}>{fmtInr(sumCol("net"))}</Text>
                      </>
                    );
                  })()}
                </View>
            </GridScroller>
            </View>
          </View>
        ) : null}

        {/* Past runs — hidden from the front page (user directive).
            Open earlier runs from Utilities → Past Salary Runs. */}
        <Pressable
          onPress={() => router.push("/past-salary-runs")}
          style={styles.pastRow}
          testID="csr-open-past-runs"
        >
          <View style={styles.pastIcon}>
            <Ionicons name="albums-outline" size={18} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.pastTitle}>Past runs</Text>
            <Text style={styles.pastMeta}>
              Open earlier compliance runs from Utilities → Past Salary Runs
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
        </Pressable>
        {/* Iter 101 / Iter 255 — Imported Salary Sheet (email / manual
            file), moved to the BOTTOM of the page per user request. */}
        <View style={[styles.card, { marginTop: 12 }]}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Ionicons name="document-attach-outline" size={16} color={colors.brandPrimary} />
            <Text style={{ color: colors.onSurface, fontSize: 12.5, fontWeight: "700", flex: 1 }}>
              Import Salary Sheet — {month}
            </Text>
            {importBusy ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : null}
          </View>
          <Text style={{ color: colors.onSurfaceTertiary, fontSize: 11 }}>
            Same column format as the Attendance Master sheet: PF No, UAN, ESIC No,
            Emp ID, Name, Present Days, Deduction Head, Deduction Amount, Gross Earning.
          </Text>
          <Text
            testID="csr-import-status"
            style={{
              fontSize: 11.5, fontWeight: "700",
              color: importStatus?.count ? "#166534" : colors.onSurfaceTertiary,
            }}
          >
            {importStatus?.count
              ? `✓ ${importStatus.count} employee(s) imported — ${importStatus.source === "email" ? "from email" : "uploaded file"}${importStatus.filename ? `: ${importStatus.filename}` : ""}`
              : "No sheet imported for this month yet."}
          </Text>
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            <Pressable
              testID="csr-import-upload"
              onPress={pickAndUpload}
              disabled={importBusy}
              style={styles.secondaryBtn}
            >
              <Ionicons name="cloud-upload-outline" size={15} color={colors.brandPrimary} />
              <Text style={styles.secondaryBtnTxt}>Upload File (Excel / CSV)</Text>
            </Pressable>
            {user?.role === "super_admin" ? (
              <Pressable
                testID="csr-import-gmail"
                onPress={openMailPicker}
                disabled={importBusy}
                style={styles.secondaryBtn}
              >
                <Ionicons name="mail-open-outline" size={15} color={colors.brandPrimary} />
                <Text style={styles.secondaryBtnTxt}>Import from Email</Text>
              </Pressable>
            ) : null}
          </View>
          <Pressable
            testID="csr-use-imported-sheet"
            onPress={() => setUseImportedSheet((v) => !v)}
            style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 }}
          >
            <Ionicons
              name={useImportedSheet ? "checkbox" : "square-outline"}
              size={18}
              color={useImportedSheet ? colors.brandPrimary : colors.onSurfaceTertiary}
            />
            <Text style={{ color: colors.onSurface, fontSize: 12, fontWeight: "600", flex: 1 }}>
              Use imported sheet for this run — Present Days + Other Deductions
              replace biometric attendance.
            </Text>
          </Pressable>
        </View>

        {/* Iter 370 (user request) — Compliance Validation (Process Command
            Center) moved to the BOTTOM of the page. */}
        <ProcessCommandCenter
          companyId={activeCompanyId}
          month={month}
          processType="compliance"
          runExists={!!run}
          runFinalized={runFinalized}
          refreshKey={(run ? 1 : 0) + (runFinalized ? 2 : 0)}
        />

        {/* Iter 181 — payroll punch line (user request) */}
        <Text style={{
          color: colors.brandPrimary, fontSize: 12.5, fontWeight: "700",
          fontStyle: "italic", textAlign: "center", marginTop: 18, marginBottom: 8,
        }}>
          &ldquo;Your Satisfaction is Our First Ambition&rdquo;
        </Text>
      </ScrollView>

      {/* Enterprise footer summary — sticky run totals.
          Iter 390 (user request) — the footer follows the Firm Master's
          enabled Deductions (Master-linked): disabled heads are hidden. */}
      {run ? (() => {
        const ed = ((run.rows[0] as any)?.enabled_deductions ?? fmMask.ed) as string[] | undefined;
        const hasDed = (k: string) => !ed || ed.includes(k);
        return (
          <TotalsFooter
            caption={
              `${run.month}  ·  ${run.employees_count} employees  ·  month_days = ${run.month_days}` +
              (hasDed("pf") && pfMethodLabel ? `  ·  ${pfMethodLabel}` : "") +
              (run.payslips_generated_at ? `  ·  ${run.payslips_count} payslips pushed` : "")
            }
            items={[
            { label: "Gross", value: run.totals?.gross_paid ?? run.totals?.monthly_gross ?? 0 },
            ...(hasDed("pf") ? [
              { label: "PF (EE)", value: run.totals?.pf_employee ?? 0 },
              { label: "PF (ER)", value: run.totals?.pf_employer_total ?? 0 },
            ] : []),
            ...(hasDed("esi") ? [
              { label: "ESIC (EE)", value: run.totals?.esic_employee ?? 0 },
              { label: "ESIC (ER)", value: run.totals?.esic_employer ?? 0 },
            ] : []),
            ...(hasDed("pt") ? [{ label: "PT", value: run.totals?.pt ?? 0 }] : []),
            ...(hasDed("tds") ? [{ label: "TDS", value: run.totals?.tds ?? 0 }] : []),
            ...(hasDed("advance") ? [{ label: "Advance", value: run.totals?.advance_recovery ?? 0 }] : []),
            { label: "Deductions", value: run.totals?.total_deduction ?? 0 },
            { label: "Net Salary", value: run.totals?.net ?? 0, tone: "#059669" },
          ]} />
        );
      })() : null}

      {/* Employee config modal */}
      <EmployeeConfigModal
        visible={showConfig}
        onClose={() => setShowConfig(false)}
      />
    </View>
  );
}

// ---------------------------------------------------------------------------
// Present-Days cell (Iter 93) — local text state so typing "26.5" (or any
// 3+ keystroke value) isn't clamped/re-rendered mid-edit. Clamping to
// month days still happens in updatePresentDays() on COMMIT (blur/Enter).
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Iter 618 (user P0 — data integrity) — Excel-style editable grid cell with
// two EXPLICIT states:
//   • NAVIGATION mode (on focus): value shown selected; Arrow keys ONLY move
//     focus between cells — they can NEVER mutate the value.
//   • EDIT mode (typing or Enter): local text state; committed on blur or
//     Enter (Enter also hops down, Excel-style); Escape reverts.
// A commit fires ONLY when the admin actually typed (dirty flag), so merely
// traversing cells never stamps manual_override on untouched rows.
// ---------------------------------------------------------------------------
function EditableGridCell({
  col, idx, width, value, cellRefs, onCommit, onNav, onFocused,
}: {
  col: string;
  idx: number;
  width: number;
  value: number;
  cellRefs: React.MutableRefObject<Record<string, any>>;
  onCommit: (n: number) => void;
  onNav: (col: string, idx: number, key: string) => void;
  /** Iter 657 (user bug) — sync the ROW HIGHLIGHT whenever this cell gains
   * focus (click OR arrow-key hop), so the highlight follows the cursor. */
  onFocused?: () => void;
}) {
  const [txt, setTxt] = useState<string>(String(Math.round(value || 0)));
  const focusedRef = useRef(false);
  const editRef = useRef(false);   // EDIT mode (Enter / typing)
  const dirtyRef = useRef(false);  // admin actually typed something
  useEffect(() => {
    if (!focusedRef.current) setTxt(String(Math.round(value || 0)));
  }, [value]);
  const commit = () => {
    if (!dirtyRef.current) return;
    dirtyRef.current = false;
    const n = Number(txt.replace(/[^0-9.]/g, ""));
    if (!Number.isNaN(n) && txt.trim() !== "") onCommit(n);
    else setTxt(String(Math.round(value || 0)));
  };
  return (
    <TextInput
      ref={(el) => { cellRefs.current[`${col}:${idx}`] = el; }}
      value={txt}
      onChangeText={(v) => {
        setTxt(v.replace(/[^0-9.]/g, ""));
        dirtyRef.current = true;
        editRef.current = true;
      }}
      onFocus={() => {
        focusedRef.current = true;
        editRef.current = false;
        dirtyRef.current = false;
        setTxt(String(Math.round(value || 0)));
        onFocused?.();
      }}
      onBlur={() => { focusedRef.current = false; editRef.current = false; commit(); }}
      onKeyPress={(e: any) => {
        const key = e?.nativeEvent?.key;
        if (key === "ArrowUp" || key === "ArrowDown") {
          e.preventDefault?.();
          commit();
          onNav(col, idx, key);
        } else if (key === "ArrowLeft" || key === "ArrowRight") {
          if (!editRef.current) {
            e.preventDefault?.();
            onNav(col, idx, key);
          } // EDIT mode → let the caret move inside the text
        } else if (key === "Enter") {
          e.preventDefault?.();
          if (dirtyRef.current || editRef.current) {
            commit();
            editRef.current = false;
            onNav(col, idx, "ArrowDown"); // Excel: commit + hop down
          } else {
            editRef.current = true; // NAVIGATION → EDIT mode
          }
        } else if (key === "Escape") {
          e.preventDefault?.();
          dirtyRef.current = false;
          editRef.current = false;
          setTxt(String(Math.round(value || 0)));
        }
      }}
      keyboardType="decimal-pad"
      selectTextOnFocus
      style={[styles.tblCell, styles.rightCell, styles.editableCell, { width }]}
    />
  );
}

/* Iter 340 (user request) — manual OT HOURS cell (commit on blur/Enter):
   hours × per-hour OT rate lands in the OT Amt column.
   Iter 618 — dirty-guarded: blurring/tabbing through WITHOUT typing never
   re-commits (which used to stamp manual_override on frozen runs). */
function OTHoursCell({ width, value, onCommit, onFocused }: {
  width: number; value: number; onCommit: (n: number) => void;
  onFocused?: () => void;
}) {
  const [txt, setTxt] = useState<string>(String(value ?? 0));
  const focusedRef = useRef(false);
  const dirtyRef = useRef(false);
  useEffect(() => {
    if (!focusedRef.current) setTxt(String(value ?? 0));
  }, [value]);
  const commit = () => {
    if (!dirtyRef.current) return;
    dirtyRef.current = false;
    const n = Number(txt.replace(/[^0-9.]/g, ""));
    if (!Number.isNaN(n) && n >= 0 && txt.trim() !== "") onCommit(n);
    else setTxt(String(value ?? 0));
  };
  return (
    <TextInput
      value={txt}
      onChangeText={(v) => { setTxt(v.replace(/[^0-9.]/g, "")); dirtyRef.current = true; }}
      onFocus={() => { focusedRef.current = true; dirtyRef.current = false; onFocused?.(); }}
      onBlur={() => { focusedRef.current = false; commit(); }}
      onKeyPress={(e: any) => {
        const key = e?.nativeEvent?.key;
        if (key === "Enter") { e.preventDefault?.(); (e?.target as any)?.blur?.(); }
        else if (key === "ArrowUp" || key === "ArrowDown") { e.preventDefault?.(); }
        else if (key === "Escape") {
          e.preventDefault?.();
          dirtyRef.current = false;
          setTxt(String(value ?? 0));
        }
      }}
      keyboardType="decimal-pad"
      selectTextOnFocus
      style={[styles.tblCell, styles.rightCell, styles.editableCell, { width }]}
    />
  );
}

function PresentDaysCell({
  idx, value, pdRefs, onCommit, onNav, onFocused, frozen,
}: {
  idx: number;
  value: number;
  pdRefs: React.MutableRefObject<(TextInput | null)[]>;
  onCommit: (n: number) => void;
  onNav?: (key: "ArrowLeft" | "ArrowRight") => void;
  /** Iter 657 (user bug) — row highlight follows the focused cell. */
  onFocused?: () => void;
  /** Iter 657 (user request) — sticky style so the PD column freezes. */
  frozen?: any;
}) {
  const [txt, setTxt] = useState<string>(String(value ?? 0));
  const focusedRef = useRef(false);
  const editRef = useRef(false);   // Iter 618 — EDIT mode (Enter / typing)
  const dirtyRef = useRef(false);  // Iter 618 — admin actually typed

  useEffect(() => {
    if (focusedRef.current) return;
    setTxt(String(value ?? 0));
  }, [value]);

  const commit = () => {
    if (!dirtyRef.current) return; // Iter 618 — never commit untouched cells
    dirtyRef.current = false;
    const n = Number(txt.replace(/[^0-9.]/g, ""));
    // Iter 93 — present days only in half-day steps: .0 or .5
    if (!Number.isNaN(n) && txt.trim() !== "") onCommit(Math.round(n * 2) / 2);
    else setTxt(String(value ?? 0));
  };

  const focusRow = (next: number) => {
    const target = pdRefs.current[next];
    if (target && typeof (target as any).focus === "function") {
      (target as any).focus();
    }
  };

  return (
    <TextInput
      ref={(el) => { pdRefs.current[idx] = el; }}
      value={txt}
      onChangeText={(v) => {
        setTxt(v.replace(/[^0-9.]/g, ""));
        dirtyRef.current = true;
        editRef.current = true;
      }}
      onFocus={() => { focusedRef.current = true; editRef.current = false; dirtyRef.current = false; onFocused?.(); }}
      onBlur={() => { focusedRef.current = false; editRef.current = false; commit(); }}
      onKeyPress={(e: any) => {
        const key = e?.nativeEvent?.key;
        if (key === "ArrowUp" || key === "ArrowDown") {
          // Iter 618 — arrows ONLY move focus; value never mutates
          e.preventDefault?.();
          commit();
          focusRow(idx + (key === "ArrowDown" ? 1 : -1));
        } else if ((key === "ArrowLeft" || key === "ArrowRight") && onNav) {
          // Iter 256 — spreadsheet-style column hop (NAVIGATION mode only)
          if (!editRef.current) {
            e.preventDefault?.();
            onNav(key);
          }
        } else if (key === "Enter") {
          e.preventDefault?.();
          if (dirtyRef.current || editRef.current) {
            commit();
            editRef.current = false;
            focusRow(idx + 1); // Excel: commit + hop down
          } else {
            editRef.current = true; // NAVIGATION → EDIT mode
          }
        } else if (key === "Escape") {
          e.preventDefault?.();
          dirtyRef.current = false;
          editRef.current = false;
          setTxt(String(value ?? 0));
        }
      }}
      keyboardType="decimal-pad"
      selectTextOnFocus
      style={[
        styles.tblCell,
        styles.rightCell,
        styles.editableCell,
        frozen,
      ]}
    />
  );
}


// ---------------------------------------------------------------------------
// Employee compliance config modal
// ---------------------------------------------------------------------------
function EmployeeConfigModal({
  visible,
  onClose,
}: {
  visible: boolean;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<EmployeeLite[]>([]);
  const [dirty, setDirty] = useState<Record<string, Partial<EmployeeLite>>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!visible) return;
    (async () => {
      setLoading(true);
      try {
        const r = await api<{ employees: EmployeeLite[] }>("/admin/employees");
        setRows(r.employees || []);
        setDirty({});
      } catch (e: any) {
        showMsg(e?.message || "Could not load employees");
      } finally { setLoading(false); }
    })();
  }, [visible]);

  const filtered = useMemo(() => {
    if (!search.trim()) return rows;
    const s = search.trim().toLowerCase();
    return rows.filter(
      (r) =>
        (r.name || "").toLowerCase().includes(s) ||
        (r.employee_code || "").toLowerCase().includes(s),
    );
  }, [rows, search]);

  const patch = (uid: string, field: keyof EmployeeLite, value: any) => {
    setDirty((d) => ({ ...d, [uid]: { ...(d[uid] || {}), [field]: value } }));
    setRows((prev) => prev.map((r) => (r.user_id === uid ? { ...r, [field]: value } : r)));
  };

  const saveAll = async () => {
    if (Object.keys(dirty).length === 0) { onClose(); return; }
    setSaving(true);
    try {
      let ok = 0;
      let err = 0;
      for (const [uid, changes] of Object.entries(dirty)) {
        try {
          await api("/admin/user-role", {
            method: "PATCH",
            body: { user_id: uid, ...changes },
          });
          ok += 1;
        } catch { err += 1; }
      }
      showMsg(`Saved ${ok} employee${ok === 1 ? "" : "s"}${err > 0 ? ` (${err} failed)` : ""}.`);
      setDirty({});
      if (err === 0) onClose();
    } finally { setSaving(false); }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <View style={styles.modalRoot}>
        <View style={styles.modalCard}>
          <View style={styles.modalHead}>
            <Text style={styles.cardTitle}>Configure employee compliance</Text>
            <Pressable onPress={onClose} hitSlop={8}>
              <Ionicons name="close" size={22} color={colors.onSurface} />
            </Pressable>
          </View>
          <Text style={styles.smallHint}>
            Set per-employee PF / ESIC eligibility, PT state and manual TDS. Leave
            fields blank to use defaults.
          </Text>

          <TextInput
            testID="csr-cfg-search"
            value={search}
            onChangeText={setSearch}
            placeholder="Search by name or code…"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={[styles.input, { marginTop: 8 }]}
            autoCapitalize="none"
          />

          {loading ? (
            <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
          ) : (
            <ScrollView style={{ maxHeight: 500 }}>
              {filtered.map((r) => (
                <View key={r.user_id} style={styles.empRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.empName}>
                      {r.name || "—"}{" "}
                      <Text style={styles.empCode}>({r.employee_code || "—"})</Text>
                    </Text>
                  </View>
                  <View style={styles.toggleWrap}>
                    <Text style={styles.tinyLabel}>PF</Text>
                    <Switch
                      value={r.pf_applicable !== false}
                      onValueChange={(v) => patch(r.user_id, "pf_applicable", v)}
                    />
                  </View>
                  <View style={styles.toggleWrap}>
                    <Text style={styles.tinyLabel}>ESIC</Text>
                    <Switch
                      value={r.esic_applicable !== false}
                      onValueChange={(v) => patch(r.user_id, "esic_applicable", v)}
                    />
                  </View>
                  <View style={{ width: 140 }}>
                    <Text style={styles.tinyLabel}>PT State</Text>
                    <PTStateSelect
                      value={r.pt_state || "None"}
                      onChange={(v) => patch(r.user_id, "pt_state", v)}
                    />
                  </View>
                  <View style={{ width: 90 }}>
                    <Text style={styles.tinyLabel}>Basic</Text>
                    <TextInput
                      value={r.basic_amount != null ? String(r.basic_amount) : ""}
                      onChangeText={(t) =>
                        patch(r.user_id, "basic_amount", t.trim() === "" ? null : Number(t) || 0)
                      }
                      keyboardType="numeric"
                      style={styles.smallInput}
                      placeholder="auto"
                      placeholderTextColor={colors.onSurfaceTertiary}
                    />
                  </View>
                  <View style={{ width: 90 }}>
                    <Text style={styles.tinyLabel}>TDS</Text>
                    <TextInput
                      value={r.tds_amount != null ? String(r.tds_amount) : ""}
                      onChangeText={(t) =>
                        patch(r.user_id, "tds_amount", t.trim() === "" ? null : Number(t) || 0)
                      }
                      keyboardType="numeric"
                      style={styles.smallInput}
                      placeholder="0"
                      placeholderTextColor={colors.onSurfaceTertiary}
                    />
                  </View>
                </View>
              ))}
              {filtered.length === 0 ? (
                <Text style={[styles.smallHint, { textAlign: "center", marginTop: 20 }]}>
                  No employees match your search.
                </Text>
              ) : null}
            </ScrollView>
          )}

          <View style={{ flexDirection: "row", gap: 8, marginTop: 14 }}>
            <Pressable onPress={onClose} style={styles.secondaryBtn}>
              <Text style={styles.secondaryBtnTxt}>Close</Text>
            </Pressable>
            <Pressable
              testID="csr-cfg-save"
              onPress={saveAll}
              disabled={saving}
              style={[styles.primaryBtn, saving && { opacity: 0.6 }, { flex: 1 }]}
            >
              {saving ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="save-outline" size={15} color="#fff" />
                  <Text style={styles.primaryBtnTxt}>
                    Save {Object.keys(dirty).length > 0 ? `(${Object.keys(dirty).length})` : ""}
                  </Text>
                </>
              )}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function PTStateSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <View>
      <Pressable style={styles.smallInput} onPress={() => setOpen((o) => !o)}>
        <Text style={{ color: colors.onSurface, fontSize: 12 }} numberOfLines={1}>
          {value}
        </Text>
      </Pressable>
      {open ? (
        <View style={styles.ptDrop}>
          <ScrollView style={{ maxHeight: 220 }}>
            {PT_STATES.map((s) => (
              <Pressable
                key={s}
                onPress={() => {
                  onChange(s);
                  setOpen(false);
                }}
                style={styles.ptOpt}
              >
                <Text style={styles.ptOptTxt}>{s}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      ) : null}
    </View>
  );
}

function PctInput({
  label,
  value,
  onChangeText,
  wide,
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  wide?: boolean;
}) {
  return (
    <View style={{ minWidth: wide ? 140 : 90 }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        keyboardType="decimal-pad"
        style={styles.input}
      />
    </View>
  );
}

// Iter 68 — Read-only chip used on the Compliance Salary screen to
// display values that can only be edited from Firm Settings.
function RoChip({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.roChip}>
      <Text style={styles.roChipLbl}>{label}</Text>
      <Text style={styles.roChipVal}>{value}</Text>
    </View>
  );
}

function TypeChip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[styles.chip, active && styles.chipActive]}>
      <Text style={[styles.chipTxt, active && styles.chipTxtActive]}>{label}</Text>
    </Pressable>
  );
}

function ActionBtn({
  icon, label, onPress, busy, primary, testID,
}: {
  icon: any; label: string; onPress: () => void; busy?: boolean; primary?: boolean; testID?: string;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={busy}
      testID={testID}
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
          <Text style={[styles.actionBtnTxt, primary && styles.actionBtnTxtPrimary]}>{label}</Text>
        </>
      )}
    </Pressable>
  );
}

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
    borderRadius: 16,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    ...shadow.card,
  },
  cardTitle: { ...type.h6, color: colors.onSurface, fontWeight: "700", marginBottom: 6 },
  subheading: {
    ...type.tiny,
    color: colors.onSurfaceSecondary,
    fontWeight: "700",
    marginTop: 12,
    marginBottom: 6,
    textTransform: "uppercase",
  },
  smallHint: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },

  // Iter 68 — Read-only chip strip for the "moved to Firm Settings" fields
  roChipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 6,
    marginBottom: 4,
  },
  roChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: "#F1F5F9",
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  roChipLbl: { color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "700", letterSpacing: 0.3 },
  roChipVal: { color: colors.onSurface, fontSize: 13, fontWeight: "800" },
  editInSettingsBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 5,
    backgroundColor: "#E0F2FE",
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: "#BAE6FD",
  },
  editInSettingsTxt: { color: "#0369A1", fontSize: 11, fontWeight: "800" },

  // Iter 85 — Pinned "Active Firm" bar at the top of the screen.
  firmSettingsBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    marginBottom: spacing.md,
  },
  firmSettingsIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center", justifyContent: "center",
  },
  firmSettingsLabel: {
    fontSize: 10,
    fontWeight: "700",
    textTransform: "uppercase",
    color: colors.onSurfaceSecondary,
    letterSpacing: 0.4,
  },
  firmSettingsName: {
    fontSize: 14,
    fontWeight: "700",
    color: colors.onSurface,
    marginTop: 2,
  },
  firmSettingsBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.pill,
  },
  firmSettingsBtnTxt: {
    color: "#FFF",
    fontSize: 12,
    fontWeight: "800",
  },

  gridRow: { flexDirection: "row", gap: 10, flexWrap: "wrap", marginBottom: 6 },
  gridCol: { flex: 1, minWidth: 140 },
  label: {
    ...type.tiny,
    color: colors.onSurfaceSecondary,
    fontWeight: "700",
    marginBottom: 4,
    marginTop: 4,
    textTransform: "uppercase",
  },
  tinyLabel: {
    ...type.tiny,
    color: colors.onSurfaceSecondary,
    fontWeight: "700",
    marginBottom: 2,
    textTransform: "uppercase",
    fontSize: 9,
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
  smallInput: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 6,
    color: colors.onSurface,
    backgroundColor: colors.surface,
    fontSize: 12,
  },
  chipStrip: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 6 },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.borderStrong,
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
  batchFirms: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    marginTop: 6,
  },
  firmChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.divider,
    backgroundColor: colors.surface,
    maxWidth: 200,
  },
  firmChipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  firmChipTxt: { fontSize: 12, fontWeight: "700" },
  linkChip: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    backgroundColor: colors.brandTertiary,
  },
  linkChipTxt: { color: colors.brandPrimary, fontSize: 11, fontWeight: "800" },
  batchStatus: {
    marginTop: 12,
    padding: 10,
    borderRadius: 8,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  batchStatusTitle: {
    fontSize: 12,
    fontWeight: "800",
    color: colors.onSurfaceSecondary,
    textTransform: "uppercase",
    marginBottom: 6,
  },
  batchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 6,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.divider,
  },
  batchRowName: { color: colors.onSurface, fontSize: 13, fontWeight: "600" },
  secondaryBtn: {
    paddingHorizontal: 14,
    paddingVertical: 12,
    marginTop: 8,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  secondaryBtnTxt: { color: colors.brandPrimary, fontWeight: "700" },

  rowBetween: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 6,
    flexWrap: "wrap",
  },
  actionBtn: {
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  actionBtnPrimary: { backgroundColor: colors.brandPrimary },
  actionBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  actionBtnTxtPrimary: { color: "#fff" },

  tblRow: { flexDirection: "row", minWidth: 1400, paddingHorizontal: 4 },
  tblHeader: { backgroundColor: colors.brandPrimary, borderTopLeftRadius: 6, borderTopRightRadius: 6 },
  tblHeaderTxt: { color: "#fff", fontWeight: "800" },
  // Iter 86 — Compliance Salary grid: 3-section group header + tinting
  // so admins can visually parse Master (green), Calculated (blue) and
  // Deductions (red) zones at a glance.
  groupHdrRow: { alignItems: "stretch", paddingHorizontal: 4 },
  groupHdrCell: {
    justifyContent: "center",
    alignItems: "center",
    paddingVertical: 6,
    borderRightWidth: 1,
    borderRightColor: "rgba(0,0,0,0.15)",
    borderTopLeftRadius: 4,
    borderTopRightRadius: 4,
  },
  groupHdrMaster: { backgroundColor: "rgba(16,185,129,0.22)" },  // green tint
  groupHdrCalc:   { backgroundColor: "rgba(59,130,246,0.22)" },  // blue tint
  groupHdrDed:    { backgroundColor: "rgba(239,68,68,0.20)" },   // red tint
  groupHdrTxt: { fontSize: 11, fontWeight: "800", color: "#0f172a", letterSpacing: 0.3 },
  // Faint horizontal-strip tints applied to the column-header cells
  // themselves. Kept lighter than the group-band above so the primary
  // header colour still reads.
  groupHdrCellHeaderMaster: { backgroundColor: "rgba(16,185,129,0.25)" },
  groupHdrCellHeaderCalc:   { backgroundColor: "rgba(59,130,246,0.25)" },
  groupHdrCellHeaderDed:    { backgroundColor: "rgba(239,68,68,0.20)" },
  // Iter 635 (user request — UI readability, VIEW ONLY) · Iter 643 (user
  // request) — grid font reduced by 2 (14 → 12) so more data fits.
  tblCell: {
    fontSize: 12,
    paddingVertical: 12,
    paddingHorizontal: 8,
    width: 84,
    color: colors.onSurface,
  },
  rightCell: { textAlign: "right", width: 84 },
  // Iter 636 — compact setup bar (shown when the setup cards collapse).
  // Iter 643 (user request) — Select firm + Configure Batch cards FROZEN
  // at the top of the page (web sticky; native keeps normal flow).
  stickyHeaderWrap: Platform.OS === "web"
    ? ({ position: "sticky", top: 0, zIndex: 40,
         backgroundColor: colors.background } as any)
    : {},
  compactBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginBottom: 8,
  },
  compactBarTxt: { flex: 1, fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  compactBarHint: { fontSize: 12, fontWeight: "800", color: colors.brandPrimary },
  // Iter 637 (user request) — compact single-line Configure Batch toolbar.
  batchTitle: { fontSize: 22, fontWeight: "800", color: colors.onSurface },
  batchLine: {
    flexDirection: "row",
    gap: 10,
    alignItems: "flex-end",
    flexWrap: "wrap",
    marginBottom: 6,
  },
  batchCol: { flexGrow: 0, minWidth: 210, maxWidth: 250, overflow: "hidden" },
  batchLabel: {
    fontSize: 12.5,
    fontWeight: "800",
    color: colors.onSurfaceSecondary,
    marginBottom: 4,
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  sumCard: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 6,
    minWidth: 92,
    minHeight: 60,
    alignItems: "center",
    justifyContent: "center",
  },
  sumLabel: { fontSize: 11.5, fontWeight: "800", color: colors.onSurfaceSecondary },
  sumVal: { fontSize: 20, fontWeight: "800", marginTop: 1 },
  infoPanel: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#F0F9FF",
    borderWidth: 1,
    borderColor: "#BAE6FD",
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 7,
    marginBottom: 6,
  },
  infoPanelTxt: { flex: 1, fontSize: 12.5, fontWeight: "600", color: "#0C4A6E" },
  // Iter 85 — Inline-editable Present Days cell in Compliance Salary grid.
  editableCell: {
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 7,
    backgroundColor: colors.brandTertiary,
    color: colors.onSurface,
    fontWeight: "700",
    width: 84,
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
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  pastTitle: { ...type.body, color: colors.onSurface, fontWeight: "600" },
  pastMeta: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 1 },

  // Modal
  modalRoot: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "center",
    alignItems: "center",
    padding: 20,
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: 20,
    width: "100%",
    maxWidth: 1000,
    maxHeight: "90%",
  },
  modalHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 4,
  },
  empRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  empName: { color: colors.onSurface, fontWeight: "600", fontSize: 13 },
  empCode: { color: colors.onSurfaceTertiary, fontWeight: "500", fontSize: 11 },
  toggleWrap: { alignItems: "center", width: 55 },
  ptDrop: {
    position: "absolute",
    top: 32,
    left: 0,
    right: 0,
    zIndex: 999,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: 6,
    elevation: 4,
  },
  ptOpt: { paddingHorizontal: 10, paddingVertical: 8 },
  ptOptTxt: { fontSize: 12, color: colors.onSurface },
});
