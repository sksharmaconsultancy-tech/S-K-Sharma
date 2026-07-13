/**
 * Iter 103 — Email Settings (SMTP) + Automated Triggers + Compose.
 *
 * Three sections for super/sub admins:
 *  1. SMTP Configuration — Gmail (or any) SMTP; editable anytime; test send.
 *  2. Automated Triggers — per-event ON/OFF, recipients, subject template.
 *  3. Compose Notification — pick firm + employees → email + in-app instantly.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, TextInput,
  ActivityIndicator, Platform, Alert, Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as DocumentPicker from "expo-document-picker";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

function showMsg(msg: string) {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert("Email settings", msg);
}

type Tab = "smtp" | "triggers" | "compose" | "log";

export default function EmailSettingsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const allowed = user?.role === "super_admin" || user?.role === "sub_admin";
  const [tab, setTab] = useState<Tab>("smtp");

  if (!allowed) {
    return (
      <View style={styles.center}>
        <Text style={{ color: colors.onSurfaceSecondary }}>Not authorised.</Text>
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 80 }}>
        <View style={styles.headRow}>
          <Pressable onPress={() => router.back()} style={styles.backBtn} testID="es-back">
            <Ionicons name="chevron-back" size={20} color={colors.onSurface} />
          </Pressable>
          <View>
            <Text style={styles.title}>Email SMTP & Notifications</Text>
            <Text style={styles.subtitle}>Configure SMTP · automated triggers · send notifications</Text>
          </View>
        </View>

        <View style={styles.tabRow}>
          {([
            ["smtp", "SMTP Settings", "settings-outline"],
            ["triggers", "Automated Triggers", "flash-outline"],
            ["compose", "Compose & Send", "send-outline"],
            ["log", "Email Log", "list-outline"],
          ] as const).map(([k, lab, icon]) => (
            <Pressable
              key={k}
              onPress={() => setTab(k)}
              style={[styles.tabBtn, tab === k && styles.tabBtnOn]}
              testID={`es-tab-${k}`}
            >
              <Ionicons name={icon as any} size={14} color={tab === k ? "#fff" : colors.onSurfaceSecondary} />
              <Text style={[styles.tabTxt, tab === k && styles.tabTxtOn]}>{lab}</Text>
            </Pressable>
          ))}
        </View>

        {tab === "smtp" ? <SmtpSection /> : null}
        {tab === "triggers" ? <TriggersSection /> : null}
        {tab === "compose" ? <ComposeSection /> : null}
        {tab === "log" ? <LogSection /> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

/* ------------------------------------------------------------------ */
function SmtpSection() {
  const [s, setS] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [testTo, setTestTo] = useState("");

  useEffect(() => {
    api<{ settings: any }>("/admin/smtp-settings")
      .then((r) => setS(r.settings))
      .catch((e) => showMsg(e?.message || "Failed to load SMTP settings"));
  }, []);

  const save = async () => {
    if (!s) return;
    setBusy(true);
    try {
      const r = await api<{ settings: any }>("/admin/smtp-settings", { method: "PUT", body: s });
      setS(r.settings);
      showMsg("SMTP settings saved.");
    } catch (e: any) { showMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  const test = async () => {
    setTestBusy(true);
    try {
      const r = await api<{ detail: string }>("/admin/smtp-settings/test", {
        method: "POST", body: testTo ? { to_email: testTo } : {},
      });
      showMsg(r.detail || "Test email sent!");
    } catch (e: any) { showMsg(e?.message || "Test failed"); }
    finally { setTestBusy(false); }
  };

  if (!s) return <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} />;

  const setPort = (mode: "587" | "465") => {
    if (mode === "587") setS({ ...s, port: 587, start_tls: true, use_tls: false });
    else setS({ ...s, port: 465, start_tls: false, use_tls: true });
  };

  return (
    <View>
      <View style={styles.card}>
        <View style={{ flexDirection: "row", alignItems: "center" }}>
          <Text style={[styles.cardTitle, { flex: 1 }]}>SMTP Configuration</Text>
          <Text style={{ fontSize: 12, color: s.enabled ? "#166534" : colors.onSurfaceTertiary, fontWeight: "700", marginRight: 8 }}>
            {s.enabled ? "ENABLED" : "DISABLED"}
          </Text>
          <Switch
            value={!!s.enabled}
            onValueChange={(v) => setS({ ...s, enabled: v })}
            testID="es-smtp-enabled"
          />
        </View>
        <Text style={styles.hint}>
          For Gmail: use an App Password (Google Account → Security → 2-Step Verification → App passwords),
          NOT your normal Gmail password.
        </Text>

        <Text style={styles.lbl}>SMTP Host</Text>
        <TextInput style={styles.input} value={String(s.host ?? "")} autoCapitalize="none"
          onChangeText={(t) => setS({ ...s, host: t })} placeholder="smtp.gmail.com" testID="es-host" />

        <Text style={styles.lbl}>Port & Security</Text>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <Pressable onPress={() => setPort("587")}
            style={[styles.chip, s.port === 587 && styles.chipOn]} testID="es-port-587">
            <Text style={[styles.chipTxt, s.port === 587 && styles.chipTxtOn]}>587 · STARTTLS (recommended)</Text>
          </Pressable>
          <Pressable onPress={() => setPort("465")}
            style={[styles.chip, s.port === 465 && styles.chipOn]} testID="es-port-465">
            <Text style={[styles.chipTxt, s.port === 465 && styles.chipTxtOn]}>465 · SSL/TLS</Text>
          </Pressable>
        </View>

        <Text style={styles.lbl}>Email (SMTP username)</Text>
        <TextInput style={styles.input} value={String(s.username ?? "")} autoCapitalize="none"
          keyboardType="email-address" onChangeText={(t) => setS({ ...s, username: t })}
          placeholder="yourname@gmail.com" testID="es-username" />

        <Text style={styles.lbl}>App Password {s.password_set ? "(saved — leave as-is to keep)" : ""}</Text>
        <TextInput style={styles.input} value={String(s.password ?? "")} autoCapitalize="none"
          secureTextEntry onChangeText={(t) => setS({ ...s, password: t })}
          placeholder="16-character app password" testID="es-password" />

        <View style={{ flexDirection: "row", gap: 10 }}>
          <View style={{ flex: 1 }}>
            <Text style={styles.lbl}>From Name</Text>
            <TextInput style={styles.input} value={String(s.from_name ?? "")}
              onChangeText={(t) => setS({ ...s, from_name: t })} placeholder="S.K. Sharma & Co." testID="es-fromname" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.lbl}>From Email (optional)</Text>
            <TextInput style={styles.input} value={String(s.from_email ?? "")} autoCapitalize="none"
              onChangeText={(t) => setS({ ...s, from_email: t })} placeholder="same as username" testID="es-fromemail" />
          </View>
        </View>

        <Pressable onPress={save} disabled={busy} style={[styles.primaryBtn, busy && { opacity: 0.6 }]} testID="es-save">
          {busy ? <ActivityIndicator color="#fff" /> : (
            <><Ionicons name="save-outline" size={16} color="#fff" /><Text style={styles.primaryBtnTxt}>Save Settings</Text></>
          )}
        </Pressable>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Send Test Email</Text>
        <Text style={styles.lbl}>To (blank = your admin email)</Text>
        <TextInput style={styles.input} value={testTo} autoCapitalize="none" keyboardType="email-address"
          onChangeText={setTestTo} placeholder="test@example.com" testID="es-test-to" />
        <Pressable onPress={test} disabled={testBusy} style={[styles.secondaryBtn, { alignSelf: "flex-start" }]} testID="es-test-send">
          {testBusy ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : (
            <><Ionicons name="paper-plane-outline" size={14} color={colors.brandPrimary} /><Text style={styles.secondaryBtnTxt}>Send Test Email</Text></>
          )}
        </Pressable>
      </View>
    </View>
  );
}

