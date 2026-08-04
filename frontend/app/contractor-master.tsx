/**
 * Contractor Master — Iter 479 (CLRA / Labour Code Phase 1, user spec).
 *
 * Full statutory contractor records: licence (no./issue/expiry), PAN,
 * GSTIN, EPF/ESIC codes, security deposit, max labour permitted,
 * agreement window and status — with live active-labour counts and
 * licence/agreement expiry warnings. Names typed earlier in the Firm
 * Master contractor list are auto-imported.
 *
 * Backend: GET/POST /admin/contractors · PUT/DELETE /admin/contractors/{id}
 * Register export lives in Report Hub → CLRA / Labour Code.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, TextInput,
  ActivityIndicator, Platform, Alert, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import FirmDropdown from "@/src/components/FirmDropdown";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing } from "@/src/theme";

const alertUser = (title: string, msg: string) => {
  if (Platform.OS === "web") window.alert(`${title}\n\n${msg}`);
  else Alert.alert(title, msg);
};

const EMPTY = {
  name: "", code: "", address: "", mobile: "", email: "", pan: "",
  gstin: "", epf_code: "", esic_code: "", licence_no: "",
  licence_issue_date: "", licence_expiry_date: "", security_deposit: "",
  max_labour: "", nature_of_work: "", agreement_no: "",
  agreement_start: "", agreement_end: "", status: "active",
};

const FIELD_DEFS: [keyof typeof EMPTY, string, string?][] = [
  ["name", "Contractor Name *"],
  ["code", "Contractor Code"],
  ["address", "Address"],
  ["mobile", "Mobile"],
  ["email", "Email"],
  ["pan", "PAN"],
  ["gstin", "GSTIN"],
  ["epf_code", "EPF Code"],
  ["esic_code", "ESIC Code"],
  ["licence_no", "Labour Licence No."],
  ["licence_issue_date", "Licence Issue Date", "YYYY-MM-DD"],
  ["licence_expiry_date", "Licence Expiry Date", "YYYY-MM-DD"],
  ["security_deposit", "Security Deposit (₹)"],
  ["max_labour", "Maximum Labour Permitted"],
  ["nature_of_work", "Nature of Work"],
  ["agreement_no", "Agreement No."],
  ["agreement_start", "Agreement Start", "YYYY-MM-DD"],
  ["agreement_end", "Agreement End", "YYYY-MM-DD"],
];

export default function ContractorMasterScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId, companies } = useSelectedCompany();
  const isSuper = ["super_admin", "sub_admin"].includes(user?.role || "");
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<any | null>(null); // null=closed
  const [form, setForm] = useState<any>({ ...EMPTY });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (user?.role === "company_admin") setCompanyId(user.company_id || null);
    else if (!companyId && selectedCompanyId) setCompanyId(selectedCompanyId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, selectedCompanyId]);

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      const d = await api<any>(`/admin/contractors?company_id=${companyId}`);
      setRows(d.contractors || []);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [companyId]);
  useEffect(() => { void load(); }, [load]);

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role))
    return <Redirect href="/" />;

  const openAdd = () => { setForm({ ...EMPTY }); setErr(""); setEditing({}); };
  const openEdit = (c: any) => {
    const f: any = { ...EMPTY };
    Object.keys(EMPTY).forEach((k) => { f[k] = String((c as any)[k] ?? ""); });
    setForm(f); setErr(""); setEditing(c);
  };

  const save = async () => {
    if (!form.name.trim()) { setErr("Contractor name is required"); return; }
    setSaving(true); setErr("");
    try {
      const body = { ...form, company_id: companyId };
      if (editing?.contractor_id) {
        await api(`/admin/contractors/${editing.contractor_id}`, { method: "PUT", body });
      } else {
        await api("/admin/contractors", { method: "POST", body });
      }
      setEditing(null);
      await load();
    } catch (e: any) {
      setErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (c: any) => {
    const ok = Platform.OS === "web"
      ? window.confirm(`Delete contractor "${c.name}"? Employees keep their contractor name.`)
      : true;
    if (!ok) return;
    try {
      await api(`/admin/contractors/${c.contractor_id}?company_id=${companyId}`, { method: "DELETE" });
      await load();
    } catch (e: any) {
      alertUser("Delete failed", e?.message || "Try again");
    }
  };

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={st.headerTitle}>Contractor Master</Text>
        <Pressable onPress={openAdd} style={st.addBtn} testID="ctr-add">
          <Ionicons name="add" size={16} color="#FFF" />
          <Text style={st.addTxt}>Add Contractor</Text>
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 60 }}>
        {isSuper ? (
          <View style={{ marginBottom: 12, maxWidth: 420 }}>
            <Text style={st.lbl}>Firm</Text>
            <FirmDropdown
              value={companyId}
              onChange={(cid) => setCompanyId(cid)}
              options={companies.map((c) => ({ company_id: c.company_id, name: c.name }))}
            />
          </View>
        ) : null}
        <Pressable
          onPress={() => router.push("/reports-center")}
          style={st.linkRow}
        >
          <Ionicons name="document-text-outline" size={14} color={colors.brandPrimary} />
          <Text style={st.linkTxt}>
            Contractor Register (PDF / Excel / Email) — Report Hub → CLRA / Labour Code
          </Text>
        </Pressable>
        {loading ? <ActivityIndicator style={{ marginTop: 30 }} /> : null}
        {!loading && !rows.length ? (
          <Text style={st.empty}>
            No contractors yet — tap “Add Contractor”. Names already typed in
            the Firm Master contractor list are imported automatically.
          </Text>
        ) : null}
        {rows.map((c) => (
          <View key={c.contractor_id} style={st.card}>
            <View style={{ flex: 1, minWidth: 220 }}>
              <Text style={st.cName}>
                {c.name}{c.code ? `  ·  ${c.code}` : ""}
              </Text>
              <Text style={st.cMeta}>
                Licence: {c.licence_no || "—"}
                {c.licence_expiry_date ? `  (exp ${c.licence_expiry_date})` : ""}
                {"   "}Agreement: {c.agreement_no || "—"}
                {c.agreement_end ? `  (to ${c.agreement_end})` : ""}
              </Text>
              <Text style={st.cMeta}>
                Labour: {c.current_active_labour}/{c.max_labour || "—"}
                {"   "}Deposit: ₹{c.security_deposit || 0}
                {"   "}EPF: {c.epf_code || "—"}  ESIC: {c.esic_code || "—"}
              </Text>
              <View style={{ flexDirection: "row", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                <Text style={[st.pill, { backgroundColor: "#DCFCE7", color: "#166534" }]}>
                  {String(c.status || "active").toUpperCase()}
                </Text>
                {c.licence_expired ? (
                  <Text style={[st.pill, { backgroundColor: "#FEE2E2", color: "#B91C1C" }]}>LICENCE EXPIRED</Text>
                ) : c.licence_expiring_soon ? (
                  <Text style={[st.pill, { backgroundColor: "#FEF3C7", color: "#92400E" }]}>LICENCE EXPIRING SOON</Text>
                ) : null}
                {c.agreement_expired ? (
                  <Text style={[st.pill, { backgroundColor: "#FEE2E2", color: "#B91C1C" }]}>AGREEMENT EXPIRED</Text>
                ) : c.agreement_expiring_soon ? (
                  <Text style={[st.pill, { backgroundColor: "#FEF3C7", color: "#92400E" }]}>AGREEMENT EXPIRING SOON</Text>
                ) : null}
              </View>
            </View>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <Pressable onPress={() => openEdit(c)} style={st.iconBtn} testID={`ctr-edit-${c.contractor_id}`}>
                <Ionicons name="create-outline" size={17} color={colors.brandPrimary} />
              </Pressable>
              <Pressable onPress={() => remove(c)} style={st.iconBtn}>
                <Ionicons name="trash-outline" size={17} color="#DC2626" />
              </Pressable>
            </View>
          </View>
        ))}
      </ScrollView>

      <Modal visible={!!editing} transparent animationType="fade" onRequestClose={() => setEditing(null)}>
        <View style={st.modalBg}>
          <View style={st.modalCard}>
            <Text style={st.modalTitle}>
              {editing?.contractor_id ? "Edit Contractor" : "Add Contractor"}
            </Text>
            <ScrollView style={{ maxHeight: 460 }}>
              <View style={st.formGrid}>
                {FIELD_DEFS.map(([k, label, ph]) => (
                  <View key={k} style={st.formCell}>
                    <Text style={st.lbl}>{label}</Text>
                    <TextInput
                      value={String(form[k] ?? "")}
                      onChangeText={(v) => setForm((f: any) => ({ ...f, [k]: v }))}
                      placeholder={ph || ""}
                      placeholderTextColor={colors.onSurfaceTertiary}
                      style={st.input}
                      testID={`ctr-f-${k}`}
                    />
                  </View>
                ))}
                <View style={st.formCell}>
                  <Text style={st.lbl}>Status</Text>
                  <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
                    {["active", "inactive", "blacklisted"].map((s) => (
                      <Pressable
                        key={s}
                        onPress={() => setForm((f: any) => ({ ...f, status: s }))}
                        style={[st.chip, form.status === s && st.chipOn]}
                      >
                        <Text style={[st.chipTxt, form.status === s && { color: "#FFF" }]}>
                          {s.toUpperCase()}
                        </Text>
                      </Pressable>
                    ))}
                  </View>
                </View>
              </View>
            </ScrollView>
            {err ? <Text style={{ color: "#DC2626", fontSize: 12, fontWeight: "700" }}>{err}</Text> : null}
            <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 8, marginTop: 10 }}>
              <Pressable onPress={() => setEditing(null)} style={st.cancelBtn}>
                <Text style={{ fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary }}>Cancel</Text>
              </Pressable>
              <Pressable onPress={save} disabled={saving} style={[st.saveBtn, saving && { opacity: 0.6 }]} testID="ctr-save">
                {saving ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="save-outline" size={14} color="#FFF" />}
                <Text style={{ color: "#FFF", fontSize: 13, fontWeight: "800" }}>Save</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingHorizontal: spacing.md, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  headerTitle: { flex: 1, fontSize: 17, fontWeight: "800", color: colors.onSurface },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 8,
  },
  addTxt: { color: "#FFF", fontSize: 12.5, fontWeight: "800" },
  lbl: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  linkRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 12 },
  linkTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  empty: { marginTop: 30, textAlign: "center", fontSize: 13, color: colors.onSurfaceTertiary, lineHeight: 20 },
  card: {
    flexDirection: "row", alignItems: "flex-start", gap: 10, flexWrap: "wrap",
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, padding: 14, marginBottom: 10,
  },
  cName: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface },
  cMeta: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 3 },
  pill: { fontSize: 10, fontWeight: "800", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, overflow: "hidden" },
  iconBtn: { padding: 8, borderRadius: 8, borderWidth: 1, borderColor: colors.border },
  modalBg: { flex: 1, backgroundColor: "rgba(15,23,42,0.55)", justifyContent: "center", alignItems: "center", padding: 14 },
  modalCard: { width: "100%", maxWidth: 720, backgroundColor: colors.surface, borderRadius: 14, padding: 18 },
  modalTitle: { fontSize: 15.5, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  formGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  formCell: { width: "48%", minWidth: 220, flexGrow: 1 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 9, fontSize: 13, color: colors.onSurface,
  },
  chip: { borderWidth: 1, borderColor: colors.border, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7 },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceSecondary },
  cancelBtn: { paddingVertical: 10, paddingHorizontal: 14, borderRadius: 8, borderWidth: 1, borderColor: colors.border },
  saveBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingVertical: 10, paddingHorizontal: 16,
  },
});
