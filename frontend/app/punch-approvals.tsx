import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  Alert,
  Platform,
  TextInput,
  Modal,
  Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useOnRefresh } from "@/src/context/RefreshBusContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import DateField from "@/src/components/DateField";

type EmployeeMini = {
  user_id?: string;
  name?: string;
  father_name?: string;
  employee_code?: string;
  designation?: string;
  profile_photo_base64?: string | null;
};

type Punch = {
  record_id: string;
  user_id: string;
  company_id: string;
  branch_name?: string | null;
  date: string;
  kind: "in" | "out";
  at: string;
  original_at?: string;
  adjusted_at?: string | null;
  distance_m?: number;
  source?: string;
  outside_geofence?: boolean;
  location_status?: "inside" | "outside" | "no-gps" | string;
  outside_note?: string | null;
  status?: "pending" | "approved" | "rejected";
  decision_reason?: string | null;
  decision_at?: string | null;
  identity_flagged?: boolean;
  employee?: EmployeeMini;
};

type ListResp = { records: Punch[]; pending_count: number };
// Iter 85 — Six-tab layout organised in two rows:
//   Row 1 (STATUS):  pending | approved | rejected
//   Row 2 (SOURCE):  updated | auto     | manual
type Tab =
  | "pending" | "approved" | "rejected"
  | "updated" | "auto" | "manual" | "extra";

// Iter 94 — Day-status row from /admin/attendance/day-status. Powers the
// three source tabs: Updated (edited punches only), Auto (both punches
// present, editable), Manual (missing punches, fill manually).
type DayCell = {
  record_id: string;
  at: string;
  hhmm: string;
  date?: string; // actual calendar date of the punch (night-shift OUT = next day)
  edited: boolean;
  source?: string | null;
  status?: string | null;
  // Iter 111 — audit detail for the Updated tab.
  edit_reason?: string | null;
  edited_by_name?: string | null;
  original_hhmm?: string | null;
} | null;
type DayRow = {
  key: string;
  user_id: string;
  date: string;
  name?: string | null;
  father_name?: string | null;
  designation?: string | null;
  employee_code?: string | null;
  in: DayCell;
  out: DayCell;
  updated: boolean;
  // Iter 95g — employee's shift times (Shift Master) for "Fill from shift".
  shift_start?: string | null;
  shift_end?: string | null;
};

// Iter 95g — firm's Shift Master definitions (fallback matching when the
// employee has no assigned shift: pick the shift closest to the existing
// punch of the day).
type ShiftDef = { shift_id: string; start: string; end: string };

// Iter 111 — system default reasons for punch updation (user-specified).
// Shown as a per-row picker in front of every employee; "Custom…" lets
// the admin type a free-text reason.
const REASON_PRESETS = [
  "Due to Mismatch",
  "Not Registered In Machine",
  "Android Not Available",
] as const;

const _toMin = (s?: string | null): number | null => {
  const m = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec((s || "").trim());
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
};
const _circDist = (a: number, b: number): number => {
  const d = Math.abs(a - b);
  return Math.min(d, 1440 - d);
};

/** Resolve the time to one-tap-fill for a missing punch. Uses the
 * employee's assigned shift first; otherwise finds the Shift Master shift
 * whose OTHER side sits closest to the punch that DOES exist that day. */
function fillTimeFor(r: DayRow, k: "in" | "out", shifts: ShiftDef[]): string | null {
  const assigned = k === "in" ? r.shift_start : r.shift_end;
  if (assigned) return assigned;
  if (!shifts.length) return null;
  const anchor = _toMin(k === "in" ? r.out?.hhmm : r.in?.hhmm);
  if (anchor == null) return null; // both missing & no assigned shift
  let best: ShiftDef | null = null;
  let bestD = Infinity;
  for (const s of shifts) {
    const side = _toMin(k === "in" ? s.end : s.start);
    if (side == null) continue;
    const d = _circDist(anchor, side);
    if (d < bestD) { bestD = d; best = s; }
  }
  return best ? (k === "in" ? best.start : best.end) : null;
}

// Iter 94 — Additional Duty grant (extra HRS merge into attendance duty;
// extra ₹ amounts land in Oth.Allo during Actual Salary Process).
type ExtraDutyEntry = {
  user_id: string;
  date: string;
  extra_hours?: number;
  extra_amount?: number;
};