/* ------------------------------------------------------------------ */
function TriggersSection() {
  const [triggers, setTriggers] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<{ triggers: any[] }>("/admin/email-triggers")
      .then((r) => setTriggers(r.triggers || []))
      .catch((e) => showMsg(e?.message || "Failed to load triggers"))
      .finally(() => setLoading(false));
  }, []);

  const upd = (i: number, patch: any) =>
    setTriggers((arr) => arr.map((t, j) => (j === i ? { ...t, ...patch } : t)));

  const save = async () => {
    setBusy(true);
    try {
      const body = {
        triggers: triggers.map((t) => ({
          ...t,
          extra_emails: typeof t.extra_emails_text === "string"
            ? t.extra_emails_text.split(",").map((x: string) => x.trim()).filter(Boolean)
            : (t.extra_emails || []),
        })),
      };
      await api("/admin/email-triggers", { method: "PUT", body });
      showMsg("Triggers saved.");
    } catch (e: any) { showMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  if (loading) return <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} />;

  return (
    <View>
      <Text style={[styles.hint, { marginBottom: 8 }]}>
        Placeholders you can use in subject/message: {"{employee_name} {employee_code} {firm_name} {date} {time} {details}"}
      </Text>
      {triggers.map((t, i) => (
        <View key={t.event} style={styles.card}>
          <View style={{ flexDirection: "row", alignItems: "center" }}>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardTitle}>{t.label}</Text>
              <Text style={styles.hint}>
                Sends to: {t.recipients === "employee" ? "the employee" : t.recipients === "admins" ? "firm admins" : "custom emails"}
              </Text>
            </View>
            <Switch value={!!t.enabled} onValueChange={(v) => upd(i, { enabled: v })} testID={`es-trigger-${t.event}`} />
          </View>
          {t.enabled ? (
            <View>
              {/* Iter 112 — daily report extras: send time + Send-now test */}
              {t.event === "daily_attendance_report" ? (
                <View>
                  <Text style={styles.lbl}>Send time (IST, 24-hr HH:MM) — report covers YESTERDAY</Text>
                  <View style={{ flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <TextInput
                      style={[styles.input, { width: 100, marginBottom: 0 }]}
                      value={t.send_time ?? "08:00"}
                      onChangeText={(x) => upd(i, { send_time: x.replace(/[^0-9:]/g, "").slice(0, 5) })}
                      placeholder="08:00"
                      maxLength={5}
                      testID="es-daily-send-time"
                    />
                    <Pressable
                      onPress={async () => {
                        try {
                          const r = await api<any>("/admin/email-triggers/daily-attendance/send-now", { method: "POST", body: {} });
                          const sent = (r.results || []).reduce((n: number, x: any) => n + (x.sent || 0), 0);
                          showMsg(`Daily report (${r.date}) queued — ${sent} email(s) sent. Check Email Log.`);
                        } catch (e: any) { showMsg(e?.message || "Send failed"); }
                      }}
                      style={styles.chip}
                      testID="es-daily-send-now"
                    >
                      <Text style={styles.chipTxt}>Send now (test)</Text>
                    </Pressable>
                    <Pressable
                      onPress={async () => {
                        try {
                          const r = await api<any>("/admin/email-triggers/daily-attendance/send-now", { method: "POST", body: { include_weekly: true } });
                          const sent = (r.results || []).reduce((n: number, x: any) => n + (x.sent || 0), 0);
                          showMsg(`Daily + weekly summary (${r.weekly?.from} → ${r.weekly?.to}) queued — ${sent} email(s) sent.`);
                        } catch (e: any) { showMsg(e?.message || "Send failed"); }
                      }}
                      style={styles.chip}
                      testID="es-daily-send-now-weekly"
                    >
                      <Text style={styles.chipTxt}>Send now + weekly (test)</Text>
                    </Pressable>
                  </View>
                  <Text style={[styles.hint, { marginTop: 6 }]}>
                    Every Monday morning the previous week&apos;s summary (Mon–Sun
                    totals, Excel + PDF) is attached automatically.
                  </Text>
                </View>
              ) : null}
              <Text style={styles.lbl}>Recipients</Text>
              <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
                {(["employee", "admins", "custom"] as const).map((m) => (
                  <Pressable key={m} onPress={() => upd(i, { recipients: m })}
                    style={[styles.chip, t.recipients === m && styles.chipOn]}>
                    <Text style={[styles.chipTxt, t.recipients === m && styles.chipTxtOn]}>
                      {m === "employee" ? "Employee" : m === "admins" ? "Firm Admins" : "Custom only"}
                    </Text>
                  </Pressable>
                ))}
              </View>
              <Text style={styles.lbl}>Extra emails (comma separated, always added)</Text>
              <TextInput style={styles.input} autoCapitalize="none"
                value={t.extra_emails_text ?? (t.extra_emails || []).join(", ")}
                onChangeText={(x) => upd(i, { extra_emails_text: x })}
                placeholder="hr@firm.com, owner@firm.com" />
              <Text style={styles.lbl}>Subject template</Text>
              <TextInput style={styles.input} value={t.subject ?? ""} onChangeText={(x) => upd(i, { subject: x })} />
              <Text style={styles.lbl}>Message template</Text>
              <TextInput style={[styles.input, { minHeight: 70, textAlignVertical: "top" }]} multiline
                value={t.body ?? ""} onChangeText={(x) => upd(i, { body: x })} />
            </View>
          ) : null}
        </View>
      ))}
      <Pressable onPress={save} disabled={busy} style={[styles.primaryBtn, busy && { opacity: 0.6 }]} testID="es-triggers-save">
        {busy ? <ActivityIndicator color="#fff" /> : (
          <><Ionicons name="save-outline" size={16} color="#fff" /><Text style={styles.primaryBtnTxt}>Save All Triggers</Text></>
        )}
      </Pressable>
    </View>
  );
}

/* ------------------------------------------------------------------ */
function ComposeSection() {
  const { user } = useAuth();
  const { selectedCompanyId: globalCid, companies } = useSelectedCompany();
  const isSuper = user?.role === "super_admin" || user?.role === "sub_admin";
  const [cid, setCid] = useState<string | null>(globalCid || user?.company_id || null);
  // User directive — one-click broadcast to EVERY firm at once.
  const [allFirms, setAllFirms] = useState(false);
  const [employees, setEmployees] = useState<any[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [allEmp, setAllEmp] = useState(true);
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [sendEmail, setSendEmail] = useState(true);
  const [sendInapp, setSendInapp] = useState(true);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  // User directive — file attachments shared with the mail.
  const [attachments, setAttachments] = useState<
    { name: string; mime: string; b64: string; size: number }[]
  >([]);

  const pickAttachment = async () => {
    try {
      const res = await DocumentPicker.getDocumentAsync({ copyToCacheDirectory: true });
      if (res.canceled || !res.assets?.length) return;
      const asset = res.assets[0];
      if ((asset.size || 0) > 10_000_000) { showMsg("File too large — max 10 MB per attachment."); return; }
      const resp = await fetch(asset.uri);
      const blob = await resp.blob();
      const b64 = await new Promise<string>((resolve, reject) => {
        const fr = new FileReader();
        fr.onload = () => { const s = String(fr.result || ""); resolve(s.includes(",") ? s.split(",")[1] : s); };
        fr.onerror = reject;
        fr.readAsDataURL(blob);
      });
      setAttachments((prev) => [...prev, {
        name: asset.name || "attachment",
        mime: asset.mimeType || "application/octet-stream",
        b64, size: asset.size || 0,
      }].slice(0, 5));
    } catch (e: any) { showMsg(e?.message || "Could not attach file"); }
  };

  const loadEmployees = useCallback(async () => {
    if (!cid) { setEmployees([]); return; }
    try {
      const r = await api<{ employees: any[] }>(`/admin/employees?company_id=${encodeURIComponent(cid)}`);
      setEmployees(r.employees || []);
    } catch { setEmployees([]); }
  }, [cid]);
  useEffect(() => { loadEmployees(); }, [loadEmployees]);

  const toggle = (uid: string) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(uid)) n.delete(uid); else n.add(uid);
    return n;
  });

  const send = async () => {
    if (!subject.trim() || !message.trim()) { showMsg("Enter subject and message"); return; }
    if (!allFirms && !allEmp && selected.size === 0) { showMsg("Select at least one employee, or choose All"); return; }
    setBusy(true);
    try {
      const r = await api<any>("/admin/notifications/compose", {
        method: "POST",
        body: {
          company_id: allFirms ? null : cid, subject: subject.trim(), message: message.trim(),
          send_email: sendEmail, send_inapp: sendInapp,
          all_companies: allFirms,
          all_employees: allFirms || allEmp,
          user_ids: allFirms || allEmp ? [] : Array.from(selected),
          attachments: attachments.map((a) => ({
            filename: a.name, mime: a.mime, content_base64: a.b64,
          })),
        },
      });
      showMsg(
        `Sent to ${r.targets} employee(s)${r.all_companies ? " across ALL firms" : ""} — in-app: ${r.inapp_sent}, emails queued: ${r.emails_queued}` +
        (r.attachments ? `, attachments: ${r.attachments}` : "") +
        (r.skipped_no_email ? ` (${r.skipped_no_email} have no email on record)` : ""),
      );
      setSubject(""); setMessage(""); setSelected(new Set()); setAttachments([]);
    } catch (e: any) { showMsg(e?.message || "Send failed"); }
    finally { setBusy(false); }
  };

  const visible = employees.filter((e) =>
    !search || (e.name || "").toLowerCase().includes(search.toLowerCase()) ||
    String(e.employee_code || "").includes(search));

  return (
    <View>
      {isSuper ? (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Select firm</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
            {/* User directive — mail EVERY company in a single click */}
            <Pressable onPress={() => { setAllFirms((v) => !v); setSelected(new Set()); }}
              style={[styles.chip, allFirms && styles.chipOn]} testID="es-firm-all">
              <Text style={[styles.chipTxt, allFirms && styles.chipTxtOn]}>📣 ALL FIRMS (single click)</Text>
            </Pressable>
            {(companies || []).map((c: any) => (
              <Pressable key={c.company_id} onPress={() => { setAllFirms(false); setCid(c.company_id); setSelected(new Set()); }}
                style={[styles.chip, !allFirms && cid === c.company_id && styles.chipOn]} testID={`es-firm-${c.company_id}`}>
                <Text style={[styles.chipTxt, !allFirms && cid === c.company_id && styles.chipTxtOn]}>{c.name}</Text>
              </Pressable>
            ))}
          </View>
          {allFirms ? (
            <Text style={{ fontSize: 11, color: "#B45309", marginTop: 6, fontWeight: "600" }}>
              ⚠ Broadcast mode — this mail goes to ALL employees of EVERY firm.
            </Text>
          ) : null}
        </View>
      ) : null}

      {!allFirms ? (
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Recipients</Text>
        <View style={{ flexDirection: "row", gap: 6, marginTop: 8 }}>
          <Pressable onPress={() => setAllEmp(true)} style={[styles.chip, allEmp && styles.chipOn]} testID="es-recip-all">
            <Text style={[styles.chipTxt, allEmp && styles.chipTxtOn]}>All employees</Text>
          </Pressable>
          <Pressable onPress={() => setAllEmp(false)} style={[styles.chip, !allEmp && styles.chipOn]} testID="es-recip-select">
            <Text style={[styles.chipTxt, !allEmp && styles.chipTxtOn]}>Select employees ({selected.size})</Text>
          </Pressable>
        </View>
        {!allEmp ? (
          <View style={{ marginTop: 8 }}>
            <TextInput style={styles.input} value={search} onChangeText={setSearch}
              placeholder="Search name / code…" autoCapitalize="none" />
            <ScrollView style={{ maxHeight: 220 }}>
              {visible.map((e) => (
                <Pressable key={e.user_id} onPress={() => toggle(e.user_id)}
                  style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 7, borderBottomWidth: 1, borderColor: colors.divider }}>
                  <Ionicons name={selected.has(e.user_id) ? "checkbox" : "square-outline"} size={18}
                    color={selected.has(e.user_id) ? colors.brandPrimary : colors.onSurfaceTertiary} />
                  <Text style={{ fontSize: 12.5, color: colors.onSurface, flex: 1 }}>
                    {e.employee_code ? `${e.employee_code} · ` : ""}{e.name}
                  </Text>
                  <Text style={{ fontSize: 11, color: e.email ? "#166534" : colors.onSurfaceTertiary }}>
                    {e.email || "no email"}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
          </View>
        ) : null}
      </View>
      ) : null}

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Message</Text>
        <Text style={styles.lbl}>Subject</Text>
        <TextInput style={styles.input} value={subject} onChangeText={setSubject}
          placeholder="e.g. Holiday on Monday" testID="es-compose-subject" />
        <Text style={styles.lbl}>Message</Text>
        <TextInput style={[styles.input, { minHeight: 100, textAlignVertical: "top" }]} multiline
          value={message} onChangeText={setMessage} placeholder="Write your notification…" testID="es-compose-message" />
        <View style={{ flexDirection: "row", gap: 16, marginTop: 6 }}>
          <Pressable onPress={() => setSendEmail((v) => !v)} style={{ flexDirection: "row", alignItems: "center", gap: 6 }} testID="es-chk-email">
            <Ionicons name={sendEmail ? "checkbox" : "square-outline"} size={18} color={sendEmail ? colors.brandPrimary : colors.onSurfaceTertiary} />
            <Text style={{ fontSize: 12.5, color: colors.onSurface }}>Send Email</Text>
          </Pressable>
          <Pressable onPress={() => setSendInapp((v) => !v)} style={{ flexDirection: "row", alignItems: "center", gap: 6 }} testID="es-chk-inapp">
            <Ionicons name={sendInapp ? "checkbox" : "square-outline"} size={18} color={sendInapp ? colors.brandPrimary : colors.onSurfaceTertiary} />
            <Text style={{ fontSize: 12.5, color: colors.onSurface }}>In-app Notification</Text>
          </Pressable>
        </View>

        {/* User directive — attachments (max 5 × 10 MB) */}
        <Text style={styles.lbl}>Attachments</Text>
        {attachments.map((a, i) => (
          <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 5 }}>
            <Ionicons name="document-attach-outline" size={16} color={colors.brandPrimary} />
            <Text style={{ fontSize: 12, color: colors.onSurface, flex: 1 }} numberOfLines={1}>
              {a.name} ({Math.round(a.size / 1024)} KB)
            </Text>
            <Pressable onPress={() => setAttachments((prev) => prev.filter((_, j) => j !== i))}
              hitSlop={8} testID={`es-att-del-${i}`}>
              <Ionicons name="close-circle" size={18} color="#B0002B" />
            </Pressable>
          </View>
        ))}
        <Pressable onPress={pickAttachment}
          style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 }}
          testID="es-att-add">
          <Ionicons name="add-circle-outline" size={18} color={colors.brandPrimary} />
          <Text style={{ color: colors.brandPrimary, fontWeight: "800", fontSize: 12.5 }}>
            Attach file (PDF / Excel / image…)
          </Text>
        </Pressable>

        <Pressable onPress={send} disabled={busy} style={[styles.primaryBtn, busy && { opacity: 0.6 }]} testID="es-compose-send">
          {busy ? <ActivityIndicator color="#fff" /> : (
            <><Ionicons name="send" size={16} color="#fff" /><Text style={styles.primaryBtnTxt}>Send Notification</Text></>
          )}
        </Pressable>
      </View>
    </View>
  );
}

