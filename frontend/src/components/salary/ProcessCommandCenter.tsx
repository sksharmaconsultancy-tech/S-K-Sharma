/**
 * Process Command Center — enterprise header for the salary process
 * screens (Compliance / Actual / Arrear). SAP SuccessFactors / Workday
 * style: KPI stat cards, a horizontal compliance workflow stepper and a
 * live validation panel with an overall compliance progress bar.
 *
 * All numbers come LIVE from the DB for the selected company + month via
 * GET /admin/salary-process/readiness (re-fetched on every change).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

type Check = {
  key: string; label: string; ok: boolean;
  passed: number; total: number; note: string; na: boolean;
};

export type Readiness = {
  compliance_pct: number;
  kpis: {
    total_employees: number; pf_eligible: number; esic_eligible: number;
    pt_applicable: number; uan_missing: number; esic_ip_missing: number;
    compliance_errors: number; attendance_records: number;
    salary_processed: {
      compliance: boolean; compliance_count: number; compliance_finalized: boolean;
      actual: boolean; actual_count: number; actual_finalized: boolean;
    };
    challans: { pf_uploaded: boolean; esic_uploaded: boolean; pending: number };
  };
  checks: Check[];
};

type Props = {
  companyId?: string | null;
  month?: string | null;           // YYYY-MM
  processType: "compliance" | "actual" | "arrear";
  runExists: boolean;
  runFinalized: boolean;
  /** bump to force a refresh (e.g. after Process / Finalize) */
  refreshKey?: number;
};

function Kpi({ icon, label, value, tone, sub }: {
  icon: keyof typeof Ionicons.glyphMap; label: string;
  value: string | number; tone: string; sub?: string;
}) {
  return (
    <View style={st.kpi} testID={`pcc-kpi-${label.replace(/\W+/g, "-").toLowerCase()}`}>
      <View style={[st.kpiIcon, { backgroundColor: `${tone}16` }]}>
        <Ionicons name={icon} size={15} color={tone} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={st.kpiValue} numberOfLines={1}>{value}</Text>
        <Text style={st.kpiLabel} numberOfLines={1}>{label}</Text>
        {sub ? <Text style={[st.kpiSub, { color: tone }]} numberOfLines={1}>{sub}</Text> : null}
      </View>
    </View>
  );
}