export default function PunchApprovalsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const canAct = user?.role === "super_admin" || user?.role === "company_admin";
  // Iter 68 — Follow the global firm selection for Sub-Admin impersonation.
  const { selectedCompanyId } = useSelectedCompany();

  const [tab, setTab] = useState<Tab>("pending");
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [records, setRecords] = useState<Punch[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  // Iter 85 — Explicit "Show" + "Save" model.
  // The list no longer auto-loads on every tab/date change; the admin
  // taps "Show" to fetch, batch-edits the visible rows, then taps "Save"
  // to commit every pending decision in one shot.
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [batchDecisions, setBatchDecisions] = useState<Record<string, "approve" | "reject">>({});
  const [savingBatch, setSavingBatch] = useState(false);

  // Iter 83 — Date filter + Updated-Punches rows for the selected day.
  // Iter 91 — "Periodic" mode: pick From + To dates to review a range.
  const [selectedDate, setSelectedDate] = useState<string>(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [dateMode, setDateMode] = useState<"single" | "period">("single");
  const [toDate, setToDate] = useState<string>(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [dayRows, setDayRows] = useState<DayRow[]>([]);
  const [shiftDefs, setShiftDefs] = useState<ShiftDef[]>([]);
  // Iter 96v — punch photo (selfie) viewer.
  const [photo, setPhoto] = useState<{ loading: boolean; b64: string | null; open: boolean }>(
    { loading: false, b64: null, open: false },
  );
  const openPunchPhoto = useCallback(async (recordId: string) => {
    setPhoto({ loading: true, b64: null, open: true });
    try {
      const r = await api<{ selfie_base64: string | null }>(`/admin/attendance/${recordId}/selfie`);
      setPhoto({ loading: false, b64: r.selfie_base64 || null, open: true });
    } catch {
      setPhoto({ loading: false, b64: null, open: true });
    }
  }, []);
  // Per-row time edits keyed by row.key → {in?: "HH:MM", out?: "HH:MM"}
  const [edits, setEdits] = useState<Record<string, { in?: string; out?: string }>>({});
  const [savingRow, setSavingRow] = useState<string | null>(null);
  // Iter 111 — per-row updation reason (defaults to the first preset).
  const [reasonSel, setReasonSel] = useState<Record<string, string>>({});
  const [reasonPickFor, setReasonPickFor] = useState<string | null>(null);
  // Iter 113 — Individual Punch modal (manual punch for ANY employee).
  const [indOpen, setIndOpen] = useState(false);
  const [indEmps, setIndEmps] = useState<{ user_id: string; name: string; employee_code?: string }[]>([]);
  const [indEmp, setIndEmp] = useState<{ user_id: string; name: string; employee_code?: string } | null>(null);
  const [indSearch, setIndSearch] = useState("");
  const [indDate, setIndDate] = useState("");
  const [indIn, setIndIn] = useState("");
  const [indOut, setIndOut] = useState("");
  const [indReason, setIndReason] = useState<string>(REASON_PRESETS[0]);
  const [indSaving, setIndSaving] = useState(false);
  // Iter 113 — Today's Manual Punches quick log (review / undo).
  const [mlogOpen, setMlogOpen] = useState(false);
  const [mlog, setMlog] = useState<any[]>([]);
  const [mlogLoading, setMlogLoading] = useState(false);
  // Iter 94 — Additional Duty (extra HRS / ₹ amount) per user|date.
  const [extraMap, setExtraMap] = useState<Record<string, ExtraDutyEntry>>({});
  const [extraEdits, setExtraEdits] =
    useState<Record<string, { hours?: string; amount?: string; unit?: "hrs" | "min"; sign?: "+" | "-" }>>({});

  const load = useCallback(
    async (showSpinner = true) => {
      if (!canAct) return;
      if (showSpinner) setLoading(true);
      setError(null);
      try {
        // Iter 94 — the three SOURCE tabs all load per-employee day-status
        // rows (works for Single day AND Periodic ranges):
        //   Updated → punches edited from App / Web Portal only
        //   Auto    → employees with BOTH In & Out punches (editable)
        //   Manual  → employees with MISSING In / Out / Both (fill manually)
        if (tab === "updated" || tab === "auto" || tab === "manual" || tab === "extra") {
          if (!selectedCompanyId) {
            setDayRows([]);
            setError("Pick a firm first (top-right selector).");
            return;
          }
          const effTo = dateMode === "period" && toDate >= selectedDate ? toDate : selectedDate;
          const r = await api<{ rows: DayRow[]; shifts?: ShiftDef[] }>(
            `/admin/attendance/day-status/${selectedCompanyId}?from_date=${selectedDate}&to_date=${effTo}`,
          );
          setDayRows(r.rows || []);
          setShiftDefs(r.shifts || []);
          setEdits({});
          // Iter 94 — Additional Duty entries for the same window.
          if (tab === "extra") {
            const x = await api<{ entries: ExtraDutyEntry[] }>(
              `/admin/attendance/extra-duty/${selectedCompanyId}?from_date=${selectedDate}&to_date=${effTo}`,
            );
            const map: Record<string, ExtraDutyEntry> = {};
            (x.entries || []).forEach((en) => { map[`${en.user_id}|${en.date}`] = en; });
            setExtraMap(map);
            setExtraEdits({});
          }
          return;
        }
        // Pending / Rejected use the existing pending-punches API and
        // filter client-side by ``selectedDate`` + status.
        const params = new URLSearchParams();
        params.set("include_decided", "true");
        if (selectedCompanyId) params.set("company_id", selectedCompanyId);
        const qs = `?${params.toString()}`;
        const r = await api<ListResp>(`/attendance/pending-punches${qs}`);
        setRecords(r.records || []);
        setPendingCount(r.pending_count || 0);
      } catch (e: any) {
        setError(e?.message || "Failed to load approvals");
      } finally {
        setLoading(false);
        setRefreshing(false);
        setHasLoadedOnce(true);
      }
    },
    [canAct, tab, selectedCompanyId, selectedDate, dateMode, toDate],
  );

  useEffect(() => {
    // Iter 85 — DO NOT auto-fetch on tab/date change. Admin must tap
    // "Show" to load. This lets them tweak filters without spamming the
    // API and matches the requested Show → edit → Save flow.
  }, [tab, selectedDate, selectedCompanyId]);
  useOnRefresh(() => { if (hasLoadedOnce) load(true); });

  const visibleRecords = useMemo(() => {
    // Filter by tab AND by selected date (single day) or period (From–To).
    const effTo = dateMode === "period" && toDate >= selectedDate ? toDate : selectedDate;
    const byDate = (r: Punch) => {
      const d = (r.at || "").slice(0, 10);
      return dateMode === "period"
        ? d >= selectedDate && d <= effTo
        : d === selectedDate;
    };
    if (tab === "pending") {
      return records.filter((r) => (r.status || "") === "pending").filter(byDate);
    }
    if (tab === "approved") {
      // Iter 85 — Approved list. Backend marks a punch approved when an
      // admin accepts a pending auto-punch or edits a manual entry.
      return records.filter((r) => (r.status || "") === "approved").filter(byDate);
    }
    if (tab === "rejected") {
      return records.filter((r) => (r.status || "") === "rejected").filter(byDate);
    }
    if (tab === "auto") {
      // Auto-generated punches from the geofence / auto-punch worker.
      return records.filter((r) => {
        const src = String((r as any).source || "").toLowerCase();
        return src === "auto" || src.includes("auto");
      }).filter(byDate);
    }
    if (tab === "manual") {
      // Manual entries created by an admin on /manual-punch-entry.
      return records.filter((r) => {
        const src = String((r as any).source || "").toLowerCase();
        return src === "manual" || src.includes("manual");
      }).filter(byDate);
    }
    return [];
  }, [records, tab, selectedDate, dateMode, toDate]);

  // Iter 93 — Day-summary rows for EVERY punch-level tab (Pending /
  // Approved / Rejected / Auto / Manual). Punches are grouped per
  // employee + day and paired: first IN→OUT pair = regular duty, any
  // later pairs = OT. Same column layout as the Updated tab.
  const groupedRows = useMemo(() => {
    const byKey = new Map<string, Punch[]>();
    for (const p of visibleRecords) {
      const d = (p.at || "").slice(0, 10);
      const k = `${p.user_id}|${d}`;
      const arr = byKey.get(k);
      if (arr) arr.push(p); else byKey.set(k, [p]);
    }
    const hrs = (a?: string | null, b?: string | null) => {
      if (!a || !b) return 0;
      const ms = new Date(b).getTime() - new Date(a).getTime();
      return ms > 0 ? ms / 3600000 : 0;
    };
    const rows = [] as {
      key: string; date: string;
      name?: string | null; father_name?: string | null; designation?: string | null;
      in: string | null; out: string | null; ot_in: string | null; ot_out: string | null;
      duty_hours: number; ot_hours: number; total_hours: number;
      recordIds: string[];
    }[];
    for (const [k, ps] of byKey) {
      ps.sort((a, b) => ((a.at || "") < (b.at || "") ? -1 : 1));
      const pairs: [Punch, Punch][] = [];
      let openIn: Punch | null = null;
      for (const p of ps) {
        if (p.kind === "in") { if (!openIn) openIn = p; }
        else if (p.kind === "out" && openIn) { pairs.push([openIn, p]); openIn = null; }
      }
      const firstIn = pairs[0]?.[0]?.at || ps.find((p) => p.kind === "in")?.at || null;
      const firstOut = pairs[0]?.[1]?.at || ps.filter((p) => p.kind === "out").pop()?.at || null;
      const otIn = pairs.length >= 2 ? pairs[1][0].at : null;
      const otOut = pairs.length >= 2 ? pairs[pairs.length - 1][1].at : null;
      const duty = pairs.length >= 1 ? hrs(pairs[0][0].at, pairs[0][1].at) : 0;
      let ot = 0;
      for (let i = 1; i < pairs.length; i++) ot += hrs(pairs[i][0].at, pairs[i][1].at);
      const emp = ps[0].employee || {};
      rows.push({
        key: k,
        date: (ps[0].at || "").slice(0, 10),
        name: emp.name,
        father_name: emp.father_name,
        designation: emp.designation,
        in: firstIn, out: firstOut, ot_in: otIn, ot_out: otOut,
        duty_hours: duty, ot_hours: ot, total_hours: duty + ot,
        recordIds: ps.map((p) => p.record_id),
      });
    }
    rows.sort((a, b) =>
      a.date === b.date
        ? (a.name || "").localeCompare(b.name || "")
        : a.date < b.date ? -1 : 1,
    );
    return rows;
  }, [visibleRecords]);

  // Iter 94 — filter the day-status rows per source tab.
  const dayVisible = useMemo(() => {
    if (tab === "updated") return dayRows.filter((r) => r.updated);
    if (tab === "auto") return dayRows.filter((r) => !!r.in && !!r.out);
    if (tab === "manual") return dayRows.filter((r) => !r.in || !r.out);
    // Additional Duty: ONLY employees whose BOTH punches are complete.
    if (tab === "extra") return dayRows.filter((r) => !!r.in && !!r.out);
    return [];
  }, [dayRows, tab]);

  // Save one Additional Duty row (extra HRS and/or ₹ amount).
  // Iter 111 — value can be entered in HRS or MIN, and can be NEGATIVE
  // ("Less" sign) to reduce that day's duty hours.
  const saveExtraRow = async (r: DayRow) => {
    const cur = extraMap[r.key];
    const e = extraEdits[r.key] || {};
    const curH = Number(cur?.extra_hours || 0);
    const hours = e.hours !== undefined ? e.hours : curH ? String(Math.abs(curH)) : "";
    const amount = e.amount !== undefined ? e.amount : String(cur?.extra_amount || "");
    const unit = e.unit || "hrs";
    const sign = e.sign || (curH < 0 ? "-" : "+");
    const rawVal = hours.trim() === "" ? 0 : Number(hours);
    const a = amount.trim() === "" ? 0 : Number(amount);
    if (Number.isNaN(rawVal) || Number.isNaN(a) || rawVal < 0 || a < 0) {
      showAlert("Invalid value", "Enter a positive number — use the +/− toggle to add or reduce duty.");
      return;
    }
    let h = unit === "min" ? rawVal / 60 : rawVal;
    if (sign === "-") h = -h;
    h = Math.round(h * 100) / 100;
    setSavingRow(r.key);
    try {
      await api(`/admin/attendance/extra-duty`, {
        method: "POST",
        body: { user_id: r.user_id, date: r.date, extra_hours: h, extra_amount: a },
      });
      setExtraMap((prev) => ({
        ...prev,
        [r.key]: { user_id: r.user_id, date: r.date, extra_hours: h, extra_amount: a },
      }));
      setExtraEdits((prev) => { const n = { ...prev }; delete n[r.key]; return n; });
      showAlert(
        "Additional Duty saved",
        h !== 0 || a > 0
          ? `${h !== 0 ? `${Math.abs(h)} HRS ${h > 0 ? "added to" : "reduced from"} duty` : ""}${h !== 0 && a > 0 ? " and " : ""}${a > 0 ? `₹${a} will be paid via Oth.Allo in Actual Salary Process` : ""}.`
          : "Entry cleared.",
      );
    } catch (err: any) {
      showAlert("Save failed", err?.message || "Try again");
    } finally {
      setSavingRow(null);
    }
  };

  // Iter 94 — auto-format punch time input as HH:MM while typing
  // ("930" → "09:3", "0930" → "09:30"; colon inserted automatically).
  // Overflow keeps the MOST RECENT digits so typing over a prefilled
  // value never swallows keystrokes; minutes clamp to 59.
  const formatHHMM = (raw: string): string => {
    let d = raw.replace(/[^0-9]/g, "");
    if (d.length > 4) d = d.slice(-4);
    if (d.length >= 1 && Number(d[0]) > 2) d = `0${d}`.slice(0, 4);
    if (d.length >= 2 && Number(d.slice(0, 2)) > 23) d = `23${d.slice(2)}`;
    if (d.length === 3 && Number(d[2]) > 5) d = `${d.slice(0, 2)}0${d[2]}`;
    if (d.length >= 4 && Number(d.slice(2, 4)) > 59) d = `${d.slice(0, 2)}59`;
    return d.length > 2 ? `${d.slice(0, 2)}:${d.slice(2)}` : d;
  };

  const setEdit = (key: string, field: "in" | "out", v: string) => {
    setEdits((prev) => ({ ...prev, [key]: { ...prev[key], [field]: formatHHMM(v) } }));
  };

  // "2026-07-09" → "2026-07-10" (night-shift OUT lands on the next day).
  const nextDay = (d: string): string => {
    const dt = new Date(`${d}T12:00:00`);
    dt.setDate(dt.getDate() + 1);
    return dt.toISOString().slice(0, 10);
  };

  // Save one row: PATCH existing punches whose time changed; POST a
  // manual punch for missing cells the admin filled in.
  // Iter 113 — Manual Punches log: load + undo.
  const loadManualLog = async () => {
    if (!selectedCompanyId) return;
    setMlogLoading(true);
    try {
      const effTo = dateMode === "range" && toDate ? toDate : selectedDate;
      const r = await api<{ records: any[] }>(
        `/admin/attendance/manual-log/${selectedCompanyId}?from_date=${selectedDate}&to_date=${effTo}`,
      );
      setMlog(r.records || []);
    } catch { setMlog([]); }
    setMlogLoading(false);
  };

  const undoManualPunch = async (rec: any) => {
    const sure = Platform.OS === "web"
      ? window.confirm(`Undo ${rec.kind?.toUpperCase()} punch ${rec.hhmm} for ${rec.employee_name}?`)
      : true;
    if (!sure) return;
    try {
      await api(
        `/admin/attendance/${rec.record_id}?reason=${encodeURIComponent("Undo individual punch")}`,
        { method: "DELETE" },
      );
      setMlog((prev) => prev.filter((x) => x.record_id !== rec.record_id));
      await load(false);
    } catch (e: any) {
      showAlert("Undo failed", e?.message || "Try again");
    }
  };

  // Iter 113 — open the Individual Punch modal (loads employee list once).
  const openIndividualPunch = async () => {
    setIndOpen(true);
    setIndEmp(null);
    setIndSearch("");
    setIndIn("");
    setIndOut("");
    setIndReason(REASON_PRESETS[0]);
    setIndDate(selectedDate);
    if (indEmps.length === 0) {
      try {
        const qs = selectedCompanyId ? `?company_id=${encodeURIComponent(selectedCompanyId)}` : "";
        const r = await api<{ employees: any[] }>(`/admin/employees${qs}`);
        setIndEmps(
          (r.employees || [])
            .filter((e) => !e.offboarded)
            .map((e) => ({ user_id: e.user_id, name: e.name || "", employee_code: e.employee_code }))
            .sort((a, b) => a.name.localeCompare(b.name)),
        );
      } catch { /* list stays empty; user can retry */ }
    }
  };

  // Iter 113 — save the Individual Punch (IN and/or OUT, night-shift aware).
  const saveIndividualPunch = async () => {
    const timeOk = (s: string) => /^([01]?\d|2[0-3]):([0-5]\d)$/.test(s.trim());
    if (!indEmp) { showAlert("Select employee", "Choose the employee to punch for."); return; }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(indDate)) { showAlert("Invalid date", "Date must be YYYY-MM-DD."); return; }
    const hasIn = indIn.trim() !== "";
    const hasOut = indOut.trim() !== "";
    if (!hasIn && !hasOut) { showAlert("Nothing to save", "Enter an IN and/or OUT time (HH:MM)."); return; }
    if ((hasIn && !timeOk(indIn)) || (hasOut && !timeOk(indOut))) {
      showAlert("Invalid time", "Times must be 24-hr HH:MM (e.g. 09:15).");
      return;
    }
    const toMin = (s: string) => {
      const mm = s.trim().match(/^([01]?\d|2[0-3]):([0-5]\d)$/);
      return mm ? Number(mm[1]) * 60 + Number(mm[2]) : null;
    };
    setIndSaving(true);
    let ok = 0, fail = 0; let failMsg = "";
    const jobs: { kind: "in" | "out"; date: string; hhmm: string }[] = [];
    if (hasIn) jobs.push({ kind: "in", date: indDate, hhmm: indIn.trim() });
    if (hasOut) {
      const inMin = toMin(indIn); const outMin = toMin(indOut);
      const outDate = hasIn && inMin != null && outMin != null && outMin <= inMin
        ? nextDay(indDate) // night shift — OUT belongs to the next morning
        : indDate;
      jobs.push({ kind: "out", date: outDate, hhmm: indOut.trim() });
    }
    for (const j of jobs) {
      try {
        await api(`/admin/attendance/manual-punch`, {
          method: "POST",
          body: {
            user_id: indEmp.user_id,
            kind: j.kind,
            at: `${j.date}T${j.hhmm.padStart(5, "0")}:00`,
            reason: indReason,
          },
        });
        ok += 1;
      } catch (err: any) { fail += 1; failMsg = err?.message || ""; }
    }
    setIndSaving(false);
    if (ok > 0) {
      setIndOpen(false);
      await load(false);
    }
    showAlert(
      fail > 0 ? (ok > 0 ? "Punch saved (partial)" : "Punch failed") : "Punch saved ✓",
      `Employee: ${indEmp.name}${indEmp.employee_code ? ` (Code ${indEmp.employee_code})` : ""}\n` +
      jobs.map((j) => `• ${j.kind.toUpperCase()} ${fmtDate(j.date)} ${j.hhmm}`).join("\n") +
      `\nReason: ${indReason}` +
      (fail > 0 ? `\n\n${fail} failed${failMsg ? ` — ${failMsg}` : ""}` : ""),
    );
  };

  const saveRow = async (r: DayRow) => {
    const e = edits[r.key] || {};
    const jobs: { kind: "in" | "out"; mode: "edit" | "create"; recordId?: string; hhmm: string }[] = [];
    (["in", "out"] as const).forEach((k) => {
      const v = (e[k] || "").trim();
      if (!v) return;
      if (!/^([01]?\d|2[0-3]):[0-5]\d$/.test(v)) {
        showAlert("Invalid time", `${k.toUpperCase()} time must be HH:MM (24-hour). Got "${v}".`);
        return;
      }
      const cell = r[k];
      if (cell && v !== cell.hhmm) {
        jobs.push({ kind: k, mode: "edit", recordId: cell.record_id, hhmm: v });
      } else if (!cell) {
        jobs.push({ kind: k, mode: "create", hhmm: v });
      }
    });
    if (jobs.length === 0) {
      showAlert("Nothing to save", "Change a time or fill a missing punch first.");
      return;
    }
    // Iter 111 — reason comes from the per-row picker (system presets +
    // custom). Defaults to the first preset when untouched.
    const reason = (reasonSel[r.key] || REASON_PRESETS[0]).trim();
    if (!reason) return;
    setSavingRow(r.key);
    let ok = 0, fail = 0; let failMsg = "";
    const toMin = (s: string) => {
      const mm = s.match(/^([01]?\d|2[0-3]):([0-5]\d)$/);
      return mm ? Number(mm[1]) * 60 + Number(mm[2]) : null;
    };
    for (const j of jobs) {
      // Night-shift aware target date:
      //  • edits keep the punch's OWN calendar date;
      //  • a filled-in OUT that is earlier than the IN time belongs to
      //    the NEXT day (e.g. IN 20:00 → OUT 08:00 next morning).
      let target = r.date;
      if (j.mode === "edit") {
        target = (j.kind === "in" ? r.in?.date : r.out?.date) || r.date;
      } else if (j.kind === "out") {
        const inBase = r.in?.date || r.date;
        const inMin = toMin((e.in || r.in?.hhmm || "").trim());
        const outMin = toMin(j.hhmm);
        target = inMin != null && outMin != null && outMin <= inMin
          ? nextDay(inBase)
          : inBase;
      }
      // Wall-clock time (system convention: stored as wall-clock labelled
      // UTC, same as .dat imports — send naive, no timezone offset).
      const atIso = `${target}T${j.hhmm.padStart(5, "0")}:00`;
      try {
        if (j.mode === "edit") {
          await api(`/admin/attendance/${j.recordId}`, {
            method: "PATCH",
            body: { at: atIso, reason: reason.trim() },
          });
        } else {
          await api(`/admin/attendance/manual-punch`, {
            method: "POST",
            body: { user_id: r.user_id, kind: j.kind, at: atIso, reason: reason.trim() },
          });
        }
        ok += 1;
      } catch (err: any) {
        fail += 1; failMsg = err?.message || "";
      }
    }
    setSavingRow(null);
    await load(false);
    // Iter 111 — post-update confirmation shows WHO was updated, WHICH
    // punch changed (old → new) and the reason, for full transparency.
    const detailLines = jobs.map((j) => {
      const oldT = j.kind === "in" ? r.in?.hhmm : r.out?.hhmm;
      return j.mode === "edit"
        ? `• ${j.kind.toUpperCase()} punch edited: ${oldT || "—"} → ${j.hhmm}`
        : `• ${j.kind.toUpperCase()} punch added: ${j.hhmm} (was missing)`;
    }).join("\n");
    showAlert(
      fail > 0 ? "Punch save (partial)" : "Punch updated ✓",
      `Employee: ${r.name || "—"}${r.employee_code ? ` (Code ${r.employee_code})` : ""}\n` +
      `Date: ${fmtDate(r.date)}\n${detailLines}\nReason: ${reason}` +
      (fail > 0 ? `\n\n${fail} failed${failMsg ? ` — ${failMsg}` : ""}` : "") +
      (ok > 0
        ? "\n\nSaved punches are linked directly to Employee Attendance In/Out."
        : ""),
    );
  };

  // Iter 85 — Queue a decision on the currently visible list without
  // committing it. The admin taps "Save" to POST every queued decision
  // in one shot.
  const queueDecision = (recordId: string, action: "approve" | "reject") => {
    setBatchDecisions((prev) => {
      const next = { ...prev };
      if (next[recordId] === action) {
        // second tap on same action = un-queue
        delete next[recordId];
      } else {
        next[recordId] = action;
      }
      return next;
    });
  };

  const saveBatch = async () => {
    const entries = Object.entries(batchDecisions);
    if (entries.length === 0) return;
    setSavingBatch(true);
    let ok = 0, fail = 0;
    for (const [recordId, action] of entries) {
      try {
        await api(`/attendance/punches/${recordId}/decision`, {
          method: "POST",
          body: action === "approve"
            ? { action: "approve" }
            : { action: "reject", reason: "Batch reject" },
        });
        ok += 1;
      } catch {
        fail += 1;
      }
    }
    setBatchDecisions({});
    setSavingBatch(false);
    await load(false);
    showAlert(
      "Batch save complete",
      `${ok} punch${ok === 1 ? "" : "es"} saved` + (fail > 0 ? `, ${fail} failed` : ""),
    );
  };


  if (!canAct) {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
          <Header title="Punch approvals" onBack={() => router.back()} />
        </SafeAreaView>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.dimTitle}>Admins only</Text>
          <Text style={styles.dimBody}>
            Only company admins and super admins can review punches.
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root} testID="punch-approvals-screen">
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <Header
          title="Punch approvals"
          onBack={() => router.back()}
          subtitle={
            pendingCount > 0
              ? `${pendingCount} auto-punch${pendingCount === 1 ? "" : "es"} awaiting review`
              : "All auto punches are up to date"
          }
        />
        {/* Iter 113 — manual punch for ANY individual employee. */}
        {canAct ? (
          <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 8, marginBottom: 8 }}>
            <Pressable
              onPress={() => {
                const next = !mlogOpen;
                setMlogOpen(next);
                if (next) loadManualLog();
              }}
              style={[upStyles.indBtn, { backgroundColor: "#B45309" }]}
              testID="pa-manual-log"
            >
              <Ionicons name="list-outline" size={15} color="#fff" />
              <Text style={upStyles.indBtnTxt}>Manual Punches Log</Text>
            </Pressable>
            <Pressable onPress={openIndividualPunch} style={upStyles.indBtn} testID="pa-individual-punch">
              <Ionicons name="finger-print-outline" size={15} color="#fff" />
              <Text style={upStyles.indBtnTxt}>+ Individual Punch</Text>
            </Pressable>
          </View>
        ) : null}
        {/* Iter 113 — Manual Punches quick log (review / undo). */}
        {canAct && mlogOpen ? (
          <View style={upStyles.mlogBox}>
            <Text style={upStyles.mlogTitle}>
              Manual / Individual punches — {fmtDate(selectedDate)}
              {dateMode === "range" && toDate ? ` → ${fmtDate(toDate)}` : ""}
              {mlogLoading ? "  (loading…)" : `  (${mlog.length})`}
            </Text>
            {!mlogLoading && mlog.length === 0 ? (
              <Text style={upStyles.mlogEmpty}>No manual punches for this date.</Text>
            ) : null}
            {mlog.map((m) => (
              <View key={m.record_id} style={upStyles.mlogRow}>
                <Text style={[upStyles.mlogCell, { width: 80 }]}>{fmtDate(m.date)}</Text>
                <Text style={[upStyles.mlogCell, { width: 44, fontWeight: "800" }]}>{(m.kind || "").toUpperCase()}</Text>
                <Text style={[upStyles.mlogCell, { width: 48 }]}>{m.hhmm}</Text>
                <Text style={[upStyles.mlogCell, { flex: 1, fontWeight: "600" }]} numberOfLines={1}>
                  {m.employee_name}{m.employee_code ? ` (${m.employee_code})` : ""}
                </Text>
                <Text style={[upStyles.mlogCell, { flex: 1 }]} numberOfLines={1}>
                  {m.manual_reason || "—"}{m.created_by_name ? ` · by ${m.created_by_name}` : ""}
                </Text>
                <Pressable
                  onPress={() => undoManualPunch(m)}
                  style={upStyles.mlogUndo}
                  testID={`mlog-undo-${m.record_id}`}
                >
                  <Ionicons name="trash-outline" size={12} color="#B91C1C" />
                  <Text style={upStyles.mlogUndoTxt}>Undo</Text>
                </Pressable>
              </View>
            ))}
          </View>
        ) : null}
        {/* Iter 85 — Two-row tab layout.
            Row 1 = STATUS filter (Pending / Approved / Rejected)
            Row 2 = SOURCE filter (Updated / Auto-Punches / Manual)
        */}
        <View style={styles.tabsGroup}>
          <Text style={styles.tabsGroupLbl}>By Status</Text>
          <View style={styles.tabs}>
            <TabPill
              label="Pending"
              count={pendingCount}
              active={tab === "pending"}
              onPress={() => setTab("pending")}
              testID="tab-pending"
            />
            <TabPill
              label="Approved"
              active={tab === "approved"}
              onPress={() => setTab("approved")}
              testID="tab-approved"
            />
            <TabPill
              label="Rejected"
              active={tab === "rejected"}
              onPress={() => setTab("rejected")}
              testID="tab-rejected"
            />
          </View>
        </View>
        <View style={styles.tabsGroup}>
          <Text style={styles.tabsGroupLbl}>By Source</Text>
          <View style={styles.tabs}>
            <TabPill
              label="Updated"
              active={tab === "updated"}
              onPress={() => setTab("updated")}
              testID="tab-updated"
            />
            <TabPill
              label="Auto-Punches"
              active={tab === "auto"}
              onPress={() => setTab("auto")}
              testID="tab-auto"
            />
            <TabPill
              label="Manual Entries"
              active={tab === "manual"}
              onPress={() => setTab("manual")}
              testID="tab-manual"
            />
            <TabPill
              label="Additional Duty"
              active={tab === "extra"}
              onPress={() => setTab("extra")}
              testID="tab-extra"
            />
          </View>
        </View>
        {/* Iter 83 — Date filter (applies to every tab).
            Iter 91 — Single-day or Periodic (From–To) filtering. */}
        <View style={styles.dateBar}>
          <View style={{ flexDirection: "row", gap: 4 }}>
            {(["single", "period"] as const).map((m) => (
              <Pressable
                key={m}
                onPress={() => setDateMode(m)}
                style={[styles.dateModeChip, dateMode === m && styles.dateModeChipOn]}
                testID={`pa-datemode-${m}`}
              >
                <Text style={[styles.dateModeTxt, dateMode === m && styles.dateModeTxtOn]}>
                  {m === "single" ? "Single day" : "Periodic"}
                </Text>
              </Pressable>
            ))}
          </View>
          <DateField
            value={selectedDate}
            onChangeISO={setSelectedDate}
            label={dateMode === "period" ? "From" : "Date"}
            testID="pa-date-input"
            compact
          />
          {dateMode === "period" ? (
            <DateField
              value={toDate}
              onChangeISO={setToDate}
              label="To"
              min={selectedDate}
              testID="pa-date-to-input"
              compact
            />
          ) : null}
          <Pressable
            onPress={() => setSelectedDate(new Date().toISOString().slice(0, 10))}
            style={styles.dateTodayBtn}
          >
            <Text style={styles.dateTodayTxt}>Today</Text>
          </Pressable>
          {/* Iter 85 — "Show" and "Save" action buttons.
              • Show — explicit trigger to fetch the punch list with the
                currently-selected filters.
              • Save — commits every queued approve/reject decision in
                one round trip. */}
          <Pressable
            onPress={() => load(true)}
            disabled={loading}
            style={[styles.showBtn, loading && { opacity: 0.6 }]}
            testID="pa-show"
          >
            {loading ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <>
                <Ionicons name="eye-outline" size={14} color="#fff" />
                <Text style={styles.showBtnTxt}>Show</Text>
              </>
            )}
          </Pressable>
          <Pressable
            onPress={saveBatch}
            disabled={savingBatch || Object.keys(batchDecisions).length === 0}
            style={[
              styles.saveBtn,
              (savingBatch || Object.keys(batchDecisions).length === 0) && { opacity: 0.5 },
            ]}
            testID="pa-save"
          >
            {savingBatch ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <>
                <Ionicons name="save-outline" size={14} color="#fff" />
                <Text style={styles.saveBtnTxt}>
                  Save {Object.keys(batchDecisions).length > 0 ? `(${Object.keys(batchDecisions).length})` : ""}
                </Text>
              </>
            )}
          </Pressable>
        </View>
      </SafeAreaView>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Ionicons name="alert-circle" size={26} color={colors.error} />
          <Text style={styles.errTxt}>{error}</Text>
          <Pressable onPress={() => load(true)} style={styles.retry}>
            <Text style={styles.retryTxt}>Retry</Text>
          </Pressable>
        </View>
      ) : tab === "extra" ? (
        <ScrollView
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); load(false); }}
              tintColor={colors.brandPrimary}
            />
          }
        >
          <View style={upStyles.hintBox}>
            <Ionicons name="information-circle-outline" size={14} color={colors.brandPrimary} />
            <Text style={upStyles.hintTxt}>
              Additional Duty — only employees whose BOTH punches are complete.
              Add extra Duty (or press the +/− toggle to REDUCE duty) in HRS or
              MIN — merged into that day&apos;s attendance — and/or a ₹ Amount
              (paid via Oth.Allo in the Actual Salary Process).
            </Text>
          </View>
          <ScrollView horizontal showsHorizontalScrollIndicator={true}>
            <View>
              <View style={upStyles.hdrRow}>
                {[
                  { w: 82, txt: "Date" },
                  { w: 54, txt: "Code" },
                  { w: 150, txt: "Name" },
                  { w: 110, txt: "Designation" },
                  { w: 60, txt: "In" },
                  { w: 60, txt: "Out" },
                  { w: 66, txt: "Duty HRS" },
                  { w: 160, txt: "Extra Duty ± (HRS/MIN)" },
                  { w: 74, txt: "Total HRS" },
                  { w: 90, txt: "Amount ₹" },
                  ...(canAct ? [{ w: 70, txt: "Action" }] : []),
                ].map((c) => (
                  <Text key={c.txt} style={[upStyles.hdrCell, { width: c.w }]}>
                    {c.txt}
                  </Text>
                ))}
              </View>
              {dayVisible.length === 0 ? (
                <Text style={upStyles.emptyTxt}>
                  {hasLoadedOnce
                    ? `No employees with both punches complete for ${selectedDate}${dateMode === "period" ? ` – ${toDate}` : ""}.`
                    : "Pick a date and tap Show to load."}
                </Text>
              ) : (
                dayVisible.map((r, i) => {
                  const cur = extraMap[r.key];
                  const e = extraEdits[r.key] || {};
                  const curH = Number(cur?.extra_hours || 0);
                  const hoursVal = e.hours !== undefined
                    ? e.hours
                    : curH ? String(Math.abs(curH)) : "";
                  const amountVal = e.amount !== undefined
                    ? e.amount
                    : cur?.extra_amount ? String(cur.extra_amount) : "";
                  const unit = e.unit || "hrs";
                  const sign = e.sign || (curH < 0 ? "-" : "+");
                  const dirty = e.hours !== undefined || e.amount !== undefined ||
                    e.unit !== undefined || e.sign !== undefined;
                  // Base Duty HRS from the day's punches (wraps midnight
                  // for night shifts); Total = base + signed extra.
                  const baseDuty = (() => {
                    const m = (s?: string) => {
                      const mm = (s || "").match(/^([01]?\d|2[0-3]):([0-5]\d)$/);
                      return mm ? Number(mm[1]) * 60 + Number(mm[2]) : null;
                    };
                    const a = m(r.in?.hhmm); const b = m(r.out?.hhmm);
                    if (a == null || b == null) return 0;
                    let mins = b - a;
                    if (mins < 0) mins += 1440;
                    return mins / 60;
                  })();
                  const signedExtra = (() => {
                    const v = Number(hoursVal) || 0;
                    const hh = unit === "min" ? v / 60 : v;
                    return sign === "-" ? -hh : hh;
                  })();
                  const totalDuty = Math.max(0, baseDuty + signedExtra);
                  return (
                    <View key={r.key} style={[upStyles.row, i % 2 === 0 && upStyles.rowAlt]}>
                      <Text style={[upStyles.cell, { width: 82 }]}>{fmtDate(r.date)}</Text>
                      <Text style={[upStyles.cell, { width: 54 }]}>{r.employee_code || "—"}</Text>
                      <Text style={[upStyles.cell, { width: 150, fontWeight: "600" }]} numberOfLines={1}>
                        {r.name || "—"}
                      </Text>
                      <Text style={[upStyles.cell, { width: 110 }]} numberOfLines={1}>
                        {r.designation || "—"}
                      </Text>
                      <Text style={[upStyles.cell, { width: 60 }]}>{r.in?.hhmm || "—"}</Text>
                      <Text style={[upStyles.cell, { width: 60 }]}>{r.out?.hhmm || "—"}</Text>
                      <Text style={[upStyles.cell, upStyles.num, { width: 66 }]}>
                        {fmtHoursHM(baseDuty)}
                      </Text>
                      {/* Iter 111 — Add/Less toggle + value + HRS/MIN unit */}
                      <View style={{ width: 160, paddingHorizontal: 3, flexDirection: "row", alignItems: "center", gap: 3 }}>
                        <Pressable
                          onPress={() =>
                            setExtraEdits((prev) => ({
                              ...prev,
                              [r.key]: { ...prev[r.key], sign: sign === "+" ? "-" : "+" },
                            }))
                          }
                          style={[upStyles.signBtn, sign === "-" && upStyles.signBtnLess]}
                          testID={`xd-sign-${r.key}`}
                        >
                          <Text style={[upStyles.signBtnTxt, sign === "-" && { color: "#B91C1C" }]}>
                            {sign === "+" ? "+" : "−"}
                          </Text>
                        </Pressable>
                        <TextInput
                          value={hoursVal}
                          onChangeText={(v) =>
                            setExtraEdits((prev) => ({
                              ...prev,
                              [r.key]: { ...prev[r.key], hours: v.replace(/[^0-9.]/g, "") },
                            }))
                          }
                          placeholder="0"
                          placeholderTextColor={colors.onSurfaceTertiary}
                          keyboardType="numeric"
                          selectTextOnFocus
                          style={[upStyles.timeInput, { flex: 1 }]}
                          testID={`xd-hrs-${r.key}`}
                        />
                        <Pressable
                          onPress={() =>
                            setExtraEdits((prev) => ({
                              ...prev,
                              [r.key]: { ...prev[r.key], unit: unit === "hrs" ? "min" : "hrs" },
                            }))
                          }
                          style={upStyles.unitBtn}
                          testID={`xd-unit-${r.key}`}
                        >
                          <Text style={upStyles.unitBtnTxt}>{unit === "hrs" ? "HRS" : "MIN"}</Text>
                        </Pressable>
                      </View>
                      {/* Total = punches duty + extra (live preview) */}
                      <Text
                        style={[
                          upStyles.cell, upStyles.num,
                          { width: 74, fontWeight: "800" },
                          signedExtra > 0 && { color: "#15803D" },
                          signedExtra < 0 && { color: "#B91C1C" },
                        ]}
                      >
                        {fmtHoursHM(totalDuty)}
                      </Text>
                      <View style={{ width: 90, paddingHorizontal: 3 }}>
                        <TextInput
                          value={amountVal}
                          onChangeText={(v) =>
                            setExtraEdits((prev) => ({
                              ...prev,
                              [r.key]: { ...prev[r.key], amount: v.replace(/[^0-9.]/g, "") },
                            }))
                          }
                          placeholder="₹ 0"
                          placeholderTextColor={colors.onSurfaceTertiary}
                          keyboardType="numeric"
                          selectTextOnFocus
                          style={[upStyles.timeInput, (cur?.extra_amount || 0) > 0 && upStyles.timeInputEdited]}
                          testID={`xd-amt-${r.key}`}
                        />
                      </View>
                      {canAct ? (
                        <View style={{ width: 70, justifyContent: "center", alignItems: "center" }}>
                          <Pressable
                            onPress={() => saveExtraRow(r)}
                            disabled={savingRow === r.key || !dirty}
                            style={[upStyles.saveRowBtn, (!dirty || savingRow === r.key) && { opacity: 0.35 }]}
                            testID={`xd-save-${r.key}`}
                          >
                            {savingRow === r.key ? (
                              <ActivityIndicator size="small" color="#fff" />
                            ) : (
                              <Text style={upStyles.saveRowTxt}>Save</Text>
                            )}
                          </Pressable>
                        </View>
                      ) : null}
                    </View>
                  );
                })
              )}
            </View>
          </ScrollView>
          <View style={{ height: 40 }} />
        </ScrollView>
      ) : tab === "updated" || tab === "auto" || tab === "manual" ? (
        <ScrollView
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); load(false); }}
              tintColor={colors.brandPrimary}
            />
          }
        >
          {/* Iter 94 — contextual hint per source tab */}
          <View style={upStyles.hintBox}>
            <Ionicons name="information-circle-outline" size={14} color={colors.brandPrimary} />
            <Text style={upStyles.hintTxt}>
              {tab === "updated"
                ? "Employees whose punch was UPDATED from the App or Web Portal. Edits by Company / Super Admin apply DIRECTLY to Employee Attendance (audit-logged)."
                : tab === "auto"
                  ? "Employees whose BOTH punches (In & Out) are available. Change any time (HH:MM, 24-hr) and press Save — linked directly to Employee Attendance."
                  : "Employees with MISSING punches — In missing, Out missing, or Both. Fill the missing time (HH:MM, 24-hr) and press Save to record a manual punch — linked directly to Employee Attendance."}
            </Text>
          </View>
          <ScrollView horizontal showsHorizontalScrollIndicator={true}>
            <View>
              <View style={upStyles.hdrRow}>
                {[
                  { w: 82, txt: "Date" },
                  { w: 54, txt: "Code" },
                  { w: 150, txt: "Name" },
                  { w: 130, txt: "Father Name" },
                  { w: 110, txt: "Designation" },
                  { w: 86, txt: "In / Date" },
                  { w: 86, txt: "Out / Date" },
                  { w: 68, txt: "Duty HRS" },
                  { w: 90, txt: "Status" },
                  ...(tab === "updated" ? [{ w: 230, txt: "Update Details (Punch · Reason · By)" }] : []),
                  ...(canAct ? [{ w: 160, txt: "Update Reason" }, { w: 70, txt: "Action" }] : []),
                ].map((c) => (
                  <Text key={c.txt} style={[upStyles.hdrCell, { width: c.w }]}>
                    {c.txt}
                  </Text>
                ))}
              </View>
              {dayVisible.length === 0 ? (
                <Text style={upStyles.emptyTxt}>
                  {hasLoadedOnce
                    ? `No ${tab === "updated" ? "updated punches" : tab === "auto" ? "complete In+Out punches" : "missing-punch employees"} for ${selectedDate}${dateMode === "period" ? ` – ${toDate}` : ""}.`
                    : "Pick a date and tap Show to load."}
                </Text>
              ) : (
                dayVisible.map((r, i) => {
                  const e = edits[r.key] || {};
                  const inVal = e.in ?? (r.in?.hhmm || "");
                  const outVal = e.out ?? (r.out?.hhmm || "");
                  const dutyH = (() => {
                    const m = (s: string) => {
                      const mm = s.match(/^([01]?\d|2[0-3]):([0-5]\d)$/);
                      return mm ? Number(mm[1]) * 60 + Number(mm[2]) : null;
                    };
                    const a = m(inVal); const b = m(outVal);
                    if (a == null || b == null) return 0;
                    let mins = b - a;
                    // Night shift: OUT next morning (b < a) wraps midnight.
                    if (mins < 0) mins += 1440;
                    return mins / 60;
                  })();
                  const dirty = (e.in !== undefined && e.in !== (r.in?.hhmm || "")) ||
                    (e.out !== undefined && e.out !== (r.out?.hhmm || ""));
                  const canEdit = canAct;
                  return (
                    <View key={r.key} style={[upStyles.row, i % 2 === 0 && upStyles.rowAlt]}>
                      <Text style={[upStyles.cell, { width: 82 }]}>{fmtDate(r.date)}</Text>
                      <Text style={[upStyles.cell, { width: 54 }]}>{r.employee_code || "—"}</Text>
                      <Text style={[upStyles.cell, { width: 150, fontWeight: "600" }]} numberOfLines={1}>
                        {r.name || "—"}
                      </Text>
                      <Text style={[upStyles.cell, { width: 130 }]} numberOfLines={1}>
                        {r.father_name || "—"}
                      </Text>
                      <Text style={[upStyles.cell, { width: 110 }]} numberOfLines={1}>
                        {r.designation || "—"}
                      </Text>
                      {(["in", "out"] as const).map((k) => {
                        const cell = r[k];
                        const val = k === "in" ? inVal : outVal;
                        const cellDate = cell?.date;
                        const nightShift = Boolean(cellDate && cellDate !== r.date);
                        return canEdit ? (
                          <View key={k} style={{ width: 86, paddingHorizontal: 3 }}>
                            <TextInput
                              value={val}
                              onChangeText={(v) => setEdit(r.key, k, v)}
                              placeholder={cell ? cell.hhmm : "HH:MM"}
                              placeholderTextColor={colors.onSurfaceTertiary}
                              // Tap on a prefilled time selects it all, so
                              // typing REPLACES instead of appending.
                              selectTextOnFocus
                              style={[
                                upStyles.timeInput,
                                !cell && upStyles.timeInputMissing,
                                cell?.edited && upStyles.timeInputEdited,
                              ]}
                              testID={`ds-${k}-${r.key}`}
                            />
                            {/* Night-shift clarity: show the punch's own
                                calendar date (amber when it's next-day). */}
                            <Text
                              style={[
                                upStyles.punchDate,
                                nightShift && { color: "#B45309", fontWeight: "800" },
                              ]}
                              numberOfLines={1}
                            >
                              {cellDate
                                ? `${fmtDate(cellDate)}${nightShift ? " (+1)" : ""}`
                                : k === "out" ? "auto date" : fmtDate(r.date)}
                            </Text>
                            {/* Iter 95g — one-tap fill from the employee's
                                shift (or closest Shift Master shift) when
                                the punch is missing. */}
                            {(() => {
                              if (tab !== "manual" || cell || val) return null;
                              const t0 = fillTimeFor(r, k, shiftDefs);
                              if (!t0) return null;
                              return (
                                <Pressable
                                  onPress={() => setEdit(r.key, k, t0)}
                                  style={upStyles.fillBtn}
                                  testID={`ds-fill-${k}-${r.key}`}
                                >
                                  <Ionicons name="flash" size={9} color="#0369A1" />
                                  <Text style={upStyles.fillBtnTxt}>{t0}</Text>
                                </Pressable>
                              );
                            })()}
                            {cell?.record_id ? (
                              <Pressable
                                onPress={() => openPunchPhoto(cell.record_id)}
                                style={upStyles.photoBtn}
                                testID={`ds-photo-${k}-${r.key}`}
                              >
                                <Ionicons name="camera" size={10} color={colors.brandPrimary} />
                                <Text style={upStyles.photoBtnTxt}>Photo</Text>
                              </Pressable>
                            ) : null}
                          </View>
                        ) : (
                          <View key={k} style={{ width: 86 }}>
                            <Text style={[upStyles.cell, { width: 86 }]}>
                              {cell?.hhmm || "—"}
                            </Text>
                            <Text
                              style={[
                                upStyles.punchDate,
                                nightShift && { color: "#B45309", fontWeight: "800" },
                              ]}
                            >
                              {cellDate ? `${fmtDate(cellDate)}${nightShift ? " (+1)" : ""}` : ""}
                            </Text>
                            {cell?.record_id ? (
                              <Pressable
                                onPress={() => openPunchPhoto(cell.record_id)}
                                style={upStyles.photoBtn}
                                testID={`ds-photo-${k}-${r.key}`}
                              >
                                <Ionicons name="camera" size={10} color={colors.brandPrimary} />
                                <Text style={upStyles.photoBtnTxt}>Photo</Text>
                              </Pressable>
                            ) : null}
                          </View>
                        );
                      })}
                      <Text style={[upStyles.cell, upStyles.num, { width: 68 }]}>
                        {fmtHoursHM(dutyH)}
                      </Text>
                      <View style={{ width: 90, justifyContent: "center" }}>
                        {tab === "manual" ? (
                          <Text style={[upStyles.badge, upStyles.badgeMiss]}>
                            {!r.in && !r.out ? "BOTH MISSING" : !r.in ? "IN MISSING" : "OUT MISSING"}
                          </Text>
                        ) : r.updated ? (
                          <Text style={[upStyles.badge, upStyles.badgeUpd]}>UPDATED</Text>
                        ) : (
                          <Text style={[upStyles.badge, upStyles.badgeOk]}>COMPLETE</Text>
                        )}
                      </View>
                      {/* Iter 111 — Updated tab: which punch changed, old →
                          new time, reason and the editing admin. */}
                      {tab === "updated" ? (
                        <View style={{ width: 230, justifyContent: "center", paddingHorizontal: 4 }}>
                          {(["in", "out"] as const).map((k) => {
                            const c = r[k];
                            if (!c?.edited) return null;
                            return (
                              <Text key={k} style={upStyles.updDetailTxt} numberOfLines={2}>
                                <Text style={{ fontWeight: "800" }}>{k.toUpperCase()}</Text>
                                {c.original_hhmm ? ` ${c.original_hhmm} → ${c.hhmm}` : ` ${c.hhmm}`}
                                {c.edit_reason ? ` · ${c.edit_reason}` : ""}
                                {c.edited_by_name ? ` · by ${c.edited_by_name}` : ""}
                              </Text>
                            );
                          })}
                          {!r.in?.edited && !r.out?.edited ? (
                            <Text style={upStyles.updDetailTxt}>—</Text>
                          ) : null}
                        </View>
                      ) : null}
                      {canAct ? (
                        <View style={{ width: 160, justifyContent: "center", paddingHorizontal: 3 }}>
                          {/* Iter 111 — per-row updation reason picker with
                              system default reasons. */}
                          <Pressable
                            onPress={() => setReasonPickFor(r.key)}
                            style={upStyles.reasonBtn}
                            testID={`ds-reason-${r.key}`}
                          >
                            <Text style={upStyles.reasonBtnTxt} numberOfLines={2}>
                              {reasonSel[r.key] || REASON_PRESETS[0]}
                            </Text>
                            <Ionicons name="chevron-down" size={11} color={colors.brandPrimary} />
                          </Pressable>
                        </View>
                      ) : null}
                      {canAct ? (
                        <View style={{ width: 70, justifyContent: "center", alignItems: "center" }}>
                          <Pressable
                            onPress={() => saveRow(r)}
                            disabled={savingRow === r.key || !dirty}
                            style={[upStyles.saveRowBtn, (!dirty || savingRow === r.key) && { opacity: 0.35 }]}
                            testID={`ds-save-${r.key}`}
                          >
                            {savingRow === r.key ? (
                              <ActivityIndicator size="small" color="#fff" />
                            ) : (
                              <Text style={upStyles.saveRowTxt}>Save</Text>
                            )}
                          </Pressable>
                        </View>
                      ) : null}
                    </View>
                  );
                })
              )}
            </View>
          </ScrollView>
          <View style={{ height: 40 }} />
        </ScrollView>
      ) : visibleRecords.length === 0 ? (
        <View style={styles.center} testID="empty-state">
          <Ionicons
            name={tab === "pending" ? "checkmark-done-circle" : "time-outline"}
            size={44}
            color={colors.brandPrimary}
          />
          <Text style={styles.dimTitle}>No {tab === "auto" ? "auto" : tab === "manual" ? "manual" : tab} punches</Text>
          <Text style={styles.dimBody}>
            {hasLoadedOnce
              ? `No ${tab === "auto" ? "auto-punch" : tab === "manual" ? "manual entry" : tab} records for ${selectedDate}${dateMode === "period" ? ` – ${toDate}` : ""}. Try another date or tab.`
              : "Pick a date and tap Show to load punches."}
          </Text>
        </View>
      ) : (
        /* Iter 93 — Same day-summary table as the Updated tab, for every
           punch-level tab. Row actions queue approve/reject for ALL the
           row's punches; "Save" commits the batch. */
        <ScrollView
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); load(false); }}
              tintColor={colors.brandPrimary}
            />
          }
        >
          <ScrollView horizontal showsHorizontalScrollIndicator={true}>
            <View>
              <View style={upStyles.hdrRow}>
                {[
                  { w: 82, txt: "Date" },
                  { w: 150, txt: "Name" },
                  { w: 130, txt: "Father Name" },
                  { w: 110, txt: "Designation" },
                  { w: 62, txt: "In" },
                  { w: 62, txt: "Out" },
                  { w: 72, txt: "Duty HRS" },
                  { w: 62, txt: "OT In" },
                  { w: 62, txt: "OT Out" },
                  { w: 68, txt: "Total OT" },
                  { w: 92, txt: "Total Duty HRS" },
                  ...(canAct && tab !== "approved" && tab !== "rejected" ? [{ w: 92, txt: "Action" }] : []),
                ].map((c) => (
                  <Text key={c.txt} style={[upStyles.hdrCell, { width: c.w }]}>
                    {c.txt}
                  </Text>
                ))}
              </View>
              {groupedRows.map((r, i) => {
                const decision = batchDecisions[r.recordIds[0]];
                return (
                  <View key={r.key} style={[upStyles.row, i % 2 === 0 && upStyles.rowAlt]}>
                    <Text style={[upStyles.cell, { width: 82 }]}>{fmtDate(r.date)}</Text>
                    <Text style={[upStyles.cell, { width: 150, fontWeight: "600" }]} numberOfLines={1}>
                      {r.name || "—"}
                    </Text>
                    <Text style={[upStyles.cell, { width: 130 }]} numberOfLines={1}>
                      {r.father_name || "—"}
                    </Text>
                    <Text style={[upStyles.cell, { width: 110 }]} numberOfLines={1}>
                      {r.designation || "—"}
                    </Text>
                    <Text style={[upStyles.cell, { width: 62 }]}>{r.in ? fmtTime(r.in) : "—"}</Text>
                    <Text style={[upStyles.cell, { width: 62 }]}>{r.out ? fmtTime(r.out) : "—"}</Text>
                    <Text style={[upStyles.cell, upStyles.num, { width: 72 }]}>{fmtHoursHM(r.duty_hours)}</Text>
                    <Text style={[upStyles.cell, { width: 62 }]}>{r.ot_in ? fmtTime(r.ot_in) : "—"}</Text>
                    <Text style={[upStyles.cell, { width: 62 }]}>{r.ot_out ? fmtTime(r.ot_out) : "—"}</Text>
                    <Text style={[upStyles.cell, upStyles.num, { width: 68, color: r.ot_hours > 0 ? colors.accent : colors.onSurfaceTertiary }]}>
                      {r.ot_hours > 0 ? fmtHoursHM(r.ot_hours) : "—"}
                    </Text>
                    <Text style={[upStyles.cell, upStyles.num, { width: 92, fontWeight: "700" }]}>
                      {fmtHoursHM(r.total_hours)}
                    </Text>
                    {/* Iter 95f — already-decided rows (Approved/Rejected
                        tabs) are read-only: no ✓ / ✗ buttons. */}
                    {canAct && tab !== "approved" && tab !== "rejected" ? (
                      <View style={{ width: 92, flexDirection: "row", gap: 6, justifyContent: "center" }}>
                        <Pressable
                          onPress={() => r.recordIds.forEach((id) => queueDecision(id, "approve"))}
                          style={[upStyles.actBtn, decision === "approve" && upStyles.actBtnOk]}
                          testID={`pa-row-approve-${r.key}`}
                        >
                          <Ionicons name="checkmark" size={14} color={decision === "approve" ? "#fff" : "#15803D"} />
                        </Pressable>
                        <Pressable
                          onPress={() => r.recordIds.forEach((id) => queueDecision(id, "reject"))}
                          style={[upStyles.actBtn, decision === "reject" && upStyles.actBtnNo]}
                          testID={`pa-row-reject-${r.key}`}
                        >
                          <Ionicons name="close" size={14} color={decision === "reject" ? "#fff" : "#DC2626"} />
                        </Pressable>
                      </View>
                    ) : null}
                  </View>
                );
              })}
            </View>
          </ScrollView>
          <View style={{ height: 40 }} />
        </ScrollView>
      )}

      <Modal visible={photo.open} transparent animationType="fade" onRequestClose={() => setPhoto((p) => ({ ...p, open: false }))}>
        <Pressable style={photoStyles.overlay} onPress={() => setPhoto((p) => ({ ...p, open: false }))}>
          <View style={photoStyles.box}>
            <View style={photoStyles.boxHead}>
              <Text style={photoStyles.boxTitle}>Punch Photo</Text>
              <Pressable onPress={() => setPhoto((p) => ({ ...p, open: false }))} hitSlop={10}>
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            {photo.loading ? (
              <ActivityIndicator color={colors.brandPrimary} size="large" style={{ marginVertical: 40 }} />
            ) : photo.b64 ? (
              <Image source={{ uri: `data:image/jpeg;base64,${photo.b64}` }} style={photoStyles.img} resizeMode="contain" />
            ) : (
              <View style={photoStyles.noPhoto}>
                <Ionicons name="camera-outline" size={40} color={colors.onSurfaceTertiary} />
                <Text style={photoStyles.noPhotoTxt}>No photo captured for this punch.</Text>
              </View>
            )}
          </View>
        </Pressable>
      </Modal>

      {/* Iter 111 — Updation reason picker (system defaults + custom). */}
      <Modal visible={!!reasonPickFor} transparent animationType="fade" onRequestClose={() => setReasonPickFor(null)}>
        <Pressable style={photoStyles.overlay} onPress={() => setReasonPickFor(null)}>
          <View style={photoStyles.box}>
            <View style={photoStyles.boxHead}>
              <Text style={photoStyles.boxTitle}>Reason of Updation</Text>
              <Pressable onPress={() => setReasonPickFor(null)} hitSlop={10}>
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            {REASON_PRESETS.map((p, idx) => {
              const active = reasonPickFor
                ? (reasonSel[reasonPickFor] || REASON_PRESETS[0]) === p
                : false;
              return (
                <Pressable
                  key={p}
                  onPress={() => {
                    if (reasonPickFor) setReasonSel((prev) => ({ ...prev, [reasonPickFor]: p }));
                    setReasonPickFor(null);
                  }}
                  style={[upStyles.reasonOpt, active && upStyles.reasonOptActive]}
                  testID={`reason-opt-${idx}`}
                >
                  <Ionicons
                    name={active ? "radio-button-on" : "radio-button-off"}
                    size={16}
                    color={active ? colors.brandPrimary : colors.onSurfaceTertiary}
                  />
                  <Text style={upStyles.reasonOptTxt}>{idx + 1}. {p}</Text>
                </Pressable>
              );
            })}
            <Pressable
              onPress={() => {
                const key = reasonPickFor;
                const custom = globalThis.prompt?.("Type a custom reason:");
                if (key && custom && custom.trim()) {
                  setReasonSel((prev) => ({ ...prev, [key]: custom.trim() }));
                }
                setReasonPickFor(null);
              }}
              style={upStyles.reasonOpt}
              testID="reason-opt-custom"
            >
              <Ionicons name="create-outline" size={16} color={colors.brandPrimary} />
              <Text style={[upStyles.reasonOptTxt, { color: colors.brandPrimary }]}>Custom reason…</Text>
            </Pressable>
          </View>
        </Pressable>
      </Modal>

      {/* Iter 113 — Individual Punch modal. */}
      <Modal visible={indOpen} transparent animationType="fade" onRequestClose={() => setIndOpen(false)}>
        <View style={photoStyles.overlay}>
          <View style={[photoStyles.box, { width: 440, maxWidth: "94%" }]}>
            <View style={photoStyles.boxHead}>
              <Text style={photoStyles.boxTitle}>Individual Punch</Text>
              <Pressable onPress={() => setIndOpen(false)} hitSlop={10}>
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            {/* Employee picker */}
            <Text style={upStyles.indLbl}>Employee</Text>
            {indEmp ? (
              <Pressable onPress={() => setIndEmp(null)} style={upStyles.indEmpSel} testID="ip-emp-selected">
                <Text style={{ fontSize: 13, fontWeight: "700", color: colors.onSurface }}>
                  {indEmp.name}{indEmp.employee_code ? ` (Code ${indEmp.employee_code})` : ""}
                </Text>
                <Ionicons name="close-circle" size={16} color={colors.onSurfaceTertiary} />
              </Pressable>
            ) : (
              <View>
                <TextInput
                  value={indSearch}
                  onChangeText={setIndSearch}
                  placeholder="Search name / code…"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={upStyles.indInput}
                  testID="ip-emp-search"
                />
                <ScrollView style={{ maxHeight: 150, marginTop: 4 }} keyboardShouldPersistTaps="handled">
                  {indEmps
                    .filter((e) => {
                      const q = indSearch.trim().toLowerCase();
                      if (!q) return true;
                      return e.name.toLowerCase().includes(q) ||
                        String(e.employee_code || "").toLowerCase().includes(q);
                    })
                    .slice(0, 30)
                    .map((e) => (
                      <Pressable
                        key={e.user_id}
                        onPress={() => setIndEmp(e)}
                        style={upStyles.indEmpOpt}
                        testID={`ip-emp-${e.user_id}`}
                      >
                        <Text style={{ fontSize: 12.5, color: colors.onSurface }}>
                          {e.name}{e.employee_code ? `  ·  ${e.employee_code}` : ""}
                        </Text>
                      </Pressable>
                    ))}
                  {indEmps.length === 0 ? (
                    <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary, padding: 8, fontStyle: "italic" }}>
                      Loading employees…
                    </Text>
                  ) : null}
                </ScrollView>
              </View>
            )}
            {/* Date + times */}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
              <View style={{ flex: 1 }}>
                <Text style={upStyles.indLbl}>Date (YYYY-MM-DD)</Text>
                <TextInput value={indDate} onChangeText={setIndDate} placeholder="YYYY-MM-DD"
                  placeholderTextColor={colors.onSurfaceTertiary} style={upStyles.indInput} maxLength={10} testID="ip-date" />
              </View>
              <View style={{ width: 90 }}>
                <Text style={upStyles.indLbl}>IN (HH:MM)</Text>
                <TextInput value={indIn} onChangeText={setIndIn} placeholder="09:00" keyboardType="numeric"
                  placeholderTextColor={colors.onSurfaceTertiary} style={upStyles.indInput} maxLength={5} testID="ip-in" />
              </View>
              <View style={{ width: 90 }}>
                <Text style={upStyles.indLbl}>OUT (HH:MM)</Text>
                <TextInput value={indOut} onChangeText={setIndOut} placeholder="18:00" keyboardType="numeric"
                  placeholderTextColor={colors.onSurfaceTertiary} style={upStyles.indInput} maxLength={5} testID="ip-out" />
              </View>
            </View>
            {/* Reason presets */}
            <Text style={[upStyles.indLbl, { marginTop: 10 }]}>Reason</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {REASON_PRESETS.map((p) => (
                <Pressable
                  key={p}
                  onPress={() => setIndReason(p)}
                  style={[upStyles.indReasonChip, indReason === p && upStyles.indReasonChipOn]}
                >
                  <Text style={[upStyles.indReasonTxt, indReason === p && { color: "#fff" }]}>{p}</Text>
                </Pressable>
              ))}
            </View>
            <Text style={{ fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 6 }}>
              OUT earlier than IN is saved to the NEXT day (night shift). Punch is
              auto-approved and linked to attendance immediately.
            </Text>
            <Pressable
              onPress={saveIndividualPunch}
              disabled={indSaving}
              style={[upStyles.indSaveBtn, indSaving && { opacity: 0.6 }]}
              testID="ip-save"
            >
              <Text style={{ color: "#fff", fontSize: 13, fontWeight: "800" }}>
                {indSaving ? "Saving…" : "Save Punch"}
              </Text>
            </Pressable>
          </View>
        </View>
      </Modal>

    </View>
  );
}

