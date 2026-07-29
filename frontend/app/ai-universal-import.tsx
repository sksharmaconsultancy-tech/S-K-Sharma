/**
 * AI Universal Payroll Import (Iter 360).
 * Upload ANY payroll Excel/CSV → "Analyze with AI" → wizard:
 *   1 Upload · 2 AI Analysis (type/company/period/columns) · 3 Validation
 *   & AI Suggestions · 4 Preview & Import · 5 Payroll & Compliance.
 * Plus Dashboard + Learned Templates tabs. M365-style clean cards.
 */
import React, { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Platform,
  StyleSheet,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { shared } from "@/src/components/RegisterTable";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";

const STEPS = ["Upload", "AI Analysis", "Validation", "Preview & Import",
  "Payroll & Compliance"];
const SEV_COLOR: Record<string, string> = {
  valid: "#15803D", warning: "#B45309", error: "#B91C1C",
};
const TARGET_OPTS = [
  ["employee_master", "Employee Master (create/update)"],
  ["attendance_salary", "Attendance + Salary Process (Freeze Sheet)"],
  ["leave", "Leave Register"],
  ["extras", "Bonus / Arrear / Increment"],
] as const;

function Sel({ value, onChange, options, testID, width }: {
  value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[]; testID: string;
  width?: number;
}) {
  if (Platform.OS !== "web") return null;
  return (
    <select data-testid={testID} value={value}
      onChange={(e) => onChange((e.target as HTMLSelectElement).value)}
      style={{ padding: 8, borderRadius: 8, borderColor: "#CBD5E1",
        borderWidth: 1, fontSize: 13, maxWidth: width || 260 } as any}>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

export default function AiUniversalImportScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { companies } = useSelectedCompany();
  const [tab, setTab] = useState<"wizard" | "dashboard" | "templates">(
    "wizard");
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  // wizard state
  const [fileName, setFileName] = useState("");
  const [fileB64, setFileB64] = useState("");
  const [analysis, setAnalysis] = useState<any>(null);
  const [fileType, setFileType] = useState("");
  const [companyId, setCompanyId] = useState("");
  const [month, setMonth] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [valid, setValid] = useState<any>(null);
  const [rowFilter, setRowFilter] = useState("all");
  const [targets, setTargets] = useState<string[]>([
    "employee_master", "attendance_salary"]);
  const [createNew, setCreateNew] = useState(true);
  const [autoPayroll, setAutoPayroll] = useState(true);
  const [job, setJob] = useState<any>(null);
  const [check, setCheck] = useState<any>(null);
  const [aiText, setAiText] = useState("");
  const [dash, setDash] = useState<any>(null);
  const [tpls, setTpls] = useState<any[]>([]);
  const pollRef = useRef<any>(null);

  const isCompanyAdmin = user?.role === "company_admin";

  useEffect(() => () => clearInterval(pollRef.current), []);
  useEffect(() => {
    if (tab === "dashboard")
      api<any>("/admin/ai-import/dashboard").then(setDash).catch(() => {});
    if (tab === "templates")
      api<any>("/admin/ai-import/templates")
        .then((r) => setTpls(r.templates || [])).catch(() => {});
  }, [tab, job]);

  const pickFile = () => {
    if (Platform.OS !== "web") return;
    const inp = document.createElement("input");
    inp.type = "file";
    inp.accept = ".xlsx,.xls,.csv";
    inp.onchange = () => {
      const f = inp.files?.[0];
      if (!f) return;
      const rd = new FileReader();
      rd.onload = () => {
        const b64 = String(rd.result || "").split(",")[1] || "";
        setFileName(f.name);
        setFileB64(b64);
        setErr("");
      };
      rd.readAsDataURL(f);
    };
    inp.click();
  };

  const analyze = async () => {
    if (!fileB64) { setErr("Please choose a file first"); return; }
    setBusy(true); setErr("");
    try {
      const r = await api<any>("/admin/ai-import/analyze", {
        method: "POST",
        body: { filename: fileName, content_base64: fileB64,
          company_id: isCompanyAdmin ? user?.company_id : undefined },
      });
      setAnalysis(r);
      setFileType(r.file_type_candidates?.[0]?.kind || "custom");
      setCompanyId(r.company_matches?.[0]?.company_id
        || (isCompanyAdmin ? user?.company_id : "") || "");
      setMonth(r.period || "");
      const m: Record<string, string> = {};
      Object.entries(r.mapping || {}).forEach(([h, v]: any) => {
        m[h] = v.field;
      });
      setMapping(m);
      setStep(1);
    } catch (e: any) {
      setErr(e?.message || "Analysis failed");
    } finally { setBusy(false); }
  };

  const runValidate = async () => {
    if (!companyId) { setErr("Select the company"); return; }
    if (!/^20\d{2}-\d{2}$/.test(month)) {
      setErr("Enter period as YYYY-MM"); return;
    }
    setBusy(true); setErr("");
    try {
      const r = await api<any>("/admin/ai-import/validate", {
        method: "POST",
        body: { job_id: analysis.job_id, company_id: companyId, month,
          file_type: fileType, mapping },
      });
      setValid(r);
      setStep(2);
    } catch (e: any) {
      setErr(e?.message || "Validation failed");
    } finally { setBusy(false); }
  };

  const runImport = async () => {
    setBusy(true); setErr("");
    try {
      await api("/admin/ai-import/commit", {
        method: "POST",
        body: { job_id: analysis.job_id, targets,
          create_new_employees: createNew, auto_payroll: autoPayroll },
      });
      setStep(4);
      pollRef.current = setInterval(async () => {
        try {
          const j = await api<any>(
            `/admin/ai-import/job/${analysis.job_id}`);
          setJob(j);
          if (j.status === "imported" || j.status === "failed") {
            clearInterval(pollRef.current);
            setBusy(false);
            if (j.status === "imported") {
              const c = await api<any>(
                "/admin/ai-import/compliance-check?company_id="
                + `${j.company_id}&month=${j.month}`);
              setCheck(c);
            }
          }
        } catch {}
      }, 1500);
    } catch (e: any) {
      setErr(e?.message || "Import failed");
      setBusy(false);
    }
  };

  const explain = async () => {
    setAiText("…thinking");
    try {
      const issues = (valid?.rows || [])
        .flatMap((r: any) => r._issues || []).slice(0, 20);
      const r = await api<any>("/admin/ai-import/explain", {
        method: "POST", body: { issues },
      });
      setAiText(r.answer || "");
    } catch (e: any) {
      setAiText(e?.message || "AI unavailable");
    }
  };

  const reset = () => {
    clearInterval(pollRef.current);
    setStep(0); setFileB64(""); setFileName(""); setAnalysis(null);
    setValid(null); setJob(null); setCheck(null); setErr("");
    setAiText(""); setRowFilter("all");
  };

  const dl = async (path: string, name: string) => {
    try {
      const res = await apiBinary(path);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = name;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      if (Platform.OS === "web")
        globalThis.alert(e?.message || "Download failed");
    }
  };

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"]
    .includes(user.role)) return <Redirect href="/" />;

  const filteredRows = (valid?.rows || []).filter((r: any) =>
    rowFilter === "all" ? true
      : rowFilter === "new" ? !r._match
        : rowFilter === "updated" ? !!r._match
          : r._status === rowFilter);

  return (
    <SafeAreaView style={shared.safe} edges={["top"]}>
      <View style={shared.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}
          testID="ai-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={shared.headerTitle}>AI Universal Payroll Import</Text>
        <View style={{ width: 40 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: 12 }}>
        <View style={shared.tabs}>
          {([["wizard", "✨ Import Wizard"], ["dashboard", "Dashboard"],
            ["templates", "Learned Templates"]] as const).map(([k, l]) => (
            <Pressable key={k} onPress={() => setTab(k)}
              style={[shared.tab, tab === k && shared.tabActive]}
              testID={`ai-tab-${k}`}>
              <Text style={[shared.tabTxt,
                tab === k && shared.tabTxtActive]}>{l}</Text>
            </Pressable>
          ))}
        </View>

        {tab === "wizard" && (
          <>
            {/* step indicator */}
            <View style={st.stepsRow}>
              {STEPS.map((s, i) => (
                <View key={s} style={st.stepWrap}>
                  <View style={[st.stepDot, i === step && st.stepDotActive,
                    i < step && st.stepDotDone]}>
                    {i < step ? (
                      <Ionicons name="checkmark" size={13} color="#fff" />
                    ) : (
                      <Text style={[st.stepNum,
                        i === step && { color: "#fff" }]}>{i + 1}</Text>
                    )}
                  </View>
                  <Text style={[st.stepLbl,
                    i === step && st.stepLblActive]}>{s}</Text>
                </View>
              ))}
            </View>
            {!!err && <Text style={st.errTxt} testID="ai-err">{err}</Text>}

            {/* STEP 0 — UPLOAD */}
            {step === 0 && (
              <View style={[shared.card, st.center]}>
                <Ionicons name="cloud-upload-outline" size={44}
                  color={colors.brandPrimary} />
                <Text style={st.h1}>Upload any payroll file</Text>
                <Text style={[shared.meta, { textAlign: "center",
                  maxWidth: 480 }]}>
                  Attendance Register · Salary Register · Employee Master ·
                  PF/ESIC Wage Sheet · OT · Leave · Bank Sheet · Bonus ·
                  Arrear · Increment · Contractor Wages — or any custom
                  Excel/CSV. No column mapping needed, the AI figures it out.
                </Text>
                <Pressable onPress={pickFile} style={st.pickBtn}
                  testID="ai-pick-file">
                  <Ionicons name="document-attach-outline" size={17}
                    color={colors.brandPrimary} />
                  <Text style={st.pickTxt}>
                    {fileName || "Choose Excel / CSV file"}
                  </Text>
                </Pressable>
                <Pressable onPress={analyze} disabled={busy || !fileB64}
                  style={[st.primaryBtn, (!fileB64 || busy)
                    && { opacity: 0.5 }]} testID="ai-analyze">
                  {busy ? <ActivityIndicator size="small" color="#fff" />
                    : (
                      <>
                        <Ionicons name="sparkles" size={16} color="#fff" />
                        <Text style={st.primaryTxt}>Analyze with AI</Text>
                      </>
                    )}
                </Pressable>
              </View>
            )}

            {/* STEP 1 — AI ANALYSIS */}
            {step === 1 && analysis && (
              <>
                <View style={shared.card}>
                  <Text style={shared.cardTitle}>
                    🤖 AI Analysis — {analysis.total_rows} rows
                    {analysis.learned_template
                      ? "  ·  📚 recognised from a learned template" : ""}
                  </Text>
                  <Text style={st.subH}>File Type</Text>
                  <View style={st.chipsRow}>
                    {(analysis.file_type_candidates || []).map((c: any) => (
                      <Pressable key={c.kind}
                        onPress={() => setFileType(c.kind)}
                        style={[st.chip, fileType === c.kind && st.chipOn]}
                        testID={`ai-ft-${c.kind}`}>
                        <Text style={[st.chipTxt,
                          fileType === c.kind && st.chipTxtOn]}>
                          {c.title} ({c.confidence}%)
                        </Text>
                      </Pressable>
                    ))}
                    <Pressable onPress={() => setFileType("custom")}
                      style={[st.chip, fileType === "custom" && st.chipOn]}>
                      <Text style={[st.chipTxt,
                        fileType === "custom" && st.chipTxtOn]}>
                        Custom Format
                      </Text>
                    </Pressable>
                  </View>
                  <View style={[shared.row, { flexWrap: "wrap", gap: 12,
                    marginTop: 10 }]}>
                    <View>
                      <Text style={st.subH}>Company
                        {analysis.company_matches?.length
                          ? `  (AI: ${analysis.company_matches[0].name} `
                            + `${analysis.company_matches[0].confidence}%)`
                          : ""}
                      </Text>
                      <Sel testID="ai-company" value={companyId}
                        onChange={setCompanyId} width={280}
                        options={[{ value: "", label: "— Select Company —" },
                          ...(companies || []).map((c: any) => ({
                            value: c.company_id, label: c.name }))]} />
                    </View>
                    <View>
                      <Text style={st.subH}>Payroll Period (YYYY-MM)
                        {analysis.period ? "  · auto-detected" : ""}
                      </Text>
                      {Platform.OS === "web" && (
                        <input data-testid="ai-month" type="month"
                          value={month}
                          onChange={(e) =>
                            setMonth((e.target as HTMLInputElement).value)}
                          style={{ padding: 8, borderRadius: 8,
                            border: "1px solid #CBD5E1",
                            fontSize: 13 } as any} />
                      )}
                    </View>
                  </View>
                </View>
                <View style={shared.card}>
                  <Text style={shared.cardTitle}>
                    Smart Column Recognition
                  </Text>
                  {(analysis.headers || []).map((h: string) => {
                    const m = analysis.mapping?.[h];
                    const low = m && m.confidence < 90;
                    return (
                      <View key={h} style={[st.mapRow,
                        (!mapping[h] || low) && st.mapRowWarn]}>
                        <Text style={st.mapHdr} numberOfLines={1}>{h}</Text>
                        <Ionicons name="arrow-forward" size={13}
                          color="#94A3B8" />
                        <Sel testID={`ai-map-${h}`} value={mapping[h] || ""}
                          onChange={(v) => setMapping((p) => {
                            const n = { ...p };
                            if (v) n[h] = v; else delete n[h];
                            return n;
                          })} width={220}
                          options={[{ value: "", label: "— ignore —" },
                            ...Object.keys(FIELD_LABELS).map((f) => ({
                              value: f, label: FIELD_LABELS[f] }))]} />
                        <Text style={st.mapConf}>
                          {m ? `${m.confidence}% · ${m.source}`
                            : "not recognised"}
                        </Text>
                      </View>
                    );
                  })}
                </View>
                <View style={st.navRow}>
                  <Pressable onPress={reset} style={st.ghostBtn}>
                    <Text style={st.ghostTxt}>Start Over</Text>
                  </Pressable>
                  <Pressable onPress={runValidate} disabled={busy}
                    style={st.primaryBtn} testID="ai-validate">
                    {busy ? <ActivityIndicator size="small" color="#fff" />
                      : <Text style={st.primaryTxt}>
                          Validate Data →</Text>}
                  </Pressable>
                </View>
              </>
            )}

            {/* STEP 2 — VALIDATION */}
            {step === 2 && valid && (
              <>
                <View style={st.statRow}>
                  {([["Total", valid.summary.total, colors.onSurface],
                    ["Valid", valid.summary.valid, "#15803D"],
                    ["Warnings", valid.summary.warning, "#B45309"],
                    ["Errors", valid.summary.error, "#B91C1C"],
                    ["New Employees", valid.summary.new_employees,
                      "#1D4ED8"],
                    ["Matched", valid.summary.updated_employees,
                      "#0E7490"]] as const).map(([l, v, c]) => (
                    <View key={l} style={st.statCard}>
                      <Text style={[st.statVal, { color: c }]}>{v}</Text>
                      <Text style={st.statLbl}>{l}</Text>
                    </View>
                  ))}
                </View>
                <View style={[shared.row, { flexWrap: "wrap", gap: 6 }]}>
                  {["all", "valid", "warning", "error", "new", "updated"]
                    .map((f) => (
                      <Pressable key={f} onPress={() => setRowFilter(f)}
                        style={[st.chip, rowFilter === f && st.chipOn]}
                        testID={`ai-filter-${f}`}>
                        <Text style={[st.chipTxt,
                          rowFilter === f && st.chipTxtOn]}>
                          {f.toUpperCase()}
                        </Text>
                      </Pressable>
                    ))}
                  <Pressable onPress={explain} style={st.aiBtn}
                    testID="ai-explain">
                    <Ionicons name="sparkles" size={13} color="#7C3AED" />
                    <Text style={st.aiBtnTxt}>Explain issues with AI</Text>
                  </Pressable>
                </View>
                {!!aiText && (
                  <View style={st.aiPanel}>
                    <Text style={st.aiPanelTxt}>{aiText}</Text>
                  </View>
                )}
                <View style={shared.card}>
                  {filteredRows.slice(0, 120).map((r: any) => (
                    <View key={r._row_no} style={st.vRow}>
                      <View style={st.vTop}>
                        <Text style={st.vName}>
                          #{r._row_no} · {r.name || r.employee_code || "—"}
                          {r._match
                            ? `  →  ${r._match.name} `
                              + `(${r._match.via} ${r._match.confidence}%)`
                            : "  →  NEW"}
                        </Text>
                        <Text style={[st.vStatus,
                          { color: SEV_COLOR[r._status] }]}>
                          {r._status.toUpperCase()}
                        </Text>
                      </View>
                      {(r._issues || []).map((i: any, ix: number) => (
                        <Text key={ix} style={[st.vIssue, {
                          color: i.severity === "error"
                            ? "#B91C1C" : "#B45309" }]}>
                          {i.severity === "error" ? "✗" : "⚠"} {i.msg}
                        </Text>
                      ))}
                      {(r._fixes || []).map((f: string, ix: number) => (
                        <Text key={ix} style={st.vFix}>💡 {f}</Text>
                      ))}
                    </View>
                  ))}
                  {filteredRows.length > 120 && (
                    <Text style={shared.meta}>
                      …and {filteredRows.length - 120} more rows
                    </Text>
                  )}
                </View>
                <View style={st.navRow}>
                  <Pressable onPress={() => setStep(1)} style={st.ghostBtn}>
                    <Text style={st.ghostTxt}>← Back to Mapping</Text>
                  </Pressable>
                  <Pressable onPress={() => setStep(3)}
                    style={st.primaryBtn} testID="ai-to-preview">
                    <Text style={st.primaryTxt}>Preview & Import →</Text>
                  </Pressable>
                </View>
              </>
            )}

            {/* STEP 3 — PREVIEW & IMPORT */}
            {step === 3 && valid && (
              <View style={shared.card}>
                <Text style={shared.cardTitle}>One-Click Import</Text>
                <Text style={shared.meta}>
                  {valid.summary.valid + valid.summary.warning} rows will be
                  imported · {valid.summary.error} error rows will be
                  SKIPPED.
                </Text>
                <Text style={[st.subH, { marginTop: 10 }]}>
                  Import into:
                </Text>
                {TARGET_OPTS.map(([k, l]) => (
                  <Pressable key={k}
                    onPress={() => setTargets((p) => p.includes(k)
                      ? p.filter((x) => x !== k) : [...p, k])}
                    style={st.tgtRow} testID={`ai-target-${k}`}>
                    <Ionicons
                      name={targets.includes(k)
                        ? "checkbox" : "square-outline"}
                      size={17}
                      color={targets.includes(k) ? "#15803D" : "#94A3B8"} />
                    <Text style={st.tgtTxt}>{l}</Text>
                  </Pressable>
                ))}
                <Pressable onPress={() => setCreateNew(!createNew)}
                  style={st.tgtRow} testID="ai-create-new">
                  <Ionicons name={createNew ? "checkbox" : "square-outline"}
                    size={17} color={createNew ? "#15803D" : "#94A3B8"} />
                  <Text style={st.tgtTxt}>
                    Create NEW employees for unmatched rows
                    ({valid.summary.new_employees})
                  </Text>
                </Pressable>
                <Pressable onPress={() => setAutoPayroll(!autoPayroll)}
                  style={st.tgtRow} testID="ai-auto-payroll">
                  <Ionicons
                    name={autoPayroll ? "checkbox" : "square-outline"}
                    size={17}
                    color={autoPayroll ? "#15803D" : "#94A3B8"} />
                  <Text style={st.tgtTxt}>
                    AUTO PAYROLL — process Compliance Salary
                    (PF/ESIC/PT/TDS) right after import
                  </Text>
                </Pressable>
                <View style={st.navRow}>
                  <Pressable onPress={() => setStep(2)} style={st.ghostBtn}>
                    <Text style={st.ghostTxt}>← Back</Text>
                  </Pressable>
                  <Pressable onPress={runImport} disabled={busy}
                    style={st.primaryBtn} testID="ai-import-go">
                    {busy ? <ActivityIndicator size="small" color="#fff" />
                      : (
                        <>
                          <Ionicons name="rocket-outline" size={16}
                            color="#fff" />
                          <Text style={st.primaryTxt}>Import Now</Text>
                        </>
                      )}
                  </Pressable>
                </View>
              </View>
            )}

            {/* STEP 4 — PROGRESS + PAYROLL + COMPLIANCE */}
            {step === 4 && (
              <>
                <View style={shared.card}>
                  <Text style={shared.cardTitle}>
                    {job?.status === "imported" ? "✅ Import Complete"
                      : job?.status === "failed" ? "❌ Import Failed"
                        : "⏳ Importing…"}
                  </Text>
                  <View style={st.progressOuter}>
                    <View style={[st.progressInner,
                      { width: `${job?.progress || 2}%` }]} />
                  </View>
                  <Text style={shared.meta} testID="ai-progress-note">
                    {job?.progress_note || "Working…"}
                    {job?.error ? ` — ${job.error}` : ""}
                  </Text>
                  {job?.result && (
                    <View style={st.statRow}>
                      {([["Created", job.result.employees_created],
                        ["Updated", job.result.employees_updated],
                        ["Salary Entries", job.result.entries_written],
                        ["Leaves", job.result.leaves_written],
                        ["Extras", job.result.extras_written],
                        ["Skipped (errors)", job.result.skipped_errors],
                      ] as const).map(([l, v]) => (
                        <View key={l} style={st.statCard}>
                          <Text style={st.statVal}>{v}</Text>
                          <Text style={st.statLbl}>{l}</Text>
                        </View>
                      ))}
                    </View>
                  )}
                </View>
                {job?.payroll && (
                  <View style={shared.card}>
                    <Text style={shared.cardTitle}>
                      💰 Auto Payroll Process
                    </Text>
                    {job.payroll.ok ? (
                      <>
                        <Text style={[shared.meta, { color: "#15803D" }]}>
                          ✓ Compliance salary processed —{" "}
                          {job.payroll.employees} employees
                          (Run {job.payroll.run_id})
                        </Text>
                        {!!job.payroll.totals && (
                          <Text style={shared.meta}>
                            Gross ₹{Number(job.payroll.totals.gross_paid
                              || job.payroll.totals.monthly_gross || 0)
                              .toLocaleString("en-IN")} · PF ₹
                            {Number(job.payroll.totals.pf_employee || 0)
                              .toLocaleString("en-IN")} · ESIC ₹
                            {Number(job.payroll.totals.esic_employee || 0)
                              .toLocaleString("en-IN")} · Net ₹
                            {Number(job.payroll.totals.net || 0)
                              .toLocaleString("en-IN")}
                          </Text>
                        )}
                      </>
                    ) : (
                      <Text style={[shared.meta, { color: "#B91C1C" }]}>
                        Payroll not processed: {job.payroll.error}
                      </Text>
                    )}
                  </View>
                )}
                {check && (
                  <View style={shared.card}>
                    <Text style={shared.cardTitle}>
                      🛡 AI Compliance Check
                      {check.issue_count
                        ? `  —  ${check.issue_count} issue(s)`
                        : "  —  all clear ✓"}
                    </Text>
                    {(check.issues || []).slice(0, 20).map(
                      (i: any, ix: number) => (
                        <Text key={ix} style={[st.vIssue, {
                          color: i.severity === "error"
                            ? "#B91C1C" : "#B45309" }]}>
                          {i.severity === "error" ? "✗" : "⚠"} {i.msg}
                        </Text>
                      ))}
                    <Text style={[st.subH, { marginTop: 8 }]}>
                      Generate Compliance:
                    </Text>
                    <View style={[shared.row, { flexWrap: "wrap", gap: 8 }]}>
                      {(check.artifacts || []).map((a: any) => (
                        <Pressable key={a.label}
                          onPress={() => {
                            if (a.kind === "download")
                              void dl(a.path, "pf_ecr.txt");
                            else if (a.kind === "screen")
                              router.push(a.path);
                            else
                              api(a.path, { method: "POST", body: {} })
                                .catch(() => {});
                          }}
                          style={st.artBtn} testID={`ai-art-${a.label}`}>
                          <Ionicons
                            name={a.kind === "download"
                              ? "download-outline"
                              : a.kind === "screen" ? "open-outline"
                                : "flash-outline"}
                            size={14} color={colors.brandPrimary} />
                          <Text style={st.artTxt}>{a.label}</Text>
                        </Pressable>
                      ))}
                    </View>
                  </View>
                )}
                <View style={st.navRow}>
                  <Pressable onPress={reset} style={st.primaryBtn}
                    testID="ai-new-import">
                    <Text style={st.primaryTxt}>+ New Import</Text>
                  </Pressable>
                </View>
              </>
            )}
          </>
        )}

        {/* ---------------------- DASHBOARD ---------------------- */}
        {tab === "dashboard" && dash && (
          <>
            <View style={st.statRow}>
              {([["Imports", dash.total_jobs],
                ["Success Rate", `${dash.success_rate}%`],
                ["Employees Added", dash.employees_added],
                ["Employees Updated", dash.employees_updated],
                ["Payroll Runs", dash.payroll_runs],
                ["Validation Errors", dash.validation_errors],
                ["Templates Learned", dash.templates_learned],
              ] as const).map(([l, v]) => (
                <View key={l} style={st.statCard}>
                  <Text style={st.statVal}>{v}</Text>
                  <Text style={st.statLbl}>{l}</Text>
                </View>
              ))}
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Recent Imports</Text>
              {(dash.recent_jobs || []).map((j: any) => (
                <View key={j.job_id} style={st.jobRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={st.vName}>{j.filename}</Text>
                    <Text style={shared.meta}>
                      {j.file_type || "—"} · {j.month || "—"} ·{" "}
                      {String(j.created_at || "").slice(0, 16)
                        .replace("T", " ")} · {j.by_name}
                    </Text>
                  </View>
                  <Text style={[st.vStatus, {
                    color: j.status === "imported" ? "#15803D"
                      : j.status === "failed" ? "#B91C1C" : "#B45309" }]}>
                    {String(j.status).toUpperCase()}
                  </Text>
                </View>
              ))}
              {!(dash.recent_jobs || []).length && (
                <Text style={shared.meta}>No imports yet.</Text>
              )}
            </View>
          </>
        )}

        {/* ---------------------- TEMPLATES ---------------------- */}
        {tab === "templates" && (
          <View style={shared.card}>
            <Text style={shared.cardTitle}>
              📚 Learned Client Formats ({tpls.length})
            </Text>
            <Text style={shared.meta}>
              Every successful import teaches the AI the client&apos;s
              Excel format — next month the same file is recognised
              instantly.
            </Text>
            {tpls.map((t) => (
              <View key={t.fingerprint} style={st.jobRow}>
                <View style={{ flex: 1 }}>
                  <Text style={st.vName}>
                    {t.company_name || "—"} · {t.file_type}
                  </Text>
                  <Text style={shared.meta}>
                    {t.filename} · {Object.keys(t.mapping || {}).length}
                    {" "}columns · used {t.uses || 1}×
                  </Text>
                </View>
                <Pressable onPress={async () => {
                  await api(`/admin/ai-import/templates/${t.fingerprint}`,
                    { method: "DELETE" }).catch(() => {});
                  setTpls((p) => p.filter(
                    (x) => x.fingerprint !== t.fingerprint));
                }} hitSlop={8} testID={`ai-tpl-del-${t.fingerprint}`}>
                  <Ionicons name="trash-outline" size={16}
                    color="#B91C1C" />
                </Pressable>
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const FIELD_LABELS: Record<string, string> = {
  employee_code: "Employee Code", name: "Employee Name",
  father_name: "Father/Husband Name", uan_no: "UAN", pf_no: "PF No.",
  esi_ip_no: "ESIC IP No.", aadhaar_no: "Aadhaar", pan_no: "PAN",
  phone: "Mobile", dob: "Date of Birth", doj: "Date of Joining",
  dol: "Date of Leaving", department: "Department",
  designation: "Designation", employee_type: "Employee Type/Category",
  gender: "Gender", bank_account: "Bank Account", bank_ifsc: "IFSC",
  bank_name: "Bank Name", present_days: "Present Days",
  ot_hours: "OT Hours", gross_earning: "Gross Earning", basic: "Basic",
  da: "DA", hra: "HRA", conveyance: "Conveyance", medical: "Medical",
  special: "Special Allowance", other_allowance: "Other Allowance",
  deduction_head: "Deduction Head", deduction_amount: "Deduction/Advance",
  tds: "TDS", pf_employee: "PF Deduction", esic_employee: "ESIC Deduction",
  pf_wages: "PF Wages", esic_wages: "ESIC Wages", net_salary: "Net Salary",
  salary_monthly: "Monthly Salary", rate_daily: "Daily Rate",
  leave_days: "Leave Days", leave_type: "Leave Type",
  leave_from: "Leave From", leave_to: "Leave To",
  bonus_amount: "Bonus Amount", arrear_amount: "Arrear Amount",
  increment_amount: "Increment/Revised Salary", month: "Month",
  remarks: "Remarks",
};

const st = StyleSheet.create({
  stepsRow: { flexDirection: "row", flexWrap: "wrap", gap: 14,
    marginBottom: 14, marginTop: 4 },
  stepWrap: { flexDirection: "row", alignItems: "center", gap: 6 },
  stepDot: { width: 24, height: 24, borderRadius: 12,
    backgroundColor: "#E2E8F0", alignItems: "center",
    justifyContent: "center" },
  stepDotActive: { backgroundColor: colors.brandPrimary },
  stepDotDone: { backgroundColor: "#15803D" },
  stepNum: { fontSize: 11.5, fontWeight: "800", color: "#64748B" },
  stepLbl: { fontSize: 12, color: colors.onSurfaceSecondary },
  stepLblActive: { fontWeight: "800", color: colors.onSurface },
  errTxt: { color: "#B91C1C", fontSize: 12.5, fontWeight: "700",
    marginBottom: 8 },
  center: { alignItems: "center", paddingVertical: 34, gap: 10 },
  h1: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  pickBtn: { flexDirection: "row", gap: 7, alignItems: "center",
    borderWidth: 1.5, borderStyle: "dashed",
    borderColor: colors.brandPrimary, borderRadius: 10,
    paddingHorizontal: 18, paddingVertical: 12, marginTop: 6 },
  pickTxt: { color: colors.brandPrimary, fontWeight: "700",
    fontSize: 13 },
  primaryBtn: { flexDirection: "row", gap: 7, alignItems: "center",
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 20, paddingVertical: 11, justifyContent: "center" },
  primaryTxt: { color: "#fff", fontWeight: "800", fontSize: 13.5 },
  ghostBtn: { borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 16, paddingVertical: 10 },
  ghostTxt: { color: colors.onSurfaceSecondary, fontWeight: "700",
    fontSize: 12.5 },
  navRow: { flexDirection: "row", justifyContent: "space-between",
    marginTop: 12, gap: 10 },
  subH: { fontSize: 11.5, fontWeight: "800",
    color: colors.onSurfaceSecondary, marginBottom: 4, marginTop: 6 },
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { borderWidth: 1, borderColor: colors.border, borderRadius: 16,
    paddingHorizontal: 11, paddingVertical: 6 },
  chipOn: { backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11.5, color: "#475569", fontWeight: "600" },
  chipTxtOn: { color: "#fff" },
  mapRow: { flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 5, borderBottomWidth: 0.5,
    borderBottomColor: colors.border, flexWrap: "wrap" },
  mapRowWarn: { backgroundColor: "#FFFBEB" },
  mapHdr: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface,
    minWidth: 150, maxWidth: 220 },
  mapConf: { fontSize: 10.5, color: "#94A3B8" },
  statRow: { flexDirection: "row", flexWrap: "wrap", gap: 8,
    marginBottom: 10, marginTop: 4 },
  statCard: { flexGrow: 1, minWidth: 105,
    backgroundColor: colors.surface, borderWidth: 1,
    borderColor: colors.border, borderRadius: 12, padding: 11,
    alignItems: "center" },
  statVal: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  statLbl: { fontSize: 10.5, color: colors.onSurfaceSecondary,
    marginTop: 2, textAlign: "center" },
  vRow: { paddingVertical: 7, borderBottomWidth: 0.5,
    borderBottomColor: colors.border },
  vTop: { flexDirection: "row", justifyContent: "space-between",
    alignItems: "center", gap: 8 },
  vName: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface,
    flex: 1 },
  vStatus: { fontSize: 10.5, fontWeight: "800" },
  vIssue: { fontSize: 11.5, marginTop: 2 },
  vFix: { fontSize: 11.5, color: "#7C3AED", marginTop: 2 },
  aiBtn: { flexDirection: "row", gap: 5, alignItems: "center",
    borderWidth: 1, borderColor: "#DDD6FE", backgroundColor: "#F5F3FF",
    borderRadius: 16, paddingHorizontal: 11, paddingVertical: 6 },
  aiBtnTxt: { fontSize: 11.5, color: "#7C3AED", fontWeight: "700" },
  aiPanel: { backgroundColor: "#F5F3FF", borderRadius: 10, padding: 10,
    borderWidth: 1, borderColor: "#DDD6FE", marginTop: 8 },
  aiPanelTxt: { fontSize: 12, color: "#4C1D95", lineHeight: 18 },
  tgtRow: { flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 6 },
  tgtTxt: { fontSize: 12.5, color: colors.onSurface, flex: 1 },
  progressOuter: { height: 10, backgroundColor: "#E2E8F0",
    borderRadius: 6, overflow: "hidden", marginVertical: 8 },
  progressInner: { height: 10, backgroundColor: colors.brandPrimary,
    borderRadius: 6 },
  artBtn: { flexDirection: "row", gap: 5, alignItems: "center",
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 11, paddingVertical: 8,
    backgroundColor: colors.surface },
  artTxt: { fontSize: 11.5, fontWeight: "700",
    color: colors.brandPrimary },
  jobRow: { flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 8, borderBottomWidth: 0.5,
    borderBottomColor: colors.border },
});
