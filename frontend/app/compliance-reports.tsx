/**
 * Compliance Reports — Iter 92 (Reports section).
 *
 * Act-wise reports for a SINGLE firm, employee-group-wise, over
 * Monthly / Half-Yearly / Annual periods:
 *   • Contributions — PF / ESIC / PT / TDS (from compliance runs)
 *   • Leave Register — approved leaves + Earned-Leave @ 1/20 present days
 *   • Gratuity — Payment of Gratuity Act calculation per employee
 * Read-only + Excel export.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  ActivityIndicator, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import MasterSelect from "@/src/components/MasterSelect";
import { colors, radius, spacing } from "@/src/theme";

type Col = { key: string; label: string };
type Row = Record<string, any>;

const REPORTS = [
  { key: "contributions", label: "PF / ESIC / PT / TDS", icon: "briefcase-outline" },
  { key: "leave", label: "Leave Register", icon: "calendar-outline" },
  { key: "gratuity", label: "Gratuity", icon: "ribbon-outline" },
] as const;

const PERIODS = [
  { key: "monthly", label: "Monthly" },
  { key: "half1", label: "Half-Yearly (Jan–Jun)" },
  { key: "half2", label: "Half-Yearly (Jul–Dec)" },
  { key: "annual", label: "Annual" },
] as const;

export default function ComplianceReportsScreen() {
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId, companies } = useSelectedCompany();
  const isAdmin = ["company_admin", "super_admin", "sub_admin"].includes(user?.role || "");
  const isSuper = user?.role === "super_admin";

  const now = new Date();
  const [report, setReport] = useState<"contributions" | "leave" | "gratuity">("contributions");
  const [cid, setCid] = useState<string | null>(null);
  const [year, setYear] = useState(now.getFullYear());
  const [period, setPeriod] = useState<"monthly" | "half1" | "half2" | "annual">("monthly");
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [empType, setEmpType] = useState("");
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [cols, setCols] = useState<Col[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [meta, setMeta] = useState<any>(null);

  const activeCid = cid || selectedCompanyId || user?.company_id || null;

  const buildQs = useCallback(() => {
    const p = new URLSearchParams();
    p.set("report", report);
    if (activeCid) p.set("company_id", activeCid);
    p.set("year", String(year));
    p.set("period", period);
    if (period === "monthly") p.set("month", String(month));
    if (empType) p.set("employee_type", empType);
    return p.toString();
  }, [report, activeCid, year, period, month, empType]);

  const load = useCallback(async () => {
    if (!activeCid) return;
    setLoading(true);
    try {
      const r = await api<any>(`/admin/reports/compliance?${buildQs()}`);
      setCols(r.columns || []);
      setRows(r.rows || []);
      setMeta(r);
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Failed to load report");
      setRows([]);
    } finally { setLoading(false); }
  }, [activeCid, buildQs]);

  useEffect(() => { if (isAdmin) load(); }, [isAdmin, load]);

  const exportXlsx = async () => {
    if (exporting || !activeCid) return;
    setExporting(true);
    try {
      const res = await apiBinary(`/admin/reports/compliance.xlsx?${buildQs()}`);
      if (Platform.OS === "web" && (res as any).webBlobUrl) {
        const a = document.createElement("a");
        a.href = (res as any).webBlobUrl;
        a.download = `Compliance_${report}_${period}_${year}.xlsx`;
        a.click();
      }
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Export failed");
    } finally { setExporting(false); }
  };

  if (authLoading) {
    return (
      <View style={styles.root}>
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
        </View>
      </View>
    );
  }

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.dimTxt}>Admins only</Text>
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
            <Text style={styles.h1}>Compliance Reports</Text>
            <Text style={styles.hsub}>
              {meta?.company_name || "Pick a firm"} · group-wise · Excel export
            </Text>
          </View>
          <Pressable onPress={exportXlsx} style={styles.exportBtn} testID="cr-export">
            {exporting ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <>
                <Ionicons name="grid-outline" size={14} color="#fff" />
                <Text style={styles.exportTxt}>Excel</Text>
              </>
            )}
          </Pressable>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Report type */}
        <View style={styles.chipRow}>
          {REPORTS.map((rp) => (
            <Pressable
              key={rp.key}
              onPress={() => setReport(rp.key)}
              style={[styles.chip, report === rp.key && styles.chipOn]}
              testID={`cr-report-${rp.key}`}
            >
              <Ionicons name={rp.icon as any} size={13}
                        color={report === rp.key ? "#fff" : colors.onSurfaceSecondary} />
              <Text style={[styles.chipTxt, report === rp.key && styles.chipTxtOn]}>{rp.label}</Text>
            </Pressable>
          ))}
        </View>

        {/* Firm picker (super admin) */}
        {isSuper ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Select firm (single)</Text>
            <View style={styles.chipRow}>
              {(companies || []).map((c: any) => (
                <Pressable
                  key={c.company_id}
                  onPress={() => setCid(c.company_id)}
                  style={[styles.chip, activeCid === c.company_id && styles.chipOn]}
                  testID={`cr-firm-${c.company_id}`}
                >
                  <Text style={[styles.chipTxt, activeCid === c.company_id && styles.chipTxtOn]}>
                    {c.name || c.company_id}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
        ) : null}

        {/* Period controls (not for gratuity — as-of today) */}
        {report !== "gratuity" ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Period</Text>
            <View style={styles.chipRow}>
              {PERIODS.map((p) => (
                <Pressable
                  key={p.key}
                  onPress={() => setPeriod(p.key)}
                  style={[styles.chip, period === p.key && styles.chipOn]}
                  testID={`cr-period-${p.key}`}
                >
                  <Text style={[styles.chipTxt, period === p.key && styles.chipTxtOn]}>{p.label}</Text>
                </Pressable>
              ))}
            </View>
            <View style={[styles.chipRow, { marginTop: 8 }]}>
              <Text style={styles.lbl}>Year:</Text>
              {[year - 1, year, year + 1].filter((yy) => yy <= now.getFullYear()).map((yy) => (
                <Pressable key={yy} onPress={() => setYear(yy)}
                           style={[styles.chip, year === yy && styles.chipOn]}>
                  <Text style={[styles.chipTxt, year === yy && styles.chipTxtOn]}>{yy}</Text>
                </Pressable>
              ))}
              {period === "monthly" ? (
                <>
                  <Text style={[styles.lbl, { marginLeft: 12 }]}>Month:</Text>
                  {Array.from({ length: 12 }, (_, i) => i + 1).map((mm) => (
                    <Pressable key={mm} onPress={() => setMonth(mm)}
                               style={[styles.chipSm, month === mm && styles.chipOn]}>
                      <Text style={[styles.chipTxt, month === mm && styles.chipTxtOn]}>{mm}</Text>
                    </Pressable>
                  ))}
                </>
              ) : null}
            </View>
          </View>
        ) : null}

        {/* Group filter */}
        <View style={[styles.card, { zIndex: 40 }]}>
          <MasterSelect
            label="Employee Type / Group (optional filter)"
            masterType="group"
            companyId={activeCid}
            value={empType}
            onChange={setEmpType}
            placeholder="All groups"
            testID="cr-group"
          />
        </View>

        {meta?.months_missing?.length ? (
          <Text style={styles.warnTxt}>
            ⚠ No compliance run found for: {meta.months_missing.join(", ")} — those months count as 0.
          </Text>
        ) : null}

        {/* Table */}
        {loading ? (
          <ActivityIndicator style={{ margin: 30 }} color={colors.brandPrimary} />
        ) : (
          <ScrollView horizontal>
            <View>
              <View style={styles.gridHead}>
                {cols.map((c) => (
                  <Text key={c.key} style={[styles.hCell, { width: cw(c.key) }]}>{c.label}</Text>
                ))}
              </View>
              {rows.map((r, i) => (
                <View key={i} style={[styles.gridRow, i % 2 === 1 && { backgroundColor: "#F8FAFC" }]}>
                  {cols.map((c) => (
                    <Text key={c.key} style={[styles.cell, { width: cw(c.key) }]} numberOfLines={2}>
                      {fmtVal(r[c.key])}
                    </Text>
                  ))}
                </View>
              ))}
              {rows.length === 0 ? (
                <Text style={[styles.dimTxt, { padding: 24 }]}>No data for this selection.</Text>
              ) : null}
            </View>
          </ScrollView>
        )}
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

function fmtVal(v: any): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return v.toLocaleString("en-IN");
  return String(v);
}

