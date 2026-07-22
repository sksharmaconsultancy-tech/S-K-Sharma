/**
 * Iter 145 — Punch Log Report (Utility).
 *
 * Full punch audit trail: every IN/OUT from biometric machines, the mobile
 * app, imports and admin manual entries. Filters: date range, firm and
 * machine. One-click Excel download of the filtered log.
 */
import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  ScrollView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";
import DateField from "@/src/components/DateField";

type Row = {
  date: string;
  time: string;
  kind: string;
  employee_code: string;
  name: string;
  bio_code: string;
  machine: string;
  machine_key: string;
  company_name: string;
  status: string;
};

type Machine = { key: string; label: string };

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}
function daysAgoIso(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

const COLS: { key: keyof Row; label: string; w: number }[] = [
  { key: "date", label: "Date", w: 96 },
  { key: "time", label: "Time", w: 76 },
  { key: "kind", label: "IN/OUT", w: 64 },
  { key: "employee_code", label: "Code", w: 60 },
  { key: "name", label: "Employee", w: 180 },
  { key: "bio_code", label: "Bio", w: 50 },
  { key: "machine", label: "Machine / Source", w: 160 },
  { key: "company_name", label: "Firm", w: 170 },
  { key: "status", label: "Status", w: 90 },
];

export default function PunchLogReportScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { companies, selectedCompanyId } = useSelectedCompany();
  const isAdmin =
    user?.role === "super_admin" || user?.role === "sub_admin" || user?.role === "company_admin";

  const [fromDate, setFromDate] = useState<string>(daysAgoIso(7));
  const [toDate, setToDate] = useState<string>(todayIso());
  const [firmId, setFirmId] = useState<string>(selectedCompanyId || "");
  const [machine, setMachine] = useState<string>("");
  const [machines, setMachines] = useState<Machine[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const showMsg = (m: string) => {
    if (Platform.OS === "web") globalThis.alert(m);
  };

  const qs = (withMachine: boolean) => {
    const p = new URLSearchParams();
    if (fromDate) p.set("from_date", fromDate);
    if (toDate) p.set("to_date", toDate);
    if (firmId) p.set("company_id", firmId);
    if (withMachine && machine) p.set("machine", machine);
    return p.toString();
  };

  const fetchLog = async (withMachine = true) => {
    setLoading(true);
    try {
      const r = await api<{
        rows: Row[];
        total: number;
        truncated: boolean;
        machines: Machine[];
      }>(`/admin/punch-logs?${qs(withMachine)}`);
      setRows(r.rows || []);
      setTotal(r.total || 0);
      setTruncated(!!r.truncated);
      if (!withMachine || !machine) setMachines(r.machines || []);
    } catch (e: any) {
      showMsg(e?.message || "Failed to load punch log");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchLog(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const downloadXlsx = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      const res = await apiBinary(`/admin/punch-logs.xlsx?${qs(true)}`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = `Punch_Log_${fromDate}_${toDate}.xlsx`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      showMsg(e?.message || "Download failed");
    } finally {
      setDownloading(false);
    }
  };

  if (!isAdmin) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <Text style={styles.subtitle}>Admin access only.</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="plog-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Punch Log Report</Text>
          <Text style={styles.subtitle}>
            Every punch — machine, app, import &amp; manual — by date, machine and firm
          </Text>
        </View>
        <Pressable
          onPress={downloadXlsx}
          style={[styles.dlBtn, downloading && { opacity: 0.6 }]}
          disabled={downloading}
          testID="plog-download"
        >
          {downloading ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <Ionicons name="download-outline" size={16} color="#fff" />
          )}
          <Text style={styles.dlBtnTxt}>Download Excel</Text>
        </Pressable>
      </View>

      {/* Filters */}
      <View style={styles.filterCard}>
        <View style={styles.filterRow}>
          <View style={{ width: 150 }}>
            <Text style={styles.lbl}>From</Text>
            <DateField value={fromDate} onChangeISO={setFromDate} testID="plog-from" />
          </View>
          <View style={{ width: 150 }}>
            <Text style={styles.lbl}>To</Text>
            <DateField value={toDate} onChangeISO={setToDate} testID="plog-to" />
          </View>
          {user?.role !== "company_admin" ? (
            <View style={{ minWidth: 200 }}>
              <Text style={styles.lbl}>Firm</Text>
              {Platform.OS === "web" ? (
                <select
                  value={firmId}
                  onChange={(e) => setFirmId((e.target as HTMLSelectElement).value)}
                  style={styles.select as any}
                >
                  <option value="">All firms</option>
                  {companies.map((c: any) => (
                    <option key={c.company_id} value={c.company_id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              ) : null}
            </View>
          ) : null}
          <View style={{ minWidth: 200 }}>
            <Text style={styles.lbl}>Machine / Source</Text>
            {Platform.OS === "web" ? (
              <select
                value={machine}
                onChange={(e) => setMachine((e.target as HTMLSelectElement).value)}
                style={styles.select as any}
              >
                <option value="">All machines / sources</option>
                {machines.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.label}
                  </option>
                ))}
              </select>
            ) : null}
          </View>
          <Pressable
            onPress={() => {
              // Iter 249 (user request) — Apply refreshes the list AND
              // downloads the FULL Excel for the selected period.
              fetchLog(true);
              downloadXlsx();
            }}
            style={styles.applyBtn}
            testID="plog-apply"
          >
            <Ionicons name="search-outline" size={15} color="#fff" />
            <Text style={styles.applyTxt}>Apply</Text>
          </Pressable>
        </View>
        <Text style={styles.countTxt}>
          {loading ? "Loading…" : `${total} punch${total === 1 ? "" : "es"}`}
          {truncated ? " (showing first 2000 — use Download Excel for the full log)" : ""}
        </Text>
      </View>

      {/* Grid */}
      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
      ) : (
        <ScrollView horizontal style={{ flex: 1 }} contentContainerStyle={{ minWidth: "100%" }}>
          <ScrollView style={{ flex: 1 }} stickyHeaderIndices={[0]}>
            <View style={styles.headRow}>
              {COLS.map((c) => (
                <Text key={c.key} style={[styles.headCell, { width: c.w }]}>{c.label}</Text>
              ))}
            </View>
            {rows.map((r, i) => (
              <View key={i} style={[styles.row, i % 2 === 1 && styles.rowAlt]}>
                {COLS.map((c) => (
                  <Text
                    key={c.key}
                    numberOfLines={1}
                    style={[
                      styles.cell,
                      { width: c.w },
                      c.key === "kind" && {
                        fontWeight: "800",
                        color: r.kind === "in" ? "#15803D" : "#B45309",
                      },
                    ]}
                  >
                    {c.key === "kind" ? (r.kind || "").toUpperCase() : (r as any)[c.key] || "—"}
                  </Text>
                ))}
              </View>
            ))}
            {rows.length === 0 ? (
              <Text style={styles.empty}>No punches found for the selected filters.</Text>
            ) : null}
            <View style={{ height: 60 }} />
          </ScrollView>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  backBtn: { padding: 6 },
  title: { fontSize: type.lg, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: type.xs, color: colors.onSurfaceSecondary },
  dlBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  dlBtnTxt: { color: "#fff", fontWeight: "800", fontSize: type.sm },
  filterCard: {
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  filterRow: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, flexWrap: "wrap" },
  lbl: { fontSize: type.xs, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  select: {
    height: 38,
    borderRadius: 8,
    border: `1px solid ${colors.border}`,
    padding: "0 8px",
    backgroundColor: colors.surface,
    color: colors.onSurface,
    fontSize: 13,
  },
  applyBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brand,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    height: 38,
  },
  applyTxt: { color: "#fff", fontWeight: "800", fontSize: type.sm },
  countTxt: { marginTop: 8, fontSize: type.xs, color: colors.onSurfaceSecondary },
  headRow: {
    flexDirection: "row",
    backgroundColor: colors.surfaceSecondary,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    paddingVertical: 8,
    paddingHorizontal: spacing.sm,
  },
  headCell: { fontSize: type.xs, fontWeight: "800", color: colors.onSurfaceSecondary },
  row: {
    flexDirection: "row",
    paddingVertical: 7,
    paddingHorizontal: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  rowAlt: { backgroundColor: colors.surfaceSecondary },
  cell: { fontSize: type.xs, color: colors.onSurface, paddingRight: 6 },
  empty: {
    textAlign: "center",
    marginTop: 40,
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
  },
});
