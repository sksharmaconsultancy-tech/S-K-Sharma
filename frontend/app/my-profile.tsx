/**
 * Iter 610 — ESS: My Profile (view-only + Request Change workflow).
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/api/client";
import { colors } from "@/src/theme";

const SECTIONS: [string, [string, string][]][] = [
  ["Personal", [["name", "Name"], ["father_name", "Father / Spouse"], ["mother_name", "Mother"],
    ["gender", "Gender"], ["dob", "Date of Birth"], ["mobile", "Mobile"], ["email", "Email"],
    ["address", "Address"], ["emergency_contact_name", "Emergency Contact Name"],
    ["emergency_contact", "Emergency Contact No."]]],
  ["Employment", [["employee_code", "Employee Code"], ["doj", "Date of Joining"],
    ["designation", "Designation"], ["department", "Department"], ["branch_name", "Worksite / Branch"],
    ["reporting_manager", "Reporting Manager"], ["employee_type", "Employee Type"],
    ["employment_status", "Status"]]],
  ["Bank & Statutory", [["bank_name", "Bank"], ["bank_account_no", "Account No."],
    ["bank_account_name", "Account Name"], ["ifsc", "IFSC"], ["uan_no", "UAN"],
    ["pf_no", "PF No."], ["esi_ip_no", "ESIC / IP No."]]],
];

export default function MyProfile() {
  const router = useRouter();
  const [p, setP] = useState<any>(null);
  const [modal, setModal] = useState(false);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api("/ess/profile").then((r) => setP(r.profile)).catch(() => {});
  useEffect(() => { load(); }, []);

  const submit = async () => {
    const clean = Object.fromEntries(Object.entries(fields).filter(([, v]) => v?.trim()));
    if (!Object.keys(clean).length) { setMsg("Enter at least one new value"); return; }
    setBusy(true);
    try {
      const r = await api("/ess/requests", {
        method: "POST",
        body: { type: "profile_correction", payload: { fields: clean }, reason },
      });
      setModal(false); setFields({}); setReason("");
      setMsg(`Change request ${r.request?.request_no} submitted — HR will review ✓`);
      load();
    } catch (e: any) { setMsg(String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const EDIT_LABELS: Record<string, string> = {
    mobile: "Mobile", email: "Email", address: "Address",
    emergency_contact_name: "Emergency Contact Name", emergency_contact: "Emergency Contact No.",
    bank_name: "Bank", bank_account_no: "Account No.", bank_account_name: "Account Name", ifsc: "IFSC",
  };

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="arrow-back" size={22} color={colors.onSurface} /></Pressable>
        <Text style={s.title}>My Profile</Text>
        <Pressable style={s.reqBtn} onPress={() => setModal(true)} testID="prof-request-change">
          <Ionicons name="create-outline" size={15} color="#fff" />
          <Text style={s.reqTxt}>Request Change</Text>
        </Pressable>
      </View>
      {!p ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 40 }} /> : (
        <ScrollView contentContainerStyle={s.body}>
          {msg ? <Text style={s.msg}>{msg}</Text> : null}
          {p.pending_profile_requests > 0 ? (
            <Text style={s.pend}>⏳ {p.pending_profile_requests} change request(s) awaiting HR approval</Text>
          ) : null}
          <View style={s.headCard}>
            <View style={s.avatar}><Text style={s.avatarTxt}>{(p.name || "?").slice(0, 1)}</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={s.name}>{p.name || "—"}</Text>
              <Text style={s.sub}>{p.employee_code || ""}{p.designation ? ` · ${p.designation}` : ""}</Text>
            </View>
          </View>
          {SECTIONS.map(([sec, rows]) => (
            <View key={sec} style={s.card}>
              <Text style={s.secTitle}>{sec}</Text>
              {rows.map(([k, label]) => (
                <View key={k} style={s.row}>
                  <Text style={s.lbl}>{label}</Text>
                  <Text style={s.val}>{p[k] != null && p[k] !== "" ? String(p[k]) : "Not Available"}</Text>
                </View>
              ))}
            </View>
          ))}
          <Text style={s.hint}>Employment & statutory details can only be changed by HR. For contact/bank details use “Request Change”.</Text>
          <View style={{ height: 40 }} />
        </ScrollView>
      )}
      <Modal visible={modal} transparent animationType="fade" onRequestClose={() => setModal(false)}>
        <Pressable style={s.modalBg} onPress={() => setModal(false)}>
          <Pressable style={s.modalCard} onPress={() => {}}>
            <Text style={s.modalTitle}>Request Profile Change</Text>
            <Text style={s.hint}>Fill only the fields you want changed — HR approves before anything updates.</Text>
            <ScrollView style={{ maxHeight: 340 }}>
              {Object.entries(EDIT_LABELS).map(([k, label]) => (
                <View key={k}>
                  <Text style={s.lbl}>{label}{p?.[k] ? `  (current: ${p[k]})` : ""}</Text>
                  <TextInput style={s.input} value={fields[k] || ""} placeholder="New value"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    onChangeText={(t) => setFields((f) => ({ ...f, [k]: t }))} testID={`prof-edit-${k}`} />
                </View>
              ))}
              <Text style={s.lbl}>Reason</Text>
              <TextInput style={s.input} value={reason} onChangeText={setReason}
                placeholder="Why this change?" placeholderTextColor={colors.onSurfaceTertiary} />
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <Pressable style={[s.mBtn, s.mBtnLight]} onPress={() => setModal(false)}>
                <Text style={[s.mBtnTxt, { color: colors.onSurface }]}>Cancel</Text>
              </Pressable>
              <Pressable style={[s.mBtn, { backgroundColor: colors.brandPrimary }]} disabled={busy}
                onPress={submit} testID="prof-submit-change">
                {busy ? <ActivityIndicator size="small" color="#fff" /> : <Text style={s.mBtnTxt}>Submit Request</Text>}
              </Pressable>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { flex: 1, fontSize: 17, fontWeight: "800", color: colors.onSurface },
  reqBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brandPrimary, borderRadius: 10, paddingHorizontal: 12, minHeight: 40, justifyContent: "center" },
  reqTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  body: { padding: 16 },
  msg: { color: "#059669", fontWeight: "700", fontSize: 12.5, marginBottom: 8 },
  pend: { color: "#B45309", fontWeight: "700", fontSize: 12, marginBottom: 8 },
  headCard: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: colors.surface, borderRadius: 14, padding: 14, borderWidth: 1, borderColor: colors.border, marginBottom: 10 },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  avatarTxt: { color: "#fff", fontSize: 22, fontWeight: "800" },
  name: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12.5, color: colors.onSurfaceTertiary, marginTop: 2 },
  card: { backgroundColor: colors.surface, borderRadius: 14, padding: 14, borderWidth: 1, borderColor: colors.border, marginBottom: 10 },
  secTitle: { fontSize: 11.5, fontWeight: "800", color: colors.brandPrimary, textTransform: "uppercase", marginBottom: 6 },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, gap: 12, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  lbl: { fontSize: 12.5, color: colors.onSurfaceTertiary, fontWeight: "700", marginTop: 8, marginBottom: 3 },
  val: { fontSize: 13, color: colors.onSurface, fontWeight: "600", flexShrink: 1, textAlign: "right" },
  hint: { fontSize: 11.5, color: colors.onSurfaceTertiary, lineHeight: 16, marginTop: 4 },
  input: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 9, fontSize: 13.5, color: colors.onSurface, minHeight: 42 },
  modalBg: { flex: 1, backgroundColor: "rgba(15,23,42,.5)", alignItems: "center", justifyContent: "center", padding: 20 },
  modalCard: { backgroundColor: colors.surface, borderRadius: 16, padding: 16, width: "100%", maxWidth: 430 },
  modalTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginBottom: 4 },
  mBtn: { flex: 1, borderRadius: 10, minHeight: 44, alignItems: "center", justifyContent: "center" },
  mBtnLight: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  mBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
});
