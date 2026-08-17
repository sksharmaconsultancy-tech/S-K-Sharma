/**
 * Iter 588 — 🤖 AI COMMAND CENTER.
 * Central AI workspace with five sections:
 *   Ask AI    — conversational EN/HI/Hinglish assistant (same engine as the
 *               floating AI Payroll Assistant: /admin/ai-assistant/command)
 *   Approvals — Maker-Checker queue (reuses /admin/approvals) + risk chips
 *   Alerts    — rule-based payroll/HR/compliance alert engine (server-side
 *               scoped; CRITICAL / WARNING / INFO)
 *   Insights  — automatic KPIs + month-over-month payroll comparison
 *   Activity  — immutable AI audit trail + own chat history
 * SECURITY: every tab calls scoped backend endpoints — the AI never sees
 * data outside the logged-in user's firm/branch/department authorization.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, Platform, Pressable, ScrollView, StyleSheet,
  Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, apiBinary } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { useLang } from "@/src/i18n";
import { colors, radius, spacing } from "@/src/theme";

type Action =
  | { type: "navigate"; route: string; label?: string }
  | { type: "link"; url: string; label?: string }
  | { type: "download"; endpoint: string; label?: string; filename?: string; auto?: boolean }
  | { type: "confirm_api"; method: string; endpoint: string; body: any;
      label: string; navigate_after?: string; danger?: boolean; success_note?: string };
type Msg = { who: "user" | "assistant"; text: string; action?: Action | null; done?: boolean };

const TABS = ["Ask AI", "Approvals", "Alerts", "Insights", "Activity"] as const;
const QUICK = [
  "Employee count", "Today's attendance", "Salary run status",
  "Show employees with missing bank details", "Total net salary this month",
  "Generate salary register", "Generate bank sheet", "Generate PF ECR",
  "Pending approvals", "Who is absent today?",
];
const SEV_STYLE: Record<string, { bg: string; fg: string; dot: string }> = {
  CRITICAL: { bg: "#FEE2E2", fg: "#B91C1C", dot: "🔴" },
  WARNING: { bg: "#FEF3C7", fg: "#92400E", dot: "🟠" },
  INFO: { bg: "#DBEAFE", fg: "#1D4ED8", dot: "🔵" },
};
const RISK_FG: Record<string, string> = {
  LOW: "#16A34A", MEDIUM: "#CA8A04", HIGH: "#EA580C", CRITICAL: "#DC2626",
};

const notify = (title: string, msg: string) => {
  if (Platform.OS === "web") (globalThis as any).alert?.(`${title}\n${msg}`);
  else Alert.alert(title, msg);
};
const inr = (v: any) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

export default function AiCommandCenterScreen() {
  const router = useRouter();
  const { selectedCompanyId, setSelectedCompanyId } = useSelectedCompany();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Ask AI");

  // ── Ask AI ──
  const [input, setInput] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<ScrollView | null>(null);

  // Iter 590b — voice-first commands (web SpeechRecognition, en-IN/hi-IN):
  // speak "attendance kholo" → auto-submits on the final result → the
  // direct-navigation engine opens the page hands-free.
  const lang = useLang();
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const recRef = useRef<any>(null);
  useEffect(() => {
    if (Platform.OS === "web") {
      const SR = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
      setVoiceSupported(!!SR);
    }
  }, []);

  const toggleVoice = () => {
    if (Platform.OS !== "web") return;
    if (listening) {
      recRef.current?.stop();
      setListening(false);
      return;
    }
    const SR = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
    if (!SR) return;
    const rec = new SR();
    rec.lang = lang === "hi" ? "hi-IN" : "en-IN";
    rec.interimResults = true;
    rec.continuous = false;
    rec.onresult = (ev: any) => {
      let final = "";
      let interim = "";
      for (let i = 0; i < ev.results.length; i++) {
        if (ev.results[i].isFinal) final += ev.results[i][0].transcript;
        else interim += ev.results[i][0].transcript;
      }
      setInput(final || interim);
      if (final) {
        setListening(false);
        void send(final); // hands-free: auto-submit the spoken command
      }
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  };

  const send = async (text: string) => {
    const cmd = text.trim();
    if (!cmd || busy) return;
    setInput("");
    setMsgs((m) => [...m, { who: "user", text: cmd }]);
    setBusy(true);
    try {
      const r = await api<{ reply: string; action: Action | null }>(
        "/admin/ai-assistant/command",
        { method: "POST", body: { text: cmd, company_id: selectedCompanyId || null } });
      setMsgs((m) => [...m, { who: "assistant", text: r.reply, action: r.action }]);
      if (r.action && (r.action as any).auto) setTimeout(() => void runAction(r.action!, -1), 150);
    } catch (e: any) {
      setMsgs((m) => [...m, { who: "assistant", text: e?.message || "Something went wrong. Try again." }]);
    } finally {
      setBusy(false);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 80);
    }
  };

  const runAction = async (a: Action, idx: number) => {
    if (a.type === "navigate") {
      // Iter 590 — firm-scoped navigation: switch the active firm first.
      const navCid = (a as any).company_id;
      if (navCid) setSelectedCompanyId(navCid);
      router.push(a.route as any);
      return;
    }
    if (a.type === "link") { if (Platform.OS === "web") window.open(a.url, "_blank"); return; }
    if (a.type === "download") {
      setBusy(true);
      try {
        const r = await apiBinary(a.endpoint);
        if (Platform.OS === "web" && (r as any).webBlobUrl) {
          const el = document.createElement("a");
          el.href = (r as any).webBlobUrl;
          el.download = a.filename || "report";
          document.body.appendChild(el); el.click(); el.remove();
          setMsgs((m) => [...m, { who: "assistant", text: `✅ Downloaded: ${a.filename || a.label}` }]);
        }
      } catch (e: any) {
        setMsgs((m) => [...m, { who: "assistant", text: `❌ ${e?.message || "Download failed."}` }]);
      } finally { setBusy(false); }
      return;
    }
    // confirm_api — user pressed the confirm button; backend re-validates.
    setBusy(true);
    try {
      const res = await api<any>(a.endpoint, { method: a.method as any, body: a.body });
      if (idx >= 0) setMsgs((m) => m.map((msg, i) => (i === idx ? { ...msg, done: true } : msg)));
      const staged = res?.approval_required;
      setMsgs((m) => [...m, {
        who: "assistant",
        text: staged
          ? `🕐 ${res.message || "Sent for approval — nothing changes until approved."}`
          : (a.success_note || "✅ Done!"),
        action: staged
          ? { type: "navigate", route: "/pending-approvals", label: "Open Pending Approvals" }
          : a.navigate_after
            ? { type: "navigate", route: a.navigate_after, label: "View Result" } : null,
      }]);
    } catch (e: any) {
      setMsgs((m) => [...m, { who: "assistant", text: `❌ ${e?.message || "Action failed."}` }]);
    } finally {
      setBusy(false);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 80);
    }
  };

  // ── Approvals / Alerts / Insights / Activity data ──
  const [approvals, setApprovals] = useState<any[]>([]);
  const [alerts, setAlerts] = useState<any>(null);
  const [sevFilter, setSevFilter] = useState<string>("");
  const [insights, setInsights] = useState<any>(null);
  const [period, setPeriod] = useState("this_month");
  const [activity, setActivity] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const cidQ = selectedCompanyId ? `company_id=${selectedCompanyId}` : "";

  const loadTab = useCallback(async (t: string, p: string) => {
    setLoading(true);
    try {
      if (t === "Approvals") {
        const r = await api<any>(`/admin/approvals?status=PENDING${cidQ ? `&${cidQ}` : ""}`);
        setApprovals(r.approvals || []);
      } else if (t === "Alerts") {
        setAlerts(await api<any>(`/admin/ai-cc/alerts${cidQ ? `?${cidQ}` : ""}`));
      } else if (t === "Insights") {
        setInsights(await api<any>(
          `/admin/ai-cc/insights?period=${p}${cidQ ? `&${cidQ}` : ""}`));
      } else if (t === "Activity") {
        setActivity(await api<any>(`/admin/ai-cc/activity`));
      }
    } catch (e: any) { notify("Failed", e?.message || "Could not load"); }
    finally { setLoading(false); }
  }, [cidQ]);
  useEffect(() => { void loadTab(tab, period); }, [tab, period, loadTab]);

  const decide = async (id: string, decision: "approve" | "reject") => {
    try {
      await api(`/admin/approvals/${id}/decide`, { method: "POST", body: { decision } });
      notify(decision === "approve" ? "Approved" : "Rejected",
        decision === "approve" ? "The change has been applied." : "Original data stays unchanged.");
      void loadTab("Approvals", period);
    } catch (e: any) { notify("Failed", e?.message || "Decision failed"); }
  };

  const fmtAt = (iso?: string) => {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return `${d.toLocaleDateString("en-IN")} ${d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`;
    } catch { return iso; }
  };

  const kpi = (label: string, value: any, icon: any, tint = colors.brandPrimary) => (
    <View style={st.kpi} key={label}>
      <Ionicons name={icon} size={16} color={tint} />
      <Text style={st.kpiVal}>{value}</Text>
      <Text style={st.kpiLbl}>{label}</Text>
    </View>
  );

  return (
    <SafeAreaView style={st.root} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} style={{ padding: 6 }}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.h1}>🤖 AI Command Center</Text>
          <Text style={st.sub}>Ask anything about your payroll — scoped to your access</Text>
        </View>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        style={{ flexGrow: 0 }} contentContainerStyle={st.tabs}>
        {TABS.map((t) => (
          <Pressable key={t} onPress={() => setTab(t)}
            style={[st.tab, tab === t && st.tabOn]} testID={`aicc-tab-${t.replace(" ", "")}`}>
            <Text style={[st.tabTxt, tab === t && st.tabTxtOn]}>{t}</Text>
          </Pressable>
        ))}
      </ScrollView>

      {/* ── ASK AI ── */}
      {tab === "Ask AI" ? (
        <View style={{ flex: 1 }}>
          <ScrollView ref={scrollRef} contentContainerStyle={{ padding: spacing.lg, gap: 8 }}>
            {msgs.length === 0 ? (
              <View style={st.block}>
                <Text style={st.blockTitle}>💬 What would you like to do?</Text>
                <Text style={st.line}>
                  English, Hindi ya Hinglish — sab chalega. Try a quick command:
                </Text>
              </View>
            ) : null}
            {msgs.map((m, i) => (
              <View key={i} style={[st.bubble, m.who === "user" ? st.bubbleUser : st.bubbleAi]}>
                <Text style={m.who === "user" ? st.bubbleUserTxt : st.bubbleAiTxt}>
                  {m.text.replace(/\*\*/g, "")}
                </Text>
                {m.action && !m.done && !(m.action as any).auto ? (
                  <Pressable
                    onPress={() => void runAction(m.action!, i)}
                    style={[st.actBtn,
                      m.action.type === "confirm_api" && (m.action as any).danger
                        ? { backgroundColor: "#DC2626" }
                        : m.action.type === "confirm_api"
                          ? { backgroundColor: "#16A34A" } : null]}
                    testID={`aicc-action-${i}`}>
                    <Ionicons
                      name={m.action.type === "confirm_api" ? "checkmark-circle"
                        : m.action.type === "download" ? "download-outline" : "open-outline"}
                      size={14} color="#fff" />
                    <Text style={st.actBtnTxt}>
                      {m.action.type === "confirm_api" ? `Confirm: ${m.action.label}`
                        : m.action.label || "Open"}
                    </Text>
                  </Pressable>
                ) : null}
                {m.done ? <Text style={st.doneTxt}>✓ confirmed</Text> : null}
              </View>
            ))}
            {busy ? <ActivityIndicator color={colors.brandPrimary} /> : null}
          </ScrollView>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}
            style={{ flexGrow: 0 }} contentContainerStyle={{ paddingHorizontal: spacing.lg, gap: 6, paddingVertical: 6 }}>
            {QUICK.map((q) => (
              <Pressable key={q} style={st.chip} onPress={() => void send(q)}
                testID={`aicc-quick-${q.slice(0, 10)}`}>
                <Text style={st.chipTxt}>{q}</Text>
              </Pressable>
            ))}
          </ScrollView>
          <View style={st.inputRow}>
            {voiceSupported ? (
              <Pressable onPress={toggleVoice}
                style={[st.micBtn, listening && st.micBtnOn]}
                testID="aicc-voice">
                <Ionicons name={listening ? "mic" : "mic-outline"} size={18}
                  color={listening ? "#fff" : colors.brandPrimary} />
              </Pressable>
            ) : null}
            <TextInput style={st.input} value={input} onChangeText={setInput}
              placeholder={listening ? "Listening… bol kar command dijiye"
                : 'e.g. "Kankani me kitne employees hain?"'}
              placeholderTextColor={colors.onSurfaceTertiary}
              onSubmitEditing={() => void send(input)} testID="aicc-input" />
            <Pressable style={st.sendBtn} onPress={() => void send(input)} testID="aicc-send">
              <Ionicons name="send" size={16} color="#fff" />
            </Pressable>
          </View>
        </View>
      ) : null}

      {/* ── APPROVALS ── */}
      {tab === "Approvals" ? (
        <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: 10, paddingBottom: 60 }}>
          <Pressable style={st.linkRow} onPress={() => router.push("/pending-approvals" as any)}>
            <Text style={st.linkTxt}>Open full Pending Approvals screen</Text>
            <Ionicons name="chevron-forward" size={14} color={colors.brandPrimary} />
          </Pressable>
          {loading ? <ActivityIndicator color={colors.brandPrimary} /> : null}
          {!loading && approvals.length === 0 ? (
            <Text style={st.empty}>No pending approval requests. ✅</Text>) : null}
          {approvals.map((a) => (
            <View key={a.approval_id} style={st.block}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <Text style={[st.riskChip, { color: RISK_FG[a.risk] || "#CA8A04" }]}>
                  {a.risk}
                </Text>
                <Text style={[st.blockTitle, { flex: 1 }]}>
                  {a.action_label} — {a.target_name}{a.target_code ? ` (${a.target_code})` : ""}
                </Text>
              </View>
              <Text style={st.line}>By {a.maker_name} ({a.maker_role}) · {fmtAt(a.created_at)}</Text>
              {Object.keys(a.new_values || {}).slice(0, 3).map((k) => (
                <Text key={k} style={st.line}>
                  {k}: <Text style={{ color: "#B91C1C" }}>{String((a.old_values || {})[k] ?? "—")}</Text>
                  {"  →  "}
                  <Text style={{ color: "#166534" }}>{String((a.new_values || {})[k] ?? "—")}</Text>
                </Text>
              ))}
              <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
                <Pressable style={[st.smallBtn, { backgroundColor: "#16A34A" }]}
                  onPress={() => void decide(a.approval_id, "approve")}
                  testID={`aicc-approve-${a.approval_id}`}>
                  <Text style={st.smallBtnTxt}>Approve</Text>
                </Pressable>
                <Pressable style={[st.smallBtn, { backgroundColor: "#DC2626" }]}
                  onPress={() => void decide(a.approval_id, "reject")}>
                  <Text style={st.smallBtnTxt}>Reject</Text>
                </Pressable>
                <Pressable style={[st.smallBtn, { backgroundColor: colors.brandPrimary }]}
                  onPress={() => router.push("/pending-approvals" as any)}>
                  <Text style={st.smallBtnTxt}>View Details</Text>
                </Pressable>
              </View>
            </View>
          ))}
        </ScrollView>
      ) : null}

      {/* ── ALERTS ── */}
      {tab === "Alerts" ? (
        <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: 10, paddingBottom: 60 }}>
          <View style={{ flexDirection: "row", gap: 8 }}>
            {["", "CRITICAL", "WARNING", "INFO"].map((s) => (
              <Pressable key={s || "all"} onPress={() => setSevFilter(s)}
                style={[st.tab, sevFilter === s && st.tabOn]} testID={`aicc-sev-${s || "ALL"}`}>
                <Text style={[st.tabTxt, sevFilter === s && st.tabTxtOn]}>
                  {s ? `${SEV_STYLE[s].dot} ${s}` : "All"}
                  {alerts?.counts && s ? ` (${alerts.counts[s] || 0})` : ""}
                </Text>
              </Pressable>
            ))}
          </View>
          {loading ? <ActivityIndicator color={colors.brandPrimary} /> : null}
          {!loading && alerts && alerts.alerts.length === 0 ? (
            <Text style={st.empty}>No alerts — everything looks clean. ✅</Text>) : null}
          {(alerts?.alerts || [])
            .filter((a: any) => !sevFilter || a.severity === sevFilter)
            .map((a: any) => (
              <Pressable key={a.id} style={st.block}
                onPress={() => a.route && router.push(a.route as any)}
                testID={`aicc-alert-${a.id}`}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <View style={[st.sevBadge, { backgroundColor: SEV_STYLE[a.severity]?.bg }]}>
                    <Text style={[st.sevTxt, { color: SEV_STYLE[a.severity]?.fg }]}>
                      {SEV_STYLE[a.severity]?.dot} {a.severity}
                    </Text>
                  </View>
                  <Text style={st.line}>{a.category}</Text>
                  <View style={{ flex: 1 }} />
                  <Text style={st.countTxt}>{a.count}</Text>
                </View>
                <Text style={st.blockTitle}>{a.title}</Text>
                {a.detail ? <Text style={st.line}>{a.detail}</Text> : null}
                {a.sample?.length ? (
                  <Text style={st.line} numberOfLines={2}>e.g. {a.sample.join(", ")}</Text>
                ) : null}
              </Pressable>
            ))}
        </ScrollView>
      ) : null}

      {/* ── INSIGHTS ── */}
      {tab === "Insights" ? (
        <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: 12, paddingBottom: 60 }}>
          <View style={{ flexDirection: "row", gap: 8 }}>
            {[["this_month", "This Month"], ["prev_month", "Previous Month"]].map(([k, l]) => (
              <Pressable key={k} onPress={() => setPeriod(k)}
                style={[st.tab, period === k && st.tabOn]} testID={`aicc-period-${k}`}>
                <Text style={[st.tabTxt, period === k && st.tabTxtOn]}>{l}</Text>
              </Pressable>
            ))}
          </View>
          {loading ? <ActivityIndicator color={colors.brandPrimary} /> : null}
          {insights ? (
            <>
              <Text style={st.section}>👥 Employees</Text>
              <View style={st.kpiRow}>
                {kpi("Active", insights.employees.active, "people-outline")}
                {kpi("Total", insights.employees.total, "person-outline")}
                {kpi("New Joiners", insights.employees.new_joiners, "person-add-outline", "#16A34A")}
                {kpi("Exits", insights.employees.exits, "exit-outline", "#DC2626")}
              </View>
              <Text style={st.section}>💰 Payroll — {insights.month}</Text>
              <View style={st.kpiRow}>
                {kpi("Gross", inr(insights.payroll.month.gross), "cash-outline")}
                {kpi("Net", inr(insights.payroll.month.net), "wallet-outline")}
                {kpi("PF (EE+ER)", inr(insights.payroll.month.pf_employee + insights.payroll.month.pf_employer), "shield-outline")}
                {kpi("ESIC (EE+ER)", inr(insights.payroll.month.esic_employee + insights.payroll.month.esic_employer), "medkit-outline")}
              </View>
              <View style={st.block}>
                <Text style={st.line}>
                  vs {insights.prev_month}: gross {inr(insights.payroll.previous.gross)}
                  {insights.payroll.growth_pct !== null
                    ? ` · growth ${insights.payroll.growth_pct > 0 ? "+" : ""}${insights.payroll.growth_pct}%` : ""}
                </Text>
              </View>
              <Text style={st.section}>🕘 Attendance</Text>
              <View style={st.kpiRow}>
                {kpi("Present Today", insights.attendance.present_today, "checkmark-circle-outline", "#16A34A")}
                {kpi("Present %", `${insights.attendance.present_pct_today}%`, "stats-chart-outline")}
                {kpi("Punch Days (month)", insights.attendance.punch_days_this_month, "calendar-outline")}
              </View>
              <Text style={st.section}>🛡 Compliance</Text>
              <View style={st.kpiRow}>
                {kpi("PF (UAN present)", insights.compliance.pf_eligible, "shield-checkmark-outline")}
                {kpi("ESIC nos present", insights.compliance.esic_eligible, "medkit-outline")}
                {kpi("Missing Aadhaar", insights.compliance.missing_aadhaar, "alert-circle-outline", "#DC2626")}
              </View>
              {insights.employees.by_department?.length ? (
                <View style={st.block}>
                  <Text style={st.blockTitle}>Department-wise employees</Text>
                  {insights.employees.by_department.map((d: any) => (
                    <Text key={d.department} style={st.line}>
                      {d.department}: {d.count}
                    </Text>
                  ))}
                </View>
              ) : null}
            </>
          ) : null}
        </ScrollView>
      ) : null}

      {/* ── ACTIVITY ── */}
      {tab === "Activity" ? (
        <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: 8, paddingBottom: 60 }}>
          {loading ? <ActivityIndicator color={colors.brandPrimary} /> : null}
          {!loading && activity && activity.audit.length === 0 ? (
            <Text style={st.empty}>No AI activity yet.</Text>) : null}
          {(activity?.audit || []).map((r: any, i: number) => (
            <View key={r.log_id || i} style={st.block}>
              <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
                <Ionicons
                  name={r.action === "AI_COMMAND" ? "sparkles-outline" : "checkmark-done-outline"}
                  size={14} color={colors.brandPrimary} />
                <Text style={[st.blockTitle, { flex: 1 }]}>{r.action}</Text>
                <Text style={st.line}>{fmtAt(r.at)}</Text>
              </View>
              <Text style={st.line}>{r.user_name || r.user_id} ({r.role})</Text>
              {r.detail?.command ? (
                <Text style={st.line}>“{r.detail.command}” → {r.detail.intent || "—"}</Text>
              ) : null}
              {r.detail?.approval_id ? (
                <Text style={st.line}>
                  {r.detail.action_type} · {r.detail.target_name || r.detail.target_user_id} · {r.detail.approval_id}
                </Text>
              ) : null}
            </View>
          ))}
        </ScrollView>
      ) : null}
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  h1: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceTertiary },
  tabs: { flexDirection: "row", gap: 8, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  tab: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  tabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtOn: { color: "#fff" },
  empty: { color: colors.onSurfaceTertiary, fontSize: 13, textAlign: "center", marginTop: 30 },
  block: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 12, gap: 4, backgroundColor: colors.surfaceSecondary,
  },
  blockTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  line: { fontSize: 12, color: colors.onSurfaceSecondary },
  section: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface, marginTop: 4 },
  // chat
  bubble: { maxWidth: "88%", borderRadius: radius.md, padding: 10, gap: 6 },
  bubbleUser: { alignSelf: "flex-end", backgroundColor: colors.brandPrimary },
  bubbleAi: {
    alignSelf: "flex-start", backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
  },
  bubbleUserTxt: { color: "#fff", fontSize: 13 },
  bubbleAiTxt: { color: colors.onSurface, fontSize: 13 },
  actBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 8,
  },
  actBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  doneTxt: { color: "#16A34A", fontSize: 11, fontWeight: "700" },
  chip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 99,
    paddingHorizontal: 12, paddingVertical: 7, backgroundColor: colors.surfaceSecondary,
  },
  chipTxt: { fontSize: 12, color: colors.onSurfaceSecondary, fontWeight: "600" },
  inputRow: {
    flexDirection: "row", gap: 8, padding: spacing.lg, paddingTop: 6,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  input: {
    flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 10, color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary, fontSize: 13,
  },
  sendBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 16, justifyContent: "center", minHeight: 44,
  },
  micBtn: {
    width: 44, minHeight: 44, borderRadius: radius.md, alignItems: "center",
    justifyContent: "center", borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  micBtnOn: { backgroundColor: "#DC2626", borderColor: "#DC2626" },
  linkRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  linkTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12.5 },
  smallBtn: { borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 9 },
  smallBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  riskChip: { fontSize: 10.5, fontWeight: "900" },
  sevBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 99 },
  sevTxt: { fontSize: 10, fontWeight: "800" },
  countTxt: { fontSize: 16, fontWeight: "900", color: colors.onSurface },
  kpiRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  kpi: {
    minWidth: 140, flexGrow: 1, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: 12, gap: 2, backgroundColor: colors.surfaceSecondary,
  },
  kpiVal: { fontSize: 16, fontWeight: "900", color: colors.onSurface },
  kpiLbl: { fontSize: 11, color: colors.onSurfaceTertiary },
});
