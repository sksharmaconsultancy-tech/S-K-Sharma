/**
 * Iter 586 — Roles & Permissions (RBAC Phase 1/2).
 * Super Admin: select a sub-admin / client user →
 *  1. Module × Action permission matrix (View/Add/Edit/Delete/Export/Approve)
 *  2. Sensitive Data (unmasked values) toggle
 *  3. Branch / Department data scope pickers
 * Saves via PATCH /admin/access/user-permissions and /admin/access/user-scope
 * (server-side validated + CRITICAL audit).
 */
import React, { useState } from "react";
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

const ACTIONS = ["view", "add", "edit", "delete", "export", "approve"];

export default function RolesPermissionsScreen() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [users, setUsers] = useState<any[]>([]);
  const [sel, setSel] = useState<any>(null);
  const [matrix, setMatrix] = useState<Record<string, Record<string, boolean>>>({});
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [sensitive, setSensitive] = useState(false);
  const [branches, setBranches] = useState<any[]>([]);
  const [departments, setDepartments] = useState<any[]>([]);
  const [brSel, setBrSel] = useState<Set<string>>(new Set());
  const [dpSel, setDpSel] = useState<Set<string>>(new Set());
  const [brAll, setBrAll] = useState(true);
  const [dpAll, setDpAll] = useState(true);
  // Iter 594 — firm access editor (all Firm Master firms, filterable).
  const [firms, setFirms] = useState<any[]>([]);
  const [fmSel, setFmSel] = useState<Set<string>>(new Set());
  const [fmAll, setFmAll] = useState(true);
  const [fmFilter, setFmFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 3500); };

  const search = async () => {
    setBusy(true); setSel(null);
    try {
      const r = await api<{ users: any[] }>(
        `/admin/access-preview/users?q=${encodeURIComponent(q.trim())}`);
      setUsers((r.users || []).filter((u) => u.role !== "employee"));
    } catch (e: any) { flash(e.message || "Search failed"); }
    finally { setBusy(false); }
  };

  const open = async (u: any) => {
    setBusy(true);
    try {
      const p = await api<any>(`/admin/access-preview/${u.user_id}`);
      setSel({ ...u, preview: p });
      setMatrix(JSON.parse(JSON.stringify(p.matrix || {})));
      setLabels(p.module_labels || {});
      setSensitive(!!p.sensitive_data_view);
      setBrAll(p.branch_scope?.mode !== "SELECTED_BRANCHES");
      setDpAll(p.department_scope?.mode !== "SELECTED_DEPARTMENTS");
      setBrSel(new Set(p.branch_scope?.branch_ids || []));
      setDpSel(new Set(p.department_scope?.department_ids || []));
      // Firm access — load the full Firm Master list, pre-select current.
      try {
        const c = await api<any>(`/companies`);
        setFirms(c.companies || c || []);
      } catch { setFirms([]); }
      const restricted = p.firm_scope?.mode === "RESTRICTED_FIRMS";
      setFmAll(!restricted);
      setFmSel(new Set((p.firm_scope?.firms || []).map((f: any) => f.company_id)));
      setFmFilter("");
      const cid = (p.firm_scope?.firms || [])[0]?.company_id || u.company_id;
      if (cid) {
        try {
          const b = await api<any>(`/admin/branches?company_id=${cid}`);
          setBranches(b.branches || b || []);
        } catch { setBranches([]); }
        try {
          const d = await api<any>(`/admin/departments?company_id=${cid}`);
          setDepartments(d.departments || []);
        } catch { setDepartments([]); }
      }
    } catch (e: any) { flash(e.message || "Failed to load user"); }
    finally { setBusy(false); }
  };

  const toggleCell = (m: string, a: string) =>
    setMatrix((prev) => ({ ...prev, [m]: { ...prev[m], [a]: !prev[m]?.[a] } }));

  // Iter 591 — bulk toggles: whole module row / whole action column.
  const toggleRow = (m: string) =>
    setMatrix((prev) => {
      const on = !ACTIONS.every((a) => prev[m]?.[a]);
      return { ...prev, [m]: Object.fromEntries(ACTIONS.map((a) => [a, on])) };
    });
  const toggleCol = (a: string) =>
    setMatrix((prev) => {
      const on = !Object.keys(prev).every((m) => prev[m]?.[a]);
      const next: any = {};
      Object.keys(prev).forEach((m) => { next[m] = { ...prev[m], [a]: on }; });
      return next;
    });

  const savePerms = async () => {
    if (!sel) return;
    const perms: string[] = [];
    Object.entries(matrix).forEach(([m, acts]: any) =>
      ACTIONS.forEach((a) => { if (acts[a]) perms.push(`${m}:${a}`); }));
    if (sensitive) perms.push("sensitive_data:view");
    setBusy(true);
    try {
      await api("/admin/access/user-permissions", {
        method: "PATCH", body: { user_id: sel.user_id, permissions: perms } });
      flash("Permissions saved ✓ (audited)");
    } catch (e: any) { flash(e.message || "Save failed"); }
    finally { setBusy(false); }
  };

  const saveScope = async () => {
    if (!sel) return;
    setBusy(true);
    try {
      await api("/admin/access/user-scope", {
        method: "PATCH",
        body: {
          user_id: sel.user_id,
          ...(sel.role === "sub_admin"
            ? { firm_scope: fmAll ? { all: true } : { all: false, ids: Array.from(fmSel) } }
            : {}),
          branch_scope: brAll ? { all: true } : { all: false, ids: Array.from(brSel) },
          department_scope: dpAll ? { all: true } : { all: false, ids: Array.from(dpSel) },
        } });
      flash("Data scope saved ✓ (takes effect immediately)");
    } catch (e: any) { flash(e.message || "Scope save failed"); }
    finally { setBusy(false); }
  };

  const chip = (on: boolean, label: string, onPress: () => void, key: string) => (
    <Pressable key={key} onPress={onPress} testID={`rp-chip-${key}`}
      style={[st.chip, on && { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary }]}>
      <Text style={[st.chipTxt, on && { color: "#fff" }]}>{on ? "✓ " : ""}{label}</Text>
    </Pressable>
  );

  return (
    <SafeAreaView style={st.root} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} style={{ padding: 6 }}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.h1}>Roles & Permissions</Text>
          <Text style={st.sub}>Action-level permissions + data scope (server-enforced)</Text>
        </View>
      </View>
      <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: 10, paddingBottom: 80 }}>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <TextInput style={st.input} value={q} onChangeText={setQ}
            placeholder="Search sub-admin / client user"
            placeholderTextColor={colors.onSurfaceTertiary} testID="rp-search" />
          <Pressable style={st.btn} onPress={() => void search()} testID="rp-search-btn">
            <Text style={st.btnTxt}>Search</Text>
          </Pressable>
        </View>
        {busy ? <ActivityIndicator color={colors.brandPrimary} /> : null}
        {!sel && users.map((u) => (
          <Pressable key={u.user_id} style={st.card} onPress={() => void open(u)}>
            <View style={{ flex: 1 }}>
              <Text style={st.name}>{u.name || u.email}</Text>
              <Text style={st.subTxt}>{u.role} · {u.email || "—"}</Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
          </Pressable>
        ))}
        {sel ? (
          <View style={{ gap: 12 }}>
            <Pressable onPress={() => setSel(null)}>
              <Text style={{ color: colors.brandPrimary, fontWeight: "700", fontSize: 12 }}>← Back to results</Text>
            </Pressable>
            <Text style={st.name}>{sel.name} · {sel.role}</Text>

            <View style={st.block} testID="rp-matrix">
              <Text style={st.blockTitle}>Module / Action Permissions — full catalog</Text>
              <Text style={st.legend}>
                R = View · W = Add/Edit · plus Delete / Export / Approve.
                Tap any cell to toggle. Tap a column header to grant/revoke
                that action on ALL modules, or a module&apos;s ALL to grant/revoke
                everything for it.
              </Text>
              <View style={st.mRow}>
                <Text style={[st.mHead, { flex: 2, textAlign: "left" }]}>Module</Text>
                {ACTIONS.map((a) => (
                  <Pressable key={a} style={[st.mCell, { alignItems: "center" }]}
                    onPress={() => toggleCol(a)} testID={`rp-col-${a}`}>
                    <Text style={[st.mHead, { textDecorationLine: "underline" }]}>
                      {a === "view" ? "VIEW (R)" : a === "edit" ? "EDIT (W)" : a.slice(0, 4).toUpperCase()}
                    </Text>
                  </Pressable>
                ))}
                <Text style={st.mHead}>ALL</Text>
              </View>
              {Object.entries(matrix).map(([m, acts]: any) => (
                <View key={m} style={st.mRow}>
                  <View style={{ flex: 2 }}>
                    <Text style={[st.mCell, { textAlign: "left", fontWeight: "700" }]}>
                      {labels[m] || m}
                    </Text>
                    <Text style={st.mKey}>{m}</Text>
                  </View>
                  {ACTIONS.map((a) => (
                    <Pressable key={a} style={[st.mCell, { alignItems: "center" }]}
                      onPress={() => toggleCell(m, a)} testID={`rp-${m}-${a}`}>
                      <Text style={{ color: acts[a] ? "#16A34A" : "#DC2626", fontWeight: "800" }}>
                        {acts[a] ? "✓" : "✗"}
                      </Text>
                    </Pressable>
                  ))}
                  <Pressable style={[st.mCell, { alignItems: "center" }]}
                    onPress={() => toggleRow(m)} testID={`rp-row-${m}`}>
                    <Text style={{
                      color: ACTIONS.every((a) => acts[a]) ? "#16A34A" : colors.onSurfaceTertiary,
                      fontWeight: "800", fontSize: 10.5,
                    }}>
                      {ACTIONS.every((a) => acts[a]) ? "✓ ALL" : "ALL"}
                    </Text>
                  </Pressable>
                </View>
              ))}
              <Pressable style={st.senRow} onPress={() => setSensitive(!sensitive)} testID="rp-sensitive">
                <Text style={{ flex: 1, fontSize: 12.5, fontWeight: "700", color: colors.onSurface }}>
                  Sensitive Data — view unmasked Aadhaar/PAN/Bank/UAN/Mobile
                </Text>
                <Text style={{ color: sensitive ? "#16A34A" : "#DC2626", fontWeight: "800" }}>
                  {sensitive ? "✓ ON" : "✗ OFF (masked)"}
                </Text>
              </Pressable>
              <Pressable style={[st.btn, { marginTop: 8 }]} onPress={() => void savePerms()} testID="rp-save-perms">
                <Text style={st.btnTxt}>Save Permissions</Text>
              </Pressable>
            </View>

            <View style={st.block} testID="rp-scope">
              {sel.role === "sub_admin" ? (
                <>
                  <Text style={st.blockTitle}>Firm Access — from Firm Master ({firms.length})</Text>
                  {!fmAll ? (
                    <TextInput style={st.input} value={fmFilter} onChangeText={setFmFilter}
                      placeholder="🔍 Filter firms…"
                      placeholderTextColor={colors.onSurfaceTertiary}
                      testID="rp-firm-filter" />
                  ) : null}
                  <View style={st.wrap}>
                    {chip(fmAll, "All Firms", () => setFmAll(!fmAll), "fm-all")}
                    {!fmAll && firms
                      .filter((f: any) => !fmFilter.trim()
                        || (f.name || "").toLowerCase().includes(fmFilter.toLowerCase()))
                      .map((f: any) => chip(
                        fmSel.has(f.company_id), f.name || f.company_id,
                        () => { const s = new Set(fmSel); if (s.has(f.company_id)) s.delete(f.company_id); else s.add(f.company_id); setFmSel(s); },
                        f.company_id))}
                  </View>
                  {!fmAll ? (
                    <Text style={st.legend}>{fmSel.size} of {firms.length} firms selected</Text>
                  ) : null}
                </>
              ) : null}
              <Text style={st.blockTitle}>Data Scope — Branches</Text>
              <View style={st.wrap}>
                {chip(brAll, "All Branches", () => setBrAll(!brAll), "br-all")}
                {!brAll && branches.map((b: any) => chip(
                  brSel.has(b.branch_id), b.name || b.branch_id,
                  () => { const s = new Set(brSel); if (s.has(b.branch_id)) s.delete(b.branch_id); else s.add(b.branch_id); setBrSel(s); },
                  b.branch_id))}
              </View>
              <Text style={st.blockTitle}>Data Scope — Departments</Text>
              <View style={st.wrap}>
                {chip(dpAll, "All Departments", () => setDpAll(!dpAll), "dp-all")}
                {!dpAll && departments.map((d: any) => chip(
                  dpSel.has(d.department_id), d.name,
                  () => { const s = new Set(dpSel); if (s.has(d.department_id)) s.delete(d.department_id); else s.add(d.department_id); setDpSel(s); },
                  d.department_id))}
              </View>
              <Pressable style={[st.btn, { marginTop: 8 }]} onPress={() => void saveScope()} testID="rp-save-scope">
                <Text style={st.btnTxt}>Save Data Scope</Text>
              </Pressable>
            </View>
          </View>
        ) : null}
      </ScrollView>
      {toast ? (
        <View style={st.toast}><Text style={{ color: "#fff", fontSize: 12.5, textAlign: "center" }}>{toast}</Text></View>
      ) : null}
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  h1: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceTertiary },
  input: {
    flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 10, color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary, fontSize: 13,
  },
  btn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 16, justifyContent: "center", alignItems: "center", minHeight: 44,
  },
  btnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  card: {
    flexDirection: "row", alignItems: "center", gap: 8, padding: 12,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
  },
  name: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  subTxt: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 2 },
  block: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 12, gap: 6, backgroundColor: colors.surfaceSecondary,
  },
  blockTitle: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface, marginTop: 4 },
  mRow: { flexDirection: "row", alignItems: "center", paddingVertical: 5, borderBottomWidth: 1, borderBottomColor: colors.border },
  mHead: { flex: 1, fontSize: 10, fontWeight: "800", color: colors.onSurfaceTertiary, textAlign: "center" },
  mCell: { flex: 1, fontSize: 11.5, color: colors.onSurface },
  mKey: { fontSize: 9, color: colors.onSurfaceTertiary },
  legend: { fontSize: 10.5, color: colors.onSurfaceTertiary, lineHeight: 15 },
  senRow: {
    flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8,
    padding: 10, borderWidth: 1, borderColor: "#FDE68A", borderRadius: radius.md,
    backgroundColor: "#FFFBEB",
  },
  wrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 7, backgroundColor: colors.surface,
  },
  chipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  toast: {
    position: "absolute", bottom: 24, left: 20, right: 20,
    backgroundColor: "#111827", borderRadius: radius.md, padding: 12,
  },
});
