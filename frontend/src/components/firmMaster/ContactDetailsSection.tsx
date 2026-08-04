/**
 * Iter 484 — Firm Master → 4. Contact Details (new normalized section).
 * All communication details of the company. Contacts are stored NORMALIZED
 * (db.company_contacts, one doc per person) so unlimited contacts can be
 * added per type. Auto-saves 2s after the last edit.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, Platform, useWindowDimensions, Linking,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api/client";
import { colors, spacing } from "@/src/theme";
import { Card, FieldV2, DropdownV2, CheckRow, MiniBtn, EMAIL_RE } from "./primitives";

type Contact = {
  contact_id?: string;
  contact_type: string;
  name: string;
  designation: string;
  mobile: string;
  alt_mobile: string;
  email: string;
  personal_email: string;
  whatsapp: string;
  country_code: string;
  recipient_permissions: Record<string, boolean>;
  sort_order: number;
};

const CARDS: { type: string; title: string; icon: keyof typeof Ionicons.glyphMap; accent: string; nameLbl: string; full?: boolean }[] = [
  { type: "primary", title: "Primary Contact", icon: "person", accent: "#1D4ED8", nameLbl: "Contact Person Name", full: true },
  { type: "hr", title: "HR Contact", icon: "people", accent: "#7C3AED", nameLbl: "HR Manager Name" },
  { type: "payroll", title: "Payroll Contact", icon: "cash", accent: "#059669", nameLbl: "Payroll Executive" },
  { type: "compliance", title: "Compliance Contact", icon: "shield-checkmark", accent: "#D97706", nameLbl: "Compliance Officer" },
  { type: "accounts", title: "Accounts Contact", icon: "calculator", accent: "#0891B2", nameLbl: "Accounts Head" },
];

const RECIPIENTS: [string, string][] = [
  ["payroll_reports", "Payroll Reports"],
  ["compliance_reports", "Compliance Reports"],
  ["bank_advice", "Bank Advice"],
  ["pf_notices", "PF Notices"],
  ["esic_notices", "ESIC Notices"],
  ["leave_notifications", "Leave Notifications"],
  ["attendance_alerts", "Attendance Alerts"],
];

const COUNTRY_CODES = ["+91", "+971", "+1", "+44", "+65"];

const COMM_EMAILS: [string, string, boolean][] = [
  ["official_email", "Official Company Email", true],
  ["support_email", "Support Email", false],
  ["billing_email", "Billing Email", false],
  ["compliance_email", "Compliance Email", false],
  ["recruitment_email", "Recruitment Email", false],
  ["noreply_email", "No Reply Email", false],
];

const PREFS: [string, string][] = [
  ["send_payroll_emails", "Send Payroll Emails"],
  ["send_compliance_alerts", "Send Compliance Alerts"],
  ["send_invoice_emails", "Send Invoice Emails"],
  ["send_employee_notifications", "Send Employee Notifications"],
  ["whatsapp_notifications", "WhatsApp Notifications Enabled"],
];

function emptyContact(type: string): Contact {
  return {
    contact_type: type, name: "", designation: "", mobile: "", alt_mobile: "",
    email: "", personal_email: "", whatsapp: "", country_code: "+91",
    recipient_permissions: {}, sort_order: 0,
  };
}

const mobileErr = (v: string, cc: string) =>
  v && cc === "+91" && !/^\d{10}$/.test(v) ? "Enter a valid 10-digit mobile" : null;
const emailErr = (v: string) => (v && !EMAIL_RE.test(v) ? "Invalid email format" : null);

export default function ContactDetailsSection({
  master, updateSection, companyId,
}: {
  master: any;
  updateSection: (section: string, patch: Record<string, any>) => void;
  companyId: string;
}) {
  const { width } = useWindowDimensions();
  const twoCol = width >= 900;
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [saveState, setSaveState] = useState<"" | "saving" | "saved" | "error">("");
  const [saveErr, setSaveErr] = useState("");
  const timer = useRef<any>(null);
  const dirtyRef = useRef(false);

  const comm = master.communication || {};
  const prefs = master.comm_prefs || {};

  const load = useCallback(async () => {
    try {
      const r = await api<{ contacts: Contact[] }>(`/admin/firm-master/${companyId}/contacts`);
      setContacts(r.contacts || []);
    } catch {} finally { setLoaded(true); }
  }, [companyId]);
  useEffect(() => { void load(); }, [load]);

  const persist = useCallback(async (rows: Contact[]) => {
    setSaveState("saving");
    try {
      const r = await api<{ contacts: Contact[] }>(`/admin/firm-master/${companyId}/contacts`, {
        method: "PUT", body: { contacts: rows },
      });
      setContacts(r.contacts || rows);
      setSaveState("saved"); setSaveErr("");
      dirtyRef.current = false;
    } catch (e: any) {
      setSaveState("error"); setSaveErr(e?.message || "Save failed");
    }
  }, [companyId]);

  // Auto-save contacts 2s after last edit.
  const scheduleSave = (rows: Contact[]) => {
    dirtyRef.current = true;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void persist(rows), 2000);
  };

  const editContact = (idx: number, patch: Partial<Contact>) => {
    setContacts((prev) => {
      const rows = [...prev];
      rows[idx] = { ...rows[idx], ...patch };
      scheduleSave(rows);
      return rows;
    });
  };
  const addContact = (type: string) => {
    setContacts((prev) => {
      const rows = [...prev, { ...emptyContact(type), sort_order: prev.filter((c) => c.contact_type === type).length }];
      scheduleSave(rows);
      return rows;
    });
  };
  const removeContact = (idx: number) => {
    if (Platform.OS === "web" && !window.confirm("Remove this contact?")) return;
    setContacts((prev) => {
      const rows = prev.filter((_, i) => i !== idx);
      scheduleSave(rows);
      return rows;
    });
  };

  // Duplicate-email detection across every email field.
  const allEmails: string[] = [];
  contacts.forEach((c) => {
    [c.email, c.personal_email].forEach((e) => { if ((e || "").trim()) allEmails.push(e.trim().toLowerCase()); });
  });
  const dupSet = new Set(allEmails.filter((e, i) => allEmails.indexOf(e) !== i));

  // ---- quick actions -------------------------------------------------------
  const testEmail = async () => {
    if (Platform.OS !== "web") return;
    const to = window.prompt("Send a test email to:", comm.official_email || "");
    if (!to) return;
    try {
      const r = await api<{ detail?: string }>("/admin/smtp-settings/test", {
        method: "POST", body: { to_email: to },
      });
      window.alert(r.detail || "Test email sent ✓");
    } catch (e: any) {
      window.alert(e?.message || "Test email failed — configure SMTP in Communication → Email Settings first.");
    }
  };
  const testWhatsapp = async () => {
    if (Platform.OS !== "web") return;
    const to = window.prompt("Send a test WhatsApp message to (10-digit number):",
      comm.company_whatsapp || "");
    if (!to) return;
    try {
      const r = await api<{ ok: boolean; configured: boolean; detail: string }>(
        `/admin/firm-master/${companyId}/test-whatsapp`,
        { method: "POST", body: { to } });
      window.alert(r.detail || (r.ok ? "Test message queued ✓" : "Could not send"));
    } catch (e: any) { window.alert(e?.message || "Test failed"); }
  };
  // Iter 487 — manual trigger for the 60/30/7-day document expiry alerts.
  const checkExpiringDocs = async () => {
    if (Platform.OS !== "web") return;
    try {
      const r = await api<{ detail?: string; found?: number; sent?: number }>(
        `/admin/doc-expiry-alerts/run-now?company_id=${companyId}`, { method: "POST" });
      window.alert(r.detail || `${r.found ?? 0} document(s) in an alert window; ${r.sent ?? 0} email(s) sent.`);
    } catch (e: any) { window.alert(e?.message || "Check failed"); }
  };
  const copyContact = (c: Contact) => {
    if (Platform.OS !== "web") return;
    const txt = `${c.name}${c.designation ? ` (${c.designation})` : ""}\nMobile: ${c.country_code || "+91"} ${c.mobile}\nEmail: ${c.email}`;
    (navigator as any).clipboard?.writeText(txt);
    window.alert("Contact copied to clipboard ✓");
  };
  const downloadVcard = async (c: Contact) => {
    if (Platform.OS !== "web" || !c.contact_id) return;
    try {
      const tok = window.localStorage.getItem("llc_session_token") || "";
      const url = `/api/admin/firm-master/${companyId}/contacts/${c.contact_id}/vcard?token=${tok}`;
      window.open(url, "_blank");
    } catch {}
  };
  const clickToCall = (c: Contact) => {
    if (!c.mobile) return;
    void Linking.openURL(`tel:${(c.country_code || "+91")}${c.mobile}`);
  };

  const contactCard = (cfg: typeof CARDS[number]) => {
    const rows = contacts.map((c, i) => ({ c, i })).filter((x) => x.c.contact_type === cfg.type);
    return (
      <Card key={cfg.type} icon={cfg.icon} title={cfg.title} accent={cfg.accent}>
        {rows.length === 0 ? (
          <Text style={st.emptyTxt}>No {cfg.title.toLowerCase()} added yet.</Text>
        ) : null}
        {rows.map(({ c, i }, ri) => (
          <View key={c.contact_id || `new-${i}`} style={[st.contactBlock, ri > 0 && st.contactBlockDivider]}>
            <View style={st.rowWrap}>
              <FieldV2 label={cfg.nameLbl} required={cfg.type === "primary"}
                       value={c.name} testID={`cd-${cfg.type}-name-${ri}`}
                       error={cfg.type === "primary" && !c.name.trim() ? "Name is required" : null}
                       onChange={(v) => editContact(i, { name: v })} />
              <FieldV2 label="Designation" value={c.designation}
                       onChange={(v) => editContact(i, { designation: v })} />
            </View>
            <View style={st.rowWrap}>
              <View style={{ width: 92 }}>
                <DropdownV2 label="Code" value={c.country_code || "+91"} options={COUNTRY_CODES}
                            onChange={(v) => editContact(i, { country_code: v || "+91" })} />
              </View>
              <FieldV2 label={cfg.type === "primary" ? "Mobile Number" : "Mobile"}
                       required={cfg.type === "primary"}
                       value={c.mobile} keyboardType="phone-pad" maxLength={12}
                       error={mobileErr(c.mobile, c.country_code || "+91")
                         || (cfg.type === "primary" && !c.mobile.trim() ? "Mobile is required" : null)}
                       onChange={(v) => editContact(i, { mobile: v.replace(/[^0-9]/g, "") })}
                       rightSlot={c.mobile ? (
                         <Pressable onPress={() => clickToCall(c)} style={st.callBtn} testID={`cd-call-${cfg.type}-${ri}`}>
                           <Ionicons name="call" size={14} color="#059669" />
                         </Pressable>
                       ) : undefined} />
              {cfg.full ? (
                <FieldV2 label="Alternate Mobile" value={c.alt_mobile} keyboardType="phone-pad" maxLength={12}
                         error={mobileErr(c.alt_mobile, c.country_code || "+91")}
                         onChange={(v) => editContact(i, { alt_mobile: v.replace(/[^0-9]/g, "") })} />
              ) : null}
            </View>
            <View style={st.rowWrap}>
              <FieldV2 label={cfg.type === "primary" ? "Official Email" : "Email"}
                       required={cfg.type === "primary"}
                       value={c.email} keyboardType="email-address" autoCapitalize="none"
                       error={emailErr(c.email)
                         || (dupSet.has((c.email || "").trim().toLowerCase()) && c.email ? "Duplicate email" : null)
                         || (cfg.type === "primary" && !c.email.trim() ? "Official email is required" : null)}
                       onChange={(v) => editContact(i, { email: v })} />
              {cfg.full ? (
                <FieldV2 label="Personal Email" value={c.personal_email}
                         keyboardType="email-address" autoCapitalize="none"
                         error={emailErr(c.personal_email)
                           || (dupSet.has((c.personal_email || "").trim().toLowerCase()) && c.personal_email ? "Duplicate email" : null)}
                         onChange={(v) => editContact(i, { personal_email: v })} />
              ) : null}
              {cfg.type !== "payroll" && cfg.type !== "compliance" && cfg.type !== "accounts" ? (
                <FieldV2 label="WhatsApp Number" value={c.whatsapp} keyboardType="phone-pad" maxLength={12}
                         error={mobileErr(c.whatsapp, c.country_code || "+91")}
                         onChange={(v) => editContact(i, { whatsapp: v.replace(/[^0-9]/g, "") })} />
              ) : null}
            </View>
            {/* Receives: recipient permissions */}
            <Text style={st.recvLbl}>Receives:</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
              {RECIPIENTS.map(([k, lbl]) => {
                const on = !!c.recipient_permissions?.[k];
                return (
                  <Pressable key={k}
                    onPress={() => editContact(i, {
                      recipient_permissions: { ...(c.recipient_permissions || {}), [k]: !on },
                    })}
                    style={[st.recvChip, on && { backgroundColor: cfg.accent + "22", borderColor: cfg.accent }]}
                    testID={`cd-recv-${cfg.type}-${k}-${ri}`}>
                    <Ionicons name={on ? "checkmark-circle" : "ellipse-outline"} size={12}
                              color={on ? cfg.accent : colors.onSurfaceTertiary} />
                    <Text style={[st.recvChipTxt, on && { color: cfg.accent, fontWeight: "700" }]}>{lbl}</Text>
                  </Pressable>
                );
              })}
            </View>
            <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
              <MiniBtn icon="copy-outline" label="Copy" tone="neutral" onPress={() => copyContact(c)} />
              <MiniBtn icon="download-outline" label="vCard" tone="neutral"
                       onPress={() => downloadVcard(c)} disabled={!c.contact_id} />
              <MiniBtn icon="trash-outline" label="Remove" tone="danger"
                       onPress={() => removeContact(i)} testID={`cd-del-${cfg.type}-${ri}`} />
            </View>
          </View>
        ))}
        <MiniBtn icon="add-circle-outline"
                 label={rows.length === 0 ? `Add ${cfg.title}` : "Add another"}
                 onPress={() => addContact(cfg.type)} testID={`cd-add-${cfg.type}`} />
      </Card>
    );
  };

  if (!loaded) return <Text style={st.emptyTxt}>Loading contacts…</Text>;

  return (
    <View style={{ gap: spacing.md }}>
      {/* Save state strip */}
      <View style={st.stateStrip}>
        <Ionicons
          name={saveState === "saving" ? "sync" : saveState === "error" ? "warning" : "cloud-done-outline"}
          size={14}
          color={saveState === "error" ? colors.error : colors.onSurfaceSecondary} />
        <Text style={[st.stateTxt, saveState === "error" && { color: colors.error }]}>
          {saveState === "saving" ? "Auto-saving contacts…"
            : saveState === "error" ? `Auto-save failed: ${saveErr}`
              : saveState === "saved" ? "Contacts saved ✓"
                : "Contacts auto-save 2s after you stop typing"}
        </Text>
        <View style={{ flex: 1 }} />
        <MiniBtn icon="mail-outline" label="Send Test Email" onPress={testEmail} testID="cd-test-email" />
        <MiniBtn icon="logo-whatsapp" label="Send Test WhatsApp" onPress={testWhatsapp} testID="cd-test-wa" />
      </View>

      {/* Contact cards in a 2-col grid on desktop */}
      <View style={{ flexDirection: twoCol ? "row" : "column", flexWrap: "wrap", gap: spacing.md }}>
        {CARDS.map((cfg) => (
          <View key={cfg.type} style={twoCol ? { flexBasis: "48.7%", flexGrow: 1, minWidth: 380 } : undefined}>
            {contactCard(cfg)}
          </View>
        ))}
      </View>

      {/* Card 6 — Company Communication (saved with the master via PATCH) */}
      <Card icon="globe" title="Company Communication" accent="#334155"
            subtitle="Company-level emails & channels — saved with the Firm Master">
        <View style={st.rowWrap}>
          {COMM_EMAILS.slice(0, 3).map(([k, lbl, req]) => (
            <FieldV2 key={k} label={lbl} required={req} value={comm[k]}
                     keyboardType="email-address" autoCapitalize="none"
                     error={emailErr(comm[k]) || (req && !(comm[k] || "").trim() ? "Required" : null)}
                     onChange={(v) => updateSection("communication", { [k]: v })} />
          ))}
        </View>
        <View style={st.rowWrap}>
          {COMM_EMAILS.slice(3).map(([k, lbl]) => (
            <FieldV2 key={k} label={lbl} value={comm[k]}
                     keyboardType="email-address" autoCapitalize="none"
                     error={emailErr(comm[k])}
                     onChange={(v) => updateSection("communication", { [k]: v })} />
          ))}
        </View>
        <View style={st.rowWrap}>
          <FieldV2 label="Website" value={comm.website} autoCapitalize="none"
                   placeholder="https://..."
                   onChange={(v) => updateSection("communication", { website: v })} />
          <FieldV2 label="Company WhatsApp" value={comm.company_whatsapp}
                   keyboardType="phone-pad" maxLength={12}
                   onChange={(v) => updateSection("communication", { company_whatsapp: v.replace(/[^0-9]/g, "") })} />
          <FieldV2 label="Landline Number" value={comm.landline}
                   keyboardType="phone-pad"
                   onChange={(v) => updateSection("communication", { landline: v })} />
          <FieldV2 label="Fax Number" value={comm.fax}
                   keyboardType="phone-pad"
                   onChange={(v) => updateSection("communication", { fax: v })} />
        </View>
      </Card>

      {/* Communication preferences */}
      <Card icon="notifications" title="Communication Preferences" accent="#7C3AED">
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
          {PREFS.map(([k, lbl]) => (
            <CheckRow key={k} label={lbl} value={!!prefs[k]}
                      testID={`cd-pref-${k}`}
                      onChange={(v) => updateSection("comm_prefs", { [k]: v })} />
          ))}
        </View>
        <Text style={st.emptyTxt}>
          SMS notifications are not configured (no SMS provider) — WhatsApp &
          Email channels are used instead.
        </Text>
        <Text style={st.emptyTxt}>
          With &quot;Send Compliance Alerts&quot; ON, an email goes automatically 60 / 30 /
          7 days before (and on the day) any Firm Master compliance document or
          contractor CLRA licence expires — to every contact ticked for
          &quot;Compliance Reports&quot; plus the Compliance / Official email above.
          Requires SMTP (Communication → Email Settings).
        </Text>
        <View style={{ flexDirection: "row", marginTop: 6 }}>
          <MiniBtn icon="alarm-outline" label="Check Expiring Docs Now"
                   onPress={checkExpiringDocs} testID="cd-check-expiry" />
        </View>
      </Card>
    </View>
  );
}

const st = StyleSheet.create({
  rowWrap: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  emptyTxt: { fontSize: 11.5, color: colors.onSurfaceTertiary },
  contactBlock: { gap: 8 },
  contactBlockDivider: {
    borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: 12, marginTop: 6,
  },
  recvLbl: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 2 },
  recvChip: {
    flexDirection: "row", alignItems: "center", gap: 4, borderWidth: 1,
    borderColor: colors.border, borderRadius: 999, paddingHorizontal: 8,
    paddingVertical: 4, backgroundColor: colors.surface,
  },
  recvChipTxt: { fontSize: 10.5, color: colors.onSurfaceSecondary },
  callBtn: {
    width: 32, height: 32, borderRadius: 8, borderWidth: 1, borderColor: "#05966966",
    alignItems: "center", justifyContent: "center", backgroundColor: "#05966911",
  },
  stateStrip: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8, flexWrap: "wrap",
  },
  stateTxt: { fontSize: 11.5, color: colors.onSurfaceSecondary },
});
