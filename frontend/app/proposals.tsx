/**
 * Sales → Proposal Management (MVP).
 * Dashboard counts + proposal list + create form + PDF/Word export.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  TextInput,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { api, apiBinary } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

type Proposal = {
  proposal_id: string;
  number: string;
  status: string;
  client: any;
  pricing: any;
  proposal_date: string;
};
type ListResp = {
  proposals: Proposal[];
  counts: Record<string, number>;
  total: number;
  total_value: number;
};

const PROPOSAL_TYPES = [
  "Payroll Outsourcing", "Labour Law Compliance", "EPF Compliance",
  "ESIC Compliance", "Payroll Software", "HRMS", "Attendance System",
  "Contractor Management", "Compliance Audit", "HR Consultancy",
  "Recruitment Services", "Complete HR & Compliance Solution",
];

const SERVICE_GROUPS: { title: string; items: [string, string][] }[] = [
  { title: "Payroll", items: [
    ["salary_processing", "Salary Processing"], ["salary_slip", "Salary Slip"],
    ["salary_register", "Salary Register"], ["bank_advice", "Bank Advice"],
    ["bonus", "Bonus"], ["gratuity", "Gratuity"], ["ff_settlement", "F&F Settlement"],
    ["reimbursement", "Reimbursement"], ["loan_management", "Loan Management"]] },
  { title: "Compliance", items: [
    ["epf", "EPF"], ["esic", "ESIC"], ["pt", "PT"], ["lwf", "LWF"],
    ["labour_licence", "Labour Licence"], ["factory_compliance", "Factory Compliance"],
    ["clra", "CLRA"], ["bocw", "BOCW"], ["minimum_wages", "Minimum Wages"],
    ["register_maintenance", "Register Maintenance"]] },
  { title: "HR", items: [
    ["employee_master", "Employee Master"], ["leave_management", "Leave Management"],
    ["attendance", "Attendance"], ["shift_management", "Shift Management"],
    ["performance_management", "Performance Mgmt"], ["asset_management", "Asset Mgmt"]] },
  { title: "Technology", items: [
    ["employee_app", "Employee App"], ["employer_portal", "Employer Portal"],
    ["offline_pwa", "Offline PWA"], ["face_attendance", "Face Attendance"],
    ["qr_attendance", "QR Attendance"], ["geo_fencing", "Geo-Fencing"],
    ["gps_attendance", "GPS Attendance"], ["ai_chatbot", "AI Chatbot"]] },
];

const STATUS_COLOR: Record<string, string> = {
  draft: "#64748B", pending_approval: "#D97706", sent: "#2563EB",
  viewed: "#0891B2", accepted: "#059669", rejected: "#DC2626",
  expired: "#9CA3AF", converted: "#7C3AED",
};

export default function ProposalsScreen() {
  const { user, loading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [data, setData] = useState<ListResp | null>(null);
  const [busy, setBusy] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // form state
  const [client, setClient] = useState<Record<string, string>>({});
  const [types, setTypes] = useState<string[]>([]);
  const [services, setServices] = useState<string[]>([]);
  const [price, setPrice] = useState<Record<string, string>>({ gst_pct: "18", billing_months: "12" });

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const qs = selectedCompanyId ? `?company_id=${selectedCompanyId}` : "";
      setData(await api<ListResp>(`/admin/proposals${qs}`));
    } catch (e: any) {
      setMsg(e?.message || "Failed to load.");
    } finally {
      setBusy(false);
    }
  }, [selectedCompanyId]);

  useEffect(() => { void load(); }, [load]);

  const toggle = (arr: string[], v: string, set: (x: string[]) => void) =>
    set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  const submit = useCallback(async () => {
    if (!client.company_name?.trim()) { setMsg("Enter the client company name."); return; }
    setSaving(true); setMsg(null);
    try {
      const pricing: Record<string, number> = {};
      Object.entries(price).forEach(([k, v]) => { if (v !== "") pricing[k] = Number(v) || 0; });
      await api("/admin/proposals", {
        method: "POST",
        body: { client, proposal_types: types, services, pricing,
                company_id: selectedCompanyId || undefined },
      });
      setShowForm(false); setClient({}); setTypes([]); setServices([]);
      setPrice({ gst_pct: "18", billing_months: "12" });
      await load();
      setMsg("Proposal created.");
    } catch (e: any) {
      setMsg(e?.message || "Create failed.");
    } finally {
      setSaving(false);
    }
  }, [client, types, services, price, load, selectedCompanyId]);

  const download = useCallback(async (id: string, kind: "pdf" | "doc", cid?: string) => {
    try {
      const qcid = cid || selectedCompanyId;
      const qs = qcid ? `?company_id=${encodeURIComponent(qcid)}` : "";
      const { webBlobUrl } = await apiBinary(`/admin/proposals/${id}/export.${kind}${qs}`);
      if (Platform.OS === "web" && webBlobUrl) {
        const a = document.createElement("a");
        a.href = webBlobUrl; a.download = `${id}.${kind}`; a.click();
        setTimeout(() => URL.revokeObjectURL(webBlobUrl), 30000);
      }
    } catch (e: any) { setMsg(e?.message || "Export failed."); }
  }, [selectedCompanyId]);

  const [converting, setConverting] = useState<string | null>(null);
  const convert = useCallback(async (id: string, clientName: string) => {
    setConverting(id); setMsg(null);
    try {
      const r = await api<{ ok: boolean; company_name?: string; company_code?: string; already_converted?: boolean }>(
        `/admin/proposals/${id}/convert`,
        { method: "POST", body: { company_id: selectedCompanyId || undefined } });
      setMsg(r.already_converted
        ? `"${r.company_name || clientName}" is already a customer firm.`
        : `🎉 "${r.company_name || clientName}" created as a new firm (code ${r.company_code || "—"}) with an active service agreement.`);
      await load();
    } catch (e: any) { setMsg(e?.message || "Convert failed."); }
    finally { setConverting(null); }
  }, [load, selectedCompanyId]);

  if (loading) return null;
  const role = user?.role as string;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={st.wrap}>
        <View style={st.headRow}>
          <View style={{ flex: 1 }}>
            <Text style={st.title}>Proposal Management</Text>
            <Text style={st.subtitle}>Create, track and export sales proposals.</Text>
          </View>
          <Pressable style={st.newBtn} onPress={() => setShowForm((v) => !v)} testID="new-proposal">
            <Ionicons name={showForm ? "close" : "add"} size={18} color="#fff" />
            <Text style={st.newBtnTxt}>{showForm ? "Close" : "New Proposal"}</Text>
          </Pressable>
        </View>

        {msg ? (
          <View style={st.msgBox}>
            <Ionicons name="information-circle" size={15} color="#2563EB" />
            <Text style={st.msgTxt}>{msg}</Text>
          </View>
        ) : null}

        {/* Dashboard counts */}
        {data ? (
          <View style={st.countsRow}>
            <Stat label="Total" value={data.total} color={colors.brandPrimary} />
            {Object.entries(data.counts).map(([k, v]) => (
              <Stat key={k} label={k.replace(/_/g, " ")} value={v} color={STATUS_COLOR[k] || "#64748B"} />
            ))}
            <Stat label="Pipeline ₹" value={Math.round(data.total_value).toLocaleString("en-IN")} color="#059669" />
          </View>
        ) : null}

        {/* Create form */}
        {showForm ? (
          <View style={st.card}>
            <Text style={st.section}>Client information</Text>
            <View style={st.grid2}>
              {[["company_name", "Company Name *"], ["contact_person", "Contact Person"],
                ["designation", "Designation"], ["industry", "Industry"],
                ["employee_strength", "Employee Strength"], ["branches", "Branches"],
                ["email", "Email"], ["mobile", "Mobile"], ["gst", "GST"], ["pan", "PAN"],
                ["payroll_frequency", "Payroll Frequency"], ["existing_software", "Existing Software"]]
                .map(([k, lbl]) => (
                <View key={k} style={st.gridItem}>
                  <Text style={st.fieldLbl}>{lbl}</Text>
                  <TextInput style={st.input} value={client[k] || ""}
                    onChangeText={(t) => setClient((c) => ({ ...c, [k]: t }))}
                    placeholder={lbl} placeholderTextColor={colors.textSecondary} />
                </View>
              ))}
            </View>

            <Text style={st.section}>Proposal type</Text>
            <View style={st.pillRow}>
              {PROPOSAL_TYPES.map((t) => (
                <Pressable key={t} style={[st.pill, types.includes(t) && st.pillActive]}
                  onPress={() => toggle(types, t, setTypes)}>
                  <Text style={[st.pillTxt, types.includes(t) && st.pillTxtActive]}>{t}</Text>
                </Pressable>
              ))}
            </View>

            <Text style={st.section}>Services</Text>
            {SERVICE_GROUPS.map((g) => (
              <View key={g.title} style={{ marginBottom: 6 }}>
                <Text style={st.grpTitle}>{g.title}</Text>
                <View style={st.pillRow}>
                  {g.items.map(([id, lbl]) => (
                    <Pressable key={id} style={[st.pill, services.includes(id) && st.pillActive]}
                      onPress={() => toggle(services, id, setServices)}>
                      <Text style={[st.pillTxt, services.includes(id) && st.pillTxtActive]}>{lbl}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            ))}

            <Text style={st.section}>Pricing</Text>
            <View style={st.grid2}>
              {[["one_time", "One-time Setup"], ["monthly", "Monthly Charges"],
                ["per_employee", "Per-Employee"], ["employee_count", "Employee Count"],
                ["per_branch", "Per-Branch"], ["branch_count", "Branch Count"],
                ["additional", "Additional Modules"], ["billing_months", "Billing Months"],
                ["discount_pct", "Discount %"], ["gst_pct", "GST %"]].map(([k, lbl]) => (
                <View key={k} style={st.gridItem}>
                  <Text style={st.fieldLbl}>{lbl}</Text>
                  <TextInput style={st.input} value={price[k] || ""} keyboardType="numeric"
                    onChangeText={(t) => setPrice((p) => ({ ...p, [k]: t }))}
                    placeholder="0" placeholderTextColor={colors.textSecondary} />
                </View>
              ))}
            </View>

            <Pressable style={st.saveBtn} onPress={submit} disabled={saving} testID="save-proposal">
              {saving ? <ActivityIndicator color="#fff" size="small" /> : <Ionicons name="checkmark" size={18} color="#fff" />}
              <Text style={st.newBtnTxt}>Create Proposal</Text>
            </Pressable>
          </View>
        ) : null}

        {/* List */}
        <Text style={st.section}>Proposals</Text>
        {busy ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 16 }} />
        ) : (data?.proposals || []).length === 0 ? (
          <Text style={st.empty}>No proposals yet. Tap the New Proposal button to create one.</Text>
        ) : (
          (data?.proposals || []).map((p) => (
            <View key={p.proposal_id} style={st.pRow}>
              <View style={{ flex: 1 }}>
                <Text style={st.pNum}>{p.number}</Text>
                <Text style={st.pClient}>{p.client?.company_name || "—"}</Text>
                <View style={st.pMeta}>
                  <View style={[st.badge, { backgroundColor: (STATUS_COLOR[p.status] || "#64748B") + "22" }]}>
                    <Text style={[st.badgeTxt, { color: STATUS_COLOR[p.status] || "#64748B" }]}>
                      {p.status.replace(/_/g, " ")}
                    </Text>
                  </View>
                  <Text style={st.pTotal}>₹ {Math.round(p.pricing?.grand_total || 0).toLocaleString("en-IN")}</Text>
                </View>
              </View>
              <Pressable style={st.expBtn} onPress={() => download(p.proposal_id, "pdf", (p as any).company_id)}>
                <Ionicons name="document-outline" size={15} color={colors.brandPrimary} />
                <Text style={st.expTxt}>PDF</Text>
              </Pressable>
              <Pressable style={st.expBtn} onPress={() => download(p.proposal_id, "doc", (p as any).company_id)}>
                <Ionicons name="document-text-outline" size={15} color="#2563EB" />
                <Text style={[st.expTxt, { color: "#2563EB" }]}>Word</Text>
              </Pressable>
              {p.status === "converted" ? (
                <View style={[st.expBtn, { borderColor: "#7C3AED", backgroundColor: "#F5F3FF" }]}>
                  <Ionicons name="checkmark-done-outline" size={15} color="#7C3AED" />
                  <Text style={[st.expTxt, { color: "#7C3AED" }]}>Customer</Text>
                </View>
              ) : (role === "super_admin" || role === "sub_admin") ? (
                <Pressable
                  style={[st.expBtn, { borderColor: "#059669", backgroundColor: "#ECFDF5" }]}
                  disabled={converting === p.proposal_id}
                  onPress={() => convert(p.proposal_id, p.client?.company_name || "")}
                  testID={`convert-${p.proposal_id}`}
                >
                  <Ionicons name="business-outline" size={15} color="#059669" />
                  <Text style={[st.expTxt, { color: "#059669" }]}>
                    {converting === p.proposal_id ? "Converting…" : "Convert to Customer"}
                  </Text>
                </Pressable>
              ) : null}
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function Stat({ label, value, color }: { label: string; value: any; color: string }) {
  return (
    <View style={st.stat}>
      <Text style={[st.statVal, { color }]}>{value}</Text>
      <Text style={st.statLbl}>{label}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  wrap: { padding: 20, gap: 12, maxWidth: 960, width: "100%", alignSelf: "center" },
  headRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  title: { fontSize: 22, fontWeight: "800", color: colors.textPrimary },
  subtitle: { fontSize: 13, color: colors.textSecondary },
  newBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.brandPrimary,
    borderRadius: 10, paddingVertical: 10, paddingHorizontal: 14,
  },
  newBtnTxt: { color: "#fff", fontSize: 14, fontWeight: "800" },
  msgBox: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#EFF6FF", borderRadius: 10, padding: 10 },
  msgTxt: { color: "#1D4ED8", fontSize: 12.5, flex: 1 },
  countsRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  stat: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 12, borderWidth: 1,
    borderColor: colors.border, paddingVertical: 10, paddingHorizontal: 14, minWidth: 96,
  },
  statVal: { fontSize: 18, fontWeight: "800" },
  statLbl: { fontSize: 11, color: colors.textSecondary, textTransform: "capitalize", marginTop: 2 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: 16, gap: 8,
  },
  section: { fontSize: 14, fontWeight: "800", color: colors.textPrimary, marginTop: 8 },
  grpTitle: { fontSize: 12, fontWeight: "800", color: colors.textSecondary, marginTop: 4, marginBottom: 4 },
  grid2: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  gridItem: { width: "48%", minWidth: 160, flexGrow: 1 },
  fieldLbl: { fontSize: 11.5, fontWeight: "700", color: colors.textSecondary, marginBottom: 3 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 10,
    paddingVertical: 9, fontSize: 13.5, color: colors.textPrimary, backgroundColor: colors.surface,
  },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pill: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 999, paddingVertical: 6,
    paddingHorizontal: 11, backgroundColor: colors.surface,
  },
  pillActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  pillTxt: { fontSize: 12, fontWeight: "700", color: colors.textSecondary },
  pillTxtActive: { color: "#fff" },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: "#059669", borderRadius: 10, paddingVertical: 13, marginTop: 8, minHeight: 46,
  },
  empty: { fontSize: 13, color: colors.textSecondary, fontStyle: "italic" },
  pRow: {
    flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: colors.surfaceSecondary,
    borderRadius: 12, borderWidth: 1, borderColor: colors.border, padding: 14,
  },
  pNum: { fontSize: 14, fontWeight: "800", color: colors.textPrimary },
  pClient: { fontSize: 13, color: colors.textSecondary, marginTop: 1 },
  pMeta: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 6 },
  badge: { borderRadius: 999, paddingVertical: 3, paddingHorizontal: 10 },
  badgeTxt: { fontSize: 11, fontWeight: "800", textTransform: "capitalize" },
  pTotal: { fontSize: 13, fontWeight: "700", color: colors.textPrimary },
  expBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, borderWidth: 1, borderColor: colors.border,
    borderRadius: 8, paddingVertical: 8, paddingHorizontal: 10,
  },
  expTxt: { fontSize: 12.5, fontWeight: "800", color: colors.brandPrimary },
});