const photoStyles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center", padding: 24 },
  box: { width: "100%", maxWidth: 400, backgroundColor: colors.surface, borderRadius: 16, padding: 16 },
  boxHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 12 },
  boxTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  img: { width: "100%", height: 320, borderRadius: 12, backgroundColor: "#000" },
  noPhoto: { alignItems: "center", padding: 30, gap: 10 },
  noPhotoTxt: { color: colors.onSurfaceSecondary, textAlign: "center" },
});

function Header({
  title,
  subtitle,
  onBack,
}: {
  title: string;
  subtitle?: string;
  onBack: () => void;
}) {
  return (
    <View style={styles.header}>
      <Pressable onPress={onBack} hitSlop={8}>
        <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
      </Pressable>
      <View style={{ flex: 1, marginLeft: 8 }}>
        <Text style={styles.h1}>{title}</Text>
        {subtitle ? <Text style={styles.h1Sub}>{subtitle}</Text> : null}
      </View>
    </View>
  );
}

function TabPill({
  label,
  count,
  active,
  onPress,
  testID,
}: {
  label: string;
  count?: number;
  active: boolean;
  onPress: () => void;
  testID?: string;
}) {
  return (
    <Pressable onPress={onPress} testID={testID} style={[styles.tab, active && styles.tabOn]}>
      <Text style={[styles.tabTxt, active && styles.tabTxtOn]}>{label}</Text>
      {typeof count === "number" && count > 0 ? (
        <View style={[styles.tabBadge, active && styles.tabBadgeOn]}>
          <Text style={[styles.tabBadgeTxt, active && { color: colors.brandPrimary }]}>
            {count}
          </Text>
        </View>
      ) : null}
    </Pressable>
  );
}

