/**
 * Iter 94 — Day-wise Salary Sheet (SEPARATE report, per user request).
 *
 * Rows = employee × day. Columns:
 *   In Punch | Out Punch | Duty HRS | OT In | OT Out | OT HRS |
 *   Total HRS | Salary for that day
 * Grand total of salary shown at the BOTTOM of the sheet.
 *
 * Data source: GET /api/admin/attendance/monthly-grid/{cid}/{month}
 * (per-day cells already carry duty/ot/total hours + `salary`).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  TextInput,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api/client";
import ReportTable, { ReportCol } from "@/src/components/ReportTable";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import WebDateField from "@/src/components/WebDateField";
import { colors, radius, spacing, type } from "@/src/theme";

type Cell = {
  in: string | null;
  out: string | null;
  ot_in?: string | null;
  ot_out?: string | null;
  hours: number;        // duty + OT combined (Total HRS)
  duty_hours?: number;  // duty only
  ot_hours?: number;
  salary?: number;
};

type EmpRow = {
  user_id: string;
  name: string;
  employee_code?: string | null;
  father_name?: string | null;
  designation?: string | null;
  days: Record<string, Cell>;
  totals: { salary_total?: number };
};

type GridResp = {
  month: string;
  day_labels: string[];
  day_full_dates?: string[];
  employees: EmpRow[];
  salary_grand_total?: number;
};

const fmtRs = (n?: number | null): string =>
  n && n > 0 ? `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : "—";

// Iter 95 — HRS always in TIME format (HH:MM), never decimals.
const fmtH = (n?: number | null): string => {
  if (!n || n <= 0) return "—";
  const totalMin = Math.round(n * 60);
  const h = Math.floor(totalMin / 60);
  const mm = totalMin % 60;
  return `${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
};

const thisMonth = (): string => new Date().toISOString().slice(0, 7);

// Iter 95 — DD-MM-YYYY date input helpers (mirrors attendance-grid).
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

function shiftMonth(m: string, delta: number): string {
  const [y, mo] = m.split("-").map(Number);
  const d = new Date(y, mo - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function SalaryDaySheetScreen() {
  const insets = useSafeAreaInsets();
  const { selectedCompanyId, selectedCompany } = useSelectedCompany();
  const [month, setMonth] = useState<string>(thisMonth());
  const [data, setData] = useState<GridResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  // Iter 95 — user-requested date selection + explicit "Show" button.
  // Inputs display DD-MM-YYYY; range is APPLIED only when Show is pressed.
  // Iter 291 — explicit Single Day mode (user request).
  const [rangeMode, setRangeMode] = useState<"month" | "day" | "range">("month");
  const [singleDay, setSingleDay] = useState<string>(""); // ISO YYYY-MM-DD
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const [applied, setApplied] = useState<{ from: string; to: string } | null>(null);

  const load = useCallback(async () => {
    if (!selectedCompanyId) {
      setData(null);
      setError("Pick a firm first (top-right selector).");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const qs = applied
        ? `?from_date=${encodeURIComponent(applied.from)}&to_date=${encodeURIComponent(applied.to)}`
        : "";
      const r = await api<GridResp>(
        `/admin/attendance/monthly-grid/${selectedCompanyId}/${month}${qs}`,
      );
      setData(r);
    } catch (e: any) {
      setError(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [selectedCompanyId, month, applied]);

  useEffect(() => { load(); }, [load]);

  // Iter 95 — "Show" pressed: validate dates and apply the range.
  const onShow = () => {
    // Iter 291 — Single Day mode: one calendar date → that day only.
    if (rangeMode === "day") {
      if (!singleDay) { setApplied(null); return; }
      setApplied({ from: singleDay, to: singleDay });
      return;
    }
    const fromIso = ddmmyyyyToIso(fromDate);
    const toIso = ddmmyyyyToIso(toDate);
    if (!fromIso && !toIso) {
      // No dates typed → clear range, back to full month.
      setApplied(null);
      return;
    }
    // Single date → show just that day.
    const f = fromIso || toIso;
    const t = toIso || fromIso;
    setApplied({ from: f <= t ? f : t, to: f <= t ? t : f });
  };

  // Flatten employee × day rows (only days that have any punch/hours).
  const rows = useMemo(() => {
    if (!data) return [] as {
      key: string; date: string; dateFull?: string; emp: EmpRow; cell: Cell;
    }[];
    const q = search.trim().toLowerCase();
    const out: { key: string; date: string; dateFull?: string; emp: EmpRow; cell: Cell }[] = [];
    for (const emp of data.employees) {
      if (q && !(
        (emp.name || "").toLowerCase().includes(q) ||
        String(emp.employee_code || "").toLowerCase().includes(q)
      )) continue;
      for (let idx = 0; idx < data.day_labels.length; idx++) {
        const d = data.day_labels[idx];
        const cell = emp.days?.[d];
        if (!cell) continue;
        if (!cell.in && !cell.out && !(cell.hours > 0)) continue;
        out.push({
          key: `${emp.user_id}|${d}`,
          date: d,
          dateFull: data.day_full_dates?.[idx],
          emp,
          cell,
        });
      }
    }
    return out;
  }, [data, search]);

  const totals = useMemo(() => {
    let duty = 0, ot = 0, total = 0, salary = 0;
    for (const r of rows) {
      duty += r.cell.duty_hours || 0;
      ot += r.cell.ot_hours || 0;
      total += r.cell.hours || 0;
      salary += r.cell.salary || 0;
    }
    return { duty, ot, total, salary };
  }, [rows]);

  const HDR: ReportCol<any>[] = [
    { key: "code", label: "Code", type: "center", min: 60, sticky: true, value: (r) => r.emp.employee_code || "—" },
    { key: "name", label: "Name", min: 200, max: 300, sticky: true, value: (r) => r.emp.name || "", textStyle: () => ({ fontWeight: "600" }) },
    { key: "desig", label: "Designation", min: 110, max: 200, value: (r) => r.emp.designation || "—" },
    {
      key: "date", label: "Date", type: "date",
      value: (r) => r.dateFull
        ? `${r.dateFull.slice(8, 10)}-${r.dateFull.slice(5, 7)}`
        : `${r.date}/${month.slice(5, 7)}`,
    },
    { key: "in", label: "In Punch", type: "center", min: 72, value: (r) => r.cell.in || "—" },
    { key: "out", label: "Out Punch", type: "center", min: 76, value: (r) => r.cell.out || "—" },
    { key: "duty", label: "Duty HRS", type: "num", min: 80, value: (r) => fmtH(r.cell.duty_hours) },
    { key: "ot_in", label: "OT In", type: "center", min: 68, value: (r) => r.cell.ot_in || "—", textStyle: () => ({ color: colors.accent }) },
    { key: "ot_out", label: "OT Out", type: "center", min: 72, value: (r) => r.cell.ot_out || "—", textStyle: () => ({ color: colors.accent }) },
    {
      key: "ot", label: "OT HRS", type: "num", min: 72, value: (r) => fmtH(r.cell.ot_hours),
      textStyle: (r) => ({ color: (r.cell.ot_hours || 0) > 0 ? colors.accent : colors.onSurfaceTertiary }),
    },
    { key: "total", label: "Total HRS", type: "num", min: 84, value: (r) => fmtH(r.cell.hours), textStyle: () => ({ fontWeight: "700" }) },
    { key: "salary", label: "Day Salary", type: "num", min: 96, value: (r) => fmtRs(r.cell.salary), textStyle: () => ({ color: "#15803D", fontWeight: "800" }) },
  ];

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      {/* Toolbar */}
      <View style={styles.toolbar}>
        <Text style={styles.title}>Day-wise Salary Sheet</Text>
        {selectedCompany ? (
          <Text style={styles.firmTxt}>{selectedCompany.name}</Text>
        ) : null}
        <View style={{ flex: 1 }} />
        <Pressable style={styles.monthBtn} onPress={() => setMonth((m) => shiftMonth(m, -1))} testID="sds-prev">
          <Ionicons name="chevron-back" size={16} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.monthTxt}>{month}</Text>
        <Pressable style={styles.monthBtn} onPress={() => setMonth((m) => shiftMonth(m, 1))} testID="sds-next">
          <Ionicons name="chevron-forward" size={16} color={colors.onSurface} />
        </Pressable>
        {/* Iter 291 — Full Month / Single Day / Date Range mode (user request) */}
        <View style={styles.modeWrap}>
          {([["month", "Full Month"], ["day", "Single Day"], ["range", "Date Range"]] as const).map(([k, lab]) => (
            <Pressable
              key={k}
              onPress={() => {
                setRangeMode(k);
                if (k === "month") { setApplied(null); setSingleDay(""); setFromDate(""); setToDate(""); }
              }}
              style={[styles.modeBtn, rangeMode === k && styles.modeBtnOn]}
              testID={`sds-mode-${k}`}
            >
              <Text style={[styles.modeTxt, rangeMode === k && styles.modeTxtOn]}>{lab}</Text>
            </Pressable>
          ))}
        </View>
        {rangeMode === "day" ? (
          <View style={{ width: 170 }}>
            <WebDateField value={singleDay} onChange={setSingleDay} testID="sds-single-day" />
          </View>
        ) : null}
        {/* Iter 95 — date selection + Show button (user request) */}
        {rangeMode === "range" ? (
          <>
        <TextInput
          style={styles.dateInput}
          value={fromDate}
          onChangeText={(v) => setFromDate(formatDdmmyyyyInput(v))}
          placeholder="From DD-MM-YYYY"
          placeholderTextColor={colors.onSurfaceTertiary}
          keyboardType="numeric"
          maxLength={10}
          testID="sds-from-date"
        />
        <TextInput
          style={styles.dateInput}
          value={toDate}
          onChangeText={(v) => setToDate(formatDdmmyyyyInput(v))}
          placeholder="To DD-MM-YYYY"
          placeholderTextColor={colors.onSurfaceTertiary}
          keyboardType="numeric"
          maxLength={10}
          testID="sds-to-date"
        />
          </>
        ) : null}
        {rangeMode !== "month" ? (
        <Pressable style={styles.showBtn} onPress={onShow} testID="sds-show">
          <Ionicons name="eye" size={14} color="#fff" />
          <Text style={styles.showTxt}>Show</Text>
        </Pressable>
        ) : null}
        {applied ? (
          <Pressable
            style={styles.clearBtn}
            onPress={() => { setApplied(null); setFromDate(""); setToDate(""); }}
            testID="sds-clear-range"
          >
            <Ionicons name="close" size={12} color={colors.onSurfaceSecondary} />
            <Text style={styles.clearTxt}>
              {`${applied.from.slice(8, 10)}-${applied.from.slice(5, 7)}`}
              {applied.from !== applied.to
                ? ` → ${applied.to.slice(8, 10)}-${applied.to.slice(5, 7)}`
                : ""}
            </Text>
          </Pressable>
        ) : null}
        <TextInput
          style={styles.search}
          value={search}
          onChangeText={setSearch}
          placeholder="Search name / code…"
          placeholderTextColor={colors.onSurfaceTertiary}
          testID="sds-search"
        />
        <Pressable style={styles.reloadBtn} onPress={load} testID="sds-reload">
          <Ionicons name="refresh" size={15} color="#fff" />
        </Pressable>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : error ? (
        <View style={styles.center}>
          <Ionicons name="alert-circle" size={28} color={colors.error || "#B91C1C"} />
          <Text style={styles.errTxt}>{error}</Text>
          <Pressable style={styles.retryBtn} onPress={load}>
            <Text style={styles.retryTxt}>Retry</Text>
          </Pressable>
        </View>
      ) : (
        <View style={{ flex: 1, padding: spacing.md }}>
          {/* Iter 497 — Universal Report Table engine */}
          <ReportTable
            reportKey="salary_day_sheet"
            columns={HDR}
            rows={rows}
            emptyText={`No attendance / salary data for ${month}.`}
            pdfTitle={`Day-wise Salary Sheet — ${month}`}
            pdfSubtitle={selectedCompany?.name || ""}
            footer={{
              label: `TOTAL (${rows.length} rows)`,
              values: {
                code: " ",
                duty: fmtH(totals.duty),
                ot: fmtH(totals.ot),
                total: fmtH(totals.total),
                salary: fmtRs(totals.salary),
              },
            }}
          />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  toolbar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    flexWrap: "wrap",
  },
  title: { fontSize: type.md, fontWeight: "800", color: colors.onSurface },
  firmTxt: { fontSize: 11, color: colors.brandPrimary, fontWeight: "700" },
  monthBtn: {
    width: 30, height: 30, borderRadius: 6, borderWidth: 1,
    borderColor: colors.border, alignItems: "center", justifyContent: "center",
  },
  monthTxt: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  // Iter 291 — Full Month / Single Day / Date Range mode chips.
  modeWrap: {
    flexDirection: "row", borderWidth: 1, borderColor: colors.border,
    borderRadius: 8, overflow: "hidden",
  },
  modeBtn: { paddingHorizontal: 10, paddingVertical: 7, backgroundColor: colors.surface },
  modeBtnOn: { backgroundColor: colors.brandPrimary },
  modeTxt: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  modeTxtOn: { color: "#fff" },
  dateInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 8, paddingVertical: 6, fontSize: 11.5,
    color: colors.onSurface, width: 118, backgroundColor: colors.surface,
    fontVariant: ["tabular-nums"],
  },
  showBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: "#15803D", borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 8,
  },
  showTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  clearBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 8, paddingVertical: 6,
    backgroundColor: colors.surfaceSecondary,
  },
  clearTxt: { fontSize: 10.5, color: colors.onSurfaceSecondary, fontWeight: "700" },
  search: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 6, fontSize: 12,
    color: colors.onSurface, minWidth: 180, backgroundColor: colors.surface,
  },
  reloadBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 8,
  },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 10 },
  errTxt: { color: colors.onSurfaceSecondary, fontSize: 13, textAlign: "center", maxWidth: 420 },
  retryBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 22, paddingVertical: 9,
  },
  retryTxt: { color: "#fff", fontWeight: "800" },
  hdrRow: {
    flexDirection: "row",
    backgroundColor: "#0F2E3D",
    borderTopLeftRadius: 8,
    borderTopRightRadius: 8,
  },
  hdrCell: {
    color: "#fff", fontSize: 10.5, fontWeight: "800",
    paddingVertical: 9, paddingHorizontal: 6,
  },
  row: {
    flexDirection: "row",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
    alignItems: "center",
  },
  rowAlt: { backgroundColor: colors.surfaceSecondary },
  totalRow: { backgroundColor: "#F0FDF4", borderTopWidth: 2, borderTopColor: "#15803D" },
  cell: { fontSize: 11.5, color: colors.onSurface, paddingVertical: 8, paddingHorizontal: 6 },
  num: { textAlign: "right", fontVariant: ["tabular-nums"] },
  emptyTxt: {
    padding: 24, color: colors.onSurfaceTertiary, fontSize: 12,
    textAlign: "center", backgroundColor: colors.surface,
  },
});
