/**
 * Iter 388 (Phase 4) — PF & ESIC AUDIT DASHBOARD.
 *
 * Per-employee statutory audit of a Compliance Salary run:
 * Code · Name · Gross · Days · PF Wage · EE PF · ER EPF · ER EPS ·
 * ESIC Wage · EE ESIC · ER ESIC · Status (Green OK / Yellow Warning /
 * Red Error) · Reason — plus a per-employee "View Calculation" popup
 * that explains every figure from the stored calculation snapshot.
 *
 * Opened from the Compliance Salary screen ("PF/ESIC Audit" button) with
 * ?run_id=…, or standalone with a run picker.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Modal,
  TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, router } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

const STATUS_UI: Record<string, { bg: string; border: string; text: string; label: string; icon: any }> = {
  ok: { bg: "#F0FDF4", border: "#86EFAC", text: "#166534", label: "OK", icon: "checkmark-circle" },
  warning: { bg: "#FFFBEB", border: "#FCD34D", text: "#92400E", label: "WARNING", icon: "warning" },
  error: { bg: "#FEF2F2", border: "#FCA5A5", text: "#B91C1C", label: "ERROR", icon: "close-circle" },
};

const fmt = (n: any) => Number(n || 0).toLocaleString("en-IN");

export default function PfEsicAuditScreen() {
  const params = useLocalSearchParams<{ run_id?: string }>();
  const [runId, setRunId] = useState<string | null>((params.run_id as string) || null);
  const [runs, setRuns] = useState<any[]>([]);
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [calcRow, setCalcRow] = useState<any | null>(null);
  // Iter 388 (Phase 6) — AI Compliance Assistant explanation.
  const [aiText, setAiText] = useState<string | null>(null);
  const [aiBusy, setAiBusy] = useState(false);

  const aiExplain = async () => {
    if (!runId || !calcRow || aiBusy) return;
    setAiBusy(true);
    setAiText(null);
    try {
      const r = await api<{ explanation: string }>(
        `/admin/compliance-salary-runs/${runId}/ai-explain/${calcRow.user_id}`,
        { method: "POST", body: {} },
      );
      setAiText(r.explanation || "No explanation returned.");
    } catch (e: any) {
      setAiText(`AI explanation failed: ${e?.message || "unknown error"}`);
    } finally { setAiBusy(false); }
  };

  // Run picker (when opened without a run_id).
  useEffect(() => {
    if (runId) return;
    (async () => {
      try {
        const r = await api<any>("/admin/compliance-salary-runs");
        setRuns(Array.isArray(r) ? r : r.runs || []);
      } catch (e: any) { setErr(e?.message || "Failed to load runs"); }
    })();
  }, [runId]);

  const load = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    setErr(null);
    try {
      const r = await api<any>(`/admin/compliance-salary-runs/${runId}/audit-dashboard`);
      setData(r);
    } catch (e: any) {
      setErr(e?.message || "Failed to load audit dashboard");
    } finally { setLoading(false); }
  }, [runId]);
  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => {
    let list = data?.rows || [];
    if (statusFilter !== "all") list = list.filter((r: any) => r.status === statusFilter);
    const q = query.trim().toLowerCase();
    if (q) {
      list = list.filter((r: any) =>
        String(r.name || "").toLowerCase().includes(q)
        || String(r.employee_code || "").toLowerCase().includes(q));
    }
    return list;
  }, [data, statusFilter, query]);

  const HeadCell = ({ w, t }: { w: number; t: string }) => (
    <Text style={[styles.hCell, { width: w }]}>{t}</Text>
  );
  const NumCell = ({ w, v }: { w: number; v: any }) => (
    <Text style={[styles.nCell, { width: w }]}>{fmt(v)}</Text>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="audit-back">
          <Ionicons name="arrow-back" size={20} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>PF & ESIC Audit Dashboard</Text>
          {data ? (
            <Text style={styles.sub}>
              {data.month} · {data.summary?.total || 0} employees
              {data.rule_version ? ` · Rule ${data.rule_version}` : ""}
              {data.finalized ? "  🔒 LOCKED" : ""}
            </Text>
          ) : null}
        </View>
        {runId ? (
          <Pressable onPress={load} style={styles.refreshBtn} testID="audit-refresh">
            <Ionicons name="refresh" size={16} color={colors.brandPrimary} />
          </Pressable>
        ) : null}
      </View>

      {err ? (
        <View style={styles.errBox}><Text style={{ color: "#B91C1C", fontSize: 12 }}>{err}</Text></View>
      ) : null}

      {!runId ? (
        <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
          <Text style={{ fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 10 }}>
            Select a Compliance Salary run to audit:
          </Text>
          {runs.map((r) => (
            <Pressable
              key={r.run_id}
              onPress={() => setRunId(r.run_id)}
              style={styles.runItem}
              testID={`audit-run-${r.run_id}`}
            >
              <Ionicons name={r.finalized ? "lock-closed" : "document-text-outline"} size={16}
                color={r.finalized ? "#16A34A" : colors.brandPrimary} />
              <Text style={{ flex: 1, fontSize: 13, fontWeight: "700", color: colors.onSurface }}>
                {r.month} · {r.employees_count ?? "—"} employees
              </Text>
              <Ionicons name="chevron-forward" size={14} color={colors.onSurfaceTertiary} />
            </Pressable>
          ))}
          {runs.length === 0 && !err ? (
            <Text style={{ fontSize: 12, color: colors.onSurfaceSecondary }}>No runs found.</Text>
          ) : null}
        </ScrollView>
      ) : loading ? (
        <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
      ) : data ? (
        <>
          {/* Summary chips + filters */}
          <View style={styles.chipsRow}>
            {(["all", "ok", "warning", "error"] as const).map((s) => {
              const n = s === "all" ? data.summary?.total : data.summary?.[s];
              const ui = STATUS_UI[s];
              const on = statusFilter === s;
              return (
                <Pressable
                  key={s}
                  onPress={() => setStatusFilter(s)}
                  style={[styles.chip,
                    ui && { backgroundColor: ui.bg, borderColor: ui.border },
                    on && { borderWidth: 2, borderColor: colors.brandPrimary }]}
                  testID={`audit-filter-${s}`}
                >
                  <Text style={[styles.chipTxt, ui && { color: ui.text }]}>
                    {s === "all" ? "ALL" : ui.label} · {n ?? 0}
                  </Text>
                </Pressable>
              );
            })}
            <TextInput
              style={styles.search}
              placeholder="Search name / code…"
              placeholderTextColor={colors.onSurfaceTertiary}
              value={query}
              onChangeText={setQuery}
              testID="audit-search"
            />
          </View>
          {(data.global_issues || []).map((g: any, i: number) => (
            <View key={i} style={[styles.errBox, { backgroundColor: g.level === "error" ? "#FEF2F2" : "#FFFBEB" }]}>
              <Text style={{ color: g.level === "error" ? "#B91C1C" : "#92400E", fontSize: 12, fontWeight: "600" }}>
                {g.message}  → {g.suggestion}
              </Text>
            </View>
          ))}

          <ScrollView horizontal showsHorizontalScrollIndicator>
            <View>
              <View style={styles.headRow}>
                <HeadCell w={56} t="Code" />
                <HeadCell w={170} t="Employee" />
                <HeadCell w={80} t="Gross" />
                <HeadCell w={50} t="Days" />
                <HeadCell w={78} t="PF Wage" />
                <HeadCell w={70} t="EE PF" />
                <HeadCell w={70} t="ER EPF" />
                <HeadCell w={70} t="ER EPS" />
                <HeadCell w={84} t="ESIC Wage" />
                <HeadCell w={70} t="EE ESIC" />
                <HeadCell w={70} t="ER ESIC" />
                <HeadCell w={92} t="Status" />
                <HeadCell w={300} t="Reason" />
                <HeadCell w={110} t="" />
              </View>
              <ScrollView style={{ maxHeight: "100%" }} contentContainerStyle={{ paddingBottom: 120 }}>
                {rows.map((r: any) => {
                  const ui = STATUS_UI[r.status] || STATUS_UI.ok;
                  return (
                    <View key={r.user_id} style={[styles.dataRow, { backgroundColor: ui.bg }]}>
                      <Text style={[styles.tCell, { width: 56 }]}>{r.employee_code || "—"}</Text>
                      <Text style={[styles.tCell, { width: 170, fontWeight: "700" }]} numberOfLines={1}>{r.name}</Text>
                      <NumCell w={80} v={r.gross_paid} />
                      <Text style={[styles.nCell, { width: 50 }]}>{r.present_days}</Text>
                      <NumCell w={78} v={r.pf_wages} />
                      <NumCell w={70} v={r.pf_employee} />
                      <NumCell w={70} v={r.pf_employer_epf} />
                      <NumCell w={70} v={r.pf_employer_eps} />
                      <NumCell w={84} v={r.esic_wage_base} />
                      <NumCell w={70} v={r.esic_employee} />
                      <NumCell w={70} v={r.esic_employer} />
                      <View style={{ width: 92, flexDirection: "row", alignItems: "center", gap: 4 }}>
                        <Ionicons name={ui.icon} size={13} color={ui.text} />
                        <Text style={{ fontSize: 10.5, fontWeight: "800", color: ui.text }}>{ui.label}</Text>
                      </View>
                      <Text style={[styles.tCell, { width: 300, fontSize: 10.5 }]} numberOfLines={2}>
                        {r.reason}
                      </Text>
                      <Pressable
                        onPress={() => { setAiText(null); setCalcRow(r); }}
                        style={styles.viewBtn}
                        testID={`audit-view-${r.user_id}`}
                      >
                        <Ionicons name="calculator-outline" size={12} color={colors.brandPrimary} />
                        <Text style={styles.viewBtnTxt}>View Calc</Text>
                      </Pressable>
                    </View>
                  );
                })}
                {rows.length === 0 ? (
                  <Text style={{ padding: 20, fontSize: 12, color: colors.onSurfaceSecondary }}>
                    No employees match the current filter.
                  </Text>
                ) : null}
              </ScrollView>
            </View>
          </ScrollView>
        </>
      ) : null}

      {/* ---- "View Calculation" explanation popup ---- */}
      <Modal visible={!!calcRow} transparent animationType="fade"
        onRequestClose={() => { setCalcRow(null); setAiText(null); }}>
        <View style={styles.mBackdrop}>
          <View style={styles.mSheet}>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <Text style={{ fontSize: 15, fontWeight: "800", color: colors.onSurface }}>
                🧮 Calculation — {calcRow?.name}
              </Text>
              <Pressable onPress={() => { setCalcRow(null); setAiText(null); }} hitSlop={10} testID="calc-close">
                <Ionicons name="close" size={18} color={colors.onSurfaceSecondary} />
              </Pressable>
            </View>
            <ScrollView style={{ maxHeight: 480 }}>
              {calcRow ? (() => {
                const s = calcRow.calc_snapshot || {};
                const pf = s.pf || {};
                const es = s.esic || {};
                const heads = s.heads_considered || {};
                const Row = ({ l, v }: { l: string; v: any }) => (
                  <View style={styles.calcRow}>
                    <Text style={styles.calcLbl}>{l}</Text>
                    <Text style={styles.calcVal}>{v}</Text>
                  </View>
                );
                return (
                  <>
                    <Text style={styles.calcSection}>Overview</Text>
                    <Row l="Gross Salary (earned)" v={`₹${fmt(calcRow.gross_paid)}`} />
                    <Row l="Paid Days" v={String(calcRow.present_days)} />
                    <Row l="Rule Version" v={s.rule_version || "—"} />
                    <Row l="Wage Definition Rule" v={s.wage_definition_rule === false ? "OFF (Head Mapping)" : "ON — max(Basic, floor% Gross)"} />
                    <Row l="Wage Floor %" v={`${s.stat_wage_floor_pct ?? 50}%`} />

                    <Text style={styles.calcSection}>Salary Heads Considered</Text>
                    {Object.keys(heads).map((k) => (
                      <View key={k} style={styles.calcRow}>
                        <Text style={styles.calcLbl}>{k.toUpperCase()}</Text>
                        <Text style={styles.calcVal}>
                          ₹{fmt(heads[k]?.amount)}
                          {"   "}PF {heads[k]?.pf_wage ? "✓" : "✗"} · ESIC {heads[k]?.esic_wage ? "✓" : "✗"}
                        </Text>
                      </View>
                    ))}

                    <Text style={styles.calcSection}>Provident Fund</Text>
                    <Row l="PF Basic (master)" v={`₹${fmt(pf.pf_basic_master)}`} />
                    <Row l="PF Basic (prorated)" v={`₹${fmt(pf.pf_basic_prorated)}`} />
                    <Row l="Proration Method" v={s.pf_proration_method || "calendar_days"} />
                    <Row l="Wage Base" v={`₹${fmt(pf.wage_base)}`} />
                    <Row l="PF Ceiling" v={`₹${fmt(pf.ceiling)}`} />
                    <Row l="PF Wages (final)" v={`₹${fmt(calcRow.pf_wages)}`} />
                    <Row l={`Employee PF @ ${pf.rate_employee ?? 12}%`} v={`₹${fmt(calcRow.pf_employee)}`} />
                    <Row l={`Employer EPF @ ${pf.rate_epf ?? 3.67}%`} v={`₹${fmt(calcRow.pf_employer_epf)}`} />
                    <Row l={`Employer EPS @ ${pf.rate_eps ?? 8.33}%`} v={`₹${fmt(calcRow.pf_employer_eps)}`} />
                    <Text style={styles.calcReason}>{calcRow.pf_reason || "—"}</Text>

                    <Text style={styles.calcSection}>ESIC</Text>
                    <Row l="Eligibility Basic" v={`₹${fmt(es.eligibility_basic)}`} />
                    <Row l="ESIC Ceiling" v={`₹${fmt(es.ceiling)}`} />
                    <Row l="Proration Method" v={s.esic_proration_method || "calendar_days"} />
                    <Row l="ESIC Wage Base" v={`₹${fmt(calcRow.esic_wage_base)}`} />
                    <Row l={`Employee ESIC @ ${es.rate_employee ?? 0.75}%`} v={`₹${fmt(calcRow.esic_employee)}`} />
                    <Row l={`Employer ESIC @ ${es.rate_employer ?? 3.25}%`} v={`₹${fmt(calcRow.esic_employer)}`} />
                    <Text style={styles.calcReason}>{calcRow.esic_reason || "—"}</Text>

                    <Text style={styles.calcSection}>Validation Result</Text>
                    {(calcRow.issues || []).length === 0 ? (
                      <Text style={[styles.calcReason, { color: "#166534" }]}>✓ No issues — all checks passed.</Text>
                    ) : (
                      (calcRow.issues || []).map((is: any, i: number) => (
                        <Text key={i} style={[styles.calcReason, { color: is.level === "error" ? "#B91C1C" : "#92400E" }]}>
                          {is.level === "error" ? "✗" : "⚠"} [{is.code}] {is.message} → {is.suggestion}
                        </Text>
                      ))
                    )}
                  </>
                );
              })() : null}
              {calcRow && !calcRow.calc_snapshot ? (
                <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 8 }}>
                  This run was calculated before the snapshot feature — re-run Salary Process to
                  capture the full calculation snapshot.
                </Text>
              ) : null}

              {/* Iter 388 (Phase 6) — AI Compliance Assistant */}
              <Pressable
                onPress={aiExplain}
                disabled={aiBusy}
                style={styles.aiBtn}
                testID="calc-ai-explain"
              >
                {aiBusy ? <ActivityIndicator size="small" color="#fff" /> : (
                  <Ionicons name="sparkles" size={14} color="#fff" />
                )}
                <Text style={{ fontSize: 12.5, fontWeight: "800", color: "#fff" }}>
                  {aiBusy ? "AI is analysing…" : "AI Explain (why PF/ESIC was or wasn't calculated)"}
                </Text>
              </Pressable>
              {aiText ? (
                <View style={styles.aiBox}>
                  <Text style={{ fontSize: 11.5, color: colors.onSurface, lineHeight: 17 }}>{aiText}</Text>
                </View>
              ) : null}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F4F7F7" },
  headerRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingHorizontal: spacing.lg, paddingVertical: 12,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 1 },
  refreshBtn: {
    padding: 8, borderRadius: 8, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  errBox: {
    backgroundColor: "#FEE2E2", borderRadius: radius.md, padding: 10,
    marginHorizontal: spacing.lg, marginTop: 8,
  },
  runItem: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, padding: 14, marginBottom: 8,
  },
  chipsRow: {
    flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap",
    paddingHorizontal: spacing.lg, paddingVertical: 10,
  },
  chip: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipTxt: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceSecondary },
  search: {
    flexGrow: 1, minWidth: 160, borderWidth: 1, borderColor: colors.border,
    borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, fontSize: 12,
    backgroundColor: colors.surface, color: colors.onSurface,
  },
  headRow: {
    flexDirection: "row", backgroundColor: "#0F172A",
    paddingVertical: 8, paddingHorizontal: 8,
  },
  hCell: { fontSize: 10, fontWeight: "800", color: "#E2E8F0", paddingHorizontal: 4 },
  dataRow: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 7, paddingHorizontal: 8,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: "#E2E8F0",
  },
  tCell: { fontSize: 11, color: colors.onSurface, paddingHorizontal: 4 },
  nCell: { fontSize: 11, color: colors.onSurface, paddingHorizontal: 4, textAlign: "right" },
  viewBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 5, marginLeft: 6,
  },
  viewBtnTxt: { fontSize: 10.5, fontWeight: "800", color: colors.brandPrimary },
  mBackdrop: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.45)",
    alignItems: "center", justifyContent: "center", padding: 20,
  },
  mSheet: {
    backgroundColor: colors.surface, borderRadius: 16, padding: 16,
    width: "100%", maxWidth: 560, maxHeight: "88%",
    borderWidth: 1, borderColor: colors.border,
  },
  calcSection: {
    fontSize: 12.5, fontWeight: "800", color: colors.brandPrimary,
    marginTop: 12, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.4,
  },
  calcRow: {
    flexDirection: "row", justifyContent: "space-between", gap: 12,
    paddingVertical: 3, borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  calcLbl: { fontSize: 11.5, color: colors.onSurfaceSecondary, flexShrink: 1 },
  calcVal: { fontSize: 11.5, fontWeight: "700", color: colors.onSurface },
  calcReason: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 4, fontStyle: "italic" },
  aiBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: "#7C3AED", borderRadius: radius.md,
    paddingVertical: 11, marginTop: 14,
  },
  aiBox: {
    backgroundColor: "#F5F3FF", borderWidth: 1, borderColor: "#DDD6FE",
    borderRadius: radius.md, padding: 12, marginTop: 10,
  },
});
