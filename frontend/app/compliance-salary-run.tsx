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
  Alert,
  Modal,
  Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as DocumentPicker from "expo-document-picker";

import { api, apiBinary } from "@/src/api/client";
import { confirmYesNo } from "@/src/utils/confirm";
import { EmployeeListSkeleton } from "@/src/components/EmployeeStatsBar";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
  
import MonthPicker from "@/src/components/MonthPicker";
import ProcessCommandCenter from "@/src/components/salary/ProcessCommandCenter";
import TotalsFooter from "@/src/components/salary/TotalsFooter";
import GridFilterChips, { GRID_FILTER_DEFAULT, rowMatchesFilters, type GridFilters } from "@/src/components/GridFilterChips";
import RegisterLayoutEditor from "@/src/components/RegisterLayoutEditor";
import { GridScroller, stickyCol, stickyHeader } from "@/src/components/GridFreeze";
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
  const d = new Date();
  d.setMonth(d.getMonth() - 1);
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
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

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
  const [layoutOpen, setLayoutOpen] = useState(false); // Iter 162 — PDF layout editor
  const [pushing, setPushing] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
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
  const [mailMsgs, setMailMsgs] = useState<any[]>([]);
  const [mailLoading, setMailLoading] = useState(false);
  // Iter 98 — display sorting for the compliance grid.
  const [sortBy, setSortBy] = useState<string>("");
  // Iter 182 — instant employee search + audit log
  const [empSearch, setEmpSearch] = useState("");
  const empSearchRef = useRef<TextInput | null>(null);
  // Iter 183 — Branch / Dept / Contractor filter chips.
  const [gridFilters, setGridFilters] = useState<GridFilters>(GRID_FILTER_DEFAULT);
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditEntries, setAuditEntries] = useState<any[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  // Iter 127e — AUTO-ADJUST every column to its widest content so nothing
  // is cut off (user request; replaces the wrap-text experiment).
  const colW = useMemo(() => {
    const rows = run?.rows || [];
    const px = (v: any) => String(v ?? "").length * 6.6 + 18;
    const fit = (label: string, vals: any[], base = 72, maxW = 240) => {
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
      name: fit("Name", rows.map((r: any) => r.name), 110),
      father: fit("Father Name", rows.map((r: any) => r.father_name), 100),
      desg: fit("Designation", rows.map((r: any) => r.designation), 90),
      uan: fit("UAN No.", rows.map((r: any) => r.uan_no), 80),
      esi: fit("ESIC No.", rows.map((r: any) => r.esi_ip_no), 80),
      pd: 72, // PresentDaysCell input is fixed-width
      num: fit("Wage Base", nums, 72, 130),
    };
  }, [run?.rows]);
  const sortRows = (rows: CompRow[]) => {
    // Iter 183 — branch/dept/contractor chips filter first…
    let base = rows.filter((r) => rowMatchesFilters(r, gridFilters));
    // …then Iter 182 — instant search filters the grid before sorting.
    const q = empSearch.trim().toLowerCase();
    if (q) {
      base = base.filter((r: any) =>
        [r.name, r.employee_code, r.uan_no, r.esi_ip_no, r.designation, r.father_name]
          .some((v) => String(v || "").toLowerCase().includes(q)));
    }
    if (!sortBy) return base;
    const num = (v: any) => Number(v ?? 0);
    const arr = [...base];
    if (sortBy === "name") arr.sort((a: any, b: any) => String(a.name || "").localeCompare(String(b.name || "")));
    else if (sortBy === "code") arr.sort((a: any, b: any) => num(a.employee_code) - num(b.employee_code));
    else if (sortBy === "net") arr.sort((a: any, b: any) => num(b.net) - num(a.net));
    else if (sortBy === "gross") arr.sort((a: any, b: any) => num(b.gross) - num(a.gross));
    return arr;
  };

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

  const openAudit = async () => {
    setAuditOpen(true);
    setAuditLoading(true);
    try {
      const p = new URLSearchParams({ limit: "60" });
      if (run?.run_id) p.set("run_id", run.run_id);
      else if (month) p.set("month", month);
      const r = await api<{ entries: any[] }>(`/admin/salary-audit-log?${p.toString()}`);
      setAuditEntries(r.entries);
    } catch { setAuditEntries([]); }
    setAuditLoading(false);
  };

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

  useEffect(() => {
    if (!activeCompanyId) return;
    (async () => {
      try {
        const r = await api<{ policy: any }>(
          `/admin/companies/${activeCompanyId}/compliance-policy`,
        );
        const p = r.policy || {};
        // Salary structure — fall back to hard-coded global defaults
        if (p.basic_pct !== undefined) setBasicPct(String(p.basic_pct));
        else setBasicPct("40");
        if (p.hra_pct !== undefined) setHraPct(String(p.hra_pct));
        else setHraPct("20");
        if (p.conveyance_pct !== undefined) setConvPct(String(p.conveyance_pct));
        else setConvPct("5");
        if (p.medical_pct !== undefined) setMedicalPct(String(p.medical_pct));
        else setMedicalPct("3");
        if (p.special_pct !== undefined) setSpecialPct(String(p.special_pct));
        else setSpecialPct("32");
        if (p.others_pct !== undefined) setOthersPct(String(p.others_pct));
        else setOthersPct("0");
        // Statutory config
        if (p.pf_wage_cap !== undefined) setPfCap(String(p.pf_wage_cap));
        else setPfCap("15000");
        if (p.pf_employee_rate !== undefined) setPfPctEmp(String(p.pf_employee_rate));
        else setPfPctEmp("12");
        if (p.esic_wage_threshold !== undefined) setEsiThreshold(String(p.esic_wage_threshold));
        else setEsiThreshold("21000");
        if (p.stat_wage_floor_pct !== undefined) setStatFloorPct(String(p.stat_wage_floor_pct));
        else setStatFloorPct("50");
      } catch {
        // If the firm has no policy override yet, keep the hard-coded
        // defaults already set in the initial state.
      }
    })();
  }, [activeCompanyId]);

  const loadRuns = useCallback(async () => {
    try {
      const r = await api<{ runs: CompRun[] }>("/admin/compliance-salary-runs");
      setRuns(r.runs || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { if (isAdmin) loadRuns(); }, [isAdmin, loadRuns]);

  const buildBody = () => {
    const body: any = {
      month,
      structure_pct: {
        basic: Number(basicPct) || 0,
        hra: Number(hraPct) || 0,
        conveyance: Number(convPct) || 0,
        medical: Number(medicalPct) || 0,
        special: Number(specialPct) || 0,
        others: Number(othersPct) || 0,
      },
      statutory_cfg: {
        pf_wage_cap: Number(pfCap) || 15000,
        pf_percent_employee: Number(pfPctEmp) || 12,
        esic_gross_threshold: Number(esiThreshold) || 21000,
        stat_wage_floor_pct: Number(statFloorPct) || 50,
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
        body: { company_id: activeCompanyId, month, filename: asset.name, content_base64: b64 },
      });
      setUseImportedSheet(true);
      await loadImportStatus();
      showMsg(
        `Imported ${r.matched} of ${r.total_rows} rows` +
        (r.unmatched_count ? ` — ${r.unmatched_count} row(s) had no matching employee.` : "."),
      );
    } catch (e: any) {
      showMsg(e?.message || "Import failed");
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
      showMsg(
        `Imported ${r.matched} of ${r.total_rows} rows from "${att.filename}"` +
        (r.unmatched_count ? ` — ${r.unmatched_count} row(s) had no matching employee.` : "."),
      );
    } catch (e: any) {
      showMsg(e?.message || "Import failed");
    } finally { setImportBusy(false); }
  };

  const generate = async () => {
    if (busy) return;
    // Iter 129e (user directive) — if a run for this firm + month already
    // exists, ask before reprocessing. "No" reloads the page unchanged.
    const q: any = buildBody();
    const existing = runs.find(
      (r: any) => r.month === q.month && (!q.company_id || r.company_id === q.company_id),
    );
    if (existing) {
      if ((existing as any).finalized) {
        showMsg(
          "This month's salary is already FINALIZED for this firm — it cannot be processed again. Use Unlock Request to de-finalize first.",
        );
        return;
      }
      const ok = await confirmYesNo(
        "This salary was already processed for this firm & month.\nDo you want to REPROCESS this salary again?",
      );
      if (!ok) {
        if (Platform.OS === "web") window.location.reload();
        return;
      }
    }
    setBusy(true);
    try {
      const r = await api<{ run: CompRun }>("/admin/compliance-salary-runs", {
        method: "POST",
        body: buildBody(),
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

  const reprocess = async () => {
    if (!run || reprocessing) return;
    if ((run as any).finalized) {
      showMsg("This run is finalized (read-only). It cannot be reprocessed.");
      return;
    }
    const ok = await confirmYesNo(
      "Do you want to REPROCESS this salary again?\nThe sheet will be recomputed with the current parameters.",
    );
    if (!ok) {
      if (Platform.OS === "web") window.location.reload();
      return;
    }
    setReprocessing(true);
    try {
      const r = await api<{ run: CompRun }>(
        `/admin/compliance-salary-runs/${run.run_id}/reprocess`,
        { method: "POST", body: buildBody() },
      );
      setRun(r.run);
      await loadRuns();
      showMsg("Recomputed with the current parameters ✓");
    } catch (e: any) {
      showMsg(e?.message || "Reprocess failed");
    } finally { setReprocessing(false); }
  };

  const finalizeRun = async () => {
    if (!run || finalizing) return;
    const okGo = Platform.OS === "web"
      ? globalThis.confirm("Finalize this compliance run? It becomes LOCKED — nobody can change it without Super Admin approval.")
      : true;
    if (!okGo) return;
    setFinalizing(true);
    try {
      const r = await api<{ ok: boolean; finalized_at?: string }>(
        `/admin/compliance-salary-runs/${run.run_id}/finalize`,
        { method: "POST", body: {} },
      );
      setRun({ ...(run as any), finalized: true, finalized_at: r.finalized_at } as any);
      await loadRuns();
      showMsg("Run finalized ✓ — locked. Challans can now be uploaded for this month.");
    } catch (e: any) {
      showMsg(e?.message || "Finalize failed");
    } finally { setFinalizing(false); }
  };

  // Iter 126h — Draft / lock workflow.
  // Iter 145 (P0 fix) — "Save as Draft" now actually PERSISTS the edited
  // grid (Present Days / Others / Other Deduction) to the backend. It used
  // to be a no-op, so every edit vanished when the run was reopened.
  const [savingDraft, setSavingDraft] = useState(false);
  // Iter 182 — silent auto-save: 3s after any grid edit the draft is
  // stored automatically (skips finalized runs and the initial compute).
  const autoSaveSkipRef = useRef<string | null>(null);
  const [autoSavedAt, setAutoSavedAt] = useState<string | null>(null);
  useEffect(() => {
    if (!run || (run as any).finalized) return;
    if (autoSaveSkipRef.current !== run.run_id) {
      // first sighting of this run (compute/open) — don't auto-save yet
      autoSaveSkipRef.current = run.run_id;
      return;
    }
    const t = setTimeout(async () => {
      try {
        await api(`/admin/compliance-salary-runs/${run.run_id}/save-rows`, {
          method: "POST",
          body: { rows: run.rows, totals: run.totals },
        });
        setAutoSavedAt(new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }));
      } catch { /* silent */ }
    }, 3000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      showMsg("Saved as draft ✓ — your edits are stored and will be there when you reopen this run.");
    } catch (e: any) {
      showMsg(e?.message || "Draft save failed");
    } finally { setSavingDraft(false); }
  };

  // Iter 145 — safety net: auto-save the edited grid (debounced 2.5s) so
  // edits survive even if the admin forgets to press "Save as Draft".
  const runRef = useRef<CompRun | null>(null);
  useEffect(() => { runRef.current = run; }, [run]);
  const autoSaveTimer = useRef<any>(null);
  const scheduleDraftAutoSave = useCallback(() => {
    if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
    autoSaveTimer.current = setTimeout(async () => {
      const r = runRef.current;
      if (!r || (r as any).finalized) return;
      try {
        await api(`/admin/compliance-salary-runs/${r.run_id}/save-rows`, {
          method: "POST",
          body: { rows: r.rows, totals: r.totals },
        });
      } catch {
        // silent — the explicit "Save as Draft" button surfaces errors
      }
    }, 2500);
  }, []);
  useEffect(() => () => {
    if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
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

  const downloadFile = async (kind: "csv" | "pdf" | "pdf2" | "xlsx" | "ecr" | "esic-mc" | "esic-reg") => {
    if (!run || downloading) return;
    setDownloading(true);
    try {
      const url =
        kind === "csv"
          ? `/admin/compliance-salary-runs/${run.run_id}/export.csv`
          : kind === "xlsx"
            ? `/admin/compliance-salary-runs/${run.run_id}/export.xlsx`
            : kind === "pdf"
              ? `/admin/compliance-salary-runs/${run.run_id}/register.pdf`
              : kind === "pdf2"
                ? `/admin/compliance-salary-runs/${run.run_id}/register.pdf?variant=2`
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
                    ? `PF_ECR_${run.month}.txt`
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
      openPastRun({ run_id: String(urlParams.run_id) } as CompRun);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlParams.run_id, isAdmin]);

  // Iter 162 — auto-open the LAST processed run on screen load so the
  // report is visible without clicking "Process Salary" (user request).
  const autoOpenedRef = React.useRef(false);
  useEffect(() => {
    if (!isAdmin || urlParams.run_id || autoOpenedRef.current || !activeCompanyId) return;
    autoOpenedRef.current = true;
    (async () => {
      try {
        const j = await api<{ runs: CompRun[] }>(
          `/admin/compliance-salary-runs?company_id=${encodeURIComponent(activeCompanyId)}`,
        );
        const latest = (j.runs || [])[0];
        if (latest?.run_id) await openPastRun(latest);
      } catch { /* screen stays on fresh state */ }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin, activeCompanyId]);

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

  // Client-side setter for individual row fields (Others allowance,
  // Other deduction). Recomputes Gross + Net locally so the grid
  // stays in sync while editing.
  const updateRowField = (userId: string, key: "others" | "other_deduction", value: number) => {
    setRun((prev) => {
      if (!prev) return prev;
      const rows = prev.rows.map((r) => {
        if (r.user_id !== userId) return r;
        const next = { ...r, [key]: value } as any;
        if (key === "others") {
          const gross = (next.basic || 0) + (next.hra || 0) + (next.conveyance || 0)
            + (next.medical || 0) + (next.special || 0) + (next.others || 0);
          next.gross_paid = Math.round(gross);
        }
        const dedTotal = (next.pf_employee || 0) + (next.esic_employee || 0)
          + (next.pt || 0) + (next.tds || 0) + (next.other_deduction || 0);
        next.total_deduction = Math.round(dedTotal);
        next.net = Math.round((next.gross_paid || 0) - dedTotal);
        return next;
      });
      return { ...prev, rows };
    });
    scheduleDraftAutoSave(); // Iter 145 — persist edits automatically
  };

  const updatePresentDays = (userId: string, newPd: number) => {
    if (!run) return;
    const monthDays = Math.max(1, run.month_days || 30);
    const stat = (run.statutory_cfg || {}) as any;
    const pfEmpRate = Number(stat.pf_percent_employee ?? stat.pf_employee_rate ?? 12) / 100;
    const pfErEpfRate = Number(stat.pf_percent_employer_epf ?? 3.67) / 100;
    const pfErEpsRate = Number(stat.pf_percent_employer_eps ?? 8.33) / 100;
    const pfCap = Number(stat.pf_wage_cap ?? 15000);
    const floorPct = Number(stat.stat_wage_floor_pct ?? 50) / 100;
    const esiEmpRate = Number(stat.esic_percent_employee ?? stat.esic_employee_rate ?? 0.75) / 100;
    const esiErRate  = Number(stat.esic_percent_employer ?? stat.esic_employer_rate ?? 3.25) / 100;
    const esiThresh  = Number(stat.esic_gross_threshold ?? stat.esic_wage_threshold ?? 21000);

    setRun((prev) => {
      if (!prev) return prev;
      const rows = prev.rows.map((r) => {
        if (r.user_id !== userId) return r;

        const pd = Math.max(0, Math.min(monthDays, Number(newPd) || 0));
        const ratio = pd / monthDays;

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
        const grossPaid = paidBasic + paidHra + paidConv + paidMed + paidSpl + paidOth;

        // Statutory wage base — mirrors utils/compliance_salary.py:
        // max(Basic, floor% of Gross Earning) (used by ESIC below).
        const statWageBase = Math.max(paidBasic, grossPaid * floorPct);
        // Iter 129 (user directive) — PF ONLY when the Employee Master's
        // "PF Basic Salary" (pf_basic) is filled. Wages = max(PF Basic,
        // floor% of Gross), capped at the EPF ceiling unless the explicit
        // PF Basic exceeds it.
        const pfBasicFull = Number((r as any).pf_basic || 0);
        const pfOn = r.pf_applicable !== false && pfBasicFull > 0;
        const pfBasicPro = (r as any).salary_mode === "monthly" ? pfBasicFull * ratio : pfBasicFull;
        const pfWagesNew = pfOn
          ? Math.min(Math.max(pfBasicPro, grossPaid * floorPct), Math.max(pfCap, pfBasicPro))
          : 0;
        const pfEmp = pfWagesNew * pfEmpRate;
        const pfErEpf = pfWagesNew * pfErEpfRate;
        const pfErEps = pfWagesNew * pfErEpsRate;
        const pfErTot = pfErEpf + pfErEps;

        // ESIC (Iter 130 user directive): calculated ON BASIC salary (earned
        // basic). Eligibility is by FULL-MONTH Basic ≤ the Compliance
        // Settings limit (not gross).
        const esiApplicable = r.esic_applicable !== false && grossPaid > 0 && fullByHead.basic <= esiThresh;
        const esiBase = esiApplicable ? paidBasic : 0;
        const esiEmp = esiApplicable ? Math.ceil(esiBase * esiEmpRate) : 0;
        const esiEr  = esiApplicable ? Math.ceil(esiBase * esiErRate)  : 0;

        const pt = Number(r.pt || 0);   // keep PT slab as-is
        const tds = Number(r.tds || 0); // keep TDS as-is
        const otherDed = Number((r as any).other_deduction || 0);
        const totalDed = Math.round(pfEmp) + esiEmp + pt + tds + otherDed;
        const net = grossPaid - totalDed;

        return {
          ...r,
          present_days: pd,
          basic: Math.round(paidBasic),
          hra: Math.round(paidHra),
          conveyance: Math.round(paidConv),
          medical: Math.round(paidMed),
          special: Math.round(paidSpl),
          others: Math.round(paidOth),
          monthly_gross: Math.round(grossPaid),
          gross_paid: Math.round(grossPaid),
          pf_applicable: pfOn,
          pf_wages: Math.round(pfWagesNew),
          pf_employee: Math.round(pfEmp),
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
    scheduleDraftAutoSave(); // Iter 145 — persist edits automatically
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
                ? "PF · ESIC · PT · TDS  —  New labour-code wage base"
                : "Best used on desktop / web portal"}
            </Text>
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Iter 85 — Pinned Firm Settings shortcut at the top of the tab.
            Shows the currently-active firm and a one-tap link to jump
            into that firm's Compliance Policy screen so admins can
            tune Basic/HRA/PF/ESIC without scrolling down. */}
        <View style={styles.firmSettingsBar}>
          <View style={styles.firmSettingsIcon}>
            <Ionicons name="business-outline" size={18} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.firmSettingsLabel}>Active Firm</Text>
            <Text style={styles.firmSettingsName} numberOfLines={1}>
              {(ctxCompanies || []).find((c: any) => c.company_id === activeCompanyId)?.name
                || user?.company_id
                || (isSuper ? "All firms — pick one from the list below" : "—")}
            </Text>
          </View>
          <Pressable
            onPress={() =>
              router.push(
                activeCompanyId
                  ? `/compliance-policy?company_id=${encodeURIComponent(activeCompanyId)}`
                  : "/compliance-policy",
              )
            }
            style={styles.firmSettingsBtn}
            testID="csr-firm-settings-top"
            disabled={!activeCompanyId}
          >
            <Ionicons name="settings-outline" size={14} color="#FFF" />
            <Text style={styles.firmSettingsBtnTxt}>Firm Settings</Text>
          </Pressable>
        </View>

        {/* Enterprise Process Command Center — KPI cards, workflow stepper
            and live compliance validation (DB-driven per firm + month). */}
        <ProcessCommandCenter
          companyId={activeCompanyId}
          month={month}
          processType="compliance"
          runExists={!!run}
          runFinalized={runFinalized}
          refreshKey={(run ? 1 : 0) + (runFinalized ? 2 : 0)}
        />

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

        {/* Config card */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Configure batch</Text>

          <View style={styles.gridRow}>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Month</Text>
              <MonthPicker
                value={month}
                onChange={setMonth}
                allowEmpty={false}
                testID="csr-month"
              />
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>
                Month days (override) · Max {calendarDaysInMonth(month)}
              </Text>
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
                style={styles.input}
                keyboardType="numeric"
                maxLength={2}
              />
            </View>
          </View>

          <View style={styles.gridRow}>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Employee group</Text>
              <View style={styles.chipStrip}>
                {/* Iter 85 pt 2 — "All" chip removed from Compliance Salary
                    Process. Reports keep an "All" filter but processing
                    must always target ONE employee type. */}
                {types.map((t) => (
                  <TypeChip
                    key={t.name}
                    label={`${t.name} (${t.count})`}
                    active={empType === t.name}
                    onPress={() => setEmpType(t.name)}
                  />
                ))}
              </View>
            </View>
          </View>

          {/* Iter 85 — Roll filter removed. Compliance Salary Process
              is intentionally locked to ON-ROLL employees only, so the
              chip strip and All/Off-roll options are no longer shown. */}

          {/* Iter 85 — Salary Structure + Statutory Config read-only
              chip strips hidden per user request. The Firm Settings
              button at the TOP of this screen already surfaces these
              values on the Compliance Policy page, so showing them again
              here was redundant. */}

          {/* Iter 101 — Imported Salary Sheet (email / manual file).
              Replaces the old Attendance Master link per user request. */}
          <View
            style={{
              marginTop: 10, borderWidth: 1, borderColor: colors.divider,
              borderRadius: 10, padding: 12, gap: 8, backgroundColor: colors.surface,
            }}
          >
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

          {/* Iter 182 — Audit Log modal */}
          <Modal
            visible={auditOpen}
            transparent
            animationType="fade"
            onRequestClose={() => setAuditOpen(false)}
          >
            <View style={{
              flex: 1, backgroundColor: "rgba(15,23,42,0.45)",
              alignItems: "center", justifyContent: "center", padding: 20,
            }}>
              <View style={{
                backgroundColor: colors.surfaceSecondary, borderRadius: 16, padding: 16,
                width: "100%", maxWidth: 560, maxHeight: "80%",
                borderWidth: 1, borderColor: colors.border,
              }}>
                <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                  <Text style={{ fontSize: 15, fontWeight: "800", color: colors.onSurface }}>
                    🕘 Salary Process Audit Log
                  </Text>
                  <Pressable onPress={() => setAuditOpen(false)} hitSlop={10} testID="comp-audit-close">
                    <Ionicons name="close" size={18} color={colors.onSurfaceSecondary} />
                  </Pressable>
                </View>
                {auditLoading ? (
                  <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 24 }} />
                ) : auditEntries.length === 0 ? (
                  <Text style={{ fontSize: 12, color: colors.onSurfaceSecondary, paddingVertical: 16 }}>
                    No audit entries yet — actions (process / save / finalize / unlock) will appear here.
                  </Text>
                ) : (
                  <ScrollView style={{ maxHeight: 420 }}>
                    {auditEntries.map((a) => {
                      const ui: any = {
                        process: { c: "#2563EB", i: "play-circle-outline" },
                        save_rows: { c: "#0891B2", i: "save-outline" },
                        finalize: { c: "#16A34A", i: "lock-closed-outline" },
                        unlock: { c: "#F97316", i: "lock-open-outline" },
                      }[a.action] || { c: colors.onSurfaceSecondary, i: "ellipse-outline" };
                      return (
                        <View key={a.audit_id} style={{
                          flexDirection: "row", gap: 10, paddingVertical: 8,
                          borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
                        }}>
                          <Ionicons name={ui.i} size={16} color={ui.c} style={{ marginTop: 2 }} />
                          <View style={{ flex: 1 }}>
                            <Text style={{ fontSize: 12, fontWeight: "700", color: colors.onSurface }}>
                              {String(a.action).replace("_", " ").toUpperCase()}
                              {a.month ? `  ·  ${a.month}` : ""}
                            </Text>
                            <Text style={{ fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 1 }}>
                              {a.detail || ""}{a.company_name ? `  ·  ${a.company_name}` : ""}
                            </Text>
                            <Text style={{ fontSize: 9.5, color: colors.onSurfaceTertiary, marginTop: 2 }}>
                              {a.actor_name || a.actor_id} ({a.actor_role}) · {String(a.at || "").slice(0, 16).replace("T", " ")}
                            </Text>
                          </View>
                        </View>
                      );
                    })}
                  </ScrollView>
                )}
              </View>
            </View>
          </Modal>

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

          <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
            <Pressable
              testID="csr-configure-employees"
              onPress={() => setShowConfig(true)}
              style={styles.secondaryBtn}
            >
              <Ionicons name="people-outline" size={15} color={colors.brandPrimary} />
              <Text style={styles.secondaryBtnTxt}>Configure employees</Text>
            </Pressable>
            <Pressable
              testID="csr-generate"
              onPress={generate}
              disabled={busy}
              style={[styles.primaryBtn, busy && { opacity: 0.6 }, { flex: 1 }]}
            >
              {busy ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="shield-checkmark-outline" size={16} color="#fff" />
                  <Text style={styles.primaryBtnTxt}>Salary Process</Text>
                </>
              )}
            </Pressable>
          </View>
        </View>

        {/* Iter 182 — loading skeleton while a run computes */}
        {busy && !run ? <EmployeeListSkeleton rows={6} /> : null}

        {/* Result table */}
        {run ? (
          <View style={styles.card}>
            <View style={styles.rowBetween}>
              <View style={{ flex: 1 }}>
                <Text style={styles.cardTitle}>
                  {run.month}  ·  {run.employees_count} employees  ·  Net {fmtInr(run.totals?.net)}
                </Text>
                <Text style={styles.smallHint}>
                  month_days = {run.month_days} · PF (Emp): {fmtInr(run.totals?.pf_employee)} · ESIC (Emp): {fmtInr(run.totals?.esic_employee)} · PT: {fmtInr(run.totals?.pt)} · TDS: {fmtInr(run.totals?.tds)}
                  {run.payslips_generated_at
                    ? `  ·  ${run.payslips_count} payslips pushed`
                    : ""}
                </Text>
              </View>
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
                    <ActionBtn icon="save-outline" label="Save as Draft" onPress={saveAsDraft} />
                    <ActionBtn icon="checkmark-done-outline" label="Finalize (Lock)" busy={finalizing} onPress={finalizeRun} primary />
                  </>
                )}
                <ActionBtn icon="refresh" label="Reprocess" busy={reprocessing} onPress={reprocess} />
                <ActionBtn icon="grid-outline" label="Excel" busy={downloading} onPress={() => downloadFile("xlsx")} />
                <ActionBtn icon="document-text-outline" label="PDF" busy={downloading} onPress={() => downloadFile("pdf")} />
                <ActionBtn icon="document-outline" label="PDF (Option 2)" busy={downloading} onPress={() => downloadFile("pdf2")} />
                {user?.role === "super_admin" ? (
                  <ActionBtn icon="options-outline" label="PDF Layout ⚙" busy={false} onPress={() => setLayoutOpen(true)} />
                ) : null}
                <RegisterLayoutEditor visible={layoutOpen} onClose={() => setLayoutOpen(false)} />
                <ActionBtn icon="download-outline" label="CSV" busy={downloading} onPress={() => downloadFile("csv")} />
                <ActionBtn icon="time-outline" label="Audit Log" busy={auditLoading} onPress={openAudit} />
                {autoSavedAt ? (
                  <Text style={{ fontSize: 9.5, color: colors.success, fontWeight: "700", alignSelf: "center" }}>
                    ✓ Auto-saved {autoSavedAt}
                  </Text>
                ) : null}
                <ActionBtn icon="paper-plane-outline" label="Push payslips" busy={pushing} onPress={pushToPayslips} primary />
              </View>
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
            </View>

            {/* Iter 183 — Branch / Dept / Contractor filter chips */}
            <GridFilterChips rows={run.rows} filters={gridFilters} onChange={setGridFilters} testPrefix="comp" />

            <GridScroller>
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
                  const en = (run.rows[0] as any)?.enabled_allowances as string[] | undefined;
                  const has = (k: string) => !en || en.includes(k) || k === "basic";
                  const CELL_W = colW.num;
                  const INFO_W = colW.name + colW.father + colW.desg + colW.uan + colW.esi + colW.pd;
                  const FROZEN_W = colW.name + colW.father + colW.desg;
                  const optKeys = ["basic","hra","conveyance","medical","special","others"].filter((k) => has(k));
                  const masterCount = optKeys.length + 1; // +M.Gross
                  const calcCount = optKeys.length + 1;   // +Gross
                  // Iter 171 — deduction columns follow Firm Master Deductions
                  const ed = (run.rows[0] as any)?.enabled_deductions as string[] | undefined;
                  const hasDed = (k: string) => !ed || ed.includes(k);
                  const dedCount = 4 // WageBase, Other, TotalDed, Net
                    + (hasDed("pf") ? 2 : 0) + (hasDed("esi") ? 2 : 0)
                    + (hasDed("pt") ? 1 : 0) + (hasDed("tds") ? 1 : 0);
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
                    </View>
                  );
                })()}
                {(() => {
                  const en = (run.rows[0] as any)?.enabled_allowances as string[] | undefined;
                  const has = (k: string) => !en || en.includes(k) || k === "basic";
                  const ed = (run.rows[0] as any)?.enabled_deductions as string[] | undefined;
                  const hasDed = (k: string) => !ed || ed.includes(k);
                  const headers: { label: string; group: "info" | "master" | "calc" | "ded" }[] = [
                    // User directive — Employee Code HIDDEN; show Father
                    // Name, Designation, UAN No. & ESIC No. instead.
                    { label: "Name", group: "info" },
                    { label: "Father Name", group: "info" },
                    { label: "Designation", group: "info" },
                    { label: "UAN No.", group: "info" },
                    { label: "ESIC No.", group: "info" },
                    { label: "Present Days", group: "info" },
                  ];
                  if (has("basic")) headers.push({ label: "M.Basic", group: "master" });
                  if (has("hra")) headers.push({ label: "M.HRA", group: "master" });
                  if (has("conveyance")) headers.push({ label: "M.Conv", group: "master" });
                  if (has("medical")) headers.push({ label: "M.Med", group: "master" });
                  if (has("special")) headers.push({ label: "M.Spl", group: "master" });
                  if (has("others")) headers.push({ label: "M.Others", group: "master" });
                  headers.push({ label: "M.Gross", group: "master" });
                  if (has("basic")) headers.push({ label: "Basic", group: "calc" });
                  if (has("hra")) headers.push({ label: "HRA", group: "calc" });
                  if (has("conveyance")) headers.push({ label: "Conv", group: "calc" });
                  if (has("medical")) headers.push({ label: "Med", group: "calc" });
                  if (has("special")) headers.push({ label: "Spl", group: "calc" });
                  if (has("others")) headers.push({ label: "Others*", group: "calc" });
                  headers.push({ label: "Gross", group: "calc" });
                  const dedLabels = [
                    "Wage Base",
                    // Iter 171 — deduction columns follow Firm Master Deductions
                    ...(hasDed("pf") ? ["PF (E)", "PF (Er)"] : []),
                    ...(hasDed("esi") ? ["ESI (E)", "ESI (Er)"] : []),
                    ...(hasDed("pt") ? ["PT"] : []),
                    ...(hasDed("tds") ? ["TDS"] : []),
                    "Other*", "Total Ded.", "Net",
                  ];
                  for (const d of dedLabels) headers.push({ label: d, group: "ded" });
                  return (
                    <View style={[styles.tblRow, styles.tblHeader]}>
                      {headers.map((h, i) => (
                        <Text
                          key={i}
                          numberOfLines={1}
                          style={[
                            styles.tblCell,
                            { width: i < 6
                                ? [colW.name, colW.father, colW.desg, colW.uan, colW.esi, colW.pd][i]
                                : colW.num },
                            styles.tblHeaderTxt,
                            i >= 5 && { textAlign: "right" },
                            h.group === "master" && styles.groupHdrCellHeaderMaster,
                            h.group === "calc" && styles.groupHdrCellHeaderCalc,
                            h.group === "ded" && styles.groupHdrCellHeaderDed,
                            i < 3 && stickyCol(
                              [0, colW.name, colW.name + colW.father][i],
                              colors.brandPrimary,
                            ),
                          ]}
                        >
                          {h.label}
                        </Text>
                      ))}
                    </View>
                  );
                })()}
                </View>
                {sortRows(run.rows).map((r, idx) => (
                  <View
                    key={r.user_id}
                    style={[
                      styles.tblRow,
                      idx % 2 === 0 && { backgroundColor: colors.surfaceSecondary },
                    ]}
                  >
                    <Text style={[styles.tblCell, { width: colW.name }, stickyCol(0, idx % 2 === 0 ? colors.surfaceSecondary : colors.surface)]} numberOfLines={1}>{r.name || "—"}</Text>
                    <Text style={[styles.tblCell, { width: colW.father }, stickyCol(colW.name, idx % 2 === 0 ? colors.surfaceSecondary : colors.surface)]} numberOfLines={1}>{(r as any).father_name || "—"}</Text>
                    <Text style={[styles.tblCell, { width: colW.desg }, stickyCol(colW.name + colW.father, idx % 2 === 0 ? colors.surfaceSecondary : colors.surface)]} numberOfLines={1}>{(r as any).designation || "—"}</Text>
                    <Text style={[styles.tblCell, { width: colW.uan }]} numberOfLines={1}>{(r as any).uan_no || "—"}</Text>
                    <Text style={[styles.tblCell, { width: colW.esi }]} numberOfLines={1}>{(r as any).esi_ip_no || "—"}</Text>
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
                    />
                    {/* Iter 85 pt 1 — Master (full-month) heads,
                        conditionally rendered per firm allowance mask. */}
                    {(() => {
                      const en = (r as any).enabled_allowances as string[] | undefined;
                      const has = (k: string) => !en || en.includes(k) || k === "basic";
                      return (
                        <>
                          {has("basic") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).basic_master)}</Text> : null}
                          {has("hra") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).hra_master)}</Text> : null}
                          {has("conveyance") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).conveyance_master)}</Text> : null}
                          {has("medical") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).medical_master)}</Text> : null}
                          {has("special") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).special_master)}</Text> : null}
                          {has("others") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).others_master)}</Text> : null}
                          <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr((r as any).gross_master)}</Text>
                          {/* Calculated (pro-rated by Present Days). */}
                          {has("basic") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.basic)}</Text> : null}
                          {has("hra") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.hra)}</Text> : null}
                          {has("conveyance") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.conveyance)}</Text> : null}
                          {has("medical") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.medical)}</Text> : null}
                          {has("special") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.special)}</Text> : null}
                          {has("others") ? (
                            <TextInput
                              value={String(Math.round(r.others || 0))}
                              onChangeText={(v) => {
                                const n = Number(v.replace(/[^0-9.]/g, ""));
                                if (!Number.isNaN(n)) updateRowField(r.user_id, "others", n);
                              }}
                              keyboardType="decimal-pad"
                              selectTextOnFocus
                              style={[styles.tblCell, styles.rightCell, styles.editableCell, { width: colW.num }]}
                            />
                          ) : null}
                        </>
                      );
                    })()}
                    <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.gross_paid)}</Text>
                    <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.stat_wage_base)}</Text>
                    {/* Iter 171 — deduction cells follow Firm Master Deductions */}
                    {(() => {
                      const ed = (r as any).enabled_deductions as string[] | undefined;
                      const hasDed = (k: string) => !ed || ed.includes(k);
                      return (
                        <>
                          {hasDed("pf") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{r.pf_applicable ? fmtInr(r.pf_employee) : "—"}</Text> : null}
                          {hasDed("pf") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{r.pf_applicable ? fmtInr(r.pf_employer_total) : "—"}</Text> : null}
                          {hasDed("esi") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{r.esic_applicable ? fmtInr(r.esic_employee) : "—"}</Text> : null}
                          {hasDed("esi") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{r.esic_applicable ? fmtInr(r.esic_employer) : "—"}</Text> : null}
                          {hasDed("pt") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.pt)}</Text> : null}
                          {hasDed("tds") ? <Text style={[styles.tblCell, styles.rightCell, { width: colW.num }]}>{fmtInr(r.tds)}</Text> : null}
                        </>
                      );
                    })()}
                    {/* Iter 85 — Editable "Other" deduction. */}
                    <TextInput
                      value={String(Math.round((r as any).other_deduction || 0))}
                      onChangeText={(v) => {
                        const n = Number(v.replace(/[^0-9.]/g, ""));
                        if (!Number.isNaN(n)) updateRowField(r.user_id, "other_deduction", n);
                      }}
                      keyboardType="decimal-pad"
                      selectTextOnFocus
                      style={[styles.tblCell, styles.rightCell, styles.editableCell, { width: colW.num }]}
                    />
                    {/* Iter 136 (user request) — Total Deduction before Net Pay */}
                    <Text style={[styles.tblCell, styles.rightCell, { width: colW.num, fontWeight: "700" }]}>{fmtInr(r.total_deduction)}</Text>
                    <Text style={[styles.tblCell, styles.rightCell, { width: colW.num, fontWeight: "700" }]}>{fmtInr(r.net)}</Text>
                  </View>
                ))}
                <View style={[styles.tblRow, { backgroundColor: colors.brandTertiary }]}>
                  <Text style={[styles.tblCell, { width: colW.name, fontWeight: "700" }, stickyCol(0, colors.brandTertiary)]}>TOTAL</Text>
                  <Text style={[styles.tblCell, { width: colW.father }, stickyCol(colW.name, colors.brandTertiary)]}>—</Text>
                  <Text style={[styles.tblCell, { width: colW.desg }, stickyCol(colW.name + colW.father, colors.brandTertiary)]}>—</Text>
                  <Text style={[styles.tblCell, { width: colW.uan }]}>—</Text>
                  <Text style={[styles.tblCell, { width: colW.esi }]}>—</Text>
                  <Text style={[styles.tblCell, { width: colW.pd }]}>—</Text>
                  {/* Iter 171 — totals row follows the same column masks so
                      every figure lands under its own header. */}
                  {(() => {
                    const en = (run.rows[0] as any)?.enabled_allowances as string[] | undefined;
                    const has = (k: string) => !en || en.includes(k) || k === "basic";
                    const ed = (run.rows[0] as any)?.enabled_deductions as string[] | undefined;
                    const hasDed = (k: string) => !ed || ed.includes(k);
                    const opt = ["basic", "hra", "conveyance", "medical", "special", "others"].filter(has);
                    const num = (v: any) => (
                      <Text style={[styles.tblCell, styles.rightCell, { width: colW.num, fontWeight: "700" }]}>{fmtInr(v)}</Text>
                    );
                    const dash = () => <Text style={[styles.tblCell, { width: colW.num }]}>—</Text>;
                    return (
                      <>
                        {/* Master group — dashes (+M.Gross) */}
                        {opt.map((k) => <React.Fragment key={`tm-${k}`}>{dash()}</React.Fragment>)}
                        {dash()}
                        {/* Calculated group totals (+Gross) */}
                        {opt.map((k) => <React.Fragment key={`tc-${k}`}>{num((run.totals as any)?.[k])}</React.Fragment>)}
                        {num(run.totals?.gross_paid)}
                        {/* Deductions group */}
                        {dash()}
                        {hasDed("pf") ? num(run.totals?.pf_employee) : null}
                        {hasDed("pf") ? num(run.totals?.pf_employer_total) : null}
                        {hasDed("esi") ? num(run.totals?.esic_employee) : null}
                        {hasDed("esi") ? num(run.totals?.esic_employer) : null}
                        {hasDed("pt") ? num(run.totals?.pt) : null}
                        {hasDed("tds") ? num(run.totals?.tds) : null}
                        {num((run.rows || []).reduce((s, r) => s + (Number((r as any).other_deduction) || 0), 0))}
                        {num(run.totals?.total_deduction)}
                        {num(run.totals?.net)}
                      </>
                    );
                  })()}
                </View>
            </GridScroller>
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
        {/* Iter 181 — payroll punch line (user request) */}
        <Text style={{
          color: colors.brandPrimary, fontSize: 12.5, fontWeight: "700",
          fontStyle: "italic", textAlign: "center", marginTop: 18, marginBottom: 8,
        }}>
          &ldquo;Your Satisfaction is Our First Ambition&rdquo;
        </Text>
      </ScrollView>

      {/* Enterprise footer summary — sticky run totals */}
      {run ? (
        <TotalsFooter items={[
          { label: "Gross", value: run.totals?.gross_paid ?? run.totals?.monthly_gross ?? 0 },
          { label: "PF (EE)", value: run.totals?.pf_employee ?? 0 },
          { label: "PF (ER)", value: run.totals?.pf_employer_total ?? 0 },
          { label: "ESIC (EE)", value: run.totals?.esic_employee ?? 0 },
          { label: "ESIC (ER)", value: run.totals?.esic_employer ?? 0 },
          { label: "PT", value: run.totals?.pt ?? 0 },
          { label: "TDS", value: run.totals?.tds ?? 0 },
          { label: "Advance", value: run.totals?.advance_recovery ?? 0 },
          { label: "Deductions", value: run.totals?.total_deduction ?? 0 },
          { label: "Net Salary", value: run.totals?.net ?? 0, tone: "#059669" },
        ]} />
      ) : null}

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
function PresentDaysCell({
  idx, value, pdRefs, onCommit,
}: {
  idx: number;
  value: number;
  pdRefs: React.MutableRefObject<(TextInput | null)[]>;
  onCommit: (n: number) => void;
}) {
  const [txt, setTxt] = useState<string>(String(value ?? 0));
  const focusedRef = useRef(false);

  useEffect(() => {
    if (focusedRef.current) return;
    setTxt(String(value ?? 0));
  }, [value]);

  const commit = () => {
    const n = Number(txt.replace(/[^0-9.]/g, ""));
    // Iter 93 — present days only in half-day steps: .0 or .5
    if (!Number.isNaN(n)) onCommit(Math.round(n * 2) / 2);
    else setTxt(String(value ?? 0));
  };

  return (
    <TextInput
      ref={(el) => { pdRefs.current[idx] = el; }}
      value={txt}
      onChangeText={(v) => setTxt(v.replace(/[^0-9.]/g, ""))}
      onFocus={() => { focusedRef.current = true; }}
      onBlur={() => { focusedRef.current = false; commit(); }}
      onKeyPress={(e: any) => {
        const key = e?.nativeEvent?.key;
        if (key === "ArrowUp" || key === "ArrowDown") {
          e.preventDefault?.();
          commit();
          const next = idx + (key === "ArrowDown" ? 1 : -1);
          const target = pdRefs.current[next];
          if (target && typeof (target as any).focus === "function") {
            (target as any).focus();
          }
        } else if (key === "Enter") {
          e.preventDefault?.();
          if (typeof (e?.target as any)?.blur === "function") {
            (e.target as any).blur();
          }
        }
      }}
      keyboardType="decimal-pad"
      selectTextOnFocus
      style={[
        styles.tblCell,
        styles.rightCell,
        styles.editableCell,
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
  icon, label, onPress, busy, primary,
}: {
  icon: any; label: string; onPress: () => void; busy?: boolean; primary?: boolean;
}) {
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
  groupHdrTxt: { fontSize: 10, fontWeight: "800", color: "#0f172a", letterSpacing: 0.3 },
  // Faint horizontal-strip tints applied to the column-header cells
  // themselves. Kept lighter than the group-band above so the primary
  // header colour still reads.
  groupHdrCellHeaderMaster: { backgroundColor: "rgba(16,185,129,0.25)" },
  groupHdrCellHeaderCalc:   { backgroundColor: "rgba(59,130,246,0.25)" },
  groupHdrCellHeaderDed:    { backgroundColor: "rgba(239,68,68,0.20)" },
  tblCell: {
    fontSize: 11,
    paddingVertical: 6,
    paddingHorizontal: 6,
    width: 72,
    color: colors.onSurface,
  },
  rightCell: { textAlign: "right", width: 72 },
  // Iter 85 — Inline-editable Present Days cell in Compliance Salary grid.
  editableCell: {
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderRadius: 6,
    paddingHorizontal: 4,
    paddingVertical: 2,
    backgroundColor: colors.brandTertiary,
    color: colors.onSurface,
    fontWeight: "700",
    width: 72,
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
