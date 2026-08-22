/**
 * Iter 674 — 🤖 EMAIL AUDIT AGENT tab (AI Command Center · Super Admin only).
 *
 * Phase 1 READ-ONLY dashboard for the backend Email Audit Agent:
 *   Overview  — stats (15-Aug-2026 → today), scan now, agent on/off
 *   Emails    — audited list w/ status & category filters + full detail
 *               (company match, AI analysis, timeline, manual company assign)
 *   Companies — company-wise email summary
 *   Registry  — Company Email Registry (multi email-IDs per firm)
 *   Report    — daily AI report
 *   Settings  — enable/sandbox/threshold/poll + sandbox test ingest
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text,
  TextInput, View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

const SUB = ["Overview", "Emails", "Companies", "Registry", "Report", "Settings"] as const;
const STATUS_META: Record<string, { label: string; bg: string; fg: string }> = {
  ACTION_REQUIRED: { label: "Action Required", bg: "#FEF3C7", fg: "#92400E" },
  URGENT: { label: "Urgent", bg: "#FEE2E2", fg: "#B91C1C" },
  REVIEW_REQUIRED: { label: "Review Required", bg: "#EDE9FE", fg: "#6D28D9" },
  COMPANY_REVIEW_REQUIRED: { label: "Company Review", bg: "#FFEDD5", fg: "#C2410C" },
  INFORMATION_ONLY: { label: "Information Only", bg: "#DBEAFE", fg: "#1D4ED8" },
  PROCESSING_FAILED: { label: "Failed", bg: "#F1F5F9", fg: "#475569" },
};
const FILTERS = ["", "ACTION_REQUIRED", "URGENT", "REVIEW_REQUIRED",
  "COMPANY_REVIEW_REQUIRED", "INFORMATION_ONLY", "PROCESSING_FAILED"];

const toast = (m: string) => {
  if (Platform.OS === "web") (globalThis as any).alert?.(m);
};
const fmtAt = (iso?: string) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("en-IN", { hour12: true }); }
  catch { return iso; }
};

function Badge({ status }: { status: string }) {
  const m = STATUS_META[status] || { label: status, bg: "#F1F5F9", fg: "#475569" };
  return (
    <View style={[st.badge, { backgroundColor: m.bg }]}>
      <Text style={[st.badgeTxt, { color: m.fg }]}>{m.label}</Text>
    </View>
  );
}

export default function EmailAuditTab() {
  const [sub, setSub] = useState<(typeof SUB)[number]>("Overview");
  const [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState<any>(null);
  const [dash, setDash] = useState<any>(null);
  const [emails, setEmails] = useState<any[]>([]);
  const [emailTotal, setEmailTotal] = useState(0);
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<any>(null);
  const [companies, setCompanies] = useState<any[]>([]);
  const [registry, setRegistry] = useState<any[]>([]);
  const [firms, setFirms] = useState<any[]>([]);
  const [report, setReport] = useState<any>(null);
  // registry form
  const [regFirm, setRegFirm] = useState<string>("");
  const [regEmail, setRegEmail] = useState("");
  const [regType, setRegType] = useState("");
  const [regPerson, setRegPerson] = useState("");
  // sandbox form
  const [sbFrom, setSbFrom] = useState("");
  const [sbSubject, setSbSubject] = useState("");
  const [sbBody, setSbBody] = useState("");

  const loadSettings = useCallback(async () => {
    try { setSettings(await api("/email-agent/settings")); } catch { /* noop */ }
  }, []);
  const loadDash = useCallback(async () => {
    try { setDash(await api("/email-agent/dashboard")); } catch { /* noop */ }
  }, []);
  const loadEmails = useCallback(async () => {
    try {
      const qs = new URLSearchParams();
      if (filter) qs.set("status", filter);
      if (search.trim()) qs.set("q", search.trim());
      const r: any = await api(`/email-agent/emails?${qs.toString()}`);
      setEmails(r.emails || []); setEmailTotal(r.total || 0);
    } catch { /* noop */ }
  }, [filter, search]);
  const loadCompanies = useCallback(async () => {
    try { setCompanies(((await api("/email-agent/company-summary")) as any).companies || []); }
    catch { /* noop */ }
  }, []);
  const loadRegistry = useCallback(async () => {
    try {
      setRegistry(((await api("/email-agent/registry")) as any).entries || []);
      const f: any = await api("/companies?lite=1");
      setFirms(f.companies || f || []);
    } catch { /* noop */ }
  }, []);
  const loadReport = useCallback(async () => {
    try { setReport(await api("/email-agent/daily-report")); } catch { /* noop */ }
  }, []);

  useEffect(() => { void loadSettings(); void loadDash(); }, [loadSettings, loadDash]);
  useEffect(() => {
    if (sub === "Emails") void loadEmails();
    if (sub === "Companies") void loadCompanies();
    if (sub === "Registry") void loadRegistry();
    if (sub === "Report") void loadReport();
    if (sub === "Overview") void loadDash();
  }, [sub, loadEmails, loadCompanies, loadRegistry, loadReport, loadDash]);

  const saveSettings = async (patch: any) => {
    setBusy(true);
    try { setSettings(await api("/email-agent/settings", { method: "POST", body: patch })); }
    catch (e: any) { toast(e?.message || "Failed"); }
    setBusy(false);
  };
  const scanNow = async () => {
    setBusy(true);
    try {
      const r: any = await api("/email-agent/scan", { method: "POST", body: {} });
      toast(r.ok
        ? `Scan done — ${r.new_processed} new audited, ${r.ignored_historical} historical ignored`
        : `Scan failed: ${r.error}`);
      void loadDash();
    } catch (e: any) { toast(e?.message || "Scan failed"); }
    setBusy(false);
  };
  const openDetail = async (auditId: string) => {
    try { setDetail(await api(`/email-agent/emails/${auditId}`)); }
    catch { /* noop */ }
  };
  const assignCompany = async (companyId: string) => {
    if (!detail) return;
    try {
      await api(`/email-agent/emails/${detail.audit_id}/assign-company`,
        { method: "POST", body: { company_id: companyId } });
      toast("Company assigned");
      void openDetail(detail.audit_id); void loadEmails();
    } catch (e: any) { toast(e?.message || "Failed"); }
  };
  const addRegistry = async () => {
    if (!regFirm || !regEmail.trim()) { toast("Select firm and enter email"); return; }
    try {
      await api("/email-agent/registry", { method: "POST", body: {
        company_id: regFirm, email: regEmail.trim(),
        email_type: regType.trim() || "general",
        contact_person: regPerson.trim() } });
      setRegEmail(""); setRegType(""); setRegPerson("");
      void loadRegistry(); toast("Email registered");
    } catch (e: any) { toast(e?.message || "Failed"); }
  };
  const sandboxTest = async () => {
    if (!sbFrom.trim() || !sbSubject.trim()) { toast("Enter sender & subject"); return; }
    setBusy(true);
    try {
      const r: any = await api("/email-agent/sandbox-ingest", { method: "POST", body: {
        sender_email: sbFrom.trim(), subject: sbSubject.trim(), body: sbBody } });
      setDetail(r.record); setSub("Emails"); void loadEmails();
    } catch (e: any) { toast(e?.message || "Sandbox test failed"); }
    setBusy(false);
  };

  const kpi = (label: string, value: any, tint = colors.brandPrimary) => (
    <View style={st.kpi} key={label}>
      <Text style={[st.kpiVal, { color: tint }]}>{value ?? 0}</Text>
      <Text style={st.kpiLbl}>{label}</Text>
    </View>
  );

  // ── DETAIL VIEW ──
  if (detail) {
    const conf = detail.confidences || {};
    return (
      <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: 10 }}>
        <Pressable onPress={() => setDetail(null)} style={st.backRow} testID="ea-detail-back">
          <Ionicons name="arrow-back" size={16} color={colors.brandPrimary} />
          <Text style={st.link}>Back to list</Text>
        </Pressable>
        <View style={st.block}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Badge status={detail.status} />
            {detail.sandbox ? <Text style={st.sandboxTag}>SANDBOX</Text> : null}
          </View>
          <Text style={st.blockTitle}>{detail.subject || "(no subject)"}</Text>
          <Text style={st.line}>From: {detail.sender_name} &lt;{detail.sender_email}&gt;</Text>
          <Text style={st.line}>Received: {fmtAt(detail.received_at)}
            {detail.folder === "SPAM" ? "  ·  ⚠️ Found in Spam (registered company sender)" : ""}</Text>
          {detail.cc ? <Text style={st.line}>CC: {detail.cc}</Text> : null}
        </View>
        <View style={st.block}>
          <Text style={st.section}>🏢 Company Identification</Text>
          <Text style={st.line}>Company: <Text style={st.bold}>{detail.company_name || "Not Identified"}</Text></Text>
          <Text style={st.line}>Match Type: {detail.company_match_type} · Confidence: {detail.company_match_confidence}%</Text>
          {detail.possible_company && !detail.company_id ? (
            <Text style={st.line}>Possible Company: {detail.possible_company} ({conf.company || 0}%)</Text>
          ) : null}
          {(detail.company_candidates || []).length ? (
            <View style={{ gap: 6, marginTop: 4 }}>
              <Text style={[st.line, { fontWeight: "800" }]}>Multiple match — select the correct firm:</Text>
              {detail.company_candidates.map((c: any) => (
                <Pressable key={c.company_id} onPress={() => assignCompany(c.company_id)}
                  style={st.candBtn} testID={`ea-assign-${c.company_id}`}>
                  <Text style={st.candTxt}>{c.company_name}</Text>
                </Pressable>
              ))}
            </View>
          ) : null}
          {!detail.company_id && !(detail.company_candidates || []).length ? (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
              {firms.slice(0, 12).map((f: any) => (
                <Pressable key={f.company_id} onPress={() => assignCompany(f.company_id)} style={st.candBtn}>
                  <Text style={st.candTxt}>{f.name}</Text>
                </Pressable>
              ))}
            </View>
          ) : null}
        </View>
        <View style={st.block}>
          <Text style={st.section}>🧠 AI Analysis</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
            {(detail.categories || []).map((c: string) => (
              <View key={c} style={st.catChip}><Text style={st.catChipTxt}>{c}</Text></View>
            ))}
          </View>
          <Text style={st.line}>Priority: {detail.priority?.toUpperCase()}</Text>
          <Text style={[st.line, { marginTop: 4 }]}>{detail.ai_summary}</Text>
          {Object.keys(detail.extracted || {}).length ? (
            <View style={{ marginTop: 6 }}>
              <Text style={[st.line, { fontWeight: "800" }]}>Extracted Data</Text>
              {Object.entries(detail.extracted).map(([k, v]: any) => (
                <Text key={k} style={st.line}>• {k}: {String(v)}</Text>
              ))}
            </View>
          ) : null}
          {(detail.missing_information || []).length ? (
            <View style={{ marginTop: 6 }}>
              <Text style={[st.line, { fontWeight: "800", color: "#B91C1C" }]}>Missing Information</Text>
              {detail.missing_information.map((m: string, i: number) => (
                <Text key={i} style={st.line}>• {m}</Text>
              ))}
            </View>
          ) : null}
          <Text style={[st.line, { marginTop: 6 }]}>
            Confidence — Company {conf.company || 0}% · Classification {conf.classification || 0}% ·
            Extraction {conf.extraction || 0}% · Recommendation {conf.recommendation || 0}%
          </Text>
        </View>
        {/* Iter 685 — OCR Document Analysis (Aadhaar / PAN / bank photos) */}
        {(detail.document_analysis || []).length ? (
          <View style={[st.block, { backgroundColor: "#EFF6FF", borderColor: "#BFDBFE" }]}>
            <Text style={st.section}>🪪 Document Analysis (OCR)</Text>
            {detail.document_analysis.map((d: any, i: number) => (
              <View key={i} style={{ marginTop: i ? 8 : 2 }}>
                <Text style={[st.line, { fontWeight: "800" }]}>
                  📎 {d.file_name} — {d.document_type}
                  {d.person_name ? ` · ${d.person_name}` : ""}
                </Text>
                {d.id_number ? <Text style={st.line}>• Number: {d.id_number}</Text> : null}
                {Object.entries(d.fields || {}).map(([k, v]: any) => (
                  <Text key={k} style={st.line}>• {k}: {String(v)}</Text>
                ))}
                {!d.legible && !d.id_number ? (
                  <Text style={[st.line, { color: "#B45309" }]}>⚠ Image not clearly legible</Text>
                ) : null}
              </View>
            ))}
          </View>
        ) : null}
        {/* Iter 683 — Data Analysis, Comparison & Findings */}
        {detail.data_analysis && (detail.data_analysis.rows || detail.data_analysis.matched || (detail.findings || []).length) ? (
          <View style={st.block}>
            <Text style={st.section}>📊 Data Analysis</Text>
            {detail.data_analysis.rows ? (
              <Text style={st.line}>
                Rows {detail.data_analysis.rows} · Blank {detail.data_analysis.blank_rows} ·
                Duplicates {detail.data_analysis.duplicate_rows} · Codes seen {detail.data_analysis.employee_codes_seen}
              </Text>
            ) : null}
            {detail.data_analysis.matched || detail.data_analysis.unmatched ? (
              <Text style={st.line}>
                Employee Master (read-only): ✓ {detail.data_analysis.matched} matched ·
                ✗ {detail.data_analysis.unmatched} unmatched
              </Text>
            ) : null}
            {(detail.email_vs_attachment || []).map((c: any, i: number) => (
              <Text key={`c${i}`} style={[st.line, { color: "#B91C1C" }]}>
                ⚠ {c.field}: email {"“"}{c.email_value}{"”"} vs attachment {"“"}{c.attachment_value}{"”"}
              </Text>
            ))}
            {(detail.findings || []).map((f: any, i: number) => (
              <Text key={`f${i}`} style={st.line}>
                {f.severity === "critical" ? "🔴" : f.severity === "high" ? "🟠"
                  : f.severity === "warning" ? "🟡" : "🟢"} {f.message}
              </Text>
            ))}
          </View>
        ) : null}
        <View style={[st.block, { backgroundColor: "#F0FDF4", borderColor: "#BBF7D0" }]}>
          <Text style={st.section}>💡 AI Recommendation</Text>
          <Text style={st.line}>{detail.ai_recommendation || "—"}</Text>
        </View>
        {(detail.attachments || []).length ? (
          <View style={st.block}>
            <Text style={st.section}>📎 Attachments ({detail.attachments.length})</Text>
            {detail.attachments.map((a: any, i: number) => (
              <View key={i} style={{ marginTop: 4 }}>
                <Text style={st.line}>• {a.name} · {a.type} · {(a.size / 1024).toFixed(1)} KB
                  {a.readable ? " · ✓ readable" : ` · ${a.note || "not analyzed"}`}</Text>
                {a.excerpt ? <Text style={st.excerpt}>{a.excerpt.slice(0, 400)}</Text> : null}
              </View>
            ))}
          </View>
        ) : null}
        <View style={st.block}>
          <Text style={st.section}>✉️ Email Body</Text>
          <Text style={st.line}>{(detail.body_text || "").slice(0, 3000) || "—"}</Text>
        </View>
        <View style={st.block}>
          <Text style={st.section}>🕒 Processing Timeline</Text>
          {(detail.timeline || []).map((t: any, i: number) => (
            <Text key={i} style={st.line}>
              {i + 1}. <Text style={st.bold}>{t.step}</Text>
              {t.detail ? ` — ${t.detail}` : ""} · {fmtAt(t.at)}
            </Text>
          ))}
          {detail.error ? <Text style={[st.line, { color: "#B91C1C" }]}>Error: {detail.error}</Text> : null}
        </View>
      </ScrollView>
    );
  }

  return (
    <View style={{ flex: 1, minHeight: 0 }}>
      {/* Iter 675 — plain wrapping row (was a horizontal ScrollView, which
          collapses to 0 height on first layout in RN-web PROD builds and
          made the content overlap this bar). */}
      <View style={st.subTabs}>
        {SUB.map((s) => (
          <Pressable key={s} onPress={() => setSub(s)}
            style={[st.subTab, sub === s && st.subTabOn]} testID={`ea-sub-${s}`}>
            <Text style={[st.subTabTxt, sub === s && st.subTabTxtOn]}>{s}</Text>
          </Pressable>
        ))}
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: 10, paddingBottom: 60 }}>
        {sub === "Overview" ? (
          <>
            <View style={st.rowBetween}>
              <Text style={st.section}>
                Window: {dash?.window?.from} → {dash?.window?.to} (cutoff enforced)
              </Text>
              <Pressable onPress={scanNow} disabled={busy} style={st.primBtn} testID="ea-scan-now">
                {busy ? <ActivityIndicator color="#fff" size="small" />
                  : <Text style={st.primBtnTxt}>Scan Now</Text>}
              </Pressable>
            </View>
            <Text style={st.line}>
              Agent: {settings?.enabled ? "🟢 ON (auto every " + (settings?.poll_minutes || 5) + " min)" : "🔴 OFF"}
              {settings?.sandbox ? " · 🧪 Sandbox" : ""} ·
              Mailbox: {settings?.smtp_configured ? "✓ configured" : "✗ not configured"}
            </Text>
            {dash?.last_scan_result ? (
              <Text style={st.line}>
                Last scan {fmtAt(dash.last_scan_at)} — {dash.last_scan_result.ok
                  ? `${dash.last_scan_result.new_processed} new · ${dash.last_scan_result.ignored_historical} historical ignored`
                  : `failed: ${dash.last_scan_result.error}`}
              </Text>
            ) : null}
            <View style={st.kpiRow}>
              {kpi("Total Emails", dash?.total)}
              {kpi("Action Required", dash?.by_status?.ACTION_REQUIRED, "#B45309")}
              {kpi("Urgent", dash?.by_status?.URGENT, "#B91C1C")}
              {kpi("Review Required", dash?.by_status?.REVIEW_REQUIRED, "#6D28D9")}
              {kpi("Company Review", dash?.by_status?.COMPANY_REVIEW_REQUIRED, "#C2410C")}
              {kpi("Information Only", dash?.by_status?.INFORMATION_ONLY, "#1D4ED8")}
              {kpi("Failed", dash?.by_status?.PROCESSING_FAILED, "#475569")}
              {kpi("With Attachments", dash?.with_attachments)}
              {kpi("Payroll Emails", dash?.groups?.payroll)}
              {kpi("Employee Emails", dash?.groups?.employee)}
              {kpi("Compliance Emails", dash?.groups?.compliance)}
              {kpi("General Emails", dash?.groups?.general)}
            </View>
          </>
        ) : null}

        {sub === "Emails" ? (
          <>
            {/* Iter 675 — wrapping row instead of nested horizontal
                ScrollView (prod overlap fix). */}
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {FILTERS.map((f) => (
                <Pressable key={f || "ALL"} onPress={() => setFilter(f)}
                  style={[st.subTab, filter === f && st.subTabOn]} testID={`ea-filter-${f || "ALL"}`}>
                  <Text style={[st.subTabTxt, filter === f && st.subTabTxtOn]}>
                    {f ? (STATUS_META[f]?.label || f) : "All"}
                  </Text>
                </Pressable>
              ))}
            </View>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <TextInput value={search} onChangeText={setSearch}
                placeholder="Search subject / sender / summary…"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={st.input} onSubmitEditing={() => void loadEmails()} testID="ea-search" />
              <Pressable onPress={() => void loadEmails()} style={st.primBtn}>
                <Text style={st.primBtnTxt}>Search</Text>
              </Pressable>
            </View>
            <Text style={st.line}>{emailTotal} audited email(s)</Text>
            {emails.map((e) => (
              <Pressable key={e.audit_id} onPress={() => void openDetail(e.audit_id)}
                style={st.block} testID={`ea-email-${e.audit_id}`}>
                <View style={st.rowBetween}>
                  <Badge status={e.status} />
                  <Text style={st.time}>{fmtAt(e.received_at)}</Text>
                </View>
                <Text style={st.blockTitle} numberOfLines={1}>{e.subject || "(no subject)"}</Text>
                <Text style={st.line} numberOfLines={1}>
                  {e.sender_email} → {e.company_name || "Company not identified"}
                  {e.folder === "SPAM" ? " · ⚠️ from Spam" : ""}
                  {e.has_attachments ? " · 📎" : ""}{e.sandbox ? " · 🧪" : ""}
                </Text>
                {e.ai_summary ? <Text style={st.line} numberOfLines={2}>{e.ai_summary}</Text> : null}
              </Pressable>
            ))}
            {!emails.length ? <Text style={st.empty}>No audited emails yet — run a scan.</Text> : null}
          </>
        ) : null}

        {sub === "Companies" ? (
          <>
            {companies.map((c) => (
              <View key={c.company_id || "unknown"} style={st.block}>
                <Text style={st.blockTitle}>{c.company_name}</Text>
                <Text style={st.line}>
                  Total {c.total} · Action Required {c.action_required} · Review {c.review_required}
                </Text>
              </View>
            ))}
            {!companies.length ? <Text style={st.empty}>No company-linked emails yet.</Text> : null}
          </>
        ) : null}

        {sub === "Registry" ? (
          <>
            <View style={st.block}>
              <Text style={st.section}>Register a company email</Text>
              {/* Iter 675 — wrapping row (prod overlap fix). */}
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                {firms.map((f: any) => (
                  <Pressable key={f.company_id} onPress={() => setRegFirm(f.company_id)}
                    style={[st.subTab, regFirm === f.company_id && st.subTabOn]}>
                    <Text style={[st.subTabTxt, regFirm === f.company_id && st.subTabTxtOn]}
                      numberOfLines={1}>{f.name}</Text>
                  </Pressable>
                ))}
              </View>
              <TextInput value={regEmail} onChangeText={setRegEmail} placeholder="email@company.com"
                placeholderTextColor={colors.onSurfaceTertiary} autoCapitalize="none"
                style={st.input} testID="ea-reg-email" />
              <View style={{ flexDirection: "row", gap: 8 }}>
                <TextInput value={regType} onChangeText={setRegType} placeholder="Type (hr/payroll/accounts)"
                  placeholderTextColor={colors.onSurfaceTertiary} style={[st.input, { flex: 1 }]} />
                <TextInput value={regPerson} onChangeText={setRegPerson} placeholder="Contact person"
                  placeholderTextColor={colors.onSurfaceTertiary} style={[st.input, { flex: 1 }]} />
              </View>
              <Pressable onPress={() => void addRegistry()} style={st.primBtn} testID="ea-reg-add">
                <Text style={st.primBtnTxt}>+ Register Email</Text>
              </Pressable>
            </View>
            {registry.map((r) => (
              <View key={r.registry_id} style={st.block}>
                <View style={st.rowBetween}>
                  <Text style={st.blockTitle}>{r.email}</Text>
                  <View style={{ flexDirection: "row", gap: 10 }}>
                    <Pressable onPress={async () => {
                      await api(`/email-agent/registry/${r.registry_id}`, { method: "PATCH", body: {} });
                      void loadRegistry();
                    }}>
                      <Text style={st.link}>{r.active !== false ? "Deactivate" : "Activate"}</Text>
                    </Pressable>
                    <Pressable onPress={async () => {
                      await api(`/email-agent/registry/${r.registry_id}`, { method: "DELETE" });
                      void loadRegistry();
                    }}>
                      <Text style={[st.link, { color: "#B91C1C" }]}>Delete</Text>
                    </Pressable>
                  </View>
                </View>
                <Text style={st.line}>
                  {r.company_name} · {r.email_type}
                  {r.contact_person ? ` · ${r.contact_person}` : ""}
                  {r.active === false ? " · ⛔ inactive" : ""}
                </Text>
              </View>
            ))}
            {!registry.length ? <Text style={st.empty}>No registered emails yet.</Text> : null}
          </>
        ) : null}

        {sub === "Report" ? (
          <>
            <Text style={st.section}>📅 Daily AI Report — {report?.date}</Text>
            <View style={st.kpiRow}>
              {kpi("Total Today", report?.total)}
              {Object.entries(report?.by_status || {}).map(([k, v]: any) =>
                kpi(STATUS_META[k]?.label || k, v))}
            </View>
            {(report?.by_company || []).length ? (
              <View style={st.block}>
                <Text style={st.section}>Company-wise</Text>
                {report.by_company.map((c: any) => (
                  <Text key={c.company} style={st.line}>{c.company} — {c.count}</Text>
                ))}
              </View>
            ) : null}
            {(report?.pending || []).length ? (
              <View style={st.block}>
                <Text style={st.section}>⏳ Pending human attention</Text>
                {report.pending.map((e: any) => (
                  <Pressable key={e.audit_id} onPress={() => void openDetail(e.audit_id)}>
                    <Text style={st.line}>• [{STATUS_META[e.status]?.label || e.status}] {e.subject} — {e.company_name || "Unknown"}</Text>
                  </Pressable>
                ))}
              </View>
            ) : <Text style={st.empty}>Nothing pending today.</Text>}
          </>
        ) : null}

        {sub === "Settings" ? (
          <>
            <View style={st.block}>
              <View style={st.rowBetween}>
                <Text style={st.blockTitle}>Agent enabled (auto-scan)</Text>
                <Pressable onPress={() => void saveSettings({ enabled: !settings?.enabled })}
                  style={[st.toggle, settings?.enabled && st.toggleOn]} testID="ea-toggle-enabled">
                  <Text style={st.toggleTxt}>{settings?.enabled ? "ON" : "OFF"}</Text>
                </Pressable>
              </View>
              <View style={st.rowBetween}>
                <Text style={st.blockTitle}>🧪 Sandbox / Test mode</Text>
                <Pressable onPress={() => void saveSettings({ sandbox: !settings?.sandbox })}
                  style={[st.toggle, settings?.sandbox && st.toggleOn]} testID="ea-toggle-sandbox">
                  <Text style={st.toggleTxt}>{settings?.sandbox ? "ON" : "OFF"}</Text>
                </Pressable>
              </View>
              <Text style={st.line}>Confidence threshold: {settings?.threshold}% · Poll every {settings?.poll_minutes} min</Text>
              <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
                {[70, 80, 90].map((t) => (
                  <Pressable key={t} onPress={() => void saveSettings({ threshold: t })}
                    style={[st.subTab, settings?.threshold === t && st.subTabOn]}>
                    <Text style={[st.subTabTxt, settings?.threshold === t && st.subTabTxtOn]}>{t}%</Text>
                  </Pressable>
                ))}
                {[5, 15, 30].map((p) => (
                  <Pressable key={`p${p}`} onPress={() => void saveSettings({ poll_minutes: p })}
                    style={[st.subTab, settings?.poll_minutes === p && st.subTabOn]}>
                    <Text style={[st.subTabTxt, settings?.poll_minutes === p && st.subTabTxtOn]}>every {p}m</Text>
                  </Pressable>
                ))}
              </View>
              <Text style={st.line}>
                Mailbox: {settings?.smtp_configured
                  ? "✓ Using the existing Email SMTP & Notifications account (read-only IMAP)"
                  : "✗ Configure Email SMTP & Notifications first — the agent reuses it"}
              </Text>
              <Text style={st.line}>Date cutoff (hard rule): emails before 15-Aug-2026 are never processed.</Text>
              <Text style={st.line}>Phase 1 is READ-ONLY — the agent never sends email or modifies payroll.</Text>
            </View>
            <View style={st.block}>
              <Text style={st.section}>🧪 Sandbox test email (needs Sandbox ON)</Text>
              <TextInput value={sbFrom} onChangeText={setSbFrom} placeholder="sender@company.com"
                placeholderTextColor={colors.onSurfaceTertiary} autoCapitalize="none"
                style={st.input} testID="ea-sb-from" />
              <TextInput value={sbSubject} onChangeText={setSbSubject} placeholder="Subject"
                placeholderTextColor={colors.onSurfaceTertiary} style={st.input} testID="ea-sb-subject" />
              <TextInput value={sbBody} onChangeText={setSbBody} placeholder="Email body…" multiline
                placeholderTextColor={colors.onSurfaceTertiary}
                style={[st.input, { minHeight: 70 }]} testID="ea-sb-body" />
              <Pressable onPress={() => void sandboxTest()} disabled={busy} style={st.primBtn} testID="ea-sb-run">
                {busy ? <ActivityIndicator color="#fff" size="small" />
                  : <Text style={st.primBtnTxt}>Run Sandbox Audit</Text>}
              </Pressable>
            </View>
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}

const st = StyleSheet.create({
  subTabs: {
    flexDirection: "row", flexWrap: "wrap", gap: 6,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
  },
  subTab: {
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
    maxWidth: 220,
  },
  subTabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  subTabTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  subTabTxtOn: { color: "#fff" },
  block: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 12, gap: 4, backgroundColor: colors.surfaceSecondary,
  },
  blockTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  section: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  line: { fontSize: 12, color: colors.onSurfaceSecondary },
  bold: { fontWeight: "800", color: colors.onSurface },
  empty: { color: colors.onSurfaceTertiary, fontSize: 13, textAlign: "center", marginTop: 20 },
  time: { fontSize: 10.5, color: colors.onSurfaceTertiary },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 99 },
  badgeTxt: { fontSize: 10, fontWeight: "800" },
  sandboxTag: { fontSize: 10, fontWeight: "800", color: "#7C3AED" },
  kpiRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  kpi: {
    minWidth: 130, flexGrow: 1, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: 12, gap: 2, backgroundColor: colors.surfaceSecondary,
  },
  kpiVal: { fontSize: 16, fontWeight: "900" },
  kpiLbl: { fontSize: 11, color: colors.onSurfaceTertiary },
  primBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 14, paddingVertical: 9, alignItems: "center", justifyContent: "center",
  },
  primBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 9, color: colors.onSurface,
    backgroundColor: colors.surface, fontSize: 13,
  },
  link: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  backRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  candBtn: {
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 6, alignSelf: "flex-start",
  },
  candTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  catChip: { backgroundColor: "#EEF2FF", borderRadius: 99, paddingHorizontal: 8, paddingVertical: 3 },
  catChipTxt: { fontSize: 10.5, fontWeight: "700", color: "#4338CA" },
  toggle: {
    borderRadius: 99, paddingHorizontal: 14, paddingVertical: 6,
    backgroundColor: "#94A3B8",
  },
  toggleOn: { backgroundColor: "#16A34A" },
  toggleTxt: { color: "#fff", fontWeight: "800", fontSize: 11 },
  excerpt: {
    fontSize: 10.5, color: colors.onSurfaceTertiary, backgroundColor: colors.surface,
    borderRadius: 6, padding: 6, marginTop: 3,
  },
});
