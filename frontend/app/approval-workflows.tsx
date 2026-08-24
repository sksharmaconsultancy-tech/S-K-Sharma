/**
 * Approval Workflow Builder — RBAC Phase 3.
 * Per-module multi-level approval chains (levels = Company Admin or any
 * company staff role). Admin-only (staff cannot see this page).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform, Alert, Switch, TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors } from "@/src/theme";

const toast = (m: string) => (Platform.OS === "web" ? window.alert(m) : Alert.alert("Workflow", m));

export default function ApprovalWorkflows() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const role = user?.role as string;
  const isStaff = !!(user as any)?.is_company_staff;

  const [companyId, setCompanyId] = useState<string>(
    role === "company_admin" ? (user?.company_id || "") : (selectedCompanyId || ""));
  const [loading, setLoading] = useState(true);
  const [modules, setModules] = useState<any[]>([]);
  const [roles, setRoles] = useState<any[]>([]);
  const [wfs, setWfs] = useState<Record<string, any>>({});
  const [addingFor, setAddingFor] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  // Phase B — per-level SLA + condition editor.
  const [settingsFor, setSettingsFor] = useState<string | null>(null);
  const [draft, setDraft] = useState<any[]>([]);
  // Phase C — notification rules + version history state.
  const [notifyDraft, setNotifyDraft] = useState<any>({});
  const [historyFor, setHistoryFor] = useState<string | null>(null);
  const [versions, setVersions] = useState<any[]>([]);

  const openHistory = async (moduleKey: string) => {
    if (historyFor === moduleKey) { setHistoryFor(null); return; }
    try {
      const r = await api<{ versions: any[] }>(
        `/admin/approval-workflows/${moduleKey}/versions?company_id=${companyId}`);
      setVersions(r.versions || []);
      setHistoryFor(moduleKey);
    } catch (e: any) { toast(e?.message || "Failed to load history"); }
  };

  const restoreVersion = async (moduleKey: string, version: number) => {
    if (Platform.OS === "web" && !window.confirm(`Restore version ${version}? The current setup is saved as a new version first.`)) return;
    try {
      await api(`/admin/approval-workflows/${moduleKey}/restore`, {
        method: "POST", body: { company_id: companyId, version },
      });
      toast(`Version ${version} restored.`);
      setHistoryFor(null);
      await load();
    } catch (e: any) { toast(e?.message || "Restore failed"); }
  };

  // Follow the global active-firm picker.
  useEffect(() => {
    if (role !== "company_admin" && selectedCompanyId) setCompanyId(selectedCompanyId);
  }, [selectedCompanyId, role]);
  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    try {
      const r = await api(`/admin/approval-workflows?company_id=${companyId}`);
      setModules(r.modules || []); setRoles(r.roles || []); setWfs(r.workflows || {});
    } catch (e: any) { toast(e?.message || "Failed to load"); }
    finally { setLoading(false); }
  }, [companyId]);
  useEffect(() => { load(); }, [load]);

  // Phase B — preserve SLA + condition when (re)saving level arrays.
  const strip = (ls: any[]) => ls.map((l: any) => ({
    approver_type: l.approver_type, role_id: l.role_id, user_id: l.user_id,
    sla_hours: l.sla_hours, condition: l.condition,
  }));

  // Iter 705 — direct employee approver: search & pick.
  const [empQ, setEmpQ] = useState("");
  const [empResults, setEmpResults] = useState<any[]>([]);
  const searchEmp = async (q: string) => {
    setEmpQ(q);
    if (q.trim().length < 2) { setEmpResults([]); return; }
    try {
      const r = await api<{ employees: any[] }>(
        `/admin/approval-workflows/employee-search?company_id=${companyId}&q=${encodeURIComponent(q.trim())}`);
      setEmpResults(r.employees || []);
    } catch { setEmpResults([]); }
  };

  const save = async (moduleKey: string, levels: any[], enabled: boolean, notify?: any) => {
    setSaving(moduleKey);
    try {
      await api("/admin/approval-workflows", {
        method: "POST",
        body: { company_id: companyId, module: moduleKey, enabled, levels,
                ...(notify ? { notify } : {}) },
      });
      await load();
    } catch (e: any) { toast(e?.message || "Save failed"); }
    finally { setSaving(null); setAddingFor(null); setSettingsFor(null); }
  };

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }
  if (isStaff) {
    // Desktop web: AdminWebShell overlays "Access Denied" while this screen
    // stays mounted — a <Redirect> here would clobber the URL. Render nothing.
    if (Platform.OS === "web") return null;
    return <Redirect href="/" />;
  }

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.hBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Approval Workflow Builder</Text>
          <Text style={s.subtitle}>Multi-level approval chains per module — no coding needed</Text>
        </View>
      </View>
      <ScrollView contentContainerStyle={s.body}>
        {role !== "company_admin" ? (
          <View style={{ marginBottom: 12 }}>
            <CompanyPicker value={companyId} onChange={(v: any) => setCompanyId(v || "")} />
          </View>
        ) : null}
        {!companyId ? <Text style={s.muted}>Select a firm to configure its workflows.</Text> : null}
        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} /> : null}

        {!loading && companyId ? modules.map((m) => {
          const wf = wfs[m.key] || { enabled: false, levels: [] };
          const levels = wf.levels || [];
          return (
            <View key={m.key} style={s.card} testID={`wf-${m.key}`}>
              <View style={s.cardHead}>
                <View style={s.cardIcon}><Ionicons name="git-branch-outline" size={16} color={colors.brandPrimary} /></View>
                <Text style={s.cardTitle}>{m.label}</Text>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Text style={s.muted}>{wf.enabled ? "Enabled" : "Off"}</Text>
                  <Switch
                    value={!!wf.enabled}
                    onValueChange={(v) => save(m.key, strip(levels), v)}
                    trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }}
                    testID={`wf-toggle-${m.key}`}
                  />
                </View>
              </View>

              {/* Chain visual — Phase C: drag & drop level cards to
                  reorder the approval sequence (web canvas). */}
              <View style={s.chain}>
                <View style={[s.node, { backgroundColor: "rgba(100,116,139,0.12)" }]}>
                  <Text style={[s.nodeTxt, { color: "#475569" }]}>Request</Text>
                </View>
                {levels.map((l: any, i: number) => {
                  const nodeInner = (
                    <View style={s.node}>
                      {Platform.OS === "web" ? (
                        <Ionicons name="reorder-three-outline" size={15} color={colors.onSurfaceTertiary} />
                      ) : null}
                      <Text style={s.nodeTxt}>
                        L{l.level} · {l.role_name || "Company Admin"}
                        {l.sla_hours ? ` · ⏱${l.sla_hours}h` : ""}
                        {l.condition?.field ? ` · IF ${l.condition.field} ${l.condition.op} ${l.condition.value}` : ""}
                      </Text>
                      <Pressable hitSlop={8} onPress={() => save(m.key,
                        strip(levels.filter((_: any, j: number) => j !== i)),
                        wf.enabled)} testID={`wf-remove-${m.key}-${i}`}>
                        <Ionicons name="close-circle" size={15} color="#DC2626" />
                      </Pressable>
                    </View>
                  );
                  return (
                    <React.Fragment key={i}>
                      <Ionicons name="arrow-forward" size={14} color={colors.onSurfaceTertiary} />
                      {Platform.OS === "web" ? (
                        <div
                          draggable
                          style={{ cursor: "grab", display: "inline-flex" }}
                          data-testid={`wf-node-${m.key}-${i}`}
                          onDragStart={(e: any) => e.dataTransfer.setData("text/plain", String(i))}
                          onDragOver={(e: any) => e.preventDefault()}
                          onDrop={(e: any) => {
                            e.preventDefault();
                            const from = parseInt(e.dataTransfer.getData("text/plain"), 10);
                            if (Number.isNaN(from) || from === i) return;
                            const arr = strip(levels);
                            const [mv] = arr.splice(from, 1);
                            arr.splice(i, 0, mv);
                            save(m.key, arr, wf.enabled);
                          }}
                        >
                          {nodeInner}
                        </div>
                      ) : nodeInner}
                    </React.Fragment>
                  );
                })}
                <Ionicons name="arrow-forward" size={14} color={colors.onSurfaceTertiary} />
                <View style={[s.node, { backgroundColor: "rgba(5,150,105,0.12)" }]}>
                  <Text style={[s.nodeTxt, { color: "#059669" }]}>Approved</Text>
                </View>
              </View>

              {/* Add level */}
              {addingFor === m.key ? (
                <View style={s.pickWrap}>
                  <Text style={s.muted}>Add approver level:</Text>
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 6 }}>
                    <Pressable style={s.chip} testID={`wf-add-admin-${m.key}`}
                      onPress={() => save(m.key, [...strip(levels), { approver_type: "company_admin" }], true)}>
                      <Text style={s.chipTxt}>Company Admin</Text>
                    </Pressable>
                    {roles.map((r) => (
                      <Pressable key={r.role_id} style={s.chip} testID={`wf-add-${m.key}-${r.name.replace(/\s+/g, "-")}`}
                        onPress={() => save(m.key, [...strip(levels), { approver_type: "company_role", role_id: r.role_id }], true)}>
                        <Text style={s.chipTxt}>{r.name}</Text>
                      </Pressable>
                    ))}
                  </View>
                  {/* Iter 705 — assign a specific employee directly */}
                  <Text style={[s.muted, { marginTop: 10, fontWeight: "700" }]}>…or a specific employee:</Text>
                  <TextInput
                    value={empQ}
                    onChangeText={searchEmp}
                    placeholder="Search employee by name / code…"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    style={s.empSearch}
                    autoCapitalize="none"
                    testID={`wf-emp-search-${m.key}`}
                  />
                  {empResults.length > 0 ? (
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 6 }}>
                      {empResults.map((e) => (
                        <Pressable key={e.user_id} style={s.chip} testID={`wf-add-emp-${m.key}-${e.user_id}`}
                          onPress={() => {
                            setEmpQ(""); setEmpResults([]);
                            save(m.key, [...strip(levels), { approver_type: "employee", user_id: e.user_id }], true);
                          }}>
                          <Text style={s.chipTxt}>👤 {e.name}{e.employee_code ? ` (${e.employee_code})` : ""}</Text>
                        </Pressable>
                      ))}
                    </View>
                  ) : empQ.trim().length >= 2 ? (
                    <Text style={[s.muted, { marginTop: 6 }]}>No matching employee.</Text>
                  ) : null}
                </View>
              ) : (
                <Pressable style={s.addBtn} onPress={() => setAddingFor(m.key)} testID={`wf-add-level-${m.key}`}>
                  {saving === m.key ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : (
                    <><Ionicons name="add" size={14} color={colors.brandPrimary} />
                      <Text style={s.addTxt}>Add Approval Level</Text></>)}
                </Pressable>
              )}
              {/* Phase B — per-level SLA + condition rules */}
              {levels.length > 0 ? (
                settingsFor === m.key ? (
                  <View style={s.pickWrap}>
                    <Text style={[s.muted, { fontWeight: "700" }]}>
                      Level Settings — SLA (hours) auto-escalates overdue requests to the next
                      level; a condition means the level only applies when it matches
                      (e.g. amount &gt; 50000).
                    </Text>
                    {draft.map((l: any, i: number) => (
                      <View key={i} style={s.setRow}>
                        <Text style={s.setLbl}>L{i + 1} · {l.role_name || "Company Admin"}</Text>
                        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                          <Text style={s.muted}>SLA</Text>
                          <TextInput
                            value={String(l.sla_hours || "")}
                            onChangeText={(v) => setDraft((d) => d.map((x, j) =>
                              j === i ? { ...x, sla_hours: v.replace(/[^0-9]/g, "") } : x))}
                            placeholder="0" keyboardType="numeric"
                            style={[s.setInput, { width: 54 }]}
                            testID={`wf-sla-${m.key}-${i}`}
                          />
                          <Text style={s.muted}>h · IF</Text>
                          <TextInput
                            value={l.condition?.field || ""}
                            onChangeText={(v) => setDraft((d) => d.map((x, j) =>
                              j === i ? { ...x, condition: { ...(x.condition || { op: ">" }), field: v } } : x))}
                            placeholder="field (e.g. amount)"
                            style={[s.setInput, { width: 140 }]}
                            testID={`wf-cf-${m.key}-${i}`}
                          />
                          {Platform.OS === "web" ? (
                            <select
                              value={l.condition?.op || ">"}
                              onChange={(e) => {
                                const v = (e.target as HTMLSelectElement).value;
                                setDraft((d) => d.map((x, j) =>
                                  j === i ? { ...x, condition: { ...(x.condition || {}), op: v } } : x));
                              }}
                              style={s.setSelect as any}
                            >
                              {[">", ">=", "<", "<=", "==", "!=", "contains"].map((o) => (
                                <option key={o} value={o}>{o}</option>
                              ))}
                            </select>
                          ) : null}
                          <TextInput
                            value={String(l.condition?.value ?? "")}
                            onChangeText={(v) => setDraft((d) => d.map((x, j) =>
                              j === i ? { ...x, condition: { ...(x.condition || { op: ">" }), value: v } } : x))}
                            placeholder="value"
                            style={[s.setInput, { width: 100 }]}
                            testID={`wf-cv-${m.key}-${i}`}
                          />
                        </View>
                      </View>
                    ))}
                    {/* Phase C — notification rules */}
                    <Text style={[s.muted, { fontWeight: "700", marginTop: 10 }]}>
                      Notification Rules (dashboard bell):
                    </Text>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 4 }}>
                      {[["on_created", "Created → admins"], ["on_approved", "Approved → requester"],
                        ["on_rejected", "Rejected → requester"], ["on_returned", "Returned → requester"],
                        ["on_escalated", "Escalated → requester"]].map(([k, lbl]) => (
                        <Pressable key={k} testID={`wf-nf-${m.key}-${k}`}
                          onPress={() => setNotifyDraft((n: any) => ({ ...n, [k]: !(n[k] ?? true) }))}
                          style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                          <Ionicons
                            name={(notifyDraft[k] ?? true) ? "checkbox" : "square-outline"}
                            size={16}
                            color={(notifyDraft[k] ?? true) ? colors.brandPrimary : colors.onSurfaceTertiary}
                          />
                          <Text style={s.muted}>{lbl}</Text>
                        </Pressable>
                      ))}
                    </View>
                    <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
                      <Pressable style={s.saveBtn} testID={`wf-save-settings-${m.key}`}
                        onPress={() => save(m.key, draft.map((l: any) => ({
                          approver_type: l.approver_type, role_id: l.role_id,
                          sla_hours: parseInt(l.sla_hours || "0", 10) || 0,
                          condition: l.condition?.field?.trim() ? l.condition : undefined,
                        })), wf.enabled, notifyDraft)}>
                        <Text style={s.saveBtnTxt}>Save Settings</Text>
                      </Pressable>
                      <Pressable style={s.addBtn} onPress={() => setSettingsFor(null)}>
                        <Text style={s.addTxt}>Cancel</Text>
                      </Pressable>
                    </View>
                  </View>
                ) : (
                  <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                    <Pressable style={s.addBtn} testID={`wf-settings-${m.key}`}
                      onPress={() => {
                        setSettingsFor(m.key);
                        setDraft(levels.map((l: any) => ({ ...l })));
                        setNotifyDraft({ ...(wf.notify || {}) });
                      }}>
                      <Ionicons name="options-outline" size={14} color={colors.brandPrimary} />
                      <Text style={s.addTxt}>Level Settings (SLA · Conditions · Notifications)</Text>
                    </Pressable>
                    <Pressable style={s.addBtn} testID={`wf-history-${m.key}`}
                      onPress={() => openHistory(m.key)}>
                      <Ionicons name="time-outline" size={14} color={colors.brandPrimary} />
                      <Text style={s.addTxt}>History{wf.version ? ` (v${wf.version})` : ""}</Text>
                    </Pressable>
                  </View>
                )
              ) : null}
              {/* Phase C — version history + restore */}
              {historyFor === m.key ? (
                <View style={s.pickWrap}>
                  <Text style={[s.muted, { fontWeight: "700" }]}>Saved versions (newest first):</Text>
                  {versions.length === 0 ? (
                    <Text style={s.muted}>No earlier versions yet — versions are saved every time the workflow changes.</Text>
                  ) : versions.map((v) => (
                    <View key={v.version} style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8 }}>
                      <Text style={[s.muted, { flex: 1 }]}>
                        v{v.version} · {(v.levels || []).map((l: any) =>
                          `${l.role_name}${l.sla_hours ? ` ⏱${l.sla_hours}h` : ""}`).join(" → ") || "no levels"}
                        {" · "}{String(v.saved_at || "").slice(0, 16).replace("T", " ")}
                        {v.saved_by_name ? ` by ${v.saved_by_name}` : ""}
                      </Text>
                      <Pressable style={s.saveBtn} testID={`wf-restore-${m.key}-${v.version}`}
                        onPress={() => restoreVersion(m.key, v.version)}>
                        <Text style={s.saveBtnTxt}>Restore</Text>
                      </Pressable>
                    </View>
                  ))}
                </View>
              ) : null}
              {m.key !== "advance" ? (
                <Text style={[s.muted, { marginTop: 8 }]}>Currently enforced for Advance issuance; other modules coming next.</Text>
              ) : null}
            </View>
          );
        }) : null}
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surfaceSecondary, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  hBtn: { width: 38, height: 38, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceTertiary },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 1 },
  body: { padding: 16, width: "100%", maxWidth: 900, alignSelf: "center" },
  muted: { fontSize: 12, color: colors.onSurfaceTertiary },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 16, padding: 14,
    borderWidth: 1, borderColor: colors.border, marginBottom: 12,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  cardIcon: { width: 30, height: 30, borderRadius: 9, backgroundColor: "rgba(37,99,235,0.1)", alignItems: "center", justifyContent: "center" },
  cardTitle: { flex: 1, fontSize: 14.5, fontWeight: "800", color: colors.onSurface },
  chain: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap", marginTop: 12 },
  node: {
    flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: "rgba(37,99,235,0.1)",
    borderRadius: 10, paddingHorizontal: 10, paddingVertical: 6,
  },
  nodeTxt: { fontSize: 11.5, fontWeight: "800", color: colors.brandPrimary },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, alignSelf: "flex-start",
    borderWidth: 1, borderColor: "rgba(37,99,235,0.35)", borderRadius: 10,
    paddingHorizontal: 12, height: 32, marginTop: 12, backgroundColor: "rgba(37,99,235,0.06)",
  },
  addTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  pickWrap: { marginTop: 12, backgroundColor: colors.surface, borderRadius: 12, padding: 10, borderWidth: 1, borderColor: colors.border },
  chip: {
    paddingHorizontal: 12, height: 32, borderRadius: 16, backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center",
  },
  chipTxt: { fontSize: 12, fontWeight: "600", color: colors.onSurfaceSecondary },
  empSearch: {
    marginTop: 6, borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 12.5,
    color: colors.onSurface, backgroundColor: colors.surfaceSecondary,
  },
  setRow: { marginTop: 10, gap: 4 },
  setLbl: { fontSize: 12, fontWeight: "800", color: colors.onSurface },
  setInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 8, paddingVertical: 6, fontSize: 12.5,
    color: colors.onSurface, backgroundColor: colors.surfaceSecondary,
  },
  setSelect: {
    padding: 6, borderRadius: 8, borderColor: colors.border, borderWidth: 1,
    fontSize: 12.5, backgroundColor: colors.surfaceSecondary, color: colors.onSurface,
  },
  saveBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: 10,
    paddingHorizontal: 14, height: 32, alignItems: "center", justifyContent: "center",
  },
  saveBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
});
