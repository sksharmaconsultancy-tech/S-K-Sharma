/**
 * Iter 746 — ORGANIZATION HIERARCHY (user PRD Phase 1).
 * Tabs: Department Hierarchy (interactive tree) | Reporting Structure |
 * Org Reports. Uses EXISTING department masters + users (no duplicates).
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Platform, Modal } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Redirect } from "expo-router";
import { api, apiBinary } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

const CHAIN: [string, string][] = [["primary_manager", "Reporting Manager"], ["secondary_manager", "Functional Mgr"], ["dept_head", "Dept Head"], ["hr_manager", "HR Manager"], ["final_approver", "Final Approver"]];

export default function OrgHierarchyScreen() {
  const { user, loading: authLoading } = useAuth();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [tab, setTab] = useState<"tree" | "reporting" | "reports">("tree");
  const [chart, setChart] = useState<any>(null);
  const [depts, setDepts] = useState<any[]>([]);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [q, setQ] = useState("");
  const [emps, setEmps] = useState<any[]>([]);
  const [deptEmps, setDeptEmps] = useState<{ name: string; list: any[] } | null>(null);
  const [editDept, setEditDept] = useState<any>(null);
  const [editChain, setEditChain] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const cid = user?.role === "company_admin" ? user.company_id : companyId;

  const load = useCallback(async () => {
    if (!cid) return;
    setBusy(true);
    try {
      const [c, d] = await Promise.all([
        api<any>(`/org/chart?company_id=${cid}`),
        api<any>(`/org/departments?company_id=${cid}`)]);
      setChart(c); setDepts(d.departments || []);
    } catch (e: any) { setMsg(e?.message || "Load failed"); }
    finally { setBusy(false); }
  }, [cid]);
  useEffect(() => { load(); }, [load]);

  const loadEmps = useCallback(async () => {
    if (!cid) return;
    try {
      const r = await api<any>(`/org/reporting?company_id=${cid}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
      setEmps(r.employees || []);
    } catch { /* ignore */ }
  }, [cid, q]);
  useEffect(() => { if (tab === "reporting") loadEmps(); }, [tab, loadEmps]);

  if (authLoading) return <View style={st.center}><ActivityIndicator /></View>;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role)) return <Redirect href="/" />;

  const showDeptEmployees = async (d: any) => {
    try {
      const r = await api<any>(`/org/departments/${d.master_id}/employees?company_id=${cid}`);
      setDeptEmps({ name: r.department, list: r.employees || [] });
    } catch (e: any) { setMsg(e?.message || "Load failed"); }
  };
  const saveDept = async () => {
    if (!editDept || !cid) return;
    setBusy(true);
    try {
      await api(`/org/departments/${editDept.master_id}`, { method: "PATCH", body: { ...editDept, company_id: cid } });
      setEditDept(null); setMsg("✅ Department saved"); load();
    } catch (e: any) { setMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };
  const saveChain = async () => {
    if (!editChain || !cid) return;
    setBusy(true);
    try {
      await api(`/org/reporting/${editChain.user_id}`, { method: "POST", body: { ...editChain.chain, company_id: cid } });
      setEditChain(null); setMsg("✅ Reporting chain saved"); loadEmps();
    } catch (e: any) { setMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };
  const dl = async (kind: string, fmt: string) => {
    try {
      const r = await apiBinary(`/org/report?kind=${kind}&fmt=${fmt}&company_id=${cid}`);
      if (Platform.OS === "web" && (r as any).webBlobUrl) {
        const a = document.createElement("a");
        a.href = (r as any).webBlobUrl; a.download = `org_${kind}.${fmt}`; a.click();
      }
    } catch (e: any) { setMsg(e?.message || "Download failed"); }
  };

  const renderNode = (n: any, depth: number) => {
    const kids = n.children || [];
    const isOpen = open.has(n.master_id);
    if (q && !String(n.name || "").toLowerCase().includes(q.toLowerCase()) && !kids.length) return null;
    return (
      <View key={n.master_id}>
        <View style={[st.node, { marginLeft: depth * 18, opacity: n.status === "inactive" ? 0.5 : 1 }]}>
          <Pressable onPress={() => { const s = new Set(open); if (s.has(n.master_id)) s.delete(n.master_id); else s.add(n.master_id); setOpen(s); }} hitSlop={8}>
            <Text style={st.caret}>{kids.length ? (isOpen ? "▼" : "▶") : "•"}</Text>
          </Pressable>
          <Pressable style={{ flex: 1 }} onPress={() => showDeptEmployees(n)} testID={`org-dept-${n.name}`}>
            <Text style={st.nodeName}>{n.name} {n.code ? `(${n.code})` : ""} <Text style={st.nodeCount}>👥 {n.employee_count}</Text></Text>
            <Text style={st.nodeSub}>{n.head_name ? `Head: ${n.head_name}` : "Head: —"}{n.branch_name ? ` · ${n.branch_name}` : ""}{n.status === "inactive" ? " · INACTIVE" : ""}</Text>
          </Pressable>
          <Pressable style={st.editBtn} onPress={() => setEditDept({ ...n })} testID={`org-edit-${n.name}`}><Text style={st.editTxt}>Edit</Text></Pressable>
        </View>
        {isOpen ? kids.map((k: any) => renderNode(k, depth + 1)) : null}
      </View>
    );
  };

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={st.body}>
        <Text style={st.h1}>🏢 Organization Hierarchy</Text>
        {user.role !== "company_admin" && <CompanyPicker value={companyId} onChange={setCompanyId} />}
        <View style={st.tabs}>
          {([["tree", "Dept Hierarchy"], ["reporting", "Reporting Structure"], ["reports", "Org Reports"]] as [any, string][]).map(([t, l]) => (
            <Pressable key={t} style={[st.tab, tab === t && st.tabOn]} onPress={() => setTab(t)} testID={`org-tab-${t}`}>
              <Text style={[st.tabTxt, tab === t && st.tabTxtOn]}>{l}</Text>
            </Pressable>
          ))}
        </View>
        {msg ? <Text style={st.msg}>{msg}</Text> : null}
        {busy ? <ActivityIndicator style={{ marginVertical: 8 }} /> : null}

        {tab === "tree" && chart ? (
          <View style={st.card}>
            <Text style={st.sum}>{chart.firm} · {chart.total_departments} departments · Branches: {(chart.branches || []).map((b: any) => `${b.name} (${b.employee_count})`).join(", ") || "—"}</Text>
            <TextInput style={st.input} value={q} onChangeText={setQ} placeholder="🔍 Department / employee search" placeholderTextColor={colors.onSurfaceTertiary} testID="org-search" />
            <View style={st.rowBtns}>
              <Pressable style={st.btnXs} onPress={() => setOpen(new Set(depts.map((d) => d.master_id)))}><Text style={st.btnTxt}>Expand All</Text></Pressable>
              <Pressable style={[st.btnXs, { backgroundColor: "#555" }]} onPress={() => setOpen(new Set())}><Text style={st.btnTxt}>Collapse</Text></Pressable>
            </View>
            {(chart.tree || []).map((n: any) => renderNode(n, 0))}
          </View>
        ) : null}

        {tab === "reporting" ? (
          <View style={st.card}>
            <TextInput style={st.input} value={q} onChangeText={setQ} onSubmitEditing={loadEmps} placeholder="🔍 Employee name / code" placeholderTextColor={colors.onSurfaceTertiary} />
            {emps.map((e) => (
              <Pressable key={e.user_id} style={st.empRow} onPress={() => setEditChain({ user_id: e.user_id, name: e.name, chain: { ...(e.reporting_chain || {}) } })} testID={`org-emp-${e.employee_code}`}>
                <Text style={st.nodeName}>{e.employee_code} · {e.name}</Text>
                <Text style={st.nodeSub}>{e.department || "—"} · {e.designation || "—"} · {e.branch_name || "—"}</Text>
                <Text style={st.chainTxt}>
                  {CHAIN.map(([k, l]) => (e.chain_names || {})[k] ? `${l}: ${e.chain_names[k]}` : null).filter(Boolean).join(" → ") || "Chain set nahi — tap karke set karein"}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}

        {tab === "reports" ? (
          <View style={st.card}>
            {[["hierarchy", "Department Hierarchy"], ["reporting", "Employee Reporting Structure"], ["manager_wise", "Manager-wise Employee List"], ["dept_wise", "Department-wise Employee List"], ["branch_dept", "Branch-wise Department Report"]].map(([k, l]) => (
              <View key={k} style={st.repRow}>
                <Text style={[st.lbl, { flex: 1 }]}>{l}</Text>
                <Pressable style={st.btnXs} onPress={() => dl(k, "xlsx")}><Text style={st.btnTxt}>Excel</Text></Pressable>
                <Pressable style={[st.btnXs, { backgroundColor: "#b3261e" }]} onPress={() => dl(k, "pdf")}><Text style={st.btnTxt}>PDF</Text></Pressable>
              </View>
            ))}
          </View>
        ) : null}
      </ScrollView>

      {/* Dept employees modal */}
      <Modal visible={!!deptEmps} transparent animationType="fade" onRequestClose={() => setDeptEmps(null)}>
        <View style={st.mWrap}><View style={st.mCard}>
          <Text style={st.h2}>👥 {deptEmps?.name} ({deptEmps?.list.length})</Text>
          <ScrollView style={{ maxHeight: 380 }}>
            {(deptEmps?.list || []).map((e) => (
              <Text key={e.user_id} style={st.nodeSub}>{e.employee_code} · {e.name} · {e.designation || "—"} · {e.branch_name || "—"}</Text>
            ))}
          </ScrollView>
          <Pressable style={st.btn} onPress={() => setDeptEmps(null)}><Text style={st.btnTxt}>Close</Text></Pressable>
        </View></View>
      </Modal>

      {/* Dept edit modal */}
      <Modal visible={!!editDept} transparent animationType="fade" onRequestClose={() => setEditDept(null)}>
        <View style={st.mWrap}><View style={st.mCard}>
          <Text style={st.h2}>✏️ {editDept?.name}</Text>
          <ScrollView style={{ maxHeight: 420 }}>
            <Text style={st.lbl}>Department Code</Text>
            <TextInput style={st.input} value={editDept?.code || ""} onChangeText={(t) => setEditDept({ ...editDept, code: t })} placeholderTextColor={colors.onSurfaceTertiary} />
            <Text style={st.lbl}>Parent Department</Text>
            <View style={st.chips}>
              <Pressable style={[st.chip, !editDept?.parent_id && st.chipOn]} onPress={() => setEditDept({ ...editDept, parent_id: null })}><Text style={st.chipTxt}>None (Top)</Text></Pressable>
              {depts.filter((d) => d.master_id !== editDept?.master_id).map((d) => (
                <Pressable key={d.master_id} style={[st.chip, editDept?.parent_id === d.master_id && st.chipOn]} onPress={() => setEditDept({ ...editDept, parent_id: d.master_id })}>
                  <Text style={[st.chipTxt, editDept?.parent_id === d.master_id && st.chipTxtOn]}>{d.name}</Text>
                </Pressable>
              ))}
            </View>
            <Text style={st.lbl}>Department Head (Emp Code likhein)</Text>
            <EmployeePick cid={cid!} value={editDept?.head_user_id} onPick={(uid) => setEditDept({ ...editDept, head_user_id: uid })} />
            <Text style={st.lbl}>Cost Centre</Text>
            <TextInput style={st.input} value={editDept?.cost_centre || ""} onChangeText={(t) => setEditDept({ ...editDept, cost_centre: t })} placeholderTextColor={colors.onSurfaceTertiary} />
            <Text style={st.lbl}>Effective From (YYYY-MM-DD)</Text>
            <TextInput style={st.input} value={editDept?.effective_from || ""} onChangeText={(t) => setEditDept({ ...editDept, effective_from: t })} placeholder="optional" placeholderTextColor={colors.onSurfaceTertiary} />
            <Pressable style={st.togRow} onPress={() => setEditDept({ ...editDept, status: editDept?.status === "inactive" ? "active" : "inactive" })}>
              <Text style={st.lbl}>Status: {editDept?.status === "inactive" ? "INACTIVE ❌" : "ACTIVE ✅"} (tap to toggle)</Text>
            </Pressable>
          </ScrollView>
          <View style={st.rowBtns}>
            <Pressable style={[st.btn, { flex: 1 }]} onPress={saveDept} testID="org-dept-save"><Text style={st.btnTxt}>Save</Text></Pressable>
            <Pressable style={[st.btn, { flex: 1, backgroundColor: "#555" }]} onPress={() => setEditDept(null)}><Text style={st.btnTxt}>Cancel</Text></Pressable>
          </View>
        </View></View>
      </Modal>

      {/* Reporting chain edit modal */}
      <Modal visible={!!editChain} transparent animationType="fade" onRequestClose={() => setEditChain(null)}>
        <View style={st.mWrap}><View style={st.mCard}>
          <Text style={st.h2}>🔗 {editChain?.name} — Reporting Chain</Text>
          <ScrollView style={{ maxHeight: 440 }}>
            {CHAIN.map(([k, l]) => (
              <View key={k}>
                <Text style={st.lbl}>{l}</Text>
                <EmployeePick cid={cid!} value={editChain?.chain?.[k]} onPick={(uid) => setEditChain({ ...editChain, chain: { ...editChain.chain, [k]: uid } })} />
              </View>
            ))}
            <Text style={st.hint}>Ye hi chain OT approval me use hoti hai — aur aage Leave / Expense / F&F approvals me bhi yahi kaam karegi.</Text>
          </ScrollView>
          <View style={st.rowBtns}>
            <Pressable style={[st.btn, { flex: 1 }]} onPress={saveChain} testID="org-chain-save"><Text style={st.btnTxt}>Save</Text></Pressable>
            <Pressable style={[st.btn, { flex: 1, backgroundColor: "#555" }]} onPress={() => setEditChain(null)}><Text style={st.btnTxt}>Cancel</Text></Pressable>
          </View>
        </View></View>
      </Modal>
    </SafeAreaView>
  );
}

function EmployeePick({ cid, value, onPick }: { cid: string; value?: string | null; onPick: (uid: string | null) => void }) {
  const [q, setQ] = useState("");
  const [opts, setOpts] = useState<any[]>([]);
  const [selName, setSelName] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    if (!value) { setSelName(null); return; }
    api<any>(`/org/reporting?company_id=${cid}`).then((r) => {
      if (!live) return;
      const f = (r.employees || []).find((e: any) => e.user_id === value);
      setSelName(f ? `${f.employee_code} · ${f.name}` : value);
    }).catch(() => {});
    return () => { live = false; };
  }, [value, cid]);
  const search = async (t: string) => {
    setQ(t);
    if (t.length < 2) { setOpts([]); return; }
    try {
      const r = await api<any>(`/org/reporting?company_id=${cid}&q=${encodeURIComponent(t)}`);
      setOpts((r.employees || []).slice(0, 8));
    } catch { setOpts([]); }
  };
  return (
    <View style={{ marginBottom: 8 }}>
      {value ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Text style={{ color: "#7dc97d", fontSize: 12, flex: 1 }}>✅ {selName || value}</Text>
          <Pressable onPress={() => onPick(null)}><Text style={{ color: "#ff8a80", fontSize: 12 }}>✕ Clear</Text></Pressable>
        </View>
      ) : (
        <>
          <TextInput style={st.input} value={q} onChangeText={search} placeholder="naam/code type karein (min 2)" placeholderTextColor={colors.onSurfaceTertiary} />
          {opts.map((o) => (
            <Pressable key={o.user_id} onPress={() => { onPick(o.user_id); setQ(""); setOpts([]); }}>
              <Text style={{ color: colors.onSurfaceSecondary, fontSize: 12, paddingVertical: 4 }}>{o.employee_code} · {o.name} ({o.designation || "—"})</Text>
            </Pressable>
          ))}
        </>
      )}
    </View>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background },
  body: { padding: spacing.lg, paddingBottom: 80 },
  h1: { fontSize: 20, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  h2: { fontSize: 16, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  tabs: { flexDirection: "row", gap: 8, marginVertical: 10, flexWrap: "wrap" },
  tab: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md, backgroundColor: colors.surfaceElevated },
  tabOn: { backgroundColor: colors.cta },
  tabTxt: { color: colors.onSurfaceSecondary, fontWeight: "700", fontSize: 13 },
  tabTxtOn: { color: "#fff" },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, marginTop: 8 },
  sum: { color: colors.onSurfaceSecondary, fontSize: 12, marginBottom: 8, lineHeight: 18 },
  msg: { color: "#ffd54f", marginVertical: 6, fontSize: 13 },
  lbl: { color: colors.onSurface, fontSize: 13, fontWeight: "600", marginTop: 8 },
  hint: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 8 },
  input: { backgroundColor: colors.surfaceElevated, color: colors.onSurface, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 8, marginTop: 6, fontSize: 13 },
  rowBtns: { flexDirection: "row", gap: 8, marginTop: 10 },
  node: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 7, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: "#333" },
  caret: { color: colors.cta, fontSize: 13, width: 18 },
  nodeName: { color: colors.onSurface, fontSize: 13, fontWeight: "700" },
  nodeCount: { color: "#7dc97d", fontSize: 12 },
  nodeSub: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 1 },
  chainTxt: { color: "#9fc3ff", fontSize: 11, marginTop: 3 },
  editBtn: { backgroundColor: colors.surfaceElevated, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 5 },
  editTxt: { color: colors.cta, fontSize: 11, fontWeight: "700" },
  empRow: { paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: "#333" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginVertical: 8 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 14, backgroundColor: colors.surfaceElevated },
  chipOn: { backgroundColor: colors.cta },
  chipTxt: { color: colors.onSurfaceSecondary, fontSize: 12 },
  chipTxtOn: { color: "#fff", fontWeight: "700" },
  togRow: { marginVertical: 8 },
  btn: { backgroundColor: colors.cta, borderRadius: radius.md, paddingVertical: 12, alignItems: "center", marginTop: 12 },
  btnXs: { backgroundColor: "#2e7d32", borderRadius: radius.sm, paddingVertical: 6, paddingHorizontal: 10 },
  btnTxt: { color: "#fff", fontWeight: "700", fontSize: 12 },
  repRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 7, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: "#333" },
  mWrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center", padding: 16 },
  mCard: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, width: "100%", maxWidth: 520 },
});
