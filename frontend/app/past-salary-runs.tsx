/**
 * Past Salary Runs — Iter 91 (Utilities).
 *
 * Per user direction the "Past Actual Runs" list was removed from the
 * bottom of the Salary Process screen and lives here as a separate
 * utility. Two tabs: Actual runs and Compliance runs. Tapping a run
 * opens it on its own process screen (?run_id= deep link).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing } from "@/src/theme";

type RunSummary = {
  run_id: string;
  month: string;
  employees_count?: number;
  finalized?: boolean;
  finalized_at?: string | null;
  finalized_by_name?: string | null;
  attendance_source?: string;
  generated_at?: string;
  generated_by_name?: string | null;
  generated_by_role?: string | null;
  totals?: Record<string, number>;
};

const fmtInr = (n?: number | null) =>
  n === undefined || n === null ? "—" : `₹${Math.round(n).toLocaleString("en-IN")}`;

const fmtDT = (iso?: string | null) => {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const p = (x: number) => String(x).padStart(2, "0");
    return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
  } catch { return iso; }
};

export default function PastSalaryRunsScreen() {
  const { user } = useAuth();
  const isAdmin = ["company_admin", "super_admin", "sub_admin"].includes(user?.role || "");
  const [tab, setTab] = useState<"actual" | "compliance">("actual");
  const [loading, setLoading] = useState(false);
  const [actualRuns, setActualRuns] = useState<RunSummary[]>([]);
  const [compRuns, setCompRuns] = useState<RunSummary[]>([]);
  // User directive — show ONLY the selected firm's runs, never global.
  const { selectedCompanyId, companies } = useSelectedCompany();
  const companyName =
    (companies || []).find((c: any) => c.company_id === selectedCompanyId)?.name || null;

  // Iter 391 (user request) — the compliance run summaries follow the
  // Firm Master's enabled Deductions (Master-linked): disabled heads
  // (PT/TDS/…) are not shown in the list either.
  const [edMask, setEdMask] = useState<string[] | undefined>(undefined);
  useEffect(() => {
    const cid = selectedCompanyId || user?.company_id || null;
    if (!cid) { setEdMask(undefined); return; }
    api<any>(`/admin/firm-master/${cid}`)
      .then((res) => {
        const f = res?.master || {};
        if (!(f.updated_at || f.updated_by)) { setEdMask(undefined); return; }
        const ded = f.deductions || {};
        const epfAp = (f.epf || {}).applicable;
        const esiAp = (f.esi || {}).applicable;
        const ed: string[] = [];
        if (epfAp != null ? epfAp : !!ded.PF) ed.push("pf");
        if (esiAp != null ? esiAp : !!ded.ESI) ed.push("esi");
        if (ded.PT) ed.push("pt");
        if (ded.TDS || ded["I. TAX"]) ed.push("tds");
        setEdMask(ed);
      })
      .catch(() => setEdMask(undefined));
  }, [selectedCompanyId, user?.company_id]);
  const hasDed = (k: string) => !edMask || edMask.includes(k);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const cid = selectedCompanyId || user?.company_id || null;
      const qs = cid ? `?company_id=${encodeURIComponent(cid)}` : "";
      const [a, c] = await Promise.all([
        api<{ runs: RunSummary[] }>(`/admin/salary-runs${qs}`).catch(() => ({ runs: [] })),
        api<{ runs: RunSummary[] }>(`/admin/compliance-salary-runs${qs}`).catch(() => ({ runs: [] })),
      ]);
      setActualRuns(a.runs || []);
      setCompRuns(c.runs || []);
    } finally { setLoading(false); }
  }, [selectedCompanyId, user?.company_id]);

  useEffect(() => { if (isAdmin) load(); }, [isAdmin, load]);

  // User directive — delete salary data, subject to Super Admin approval.
  const doDeleteRun = async (r: RunSummary) => {
    const isSuper = user?.role === "super_admin";
    const q = isSuper
      ? `Delete the ${tab} salary run for ${r.month}? This cannot be undone.`
      : `Request deletion of the ${tab} salary run for ${r.month}?\n\nThe Super Admin must approve it — nothing is deleted until approved.`;
    if (Platform.OS === "web" && !window.confirm(q)) return;
    try {
      const path = tab === "actual"
        ? `/admin/salary-runs/${r.run_id}`
        : `/admin/compliance-salary-runs/${r.run_id}`;
      const res = await api<any>(path, { method: "DELETE" });
      if (res?.approval_required) {
        if (Platform.OS === "web") window.alert(res.message || "Sent to the Super Admin for approval.");
      } else {
        await load();
      }
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Delete failed");
    }
  };

  // Iter 757 (user request — "Past Run ke andar hi do") — sheet version
  // HISTORY per compliance run: every Save-as-Draft / Finalize /
  // Reprocess keeps its own copy that can be viewed & restored here.
  const [histFor, setHistFor] = useState<string | null>(null);
  const [histLoading, setHistLoading] = useState(false);
  const [histVersions, setHistVersions] = useState<any[]>([]);
  const HIST_KIND: Record<string, string> = {
    draft: "💾 Draft Save",
    finalize: "🔒 Finalized",
    pre_reprocess: "♻️ Before Reprocess",
    pre_restore: "↩️ Before Restore",
  };
  const openHistory = async (r: RunSummary) => {
    if (histFor === r.run_id) { setHistFor(null); return; }
    setHistFor(r.run_id);
    setHistLoading(true);
    try {
      const j = await api<{ versions: any[] }>(
        `/admin/compliance-salary-runs/${r.run_id}/versions`);
      setHistVersions(j.versions || []);
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Failed to load history");
      setHistVersions([]);
    }
    setHistLoading(false);
  };
  const restoreVersion = async (r: RunSummary, v: any) => {
    if (r.finalized) {
      if (Platform.OS === "web") window.alert("Run is FINALIZED — unlock it first, then restore a version.");
      return;
    }
    const q = `Restore this version on the ${r.month} sheet?\n\n${HIST_KIND[v.kind] || v.kind} · ${fmtDT(v.saved_at)}\nBy: ${v.saved_by_name || "—"} · Rows: ${v.rows_count} · Net ${fmtInr(v.net_total)}\n\nThe CURRENT sheet is saved to History first — nothing is lost.`;
    if (Platform.OS === "web" && !window.confirm(q)) return;
    try {
      await api(`/admin/compliance-salary-runs/${r.run_id}/versions/${v.version_id}/restore`,
        { method: "POST" });
      if (Platform.OS === "web") window.alert(`Version restored ✓ (${fmtDT(v.saved_at)})`);
      setHistFor(null);
      await load();
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Restore failed");
    }
  };

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

  const runs = tab === "actual" ? actualRuns : compRuns;

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>Past Salary Runs</Text>
            <Text style={styles.hsub}>
              {companyName ? `Firm: ${companyName} — its runs only` : "Utilities · Open, review or reprocess earlier runs"}
            </Text>
          </View>
          <Pressable onPress={load} hitSlop={8}>
            <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
          </Pressable>
        </View>
      </SafeAreaView>

      <View style={styles.tabs}>
        {(["actual", "compliance"] as const).map((t) => (
          <Pressable
            key={t}
            onPress={() => setTab(t)}
            style={[styles.tabBtn, tab === t && styles.tabBtnOn]}
            testID={`psr-tab-${t}`}
          >
            <Text style={[styles.tabTxt, tab === t && styles.tabTxtOn]}>
              {t === "actual" ? "Actual Salary Runs" : "Compliance Salary Runs"}
            </Text>
          </Pressable>
        ))}
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        {loading ? (
          <ActivityIndicator style={{ margin: 40 }} color={colors.brandPrimary} />
        ) : runs.length === 0 ? (
          <View style={styles.center}>
            <Ionicons name="albums-outline" size={36} color={colors.onSurfaceTertiary} />
            <Text style={styles.dimTxt}>No {tab} runs yet.</Text>
          </View>
        ) : (
          <View style={styles.card}>
            {runs.map((r) => (
              <View key={r.run_id}>
              <Pressable
                testID={`psr-run-${r.run_id}`}
                onPress={() =>
                  router.push(
                    tab === "actual"
                      ? `/salary-run?run_id=${encodeURIComponent(r.run_id)}`
                      : `/compliance-salary-run?run_id=${encodeURIComponent(r.run_id)}`,
                  )
                }
                style={styles.row}
              >
                <View style={styles.rowIcon}>
                  <Ionicons
                    name={tab === "actual" ? "cash-outline" : "briefcase-outline"}
                    size={18}
                    color={colors.brandPrimary}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>
                    {r.month}  ·  {r.employees_count ?? "—"} employees
                    {r.finalized ? "  ·  Finalized 🔒" : "  ·  Draft"}
                  </Text>
                  <Text style={styles.rowMeta}>
                    Net {fmtInr(r.totals?.net_pay ?? (r.totals as any)?.net)}
                    {/* Iter 391 — masked head totals for compliance runs */}
                    {tab === "compliance" ? [
                      hasDed("pf") ? `  ·  PF ${fmtInr(r.totals?.pf_employee)}` : "",
                      hasDed("esi") ? `  ·  ESIC ${fmtInr(r.totals?.esic_employee)}` : "",
                      hasDed("pt") ? `  ·  PT ${fmtInr(r.totals?.pt)}` : "",
                      hasDed("tds") ? `  ·  TDS ${fmtInr(r.totals?.tds)}` : "",
                    ].join("") : ""}
                    {r.attendance_source ? `  ·  ${r.attendance_source === "biometric" ? "Biometric" : "Manual"}` : ""}
                  </Text>
                  {(r.generated_at || r.generated_by_name) ? (
                    <Text style={styles.rowMeta}>
                      {fmtDT(r.generated_at)}
                      {r.generated_by_name ? ` · ${r.generated_by_name}` : ""}
                      {r.generated_by_role ? ` (${r.generated_by_role})` : ""}
                    </Text>
                  ) : null}
                </View>
                <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
                {/* Iter 757 (user request) — version History inside Past Runs */}
                {tab === "compliance" ? (
                  <Pressable
                    onPress={(e: any) => { e?.stopPropagation?.(); void openHistory(r); }}
                    hitSlop={10}
                    style={{ marginLeft: 10, padding: 4 }}
                    testID={`psr-hist-${r.run_id}`}
                  >
                    <Ionicons name="time-outline" size={18}
                              color={histFor === r.run_id ? colors.brandPrimary : colors.onSurfaceSecondary} />
                  </Pressable>
                ) : null}
                {/* User directive — delete salary data (super admin approves
                    requests raised by sub/company admins) */}
                <Pressable
                  onPress={(e: any) => { e?.stopPropagation?.(); void doDeleteRun(r); }}
                  hitSlop={10}
                  style={{ marginLeft: 10, padding: 4 }}
                  testID={`psr-del-${r.run_id}`}
                >
                  <Ionicons name="trash-outline" size={17} color="#B0002B" />
                </Pressable>
              </Pressable>
              {histFor === r.run_id ? (
                <View style={styles.histBox}>
                  <Text style={styles.histHead}>
                    Sheet History — {r.month} (har Save / Finalize / Reprocess ka apna version;
                    Restore se wahi data sheet par wapas — current sheet pehle save hoti hai)
                  </Text>
                  {histLoading ? (
                    <ActivityIndicator style={{ marginVertical: 14 }} color={colors.brandPrimary} />
                  ) : histVersions.length === 0 ? (
                    <Text style={styles.dimTxt}>
                      Abhi koi version saved nahi — Save as Draft / Finalize karne par versions yahan dikhenge.
                    </Text>
                  ) : (
                    histVersions.map((v, i) => (
                      <View key={v.version_id}
                            style={[styles.histRow, i === 0 && { backgroundColor: "#F0FDF4" }]}>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.histTitle}>
                            {HIST_KIND[v.kind] || v.kind}{i === 0 ? " · latest" : ""}
                          </Text>
                          <Text style={styles.rowMeta}>
                            {fmtDT(v.saved_at)} · by {v.saved_by_name || "—"} · {v.rows_count} rows · Net {fmtInr(v.net_total)}
                          </Text>
                        </View>
                        <Pressable
                          onPress={() => void restoreVersion(r, v)}
                          testID={`psr-restore-${i}`}
                          style={styles.restoreBtn}
                        >
                          <Text style={styles.restoreTxt}>Restore</Text>
                        </Pressable>
                      </View>
                    ))
                  )}
                </View>
              ) : null}
              </View>
            ))}
          </View>
        )}
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
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
  tabs: {
    flexDirection: "row", gap: 8,
    paddingHorizontal: spacing.md, paddingVertical: 10,
  },
  tabBtn: {
    paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  tabBtnOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtOn: { color: "#fff" },
  scroll: { padding: spacing.md, ...(Platform.OS === "web" ? { maxWidth: 1100, width: "100%", alignSelf: "center" } : {}) },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
    overflow: "hidden",
  },
  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 14, paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  rowIcon: {
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: "#EEF2FF",
    alignItems: "center", justifyContent: "center",
  },
  rowTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  rowMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 1 },
  center: { alignItems: "center", gap: 8, padding: 40 },
  dimTxt: { color: colors.onSurfaceTertiary, fontSize: 13 },
  // Iter 757 — version history box under a compliance run row.
  histBox: {
    backgroundColor: "#F8FAFC",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
    paddingHorizontal: 14, paddingVertical: 10,
  },
  histHead: { fontSize: 11, color: colors.onSurfaceTertiary, marginBottom: 6 },
  histRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 7, paddingHorizontal: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  histTitle: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  restoreBtn: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8,
    backgroundColor: "#EFF6FF", borderWidth: 1, borderColor: "#BFDBFE",
  },
  restoreTxt: { fontSize: 12, fontWeight: "700", color: "#1D4ED8" },
});
