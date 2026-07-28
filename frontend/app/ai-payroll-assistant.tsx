/**
 * AI Payroll Assistant (Iter 346) — dashboard for the AI layer.
 * Widgets: Payroll Health, Compliance Score, Risk, AI Alerts, Attendance
 * Issues, Payroll Errors, Pending Compliance (green/yellow/red cards).
 * Tabs: Overview (trends, forecast, calendar, insights, recommendations),
 * Compliance Checker (findings + Apply Fix + 👍/👎 learning feedback),
 * Auditor (severity groups + PDF/Excel export), Attendance, Salary Diff,
 * Reconciliation. Keyboard: Alt+1..6 switch tabs, R = re-analyse.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { showToast } from "@/src/utils/confirm";

const SEV_COLORS: Record<string, string> = {
  critical: "#DC2626", high: "#EA580C", medium: "#CA8A04", low: "#16A34A",
};
const RISK: Record<string, { bg: string; fg: string; label: string }> = {
  green: { bg: "#DCFCE7", fg: "#166534", label: "SAFE" },
  yellow: { bg: "#FEF9C3", fg: "#854D0E", label: "NEEDS REVIEW" },
  red: { bg: "#FEE2E2", fg: "#991B1B", label: "ACTION REQUIRED" },
};
const TABS = ["Overview", "Compliance Checker", "Auditor", "Attendance", "Salary Diff", "Reconciliation"];

const fmtInr = (n?: number | null) => `₹${Math.round(Number(n) || 0)}`;

function scoreColor(v: number) {
  return v >= 85 ? RISK.green : v >= 60 ? RISK.yellow : RISK.red;
}

function monthShift(m: string, d: number) {
  const [y, mm] = m.split("-").map(Number);
  const t = new Date(y, mm - 1 + d, 1);
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}`;
}

export default function AiPayrollAssistant() {
  const router = useRouter();
  const { selectedCompanyId, companies } = useSelectedCompany() as any;
  const firm = (companies || []).find((c: any) => c.company_id === selectedCompanyId);
  const now = new Date();
  const [month, setMonth] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`);
  const [tab, setTab] = useState(0);
  const [busy, setBusy] = useState(false);
  const [ana, setAna] = useState<any>(null);
  const [diff, setDiff] = useState<any>(null);

  const load = useCallback(async (refresh = false) => {
    if (!selectedCompanyId) return;
    setBusy(true);
    try {
      const r = await api<any>(
        `/admin/ai/analysis?company_id=${selectedCompanyId}&month=${month}${refresh ? "&refresh=1" : ""}`);
      setAna(r);
    } catch (e: any) {
      showToast(e?.message || "AI analysis failed");
    } finally { setBusy(false); }
  }, [selectedCompanyId, month]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (tab === 4 && selectedCompanyId) {
      api<any>(`/admin/ai/salary-diff?company_id=${selectedCompanyId}&month=${month}`)
        .then(setDiff).catch(() => setDiff(null));
    }
  }, [tab, selectedCompanyId, month]);

  // Shortcuts: Alt+1..6 tabs, R re-analyse
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const onKey = (e: any) => {
      const tag = (e.target?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      if (e.altKey && e.key >= "1" && e.key <= "6") { e.preventDefault(); setTab(Number(e.key) - 1); }
      else if (e.key.toLowerCase() === "r" && !e.ctrlKey && !e.metaKey) load(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [load]);

  const applyFix = async (f: any) => {
    try {
      const r = await api<any>("/admin/ai/apply-fix", {
        method: "POST",
        body: { company_id: selectedCompanyId, month, finding_id: f.finding_id },
      });
      if (r.applied) { showToast(`✅ ${r.detail}`); await load(); }
      else {
        showToast(r.detail);
        if (r.fix_route) router.push(r.fix_route as any);
      }
    } catch (e: any) { showToast(e?.message || "Apply Fix failed"); }
  };

  const feedback = async (f: any, verdict: string) => {
    try {
      await api("/admin/ai/feedback", {
        method: "POST",
        body: { company_id: selectedCompanyId, finding_key: f.key, verdict },
      });
      showToast(verdict === "false_positive"
        ? "Marked false positive — I won't flag this again (learning engine)."
        : "Thanks — feedback recorded.");
      if (verdict === "false_positive") await load(true);
    } catch (e: any) { showToast(e?.message || "Feedback failed"); }
  };

  const download = async (kind: "pdf" | "xlsx") => {
    try {
      const r = await apiBinary(
        `/admin/ai/audit-report.${kind}?company_id=${selectedCompanyId}&month=${month}`);
      if (Platform.OS === "web" && r.webBlobUrl) {
        const el = document.createElement("a");
        el.href = r.webBlobUrl;
        el.download = `ai-audit-${firm?.name || "firm"}-${month}.${kind}`;
        document.body.appendChild(el); el.click(); el.remove();
      }
    } catch (e: any) { showToast(e?.message || "Export failed"); }
  };

  const s = ana?.scores || {};
  const findings: any[] = ana?.findings || [];
  const attFindings = findings.filter((f) =>
    ["missing_punch", "duplicate_punch", "continuous_working", "ot_anomaly"].includes(f.code));
  const risk = RISK[s.risk_level || "yellow"] || RISK.yellow;

  const Card = ({ label, value, tone }: { label: string; value: any; tone: any }) => (
    <View style={[st.card, { backgroundColor: tone.bg }]}>
      <Text style={[st.cardVal, { color: tone.fg }]}>{value}</Text>
      <Text style={[st.cardLbl, { color: tone.fg }]}>{label}</Text>
    </View>
  );

  const Finding = ({ f }: { f: any }) => (
    <View style={st.finding} testID={`ai-finding-${f.code}`}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <View style={[st.sevPill, { backgroundColor: SEV_COLORS[f.severity] }]}>
          <Text style={st.sevPillTxt}>{f.severity.toUpperCase()}</Text>
        </View>
        <Text style={st.fIssue}>{f.issue}</Text>
        {f.employee ? <Text style={st.fEmp}>{f.employee}</Text> : null}
        <View style={st.confWrap}>
          <View style={[st.confBar, { width: `${f.confidence}%` as any }]} />
          <Text style={st.confTxt}>{f.confidence}%</Text>
        </View>
      </View>
      <Text style={st.fLine}><Text style={st.fKey}>Reason: </Text>{f.reason}</Text>
      <Text style={st.fLine}><Text style={st.fKey}>Impact: </Text>{f.impact}</Text>
      <Text style={st.fLine}><Text style={st.fKey}>Fix: </Text>{f.fix}</Text>
      <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
        <Pressable onPress={() => applyFix(f)} style={[st.btn, { backgroundColor: f.fixable ? "#16A34A" : "#2563EB" }]}
          testID={`ai-fix-${f.finding_id}`}>
          <Ionicons name={f.fixable ? "construct" : "open-outline"} size={12} color="#fff" />
          <Text style={st.btnTxt}>{f.fixable ? "Apply Fix" : "Open & Fix"}</Text>
        </Pressable>
        <Pressable onPress={() => feedback(f, "correct")} style={[st.btn, st.btnGhost]}>
          <Text style={st.btnGhostTxt}>👍 Correct</Text>
        </Pressable>
        <Pressable onPress={() => feedback(f, "false_positive")} style={[st.btn, st.btnGhost]}>
          <Text style={st.btnGhostTxt}>👎 False positive</Text>
        </Pressable>
      </View>
    </View>
  );

  const trends: any[] = ana?.trends || [];
  const maxNet = Math.max(1, ...trends.map((t) => Math.abs(t.net || 0)));

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#F8FAFC" }}>
      <ScrollView contentContainerStyle={{ padding: 16, gap: 12 }}>
        <View style={st.headRow}>
          <View>
            <Text style={st.h1}>🤖 AI Payroll Assistant</Text>
            <Text style={st.sub}>
              {firm?.name || "Select a firm"} · {month} · AI analyses, recommends & explains —
              changes only after your approval. Shortcuts: Alt+1…6 tabs · R re-analyse
            </Text>
          </View>
          <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
            <Pressable onPress={() => setMonth(monthShift(month, -1))} style={st.monBtn}><Text style={st.monTxt}>◀</Text></Pressable>
            <Text style={st.monLbl}>{month}</Text>
            <Pressable onPress={() => setMonth(monthShift(month, 1))} style={st.monBtn}><Text style={st.monTxt}>▶</Text></Pressable>
            <Pressable onPress={() => load(true)} style={[st.btn, { backgroundColor: "#0F172A" }]} testID="ai-reanalyse">
              <Ionicons name="refresh" size={13} color="#fff" />
              <Text style={st.btnTxt}>Re-analyse</Text>
            </Pressable>
          </View>
        </View>

        {busy && !ana ? <ActivityIndicator size="large" color="#2563EB" style={{ marginTop: 40 }} /> : null}
        {ana ? (
          <>
            <View style={st.cardRow}>
              <Card label="Payroll Health" value={s.payroll_health} tone={scoreColor(s.payroll_health || 0)} />
              <Card label="Compliance Score" value={s.compliance_score} tone={scoreColor(s.compliance_score || 0)} />
              <Card label="Risk Level" value={risk.label} tone={risk} />
              <Card label="AI Alerts" value={s.ai_alerts} tone={s.ai_alerts ? RISK.red : RISK.green} />
              <Card label="Attendance Issues" value={s.attendance_issues} tone={s.attendance_issues ? RISK.yellow : RISK.green} />
              <Card label="Payroll Errors" value={s.payroll_errors} tone={s.payroll_errors ? RISK.red : RISK.green} />
              <Card label="Pending Compliance" value={s.pending_compliance} tone={s.pending_compliance ? RISK.yellow : RISK.green} />
            </View>

            <View style={st.tabRow}>
              {TABS.map((t, i) => (
                <Pressable key={t} onPress={() => setTab(i)}
                  style={[st.tab, tab === i && st.tabOn]} testID={`ai-tab-${i}`}>
                  <Text style={[st.tabTxt, tab === i && st.tabTxtOn]}>{t}
                    {i === 1 ? ` (${findings.length})` : i === 3 ? ` (${attFindings.length})` : ""}
                  </Text>
                </Pressable>
              ))}
            </View>

            {tab === 0 ? (
              <View style={{ gap: 12 }}>
                <View style={st.panel}>
                  <Text style={st.pTitle}>💡 AI Recommendations</Text>
                  {(ana.recommendations || []).map((r: any, i: number) => (
                    <Text key={i} style={st.fLine}>
                      • {r.text}  <Text style={{ color: "#64748B" }}>({r.confidence}%)</Text>
                    </Text>
                  ))}
                  {!ana.recommendations?.length ? <Text style={st.fLine}>All clear ✅</Text> : null}
                </View>
                <View style={st.panel}>
                  <Text style={st.pTitle}>📈 Payroll & Labour Cost Trend (Net)</Text>
                  {trends.map((t) => (
                    <View key={t.month} style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 }}>
                      <Text style={{ width: 62, fontSize: 11, color: "#475569" }}>{t.month}</Text>
                      <View style={{ flex: 1, height: 14, backgroundColor: "#F1F5F9", borderRadius: 4 }}>
                        <View style={{
                          width: `${Math.min(100, Math.abs(t.net) / maxNet * 100)}%` as any,
                          height: 14, borderRadius: 4,
                          backgroundColor: t.net >= 0 ? "#2563EB" : "#DC2626",
                        }} />
                      </View>
                      <Text style={{ width: 90, fontSize: 11, fontWeight: "700", color: "#0F172A", textAlign: "right" }}>
                        {fmtInr(t.net)} · {t.employees} emp
                      </Text>
                    </View>
                  ))}
                </View>
                {ana.forecast?.next_month_net !== undefined ? (
                  <View style={st.panel}>
                    <Text style={st.pTitle}>🔮 AI Payroll Forecast <Text style={{ fontSize: 10, color: "#64748B" }}>({ana.forecast.basis})</Text></Text>
                    <Text style={st.fLine}>• Next month Net: <Text style={st.bold}>{fmtInr(ana.forecast.next_month_net)}</Text> · Yearly: <Text style={st.bold}>{fmtInr(ana.forecast.yearly_net)}</Text></Text>
                    <Text style={st.fLine}>• PF liability: {fmtInr(ana.forecast.next_month_pf)} · ESIC: {fmtInr(ana.forecast.next_month_esic)} · Bonus provision (yr): {fmtInr(ana.forecast.bonus_provision)}</Text>
                  </View>
                ) : null}
                <View style={st.panel}>
                  <Text style={st.pTitle}>📅 AI Compliance Calendar</Text>
                  {(ana.calendar || []).map((c: any, i: number) => (
                    <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 }}>
                      <View style={[st.sevPill, {
                        backgroundColor: c.status === "overdue" ? "#DC2626" : c.status === "soon" ? "#CA8A04" : "#16A34A",
                      }]}>
                        <Text style={st.sevPillTxt}>{c.due}</Text>
                      </View>
                      <Text style={[st.fLine, { marginTop: 0, flex: 1 }]}>{c.what}
                        {c.days_left >= 0 ? `  (${c.days_left}d left)` : "  (OVERDUE)"}
                      </Text>
                    </View>
                  ))}
                </View>
                {(ana.insights || []).map((ins: any, i: number) => (
                  <View key={i} style={st.panel}>
                    <Text style={st.pTitle}>📊 {ins.title}</Text>
                    {ins.lines.map((l: string, j: number) => <Text key={j} style={st.fLine}>• {l}</Text>)}
                  </View>
                ))}
              </View>
            ) : null}

            {tab === 1 ? (
              <View style={{ gap: 8 }}>
                {ana.suppressed_count ? (
                  <Text style={st.sub}>🧠 Learning engine: {ana.suppressed_count} previously-marked false positives are hidden.</Text>
                ) : null}
                {findings.map((f) => <Finding key={f.finding_id} f={f} />)}
                {!findings.length ? <Text style={st.fLine}>No issues found ✅</Text> : null}
              </View>
            ) : null}

            {tab === 2 ? (
              <View style={{ gap: 8 }}>
                <View style={{ flexDirection: "row", gap: 8 }}>
                  {(["critical", "high", "medium", "low"] as const).map((sv) => (
                    <View key={sv} style={[st.card, { backgroundColor: "#fff", borderWidth: 1, borderColor: SEV_COLORS[sv] }]}>
                      <Text style={[st.cardVal, { color: SEV_COLORS[sv] }]}>{ana.severity_counts?.[sv] || 0}</Text>
                      <Text style={[st.cardLbl, { color: SEV_COLORS[sv] }]}>{sv.toUpperCase()}</Text>
                    </View>
                  ))}
                  <Pressable onPress={() => download("pdf")} style={[st.btn, { backgroundColor: "#DC2626", alignSelf: "center" }]} testID="ai-export-pdf">
                    <Ionicons name="document-outline" size={13} color="#fff" /><Text style={st.btnTxt}>Audit PDF</Text>
                  </Pressable>
                  <Pressable onPress={() => download("xlsx")} style={[st.btn, { backgroundColor: "#16A34A", alignSelf: "center" }]} testID="ai-export-xlsx">
                    <Ionicons name="grid-outline" size={13} color="#fff" /><Text style={st.btnTxt}>Audit Excel</Text>
                  </Pressable>
                </View>
                {findings.filter((f) => ["critical", "high"].includes(f.severity)).map((f) => <Finding key={f.finding_id} f={f} />)}
              </View>
            ) : null}

            {tab === 3 ? (
              <View style={{ gap: 8 }}>
                {attFindings.map((f) => <Finding key={f.finding_id} f={f} />)}
                {!attFindings.length ? <Text style={st.fLine}>No attendance anomalies detected for {month} ✅</Text> : null}
              </View>
            ) : null}

            {tab === 4 ? (
              <View style={{ gap: 8 }}>
                <View style={st.panel}>
                  <Text style={st.pTitle}>🧾 Salary Difference — {diff?.month} vs {diff?.prev_month}</Text>
                  <Text style={st.fLine}>{diff?.summary || "Loading…"}</Text>
                </View>
                {(diff?.rows || []).slice(0, 60).map((r: any, i: number) => (
                  <View key={i} style={st.finding}>
                    <Text style={st.fIssue}>{r.name} (Code {r.employee_code}) —{" "}
                      <Text style={{ color: r.net_diff >= 0 ? "#16A34A" : "#DC2626" }}>
                        {r.net_diff >= 0 ? "+" : ""}{fmtInr(r.net_diff)}
                      </Text>
                    </Text>
                    <Text style={st.fLine}>{(r.reasons || []).join(" · ")}</Text>
                  </View>
                ))}
              </View>
            ) : null}

            {tab === 5 ? (
              <View style={{ gap: 8 }}>
                {(ana.reconciliation?.items || []).map((it: any, i: number) => (
                  <View key={i} style={st.finding}>
                    <Text style={st.fIssue}>⚖️ {it.kind.replace(/_/g, " ").toUpperCase()} — {it.count}</Text>
                    <Text style={st.fLine}>{it.detail}</Text>
                  </View>
                ))}
                {ana.reconciliation?.ok ? <Text style={st.fLine}>Everything reconciles ✅</Text> : null}
              </View>
            ) : null}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  headRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 },
  h1: { fontSize: 20, fontWeight: "800", color: "#0F172A" },
  sub: { fontSize: 11.5, color: "#64748B", marginTop: 2, maxWidth: 700 },
  monBtn: { width: 28, height: 28, borderRadius: 6, backgroundColor: "#E2E8F0", alignItems: "center", justifyContent: "center" },
  monTxt: { fontSize: 12, color: "#0F172A" },
  monLbl: { fontSize: 13, fontWeight: "800", color: "#0F172A" },
  cardRow: { flexDirection: "row", gap: 10, flexWrap: "wrap" },
  card: { minWidth: 128, borderRadius: 12, paddingVertical: 12, paddingHorizontal: 14, alignItems: "center" },
  cardVal: { fontSize: 20, fontWeight: "900" },
  cardLbl: { fontSize: 10.5, fontWeight: "700", marginTop: 2, textAlign: "center" },
  tabRow: { flexDirection: "row", gap: 6, flexWrap: "wrap" },
  tab: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8, backgroundColor: "#fff", borderWidth: 1, borderColor: "#E2E8F0" },
  tabOn: { backgroundColor: "#0F172A", borderColor: "#0F172A" },
  tabTxt: { fontSize: 12, fontWeight: "700", color: "#334155" },
  tabTxtOn: { color: "#fff" },
  panel: { backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#E2E8F0", padding: 14 },
  pTitle: { fontSize: 13.5, fontWeight: "800", color: "#0F172A", marginBottom: 6 },
  finding: { backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#E2E8F0", padding: 12 },
  sevPill: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3 },
  sevPillTxt: { color: "#fff", fontSize: 10, fontWeight: "800" },
  fIssue: { fontSize: 13, fontWeight: "800", color: "#0F172A" },
  fEmp: { fontSize: 12, color: "#2563EB", fontWeight: "700" },
  fLine: { fontSize: 12, color: "#334155", marginTop: 3, lineHeight: 17 },
  fKey: { fontWeight: "800", color: "#0F172A" },
  bold: { fontWeight: "800", color: "#0F172A" },
  confWrap: { width: 90, height: 12, backgroundColor: "#F1F5F9", borderRadius: 6, overflow: "hidden", justifyContent: "center" },
  confBar: { position: "absolute", left: 0, top: 0, bottom: 0, backgroundColor: "#93C5FD" },
  confTxt: { fontSize: 9, fontWeight: "800", color: "#1E3A8A", textAlign: "center" },
  btn: { flexDirection: "row", alignItems: "center", gap: 5, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 7 },
  btnTxt: { color: "#fff", fontSize: 11.5, fontWeight: "800" },
  btnGhost: { backgroundColor: "#F1F5F9", borderWidth: 1, borderColor: "#E2E8F0" },
  btnGhostTxt: { color: "#334155", fontSize: 11.5, fontWeight: "700" },
});
