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
import ReportTable, { ReportCol } from "@/src/components/ReportTable";
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

// Iter 496 — Universal Report Table columns (auto width, sticky code+name).
const OT_COLS: ReportCol<OTRow>[] = [
  { key: "employee_code", label: "Code", type: "center", min: 76, sticky: true },
  { key: "name", label: "Name", min: 200, max: 300, sticky: true },
  { key: "designation", label: "Designation", min: 110, max: 220 },
  { key: "date", label: "Date", type: "date" },
  { key: "day_label", label: "Day", type: "center", min: 60 },
  { key: "in", label: "In", type: "center", min: 72 },
  { key: "out", label: "Out", type: "center", min: 72 },
  { key: "ot_in", label: "OT In", type: "center", min: 72 },
  { key: "ot_out", label: "OT Out", type: "center", min: 76 },
  { key: "duty_hours", label: "Duty", type: "num", min: 76, value: (r) => fmtHM(r.duty_hours) },
  {
    key: "ot_hours", label: "OT", type: "num", min: 72,
    value: (r) => fmtHM(r.ot_hours),
    textStyle: () => ({ color: "#B45309", fontWeight: "800" }),
  },
  {
    key: "total_hours", label: "Total", type: "num", min: 80,
    value: (r) => fmtHM(r.total_hours),
    textStyle: () => ({ fontWeight: "800" }),
  },
];

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

  // Iter 77m — Tap-to-sort on every OT-Report column (Iter 496: keys now
  // match the ReportTable column keys).
  const [sortBy, setSortBy] = useState<string>("date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const toggleSort = useCallback(
    (col: string) => {
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
    const numeric = ["duty_hours", "ot_hours", "total_hours"];
    rows.sort((a, b) => {
      if (numeric.includes(sortBy)) {
        return (n((a as any)[sortBy]) - n((b as any)[sortBy])) * dir;
      }
      return s((a as any)[sortBy]).localeCompare(
        s((b as any)[sortBy]), "en", { numeric: sortBy === "employee_code" }) * dir;
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
        <View style={{ flex: 1 }}>
          {/* Iter 496 — Universal Report Table engine */}
          <ReportTable<OTRow>
            reportKey="ot_report"
            columns={OT_COLS}
            rows={sortedRows}
            sortBy={sortBy}
            sortDir={sortDir}
            onHeaderPress={toggleSort}
            footer={{
              label: "TOTAL",
              values: {
                duty_hours: fmtHM(grandTotals.duty),
                ot_hours: fmtHM(grandTotals.ot),
                total_hours: fmtHM(grandTotals.total),
              },
            }}
          />
          <Text style={styles.foot}>
            {grandTotals.days} OT day(s). Duty HRS = policy-adjusted excluding OT. Total = Duty + OT.
          </Text>
        </View>
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