function cw(key: string): number {
  if (key === "name") return 170;
  if (key === "leave_breakup") return 200;
  if (key === "group") return 120;
  if (key === "gratuity") return 160;
  return 110;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: spacing.md, paddingVertical: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  h1: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  hsub: { fontSize: 11, color: colors.onSurfaceTertiary },
  exportBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: "#15803D",
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: radius.md,
  },
  exportTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  scroll: { padding: spacing.md, ...(Platform.OS === "web" ? { maxWidth: 1200, width: "100%", alignSelf: "center" } : {}) },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
    padding: 12, marginBottom: 10,
  },
  cardTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, alignItems: "center", marginBottom: 4 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipSm: {
    paddingHorizontal: 9, paddingVertical: 6,
    borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  lbl: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  warnTxt: { fontSize: 11, color: "#B45309", marginBottom: 8 },
  gridHead: { flexDirection: "row", backgroundColor: "#1E3A8A", paddingVertical: 8 },
  hCell: { color: "#fff", fontSize: 11, fontWeight: "800", paddingHorizontal: 6 },
  gridRow: {
    flexDirection: "row", paddingVertical: 7,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
  },
  cell: { fontSize: 11, color: colors.onSurface, paddingHorizontal: 6 },
  center: { alignItems: "center", gap: 8, padding: 40 },
  dimTxt: { color: colors.onSurfaceTertiary, fontSize: 13 },
});