// ---------- helpers ----------

// Iter 95 — Duty/Total HRS shown in TIME format (HH:MM), never decimals.
function fmtHoursHM(hoursDec: number | null | undefined): string {
  if (!hoursDec || hoursDec <= 0) return "—";
  const totalMin = Math.round(hoursDec * 60);
  const h = Math.floor(totalMin / 60);
  const mm = totalMin % 60;
  return `${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
    });
  } catch {
    return iso;
  }
}

function fmtDate(ymd: string): string {
  try {
    const [y, m, d] = ymd.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return ymd;
  }
}

function showAlert(title: string, msg: string) {
  if (Platform.OS === "web") {
    console.log(title, msg);
    return;
  }
  Alert.alert(title, msg);
}

const styles = StyleSheet.create({
  // Iter 83 — Date filter bar under the tabs.
  dateBar: {
    flexDirection: "row",
    alignItems: "center",
    // Iter 93 — wrap on narrow screens so the calendar fields and the
    // Show/Save buttons never get squeezed to zero width or clipped.
    flexWrap: "wrap",
    gap: 8,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.surfaceTertiary,
    backgroundColor: colors.surfaceSecondary,
  },
  dateLbl: { color: colors.onSurfaceSecondary, fontWeight: "700", fontSize: 13 },
  dateInput: {
    borderWidth: 1,
    borderColor: colors.surfaceTertiary,
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    fontSize: 13,
    color: colors.onSurface,
    backgroundColor: "#FFFFFF",
    minWidth: 130,
  },
  dateModeChip: {
    paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  dateModeChipOn: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  dateModeTxt: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  dateModeTxtOn: { color: "#fff" },
  dateTodayBtn: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    backgroundColor: colors.brand,
    borderRadius: 6,
  },
  dateTodayTxt: { color: "#FFFFFF", fontWeight: "700", fontSize: 12 },

  // Iter 85 — Show + Save button styles next to the date filter.
  showBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.md,
    backgroundColor: colors.brandPrimary,
  },
  showBtnTxt: {
    color: "#FFFFFF",
    fontWeight: "800",
    fontSize: 12,
  },
  saveBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.md,
    backgroundColor: colors.accent,
  },
  saveBtnTxt: {
    color: "#FFFFFF",
    fontWeight: "800",
    fontSize: 12,
  },
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  h1: { fontSize: type.lg, color: colors.onSurface, fontWeight: "700" },
  h1Sub: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 2 },

  tabs: {
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
    flexWrap: "wrap",
  },
  // Iter 85 — Two-row tab layout (By Status / By Source).
  tabsGroup: {
    paddingHorizontal: spacing.lg,
    paddingBottom: 6,
  },
  tabsGroupLbl: {
    fontSize: 10,
    fontWeight: "800",
    color: colors.onSurfaceSecondary,
    textTransform: "uppercase",
    letterSpacing: 0.4,
    marginBottom: 4,
  },
  tab: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  tabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { color: colors.onSurface, fontWeight: "600", fontSize: type.sm },
  tabTxtOn: { color: colors.onCta },
  tabBadge: {
    minWidth: 20,
    paddingHorizontal: 6,
    height: 18,
    borderRadius: 9,
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  tabBadgeOn: { backgroundColor: "#fff" },
  tabBadgeTxt: { color: "#fff", fontSize: 10, fontWeight: "800" },

  list: { padding: spacing.lg, gap: spacing.md },

  card: {
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    gap: spacing.sm,
    ...shadow.card,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 12 },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarTxt: { color: colors.brandPrimary, fontSize: 16, fontWeight: "700" },
  name: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  metaTxt: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 2 },

  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  pillTxt: { fontSize: 10, fontWeight: "800", letterSpacing: 0.4 },

  factRow: { flexDirection: "row", gap: 12 },
  fact: { flex: 1 },
  factLbl: { flexDirection: "row", alignItems: "center", gap: 4 },
  factLblTxt: {
    color: colors.onSurfaceTertiary,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.5,
  },
  factVal: { color: colors.onSurface, fontSize: type.sm, fontWeight: "600", marginTop: 2 },

  adjNote: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brandTertiary,
    padding: 8,
    borderRadius: radius.sm,
  },
  adjNoteTxt: { color: colors.brandPrimary, fontSize: 12, fontWeight: "600", flex: 1 },
  reasonTxt: {
    color: colors.onSurfaceSecondary,
    fontSize: 12,
    fontStyle: "italic",
    marginTop: 2,
  },

  actionRow: { flexDirection: "row", gap: 8, marginTop: 6 },
  superHint: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brandTertiary,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderRadius: radius.sm,
    paddingHorizontal: 8,
    paddingVertical: 6,
    marginTop: 6,
  },
  superHintTxt: {
    color: colors.brandPrimary,
    fontSize: 11,
    fontWeight: "700",
    flex: 1,
  },
  actBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingVertical: 10,
    borderRadius: radius.pill,
    borderWidth: 1,
  },
  approve: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  approveTxt: { color: "#fff", fontWeight: "700", fontSize: type.sm },
  adjust: { backgroundColor: colors.brandTertiary, borderColor: colors.brandPrimary },
  adjustTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: type.sm },
  reject: { backgroundColor: colors.surface, borderColor: colors.error },
  rejectTxt: { color: colors.error, fontWeight: "700", fontSize: type.sm },

  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: 10 },
  errTxt: { color: colors.onSurfaceSecondary, fontSize: type.sm, textAlign: "center" },
  retry: {
    marginTop: 4,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: radius.pill,
    backgroundColor: colors.brandPrimary,
  },
  retryTxt: { color: "#fff", fontWeight: "700" },
  dimTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  dimBody: {
    color: colors.onSurfaceSecondary,
    textAlign: "center",
    fontSize: type.sm,
    lineHeight: 20,
    paddingHorizontal: spacing.lg,
  },

  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.4)" },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  grip: {
    alignSelf: "center",
    width: 44,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    marginBottom: 4,
  },
  sheetTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  sheetSub: { color: colors.onSurfaceSecondary, fontSize: type.sm, lineHeight: 18 },
  lblSmall: {
    color: colors.onSurfaceSecondary,
    fontSize: 12,
    fontWeight: "600",
    marginTop: 6,
    marginBottom: 4,
  },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.onSurface,
    fontSize: type.base,
  },
  sheetActions: { flexDirection: "row", gap: 10, marginTop: spacing.md },
  sheetBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderRadius: radius.pill,
  },
  sheetCancel: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  sheetCancelTxt: { color: colors.onSurface, fontWeight: "700" },
  sheetSubmit: { backgroundColor: colors.brandPrimary },
  sheetSubmitTxt: { color: "#fff", fontWeight: "700" },
});


// Iter 83 — Updated Punches tab table styles
const upStyles = StyleSheet.create({
  // Iter 94 — day-status tab additions
  hintBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 6,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.sm,
    padding: 8,
    marginBottom: 8,
  },
  hintTxt: { flex: 1, fontSize: 11, color: colors.onSurfaceSecondary, lineHeight: 15 },
  timeInput: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 5,
    fontSize: 12,
    color: colors.onSurface,
    backgroundColor: colors.surface,
    textAlign: "center",
  },
  timeInputMissing: { borderColor: "#DC2626", backgroundColor: "#FEF2F2" },
  timeInputEdited: { borderColor: "#B45309", backgroundColor: "#FFFBEB" },
  badge: {
    fontSize: 9,
    fontWeight: "800",
    textAlign: "center",
    paddingVertical: 3,
    paddingHorizontal: 4,
    borderRadius: 5,
    overflow: "hidden",
  },
  badgeMiss: { color: "#DC2626", backgroundColor: "#FEF2F2" },
  badgeUpd: { color: "#B45309", backgroundColor: "#FFFBEB" },
  badgeOk: { color: "#15803D", backgroundColor: "#F0FDF4" },
  // Iter 94 — small calendar-date label under each punch time
  punchDate: {
    fontSize: 8.5,
    color: colors.onSurfaceTertiary,
    textAlign: "center",
    marginTop: 2,
  },
  saveRowBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: 6,
    paddingVertical: 6,
    paddingHorizontal: 12,
  },
  saveRowTxt: { color: "#fff", fontSize: 11, fontWeight: "800" },
  // Iter 111 — Add/Less sign + HRS/MIN unit toggles (Additional Duty).
  signBtn: {
    width: 24, height: 26, borderRadius: 6, borderWidth: 1,
    borderColor: colors.borderStrong, backgroundColor: "#F0FDF4",
    alignItems: "center", justifyContent: "center",
  },
  signBtnLess: { backgroundColor: "#FEF2F2", borderColor: "#FCA5A5" },
  signBtnTxt: { fontSize: 14, fontWeight: "900", color: "#15803D" },
  unitBtn: {
    paddingHorizontal: 5, height: 26, borderRadius: 6, borderWidth: 1,
    borderColor: colors.brandPrimary, backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  unitBtnTxt: { fontSize: 9, fontWeight: "800", color: colors.brandPrimary },
  // Iter 111 — per-row updation reason picker + Updated-tab audit text.
  reasonBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    gap: 4, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: 6,
    paddingHorizontal: 6, paddingVertical: 5, backgroundColor: colors.surface,
  },
  reasonBtnTxt: { flex: 1, fontSize: 10.5, color: colors.onSurface, fontWeight: "600" },
  updDetailTxt: { fontSize: 10, color: "#B45309", lineHeight: 14 },
  reasonOpt: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 10, paddingHorizontal: 8, borderRadius: 8,
  },
  reasonOptActive: { backgroundColor: colors.brandTertiary },
  reasonOptTxt: { fontSize: 13, color: colors.onSurface, fontWeight: "600" },
  // Iter 113 — Individual Punch button + modal styles.
  indBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 14, paddingVertical: 9,
  },
  indBtnTxt: { color: "#fff", fontSize: 12.5, fontWeight: "800" },
  indLbl: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  indInput: {
    borderWidth: 1, borderColor: colors.borderStrong, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  indEmpSel: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 9, backgroundColor: colors.brandTertiary,
  },
  indEmpOpt: {
    paddingVertical: 8, paddingHorizontal: 10,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
  },
  indReasonChip: {
    borderWidth: 1, borderColor: colors.borderStrong, borderRadius: 14,
    paddingHorizontal: 10, paddingVertical: 6, backgroundColor: colors.surface,
  },
  indReasonChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  indReasonTxt: { fontSize: 11.5, fontWeight: "600", color: colors.onSurface },
  indSaveBtn: {
    marginTop: 12, backgroundColor: colors.brandPrimary, borderRadius: 8,
    alignItems: "center", paddingVertical: 11,
  },
  // Iter 113 — Manual Punches quick log panel.
  mlogBox: {
    borderWidth: 1, borderColor: "#FCD34D", backgroundColor: "#FFFBEB",
    borderRadius: 10, padding: 10, marginBottom: 10,
  },
  mlogTitle: { fontSize: 12, fontWeight: "800", color: "#92400E", marginBottom: 6 },
  mlogEmpty: { fontSize: 11.5, color: colors.onSurfaceTertiary, fontStyle: "italic" },
  mlogRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingVertical: 5, borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: "#FDE68A",
  },
  mlogCell: { fontSize: 11.5, color: colors.onSurface },
  mlogUndo: {
    flexDirection: "row", alignItems: "center", gap: 3,
    borderWidth: 1, borderColor: "#FCA5A5", borderRadius: 6,
    paddingHorizontal: 8, paddingVertical: 4, backgroundColor: "#FEF2F2",
  },
  mlogUndoTxt: { fontSize: 10.5, fontWeight: "800", color: "#B91C1C" },
  hdrRow: {
    flexDirection: "row",
    backgroundColor: colors.brand,
    borderTopLeftRadius: 8,
    borderTopRightRadius: 8,
  },
  hdrCell: {
    color: "#FFFFFF",
    fontWeight: "800",
    fontSize: 12,
    padding: 10,
    textAlign: "center",
    borderRightWidth: 1,
    borderRightColor: "rgba(255,255,255,0.15)",
  },
  row: {
    flexDirection: "row",
    borderBottomWidth: 1,
    borderBottomColor: colors.surfaceTertiary,
    backgroundColor: "#FFFFFF",
  },
  rowAlt: {
    backgroundColor: colors.surfaceTertiary,
  },
  cell: {
    color: colors.onSurface,
    padding: 10,
    fontSize: 13,
    borderRightWidth: 1,
    borderRightColor: colors.surfaceTertiary,
  },
  num: {
    textAlign: "right",
    fontVariant: ["tabular-nums" as any],
    fontWeight: "600",
  },
  emptyTxt: {
    padding: 20,
    color: colors.onSurfaceTertiary,
    fontStyle: "italic",
    textAlign: "center",
  },
  // Iter 95g — "Fill from shift" one-tap pill under empty time boxes.
  fillBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 3, marginTop: 3, paddingVertical: 3, paddingHorizontal: 6,
    borderRadius: 6, borderWidth: 1, borderColor: "#0369A1",
    backgroundColor: "rgba(3,105,161,0.08)",
  },
  fillBtnTxt: { fontSize: 9.5, fontWeight: "800", color: "#0369A1" },
  photoBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 3,
    marginTop: 3, paddingVertical: 2, paddingHorizontal: 6, borderRadius: 6,
    backgroundColor: "#EFF6FF", alignSelf: "center",
  },
  photoBtnTxt: { fontSize: 9.5, fontWeight: "800", color: colors.brandPrimary },
  // Iter 93 — row action buttons (queue approve / reject for the day group)
  actBtn: {
    width: 30,
    height: 26,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: colors.divider,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "center",
    backgroundColor: colors.surface,
  },
  actBtnOk: { backgroundColor: "#15803D", borderColor: "#15803D" },
  actBtnNo: { backgroundColor: "#DC2626", borderColor: "#DC2626" },
});

