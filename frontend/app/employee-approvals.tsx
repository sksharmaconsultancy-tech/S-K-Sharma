/**
 * Iter 285 — Pending Employee Approval dashboard (Onboarding Approval
 * Workflow Phase 1).
 *
 *  • Firm dropdown + policy settings card (toggles saved per firm)
 *  • Pending / Hold / Rejected employees with photo, code, dept,
 *    designation, DOJ, today's punches, document checklist, shift and
 *    expiry state
 *  • Approve / Reject / Hold with remarks — releases held attendance
 *    into payroll on approval.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  ActivityIndicator, TextInput, Platform, Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "../src/api/client";
import { colors } from "../src/theme";

type Company = { company_id: string; name: string };
type Settings = Record<string, any>;
type PendingEmp = {
  user_id: string; name: string; employee_code?: string | null;
  department?: string | null; designation?: string | null; doj?: string | null;
  phone?: string | null; shift_name?: string | null;
  shift_start?: string | null; shift_end?: string | null;
  onboarding_status: string; onboarding_pending_since?: string | null;
  onboarding_remarks?: string | null; onboarding_decided_by_name?: string | null;
  first_punch?: string | null; last_punch?: string | null;
  punch_source?: string | null; punch_count_today?: number;
  photo_doc_id?: string | null;
  has_aadhaar?: boolean; has_pan?: boolean; has_bank?: boolean;
  has_uan?: boolean; has_esic?: boolean;
  expired?: boolean; expires_at?: string | null;
};

const TOGGLES: { key: string; label: string }[] = [
  { key: "require_hr_approval", label: "Require HR Approval Before Activation" },
  { key: "allow_punch", label: "Allow Punch Before Approval" },
  { key: "store_attendance", label: "Store Attendance Until Approval (held, not payrolled)" },
  { key: "allow_mobile_login", label: "Allow Mobile Login Before Approval" },
  { key: "allow_web_login", label: "Allow Web Login Before Approval" },
  { key: "allow_face", label: "Allow Face Recognition Before Approval" },
  { key: "allow_biometric", label: "Allow Biometric Punch Before Approval" },
  { key: "allow_geo", label: "Allow Geo Attendance Before Approval" },
  { key: "allow_salary", label: "Allow Salary Processing Before Approval" },
  { key: "allow_leave", label: "Allow Leave Calculation Before Approval" },
  { key: "allow_ot", label: "Allow OT Calculation Before Approval" },
  { key: "allow_pf", label: "Allow PF Processing Before Approval" },
  { key: "allow_esic", label: "Allow ESIC Processing Before Approval" },
  { key: "allow_tds", label: "Allow TDS Processing Before Approval" },
  { key: "auto_activate", label: "Auto Activate After Approval" },
];

function StatusChip({ status, expired }: { status: string; expired?: boolean }) {
  const map: Record<string, { bg: string; fg: string; label: string }> = {
    pending_approval: { bg: "#FEF3C7", fg: "#92400E", label: "PENDING APPROVAL" },
    hold: { bg: "#E0E7FF", fg: "#3730A3", label: "ON HOLD" },
    rejected: { bg: "#FEE2E2", fg: "#B91C1C", label: "REJECTED" },
  };
  const s = map[status] || { bg: "#F1F5F9", fg: "#475569", label: status.toUpperCase() };
  return (
    <View style={{ flexDirection: "row", gap: 6 }}>
      <View style={[st.chip, { backgroundColor: s.bg }]}>
        <Text style={[st.chipTxt, { color: s.fg }]}>{s.label}</Text>
      </View>
      {expired ? (
        <View style={[st.chip, { backgroundColor: "#FEE2E2" }]}>
          <Text style={[st.chipTxt, { color: "#B91C1C" }]}>⏰ EXPIRED</Text>
        </View>
      ) : null}
    </View>
  );
}

function DocFlag({ ok, label }: { ok?: boolean; label: string }) {
  return (
    <View style={[st.docFlag, { backgroundColor: ok ? "#DCFCE7" : "#F1F5F9" }]}>
      <Ionicons name={ok ? "checkmark-circle" : "ellipse-outline"} size={12}
        color={ok ? "#15803D" : "#94A3B8"} />
      <Text style={[st.docFlagTxt, { color: ok ? "#15803D" : "#64748B" }]}>{label}</Text>
    </View>
  );
}

function EmpCard({ e, busy, onDecide }: {
  e: PendingEmp; busy: boolean;
  onDecide: (uid: string, action: string, remarks: string) => void;
}) {
  const [remarks, setRemarks] = useState("");
  const [photo, setPhoto] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    if (e.photo_doc_id) {
      api<{ document: any }>(`/admin/employees/${e.user_id}/documents/${e.photo_doc_id}`)
        .then((r) => {
          if (alive && r.document?.base64) {
            setPhoto(`data:${r.document.mime_type || "image/jpeg"};base64,${r.document.base64}`);
          }
        })
        .catch(() => {});
    }
    return () => { alive = false; };
  }, [e.photo_doc_id, e.user_id]);

  return (
    <View style={st.empCard} testID={`ob-emp-${e.user_id}`}>
      <View style={{ flexDirection: "row", gap: 12 }}>
        {photo ? (
          <Image source={{ uri: photo }} style={st.empPhoto} />
        ) : (
          <View style={[st.empPhoto, st.empPhotoEmpty]}>
            <Ionicons name="person-outline" size={26} color={colors.onSurfaceTertiary} />
          </View>
        )}
        <View style={{ flex: 1, gap: 3 }}>
          <Text style={st.empName}>
            {e.name} {e.employee_code ? `· #${e.employee_code}` : ""}
          </Text>
          <Text style={st.empSub}>
            {[e.designation, e.department].filter(Boolean).join(" · ") || "—"}
            {e.doj ? ` · DOJ ${e.doj}` : ""}
          </Text>
          <Text style={st.empSub}>
            Shift: {e.shift_name || (e.shift_start ? `${e.shift_start}–${e.shift_end}` : "—")}
            {" · "}Today: {e.first_punch
              ? `IN ${e.first_punch}${e.last_punch ? ` → ${e.last_punch}` : ""} (${e.punch_source || "—"})`
              : "no punch"}
          </Text>
          <StatusChip status={e.onboarding_status} expired={e.expired} />
        </View>
      </View>
      <View style={st.docRow}>
        <DocFlag ok={e.has_aadhaar} label="Aadhaar" />
        <DocFlag ok={e.has_pan} label="PAN" />
        <DocFlag ok={e.has_bank} label="Bank" />
        <DocFlag ok={e.has_uan} label="UAN" />
        <DocFlag ok={e.has_esic} label="ESIC" />
      </View>
      {e.onboarding_remarks ? (
        <Text style={st.prevRemark}>
          Last remark: {e.onboarding_remarks}
          {e.onboarding_decided_by_name ? ` — ${e.onboarding_decided_by_name}` : ""}
        </Text>
      ) : null}
      <TextInput
        value={remarks}
        onChangeText={setRemarks}
        placeholder="Remarks (kept in audit log)…"
        placeholderTextColor={colors.onSurfaceTertiary}
        style={st.remarksInput}
        testID={`ob-remarks-${e.user_id}`}
      />
      <View style={st.btnRow}>
        <Pressable
          disabled={busy}
          onPress={() => onDecide(e.user_id, "approve", remarks)}
          style={[st.actBtn, { backgroundColor: "#16A34A" }]}
          testID={`ob-approve-${e.user_id}`}
        >
          <Ionicons name="checkmark" size={15} color="#fff" />
          <Text style={st.actBtnTxt}>Approve</Text>
        </Pressable>
        <Pressable
          disabled={busy}
          onPress={() => onDecide(e.user_id, "hold", remarks)}
          style={[st.actBtn, { backgroundColor: "#4338CA" }]}
          testID={`ob-hold-${e.user_id}`}
        >
          <Ionicons name="pause" size={15} color="#fff" />
          <Text style={st.actBtnTxt}>Hold</Text>
        </Pressable>
        <Pressable
          disabled={busy}
          onPress={() => onDecide(e.user_id, "reject", remarks)}
          style={[st.actBtn, { backgroundColor: "#DC2626" }]}
          testID={`ob-reject-${e.user_id}`}
        >
          <Ionicons name="close" size={15} color="#fff" />
          <Text style={st.actBtnTxt}>Reject</Text>
        </Pressable>
      </View>
    </View>
  );
}

export default function EmployeeApprovalsScreen() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [emps, setEmps] = useState<PendingEmp[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api<{ companies: Company[] }>("/companies")
      .then((r) => {
        setCompanies(r.companies || []);
        if (r.companies?.length) setCompanyId((p) => p || r.companies[0].company_id);
      })
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      const r = await api<{ settings: Settings; employees: PendingEmp[] }>(
        `/admin/onboarding-approvals?company_id=${companyId}`,
      );
      setSettings(r.settings);
      setEmps(r.employees || []);
    } catch (e: any) {
      setMsg(e?.message || "Failed to load");
    } finally { setLoading(false); }
  }, [companyId]);
  useEffect(() => { void load(); }, [load]);

  const saveSettings = async (next: Settings) => {
    setSettings(next);
    setSaving(true);
    try {
      await api(`/admin/companies/${companyId}/onboarding-approval`, {
        method: "PUT", body: next,
      });
    } catch (e: any) {
      setMsg(e?.message || "Save failed");
    } finally { setSaving(false); }
  };

  const decide = async (uid: string, action: string, remarks: string) => {
    if (Platform.OS === "web" && action !== "hold") {
      const verb = action === "approve" ? "APPROVE" : "REJECT";
      if (!window.confirm(`${verb} this employee?`)) return;
    }
    setBusy(true);
    try {
      await api(`/admin/onboarding-approvals/${uid}/decide`, {
        method: "POST", body: { action, remarks },
      });
      setMsg(action === "approve"
        ? "Approved — held attendance is now payroll-eligible."
        : action === "reject" ? "Rejected." : "Put on hold.");
      void load();
    } catch (e: any) {
      setMsg(e?.message || "Action failed");
    } finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.surfaceSecondary }} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="ob-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={st.headerTitle}>Pending Employee Approval</Text>
        <Pressable onPress={() => void load()} hitSlop={10} testID="ob-refresh">
          <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 16, gap: 12 }}>
        {/* Firm picker */}
        <View style={st.card}>
          <Text style={st.cardTitle}>Firm</Text>
          {Platform.OS === "web" ? (
            <select
              value={companyId}
              onChange={(ev) => setCompanyId((ev.target as HTMLSelectElement).value)}
              style={st.firmSelect as any}
              data-testid="ob-firm-select"
            >
              {companies.map((c) => (
                <option key={c.company_id} value={c.company_id}>{c.name}</option>
              ))}
            </select>
          ) : (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
              {companies.map((c) => (
                <Pressable key={c.company_id} onPress={() => setCompanyId(c.company_id)}
                  style={[st.fChip, companyId === c.company_id && st.fChipOn]}>
                  <Text style={[st.fChipTxt, companyId === c.company_id && { color: "#fff" }]}>
                    {c.name}
                  </Text>
                </Pressable>
              ))}
            </View>
          )}
        </View>

        {/* Settings */}
        {settings ? (
          <View style={st.card}>
            <Pressable
              onPress={() => setShowSettings((v) => !v)}
              style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
              testID="ob-settings-toggle"
            >
              <Ionicons name={showSettings ? "chevron-down" : "chevron-forward"}
                size={16} color={colors.onSurfaceSecondary} />
              <Text style={st.cardTitle}>
                Onboarding Approval Policy — {settings.enabled ? "ENABLED" : "DISABLED"}
              </Text>
              {saving ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : null}
            </Pressable>
            <Pressable
              onPress={() => saveSettings({ ...settings, enabled: !settings.enabled })}
              style={[st.masterToggle, settings.enabled && { backgroundColor: "#16A34A" }]}
              testID="ob-enable-toggle"
            >
              <Text style={st.masterToggleTxt}>
                {settings.enabled
                  ? "✓ Employee Approval Workflow is ON — new employees need approval"
                  : "Enable Employee Approval Workflow (currently OFF)"}
              </Text>
            </Pressable>
            {showSettings ? (
              <View style={{ gap: 6, marginTop: 8 }}>
                {TOGGLES.map((t) => (
                  <Pressable
                    key={t.key}
                    onPress={() => saveSettings({ ...settings, [t.key]: !settings[t.key] })}
                    style={st.togRow}
                    testID={`ob-tog-${t.key}`}
                  >
                    <Ionicons
                      name={settings[t.key] ? "checkbox" : "square-outline"}
                      size={18}
                      color={settings[t.key] ? colors.brandPrimary : colors.onSurfaceTertiary}
                    />
                    <Text style={st.togTxt}>{t.label}</Text>
                  </Pressable>
                ))}
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 }}>
                  <Text style={st.togTxt}>Approval Expiry:</Text>
                  {[0, 1, 3, 7].map((d) => (
                    <Pressable
                      key={d}
                      onPress={() => saveSettings({ ...settings, approval_expiry_days: d })}
                      style={[st.expChip, settings.approval_expiry_days === d && st.expChipOn]}
                    >
                      <Text style={[st.expChipTxt,
                        settings.approval_expiry_days === d && { color: "#fff" }]}>
                        {d === 0 ? "Unlimited" : `${d} Day${d > 1 ? "s" : ""}`}
                      </Text>
                    </Pressable>
                  ))}
                </View>
                <Text style={st.hint}>
                  Expired items are flagged ⏰ on this dashboard (no auto-action).
                  Approvers follow the Workflow Builder → &quot;Employee Creation&quot; chain
                  when one is enabled for this firm.
                </Text>
              </View>
            ) : null}
          </View>
        ) : null}

        {msg ? (
          <Pressable onPress={() => setMsg(null)} style={st.msgBar}>
            <Text style={st.msgTxt}>{msg} (tap to dismiss)</Text>
          </Pressable>
        ) : null}

        {/* Pending list */}
        <View style={st.card}>
          <Text style={st.cardTitle}>
            {emps.length} employee(s) awaiting decision
          </Text>
          {loading ? (
            <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 20 }} />
          ) : emps.length === 0 ? (
            <Text style={st.hint}>
              No pending employees. New hires appear here automatically when the
              policy is enabled and an employee is added.
            </Text>
          ) : (
            emps.map((e) => (
              <EmpCard key={e.user_id} e={e} busy={busy} onDecide={decide} />
            ))
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  headerTitle: { color: colors.onSurface, fontSize: 16, fontWeight: "800" },
  card: {
    backgroundColor: colors.surface, borderRadius: 12, padding: 14,
    borderWidth: 1, borderColor: colors.border, gap: 8,
  },
  cardTitle: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface },
  firmSelect: {
    padding: 10, borderRadius: 8, borderColor: colors.border, borderWidth: 1,
    fontSize: 14, width: "100%", maxWidth: 420,
    backgroundColor: colors.surface, color: colors.onSurface,
  },
  fChip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 16,
    paddingHorizontal: 12, paddingVertical: 7,
  },
  fChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  fChipTxt: { fontSize: 12.5, color: colors.onSurface, fontWeight: "600" },
  masterToggle: {
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingVertical: 10, paddingHorizontal: 12,
  },
  masterToggleTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  togRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 3 },
  togTxt: { fontSize: 13, color: colors.onSurface },
  expChip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 14,
    paddingHorizontal: 10, paddingVertical: 5,
  },
  expChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  expChipTxt: { fontSize: 12, color: colors.onSurface, fontWeight: "600" },
  hint: { fontSize: 12, color: colors.onSurfaceTertiary, lineHeight: 17 },
  msgBar: {
    backgroundColor: "#ECFDF5", borderRadius: 8, padding: 10,
    borderWidth: 1, borderColor: "#A7F3D0",
  },
  msgTxt: { color: "#065F46", fontSize: 12.5, fontWeight: "600" },
  empCard: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 10,
    padding: 12, gap: 8, backgroundColor: colors.surfaceSecondary,
  },
  empPhoto: { width: 56, height: 56, borderRadius: 10 },
  empPhotoEmpty: {
    backgroundColor: "#F1F5F9", alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: colors.border,
  },
  empName: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  empSub: { fontSize: 12, color: colors.onSurfaceSecondary },
  chip: { borderRadius: 10, paddingHorizontal: 8, paddingVertical: 3, alignSelf: "flex-start" },
  chipTxt: { fontSize: 10, fontWeight: "800" },
  docRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  docFlag: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderRadius: 10, paddingHorizontal: 8, paddingVertical: 3,
  },
  docFlagTxt: { fontSize: 11, fontWeight: "700" },
  prevRemark: { fontSize: 11.5, color: colors.onSurfaceTertiary, fontStyle: "italic" },
  remarksInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  btnRow: { flexDirection: "row", gap: 8 },
  actBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderRadius: 8, paddingHorizontal: 14, paddingVertical: 9,
  },
  actBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
});
