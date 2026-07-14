/**
 * Iter 102 — Salary Process (Arrear) — LIVE module.
 *
 * Revised-wage arrears: pick a firm + month range → the backend compares
 * every stored compliance salary run in the range against the CURRENT
 * (revised) employee master, using the same present days, and computes
 * the arrear gross + PF/ESIC dues per the EPFO Arrear ECR help file.
 *
 * Downloads: EPFO Arrear ECR (.txt, `#~#` format) + Arrear Register (.xlsx).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView,
  ActivityIndicator, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import MonthPicker from "@/src/components/MonthPicker";
import { colors, radius, spacing, type } from "@/src/theme";

function showMsg(msg: string) {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert("Arrear salary", msg);
}

function fmtInr(n?: number | null): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Math.round(n).toLocaleString("en-IN");
}

function prevMonth(offset: number): string {
  const d = new Date();
  d.setMonth(d.getMonth() - offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

type ArrearRow = {
  user_id: string;
  employee_code?: string | null;
  name?: string | null;
  uan_no?: string | null;
  esic_no?: string | null;
  months: { month: string }[];
  old_gross: number;
  new_gross: number;
  arrear_gross: number;
  arrear_epf_wages: number;
  epf_due: number;
  eps_due: number;
  er_due: number;
  esic_employee: number;
  esic_employer: number;
};

type ArrearRun = {
  run_id: string;
  company_id: string;
  company_name?: string;
  from_month: string;
  to_month: string;
  months_used: string[];
  months_skipped: string[];
  employees_count: number;
  rows: ArrearRow[];
  totals: Record<string, number>;
  generated_at: string;
};

export default function ArrearSalaryRunScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { selectedCompanyId: globalCid, companies: ctxCompanies } = useSelectedCompany();
  const isSuper = user?.role === "super_admin" || user?.role === "sub_admin";
  const allowed = isSuper || user?.role === "company_admin";

  const [localCid, setLocalCid] = useState<string | null>(null);
  const activeCompanyId = localCid || globalCid || user?.company_id || null;

  const [fromMonth, setFromMonth] = useState(prevMonth(3));
  const [toMonth, setToMonth] = useState(prevMonth(1));
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [run, setRun] = useState<ArrearRun | null>(null);
  const [pastRuns, setPastRuns] = useState<any[]>([]);

  const loadRuns = useCallback(async () => {
    try {
      const q = activeCompanyId ? `?company_id=${encodeURIComponent(activeCompanyId)}` : "";
      const r = await api<{ runs: any[] }>(`/admin/arrear-salary-runs${q}`);
      setPastRuns(r.runs || []);
    } catch { setPastRuns([]); }
  }, [activeCompanyId]);
  useEffect(() => { loadRuns(); }, [loadRuns]);

  const generate = async () => {
    if (busy) return;
    if (!activeCompanyId) { showMsg("Select a firm first"); return; }
    setBusy(true);
    try {
      const r = await api<{ run: ArrearRun }>("/admin/arrear-salary-runs", {
        method: "POST",
        body: { company_id: activeCompanyId, from_month: fromMonth, to_month: toMonth },
      });
      setRun(r.run);
      await loadRuns();
      const skipped = r.run.months_skipped?.length
        ? ` (skipped ${r.run.months_skipped.join(", ")} — no compliance run found)` : "";
      showMsg(`Arrear computed for ${r.run.employees_count} employee(s). Total arrear gross: ₹${fmtInr(r.run.totals?.arrear_gross)}${skipped}`);
    } catch (e: any) {
      showMsg(e?.message || "Failed to generate arrear run");
    } finally { setBusy(false); }
  };

  const openRun = async (runId: string) => {
    try {
      const r = await api<{ run: ArrearRun }>(`/admin/arrear-salary-runs/${runId}`);
      setRun(r.run);
      setFromMonth(r.run.from_month);
      setToMonth(r.run.to_month);
    } catch (e: any) { showMsg(e?.message || "Could not open run"); }
  };

  const download = async (kind: "ecr" | "xlsx") => {
    if (!run || downloading) return;
    setDownloading(true);
    try {
      const path = kind === "ecr"
        ? `/admin/arrear-salary-runs/${run.run_id}/ecr.txt`
        : `/admin/arrear-salary-runs/${run.run_id}/export.xlsx`;
      const f = await apiBinary(path);
      if (Platform.OS === "web" && f.webBlobUrl) {
        const a = document.createElement("a");
        a.href = f.webBlobUrl;
        a.download = kind === "ecr"
          ? `arrear_ecr_${run.from_month}_${run.to_month}.txt`
          : `arrear_register_${run.from_month}_${run.to_month}.xlsx`;
        a.click();
      } else {
        showMsg("Download is available on the web portal.");
      }
    } catch (e: any) { showMsg(e?.message || "Download failed"); }
    finally { setDownloading(false); }
  };

  if (!allowed) {
    return (
      <View style={styles.center}>
        <Text style={{ color: colors.onSurfaceSecondary }}>Not authorised.</Text>
      </View>
    );
  }

  const t = run?.totals || {};

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 60 }}>
        <View style={styles.headRow}>
          <Pressable onPress={() => router.back()} style={styles.backBtn} testID="arrear-back">
            <Ionicons name="chevron-back" size={20} color={colors.onSurface} />
          </Pressable>
          <View>
            <Text style={styles.title}>Salary Process (Arrear)</Text>
            <Text style={styles.subtitle}>
              Revised-wage difference vs past compliance runs · PF/ESIC on arrears (EPFO Arrear ECR)
            </Text>
          </View>
        </View>

        {/* Firm selection (super/sub admins) */}
        {isSuper ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Select firm</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
              {(ctxCompanies || []).map((c: any) => {
                const on = activeCompanyId === c.company_id;
                return (
                  <Pressable
                    key={c.company_id}
                    onPress={() => setLocalCid(c.company_id)}
                    style={[styles.chip, on && styles.chipOn]}
                    testID={`arrear-firm-${c.company_id}`}
                  >
                    <Text style={[styles.chipTxt, on && styles.chipTxtOn]}>
                      {c.name || c.company_id}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        ) : null}

        {/* Period */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Arrear period</Text>
          <Text style={styles.hint}>
            Every month in this range that has a Compliance Salary run will be
            re-computed at the CURRENT (revised) salary — the difference is the arrear.
          </Text>
          <View style={{ flexDirection: "row", gap: 14, marginTop: 10, flexWrap: "wrap" }}>
            <View style={{ minWidth: 200 }}>
              <Text style={styles.lbl}>From month</Text>
              <MonthPicker value={fromMonth} onChange={setFromMonth} allowEmpty={false} testID="arrear-from" />
            </View>
            <View style={{ minWidth: 200 }}>
              <Text style={styles.lbl}>To month</Text>
              <MonthPicker value={toMonth} onChange={setToMonth} allowEmpty={false} testID="arrear-to" />
            </View>
          </View>
          <Pressable
            onPress={generate}
            disabled={busy || !activeCompanyId}
            style={[styles.primaryBtn, (busy || !activeCompanyId) && { opacity: 0.6 }]}
            testID="arrear-generate"
          >
            {busy ? <ActivityIndicator color="#fff" /> : (
              <>
                <Ionicons name="calculator-outline" size={16} color="#fff" />
                <Text style={styles.primaryBtnTxt}>Compute Arrears</Text>
              </>
            )}
          </Pressable>
        </View>

        {/* Result */}
        {run ? (
          <View style={styles.card} testID="arrear-result">
            <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
              <View style={{ flex: 1, minWidth: 220 }}>
                <Text style={styles.cardTitle}>
                  {run.from_month} → {run.to_month} · {run.employees_count} employee(s)
                </Text>
                <Text style={styles.hint}>
                  Months used: {run.months_used?.join(", ") || "—"}
                  {run.months_skipped?.length ? `  ·  Skipped (no run): ${run.months_skipped.join(", ")}` : ""}
                </Text>
              </View>
              <Pressable style={styles.secondaryBtn} onPress={() => download("xlsx")} disabled={downloading} testID="arrear-dl-xlsx">
                <Ionicons name="grid-outline" size={14} color={colors.brandPrimary} />
                <Text style={styles.secondaryBtnTxt}>Excel Register</Text>
              </Pressable>
              <Pressable style={styles.secondaryBtn} onPress={() => download("ecr")} disabled={downloading} testID="arrear-dl-ecr">
                <Ionicons name="document-text-outline" size={14} color={colors.brandPrimary} />
                <Text style={styles.secondaryBtnTxt}>EPFO Arrear ECR (.txt)</Text>
              </Pressable>
            </View>

            {/* Totals strip */}
            <View style={styles.totalsRow}>
              {[
                ["Arrear Gross", t.arrear_gross],
                ["EPF Wages", t.arrear_epf_wages],
                ["EPF Due (EE)", t.epf_due],
                ["EPS Due", t.eps_due],
                ["ER Due (3.67)", t.er_due],
                ["ESIC EE", t.esic_employee],
                ["ESIC ER", t.esic_employer],
              ].map(([lab, val]) => (
                <View key={String(lab)} style={styles.totBox}>
                  <Text style={styles.totLbl}>{lab}</Text>
                  <Text style={styles.totVal}>₹{fmtInr(val as number)}</Text>
                </View>
              ))}
            </View>

            {run.rows.length === 0 ? (
              <Text style={[styles.hint, { marginTop: 10 }]}>
                No arrears found — revised salaries match what was already paid
                for the selected months.
              </Text>
            ) : (
              <ScrollView horizontal style={{ marginTop: 12 }}>
                <View>
                  <View style={[styles.tr, styles.th]}>
                    {["SN", "Code", "Name", "UAN", "Months", "Old Gross", "Revised", "Arrear",
                      "EPF Wages", "EPF (EE)", "EPS", "ER (3.67)", "ESIC EE", "ESIC ER"].map((h, i) => (
                      <Text key={h} style={[styles.thTxt, { width: COLW[i] }]}>{h}</Text>
                    ))}
                  </View>
                  {run.rows.map((r, idx) => (
                    <View key={r.user_id} style={[styles.tr, idx % 2 ? styles.zebra : null]}>
                      <Text style={[styles.td, { width: COLW[0] }]}>{idx + 1}</Text>
                      <Text style={[styles.td, { width: COLW[1] }]}>{r.employee_code}</Text>
                      <Text style={[styles.td, { width: COLW[2], textAlign: "left" }]} numberOfLines={1}>{r.name}</Text>
                      <Text style={[styles.td, { width: COLW[3] }]}>{r.uan_no || "—"}</Text>
                      <Text style={[styles.td, { width: COLW[4] }]}>{r.months?.length || 0}</Text>
                      <Text style={[styles.td, { width: COLW[5] }]}>{fmtInr(r.old_gross)}</Text>
                      <Text style={[styles.td, { width: COLW[6] }]}>{fmtInr(r.new_gross)}</Text>
                      <Text style={[styles.td, { width: COLW[7], fontWeight: "800", color: "#166534" }]}>{fmtInr(r.arrear_gross)}</Text>
                      <Text style={[styles.td, { width: COLW[8] }]}>{fmtInr(r.arrear_epf_wages)}</Text>
                      <Text style={[styles.td, { width: COLW[9] }]}>{fmtInr(r.epf_due)}</Text>
                      <Text style={[styles.td, { width: COLW[10] }]}>{fmtInr(r.eps_due)}</Text>
                      <Text style={[styles.td, { width: COLW[11] }]}>{fmtInr(r.er_due)}</Text>
                      <Text style={[styles.td, { width: COLW[12] }]}>{fmtInr(r.esic_employee)}</Text>
                      <Text style={[styles.td, { width: COLW[13] }]}>{fmtInr(r.esic_employer)}</Text>
                    </View>
                  ))}
                </View>
              </ScrollView>
            )}
          </View>
        ) : null}

        {/* Past runs */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Past arrear runs</Text>
          {pastRuns.length === 0 ? (
            <Text style={styles.hint}>No arrear runs yet.</Text>
          ) : pastRuns.map((r: any) => (
            <Pressable
              key={r.run_id}
              onPress={() => openRun(r.run_id)}
              style={styles.runRow}
              testID={`arrear-run-${r.run_id}`}
            >
              <Ionicons name="time-outline" size={16} color={colors.brandPrimary} />
              <View style={{ flex: 1 }}>
                <Text style={{ fontWeight: "700", color: colors.onSurface, fontSize: 13 }}>
                  {r.from_month} → {r.to_month} · {r.employees_count} employee(s)
                </Text>
                <Text style={styles.hint}>
                  {r.company_name || r.company_id} · Arrear ₹{fmtInr(r.totals?.arrear_gross)} · {String(r.generated_at || "").slice(0, 10)}
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const COLW = [36, 56, 170, 120, 60, 90, 90, 90, 90, 80, 80, 80, 72, 72];

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  headRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: spacing.lg },
  backBtn: {
    width: 36, height: 36, borderRadius: 10, backgroundColor: colors.surface,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: colors.divider,
  },
  title: { ...type.h2, color: colors.onSurface, fontWeight: "800" },
  subtitle: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 2 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.divider, marginBottom: spacing.md,
  },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  hint: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 3 },
  lbl: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4, textTransform: "uppercase" },
  chip: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999,
    borderWidth: 1, borderColor: colors.divider, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  chipTxtOn: { color: "#fff" },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brandPrimary, paddingVertical: 13, borderRadius: radius.md,
    marginTop: spacing.md, maxWidth: 340,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 14 },
  secondaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  secondaryBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  totalsRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12 },
  totBox: {
    backgroundColor: "#F1F5F9", borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 8, minWidth: 110,
  },
  totLbl: { fontSize: 10, fontWeight: "700", color: colors.onSurfaceTertiary, textTransform: "uppercase" },
  totVal: { fontSize: 14, fontWeight: "800", color: colors.onSurface, marginTop: 2 },
  tr: { flexDirection: "row", alignItems: "center", borderBottomWidth: 1, borderColor: colors.divider },
  th: { backgroundColor: "#0F2E3D" },
  thTxt: { color: "#fff", fontWeight: "800", fontSize: 11, paddingVertical: 8, paddingHorizontal: 4, textAlign: "center" },
  td: { fontSize: 11.5, color: colors.onSurface, paddingVertical: 7, paddingHorizontal: 4, textAlign: "center" },
  zebra: { backgroundColor: "#FAFAF9" },
  runRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 10, borderBottomWidth: 1, borderColor: colors.divider,
  },
});
