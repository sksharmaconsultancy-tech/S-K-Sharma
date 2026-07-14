/**
 * Iter 95 — HR Letters (web portal only).
 *
 * Generate Appointment / Offer / Warning / Termination letters on the firm
 * letterhead. Templates auto-fill from Employee Master + Firm Master and are
 * fully editable before saving. Saved letters live in a per-firm Letter
 * Register with re-download + delete.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  ScrollView,
  TextInput,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

type LetterType = "appointment" | "offer" | "warning" | "termination";

const LETTER_TYPES: { key: LetterType; label: string; icon: string }[] = [
  { key: "appointment", label: "Appointment", icon: "document-text-outline" },
  { key: "offer", label: "Offer", icon: "mail-open-outline" },
  { key: "warning", label: "Warning", icon: "warning-outline" },
  { key: "termination", label: "Termination", icon: "close-circle-outline" },
];

type Emp = {
  user_id: string;
  name: string;
  employee_code?: string | null;
  designation?: string | null;
  father_name?: string | null;
};

type Letter = {
  letter_id: string;
  letter_type: LetterType;
  letter_type_label: string;
  ref_no: string;
  subject: string;
  body: string;
  issued_date: string;
  employee_name?: string;
  employee_code?: string | null;
  designation?: string | null;
  created_at: string;
};

type TemplateResp = {
  subject: string;
  body: string;
  issued_date: string;
  company: { name: string; address?: string };
  employee: Emp & { address?: string | null };
};

export default function HrLettersScreen() {
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const { selectedCompanyId, selectedCompany } = useSelectedCompany();
  const isAdmin =
    user?.role === "super_admin" ||
    user?.role === "company_admin" ||
    user?.role === "sub_admin";

  const cid = useMemo(() => {
    if (user?.role === "company_admin") return user.company_id || null;
    return selectedCompanyId && selectedCompanyId !== "all" ? selectedCompanyId : null;
  }, [user, selectedCompanyId]);

  const [tab, setTab] = useState<"generate" | "register">("generate");
  const [ltype, setLtype] = useState<LetterType>("appointment");

  // Employee picker
  const [emps, setEmps] = useState<Emp[]>([]);
  const [empQ, setEmpQ] = useState("");
  const [selEmp, setSelEmp] = useState<Emp | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  // Draft
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [issuedDate, setIssuedDate] = useState("");
  const [tplMeta, setTplMeta] = useState<TemplateResp | null>(null);
  const [loadingTpl, setLoadingTpl] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // Iter 95d — bulk generate/email
  const [bulkEmail, setBulkEmail] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);

  // Register
  const [letters, setLetters] = useState<Letter[]>([]);
  const [regFilter, setRegFilter] = useState<LetterType | "all">("all");
  const [loadingReg, setLoadingReg] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  // Iter 95c — email letter to employee (with optional address override).
  const [emailFor, setEmailFor] = useState<string | null>(null);
  const [emailAddr, setEmailAddr] = useState("");
  const [emailNote, setEmailNote] = useState<string | null>(null);

  useEffect(() => {
    if (!cid) { setEmps([]); return; }
    (async () => {
      try {
        const r = await api<{ employees: any[] }>(
          `/admin/employees?company_id=${encodeURIComponent(cid)}`,
        );
        const list = (r.employees || []).map((e) => ({
          user_id: e.user_id,
          name: e.name,
          employee_code: e.employee_code,
          designation: e.designation || e.position,
          father_name: e.father_name,
        }));
        list.sort((a, b) => Number(a.employee_code || 0) - Number(b.employee_code || 0));
        setEmps(list);
      } catch {
        setEmps([]);
      }
    })();
    setSelEmp(null);
    setSubject("");
    setBody("");
    setTplMeta(null);
  }, [cid]);

  const loadRegister = useCallback(async () => {
    if (!cid) { setLetters([]); return; }
    setLoadingReg(true);
    try {
      const qs = regFilter !== "all" ? `&letter_type=${regFilter}` : "";
      const r = await api<{ letters: Letter[] }>(
        `/admin/hr-letters?company_id=${encodeURIComponent(cid)}${qs}`,
      );
      setLetters(r.letters || []);
    } catch {
      setLetters([]);
    } finally {
      setLoadingReg(false);
    }
  }, [cid, regFilter]);

  useEffect(() => {
    if (tab === "register") loadRegister();
  }, [tab, loadRegister]);

  const filteredEmps = useMemo(() => {
    const q = empQ.trim().toLowerCase();
    if (!q) return emps;
    return emps.filter(
      (e) =>
        (e.name || "").toLowerCase().includes(q) ||
        String(e.employee_code || "").toLowerCase().includes(q),
    );
  }, [emps, empQ]);

  const loadTemplate = useCallback(async () => {
    if (!cid || !selEmp) return;
    setLoadingTpl(true);
    setErr(null);
    setMsg(null);
    try {
      const r = await api<TemplateResp>(
        `/admin/hr-letters/template/${ltype}?company_id=${encodeURIComponent(cid)}&user_id=${encodeURIComponent(selEmp.user_id)}`,
      );
      setSubject(r.subject);
      setBody(r.body);
      setIssuedDate(r.issued_date);
      setTplMeta(r);
    } catch (e: any) {
      setErr(e?.message || "Could not load template");
    } finally {
      setLoadingTpl(false);
    }
  }, [cid, selEmp, ltype]);

  const downloadPdf = useCallback(async (letter: Letter) => {
    setBusyId(letter.letter_id);
    try {
      const res = await apiBinary(`/admin/hr-letters/${letter.letter_id}/pdf`);
      const fname = `${letter.letter_type_label.replace(/ /g, "_")}_${letter.employee_code || "emp"}_${letter.issued_date}.pdf`;
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = fname;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      setErr(e?.message || "PDF download failed");
    } finally {
      setBusyId(null);
    }
  }, []);

  const saveLetter = useCallback(async () => {
    if (!cid || !selEmp || saving) return;
    if (!subject.trim() || !body.trim()) {
      setErr("Load a template / fill subject & body first.");
      return;
    }
    setSaving(true);
    setErr(null);
    setMsg(null);
    try {
      const r = await api<{ letter: Letter }>("/admin/hr-letters", {
        method: "POST",
        body: {
          company_id: cid,
          user_id: selEmp.user_id,
          letter_type: ltype,
          subject: subject.trim(),
          body: body.trim(),
          issued_date: issuedDate.trim() || undefined,
        },
      });
      setMsg(`Saved to register — Ref ${r.letter.ref_no}. Downloading PDF…`);
      await downloadPdf(r.letter);
    } catch (e: any) {
      setErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }, [cid, selEmp, ltype, subject, body, issuedDate, saving, downloadPdf]);

  const deleteLetter = useCallback(async (letterId: string) => {
    setBusyId(letterId);
    try {
      await api(`/admin/hr-letters/${letterId}`, { method: "DELETE" });
      setLetters((prev) => prev.filter((l) => l.letter_id !== letterId));
    } catch (e: any) {
      setErr(e?.message || "Delete failed");
    } finally {
      setBusyId(null);
    }
  }, []);

  const bulkGenerate = useCallback(async () => {
    if (!cid || bulkBusy) return;
    const label = LETTER_TYPES.find((t) => t.key === ltype)?.label || ltype;
    if (Platform.OS === "web") {
      const ok = window.confirm(
        `Generate ${label} Letters for ALL employees of this firm?` +
        (bulkEmail ? " Letters will also be EMAILED to employees who have an email on file." : ""),
      );
      if (!ok) return;
    }
    setBulkBusy(true);
    setBulkMsg(null);
    setErr(null);
    try {
      const r = await api<{
        created: number; skipped_existing: number; emailed: number;
        email_failed: number; no_email: number; total_employees: number;
      }>("/admin/hr-letters/bulk", {
        method: "POST",
        body: {
          company_id: cid,
          letter_type: ltype,
          send_email: bulkEmail,
        },
      });
      const parts = [
        `${r.created} letter(s) created`,
        r.skipped_existing ? `${r.skipped_existing} skipped (already have a ${label} letter)` : "",
        bulkEmail ? `${r.emailed} emailed` : "",
        bulkEmail && r.no_email ? `${r.no_email} employee(s) have no email` : "",
        bulkEmail && r.email_failed ? `${r.email_failed} email(s) failed` : "",
      ].filter(Boolean);
      setBulkMsg(`✓ Bulk done — ${parts.join(", ")}. See Letter Register.`);
    } catch (e: any) {
      setErr(e?.message || "Bulk generation failed");
    } finally {
      setBulkBusy(false);
    }
  }, [cid, ltype, bulkEmail, bulkBusy]);

  const downloadAllPdf = useCallback(async () => {
    if (!cid || regFilter === "all") return;
    setBusyId("bulk-pdf");
    setErr(null);
    try {
      const res = await apiBinary(
        `/admin/hr-letters/bulk.pdf?company_id=${encodeURIComponent(cid)}&letter_type=${regFilter}`,
      );
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = `${regFilter}_letters_ALL.pdf`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      setErr(e?.message || "Combined PDF failed");
    } finally {
      setBusyId(null);
    }
  }, [cid, regFilter]);

  const emailLetter = useCallback(async (letter: Letter, override?: string) => {
    setBusyId(letter.letter_id);
    setEmailNote(null);
    setErr(null);
    try {
      const r = await api<{ delivered: boolean; to_email: string }>(
        `/admin/hr-letters/${letter.letter_id}/email`,
        { method: "POST", body: override ? { to_email: override } : {} },
      );
      setEmailNote(`✓ Emailed to ${r.to_email}`);
      setEmailFor(null);
      setEmailAddr("");
    } catch (e: any) {
      const m = e?.message || "Email failed";
      if (m.toLowerCase().includes("no email")) {
        // Employee has no email on file — open inline override input.
        setEmailFor(letter.letter_id);
        setEmailNote("No email on file for this employee — type one below and press Send.");
      } else {
        setErr(m);
      }
    } finally {
      setBusyId(null);
    }
  }, []);

  if (!isAdmin) {
    return (
      <View style={[styles.center, { flex: 1 }]}>
        <Ionicons name="lock-closed-outline" size={36} color={colors.brandPrimary} />
        <Text style={styles.errTitle}>Admins only</Text>
      </View>
    );
  }

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      {/* Toolbar */}
      <View style={styles.toolbar}>
        <Text style={styles.title}>HR Letters</Text>
        {selectedCompany ? <Text style={styles.firmTxt}>{selectedCompany.name}</Text> : null}
        <View style={{ flex: 1 }} />
        <Pressable
          style={[styles.tabBtn, tab === "generate" && styles.tabBtnOn]}
          onPress={() => setTab("generate")}
          testID="hrl-tab-generate"
        >
          <Text style={[styles.tabTxt, tab === "generate" && styles.tabTxtOn]}>Generate Letter</Text>
        </Pressable>
        <Pressable
          style={[styles.tabBtn, tab === "register" && styles.tabBtnOn]}
          onPress={() => setTab("register")}
          testID="hrl-tab-register"
        >
          <Text style={[styles.tabTxt, tab === "register" && styles.tabTxtOn]}>Letter Register</Text>
        </Pressable>
      </View>

      {!cid ? (
        <View style={styles.center}>
          <Ionicons name="business-outline" size={30} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyTxt}>Pick a firm first (top-right selector).</Text>
        </View>
      ) : tab === "generate" ? (
        <ScrollView contentContainerStyle={{ padding: spacing.md, gap: 12 }}>
          {/* Step 1 — letter type */}
          <Text style={styles.stepLbl}>1. Letter Type</Text>
          <View style={styles.pillRow}>
            {LETTER_TYPES.map((t) => (
              <Pressable
                key={t.key}
                style={[styles.pill, ltype === t.key && styles.pillOn]}
                onPress={() => setLtype(t.key)}
                testID={`hrl-type-${t.key}`}
              >
                <Ionicons
                  name={t.icon as any}
                  size={14}
                  color={ltype === t.key ? "#fff" : colors.onSurfaceSecondary}
                />
                <Text style={[styles.pillTxt, ltype === t.key && styles.pillTxtOn]}>
                  {t.label} Letter
                </Text>
              </Pressable>
            ))}
          </View>

          {/* Iter 95d — Bulk generate & email for the whole firm */}
          <View style={styles.bulkCard}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <Ionicons name="layers-outline" size={16} color={colors.brandPrimary} />
              <Text style={styles.bulkTitle}>
                Bulk — {LETTER_TYPES.find((t) => t.key === ltype)?.label} Letters for ALL employees
              </Text>
              <Pressable
                style={styles.checkRow}
                onPress={() => setBulkEmail((v) => !v)}
                testID="hrl-bulk-email-toggle"
              >
                <Ionicons
                  name={bulkEmail ? "checkbox" : "square-outline"}
                  size={17}
                  color={bulkEmail ? "#0369A1" : colors.onSurfaceTertiary}
                />
                <Text style={styles.checkTxt}>Also email employees who have an email</Text>
              </Pressable>
              <Pressable
                style={[styles.bulkBtn, bulkBusy && { opacity: 0.6 }]}
                onPress={bulkGenerate}
                disabled={bulkBusy}
                testID="hrl-bulk-generate"
              >
                {bulkBusy ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Ionicons name="flash-outline" size={14} color="#fff" />
                )}
                <Text style={styles.bulkBtnTxt}>Generate for ALL employees</Text>
              </Pressable>
            </View>
            {bulkMsg ? <Text style={[styles.okTxt, { marginTop: 6 }]}>{bulkMsg}</Text> : null}
          </View>

          {/* Step 2 — employee */}
          <Text style={styles.stepLbl}>2. Employee</Text>
          <View style={{ zIndex: 50 }}>
            <Pressable
              style={styles.empSelect}
              onPress={() => setPickerOpen((v) => !v)}
              testID="hrl-emp-select"
            >
              <Ionicons name="person-outline" size={15} color={colors.onSurfaceSecondary} />
              <Text style={styles.empSelectTxt}>
                {selEmp
                  ? `${selEmp.employee_code || ""} — ${selEmp.name}${selEmp.designation ? ` (${selEmp.designation})` : ""}`
                  : "Select employee…"}
              </Text>
              <Ionicons
                name={pickerOpen ? "chevron-up" : "chevron-down"}
                size={15}
                color={colors.onSurfaceSecondary}
              />
            </Pressable>
            {pickerOpen && (
              <View style={styles.empDrop}>
                <TextInput
                  style={styles.empSearch}
                  value={empQ}
                  onChangeText={setEmpQ}
                  placeholder="Search name / code…"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  testID="hrl-emp-search"
                />
                <ScrollView style={{ maxHeight: 260 }} nestedScrollEnabled>
                  {filteredEmps.map((e) => (
                    <Pressable
                      key={e.user_id}
                      style={styles.empRow}
                      onPress={() => {
                        setSelEmp(e);
                        setPickerOpen(false);
                        setSubject("");
                        setBody("");
                        setTplMeta(null);
                        setMsg(null);
                      }}
                      testID={`hrl-emp-${e.employee_code || e.user_id}`}
                    >
                      <Text style={styles.empCode}>{e.employee_code || "—"}</Text>
                      <Text style={styles.empName} numberOfLines={1}>{e.name}</Text>
                      <Text style={styles.empDesig} numberOfLines={1}>{e.designation || ""}</Text>
                    </Pressable>
                  ))}
                  {filteredEmps.length === 0 && (
                    <Text style={styles.emptyTxt}>No employees match.</Text>
                  )}
                </ScrollView>
              </View>
            )}
          </View>

          {/* Step 3 — template */}
          <View style={{ flexDirection: "row", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <Text style={styles.stepLbl}>3. Draft</Text>
            <Pressable
              style={[styles.loadBtn, (!selEmp || loadingTpl) && { opacity: 0.5 }]}
              onPress={loadTemplate}
              disabled={!selEmp || loadingTpl}
              testID="hrl-load-template"
            >
              {loadingTpl ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <Ionicons name="sparkles-outline" size={14} color="#fff" />
              )}
              <Text style={styles.loadTxt}>Load Template</Text>
            </Pressable>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <Text style={styles.dateLbl}>Letter Date:</Text>
              <TextInput
                style={styles.dateInput}
                value={issuedDate}
                onChangeText={setIssuedDate}
                placeholder="DD-MM-YYYY"
                placeholderTextColor={colors.onSurfaceTertiary}
                maxLength={10}
                testID="hrl-date"
              />
            </View>
          </View>

          <TextInput
            style={styles.subjectInput}
            value={subject}
            onChangeText={setSubject}
            placeholder="Subject…"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID="hrl-subject"
          />
          <TextInput
            style={styles.bodyInput}
            value={body}
            onChangeText={setBody}
            placeholder="Letter body… (Load Template to auto-fill, then edit freely. Replace [BRACKETED] placeholders.)"
            placeholderTextColor={colors.onSurfaceTertiary}
            multiline
            textAlignVertical="top"
            testID="hrl-body"
          />

          {/* Preview */}
          {subject || body ? (
            <View style={styles.previewCard} testID="hrl-preview">
              <Text style={styles.pvFirm}>{tplMeta?.company?.name || selectedCompany?.name || ""}</Text>
              {tplMeta?.company?.address ? (
                <Text style={styles.pvAddr}>{tplMeta.company.address}</Text>
              ) : null}
              <View style={styles.pvRule} />
              <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <Text style={styles.pvMeta}>Ref. No.: (auto on save)</Text>
                <Text style={styles.pvMeta}>Date: {issuedDate}</Text>
              </View>
              <Text style={[styles.pvMeta, { marginTop: 8 }]}>
                To,{"\n"}
                {selEmp ? `${selEmp.name}${selEmp.father_name ? `\nS/o ${selEmp.father_name}` : ""}\nEmp. Code: ${selEmp.employee_code || "—"}${selEmp.designation ? ` | ${selEmp.designation}` : ""}` : "—"}
              </Text>
              <Text style={styles.pvSubject}>Subject: {subject}</Text>
              <Text style={styles.pvBody}>{body}</Text>
              <Text style={[styles.pvMeta, { marginTop: 14, fontWeight: "800" }]}>
                For {tplMeta?.company?.name || selectedCompany?.name || ""}
              </Text>
              <Text style={[styles.pvMeta, { marginTop: 22 }]}>Authorised Signatory</Text>
            </View>
          ) : null}

          {err ? <Text style={styles.errTxt}>{err}</Text> : null}
          {msg ? <Text style={styles.okTxt}>{msg}</Text> : null}

          <Pressable
            style={[styles.saveBtn, (saving || !selEmp || !subject.trim() || !body.trim()) && { opacity: 0.5 }]}
            onPress={saveLetter}
            disabled={saving || !selEmp || !subject.trim() || !body.trim()}
            testID="hrl-save"
          >
            {saving ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Ionicons name="download-outline" size={16} color="#fff" />
            )}
            <Text style={styles.saveTxt}>Save & Download PDF</Text>
          </Pressable>
          <View style={{ height: 40 }} />
        </ScrollView>
      ) : (
        /* ----- Register tab ----- */
        <ScrollView contentContainerStyle={{ padding: spacing.md }}>
          <View style={[styles.pillRow, { marginBottom: 10 }]}>
            <Pressable
              style={[styles.pill, regFilter === "all" && styles.pillOn]}
              onPress={() => setRegFilter("all")}
            >
              <Text style={[styles.pillTxt, regFilter === "all" && styles.pillTxtOn]}>All</Text>
            </Pressable>
            {LETTER_TYPES.map((t) => (
              <Pressable
                key={t.key}
                style={[styles.pill, regFilter === t.key && styles.pillOn]}
                onPress={() => setRegFilter(t.key)}
              >
                <Text style={[styles.pillTxt, regFilter === t.key && styles.pillTxtOn]}>{t.label}</Text>
              </Pressable>
            ))}
            <View style={{ flex: 1 }} />
            {regFilter !== "all" && letters.length > 0 ? (
              <Pressable
                style={[styles.loadBtn, { backgroundColor: "#B91C1C" }, busyId === "bulk-pdf" && { opacity: 0.6 }]}
                onPress={downloadAllPdf}
                disabled={busyId === "bulk-pdf"}
                testID="hrl-download-all"
              >
                {busyId === "bulk-pdf" ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Ionicons name="print-outline" size={14} color="#fff" />
                )}
                <Text style={styles.loadTxt}>Download All (1 PDF)</Text>
              </Pressable>
            ) : null}
            <Pressable style={styles.loadBtn} onPress={loadRegister}>
              <Ionicons name="refresh" size={14} color="#fff" />
              <Text style={styles.loadTxt}>Refresh</Text>
            </Pressable>
          </View>

          {loadingReg ? (
            <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} />
          ) : (
            <>
              {emailNote ? <Text style={styles.okTxt}>{emailNote}</Text> : null}
              {err ? <Text style={styles.errTxt}>{err}</Text> : null}
              <ScrollView horizontal showsHorizontalScrollIndicator>
              <View>
                <View style={styles.hdrRow}>
                  {[
                    { w: 86, t: "Date" },
                    { w: 130, t: "Ref No." },
                    { w: 105, t: "Type" },
                    { w: 56, t: "Code" },
                    { w: 160, t: "Employee" },
                    { w: 230, t: "Subject" },
                    { w: 158, t: "Actions" },
                  ].map((c) => (
                    <Text key={c.t} style={[styles.hdrCell, { width: c.w }]}>{c.t}</Text>
                  ))}
                </View>
                {letters.length === 0 ? (
                  <Text style={styles.emptyTxt}>No letters in the register yet.</Text>
                ) : (
                  letters.map((l, i) => (
                    <View key={l.letter_id}>
                      <View style={[styles.row, i % 2 === 0 && styles.rowAlt]}>
                        <Text style={[styles.cell, { width: 86 }]}>{l.issued_date}</Text>
                        <Text style={[styles.cell, { width: 130 }]} numberOfLines={1}>{l.ref_no}</Text>
                        <Text style={[styles.cell, { width: 105, fontWeight: "700" }]}>{l.letter_type_label.replace(" Letter", "")}</Text>
                        <Text style={[styles.cell, { width: 56 }]}>{l.employee_code || "—"}</Text>
                        <Text style={[styles.cell, { width: 160, fontWeight: "600" }]} numberOfLines={1}>
                          {l.employee_name || "—"}
                        </Text>
                        <Text style={[styles.cell, { width: 230 }]} numberOfLines={1}>{l.subject}</Text>
                        <View style={{ width: 158, flexDirection: "row", gap: 8, alignItems: "center", paddingHorizontal: 6 }}>
                          <Pressable
                            style={styles.pdfBtn}
                            onPress={() => downloadPdf(l)}
                            disabled={busyId === l.letter_id}
                            testID={`hrl-pdf-${l.letter_id}`}
                          >
                            {busyId === l.letter_id ? (
                              <ActivityIndicator size="small" color="#fff" />
                            ) : (
                              <Ionicons name="download-outline" size={13} color="#fff" />
                            )}
                            <Text style={styles.pdfTxt}>PDF</Text>
                          </Pressable>
                          <Pressable
                            style={[styles.pdfBtn, { backgroundColor: "#0369A1" }]}
                            onPress={() => emailLetter(l)}
                            disabled={busyId === l.letter_id}
                            testID={`hrl-email-${l.letter_id}`}
                          >
                            <Ionicons name="mail-outline" size={13} color="#fff" />
                            <Text style={styles.pdfTxt}>Email</Text>
                          </Pressable>
                          <Pressable
                            onPress={() => deleteLetter(l.letter_id)}
                            disabled={busyId === l.letter_id}
                            testID={`hrl-del-${l.letter_id}`}
                            hitSlop={6}
                          >
                            <Ionicons name="trash-outline" size={16} color="#B91C1C" />
                          </Pressable>
                        </View>
                      </View>
                      {emailFor === l.letter_id && (
                        <View style={styles.emailRow}>
                          <TextInput
                            style={[styles.empSearch, { flex: 1, maxWidth: 320, marginBottom: 0 }]}
                            value={emailAddr}
                            onChangeText={setEmailAddr}
                            placeholder="recipient@email.com"
                            placeholderTextColor={colors.onSurfaceTertiary}
                            keyboardType="email-address"
                            autoCapitalize="none"
                            testID={`hrl-email-input-${l.letter_id}`}
                          />
                          <Pressable
                            style={[styles.pdfBtn, { backgroundColor: "#0369A1" }, (!emailAddr.includes("@") || busyId === l.letter_id) && { opacity: 0.5 }]}
                            onPress={() => emailLetter(l, emailAddr.trim())}
                            disabled={!emailAddr.includes("@") || busyId === l.letter_id}
                            testID={`hrl-email-send-${l.letter_id}`}
                          >
                            <Ionicons name="send-outline" size={13} color="#fff" />
                            <Text style={styles.pdfTxt}>Send</Text>
                          </Pressable>
                          <Pressable onPress={() => { setEmailFor(null); setEmailAddr(""); }} hitSlop={6}>
                            <Ionicons name="close" size={16} color={colors.onSurfaceSecondary} />
                          </Pressable>
                        </View>
                      )}
                    </View>
                  ))
                )}
              </View>
            </ScrollView>
            </>
          )}
          <View style={{ height: 40 }} />
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  toolbar: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.md, paddingVertical: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    flexWrap: "wrap",
  },
  title: { fontSize: type.md, fontWeight: "800", color: colors.onSurface },
  firmTxt: { fontSize: 11, color: colors.brandPrimary, fontWeight: "700" },
  tabBtn: {
    paddingHorizontal: 14, paddingVertical: 7, borderRadius: 8,
    borderWidth: 1, borderColor: colors.border,
  },
  tabBtnOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtOn: { color: "#fff" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 10 },
  errTitle: { fontSize: type.md, fontWeight: "800", color: colors.onSurface },
  stepLbl: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  pillRow: { flexDirection: "row", gap: 8, flexWrap: "wrap", alignItems: "center" },
  pill: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 20,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  pillOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  pillTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  pillTxtOn: { color: "#fff" },
  empSelect: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 10, backgroundColor: colors.surface,
    maxWidth: 520,
  },
  empSelectTxt: { flex: 1, fontSize: 12.5, color: colors.onSurface, fontWeight: "600" },
  empDrop: {
    position: "absolute", top: 44, left: 0, right: 0, maxWidth: 520,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 8, padding: 8, zIndex: 100,
    shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 12, elevation: 8,
  },
  empSearch: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 6,
    paddingHorizontal: 10, paddingVertical: 6, fontSize: 12,
    color: colors.onSurface, marginBottom: 6,
  },
  empRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 8, paddingHorizontal: 6,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
  },
  empCode: { width: 42, fontSize: 11, fontWeight: "800", color: colors.brandPrimary },
  empName: { flex: 1, fontSize: 12, fontWeight: "600", color: colors.onSurface },
  empDesig: { width: 130, fontSize: 10.5, color: colors.onSurfaceTertiary },
  loadBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 8,
  },
  loadTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  dateLbl: { fontSize: 11.5, color: colors.onSurfaceSecondary, fontWeight: "600" },
  dateInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 8, paddingVertical: 6, fontSize: 12,
    color: colors.onSurface, width: 110, backgroundColor: colors.surface,
  },
  subjectInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 10, fontSize: 13, fontWeight: "700",
    color: colors.onSurface, backgroundColor: colors.surface, maxWidth: 860,
  },
  bodyInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 10, fontSize: 12.5, lineHeight: 19,
    color: colors.onSurface, backgroundColor: colors.surface,
    minHeight: 260, maxWidth: 860,
  },
  previewCard: {
    backgroundColor: "#fff", borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: 26, maxWidth: 860,
    shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 8, elevation: 2,
  },
  pvFirm: { fontSize: 17, fontWeight: "900", color: "#111", textAlign: "center" },
  pvAddr: { fontSize: 10.5, color: "#555", textAlign: "center", marginTop: 2 },
  pvRule: { height: 2, backgroundColor: "#222", marginVertical: 10 },
  pvMeta: { fontSize: 11.5, color: "#222", lineHeight: 17 },
  pvSubject: { fontSize: 12.5, fontWeight: "800", color: "#111", marginTop: 12 },
  pvBody: { fontSize: 11.5, color: "#222", lineHeight: 18, marginTop: 8 },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: "#15803D", borderRadius: radius.md,
    paddingVertical: 12, maxWidth: 860,
  },
  saveTxt: { color: "#fff", fontWeight: "800", fontSize: 13.5 },
  errTxt: { color: "#B91C1C", fontSize: 12, fontWeight: "700" },
  okTxt: { color: "#15803D", fontSize: 12, fontWeight: "700" },
  emptyTxt: {
    padding: 18, color: colors.onSurfaceTertiary, fontSize: 12, textAlign: "center",
  },
  hdrRow: {
    flexDirection: "row", backgroundColor: "#0F2E3D",
    borderTopLeftRadius: 8, borderTopRightRadius: 8,
  },
  hdrCell: { color: "#fff", fontSize: 10.5, fontWeight: "800", paddingVertical: 9, paddingHorizontal: 6 },
  row: {
    flexDirection: "row",
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
    backgroundColor: colors.surface, alignItems: "center",
  },
  rowAlt: { backgroundColor: colors.surfaceSecondary },
  cell: { fontSize: 11.5, color: colors.onSurface, paddingVertical: 8, paddingHorizontal: 6 },
  pdfBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "#B91C1C", borderRadius: 6,
    paddingHorizontal: 9, paddingVertical: 5,
  },
  pdfTxt: { color: "#fff", fontSize: 10.5, fontWeight: "800" },
  emailRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 8, paddingHorizontal: 10,
    backgroundColor: "rgba(3,105,161,0.06)",
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
  },
  bulkCard: {
    backgroundColor: "rgba(15,46,61,0.04)", borderWidth: 1,
    borderColor: colors.border, borderRadius: radius.md,
    padding: 12, maxWidth: 980,
  },
  bulkTitle: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  checkRow: { flexDirection: "row", alignItems: "center", gap: 5 },
  checkTxt: { fontSize: 11.5, color: colors.onSurfaceSecondary, fontWeight: "600" },
  bulkBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 8,
  },
  bulkBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
});