/* ------------------------------------------------------------------ */
function LogSection() {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api<{ logs: any[] }>("/admin/email-log?limit=50")
      .then((r) => setLogs(r.logs || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);
  if (loading) return <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} />;
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>Recent emails ({logs.length})</Text>
      {logs.length === 0 ? <Text style={styles.hint}>No emails sent yet.</Text> : logs.map((l) => (
        <View key={l.log_id} style={{ paddingVertical: 8, borderBottomWidth: 1, borderColor: colors.divider }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Ionicons name={l.status === "sent" ? "checkmark-circle" : "close-circle"} size={15}
              color={l.status === "sent" ? "#16A34A" : "#DC2626"} />
            <Text style={{ fontSize: 12.5, fontWeight: "700", color: colors.onSurface, flex: 1 }} numberOfLines={1}>
              {l.subject}
            </Text>
            <Text style={{ fontSize: 10.5, color: colors.onSurfaceTertiary }}>{String(l.sent_at || "").slice(0, 16).replace("T", " ")}</Text>
          </View>
          <Text style={{ fontSize: 11.5, color: colors.onSurfaceTertiary, marginLeft: 21 }} numberOfLines={1}>
            → {l.to} · {l.event}{l.error ? ` · ${l.error}` : ""}
          </Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  headRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: spacing.md },
  backBtn: {
    width: 36, height: 36, borderRadius: 10, backgroundColor: colors.surface,
    alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.divider,
  },
  title: { ...type.h2, color: colors.onSurface, fontWeight: "800" },
  subtitle: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 2 },
  tabRow: { flexDirection: "row", gap: 6, marginBottom: spacing.md, flexWrap: "wrap" },
  tabBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999,
    borderWidth: 1, borderColor: colors.divider, backgroundColor: colors.surface,
  },
  tabBtnOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtOn: { color: "#fff" },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.divider, marginBottom: spacing.md, maxWidth: 760,
  },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  hint: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 4, lineHeight: 16 },
  lbl: {
    fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary,
    marginTop: 10, marginBottom: 4, textTransform: "uppercase",
  },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: Platform.OS === "web" ? 9 : 8,
    fontSize: 13.5, color: colors.onSurface, backgroundColor: colors.background,
  },
  chip: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999,
    borderWidth: 1, borderColor: colors.divider, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  chipTxtOn: { color: "#fff" },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brandPrimary, paddingVertical: 12, borderRadius: radius.md,
    marginTop: spacing.md, maxWidth: 320,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 13.5 },
  secondaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10,
    paddingHorizontal: 12, paddingVertical: 9, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  secondaryBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12.5 },
});
