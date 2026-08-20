/**
 * Iter 624 — MULTI-BRANCH MANAGEMENT (user spec).
 * Tabs: Branches (extended fields + link existing) · Employees (Home +
 * Authorized branches) · Temp Assignments · Transfers.
 * Home Branch never auto-changes; history is effective-dated, never rewritten.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, Platform, Pressable, ScrollView, StyleSheet,
  Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";

const notify = (t: string, m: string) => {
  if (Platform.OS === "web") window.alert(`${t}\n${m}`);
  else Alert.alert(t, m);
};

type Branch = {
  branch_id: string; company_id: string; name: string; code?: string;
  address?: string; state?: string; city?: string; pin?: string;
  head_name?: string; email?: string; mobile?: string;
  office_lat?: number; office_lng?: number; geofence_radius_m?: number;
  active?: boolean; linked_company_ids?: string[];
};
type Emp = {
  user_id: string; name: string; employee_code?: string;
  home_branch_id?: string | null; authorized_branch_ids?: string[];
};

const TABS = ["Branches", "Employees", "Temp Assignments", "Transfers"] as const;

export default function BranchManagement() {
  const router = useRouter();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Branches");
  const [companies, setCompanies] = useState<any[]>([]);
  const [cid, setCid] = useState("");
  const [branches, setBranches] = useState<Branch[]>([]);
  const [emps, setEmps] = useState<Emp[]>([]);
  const [assigns, setAssigns] = useState<any[]>([]);
  const [transfers, setTransfers] = useState<any[]>([]);
  const [allBranches, setAllBranches] = useState<Branch[]>([]);
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState<Branch | null>(null);
  const [empQ, setEmpQ] = useState("");
  const [empSel, setEmpSel] = useState<Emp | null>(null);
  const [taForm, setTaForm] = useState({ user_id: "", branch_id: "", from_date: "", to_date: "", reason: "" });
  const [trForm, setTrForm] = useState({ user_id: "", new_branch_id: "", effective_date: "", reason: "" });

  useEffect(() => {
    api<{ companies: any[] }>("/companies?lite=1").then((r) => {
      setCompanies(r.companies || []);
      if (r.companies?.length && !cid) setCid(r.companies[0].company_id);
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = useCallback(async () => {
    if (!cid) return;
    setBusy(true);
    try {
      const [b, e, a, t, ab] = await Promise.all([
        api<{ branches: Branch[] }>(`/admin/branch-management/branches?company_id=${cid}`),
        api<{ employees: Emp[] }>(`/admin/branch-management/employees?company_id=${cid}`),
        api<{ assignments: any[] }>(`/admin/branch-management/temp-assignments?company_id=${cid}`),
        api<{ transfers: any[] }>(`/admin/branch-management/transfers?company_id=${cid}`),
        api<{ branches: Branch[] }>(`/company/branches?company_id=all`).catch(() => ({ branches: [] as Branch[] })),
      ]);
      setBranches(b.branches || []);
      setEmps(e.employees || []);
      setAssigns(a.assignments || []);
      setTransfers(t.transfers || []);
      setAllBranches(ab.branches || []);
    } catch (er: any) {
      notify("Error", er?.message || "Could not load");
    } finally { setBusy(false); }
  }, [cid]);
  useEffect(() => { load(); }, [load]);

  const bname = (bid?: string | null) =>
    branches.find((b) => b.branch_id === bid)?.name
    || allBranches.find((b) => b.branch_id === bid)?.name
    || (bid ? bid : "—");

  const saveBranch = async () => {
    if (!edit) return;
    try {
      await api(`/admin/branch-management/branches/${edit.branch_id}`, { method: "PATCH", body: edit });
      setEdit(null);
      notify("Saved", "Branch updated ✓");
      load();
    } catch (er: any) { notify("Error", er?.message || "Save failed"); }
  };

  const linkExisting = async (b: Branch) => {
    try {
      await api("/admin/branch-management/branches/link", { method: "POST", body: { branch_id: b.branch_id, company_id: cid } });
      notify("Linked", `${b.name} linked to this firm ✓`);
      load();
    } catch (er: any) { notify("Error", er?.message || "Link failed"); }
  };

  const saveAssign = async () => {
    if (!empSel) return;
    try {
      await api("/admin/branch-management/assign", {
        method: "POST",
        body: { user_id: empSel.user_id, home_branch_id: empSel.home_branch_id || null, authorized_branch_ids: empSel.authorized_branch_ids || [] },
      });
      setEmpSel(null);
      notify("Saved", "Branch assignment updated ✓");
      load();
    } catch (er: any) { notify("Error", er?.message || "Save failed"); }
  };

  const createTa = async () => {
    try {
      await api("/admin/branch-management/temp-assignments", { method: "POST", body: taForm });
      setTaForm({ user_id: "", branch_id: "", from_date: "", to_date: "", reason: "" });
      notify("Created", "Temporary assignment approved ✓");
      load();
    } catch (er: any) { notify("Error", er?.message || "Create failed"); }
  };

  const createTr = async () => {
    try {
      await api("/admin/branch-management/transfers", { method: "POST", body: trForm });
      setTrForm({ user_id: "", new_branch_id: "", effective_date: "", reason: "" });
      notify("Created", "Transfer recorded ✓ (applies on the effective date)");
      load();
    } catch (er: any) { notify("Error", er?.message || "Create failed"); }
  };

  const chip = (label: string, on: boolean, onPress: () => void, key?: string) => (
    <Pressable key={key || label} onPress={onPress} style={[st.chip, on && st.chipOn]}>
      <Text style={[st.chipTxt, on && st.chipTxtOn]}>{label}</Text>
    </Pressable>
  );

  const empPicker = (val: string, set: (v: string) => void) => (
    <View style={st.wrapRow}>
      {emps.slice(0, 60).map((e) => chip(e.name, val === e.user_id, () => set(e.user_id), e.user_id))}
    </View>
  );
  const brPicker = (val: string, set: (v: string) => void) => (
    <View style={st.wrapRow}>
      {branches.map((b) => chip(b.name, val === b.branch_id, () => set(b.branch_id), b.branch_id))}
    </View>
  );

  const filteredEmps = emps.filter((e) => !empQ.trim() || e.name?.toLowerCase().includes(empQ.toLowerCase()));
  const linkable = allBranches.filter((b) => b.company_id !== cid && !(b.linked_company_ids || []).includes(cid));

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={8}>
          <Ionicons name="arrow-back" size={22} color="#0F172A" />
        </Pressable>
        <Text style={st.h1}>Branch Management</Text>
        <Pressable onPress={() => router.push("/branch-dashboard")} style={st.dashBtn} testID="open-branch-dashboard">
          <Ionicons name="stats-chart" size={14} color="#fff" />
          <Text style={st.dashBtnTxt}>Dashboard</Text>
        </Pressable>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0 }} contentContainerStyle={{ paddingHorizontal: 12, gap: 6 }}>
        {companies.map((c) => chip(c.name, cid === c.company_id, () => setCid(c.company_id), c.company_id))}
      </ScrollView>
      <View style={st.tabRow}>
        {TABS.map((t) => chip(t, tab === t, () => setTab(t), t))}
      </View>
      {busy ? <ActivityIndicator style={{ marginTop: 24 }} /> : (
        <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 60, gap: 10 }}>
          {tab === "Branches" ? (
            <>
              <Text style={st.hint}>
                Create branches on the Branches screen (map + geofence). Here you manage the extended
                master fields, Active status and firm linking. Branch Code is unique per firm.
              </Text>
              {branches.map((b) => (
                <View key={b.branch_id} style={st.card} testID={`bm-branch-${b.branch_id}`}>
                  <View style={st.rowBetween}>
                    <Text style={st.cardT}>{b.name} {b.code ? `· ${b.code}` : ""}</Text>
                    <View style={[st.badge, { backgroundColor: b.active === false ? "#FEE2E2" : "#DCFCE7" }]}>
                      <Text style={[st.badgeTxt, { color: b.active === false ? "#B91C1C" : "#15803D" }]}>
                        {b.active === false ? "INACTIVE" : "ACTIVE"}
                      </Text>
                    </View>
                  </View>
                  <Text style={st.sub}>
                    {[b.city, b.state, b.pin].filter(Boolean).join(", ") || "No address set"}
                    {b.head_name ? `  ·  Head: ${b.head_name}` : ""}
                    {b.company_id !== cid ? "  ·  🔗 linked" : ""}
                  </Text>
                  <Pressable style={st.linkBtn} onPress={() => setEdit({ ...b })} testID={`bm-edit-${b.branch_id}`}>
                    <Text style={st.linkTxt}>Edit details</Text>
                  </Pressable>
                </View>
              ))}
              {edit ? (
                <View style={[st.card, { borderColor: "#2563EB" }]}>
                  <Text style={st.cardT}>Edit — {edit.name}</Text>
                  {([["name", "Branch Name"], ["code", "Branch Code (unique)"], ["address", "Address"],
                    ["state", "State"], ["city", "City"], ["pin", "PIN"], ["head_name", "Branch Head"],
                    ["email", "Branch Email"], ["mobile", "Branch Mobile"]] as const).map(([k, lbl]) => (
                      <View key={k} style={{ marginTop: 6 }}>
                        <Text style={st.lbl}>{lbl}</Text>
                        <TextInput style={st.input} value={String((edit as any)[k] ?? "")}
                          onChangeText={(v) => setEdit((p) => p ? ({ ...p, [k]: v }) : p)}
                          testID={`bm-f-${k}`} />
                      </View>
                    ))}
                  <View style={[st.wrapRow, { marginTop: 8 }]}>
                    {chip(edit.active === false ? "Inactive" : "Active", true,
                      () => setEdit((p) => p ? ({ ...p, active: p.active === false }) : p))}
                  </View>
                  <View style={st.rowBetween}>
                    <Pressable style={st.saveBtn} onPress={saveBranch} testID="bm-save-branch">
                      <Text style={st.saveTxt}>Save Branch</Text>
                    </Pressable>
                    <Pressable onPress={() => setEdit(null)}><Text style={st.linkTxt}>Cancel</Text></Pressable>
                  </View>
                </View>
              ) : null}
              {linkable.length ? (
                <View style={st.card}>
                  <Text style={st.cardT}>🔗 Link Existing Branch</Text>
                  <Text style={st.hint}>Attach a branch created under another firm to this firm (authorized admins only).</Text>
                  {linkable.slice(0, 20).map((b) => (
                    <View key={b.branch_id} style={st.rowBetween}>
                      <Text style={st.sub}>{b.name}</Text>
                      <Pressable style={st.linkBtn} onPress={() => linkExisting(b)}>
                        <Text style={st.linkTxt}>Link</Text>
                      </Pressable>
                    </View>
                  ))}
                </View>
              ) : null}
            </>
          ) : null}

          {tab === "Employees" ? (
            <>
              <TextInput style={st.input} placeholder="Search employee…" value={empQ} onChangeText={setEmpQ} testID="bm-emp-search" />
              {filteredEmps.map((e) => (
                <Pressable key={e.user_id} style={st.card} onPress={() => setEmpSel({ ...e, authorized_branch_ids: e.authorized_branch_ids || [] })} testID={`bm-emp-${e.user_id}`}>
                  <Text style={st.cardT}>{e.name}</Text>
                  <Text style={st.sub}>
                    Home: {bname(e.home_branch_id)} · Authorized: {(e.authorized_branch_ids || []).map(bname).join(", ") || "—"}
                  </Text>
                </Pressable>
              ))}
              {empSel ? (
                <View style={[st.card, { borderColor: "#2563EB" }]}>
                  <Text style={st.cardT}>Assign — {empSel.name}</Text>
                  <Text style={st.lbl}>Home Branch (permanent; never auto-changes)</Text>
                  <View style={st.wrapRow}>
                    {chip("None", !empSel.home_branch_id, () => setEmpSel((p) => p ? ({ ...p, home_branch_id: null }) : p))}
                    {branches.map((b) => chip(b.name, empSel.home_branch_id === b.branch_id,
                      () => setEmpSel((p) => p ? ({ ...p, home_branch_id: b.branch_id }) : p), b.branch_id))}
                  </View>
                  <Text style={st.lbl}>Authorized Branches (may punch here)</Text>
                  <View style={st.wrapRow}>
                    {branches.map((b) => chip(b.name, (empSel.authorized_branch_ids || []).includes(b.branch_id), () => {
                      setEmpSel((p) => {
                        if (!p) return p;
                        const cur = p.authorized_branch_ids || [];
                        return { ...p, authorized_branch_ids: cur.includes(b.branch_id) ? cur.filter((x) => x !== b.branch_id) : [...cur, b.branch_id] };
                      });
                    }, `a-${b.branch_id}`))}
                  </View>
                  <View style={st.rowBetween}>
                    <Pressable style={st.saveBtn} onPress={saveAssign} testID="bm-save-assign">
                      <Text style={st.saveTxt}>Save Assignment</Text>
                    </Pressable>
                    <Pressable onPress={() => setEmpSel(null)}><Text style={st.linkTxt}>Cancel</Text></Pressable>
                  </View>
                </View>
              ) : null}
            </>
          ) : null}

          {tab === "Temp Assignments" ? (
            <>
              <View style={st.card}>
                <Text style={st.cardT}>＋ New Temporary Assignment</Text>
                <Text style={st.lbl}>Employee</Text>
                {empPicker(taForm.user_id, (v) => setTaForm((p) => ({ ...p, user_id: v })))}
                <Text style={st.lbl}>Branch</Text>
                {brPicker(taForm.branch_id, (v) => setTaForm((p) => ({ ...p, branch_id: v })))}
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <View style={{ flex: 1 }}>
                    <Text style={st.lbl}>From (YYYY-MM-DD)</Text>
                    <TextInput style={st.input} value={taForm.from_date} placeholder="2026-08-20" onChangeText={(v) => setTaForm((p) => ({ ...p, from_date: v }))} testID="ta-from" />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={st.lbl}>To (YYYY-MM-DD)</Text>
                    <TextInput style={st.input} value={taForm.to_date} placeholder="2026-08-25" onChangeText={(v) => setTaForm((p) => ({ ...p, to_date: v }))} testID="ta-to" />
                  </View>
                </View>
                <Text style={st.lbl}>Reason</Text>
                <TextInput style={st.input} value={taForm.reason} placeholder="Project work" onChangeText={(v) => setTaForm((p) => ({ ...p, reason: v }))} testID="ta-reason" />
                <Pressable style={st.saveBtn} onPress={createTa} testID="ta-create">
                  <Text style={st.saveTxt}>Approve Assignment</Text>
                </Pressable>
              </View>
              {assigns.map((a) => (
                <View key={a.assign_id} style={st.card}>
                  <View style={st.rowBetween}>
                    <Text style={st.cardT}>{a.employee_name}</Text>
                    <View style={[st.badge, { backgroundColor: a.status === "approved" ? "#DBEAFE" : "#F1F5F9" }]}>
                      <Text style={st.badgeTxt}>{String(a.status || "").toUpperCase()}</Text>
                    </View>
                  </View>
                  <Text style={st.sub}>{bname(a.branch_id)} · {a.from_date} → {a.to_date}{a.reason ? ` · ${a.reason}` : ""}</Text>
                  {a.status === "approved" ? (
                    <Pressable style={st.linkBtn} onPress={async () => {
                      await api(`/admin/branch-management/temp-assignments/${a.assign_id}/cancel`, { method: "PATCH" });
                      load();
                    }}>
                      <Text style={[st.linkTxt, { color: "#DC2626" }]}>Cancel</Text>
                    </Pressable>
                  ) : null}
                </View>
              ))}
            </>
          ) : null}

          {tab === "Transfers" ? (
            <>
              <View style={st.card}>
                <Text style={st.cardT}>＋ Permanent Branch Transfer</Text>
                <Text style={st.hint}>Applies on the effective date. Historical records keep the old branch.</Text>
                <Text style={st.lbl}>Employee</Text>
                {empPicker(trForm.user_id, (v) => setTrForm((p) => ({ ...p, user_id: v })))}
                <Text style={st.lbl}>New Home Branch</Text>
                {brPicker(trForm.new_branch_id, (v) => setTrForm((p) => ({ ...p, new_branch_id: v })))}
                <Text style={st.lbl}>Effective Date (YYYY-MM-DD)</Text>
                <TextInput style={st.input} value={trForm.effective_date} placeholder="2026-09-01" onChangeText={(v) => setTrForm((p) => ({ ...p, effective_date: v }))} testID="tr-eff" />
                <Text style={st.lbl}>Reason</Text>
                <TextInput style={st.input} value={trForm.reason} onChangeText={(v) => setTrForm((p) => ({ ...p, reason: v }))} testID="tr-reason" />
                <Pressable style={st.saveBtn} onPress={createTr} testID="tr-create">
                  <Text style={st.saveTxt}>Record Transfer</Text>
                </Pressable>
              </View>
              {transfers.map((t) => (
                <View key={t.transfer_id} style={st.card}>
                  <View style={st.rowBetween}>
                    <Text style={st.cardT}>{t.employee_name}</Text>
                    <View style={[st.badge, { backgroundColor: t.status === "applied" ? "#DCFCE7" : "#FEF9C3" }]}>
                      <Text style={st.badgeTxt}>{String(t.status || "").toUpperCase()}</Text>
                    </View>
                  </View>
                  <Text style={st.sub}>
                    {bname(t.prev_branch_id)} → {bname(t.new_branch_id)} · from {t.effective_date}{t.reason ? ` · ${t.reason}` : ""}
                  </Text>
                </View>
              ))}
            </>
          ) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F8FAFC" },
  header: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14 },
  h1: { fontSize: 18, fontWeight: "800", color: "#0F172A", flex: 1 },
  dashBtn: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: "#2563EB", paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8 },
  dashBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  tabRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, paddingHorizontal: 12, paddingVertical: 8 },
  chip: { borderWidth: 1, borderColor: "#CBD5E1", borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6, backgroundColor: "#fff" },
  chipOn: { backgroundColor: "#2563EB", borderColor: "#2563EB" },
  chipTxt: { fontSize: 12, color: "#334155", fontWeight: "600" },
  chipTxtOn: { color: "#fff" },
  card: { backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#E2E8F0", padding: 12, gap: 4 },
  cardT: { fontSize: 14, fontWeight: "800", color: "#0F172A" },
  sub: { fontSize: 12, color: "#64748B" },
  hint: { fontSize: 11.5, color: "#94A3B8" },
  lbl: { fontSize: 11, fontWeight: "700", color: "#64748B", marginTop: 6 },
  input: { borderWidth: 1, borderColor: "#CBD5E1", borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, backgroundColor: "#fff", marginTop: 2 },
  wrapRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 8 },
  badge: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  badgeTxt: { fontSize: 10, fontWeight: "800", color: "#334155" },
  linkBtn: { alignSelf: "flex-start", marginTop: 6 },
  linkTxt: { color: "#2563EB", fontWeight: "700", fontSize: 12.5 },
  saveBtn: { backgroundColor: "#16A34A", borderRadius: 8, paddingHorizontal: 16, paddingVertical: 10, marginTop: 10, alignSelf: "flex-start" },
  saveTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
});