export default function ProcessCommandCenter({
  companyId, month, processType, runExists, runFinalized, refreshKey = 0,
}: Props) {
  const [data, setData] = useState<Readiness | null>(null);
  const [loading, setLoading] = useState(false);
  const [showChecks, setShowChecks] = useState(false);

  const load = useCallback(async () => {
    if (!companyId || !month) { setData(null); return; }
    setLoading(true);
    try {
      const r = await api<Readiness & { ok: boolean }>(
        `/admin/salary-process/readiness?company_id=${encodeURIComponent(companyId)}&month=${month}`);
      setData(r);
    } catch { setData(null); }
    finally { setLoading(false); }
  }, [companyId, month]);
  useEffect(() => { load(); }, [load, refreshKey]);

  const steps = useMemo(() => {
    const k = data?.kpis;
    const byKey: Record<string, Check> = {};
    (data?.checks || []).forEach((c) => { byKey[c.key] = c; });
    const attendanceOk = !!byKey.attendance?.ok;
    const dataOk = (data?.compliance_pct ?? 0) >= 60 &&
      !!byKey.salary_structure?.ok && !!byKey.duplicates?.ok;
    const noErrors = (k?.compliance_errors ?? 1) === 0;
    const challansDone = (k?.challans?.pending ?? 2) === 0;
    if (processType === "arrear") {
      return [
        { label: "Load Employees", done: (k?.total_employees ?? 0) > 0 },
        { label: "Validate Data", done: dataOk },
        { label: "Base Runs Available", done: !!k?.salary_processed?.compliance },
        { label: "Compute Arrears", done: runExists },
        { label: "Review & Export", done: runExists && runFinalized },
      ];
    }
    const base = [
      { label: "Load Employees", done: (k?.total_employees ?? 0) > 0 },
      { label: "Validate Employee Data", done: dataOk },
      { label: "Attendance Validation", done: attendanceOk },
      { label: "Salary Calculation", done: runExists },
      { label: "Compliance Validation", done: runExists && noErrors },
      { label: "Review & Approve", done: runFinalized },
      { label: "Finalize & Lock", done: runFinalized },
    ];
    if (processType === "compliance") {
      base.push({ label: "Challans & Returns", done: challansDone });
    }
    return base;
  }, [data, processType, runExists, runFinalized]);

  const currentIdx = steps.findIndex((s) => !s.done);
  const pct = data?.compliance_pct ?? 0;
  const pctTone = pct >= 80 ? "#059669" : pct >= 50 ? "#D97706" : "#DC2626";

  if (!companyId || !month) return null;

  const k = data?.kpis;
  const sp = k?.salary_processed;
  const processedCount = processType === "actual" ? sp?.actual_count : sp?.compliance_count;
  const processedOk = processType === "actual" ? sp?.actual : sp?.compliance;

  return (
    <View style={st.wrap} testID="process-command-center">
      {/* ---------- KPI cards ---------- */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ gap: 8, paddingBottom: 2 }}>
        <Kpi icon="people-outline" label="Total Employees" tone="#2563EB"
          value={k?.total_employees ?? "—"} />
        <Kpi icon="cash-outline" label="Salary Processed" tone={processedOk ? "#059669" : "#64748B"}
          value={processedOk ? processedCount ?? 0 : "Not yet"}
          sub={runFinalized ? "Locked" : processedOk ? "Draft" : undefined} />
        <Kpi icon="briefcase-outline" label="PF Eligible" tone="#7C3AED"
          value={k?.pf_eligible ?? "—"}
          sub={k?.uan_missing ? `${k.uan_missing} UAN missing` : undefined} />
        <Kpi icon="medkit-outline" label="ESIC Eligible" tone="#0891B2"
          value={k?.esic_eligible ?? "—"}
          sub={k?.esic_ip_missing ? `${k.esic_ip_missing} IP missing` : undefined} />
        <Kpi icon="receipt-outline" label="PT Applicable" tone="#D97706"
          value={k?.pt_applicable ?? "—"} />
        <Kpi icon="alert-circle-outline" label="Compliance Errors"
          tone={(k?.compliance_errors ?? 0) > 0 ? "#DC2626" : "#059669"}
          value={k?.compliance_errors ?? "—"} />
        {processType === "compliance" && (
          <Kpi icon="documents-outline" label="Challans Pending"
            tone={(k?.challans?.pending ?? 0) > 0 ? "#EA580C" : "#059669"}
            value={k?.challans?.pending ?? "—"}
            sub={k ? `PF ${k.challans.pf_uploaded ? "✓" : "•"} · ESIC ${k.challans.esic_uploaded ? "✓" : "•"}` : undefined} />
        )}
      </ScrollView>

      {/* ---------- Workflow stepper ---------- */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        contentContainerStyle={st.stepperRow}>
        {steps.map((s, i) => {
          const state = s.done ? "done" : i === currentIdx ? "current" : "pending";
          const tone = state === "done" ? "#059669" : state === "current" ? colors.brandPrimary : "#94A3B8";
          return (
            <View key={s.label} style={st.stepItem}>
              <View style={[st.stepDot,
                { borderColor: tone, backgroundColor: state === "done" ? tone : "#fff" }]}>
                {state === "done" ? (
                  <Ionicons name="checkmark" size={11} color="#fff" />
                ) : (
                  <Text style={[st.stepNum, { color: tone }]}>{i + 1}</Text>
                )}
              </View>
              <Text style={[st.stepLabel, { color: tone },
                state === "current" && { fontWeight: "800" }]} numberOfLines={1}>
                {s.label}
              </Text>
              {i < steps.length - 1 && (
                <View style={[st.stepLine, s.done && { backgroundColor: "#059669" }]} />
              )}
            </View>
          );
        })}
      </ScrollView>

      {/* ---------- Validation panel ---------- */}
      <Pressable style={st.valHead} onPress={() => setShowChecks((v) => !v)}
        testID="pcc-validation-toggle">
        <Ionicons name="shield-checkmark-outline" size={15} color={pctTone} />
        <Text style={st.valTitle}>
          Compliance Validation — {loading ? "…" : `${pct}%`}
        </Text>
        {loading ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : null}
        <View style={st.valBarTrack}>
          <View style={[st.valBarFill, { width: `${Math.min(pct, 100)}%`, backgroundColor: pctTone }]} />
        </View>
        <Ionicons name={showChecks ? "chevron-up" : "chevron-down"} size={15}
          color={colors.textSecondary} />
      </Pressable>
      {showChecks && (
        <View style={st.checksWrap} testID="pcc-checks">
          {(data?.checks || []).map((c) => (
            <View key={c.key} style={st.checkRow}>
              <Ionicons
                name={c.na ? "remove-circle-outline" : c.ok ? "checkmark-circle" : "close-circle"}
                size={14}
                color={c.na ? "#94A3B8" : c.ok ? "#059669" : "#DC2626"} />
              <Text style={st.checkLabel}>{c.label}</Text>
              <Text style={st.checkNote} numberOfLines={1}>{c.note}</Text>
            </View>
          ))}
          {!data && !loading ? (
            <Text style={st.checkNote}>Pick a firm + month to run the live validation.</Text>
          ) : null}
        </View>
      )}
    </View>
  );
}

