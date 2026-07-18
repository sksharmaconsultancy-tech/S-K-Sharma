/**
 * Statutory Registration — FULL-PAGE portal-style form.
 *
 * Looks and flows like the actual ESIC "Register New IP" (Form-1) / EPFO
 * member registration (Form-11) screens: sectioned form with Insured
 * Person details, identifiers, employment & wages, address, dispensary,
 * family particulars grid and nominee. One primary action — "Register on
 * Portal Now" — which saves everything and queues the RPA in a single
 * click, then shows the LIVE portal view while the registration runs.
 *
 * Route: /statutory-registration-form?portal=esic|uan&user_id=...
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import LiveRunViewer from "@/src/components/LiveRunViewer";
import { colors, radius } from "@/src/theme";

type Fam = { name: string; relation: string; dob?: string; residing?: boolean };

const FIELD_SECTIONS: {
  title: string; icon: string;
  fields: { key: string; label: string; ph?: string; multiline?: boolean; num?: boolean }[];
}[] = [
  {
    title: "Step 1 — Aadhaar & Mobile Verification", icon: "finger-print-outline",
    fields: [
      { key: "aadhaar_no", label: "Aadhaar Number (12 digits) — used for UIDAI authentication", num: true },
      { key: "phone", label: "Mobile Number (verified on the portal)", num: true },
    ],
  },
  {
    title: "Step 2 — Employee Details (auto-verified from UIDAI on the portal)", icon: "person-outline",
    fields: [
      { key: "name", label: "Full Name (as per Aadhaar)" },
      { key: "father_name", label: "Father's / Husband's Name" },
      { key: "mother_name", label: "Mother's Name" },
      { key: "dob", label: "Date of Birth", ph: "YYYY-MM-DD" },
      { key: "gender", label: "Gender", ph: "male / female" },
      { key: "marital_status", label: "Marital Status", ph: "single / married" },
      { key: "pan_no", label: "PAN (optional)", ph: "AAAAA9999A" },
      { key: "email", label: "Email (optional)" },
    ],
  },
  {
    title: "Step 3 — Employment Details & Wages", icon: "briefcase-outline",
    fields: [
      { key: "employee_code", label: "Employee Code" },
      { key: "doj", label: "Date of Appointment", ph: "YYYY-MM-DD" },
      { key: "salary_monthly", label: "Monthly Wages (Gross ₹)", num: true },
      { key: "designation", label: "Designation" },
      { key: "department", label: "Department" },
    ],
  },
  {
    title: "Step 4 — Present Address", icon: "location-outline",
    fields: [
      { key: "present_address", label: "Address (house, street, city, district, state, PIN)", multiline: true },
    ],
  },
];

const ESIC_FLOW = [
  "Eligibility", "Aadhaar Auth (OTP)", "UIDAI Details", "Mobile Verify",
  "Employment", "Dispensary", "Family", "IP No. + e-Pehchan",
];
const UAN_FLOW = [
  "Eligibility", "Aadhaar Verify", "Member Details", "Employment",
  "UAN Generated", "Member ID",
];

function toast(msg: string) {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert("Registration", msg);
}

export default function StatutoryRegistrationForm() {
  const params = useLocalSearchParams<{ portal?: string; user_id?: string }>();
  const portal = (params.portal === "uan" ? "uan" : "esic") as "esic" | "uan";
  const userId = params.user_id || "";
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();

  const [loading, setLoading] = useState(true);
  const [emp, setEmp] = useState<any>(null);
  const [snap, setSnap] = useState<Record<string, any>>({});
  const [validation, setValidation] = useState<any>(null);
  const [duplicate, setDuplicate] = useState<any>(null);
  const [reg, setReg] = useState<any>(null);
  const [fam, setFam] = useState<Fam[]>([]);
  const [nomineeName, setNomineeName] = useState("");
  const [nomineeRel, setNomineeRel] = useState("");
  const [dispensary, setDispensary] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [liveJobId, setLiveJobId] = useState<string | null>(null);
  const [linkVal, setLinkVal] = useState("");

  const label = portal === "esic" ? "ESIC IP" : "PF UAN";

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const r = await api<any>(`/admin/statutory/${portal}/employee/${userId}/prefill`);
      setEmp(r.employee);
      setSnap(r.snapshot || {});
      setValidation(r.validation);
      setDuplicate(r.duplicate);
      setReg(r.registration);
      setFam(r.registration?.family_members || []);
      setNomineeName(r.registration?.nominee?.name || "");
      setNomineeRel(r.registration?.nominee?.relation || "");
      setDispensary(r.registration?.dispensary || "");
      if (r.registration?.rpa_job_id &&
        ["queued", "submitted"].includes(r.registration.status)) {
        setLiveJobId(r.registration.rpa_job_id);
      }
    } catch (e: any) { toast(e?.message || "Failed to load employee"); }
    finally { setLoading(false); }
  }, [portal, userId]);
  useEffect(() => { load(); }, [load]);

  const buildBody = () => ({
    overrides: snap,
    family_members: fam.filter((f) => f.name.trim()),
    nominee: nomineeName.trim() ? { name: nomineeName.trim(), relation: nomineeRel.trim() } : {},
    dispensary,
  });

  const saveDraft = async (silent = false): Promise<string | null> => {
    try {
      if (reg && ["draft", "failed", "action_required", "existing_found", "rejected"].includes(reg.status)) {
        const r = await api<any>(`/admin/statutory/registrations/${reg.reg_id}`, {
          method: "PUT", body: buildBody(),
        });
        setReg(r.registration);
        setValidation(r.registration.validation);
        if (!silent) toast("Details saved.");
        return r.registration.reg_id;
      }
      if (!reg) {
        const r = await api<any>(`/admin/statutory/${portal}/registrations`, {
          method: "POST", body: { employee_user_id: userId, ...buildBody() },
        });
        setReg(r.registration);
        setValidation(r.registration.validation);
        if (!silent) toast("Details saved.");
        return r.registration.reg_id;
      }
      return reg.reg_id;
    } catch (e: any) { toast(e?.message || "Save failed"); return null; }
  };

  const registerNow = async () => {
    if (busy) return;
    setBusy("register");
    try {
      const regId = await saveDraft(true);
      if (!regId) return;
      const r = await api<any>(`/admin/statutory/registrations/${regId}/submit`,
        { method: "POST", body: {} });
      toast(r.message || "Registration queued.");
      const d = await api<any>(`/admin/statutory/registrations/${regId}`);
      setReg(d.registration);
      if (d.registration?.rpa_job_id) setLiveJobId(d.registration.rpa_job_id);
    } catch (e: any) { toast(e?.message || "Registration failed"); }
    finally { setBusy(null); }
  };

  const linkExisting = async () => {
    if (busy || !linkVal.trim()) return;
    setBusy("link");
    try {
      const regId = await saveDraft(true);
      if (!regId) return;
      await api<any>(`/admin/statutory/registrations/${regId}/link-existing`,
        { method: "POST", body: { value: linkVal.trim() } });
      toast(`Existing ${label} linked — saved to the Employee Master.`);
      await load();
    } catch (e: any) { toast(e?.message || "Link failed"); }
    finally { setBusy(null); }
  };

  if (authLoading) return null;
  const role = user?.role as string;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }
  const isStaff = !!(user as any)?.is_company_staff;
  const staffPerms: string[] = ((user as any)?.staff_permissions || []) as string[];
  if (isStaff && !staffPerms.some((p) => p.startsWith("registrations:"))) {
    return <Redirect href="/portal-dashboard" />;
  }

  const editable = !reg || ["draft", "failed", "action_required", "existing_found", "rejected"].includes(reg?.status);
  const done = reg && ["generated", "linked_existing"].includes(reg.status);

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={st.scroll}>
        {/* Header */}
        <View style={st.header}>
          <Pressable onPress={() => router.back()} style={st.backBtn} testID="btn-back">
            <Ionicons name="arrow-back" size={18} color={colors.textPrimary} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={st.title}>
              {portal === "esic" ? "ESIC — Register New Insured Person (Form-1)"
                : "EPFO — New Member Registration (Form-11)"}
            </Text>
            <Text style={st.subtitle}>
              {emp ? `${emp.name}${emp.employee_code ? ` · #${emp.employee_code}` : ""} · ${emp.company_name}` : "…"}
            </Text>
          </View>
          {reg ? (
            <View style={[st.statusChip, done && { backgroundColor: "#05966915" }]}>
              <Text style={[st.statusTxt, done && { color: "#059669" }]}>
                {String(reg.status).replace(/_/g, " ").toUpperCase()}
              </Text>
            </View>
          ) : null}
        </View>

        {loading ? (
          <View style={{ padding: 60, alignItems: "center" }}>
            <ActivityIndicator size="large" color={colors.brandPrimary} />
          </View>
        ) : (
          <>
            {/* Portal flow strip — mirrors the actual govt-portal journey */}
            <ScrollView horizontal showsHorizontalScrollIndicator={false}
              contentContainerStyle={st.flowStrip}>
              {(portal === "esic" ? ESIC_FLOW : UAN_FLOW).map((f, i, arr) => (
                <View key={f} style={{ flexDirection: "row", alignItems: "center" }}>
                  <View style={st.flowChip}>
                    <Text style={st.flowChipTxt}>{f}</Text>
                  </View>
                  {i < arr.length - 1 && (
                    <Ionicons name="chevron-forward" size={13} color={colors.textSecondary} />
                  )}
                </View>
              ))}
            </ScrollView>
          <View style={st.columns}>
            {/* ---------------- Left: portal-style form ---------------- */}
            <View style={st.formCol}>
              {done && (
                <View style={st.doneBanner}>
                  <Ionicons name="checkmark-circle" size={18} color="#059669" />
                  <Text style={st.doneTxt}>
                    {label} {reg.value} is on the Employee Master. Nothing more to do.
                  </Text>
                </View>
              )}
              {duplicate && !done && (
                <View style={st.dupBanner}>
                  <Ionicons name="warning" size={15} color="#CA8A04" />
                  <Text style={st.dupTxt}>{duplicate.note}</Text>
                </View>
              )}

              {FIELD_SECTIONS.map((sec) => (
                <View key={sec.title} style={st.card}>
                  <View style={st.cardHead}>
                    <Ionicons name={sec.icon as any} size={15} color={colors.brandPrimary} />
                    <Text style={st.cardTitle}>{sec.title}</Text>
                  </View>
                  <View style={st.fieldGrid}>
                    {sec.fields.map((f) => (
                      <View key={f.key} style={st.field}>
                        <Text style={st.fieldLabel}>{f.label}</Text>
                        <TextInput
                          style={[st.input, f.multiline && { minHeight: 64, textAlignVertical: "top" }]}
                          value={String(snap[f.key] ?? "")}
                          editable={editable}
                          multiline={!!f.multiline}
                          keyboardType={f.num ? "number-pad" : "default"}
                          placeholder={f.ph || ""}
                          placeholderTextColor={colors.textSecondary}
                          onChangeText={(v) => setSnap((s) => ({ ...s, [f.key]: v }))}
                          testID={`field-${f.key}`}
                        />
                      </View>
                    ))}
                  </View>
                </View>
              ))}

              {portal === "esic" && (
                <View style={st.card}>
                  <View style={st.cardHead}>
                    <Ionicons name="medkit-outline" size={15} color={colors.brandPrimary} />
                    <Text style={st.cardTitle}>Dispensary & Family Particulars</Text>
                  </View>
                  <View style={st.field}>
                    <Text style={st.fieldLabel}>Dispensary / IMP</Text>
                    <TextInput style={st.input} value={dispensary} editable={editable}
                      placeholder="e.g. Bhilwara ESI Dispensary"
                      placeholderTextColor={colors.textSecondary}
                      onChangeText={setDispensary} testID="field-dispensary" />
                  </View>
                  <Text style={[st.fieldLabel, { marginTop: 10 }]}>
                    Family members (for ESIC medical benefit)
                  </Text>
                  {fam.map((m, idx) => (
                    <View key={idx} style={st.famRow}>
                      <TextInput style={[st.input, { flex: 2 }]} placeholder="Name" value={m.name}
                        editable={editable} placeholderTextColor={colors.textSecondary}
                        onChangeText={(v) => { const n = [...fam]; n[idx] = { ...m, name: v }; setFam(n); }} />
                      <TextInput style={[st.input, { flex: 1.2 }]} placeholder="Relation" value={m.relation}
                        editable={editable} placeholderTextColor={colors.textSecondary}
                        onChangeText={(v) => { const n = [...fam]; n[idx] = { ...m, relation: v }; setFam(n); }} />
                      <TextInput style={[st.input, { flex: 1.2 }]} placeholder="DOB" value={m.dob || ""}
                        editable={editable} placeholderTextColor={colors.textSecondary}
                        onChangeText={(v) => { const n = [...fam]; n[idx] = { ...m, dob: v }; setFam(n); }} />
                      {editable && (
                        <Pressable onPress={() => setFam(fam.filter((_, i) => i !== idx))}>
                          <Ionicons name="trash-outline" size={16} color="#DC2626" />
                        </Pressable>
                      )}
                    </View>
                  ))}
                  {editable && (
                    <Pressable style={st.addBtn}
                      onPress={() => setFam([...fam, { name: "", relation: "", residing: true }])}
                      testID="btn-add-family-member">
                      <Ionicons name="add" size={14} color={colors.brandPrimary} />
                      <Text style={st.addBtnTxt}>Add family member</Text>
                    </Pressable>
                  )}
                </View>
              )}

              <View style={st.card}>
                <View style={st.cardHead}>
                  <Ionicons name="people-circle-outline" size={15} color={colors.brandPrimary} />
                  <Text style={st.cardTitle}>Nominee</Text>
                </View>
                <View style={st.fieldGrid}>
                  <View style={st.field}>
                    <Text style={st.fieldLabel}>Nominee Name</Text>
                    <TextInput style={st.input} value={nomineeName} editable={editable}
                      placeholderTextColor={colors.textSecondary}
                      onChangeText={setNomineeName} testID="field-nominee-name" />
                  </View>
                  <View style={st.field}>
                    <Text style={st.fieldLabel}>Relation</Text>
                    <TextInput style={st.input} value={nomineeRel} editable={editable}
                      placeholderTextColor={colors.textSecondary}
                      onChangeText={setNomineeRel} />
                  </View>
                </View>
              </View>
            </View>

            {/* ---------------- Right: actions + live view ---------------- */}
            <View style={st.sideCol}>
              {liveJobId ? (
                <LiveRunViewer jobId={liveJobId} onDone={() => load()} />
              ) : null}

              {!done && (
                <View style={st.card}>
                  <Text style={st.cardTitle}>Actions</Text>
                  <Pressable
                    style={[st.bigBtn, (busy || (reg && !editable && reg.status !== "pending_approval")) && { opacity: 0.6 }]}
                    onPress={registerNow}
                    disabled={!!busy || (reg && !editable)}
                    testID="btn-register-now">
                    {busy === "register" ? <ActivityIndicator color="#fff" /> : (
                      <>
                        <Ionicons name="rocket" size={16} color="#fff" />
                        <Text style={st.bigBtnTxt}>Register on Portal Now</Text>
                      </>
                    )}
                  </Pressable>
                  <Text style={st.hint}>
                    Saves everything and runs the registration on the{" "}
                    {portal === "esic" ? "ESIC" : "EPFO"} portal in one click.
                    Watch it live above once it starts.
                  </Text>
                  {editable && (
                    <Pressable style={[st.smallBtn]} onPress={() => saveDraft()} disabled={!!busy}
                      testID="btn-save-draft">
                      <Text style={st.smallBtnTxt}>Save details only</Text>
                    </Pressable>
                  )}
                  <View style={st.divider} />
                  <Text style={st.fieldLabel}>Already have {portal === "uan" ? "a UAN" : "an IP number"}? Link it:</Text>
                  <View style={{ flexDirection: "row", gap: 6 }}>
                    <TextInput style={[st.input, { flex: 1 }]}
                      placeholder={portal === "uan" ? "12-digit UAN" : "10–17 digit Insurance No."}
                      placeholderTextColor={colors.textSecondary}
                      keyboardType="number-pad" value={linkVal} onChangeText={setLinkVal}
                      testID="field-link-existing" />
                    <Pressable style={[st.smallBtn, { backgroundColor: "#0891B2" }]}
                      onPress={linkExisting} disabled={!!busy || !linkVal.trim()}
                      testID="btn-link-existing-form">
                      {busy === "link" ? <ActivityIndicator color="#fff" size="small" /> :
                        <Text style={[st.smallBtnTxt, { color: "#fff" }]}>Link</Text>}
                    </Pressable>
                  </View>
                </View>
              )}

              {/* Validation checklist */}
              {validation && (
                <View style={st.card}>
                  <Text style={st.cardTitle}>Pre-registration checks</Text>
                  {(validation.issues || []).map((i: string, idx: number) => (
                    <Text key={`i${idx}`} style={[st.checkTxt, { color: "#DC2626" }]}>✕ {i}</Text>
                  ))}
                  {(validation.warnings || []).map((w: string, idx: number) => (
                    <Text key={`w${idx}`} style={[st.checkTxt, { color: "#D97706" }]}>! {w}</Text>
                  ))}
                  {(validation.issues || []).length === 0 && (
                    <Text style={[st.checkTxt, { color: "#059669" }]}>✓ All mandatory checks passed</Text>
                  )}
                  <Text style={[st.checkTxt, { color: colors.textSecondary }]}>
                    {validation.eligibility_note}
                  </Text>
                </View>
              )}
            </View>
          </View>
          </>
        )}
        <View style={{ height: 60 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: 16 },
  header: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 14 },
  backBtn: {
    width: 36, height: 36, borderRadius: 10, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
  },
  title: { fontSize: 17, fontWeight: "800", color: colors.textPrimary },
  subtitle: { fontSize: 12, color: colors.textSecondary, marginTop: 2 },
  statusChip: {
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, backgroundColor: "#2563EB15",
  },
  statusTxt: { fontSize: 10.5, fontWeight: "900", color: "#2563EB" },

  columns: { flexDirection: "row", flexWrap: "wrap", gap: 14 },
  flowStrip: { alignItems: "center", paddingBottom: 12, gap: 2 },
  flowChip: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999,
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
  },
  flowChipTxt: { fontSize: 10.5, fontWeight: "700", color: colors.textSecondary },
  formCol: { flex: 1.6, minWidth: 340, gap: 12 },
  sideCol: { flex: 1, minWidth: 320, gap: 12 },

  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, padding: 14, gap: 8,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 7 },
  cardTitle: { fontSize: 13, fontWeight: "800", color: colors.textPrimary },
  fieldGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  field: { minWidth: 200, flex: 1, gap: 4 },
  fieldLabel: { fontSize: 11, fontWeight: "700", color: colors.textSecondary },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 9,
    paddingHorizontal: 10, paddingVertical: Platform.OS === "web" ? 9 : 7,
    fontSize: 13, color: colors.textPrimary, backgroundColor: colors.surface,
  },
  famRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6 },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start",
    paddingHorizontal: 10, paddingVertical: 7, borderRadius: 8, marginTop: 6,
    borderWidth: 1, borderColor: colors.brandPrimary,
  },
  addBtnTxt: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },

  doneBanner: {
    flexDirection: "row", alignItems: "center", gap: 8, padding: 12,
    borderRadius: radius.lg, backgroundColor: "#ECFDF5", borderWidth: 1, borderColor: "#A7F3D0",
  },
  doneTxt: { fontSize: 12.5, fontWeight: "700", color: "#065F46", flex: 1 },
  dupBanner: {
    flexDirection: "row", alignItems: "center", gap: 8, padding: 12,
    borderRadius: radius.lg, backgroundColor: "#FEFCE8", borderWidth: 1, borderColor: "#FDE68A",
  },
  dupTxt: { fontSize: 12, color: "#854D0E", flex: 1 },

  bigBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brandPrimary, borderRadius: 10, paddingVertical: 13,
  },
  bigBtnTxt: { color: "#fff", fontSize: 14, fontWeight: "900" },
  hint: { fontSize: 10.5, color: colors.textSecondary, lineHeight: 15 },
  smallBtn: {
    alignItems: "center", justifyContent: "center", borderRadius: 9,
    paddingVertical: 10, paddingHorizontal: 12, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  smallBtnTxt: { fontSize: 12, fontWeight: "800", color: colors.textPrimary },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 6 },
  checkTxt: { fontSize: 11.5, lineHeight: 17 },
});
