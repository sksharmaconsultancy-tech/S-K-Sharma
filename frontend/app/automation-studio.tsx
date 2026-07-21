/**
 * Compliance Automation Studio — Iter 234/235.
 *
 * Runs government-portal automations (EPFO / ESIC / …) on the server and
 * STREAMS a live view into the payroll: every click, field highlight,
 * typing and scroll is visible. CAPTCHA / OTP pause and ask the user for
 * input from inside this screen. Full controls: Start / Pause / Resume /
 * Retry / Skip / Previous / Stop / Emergency Stop.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, getApiBaseUrl, readAuthToken } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing } from "@/src/theme";

type Flow = {
  key: string;
  label: string;
  portals: string[];
  needs_employee: boolean;
  needs_run: boolean;
};
type Portal = { key: string; label: string; url: string };
type Employee = { user_id: string; name?: string; employee_code?: string };
type Run = { run_id: string; month: string; status?: string };

type Session = {
  session_id: string;
  status: string;
  message: string;
  progress: number;
  current_step: number;
  current_url?: string | null;
  network?: string;
  browser?: string;
  frame_b64?: string | null;
  captcha_b64?: string | null;
  input_needed?: { kind: string; prompt: string } | null;
  steps: { index: number; name: string; status: string }[];
  logs: { t: string; msg: string; level: string }[];
  elapsed_sec: number;
  eta_sec?: number | null;
  portal_label?: string;
  flow_label?: string;
  company_name?: string;
  employee?: { name?: string } | null;
  run_month?: string | null;
  validation?: any;
  downloads?: { tag: string; file: string }[];
  job_id?: string;
  video?: string | null;
  error?: string | null;
};

const STATUS_COLOR: Record<string, string> = {
  running: "#16A34A",
  paused: "#D97706",
  completed: "#16A34A",
  failed: "#DC2626",
  stopped: "#6B7280",
};

const fmtDuration = (s?: number | null) => {
  if (!s || s < 0) return "0s";
  const m = Math.floor(s / 60);
  const ss = s % 60;
  return m > 0 ? `${m}m ${ss}s` : `${ss}s`;
};

export default function AutomationStudioScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";
  const { selectedCompanyId, setSelectedCompanyId } = useSelectedCompany() as any;
  const companyId = isSuper ? selectedCompanyId : user?.company_id;

  const [flows, setFlows] = useState<Flow[]>([]);
  const [portals, setPortals] = useState<Portal[]>([]);
  const [portal, setPortal] = useState<string>("epfo");
  const [flow, setFlow] = useState<string>("login");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [empId, setEmpId] = useState<string>("");
  const [empSearch, setEmpSearch] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState<string>("");
  const [speed, setSpeed] = useState<string>("normal");
  const [validation, setValidation] = useState<any>(null);

  const [session, setSession] = useState<Session | null>(null);
  const [sid, setSid] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [inputVal, setInputVal] = useState("");
  const [tab, setTab] = useState<"run" | "history">("run");
  const [history, setHistory] = useState<any[]>([]);
  const [baseUrl, setBaseUrl] = useState("");
  const [token, setToken] = useState("");

  const pollRef = useRef<any>(null);

  useEffect(() => {
    setBaseUrl(getApiBaseUrl());
    readAuthToken().then((t) => setToken(t || ""));
  }, []);

  // ---- Catalog + selectors ----------------------------------------------
  useEffect(() => {
    api<{ portals: Portal[]; flows: Flow[] }>("/rpa/catalog")
      .then((r) => {
        setPortals(r.portals || []);
        setFlows(r.flows || []);
      })
      .catch(() => {});
  }, []);

  const portalFlows = flows.filter((f) => f.portals.includes(portal));
  const activeFlow = flows.find((f) => f.key === flow);

  useEffect(() => {
    // Ensure the selected flow is valid for the current portal.
    if (portalFlows.length && !portalFlows.find((f) => f.key === flow)) {
      setFlow(portalFlows[0].key);
    }
  }, [portal, flows]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load employees when a flow needs one.
  useEffect(() => {
    if (!companyId || !activeFlow?.needs_employee) return;
    api<{ employees: Employee[] }>(
      `/admin/employees?company_id=${companyId}&limit=2000`,
    )
      .then((r) => setEmployees(r.employees || []))
      .catch(() => setEmployees([]));
  }, [companyId, activeFlow?.needs_employee]);

  // Load compliance runs when a flow needs one.
  useEffect(() => {
    if (!companyId || !activeFlow?.needs_run) return;
    api<{ runs: Run[] }>(`/rpa/runs?company_id=${companyId}`)
      .then((r) => setRuns(r.runs || []))
      .catch(() => setRuns([]));
  }, [companyId, activeFlow?.needs_run]);

  // Pre-flight validation preview.
  useEffect(() => {
    setValidation(null);
    if (!companyId || !activeFlow?.needs_run || !runId) return;
    api<{ report: any; month: string }>("/rpa/validate", {
      method: "POST",
      body: { company_id: companyId, portal, run_id: runId },
    })
      .then((r) => setValidation({ ...r.report, month: r.month }))
      .catch(() => {});
  }, [companyId, portal, runId, activeFlow?.needs_run]);

  // ---- Session polling ---------------------------------------------------
  const poll = useCallback(async (id: string) => {
    try {
      const s = await api<Session>(`/rpa/session/${id}`);
      setSession(s);
      if (["completed", "failed", "stopped"].includes(s.status)) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
      }
    } catch {
      /* keep polling */
    }
  }, []);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const start = async () => {
    if (!companyId) {
      setErr("Select a firm first.");
      return;
    }
    setErr("");
    setBusy(true);
    setSession(null);
    try {
      const r = await api<{ session_id: string }>("/rpa/start", {
        method: "POST",
        body: {
          company_id: companyId,
          portal,
          flow,
          employee_id: activeFlow?.needs_employee ? empId : undefined,
          run_id: activeFlow?.needs_run ? runId : undefined,
          speed,
        },
      });
      setSid(r.session_id);
      await poll(r.session_id);
      pollRef.current = setInterval(() => poll(r.session_id), 1200);
    } catch (e: any) {
      setErr(e?.message || "Failed to start automation");
    } finally {
      setBusy(false);
    }
  };

  const control = async (action: string) => {
    if (!sid) return;
    try {
      await api(`/rpa/session/${sid}/control`, { method: "POST", body: { action } });
      if (action === "stop" || action === "emergency_stop") {
        // keep polling; runner flips to stopped
      } else if (!pollRef.current && !["completed", "failed", "stopped"].includes(session?.status || "")) {
        pollRef.current = setInterval(() => poll(sid), 1200);
      }
    } catch (e: any) {
      setErr(e?.message || "Control failed");
    }
  };

  const submitInput = async () => {
    if (!sid || !inputVal.trim()) return;
    try {
      await api(`/rpa/session/${sid}/input`, {
        method: "POST",
        body: { value: inputVal.trim() },
      });
      setInputVal("");
    } catch (e: any) {
      setErr(e?.message || "Failed to submit");
    }
  };

  const loadHistory = useCallback(() => {
    const q = companyId ? `?company_id=${companyId}` : "";
    api<{ jobs: any[] }>(`/rpa/history${q}`)
      .then((r) => setHistory(r.jobs || []))
      .catch(() => setHistory([]));
  }, [companyId]);

  useEffect(() => {
    if (tab === "history") loadHistory();
  }, [tab, loadHistory]);

  const isLive = session && !["completed", "failed", "stopped"].includes(session.status);
  const needsInput = !!session?.input_needed;

  const filteredEmps = employees
    .filter(
      (e) =>
        !empSearch ||
        (e.name || "").toLowerCase().includes(empSearch.toLowerCase()) ||
        (e.employee_code || "").toLowerCase().includes(empSearch.toLowerCase()),
    )
    .slice(0, 30);

  const mediaUrl = (file: string) =>
    `${baseUrl}/rpa/media/${session?.job_id}/${file}?token=${encodeURIComponent(token)}`;

  return (
    <SafeAreaView style={st.root} edges={["top"]}>
      {/* Header */}
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={8} style={st.iconBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.title}>Compliance Automation Studio</Text>
          <Text style={st.subtitle}>Live government-portal automation</Text>
        </View>
        <View style={st.tabRow}>
          {(["run", "history"] as const).map((t) => (
            <Pressable
              key={t}
              onPress={() => setTab(t)}
              style={[st.tab, tab === t && st.tabActive]}
            >
              <Text style={[st.tabTxt, tab === t && st.tabTxtActive]}>
                {t === "run" ? "Run" : "History"}
              </Text>
            </Pressable>
          ))}
        </View>
      </View>

      {isSuper && (
        <View style={st.pickerWrap}>
          <CompanyPicker
            value={selectedCompanyId || "all"}
            onChange={(v) => setSelectedCompanyId(v === "all" ? null : v)}
            allowAll={false}
            label="Firm (required)"
          />
        </View>
      )}

      {tab === "history" ? (
        <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: spacing.lg }}>
          <Pressable style={st.refreshBtn} onPress={loadHistory}>
            <Ionicons name="refresh" size={16} color={colors.primary} />
            <Text style={st.refreshTxt}>Refresh</Text>
          </Pressable>
          {history.length === 0 ? (
            <Text style={st.muted}>No automation jobs yet.</Text>
          ) : (
            history.map((j) => (
              <View key={j.job_id} style={st.histCard}>
                <View style={st.histTop}>
                  <Text style={st.histTitle}>
                    {j.portal_label} · {j.flow_label}
                  </Text>
                  <View
                    style={[
                      st.statusPill,
                      { backgroundColor: (STATUS_COLOR[j.status] || "#6B7280") + "22" },
                    ]}
                  >
                    <Text style={[st.statusTxt, { color: STATUS_COLOR[j.status] || "#6B7280" }]}>
                      {j.status}
                    </Text>
                  </View>
                </View>
                <Text style={st.histMeta}>
                  {j.company_name || j.company_id} · {j.run_month || j.employee?.name || "—"}
                </Text>
                <Text style={st.histMeta}>
                  {(j.started_at || "").slice(0, 16).replace("T", " ")} · by {j.started_by || "—"}
                </Text>
                {j.error ? <Text style={st.histErr}>{j.error}</Text> : null}
                <View style={st.histFiles}>
                  {(j.downloads || []).length > 0 && (
                    <Text style={st.histFileTxt}>
                      ⬇ {(j.downloads || []).length} file(s)
                    </Text>
                  )}
                  {(j.screens || []).length > 0 && (
                    <Text style={st.histFileTxt}>📸 {(j.screens || []).length} shot(s)</Text>
                  )}
                  {j.video && <Text style={st.histFileTxt}>🎬 video</Text>}
                </View>
              </View>
            ))
          )}
        </ScrollView>
      ) : (
        <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: spacing.lg }}>
          {/* Firm selection is MANDATORY before any automation can be set up. */}
          {!companyId && (
            <View style={st.gate}>
              <Ionicons name="business-outline" size={40} color={colors.onSurfaceTertiary} />
              <Text style={st.gateTitle}>Select a firm to continue</Text>
              <Text style={st.gateBody}>
                Choose the firm you want to run the government-portal automation for
                using the “Firm (required)” selector above.
              </Text>
            </View>
          )}
          {/* --- Configuration (hidden while live) --- */}
          {!!companyId && !isLive && (
            <View style={st.card}>
              <Text style={st.cardTitle}>1. Choose Portal</Text>
              <View style={st.chipRow}>
                {portals.map((p) => (
                  <Pressable
                    key={p.key}
                    onPress={() => setPortal(p.key)}
                    style={[st.chip, portal === p.key && st.chipActive]}
                  >
                    <Text style={[st.chipTxt, portal === p.key && st.chipTxtActive]}>
                      {p.key.toUpperCase()}
                    </Text>
                  </Pressable>
                ))}
              </View>

              <Text style={[st.cardTitle, { marginTop: spacing.md }]}>2. Choose Action</Text>
              <View style={st.flowList}>
                {portalFlows.map((f) => (
                  <Pressable
                    key={f.key}
                    onPress={() => setFlow(f.key)}
                    style={[st.flowItem, flow === f.key && st.flowItemActive]}
                  >
                    <Ionicons
                      name={flow === f.key ? "radio-button-on" : "radio-button-off"}
                      size={18}
                      color={flow === f.key ? "#8B5E34" : colors.onSurfaceTertiary}
                    />
                    <Text style={[st.flowTxt, flow === f.key && { color: "#7A4A18", fontWeight: "700" }]}>
                      {f.label}
                    </Text>
                  </Pressable>
                ))}
              </View>

              {activeFlow?.needs_employee && (
                <View style={{ marginTop: spacing.md }}>
                  <Text style={st.cardTitle}>3. Select Employee</Text>
                  <TextInput
                    style={st.search}
                    value={empSearch}
                    onChangeText={setEmpSearch}
                    placeholder="Search name / code…"
                    placeholderTextColor={colors.onSurfaceTertiary}
                  />
                  <View style={st.empList}>
                    {filteredEmps.map((e) => (
                      <Pressable
                        key={e.user_id}
                        onPress={() => setEmpId(e.user_id)}
                        style={[st.empItem, empId === e.user_id && st.empItemActive]}
                      >
                        <Text style={[st.empTxt, empId === e.user_id && { color: "#7A4A18", fontWeight: "700" }]} numberOfLines={1}>
                          {e.employee_code ? `${e.employee_code} · ` : ""}
                          {e.name}
                        </Text>
                        {empId === e.user_id && (
                          <Ionicons name="checkmark-circle" size={18} color="#8B5E34" />
                        )}
                      </Pressable>
                    ))}
                  </View>
                </View>
              )}

              {activeFlow?.needs_run && (
                <View style={{ marginTop: spacing.md }}>
                  <Text style={st.cardTitle}>3. Select Month (Compliance Process)</Text>
                  <View style={st.chipRow}>
                    {runs.map((r) => (
                      <Pressable
                        key={r.run_id}
                        onPress={() => setRunId(r.run_id)}
                        style={[st.chip, runId === r.run_id && st.chipActive]}
                      >
                        <Text style={[st.chipTxt, runId === r.run_id && st.chipTxtActive]}>
                          {r.month}
                        </Text>
                      </Pressable>
                    ))}
                    {runs.length === 0 && (
                      <Text style={st.muted}>No compliance salary processes found.</Text>
                    )}
                  </View>
                  {validation && (
                    <View style={st.valBox}>
                      <Text style={st.valTitle}>Pre-flight Validation</Text>
                      <Text style={st.valRow}>
                        ✅ {validation.included} of {validation.employee_count} employees included
                      </Text>
                      <Text style={st.valRow}>
                        💰 Wages ₹{Number(validation.total_wages || 0).toLocaleString("en-IN")} ·
                        Contribution ₹{Number(validation.total_contribution || 0).toLocaleString("en-IN")}
                      </Text>
                      {(validation.missing_ids || []).length > 0 && (
                        <Text style={[st.valRow, { color: "#DC2626" }]}>
                          ⚠ {validation.missing_ids.length} missing ID(s) — will be skipped
                        </Text>
                      )}
                      {(validation.duplicate_ids || []).length > 0 && (
                        <Text style={[st.valRow, { color: "#DC2626" }]}>
                          ⚠ {validation.duplicate_ids.length} duplicate ID(s)
                        </Text>
                      )}
                    </View>
                  )}
                </View>
              )}

              <Text style={[st.cardTitle, { marginTop: spacing.md }]}>Speed</Text>
              <View style={st.chipRow}>
                {["very_slow", "slow", "normal", "fast"].map((sp) => (
                  <Pressable
                    key={sp}
                    onPress={() => setSpeed(sp)}
                    style={[st.chip, speed === sp && st.chipActive]}
                  >
                    <Text style={[st.chipTxt, speed === sp && st.chipTxtActive]}>
                      {sp.replace("_", " ")}
                    </Text>
                  </Pressable>
                ))}
              </View>

              {err ? <Text style={st.errTxt}>{err}</Text> : null}

              <Pressable
                style={[st.startBtn, busy && { opacity: 0.6 }]}
                onPress={start}
                disabled={busy}
              >
                {busy ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons name="play" size={18} color="#fff" />
                    <Text style={st.startTxt}>Start Automation</Text>
                  </>
                )}
              </Pressable>
              <Text style={st.safety}>
                🔒 CAPTCHA & OTP are never bypassed — you complete them here. Payment
                buttons are never clicked. You confirm before every submission.
              </Text>
            </View>
          )}

          {/* --- LIVE MONITOR --- */}
          {session && (
            <View style={st.card}>
              <View style={st.monitorHead}>
                <View
                  style={[
                    st.statusPill,
                    { backgroundColor: (STATUS_COLOR[session.status] || "#D97706") + "22" },
                  ]}
                >
                  <View
                    style={[
                      st.liveDot,
                      { backgroundColor: STATUS_COLOR[session.status] || "#D97706" },
                    ]}
                  />
                  <Text style={[st.statusTxt, { color: STATUS_COLOR[session.status] || "#D97706" }]}>
                    {session.status.replace("_", " ")}
                  </Text>
                </View>
                <Text style={st.monitorMeta}>
                  {session.portal_label} · {session.flow_label}
                </Text>
                {isLive && (
                  <Pressable style={st.stopTop} onPress={() => control("stop")}>
                    <Ionicons name="stop-circle" size={16} color="#fff" />
                    <Text style={st.stopTopTxt}>Stop</Text>
                  </Pressable>
                )}
              </View>

              {/* Progress */}
              <View style={st.progressTrack}>
                <View style={[st.progressFill, { width: `${session.progress}%` }]} />
              </View>
              <View style={st.metaRow}>
                <Text style={st.metaTxt}>Step {session.current_step + 1}/{session.steps.length}</Text>
                <Text style={st.metaTxt}>{session.progress}%</Text>
                <Text style={st.metaTxt}>⏱ {fmtDuration(session.elapsed_sec)}</Text>
                {session.eta_sec != null && (
                  <Text style={st.metaTxt}>ETA {fmtDuration(session.eta_sec)}</Text>
                )}
              </View>
              <Text style={st.currentMsg}>{session.message}</Text>

              {/* Live frame */}
              <View style={st.frameWrap}>
                {session.frame_b64 ? (
                  <Image
                    source={{ uri: `data:image/jpeg;base64,${session.frame_b64}` }}
                    style={st.frame}
                    resizeMode="contain"
                  />
                ) : (
                  <View style={[st.frame, st.frameEmpty]}>
                    <ActivityIndicator color={colors.primary} />
                    <Text style={st.muted}>Waiting for the live view…</Text>
                  </View>
                )}
              </View>
              {session.current_url ? (
                <Text style={st.urlTxt} numberOfLines={1}>
                  🌐 {session.current_url}
                </Text>
              ) : null}

              {/* CAPTCHA / OTP / confirm input */}
              {needsInput && (
                <View style={st.inputBox}>
                  <Text style={st.inputPrompt}>{session.input_needed?.prompt}</Text>
                  {session.captcha_b64 ? (
                    <Image
                      source={{ uri: `data:image/png;base64,${session.captcha_b64}` }}
                      style={st.captchaImg}
                      resizeMode="contain"
                    />
                  ) : null}
                  <View style={st.inputRow}>
                    <TextInput
                      style={st.input}
                      value={inputVal}
                      onChangeText={setInputVal}
                      placeholder={
                        session.input_needed?.kind === "confirm"
                          ? "Type YES to continue"
                          : "Enter value…"
                      }
                      placeholderTextColor={colors.onSurfaceTertiary}
                      autoCapitalize="characters"
                      autoFocus
                      onSubmitEditing={submitInput}
                    />
                    <Pressable style={st.inputBtn} onPress={submitInput}>
                      <Text style={st.inputBtnTxt}>Submit</Text>
                    </Pressable>
                  </View>
                </View>
              )}

              {/* Controls */}
              <View style={st.controls}>
                {session.status === "paused" ? (
                  <CtrlBtn icon="play" label="Resume" color="#16A34A" onPress={() => control("resume")} />
                ) : (
                  <CtrlBtn icon="pause" label="Pause" color="#D97706" onPress={() => control("pause")} disabled={!isLive} />
                )}
                <CtrlBtn icon="refresh" label="Retry" color={colors.primary} onPress={() => control("retry")} disabled={!isLive} />
                <CtrlBtn icon="play-skip-forward" label="Skip" color={colors.primary} onPress={() => control("skip")} disabled={!isLive} />
                <CtrlBtn icon="play-skip-back" label="Prev" color={colors.primary} onPress={() => control("previous")} disabled={!isLive} />
                <CtrlBtn icon="stop" label="Stop" color="#6B7280" onPress={() => control("stop")} disabled={!isLive} />
                <CtrlBtn icon="warning" label="E-Stop" color="#DC2626" onPress={() => control("emergency_stop")} disabled={!isLive} />
              </View>

              {/* Steps */}
              <View style={st.steps}>
                {session.steps.map((s) => (
                  <View key={s.index} style={st.stepRow}>
                    <Ionicons
                      name={
                        s.status === "done"
                          ? "checkmark-circle"
                          : s.status === "running"
                          ? "sync"
                          : s.status === "failed"
                          ? "close-circle"
                          : s.status === "skipped"
                          ? "arrow-redo-circle"
                          : "ellipse-outline"
                      }
                      size={16}
                      color={
                        s.status === "done"
                          ? "#16A34A"
                          : s.status === "running"
                          ? colors.primary
                          : s.status === "failed"
                          ? "#DC2626"
                          : colors.onSurfaceTertiary
                      }
                    />
                    <Text
                      style={[
                        st.stepTxt,
                        s.status === "running" && { fontWeight: "800", color: colors.onSurface },
                      ]}
                    >
                      {s.name}
                    </Text>
                  </View>
                ))}
              </View>

              {/* Downloads */}
              {(session.downloads || []).length > 0 && (
                <View style={st.dlBox}>
                  <Text style={st.dlTitle}>Documents</Text>
                  {(session.downloads || []).map((d, i) => (
                    <Pressable
                      key={i}
                      onPress={() => {
                        if (Platform.OS === "web") window.open(mediaUrl(d.file), "_blank");
                      }}
                    >
                      <Text style={st.dlLink}>⬇ {d.file.split("/").pop()}</Text>
                    </Pressable>
                  ))}
                </View>
              )}

              {/* Live log */}
              <View style={st.logBox}>
                <Text style={st.logTitle}>Live Log</Text>
                {(session.logs || []).slice(-30).reverse().map((l, i) => (
                  <Text
                    key={i}
                    style={[
                      st.logLine,
                      l.level === "error" && { color: "#DC2626" },
                      l.level === "warn" && { color: "#D97706" },
                    ]}
                  >
                    {l.t} · {l.msg}
                  </Text>
                ))}
              </View>

              {!isLive && (
                <Pressable style={st.newBtn} onPress={() => { setSession(null); setSid(""); }}>
                  <Ionicons name="add" size={18} color={colors.primary} />
                  <Text style={st.newTxt}>New Automation</Text>
                </Pressable>
              )}
            </View>
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function CtrlBtn({
  icon, label, color, onPress, disabled,
}: {
  icon: any; label: string; color: string; onPress: () => void; disabled?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={[st.ctrl, { borderColor: color }, disabled && { opacity: 0.4 }]}
    >
      <Ionicons name={icon} size={18} color={color} />
      <Text style={[st.ctrlTxt, { color }]}>{label}</Text>
    </Pressable>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    gap: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  iconBtn: { padding: 4 },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceSecondary },
  tabRow: { flexDirection: "row", backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: 3 },
  tab: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: radius.sm },
  tabActive: { backgroundColor: colors.surface },
  tabTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtActive: { color: colors.primary },
  pickerWrap: { paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    marginBottom: spacing.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.sm },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: "#FBECD6", borderColor: "#8B5E34" },
  chipTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  chipTxtActive: { color: "#7A4A18" },
  flowList: { gap: 4 },
  flowItem: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 9 },
  flowItemActive: {},
  flowTxt: { fontSize: 13.5, color: colors.onSurfaceSecondary, flex: 1 },
  search: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 9, fontSize: 14, color: colors.onSurface,
    backgroundColor: colors.surface, marginBottom: spacing.sm,
  },
  empList: { gap: 2 },
  empItem: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 12, paddingVertical: 10, borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary, marginBottom: 4,
  },
  empItemActive: { backgroundColor: "#FBECD6" },
  empTxt: { fontSize: 13.5, color: colors.onSurface, flex: 1 },
  gate: { alignItems: "center", paddingVertical: 48, paddingHorizontal: spacing.lg, gap: 10 },
  gateTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  gateBody: { fontSize: 13, color: colors.onSurfaceSecondary, textAlign: "center", lineHeight: 19 },
  valBox: { marginTop: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md },
  valTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 6 },
  valRow: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginBottom: 3 },
  errTxt: { color: "#DC2626", fontSize: 13, fontWeight: "700", marginTop: spacing.md },
  startBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: "#15803D", borderRadius: radius.md, paddingVertical: 13,
    marginTop: spacing.md,
  },
  startTxt: { fontSize: 15, fontWeight: "800", color: "#fff" },
  safety: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: spacing.sm, lineHeight: 16 },
  monitorHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  monitorMeta: { fontSize: 12.5, color: colors.onSurfaceSecondary, flex: 1 },
  stopTop: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: "#DC2626", borderRadius: radius.pill,
    paddingHorizontal: 14, paddingVertical: 7,
  },
  stopTopTxt: { fontSize: 13, fontWeight: "800", color: "#fff" },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 20 },
  liveDot: { width: 8, height: 8, borderRadius: 4 },
  statusTxt: { fontSize: 12, fontWeight: "800", textTransform: "capitalize" },
  progressTrack: { height: 8, backgroundColor: colors.surfaceSecondary, borderRadius: 4, overflow: "hidden", marginTop: 4 },
  progressFill: { height: "100%", backgroundColor: colors.primary, borderRadius: 4 },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: 12, marginTop: 8 },
  metaTxt: { fontSize: 12, color: colors.onSurfaceSecondary, fontWeight: "600" },
  currentMsg: { fontSize: 13.5, color: colors.onSurface, fontWeight: "700", marginTop: 8 },
  frameWrap: {
    marginTop: spacing.md, borderRadius: radius.md, overflow: "hidden",
    backgroundColor: "#111", borderWidth: 1, borderColor: colors.border,
  },
  frame: { width: "100%", aspectRatio: 1280 / 800, backgroundColor: "#000" },
  frameEmpty: { alignItems: "center", justifyContent: "center", gap: 8 },
  urlTxt: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 6 },
  inputBox: {
    marginTop: spacing.md, backgroundColor: "#FEF9C3", borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: "#FACC15",
  },
  inputPrompt: { fontSize: 13.5, fontWeight: "800", color: "#854D0E", marginBottom: spacing.sm },
  captchaImg: { width: 220, height: 70, alignSelf: "center", marginBottom: spacing.sm, backgroundColor: "#fff", borderRadius: 6 },
  inputRow: { flexDirection: "row", gap: 8 },
  input: {
    flex: 1, borderWidth: 1, borderColor: "#FACC15", borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 10, fontSize: 15, fontWeight: "700",
    color: "#111", backgroundColor: "#fff",
  },
  inputBtn: { backgroundColor: "#CA8A04", borderRadius: radius.md, paddingHorizontal: 18, justifyContent: "center" },
  inputBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 14 },
  controls: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: spacing.md },
  ctrl: {
    flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1.5,
    borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 8,
  },
  ctrlTxt: { fontSize: 12.5, fontWeight: "800" },
  steps: { marginTop: spacing.md, gap: 2 },
  stepRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 },
  stepTxt: { fontSize: 13, color: colors.onSurfaceSecondary },
  dlBox: { marginTop: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md },
  dlTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 6 },
  dlLink: { fontSize: 13, color: colors.primary, fontWeight: "700", paddingVertical: 4 },
  logBox: { marginTop: spacing.md, backgroundColor: "#0F172A", borderRadius: radius.md, padding: spacing.md, maxHeight: 220 },
  logTitle: { fontSize: 12, fontWeight: "800", color: "#94A3B8", marginBottom: 6 },
  logLine: { fontSize: 11.5, color: "#CBD5E1", fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace", marginBottom: 2 },
  newBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    marginTop: spacing.md, paddingVertical: 11, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.primary,
  },
  newTxt: { fontSize: 14, fontWeight: "800", color: colors.primary },
  muted: { fontSize: 13, color: colors.onSurfaceTertiary },
  refreshBtn: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-end", marginBottom: spacing.sm },
  refreshTxt: { fontSize: 13, fontWeight: "700", color: colors.primary },
  histCard: {
    backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md,
    marginBottom: spacing.sm, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border,
  },
  histTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  histTitle: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface, flex: 1 },
  histMeta: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 3 },
  histErr: { fontSize: 12, color: "#DC2626", marginTop: 4 },
  histFiles: { flexDirection: "row", gap: 14, marginTop: 6 },
  histFileTxt: { fontSize: 12, color: colors.onSurfaceSecondary, fontWeight: "600" },
});
