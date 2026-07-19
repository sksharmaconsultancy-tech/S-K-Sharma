/**
 * Monthly Attendance Grid — Iter 76.
 *
 * Renders the same per-employee × per-day matrix as the XLSX exports,
 * but live inside the web portal. Each cell shows IN / OUT / hours;
 * summary columns on the right show Total Present Days, Total Hours
 * and Overtime Hours.
 *
 * Data source: GET /api/admin/attendance/monthly-grid/{cid}/{month}
 * (a JSON sibling of the /monthly-inout/.xlsx endpoint that reuses the
 * same _pair_punches loop, so the numbers stay identical.)
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  TextInput,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useLiveSync } from "@/src/api/live-sync";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import * as FileSystemNS from "expo-file-system";
import * as Sharing from "expo-sharing";
import { colors, radius, shadow, spacing, type } from "@/src/theme";

const FileSystem: any = FileSystemNS as any;

type Cell = {
  in: string | null;
  out: string | null;
  ot_in?: string | null;       // Iter 77g — OT window start
  ot_out?: string | null;      // Iter 77g — OT window end
  hours: number;               // policy-adjusted duty hours (Total Duty HRS view)
  raw_hours?: number;          // Iter 77e — actual worked hours (IN/OUT view)
  ot_hours?: number;           // Iter 77f — SEPARATE OT hours
  punches?: number;
  sources?: string[]; // ["bio","app","sys"] — provenance badges for the day
  present?: number;            // Iter 77e — 0 / 0.5 / 1 present-day credit
  weekly_off?: boolean;        // Iter 77e — cell falls on a weekly-off day
  salary?: number;             // Iter 94 — day-wise earned salary (₹)
};

type EmpRow = {
  user_id: string;
  employee_code?: string | null;
  name?: string | null;
  father_name?: string | null;
  department?: string | null;
  position?: string | null;
  designation?: string | null;   // Iter 77f — shown instead of department
  doj?: string | null;
  bio_code?: string | number | null;
  employee_group?: string | null;
  days: Record<string, Cell>;
  totals: {
    present_days: number;
    hours: number;
    ot_hours: number;
    // Iter 77k — decimal-days total (Total Duty HRS / Shift HRS)
    total_days_computed?: number;
    shift_hours?: number;
    salary_total?: number;     // Iter 94 — employee-wise earned salary (₹)
  };
};

type GridResp = {
  company: { company_id: string; name: string };
  month: string;
  days_in_month: number;
  day_labels: string[];
  weekday_labels: string[];
  full_day_hours: number;
  employees: EmpRow[];
  // Iter 94 — day-wise salary bottom row + grand total
  day_salary_totals?: Record<string, number>;
  salary_grand_total?: number;
};

const currentMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

const shiftMonth = (ym: string, dir: -1 | 1): string => {
  const [ys, ms] = ym.split("-");
  let y = Number(ys), m = Number(ms) + dir;
  if (m < 1) { m = 12; y -= 1; }
  if (m > 12) { m = 1; y += 1; }
  return `${y}-${String(m).padStart(2, "0")}`;
};

/** Convert decimal hours (e.g. 9.9) to a HH:MM string ("09:54"). */
// Iter 94 — 5 report types: In/Out, OT In/Out, Total Duty HRS,
// Per-Day Salary, and In/Out WITH Salary.
type GridView = "inout" | "hours" | "ot" | "salary" | "inout_salary";

// Compact ₹ formatter for salary day cells.
const fmtRsCell = (n?: number | null): string =>
  n && n > 0 ? `₹${Math.round(n).toLocaleString("en-IN")}` : "—";

