/**
 * OT Report — Iter 77i.
 *
 * Lists every (employee × day) where OT > 0 for the currently selected
 * firm + month. Supports:
 *   • Custom date range via ?from=YYYY-MM-DD&to=YYYY-MM-DD.
 *   • XLSX download via the sibling endpoint.
 *
 * Depends on the JSON endpoint at:
 *   GET /api/admin/attendance/ot-report/{company_id}/{month}
 * and the XLSX endpoint at:
 *   GET /api/admin/attendance/ot-report/{company_id}/{month}/xlsx
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Platform,
  Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api/client";
import { useLiveSync } from "@/src/api/live-sync";
import { colors, spacing, type as typeScale } from "@/src/theme";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";

type OTRow = {
  user_id: string;
  employee_code?: string | null;
  name?: string | null;
  designation?: string | null;
  bio_code?: string | number | null;
  date: string;
  day_label: string;
  in: string | null;
  out: string | null;
  ot_in?: string | null;
  ot_out?: string | null;
  duty_hours: number;
  ot_hours: number;
  total_hours: number;
};

type OTResp = {
  company: { company_id: string; name: string };
  month: string;
  from_date?: string | null;
  to_date?: string | null;
  count: number;
  rows: OTRow[];
};

function fmtHM(v?: number | null): string {
  if (!v || v <= 0) return "0:00";
  const totalMin = Math.round(v * 60);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return `${h}:${String(m).padStart(2, "0")}`;
}

// Iter 77m — tap-to-sort table header cell
function SortableTh<T extends string>({
  label,
  col,
  w,
  sortBy,
  sortDir,
  onSort,
}: {
  label: string;
  col: T;
  w: number;
  sortBy: T;
  sortDir: "asc" | "desc";
  onSort: (c: T) => void;
}) {
  const active = sortBy === col;
  return (
    <Pressable onPress={() => onSort(col)} style={{ width: w }}>
      <Text style={styles.th}>
        {label}
        {active ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
      </Text>
    </Pressable>
  );
}

function ymNow(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export default function OTReportScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{
    company_id?: string;
    month?: string;
    from?: string;
    to?: string;
  }>();
  const { selectedCompanyId } = useSelectedCompany();
  const cid = (params.company_id as string) || selectedCompanyId || "";

  const [month, setMonth] = useState<string>((params.month as string) || ymNow());
  const [data, setData] = useState<OTResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const load = useCallback(async () => {
    if (!cid) return;
    setLoading(true);
    setErr(null);
    try {
      const q = new URLSearchParams();
      if (params.from) q.set("from_date", String(params.from));
      if (params.to) q.set("to_date", String(params.to));
      const url =
        `/admin/attendance/ot-report/${encodeURIComponent(cid)}/${encodeURIComponent(month)}` +
        (q.toString() ? `?${q.toString()}` : "");
      const r = await api<OTResp>(url);
      setData(r);
    } catch (e: any) {
      setErr(e?.message || "Failed to load OT report");
    } finally {
      setLoading(false);
    }
  }, [cid, month, params.from, params.to]);

  useEffect(() => {
    load();
  }, [load]);

  // Iter 77n — live-sync: refetch OT rows when a punch changes for
  // this firm. Debounced to avoid hammering during bulk imports.
  const liveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useLiveSync(cid, (ev) => {
    if (!ev?.type) return;
    if (!(ev.type.startsWith("punch.") || ev.type === "attendance.dat-imported")) {
      return;
    }
    if (liveTimerRef.current) clearTimeout(liveTimerRef.current);
    liveTimerRef.current = setTimeout(() => load(), 1000);
  });
  useEffect(() => () => {
    if (liveTimerRef.current) clearTimeout(liveTimerRef.current);
  }, []);

  const downloadXlsx = async () => {
    if (!cid) return;
    setDownloading(true);
    try {
      const base = (process.env.EXPO_PUBLIC_API_URL as string) || "";
      const q = new URLSearchParams();
      if (params.from) q.set("from_date", String(params.from));
      if (params.to) q.set("to_date", String(params.to));
      const url =
        `${base}/api/admin/attendance/ot-report/${encodeURIComponent(cid)}/${encodeURIComponent(month)}/xlsx` +
        (q.toString() ? `?${q.toString()}` : "");
      if (Platform.OS === "web") {
        // Grab token from local storage (auth context stores it there)
        const token =
          (globalThis as any).localStorage?.getItem("auth:token") || "";
        const res = await fetch(url, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok) throw new Error(await res.text());
        const blob = await res.blob();
        const a = (globalThis as any).document.createElement("a");
        a.href = (globalThis as any).URL.createObjectURL(blob);
        a.download = `${data?.company?.name || "OT"}_OT_Report_${month}.xlsx`;
        (globalThis as any).document.body.appendChild(a);
        a.click();
        a.remove();
      } else {
        Alert.alert(
          "Download",
          "XLSX download is currently supported from the web portal only. Open the web app to save the file.",
        );
      }
    } catch (e: any) {
      Alert.alert("Download failed", e?.message || "Please try again.");
    } finally {
      setDownloading(false);
    }
  };

  const grandTotals = useMemo(() => {
    const rows = data?.rows || [];
    return {
      days: rows.length,
      duty: rows.reduce((s, r) => s + (r.duty_hours || 0), 0),
      ot: rows.reduce((s, r) => s + (r.ot_hours || 0), 0),
      total: rows.reduce((s, r) => s + (r.total_hours || 0), 0),
    };
  }, [data]);

  // Iter 77m — Tap-to-sort on every OT-Report column.
  type OTSortCol =
    | "code" | "name" | "desig" | "date" | "day"
    | "in" | "out" | "duty" | "ot" | "total";
  const [sortBy, setSortBy] = useState<OTSortCol>("date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const toggleSort = useCallback(
    (col: OTSortCol) => {
      if (col === sortBy) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortBy(col);
        setSortDir("asc");
      }
    },
    [sortBy],
  );
  const sortedRows = useMemo(() => {
    const rows = (data?.rows || []).slice();
    const dir = sortDir === "asc" ? 1 : -1;
    const s = (v: unknown) =>
      v === null || v === undefined ? "" : String(v).toLowerCase();
    const n = (v: unknown) => Number(v) || 0;
    rows.sort((a, b) => {
      switch (sortBy) {
        case "code":  return s(a.employee_code).localeCompare(s(b.employee_code), "en", { numeric: true }) * dir;
        case "name":  return s(a.name).localeCompare(s(b.name)) * dir;
        case "desig": return s(a.designation).localeCompare(s(b.designation)) * dir;
        case "date":  return s(a.date).localeCompare(s(b.date)) * dir;
        case "day":   return s(a.day_label).localeCompare(s(b.day_label)) * dir;
        case "in":    return s(a.in).localeCompare(s(b.in)) * dir;
        case "out":   return s(a.out).localeCompare(s(b.out)) * dir;
        case "duty":  return (n(a.duty_hours) - n(b.duty_hours)) * dir;
        case "ot":    return (n(a.ot_hours) - n(b.ot_hours)) * dir;
        case "total": return (n(a.total_hours) - n(b.total_hours)) * dir;
        default:      return 0;
      }
    });
    return rows;
  }, [data, sortBy, sortDir]);

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1, marginLeft: 8 }}>
          <Text style={styles.title}>OT Report</Text>
          <Text style={styles.subtitle} numberOfLines={1}>
            {data?.company?.name || "—"} · {month}
            {params.from && params.to ? `  (${params.from} → ${params.to})` : ""}
          </Text>
        </View>
        <Pressable
          onPress={downloadXlsx}
          disabled={downloading || (data?.rows || []).length === 0}
          style={[
            styles.dlBtn,
            (downloading || (data?.rows || []).length === 0) && { opacity: 0.5 },
          ]}
          testID="ot-report-download"
        >
          {downloading ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <>
              <Ionicons name="download-outline" size={16} color="#fff" />
              <Text style={styles.dlTxt}>XLSX</Text>
            </>
          )}
        </Pressable>
      </View>

      {/* Month picker */}
      <View style={styles.filterRow}>
        <Text style={styles.filterLbl}>Month</Text>
        <View style={styles.monthChips}>
          {[-2, -1, 0].map((off) => {
            const d = new Date();
            d.setMonth(d.getMonth() + off);
            const ym = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
            const on = ym === month;
            return (
              <Pressable
                key={ym}
                onPress={() => setMonth(ym)}
                style={[styles.chip, on && styles.chipOn]}
              >
                <Text style={[styles.chipTxt, on && styles.chipTxtOn]}>{ym}</Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={colors.brand} />
        </View>
      ) : err ? (
        <View style={styles.center}>
          <Text style={styles.errTxt}>{err}</Text>
          <Pressable onPress={load} style={styles.retryBtn}>
            <Text style={styles.retryTxt}>Retry</Text>
          </Pressable>
        </View>
      ) : (data?.rows || []).length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="time-outline" size={44} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyTxt}>No OT recorded in this period.</Text>
        </View>
      ) : (
        <ScrollView>
          <ScrollView horizontal showsHorizontalScrollIndicator>
            <View>
              {/* Header — Iter 77m: tap column headers to sort */}
              <View style={styles.tblHdr}>
                <SortableTh label="Code" col="code" w={76} sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="Name" col="name" w={170} sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="Designation" col="desig" w={110} sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="Date" col="date" w={100} sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="Day" col="day" w={60} sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="In" col="in" w={72} sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="Out" col="out" w={72} sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="OT In" col="otin" w={72} sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="OT Out" col="otout" w={72} sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="Duty" col="duty" w={68} sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="OT" col="ot" w={68} sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="Total" col="total" w={74} sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
              </View>
              {sortedRows.map((row, i) => (
                <View
                  key={`${row.user_id}-${row.date}`}
                  style={[styles.tblRow, i % 2 === 0 && styles.tblRowAlt]}
                >
                  <Text style={[styles.td, { width: 76 }]}>{row.employee_code || "—"}</Text>
                  <Text style={[styles.td, { width: 170 }]} numberOfLines={1}>
                    {row.name || "—"}
                  </Text>
                  <Text style={[styles.td, { width: 110 }]} numberOfLines={1}>
                    {row.designation || "—"}
                  </Text>
                  <Text style={[styles.td, { width: 100 }]}>{row.date}</Text>
                  <Text style={[styles.td, { width: 60 }]}>{row.day_label}</Text>
                  <Text style={[styles.td, { width: 72 }]}>{row.in || "—"}</Text>
                  <Text style={[styles.td, { width: 72 }]}>{row.out || "—"}</Text>
                  <Text style={[styles.td, { width: 72 }]}>{row.ot_in || "—"}</Text>
                  <Text style={[styles.td, { width: 72 }]}>{row.ot_out || "—"}</Text>
                  <Text style={[styles.td, styles.tdNum, { width: 68 }]}>
                    {fmtHM(row.duty_hours)}
                  </Text>
                  <Text style={[styles.td, styles.tdNum, styles.tdOt, { width: 68 }]}>
                    {fmtHM(row.ot_hours)}
                  </Text>
                  <Text style={[styles.td, styles.tdNum, styles.tdTotal, { width: 74 }]}>
                    {fmtHM(row.total_hours)}
                  </Text>
                </View>
              ))}
              {/* Totals */}
              <View style={styles.totalsRow}>
                <Text style={[styles.totalLbl, { width: 732 }]}>TOTAL</Text>
                <Text style={[styles.totalVal, { width: 68 }]}>{fmtHM(grandTotals.duty)}</Text>
                <Text style={[styles.totalVal, styles.tdOt, { width: 68 }]}>
                  {fmtHM(grandTotals.ot)}
                </Text>
                <Text style={[styles.totalVal, styles.tdTotal, { width: 74 }]}>
                  {fmtHM(grandTotals.total)}
                </Text>
              </View>
              <Text style={styles.foot}>
                {grandTotals.days} OT day(s). Duty HRS = policy-adjusted excluding OT. Total = Duty + OT.
              </Text>
            </View>
          </ScrollView>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  iconBtn: { padding: 8, borderRadius: 8 },
  title: { color: colors.onSurface, fontSize: typeScale.lg, fontWeight: "800" },
  subtitle: { color: colors.onSurfaceSecondary, fontSize: 12 },
  dlBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brand,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
  },
  dlTxt: { color: "#fff", fontWeight: "700", fontSize: 13 },
  filterRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    gap: 12,
    backgroundColor: colors.surface,
  },
  filterLbl: { color: colors.onSurfaceSecondary, fontSize: 12, fontWeight: "700" },
  monthChips: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: colors.brandTertiary,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  chipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipTxt: { color: colors.onSurface, fontSize: 12, fontWeight: "700" },
  chipTxtOn: { color: "#fff" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 32 },
  errTxt: { color: colors.error, textAlign: "center", marginBottom: 12 },
  retryBtn: {
    backgroundColor: colors.brand,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 8,
  },
  retryTxt: { color: "#fff", fontWeight: "700" },
  emptyTxt: { color: colors.onSurfaceSecondary, marginTop: 8, fontSize: 14 },
  tblHdr: {
    flexDirection: "row",
    backgroundColor: colors.brand,
    paddingVertical: 8,
    paddingHorizontal: 4,
  },
  th: {
    color: "#fff",
    fontWeight: "800",
    fontSize: 12,
    paddingHorizontal: 4,
  },
  tblRow: {
    flexDirection: "row",
    paddingVertical: 6,
    paddingHorizontal: 4,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
  },
  tblRowAlt: { backgroundColor: colors.brandTertiary },
  td: { color: colors.onSurface, fontSize: 12, paddingHorizontal: 4 },
  tdNum: { fontWeight: "700", textAlign: "right" },
  tdOt: { color: colors.accent },
  tdTotal: { color: colors.brand, fontWeight: "800" },
  totalsRow: {
    flexDirection: "row",
    paddingVertical: 10,
    paddingHorizontal: 4,
    borderTopWidth: 2,
    borderTopColor: colors.brand,
    backgroundColor: colors.surface,
  },
  totalLbl: {
    color: colors.onSurface,
    fontWeight: "800",
    fontSize: 13,
    paddingHorizontal: 4,
  },
  totalVal: {
    color: colors.onSurface,
    fontWeight: "800",
    fontSize: 13,
    textAlign: "right",
    paddingHorizontal: 4,
  },
  foot: {
    color: colors.onSurfaceSecondary,
    fontSize: 11,
    padding: 12,
    fontStyle: "italic",
  },
});
