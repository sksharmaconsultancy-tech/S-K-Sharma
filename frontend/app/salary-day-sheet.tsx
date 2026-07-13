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
  ScrollView,
  TextInput,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
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

const W = {
  date: 74, code: 52, name: 160, desig: 104,
  t: 58, hrs: 58, salary: 88,
};

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

  const HDR: { w: number; txt: string }[] = [
    { w: W.code, txt: "Code" },
    { w: W.name, txt: "Name" },
    { w: W.desig, txt: "Designation" },
    { w: W.date, txt: "Date" },
    { w: W.t, txt: "In Punch" },
    { w: W.t, txt: "Out Punch" },
    { w: W.hrs, txt: "Duty HRS" },
    { w: W.t, txt: "OT In" },
    { w: W.t, txt: "OT Out" },
    { w: W.hrs, txt: "OT HRS" },
    { w: W.hrs, txt: "Total HRS" },
    { w: W.salary, txt: "Day Salary" },
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
        {/* Iter 95 — date selection + Show button (user request) */}
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
        <Pressable style={styles.showBtn} onPress={onShow} testID="sds-show">
          <Ionicons name="eye" size={14} color="#fff" />
          <Text style={styles.showTxt}>Show</Text>
        </Pressable>
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
        <ScrollView contentContainerStyle={{ padding: spacing.md }}>
          <ScrollView horizontal showsHorizontalScrollIndicator>
            <View>
              {/* Header */}
              <View style={styles.hdrRow}>
                {HDR.map((c) => (
                  <Text key={c.txt} style={[styles.hdrCell, { width: c.w }]}>{c.txt}</Text>
                ))}
              </View>
              {rows.length === 0 ? (
                <Text style={styles.emptyTxt}>No attendance / salary data for {month}.</Text>
              ) : (
                rows.map((r, i) => (
                  <View key={r.key} style={[styles.row, i % 2 === 0 && styles.rowAlt]}>
                    <Text style={[styles.cell, { width: W.code }]}>{r.emp.employee_code || "—"}</Text>
                    <Text style={[styles.cell, { width: W.name, fontWeight: "600" }]} numberOfLines={1}>
                      {r.emp.name}
                    </Text>
                    <Text style={[styles.cell, { width: W.desig }]} numberOfLines={1}>
                      {r.emp.designation || "—"}
                    </Text>
                    <Text style={[styles.cell, { width: W.date }]}>
                      {r.dateFull
                        ? `${r.dateFull.slice(8, 10)}-${r.dateFull.slice(5, 7)}`
                        : `${r.date}/${month.slice(5, 7)}`}
                    </Text>
                    <Text style={[styles.cell, { width: W.t }]}>{r.cell.in || "—"}</Text>
                    <Text style={[styles.cell, { width: W.t }]}>{r.cell.out || "—"}</Text>
                    <Text style={[styles.cell, styles.num, { width: W.hrs }]}>{fmtH(r.cell.duty_hours)}</Text>
                    <Text style={[styles.cell, { width: W.t, color: colors.accent }]}>{r.cell.ot_in || "—"}</Text>
                    <Text style={[styles.cell, { width: W.t, color: colors.accent }]}>{r.cell.ot_out || "—"}</Text>
                    <Text style={[styles.cell, styles.num, { width: W.hrs, color: (r.cell.ot_hours || 0) > 0 ? colors.accent : colors.onSurfaceTertiary }]}>
                      {fmtH(r.cell.ot_hours)}
                    </Text>
                    <Text style={[styles.cell, styles.num, { width: W.hrs, fontWeight: "700" }]}>
                      {fmtH(r.cell.hours)}
                    </Text>
                    <Text style={[styles.cell, styles.num, { width: W.salary, color: "#15803D", fontWeight: "800" }]}>
                      {fmtRs(r.cell.salary)}
                    </Text>
                  </View>
                ))
              )}
              {/* BOTTOM — grand totals */}
              <View style={[styles.row, styles.totalRow]} testID="sds-total-row">
                <Text style={[styles.cell, { width: W.code + W.name + W.desig + W.date, fontWeight: "900", color: "#15803D" }]}>
                  TOTAL ({rows.length} rows)
                </Text>
                <Text style={[styles.cell, { width: W.t * 2 }]} />
                <Text style={[styles.cell, styles.num, { width: W.hrs, fontWeight: "800" }]}>{fmtH(totals.duty)}</Text>
                <Text style={[styles.cell, { width: W.t * 2 }]} />
                <Text style={[styles.cell, styles.num, { width: W.hrs, fontWeight: "800", color: colors.accent }]}>{fmtH(totals.ot)}</Text>
                <Text style={[styles.cell, styles.num, { width: W.hrs, fontWeight: "800" }]}>{fmtH(totals.total)}</Text>
                <Text style={[styles.cell, styles.num, { width: W.salary, fontWeight: "900", color: "#15803D" }]}>
                  {fmtRs(totals.salary)}
                </Text>
              </View>
            </View>
          </ScrollView>
          <View style={{ height: 40 }} />
        </ScrollView>
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