const fmtHoursHM = (hoursDec: number | null | undefined): string => {
  if (!hoursDec || hoursDec <= 0) return "—";
  const totalMin = Math.round(hoursDec * 60);
  const h = Math.floor(totalMin / 60);
  const mm = totalMin % 60;
  return `${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
};

/**
 * Iter 77 - Date-input formatter for the DD-MM-YYYY custom range fields.
 *  - Digits only (dashes are auto-inserted)
 *  - Auto-inserts "-" after DD and after MM
 *  - Clamps DD to 01-31, MM to 01-12
 *  - Returns partial strings while user is still typing
 */
function formatDdmmyyyyInput(raw: string): string {
  const digits = (raw || "").replace(/\D/g, "").slice(0, 8);
  if (!digits) return "";
  const dd = digits.slice(0, 2);
  const mm = digits.slice(2, 4);
  const yyyy = digits.slice(4, 8);
  const parts: string[] = [];
  if (dd.length === 2) {
    const d = Math.max(1, Math.min(31, parseInt(dd, 10) || 0));
    parts.push(String(d).padStart(2, "0"));
  } else {
    parts.push(dd);
  }
  if (mm.length > 0) {
    if (mm.length === 2) {
      const m = Math.max(1, Math.min(12, parseInt(mm, 10) || 0));
      parts.push(String(m).padStart(2, "0"));
    } else parts.push(mm);
  }
  if (yyyy.length > 0) parts.push(yyyy);
  return parts.join("-");
}

/** Convert "DD-MM-YYYY" -> "YYYY-MM-DD"; empty / invalid -> "". */
function ddmmyyyyToIso(dmy: string): string {
  const m = /^(\d{2})-(\d{2})-(\d{4})$/.exec((dmy || "").trim());
  if (!m) return "";
  return `${m[3]}-${m[2]}-${m[1]}`;
}

const isValidDdmmyyyy = (v: string): boolean => {
  const m = /^(\d{2})-(\d{2})-(\d{4})$/.exec((v || "").trim());
  if (!m) return false;
  const d = Number(m[1]); const mo = Number(m[2]); const y = Number(m[3]);
  if (d < 1 || d > 31) return false;
  if (mo < 1 || mo > 12) return false;
  if (y < 2000 || y > 2100) return false;
  return true;
};

export default function AttendanceGridScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const params = useLocalSearchParams<{ month?: string; company_id?: string }>();
  const { selectedCompanyId, setSelectedCompanyId } = useSelectedCompany() as any;
  const isAdmin =
    user?.role === "super_admin" ||
    user?.role === "company_admin" ||
    user?.role === "sub_admin";

  const initialMonth =
    typeof params.month === "string" && /^\d{4}-\d{2}$/.test(params.month)
      ? params.month
      : currentMonth();

  const [month, setMonth] = useState<string>(initialMonth);
  const [view, setView] = useState<GridView>("inout");

  // Iter 200 (user request) — per-firm Report Settings (Attendance Policy →
  // Report Settings) decide which report views exist for this firm and
  // which one opens by default.
  const [reportCfg, setReportCfg] = useState<{ enabled: Record<string, boolean>; default_view: string } | null>(null);
  // Iter 94 — HIDE the day columns 1–31 (hide only, data untouched).
  // When hidden, only summary columns show: OT HRS, Total Duty HRS,
  // Days, Extra HRS.
  const [hideDays, setHideDays] = useState(false);

  // Iter 77 - Optional custom date range. Inputs display DD-MM-YYYY but the
  // backend consumes YYYY-MM-DD, so we convert on-the-fly.
  const [fromDate, setFromDate] = useState<string>(""); // DD-MM-YYYY (visible)
  const [toDate, setToDate] = useState<string>("");     // DD-MM-YYYY (visible)
  // Iter 111 — Daily-basis report export date (defaults to today).
  const [dailyDate, setDailyDate] = useState<string>(() => {
    const d = new Date();
    return `${String(d.getDate()).padStart(2, "0")}-${String(d.getMonth() + 1).padStart(2, "0")}-${d.getFullYear()}`;
  });
  const fromIso = ddmmyyyyToIso(fromDate);
  const toIso = ddmmyyyyToIso(toDate);
  const rangeActive = !!fromIso && !!toIso;

  // Iter 77 - Employee-Group filter (Group Wise). None = all employees.
  const [groups, setGroups] = useState<{ group_id: string; name: string }[]>([]);
  const [groupId, setGroupId] = useState<string | null>(null);

  // Iter 76 — Honour ?company_id= passed from the Attendance Sheet
  // "Grid View" button so super-admins land on the right firm.
  // Iter 77b — Also re-fire when the selection is cleared (e.g. after
  // self-heal detects the previously-selected firm was deleted).
  useEffect(() => {
    if (
      typeof params.company_id === "string" &&
      params.company_id &&
      params.company_id !== selectedCompanyId &&
      typeof setSelectedCompanyId === "function"
    ) {
      setSelectedCompanyId(params.company_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.company_id, selectedCompanyId]);
  const [q, setQ] = useState<string>("");
  const [data, setData] = useState<GridResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [refreshingBio, setRefreshingBio] = useState(false);

  const effectiveCid = useMemo(() => {
    if (user?.role === "company_admin") return user.company_id || null;
    return selectedCompanyId && selectedCompanyId !== "all" ? selectedCompanyId : null;
  }, [user, selectedCompanyId]);

  const load = useCallback(async () => {
    if (!effectiveCid) return;
    setLoading(true);
    setErr(null);
    setData(null);
    try {
      const params: string[] = [];
      if (rangeActive) {
        params.push(`from_date=${encodeURIComponent(fromIso)}`);
        params.push(`to_date=${encodeURIComponent(toIso)}`);
      }
      if (groupId) params.push(`group_id=${encodeURIComponent(groupId)}`);
      const qs = params.length ? `?${params.join("&")}` : "";
      const res = await api<GridResp>(
        `/admin/attendance/monthly-grid/${effectiveCid}/${month}${qs}`,
      );
      setData(res);
    } catch (e: any) {
      setErr(e?.message || "Could not load attendance");
    } finally {
      setLoading(false);
    }
  }, [effectiveCid, month, rangeActive, groupId, fromIso, toIso]);

  useEffect(() => { load(); }, [load]);

  // Iter 93 — Re-map unmapped device punches after bio-code updates in the
  // Employee Master, then reload the grid so recovered punches show up.
  const refreshBioData = useCallback(async () => {
    if (refreshingBio) return;
    setRefreshingBio(true);
    try {
      const qs = effectiveCid ? `?company_id=${encodeURIComponent(effectiveCid)}` : "";
      const r = await api<{ checked: number; remapped: number; still_unmapped: number; dat_files_reread: number; dat_recovered: number }>(
        `/biometric/remap-unmapped${qs}`,
        { method: "POST" },
      );
      const parts: string[] = [];
      if (r.checked > 0) {
        parts.push(`Device queue: checked ${r.checked}, recovered ${r.remapped}, still unmapped ${r.still_unmapped}.`);
      }
      if (r.dat_files_reread > 0) {
        parts.push(`.dat files re-read: ${r.dat_files_reread} — recovered ${r.dat_recovered} punch(es).`);
      }
      const msg = parts.length ? parts.join("\n") : "No stored .dat files or unmapped device punches found.";
      if (Platform.OS === "web") globalThis.alert(msg);
      else Alert.alert("Biometric refresh", msg);
      if (r.remapped > 0 || r.dat_recovered > 0) await load();
    } catch (e: any) {
      const msg = e?.message || "Biometric refresh failed";
      if (Platform.OS === "web") globalThis.alert(msg);
      else Alert.alert("Biometric refresh", msg);
    } finally {
      setRefreshingBio(false);
    }
  }, [refreshingBio, effectiveCid, load]);

  // Iter 77 - Load groups for the current firm so the Group filter has options.
  // Iter 101 — ALSO merge legacy Masters groups (type=group, incl. global)
  // like the Attendance Sheet screen does, so firms that only use Masters
  // groups still see their Group filter here.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!effectiveCid) { setGroups([]); return; }
      try {
        const [egp, legacy] = await Promise.all([
          api<{ groups: { group_id: string; name: string }[] }>(
            `/admin/employee-groups?company_id=${encodeURIComponent(effectiveCid)}`,
          ).catch(() => ({ groups: [] })),
          api<{ items: { master_id: string; name: string }[] }>(
            `/admin/masters?type=group&company_id=${encodeURIComponent(effectiveCid)}`,
          ).catch(() => ({ items: [] })),
        ]);
        const combined = [
          ...(egp.groups || []),
          ...(legacy.items || []).map((m) => ({ group_id: m.master_id, name: m.name })),
        ];
        // de-dupe by name (Masters + policy groups may overlap)
        const seen = new Set<string>();
        const unique = combined.filter((g) => {
          const k = (g.name || "").trim().toLowerCase();
          if (!k || seen.has(k)) return false;
          seen.add(k);
          return true;
        });
        if (!cancelled) setGroups(unique);
      } catch {
        if (!cancelled) setGroups([]);
      }
    })();
    return () => { cancelled = true; };
  }, [effectiveCid]);

  // Reset group filter when firm changes (a group belongs to one firm).
  useEffect(() => { setGroupId(null); }, [effectiveCid]);

  // Iter 200 — load the firm's Report Settings and apply availability + default.
  useEffect(() => {
    if (!effectiveCid) return;
    let alive = true;
    (async () => {
      try {
        const r = await api<any>(
          `/attendance/policy?company_id=${encodeURIComponent(effectiveCid)}`);
        if (!alive) return;
        const rs = r?.policy?.report_settings || {};
        const enabled: Record<string, boolean> = rs.enabled || {};
        const order: GridView[] = ["inout", "ot", "hours", "salary", "inout_salary"];
        const isOn = (k: string) => (enabled[k] ?? true) !== false;
        let def = String(rs.default_view || "inout") as GridView;
        if (!isOn(def)) def = order.find(isOn) || "inout";
        setReportCfg({ enabled, default_view: def });
        setView(def);
      } catch { if (alive) setReportCfg(null); }
    })();
    return () => { alive = false; };
  }, [effectiveCid]);

  const viewEnabled = useCallback(
    (k: GridView) => (reportCfg?.enabled?.[k] ?? true) !== false,
    [reportCfg],
  );

  // Iter 77n — Live-sync: auto-refetch the grid when a new punch (mobile,
  // biometric or ZK push) lands for this firm. Debounced so a flurry of
  // punches (e.g. shift start) only triggers ONE refetch.
  const liveRefetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useLiveSync(effectiveCid, (ev) => {
    if (!ev?.type) return;
    if (!ev.type.startsWith("punch.")) return;
    if (liveRefetchTimer.current) clearTimeout(liveRefetchTimer.current);
    liveRefetchTimer.current = setTimeout(() => {
      load();
    }, 800);
  });
  useEffect(() => () => {
    if (liveRefetchTimer.current) clearTimeout(liveRefetchTimer.current);
  }, []);

  // Iter 77m — Sortable columns on the Attendance Grid.
  const [sortBy, setSortBy] = useState<
    "code" | "name" | "dept" | "department" | "designation" | "bio" | "days" | "hours" | "ot" | "duty"
  >("code");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const toggleSort = useCallback(
    (col: typeof sortBy) => {
      if (col === sortBy) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortBy(col);
        setSortDir("asc");
      }
    },
    [sortBy],
  );

  const filteredEmployees = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    const src = !needle
      ? data.employees
      : data.employees.filter((e) => {
          const hay = `${e.name || ""} ${e.employee_code || ""} ${e.bio_code || ""} ${e.department || ""} ${e.designation || ""}`.toLowerCase();
          return hay.includes(needle);
        });
    // Sort
    const sorted = src.slice().sort((a, b) => {
      const dir = sortDir === "asc" ? 1 : -1;
      const key = (v: string | number | null | undefined) =>
        v === null || v === undefined ? "" : String(v).toLowerCase();
      switch (sortBy) {
        case "code":
          return key(a.employee_code).localeCompare(key(b.employee_code), "en", { numeric: true }) * dir;
        case "name":
          return key(a.name).localeCompare(key(b.name)) * dir;
        case "dept":
          return key(a.designation || a.department).localeCompare(
            key(b.designation || b.department),
          ) * dir;
        // Iter 114 — dedicated Department-wise / Designation-wise sorting.
        case "department":
          return key(a.department).localeCompare(key(b.department)) * dir
            || key(a.name).localeCompare(key(b.name));
        case "designation":
          return key(a.designation).localeCompare(key(b.designation)) * dir
            || key(a.name).localeCompare(key(b.name));
        case "bio":
          return key(a.bio_code).localeCompare(key(b.bio_code), "en", { numeric: true }) * dir;
        case "days":
          return ((a.totals?.present_days || 0) - (b.totals?.present_days || 0)) * dir;
        case "hours":
          return ((a.totals?.hours || 0) - (b.totals?.hours || 0)) * dir;
        case "ot":
          return ((a.totals?.ot_hours || 0) - (b.totals?.ot_hours || 0)) * dir;
        case "duty":
          return (((a.totals as any)?.duty_hours || 0) - ((b.totals as any)?.duty_hours || 0)) * dir;
        default:
          return 0;
      }
    });
    return sorted;
  }, [data, q, sortBy, sortDir]);

  const downloadReport = useCallback(
    async (fmt: "xlsx" | "pdf") => {
      if (!effectiveCid || exporting) return;
      setExporting(true);
      try {
        const kind = view === "inout" ? "InOut" : "Hours";
        const slug = view === "inout" ? "monthly-inout" : "monthly-hours";
        const path = `/admin/attendance/${slug}/${effectiveCid}/${month}.${fmt}`;
        const res = await apiBinary(path);
        const fname = `MonthlyAttendance_${kind}_${month}.${fmt}`;
        const mime = fmt === "xlsx"
          ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          : "application/pdf";
        if (Platform.OS === "web" && res.webBlobUrl) {
          const a = document.createElement("a");
          a.href = res.webBlobUrl;
          a.download = fname;
          a.click();
          setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
        } else {
          const dest = `${FileSystem.cacheDirectory}${fname}`;
          await FileSystem.writeAsStringAsync(dest, res.base64, { encoding: "base64" });
          if (await Sharing.isAvailableAsync()) {
            await Sharing.shareAsync(dest, { mimeType: mime, dialogTitle: fname });
          }
        }
      } catch (e: any) {
        setErr(e?.message || "Download failed");
      } finally {
        setExporting(false);
      }
    },
    [effectiveCid, exporting, month, view],
  );

  // Iter 111 — Daily-basis report (single date, one row per employee).
  const downloadDaily = useCallback(
    async (fmt: "xlsx" | "pdf") => {
      const iso = ddmmyyyyToIso(dailyDate);
      if (!effectiveCid || exporting || !iso) return;
      setExporting(true);
      try {
        const gq = groupId ? `?group_id=${encodeURIComponent(groupId)}` : "";
        const res = await apiBinary(`/admin/attendance/daily/${effectiveCid}/${iso}.${fmt}${gq}`);
        const fname = `DailyAttendance_${iso}.${fmt}`;
        const mime = fmt === "xlsx"
          ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          : "application/pdf";
        if (Platform.OS === "web" && res.webBlobUrl) {
          const a = document.createElement("a");
          a.href = res.webBlobUrl;
          a.download = fname;
          a.click();
          setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
        } else {
          const dest = `${FileSystem.cacheDirectory}${fname}`;
          await FileSystem.writeAsStringAsync(dest, res.base64, { encoding: "base64" });
          if (await Sharing.isAvailableAsync()) {
            await Sharing.shareAsync(dest, { mimeType: mime, dialogTitle: fname });
          }
        }
      } catch (e: any) {
        setErr(e?.message || "Daily report download failed");
      } finally {
        setExporting(false);
      }
    },
    [effectiveCid, exporting, dailyDate, groupId],
  );

  if (!isAdmin) {
    return (
      <SafeAreaView style={styles.centerScreen}>
        <Ionicons name="lock-closed-outline" size={40} color={colors.brand} />
        <Text style={styles.errTitle}>Admins only</Text>
        <Pressable onPress={() => router.replace("/(tabs)" as any)} style={styles.retryBtn}>
          <Text style={styles.retryBtnTxt}>Back to dashboard</Text>
        </Pressable>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      {/* Toolbar */}
      <View style={styles.toolbar}>
        <Pressable onPress={() => router.back()} style={styles.iconBtn} hitSlop={8}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>

        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Monthly Attendance</Text>
          <Text style={styles.subtitle}>
            {data?.company.name || "Pick a firm above"} · {month}
          </Text>
        </View>

        {user?.role !== "company_admin" && (
          <View style={styles.firmPicker}>
            <CompanyPicker
              value={selectedCompanyId || "all"}
              onChange={(v) => setSelectedCompanyId(v === "all" ? null : v)}
              testID="attendance-grid-firm-picker"
              label=""
              compact
            />
          </View>
        )}
      </View>

      {/* Controls */}
      <View style={styles.controls}>
        <Pressable
          style={styles.chevBtn}
          onPress={() => setMonth((m) => shiftMonth(m, -1))}
          testID="ms-prev-month"
        >
          <Ionicons name="chevron-back" size={16} color={colors.onSurface} />
        </Pressable>
        <TextInput
          style={styles.monthInput}
          value={month}
          onChangeText={setMonth}
          placeholder="YYYY-MM"
          placeholderTextColor={colors.onSurfaceTertiary}
          autoCapitalize="none"
        />
        <Pressable
          style={styles.chevBtn}
          onPress={() => setMonth((m) => shiftMonth(m, 1))}
          testID="ms-next-month"
        >
          <Ionicons name="chevron-forward" size={16} color={colors.onSurface} />
        </Pressable>

        {/* View toggle — Iter 200: options follow the firm's Report Settings */}
        <View style={styles.segment}>
          {([
            ["inout", "IN / OUT", undefined],
            ["ot", "OT IN / OUT", undefined],
            ["hours", "Hours only", undefined],
            ["salary", "Day Salary", "view-salary"],
            ["inout_salary", "IN/OUT + Salary", "view-inout-salary"],
          ] as [GridView, string, string | undefined][])
            .filter(([k]) => viewEnabled(k))
            .map(([k, label, tid]) => (
              <Pressable
                key={k}
                style={[styles.segmentBtn, view === k && styles.segmentBtnOn]}
                onPress={() => setView(k)}
                testID={tid}
              >
                <Text style={[styles.segmentTxt, view === k && styles.segmentTxtOn]}>
                  {label}
                </Text>
              </Pressable>
            ))}
        </View>

        <TextInput
          style={styles.searchInput}
          value={q}
          onChangeText={setQ}
          placeholder="Search name / code / bio…"
          placeholderTextColor={colors.onSurfaceTertiary}
        />

        <Pressable
          onPress={refreshBioData}
          disabled={refreshingBio}
          style={[styles.refreshBioBtn, refreshingBio && { opacity: 0.6 }]}
          testID="ms-refresh-bio"
        >
          {refreshingBio ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <>
              <Ionicons name="sync-outline" size={14} color="#fff" />
              <Text style={styles.exportBtnTxt}>Refresh Bio</Text>
            </>
          )}
        </Pressable>
        <Pressable
          onPress={() => downloadReport("xlsx")}
          disabled={exporting || !data}
          style={[styles.exportBtn, (exporting || !data) && { opacity: 0.6 }]}
          testID="ms-export-xlsx"
        >
          {exporting ? (
            <ActivityIndicator color={colors.onCta} size="small" />
          ) : (
            <>
              <Ionicons name="download-outline" size={14} color={colors.onCta} />
              <Text style={styles.exportBtnTxt}>Excel</Text>
            </>
          )}
        </Pressable>
        <Pressable
          onPress={() => downloadReport("pdf")}
          disabled={exporting || !data}
          style={[styles.exportBtnPdf, (exporting || !data) && { opacity: 0.6 }]}
          testID="ms-export-pdf"
        >
          <Ionicons name="document-text-outline" size={14} color="#fff" />
          <Text style={styles.exportBtnTxt}>PDF</Text>
        </Pressable>

        {/* Iter 77i — Jump to the standalone OT Report screen. */}
        <Pressable
          onPress={() => {
            const cid = selectedCompanyId;
            if (!cid) return;
            const q = new URLSearchParams({ company_id: cid, month });
            if (fromIso && toIso) {
              q.set("from", fromIso);
              q.set("to", toIso);
            }
            router.push(`/ot-report?${q.toString()}`);
          }}
          disabled={!data}
          style={[styles.exportBtnOt, !data && { opacity: 0.6 }]}
          testID="ms-open-ot-report"
        >
          <Ionicons name="time-outline" size={14} color="#fff" />
          <Text style={styles.exportBtnTxt}>OT Report</Text>
        </Pressable>
      </View>

      {/* Iter 77 - Date range + source-badge legend */}
      <View style={styles.subControls}>
        <Text style={styles.rangeLabel}>Custom range</Text>
        <TextInput
          style={[
            styles.dateInput,
            fromDate && !isValidDdmmyyyy(fromDate) && styles.dateInputErr,
          ]}
          value={fromDate}
          onChangeText={(t) => setFromDate(formatDdmmyyyyInput(t))}
          placeholder="From DD-MM-YYYY"
          placeholderTextColor={colors.onSurfaceTertiary}
          autoCapitalize="none"
          keyboardType="number-pad"
          maxLength={10}
        />
        <Text style={styles.rangeDash}>-</Text>
        <TextInput
          style={[
            styles.dateInput,
            toDate && !isValidDdmmyyyy(toDate) && styles.dateInputErr,
          ]}
          value={toDate}
          onChangeText={(t) => setToDate(formatDdmmyyyyInput(t))}
          placeholder="To DD-MM-YYYY"
          placeholderTextColor={colors.onSurfaceTertiary}
          autoCapitalize="none"
          keyboardType="number-pad"
          maxLength={10}
        />
        {(fromDate || toDate) ? (
          <Pressable
            onPress={() => { setFromDate(""); setToDate(""); }}
            style={styles.clearRangeBtn}
          >
            <Ionicons name="close-circle" size={16} color={colors.onSurfaceSecondary} />
            <Text style={styles.clearRangeTxt}>Clear</Text>
          </Pressable>
        ) : null}
        {rangeActive ? (
          <View style={styles.rangePill}><Text style={styles.rangePillTxt}>Range active</Text></View>
        ) : null}

        {/* Iter 111 — Daily-basis report export (Excel / PDF) */}
        <Text style={[styles.rangeLabel, { marginLeft: 12 }]}>Daily basis</Text>
        <TextInput
          style={[
            styles.dateInput,
            dailyDate && !isValidDdmmyyyy(dailyDate) && styles.dateInputErr,
          ]}
          value={dailyDate}
          onChangeText={(t) => setDailyDate(formatDdmmyyyyInput(t))}
          placeholder="DD-MM-YYYY"
          placeholderTextColor={colors.onSurfaceTertiary}
          autoCapitalize="none"
          keyboardType="number-pad"
          maxLength={10}
          testID="daily-date-input"
        />
        <Pressable
          onPress={() => downloadDaily("xlsx")}
          disabled={exporting || !isValidDdmmyyyy(dailyDate)}
          style={[styles.exportBtn, (exporting || !isValidDdmmyyyy(dailyDate)) && { opacity: 0.6 }]}
          testID="daily-export-xlsx"
        >
          <Ionicons name="download-outline" size={14} color={colors.onCta} />
          <Text style={styles.exportBtnTxt}>Daily Excel</Text>
        </Pressable>
        <Pressable
          onPress={() => downloadDaily("pdf")}
          disabled={exporting || !isValidDdmmyyyy(dailyDate)}
          style={[styles.exportBtnPdf, (exporting || !isValidDdmmyyyy(dailyDate)) && { opacity: 0.6 }]}
          testID="daily-export-pdf"
        >
          <Ionicons name="document-text-outline" size={14} color="#fff" />
          <Text style={styles.exportBtnTxt}>Daily PDF</Text>
        </Pressable>

        {/* Iter 114 — quick sort options (user rule): Department / Designation wise */}
        <Text style={[styles.rangeLabel, { marginLeft: 12 }]}>Sort</Text>
        {([["department", "Department wise"], ["designation", "Designation wise"], ["name", "Name"], ["code", "Code"]] as const).map(([k, lbl]) => (
          <Pressable
            key={k}
            onPress={() => toggleSort(k)}
            style={[styles.groupChip, sortBy === k && styles.groupChipOn]}
            testID={`sort-${k}`}
          >
            <Text style={[styles.groupChipTxt, sortBy === k && styles.groupChipTxtOn]}>
              {lbl}{sortBy === k ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
            </Text>
          </Pressable>
        ))}

        {/* Iter 77 - Group Wise filter */}
        <View style={styles.groupBox}>
          <Text style={styles.rangeLabel}>Group</Text>
          <View style={styles.groupChipsRow}>
            <Pressable
              onPress={() => setGroupId(null)}
              style={[styles.groupChip, groupId === null && styles.groupChipOn]}
              testID="group-all"
            >
              <Text style={[styles.groupChipTxt, groupId === null && styles.groupChipTxtOn]}>
                All
              </Text>
            </Pressable>
            {groups.map((g) => (
              <Pressable
                key={g.group_id}
                onPress={() => setGroupId(g.group_id)}
                style={[styles.groupChip, groupId === g.group_id && styles.groupChipOn]}
                testID={`group-${g.name}`}
              >
                <Text style={[styles.groupChipTxt, groupId === g.group_id && styles.groupChipTxtOn]}>
                  {g.name}
                </Text>
              </Pressable>
            ))}
            {groups.length === 0 && effectiveCid ? (
              <Text style={styles.inheritHintSm}>No groups defined for this firm</Text>
            ) : null}
          </View>
        </View>

        {/* Iter 101 — visible Sort control (column headers are also tappable) */}
        <View style={styles.groupBox}>
          <Text style={styles.rangeLabel}>Sort</Text>
          <View style={styles.groupChipsRow}>
            {([["code", "Code"], ["name", "Name"], ["days", "Days"], ["duty", "Duty HRS"], ["ot", "OT HRS"]] as const).map(([col, lab]) => (
              <Pressable
                key={col}
                onPress={() => toggleSort(col as any)}
                style={[styles.groupChip, sortBy === col && styles.groupChipOn]}
                testID={`sort-${col}`}
              >
                <Text style={[styles.groupChipTxt, sortBy === col && styles.groupChipTxtOn]}>
                  {lab}{sortBy === col ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>

        <View style={{ flex: 1 }} />

        {/* Iter 94 — Hide/Show the 1–31 day columns (summary-only view) */}
        <Pressable
          onPress={() => setHideDays((h) => !h)}
          style={[styles.groupChip, hideDays && styles.groupChipOn]}
          testID="toggle-hide-days"
        >
          <Ionicons
            name={hideDays ? "eye-off-outline" : "eye-outline"}
            size={13}
            color={hideDays ? "#fff" : colors.onSurfaceSecondary}
          />
          <Text style={[styles.groupChipTxt, hideDays && styles.groupChipTxtOn]}>
            {hideDays ? "Show Days 1–31" : "Hide Days 1–31"}
          </Text>
        </Pressable>

        {/* Source badge legend */}
        <View style={styles.legendRow}>
          <View style={styles.legendItem}>
            <View style={[styles.badge, styles.badgeBio]}><Text style={styles.badgeTxt}>B</Text></View>
            <Text style={styles.legendTxt}>Biometric</Text>
          </View>
          <View style={styles.legendItem}>
            <View style={[styles.badge, styles.badgeApp]}><Text style={styles.badgeTxt}>M</Text></View>
            <Text style={styles.legendTxt}>Mobile</Text>
          </View>
          <View style={styles.legendItem}>
            <View style={[styles.badge, styles.badgeSys]}><Text style={styles.badgeTxt}>S</Text></View>
            <Text style={styles.legendTxt}>System</Text>
          </View>
        </View>
      </View>

      {/* Body */}
      {!effectiveCid ? (
        <View style={styles.emptyCard}>
          <Ionicons name="business-outline" size={32} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyTitle}>Pick a firm</Text>
          <Text style={styles.emptyBody}>Monthly attendance is per firm — select one above.</Text>
        </View>
      ) : loading ? (
        <View style={{ padding: 48, alignItems: "center" }}>
          <ActivityIndicator color={colors.brand} size="large" />
        </View>
      ) : err ? (
        <View style={styles.errBox}>
          <Ionicons name="alert-circle" size={16} color={colors.error} />
          <Text style={styles.errText}>{err}</Text>
        </View>
      ) : !data ? null : filteredEmployees.length === 0 ? (
        <View style={styles.emptyCard}>
          <Text style={styles.emptyTitle}>No employees match</Text>
          <Text style={styles.emptyBody}>Try clearing the search or picking a different month.</Text>
        </View>
      ) : (
        <ScrollView horizontal style={{ flex: 1 }} showsHorizontalScrollIndicator>
          <ScrollView showsVerticalScrollIndicator>
            <View style={styles.gridRoot}>
              <GridHeader
                data={data}
                view={view}
                hideDays={hideDays}
                sortBy={sortBy}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              {filteredEmployees.map((e, idx) => (
                <GridRow
                  key={e.user_id}
                  emp={e}
                  data={data}
                  view={view}
                  hideDays={hideDays}
                  zebra={idx % 2 === 1}
                />
              ))}
            </View>
          </ScrollView>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Grid header / row
// ---------------------------------------------------------------------------
const COL = {
  code: 62,
  name: 190,
  dept: 110,
  bio: 60,
  day: 66,
  dayHours: 46,
  daySal: 58,
  sum: 62,
};

function GridHeader({
  data,
  view,
  hideDays,
  sortBy,
  sortDir,
  onSort,
}: {
  data: GridResp;
  view: GridView;
  hideDays?: boolean;
  sortBy?: "code" | "name" | "dept" | "bio" | "days" | "hours" | "ot" | "duty";
  sortDir?: "asc" | "desc";
  onSort?: (col: "code" | "name" | "dept" | "bio" | "days" | "hours" | "ot" | "duty") => void;
}) {
  const dayW =
    view === "inout" || view === "inout_salary"
      ? COL.day
      : view === "salary"
        ? COL.daySal
        : COL.dayHours;
  const arrow = (col: string) =>
    sortBy === col ? (sortDir === "asc" ? " ▲" : " ▼") : "";
  const tap = (col: "code" | "name" | "dept" | "bio" | "days" | "hours" | "ot" | "duty") => () => {
    if (onSort) onSort(col);
  };
  return (
    <View style={styles.headerRow}>
      <Pressable
        onPress={tap("code")}
        style={[styles.hcell, { width: COL.code }]}
      >
        <Text style={styles.hcellTxt}>Code{arrow("code")}</Text>
      </Pressable>
      <Pressable
        onPress={tap("name")}
        style={[styles.hcell, { width: COL.name }]}
      >
        <Text style={styles.hcellTxt}>Name{arrow("name")}</Text>
      </Pressable>
      <Pressable
        onPress={tap("dept")}
        style={[styles.hcell, { width: COL.dept }]}
      >
        <Text style={styles.hcellTxt}>Designation{arrow("dept")}</Text>
      </Pressable>
      <Pressable
        onPress={tap("bio")}
        style={[styles.hcell, { width: COL.bio }]}
      >
        <Text style={styles.hcellTxt}>Bio{arrow("bio")}</Text>
      </Pressable>
      {hideDays ? null : data.day_labels.map((d, i) => (
        <View key={d} style={[styles.hcell, { width: dayW, alignItems: "center" }]}>
          <Text style={styles.hcellDay}>{d}</Text>
          <Text style={styles.hcellDayLabel}>{data.weekday_labels[i]}</Text>
        </View>
      ))}
      {/* Iter 77s — Column order per user request:
          Total HRS | OT HRS | Total Duty HRS | Days */}
      {hideDays ? null : (
        <Pressable
          onPress={tap("hours")}
          style={[styles.hcell, styles.sumCell, { width: COL.sum }]}
        >
          <Text style={styles.hcellTxt}>Duty HRS{arrow("hours")}</Text>
        </Pressable>
      )}
      <Pressable
        onPress={tap("ot")}
        style={[styles.hcell, styles.sumCell, { width: COL.sum }]}
      >
        <Text style={styles.hcellTxt}>OT HRS{arrow("ot")}</Text>
      </Pressable>
      <Pressable
        onPress={tap("duty")}
        style={[styles.hcell, styles.sumCell, { width: COL.sum }]}
      >
        <Text style={styles.hcellTxt}>Total Duty HRS{arrow("duty")}</Text>
      </Pressable>
      <Pressable
        onPress={tap("days")}
        style={[styles.hcell, styles.sumCell, { width: COL.sum }]}
      >
        <Text style={styles.hcellTxt}>Days{arrow("days")}</Text>
      </Pressable>
      {/* Iter 83 — Extra HRS column: remainder of (Total Duty HRS mod Daily HRS). */}
      <View style={[styles.hcell, styles.sumCell, { width: COL.sum }]}>
        <Text style={styles.hcellTxt}>Extra HRS</Text>
      </View>
    </View>
  );
}

function GridRow({
  emp,
  data,
  view,
  hideDays,
  zebra,
}: {
  emp: EmpRow;
  data: GridResp;
  view: GridView;
  hideDays?: boolean;
  zebra: boolean;
}) {
  const dayW =
    view === "inout" || view === "inout_salary"
      ? COL.day
      : view === "salary"
        ? COL.daySal
        : COL.dayHours;
  return (
    <View style={[styles.row, zebra && styles.rowZebra]}>
      <View style={[styles.cell, { width: COL.code }]}>
        <Text style={styles.codeTxt}>{emp.employee_code || "—"}</Text>
      </View>
      <View style={[styles.cell, { width: COL.name }]}>
        <Text style={styles.nameTxt} numberOfLines={1}>{emp.name}</Text>
        {emp.employee_group ? (
          <Text style={styles.subTxt} numberOfLines={1}>{emp.employee_group}</Text>
        ) : null}
      </View>
      <View style={[styles.cell, { width: COL.dept }]}>
        <Text style={styles.deptTxt} numberOfLines={1}>{emp.designation || emp.position || "—"}</Text>
      </View>
      <View style={[styles.cell, { width: COL.bio }]}>
        <Text style={styles.bioTxt}>
          {emp.bio_code !== null && emp.bio_code !== undefined ? String(emp.bio_code) : "—"}
        </Text>
      </View>
      {hideDays ? null : data.day_labels.map((d) => {
        const cell = emp.days[d];
        return (
          <DayCell key={d} cell={cell} view={view} width={dayW} fullDay={data.full_day_hours} />
        );
      })}
      {/* User rule (Iter 83): Total HRS = Regular Duty only, OT HRS = OT total,
          Total Duty HRS = Total + OT combined, Days = present days. */}
      {hideDays ? null : (
        <View style={[styles.cell, styles.sumCellLight, { width: COL.sum }]}>
          <Text style={styles.sumTxt}>
            {fmtHoursHM((emp.totals as any).duty_hours ?? 0)}
          </Text>
        </View>
      )}
      <View style={[styles.cell, styles.sumCellLight, { width: COL.sum }]}>
        <Text style={[styles.sumTxt, emp.totals.ot_hours > 0 && { color: colors.accent }]}>
          {fmtHoursHM(emp.totals.ot_hours)}
        </Text>
      </View>
      <View style={[styles.cell, styles.sumCellLight, { width: COL.sum }]}>
        <Text style={styles.sumTxt}>
          {fmtHoursHM(emp.totals.hours)}
        </Text>
      </View>
      <View style={[styles.cell, styles.sumCellLight, { width: COL.sum }]}>
        <Text style={styles.sumTxt}>
          {typeof (emp.totals as any).total_days_int === "number"
            ? (emp.totals as any).total_days_int
            : emp.totals.present_days}
        </Text>
      </View>
      {/* Iter 83 — Extra HRS (fractional part of days × daily hrs). */}
      <View style={[styles.cell, styles.sumCellLight, { width: COL.sum }]}>
        <Text style={styles.sumTxt}>
          {fmtHoursHM((emp.totals as any).total_extra_hrs ?? 0)}
        </Text>
      </View>
    </View>
  );
}

function DayCell({
  cell,
  view,
  width,
  fullDay,
}: {
  cell: Cell | undefined;
  view: GridView;
  width: number;
  fullDay: number;
}) {
  // Iter 77e - Pick the right hours source per view:
  //   * IN/OUT view      -> raw_hours (actual worked, unadjusted)
  //   * OT view (77l)    -> ot_hours  (OT only; empty cell if none)
  //   * Total-Duty view  -> hours     (POLICY-ADJUSTED, capped per shift)
  //                        OT is ALWAYS merged into this total.
  const displayHours =
    view === "hours"
      ? (cell?.hours ?? 0)
      : view === "ot"
      ? (cell?.ot_hours ?? 0)
      : ((cell?.raw_hours ?? cell?.hours) ?? 0);
  // Iter 94 — user rules:
  //  • "⚠ rectify" ONLY when a punch is genuinely one-sided (IN xor OUT).
  //    Both punches present must NEVER show an error even if computed
  //    hours are 0.
  //  • Any missing punch (IN / OUT / both) → HRS stays BLANK everywhere.
  const hasIn = Boolean(cell?.in);
  const hasOut = Boolean(cell?.out);
  const oneSided = hasIn !== hasOut;
  if (!cell || (!hasIn && !hasOut)) {
    return (
      <View style={[styles.cell, styles.dayCellEmpty, { width }]}>
        <Text style={styles.dayEmpty}>·</Text>
      </View>
    );
  }
  if (oneSided) {
    // Missing partner punch → amber indicator, HRS/salary blank.
    if (view === "hours" || view === "salary") {
      // Blank cell (faint amber tint so the admin can spot it).
      return (
        <View
          style={[
            styles.cell,
            { width, backgroundColor: "rgba(245,158,11,0.10)" },
          ]}
        />
      );
    }
    return (
      <View
        style={[
          styles.cell,
          {
            width,
            alignItems: "center",
            paddingVertical: 4,
            backgroundColor: "rgba(245,158,11,0.12)",
          },
        ]}
      >
        <Text style={[styles.dayIn, hasIn ? null : { color: colors.onSurfaceTertiary }]}>
          {cell.in || "— missing IN —"}
        </Text>
        <Text style={[styles.dayOut, hasOut ? null : { color: colors.onSurfaceTertiary }]}>
          {cell.out || "— missing OUT —"}
        </Text>
        <Text style={[styles.dayHoursSm, { color: "#b45309", fontWeight: "800" }]}>
          ⚠ rectify
        </Text>
      </View>
    );
  }
  const isOt = displayHours > fullDay;
  // Iter 94 — Per-Day Salary report: single ₹ figure per day.
  if (view === "salary") {
    return (
      <View style={[styles.cell, { width, alignItems: "center", justifyContent: "center" }]}>
        <Text style={{ fontSize: 9.5, color: "#15803D", fontWeight: "800" }}>
          {fmtRsCell(cell.salary)}
        </Text>
      </View>
    );
  }
  // Iter 94 — In/Out WITH Salary report: punches + day salary line.
  // Iter 95 — also surface OT data (OT window + OT HRS) per user request.
  if (view === "inout_salary") {
    const otH = cell.ot_hours || 0;
    return (
      <View style={[styles.cell, { width, alignItems: "center", paddingVertical: 4 }]}>
        <Text style={styles.dayIn}>{cell.in || "—"}</Text>
        <Text style={styles.dayOut}>{cell.out || "—"}</Text>
        {otH > 0 && (
          <Text style={{ fontSize: 8, color: colors.accent, fontWeight: "800" }}>
            OT {cell.ot_in || "—"}–{cell.ot_out || "—"} · {fmtHoursHM(otH)}
          </Text>
        )}
        <Text style={{ fontSize: 8.5, color: "#15803D", fontWeight: "800" }}>
          {fmtRsCell(cell.salary)}
        </Text>
      </View>
    );
  }
  if (view === "hours") {
    // Total-Duty view - single number (OT already merged in).
    return (
      <View style={[styles.cell, { width, alignItems: "center", justifyContent: "center" }]}>
        <Text style={[styles.dayHours, isOt && styles.dayHoursOt]}>
          {displayHours > 0 ? fmtHoursHM(displayHours) : "—"}
        </Text>
      </View>
    );
  }
  if (view === "ot") {
    // Iter 77l — OT IN/OUT view. Days with punches but no OT show a dot.
    if (displayHours === 0) {
      return (
        <View style={[styles.cell, styles.dayCellEmpty, { width }]}>
          <Text style={styles.dayEmpty}>·</Text>
        </View>
      );
    }
    return (
      <View style={[styles.cell, { width, alignItems: "center", paddingVertical: 4 }]}>
        <Text style={[styles.dayIn, { color: colors.accent }]}>{cell.ot_in || "—"}</Text>
        <Text style={[styles.dayOut, { color: colors.accent }]}>{cell.ot_out || "—"}</Text>
        <Text style={[styles.dayHoursSm, { color: colors.accent, fontWeight: "800" }]}>
          {fmtHoursHM(displayHours)}
        </Text>
      </View>
    );
  }
  // Iter 77h — IN/OUT view: compact 2-line In/Out + total hrs.
  return (
    <View style={[styles.cell, { width, alignItems: "center", paddingVertical: 4 }]}>
      <Text style={styles.dayIn}>{cell.in || "—"}</Text>
      <Text style={styles.dayOut}>{cell.out || "—"}</Text>
      <Text style={[styles.dayHoursSm, isOt && styles.dayHoursOt]}>
        {displayHours > 0 ? fmtHoursHM(displayHours) : "—"}
      </Text>
      {cell.sources && cell.sources.length > 0 && (
        <View style={styles.badgeRow}>
          {cell.sources.map((s) => (
            <View key={s} style={[styles.badge, s === "bio" ? styles.badgeBio : s === "app" ? styles.badgeApp : styles.badgeSys]}>
              <Text style={styles.badgeTxt}>{s === "bio" ? "B" : s === "app" ? "M" : "S"}</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.surface },
  centerScreen: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.lg,
    gap: spacing.sm,
    backgroundColor: colors.surface,
  },
  errTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  retryBtn: {
    marginTop: spacing.md,
    backgroundColor: colors.brand,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
  },
  retryBtnTxt: { color: colors.onBrandPrimary, fontWeight: "700" },

  toolbar: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  iconBtn: { width: 34, height: 34, alignItems: "center", justifyContent: "center" },
  title: { fontSize: type.h2, fontWeight: "800", color: colors.onSurface },
  subtitle: { color: colors.onSurfaceSecondary, marginTop: 2, fontSize: type.sm },
  firmPicker: { minWidth: 200 },

  controls: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    padding: spacing.md,
    flexWrap: "wrap",
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  chevBtn: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  monthInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 8,
    paddingHorizontal: spacing.md,
    minWidth: 110,
    color: colors.onSurface,
    ...Platform.select({ web: { outlineWidth: 0 as any } }),
  },
  segment: {
    flexDirection: "row",
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  segmentBtn: { paddingHorizontal: 12, paddingVertical: 8 },
  segmentBtnOn: { backgroundColor: colors.brand },
  segmentTxt: { color: colors.onSurface, fontWeight: "600", fontSize: type.sm },
  segmentTxtOn: { color: colors.onBrandPrimary },

  searchInput: {
    flex: 1,
    minWidth: 200,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 8,
    paddingHorizontal: spacing.md,
    color: colors.onSurface,
    backgroundColor: colors.surface,
    ...Platform.select({ web: { outlineWidth: 0 as any } }),
  },
  exportBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.cta,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: radius.pill,
    ...shadow.cta,
  },
  exportBtnPdf: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#8B1A1A",
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: radius.pill,
  },
  // Iter 93 — Refresh biometric (re-map unmapped punches) button
  refreshBioBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#0E7490",
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: radius.pill,
  },
  // Iter 77i — OT Report button (secondary accent colour)
  exportBtnOt: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.accent,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: radius.pill,
  },
  exportBtnTxt: { color: colors.onCta, fontWeight: "700", fontSize: type.sm },

  // Iter 77 - Sub-controls (Date range + Legend)
  subControls: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    flexWrap: "wrap",
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surfaceSecondary,
  },
  rangeLabel: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "600",
  },
  dateInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 6,
    paddingHorizontal: 10,
    minWidth: 140,
    color: colors.onSurface,
    backgroundColor: colors.surface,
    fontSize: type.sm,
    ...Platform.select({ web: { outlineWidth: 0 as any } }),
  },
  dateInputErr: {
    borderColor: colors.error,
    backgroundColor: "rgba(220, 38, 38, 0.05)",
  },
  rangeDash: { color: colors.onSurfaceSecondary, fontWeight: "700" },
  clearRangeBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingVertical: 4,
    paddingHorizontal: 8,
    borderRadius: radius.pill,
  },
  clearRangeTxt: { color: colors.onSurfaceSecondary, fontSize: type.sm },
  rangePill: {
    backgroundColor: colors.brand,
    paddingVertical: 3,
    paddingHorizontal: 10,
    borderRadius: radius.pill,
  },
  rangePillTxt: { color: colors.onBrandPrimary, fontSize: 11, fontWeight: "700" },
  legendRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  legendTxt: { color: colors.onSurfaceSecondary, fontSize: 11 },
  // Iter 77 - Group Wise filter
  groupBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    flexWrap: "wrap",
    marginLeft: 8,
  },
  groupChipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 4 },
  groupChip: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  groupChipOn: {
    backgroundColor: colors.brand,
    borderColor: colors.brand,
  },
  groupChipTxt: { color: colors.onSurface, fontSize: 11, fontWeight: "600" },
  groupChipTxtOn: { color: "#fff" },
  inheritHintSm: { color: colors.onSurfaceTertiary, fontSize: 11, fontStyle: "italic" },

  emptyCard: {
    margin: spacing.lg,
    padding: spacing.xl,
    borderRadius: radius.lg,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  emptyTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  emptyBody: { color: colors.onSurfaceSecondary, textAlign: "center" },
  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FEE2E2",
    padding: spacing.sm,
    borderRadius: radius.md,
    margin: spacing.md,
  },
  errText: { color: colors.error, flex: 1 },

  // Grid ------------------------------------------------------------------
  gridRoot: { padding: 8 },
  headerRow: {
    flexDirection: "row",
    backgroundColor: colors.brandPrimary,
    borderTopLeftRadius: 6,
    borderTopRightRadius: 6,
  },
  hcell: {
    paddingVertical: 8,
    paddingHorizontal: 6,
    borderRightWidth: 1,
    borderRightColor: "rgba(255,255,255,0.15)",
    justifyContent: "center",
  },
  hcellTxt: { color: "#fff", fontWeight: "700", fontSize: 11, letterSpacing: 0.4 },
  hcellDay: { color: "#fff", fontWeight: "700", fontSize: 12 },
  hcellDayLabel: { color: "rgba(255,255,255,0.75)", fontSize: 9, marginTop: 1 },
  sumCell: { backgroundColor: colors.brandSecondary || colors.brandPrimary, alignItems: "center" },
  // Iter 114 — body Total columns highlighted with a LIGHT tint (user rule).
  sumCellLight: { backgroundColor: "#E9F5F0", alignItems: "center" },

  row: {
    flexDirection: "row",
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  rowZebra: { backgroundColor: colors.surfaceSecondary },
  cell: {
    paddingVertical: 4,
    paddingHorizontal: 6,
    borderRightWidth: 1,
    borderRightColor: colors.divider,
    justifyContent: "center",
  },
  codeTxt: { color: colors.onSurface, fontWeight: "700", fontSize: 11 },
  nameTxt: { color: colors.onSurface, fontWeight: "600", fontSize: 12 },
  subTxt: { color: colors.onSurfaceTertiary, fontSize: 10, marginTop: 1 },
  deptTxt: { color: colors.onSurfaceSecondary, fontSize: 11 },
  bioTxt: { color: colors.onSurface, fontWeight: "700", fontSize: 11, textAlign: "center" },
  dayCellEmpty: { alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  dayEmpty: { color: colors.onSurfaceTertiary, fontSize: 14 },
  dayIn: { color: colors.success || "#0F5132", fontWeight: "700", fontSize: 10 },
  dayOut: { color: colors.error || "#8A1F1F", fontWeight: "700", fontSize: 10 },
  dayHoursSm: { color: colors.onSurface, fontSize: 10, marginTop: 1 },
  dayHours: { color: colors.onSurface, fontWeight: "700", fontSize: 12 },
  dayHoursOt: { color: colors.accent, fontWeight: "800" },
  // Iter 77g — OT tag (small pill under total hrs) + 4-row IN/OUT layout
  dayOtTag: {
    color: colors.accent, fontWeight: "800", fontSize: 9,
    marginTop: 1,
  },
  dayOtTagSm: {
    color: colors.accent, fontWeight: "700", fontSize: 9,
  },
  inoutRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 2,
  },
  inoutLbl: {
    color: colors.onSurfaceSecondary, fontSize: 8, fontWeight: "700",
    minWidth: 22,
  },
  inoutLblOt: { color: colors.accent },
  inoutVal: {
    color: colors.onSurface, fontSize: 9, fontWeight: "700",
    flex: 1, textAlign: "right",
  },
  inoutValOt: { color: colors.accent, fontWeight: "800" },
  inoutHrsRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 4, marginTop: 2,
  },
  sumTxt: { color: colors.onSurface, fontWeight: "700", fontSize: 11, textAlign: "center" },
  // Iter 77 - Source provenance badges (Mobile "M" / Biometric "B" / System "S")
  badgeRow: {
    flexDirection: "row",
    marginTop: 2,
    gap: 2,
    justifyContent: "center",
  },
  badge: {
    width: 12,
    height: 12,
    borderRadius: 3,
    alignItems: "center",
    justifyContent: "center",
  },
  badgeBio: { backgroundColor: "#1F5254" },
  badgeApp: { backgroundColor: "#2563EB" },
  badgeSys: { backgroundColor: "#6B7280" },
  badgeTxt: { color: "#fff", fontSize: 7, fontWeight: "700" },
});