const st = StyleSheet.create({
  wrap: {
    marginTop: 10, padding: 12, borderRadius: radius.lg, gap: 10,
    backgroundColor: colors.surfaceSecondary ?? "#FFFFFF",
    borderWidth: 1, borderColor: colors.border ?? "#E2E8F0",
  },
  kpi: {
    flexDirection: "row", alignItems: "center", gap: 8,
    minWidth: 158, paddingHorizontal: 10, paddingVertical: 9,
    borderRadius: 12, borderWidth: 1, borderColor: colors.border ?? "#E2E8F0",
    backgroundColor: colors.surface,
  },
  kpiIcon: { width: 28, height: 28, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  kpiValue: { fontSize: 15.5, fontWeight: "800", color: colors.textPrimary },
  kpiLabel: { fontSize: 10.5, fontWeight: "600", color: colors.textSecondary },
  kpiSub: { fontSize: 9.5, fontWeight: "700" },

  stepperRow: { alignItems: "center", paddingVertical: 2 },
  stepItem: { flexDirection: "row", alignItems: "center" },
  stepDot: {
    width: 20, height: 20, borderRadius: 10, borderWidth: 1.6,
    alignItems: "center", justifyContent: "center",
  },
  stepNum: { fontSize: 10, fontWeight: "800" },
  stepLabel: { fontSize: 10.5, fontWeight: "600", marginLeft: 5, maxWidth: 118 },
  stepLine: { width: 22, height: 2, backgroundColor: "#E2E8F0", marginHorizontal: 7, borderRadius: 1 },

  valHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  valTitle: { fontSize: 12, fontWeight: "800", color: colors.textPrimary },
  valBarTrack: {
    flex: 1, height: 7, borderRadius: 4, backgroundColor: "#EDF2F7",
    overflow: "hidden", marginHorizontal: 4,
  },
  valBarFill: { height: 7, borderRadius: 4 },

  checksWrap: {
    borderTopWidth: 1, borderTopColor: colors.border ?? "#E2E8F0",
    paddingTop: 8, gap: 5,
  },
  checkRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  checkLabel: { fontSize: 11.5, fontWeight: "700", color: colors.textPrimary, minWidth: 178 },
  checkNote: { fontSize: 10.5, color: colors.textSecondary, flex: 1 },
});
