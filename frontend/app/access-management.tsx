/**
 * Iter 286 — Access & Workflow Management (Phase A).
 *
 * Single unified module merging Roles & Permissions + Workflow Builder:
 *   Dashboard · Roles · Users · Permission Matrix · Workflow Builder ·
 *   Audit Logs.  Engines stay separate on the backend
 *   (company_roles / approvals_engine / access_management).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  ActivityIndicator, TextInput, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "../src/api/client";
import { colors } from "../src/theme";

type Tab = "dashboard" | "roles" | "users" | "matrix" | "workflows" | "activity" | "audit";
type Company = { company_id: string; name: string };
type Role = { role_id: string; name: string; permissions: string[]; staff_count?: number };
type CatalogRow = { module: string; read: string; write: string };
type Staff = {
  user_id: string; name: string; email?: string | null;
  company_role_id?: string | null; role_name?: string; disabled?: boolean;
  linked_employee?: boolean;
};

const TABS: { key: Tab; label: string; icon: any }[] = [
  { key: "dashboard", label: "Dashboard", icon: "speedometer-outline" },
  { key: "roles", label: "Roles", icon: "key-outline" },
  { key: "users", label: "Users", icon: "people-outline" },
  { key: "matrix", label: "Permission Matrix", icon: "grid-outline" },
  { key: "workflows", label: "Workflow Builder", icon: "git-branch-outline" },
  { key: "activity", label: "Activity Monitor", icon: "pulse-outline" },
  { key: "audit", label: "Audit Logs", icon: "document-text-outline" },
];

function StatCard({ label, value, tone }: { label: string; value: any; tone?: string }) {
  return (
    <View style={[st.statCard, tone ? { borderLeftColor: tone, borderLeftWidth: 4 } : null]}>
      <Text style={st.statVal}>{value ?? "—"}</Text>
      <Text style={st.statLbl}>{label}</Text>
    </View>
  );
}

export default function AccessManagementScreen() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [stats, setStats] = useState<any>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [catalog, setCatalog] = useState<CatalogRow[]>([]);
  const [staff, setStaff] = useState<Staff[]>([]);
  const [wf, setWf] = useState<any>(null);
  const [audit, setAudit] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [newRole, setNewRole] = useState("");
  const [newStaff, setNewStaff] = useState({ name: "", email: "", password: "", role_id: "" });
  const [showAddStaff, setShowAddStaff] = useState(false);
  // Phase C — live activity monitor (auto-refresh every 10s while open).
  const [activity, setActivity] = useState<any>(null);

  useEffect(() => {
    if (tab !== "activity" || !companyId) return;
    let alive = true;
    const tick = async () => {
      try {
        const r = await api<any>(`/admin/access-management/activity?company_id=${companyId}`);
        if (alive) setActivity(r);
      } catch { /* transient */ }
    };
    void tick();
    const iv = setInterval(tick, 10000);
    return () => { alive = false; clearInterval(iv); };
  }, [tab, companyId]);

  useEffect(() => {
    api<{ companies: Company[] }>("/companies").then((r) => {
      setCompanies(r.companies || []);
      if (r.companies?.length) setCompanyId((p) => p || r.companies[0].company_id);
    }).catch(() => {});
    api<{ catalog: CatalogRow[] }>("/admin/company-roles/catalog")
      .then((r) => setCatalog(r.catalog || [])).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      const [s, r, u, w, a] = await Promise.all([
        api<any>(`/admin/access-management/stats?company_id=${companyId}`),
        api<{ roles: Role[] }>(`/admin/company-roles?company_id=${companyId}`),
        api<{ staff: Staff[] }>(`/admin/company-staff?company_id=${companyId}`),
        api<any>(`/admin/approval-workflows?company_id=${companyId}`),
        api<{ logs: any[] }>(`/admin/access-management/audit?company_id=${companyId}`),
      ]);
      setStats(s); setRoles(r.roles || []); setStaff(u.staff || []);
      setWf(w); setAudit(a.logs || []);
    } catch (e: any) {
      setMsg(e?.message || "Failed to load");
    } finally { setLoading(false); }
  }, [companyId]);
  useEffect(() => { void load(); }, [load]);

  const togglePerm = async (role: Role, key: string) => {
    const has = role.permissions.includes(key);
    const perms = has
      ? role.permissions.filter((p) => p !== key)
      : [...role.permissions, key];
    setRoles((rs) => rs.map((r) => (r.role_id === role.role_id ? { ...r, permissions: perms } : r)));
    try {
      await api(`/admin/company-roles/${role.role_id}`, { method: "PATCH", body: { permissions: perms } });
    } catch (e: any) {
      setMsg(e?.message || "Save failed");
      void load();
    }
  };

  const createRole = async () => {
    if (!newRole.trim()) return;
    try {
      await api("/admin/company-roles", {
        method: "POST", body: { company_id: companyId, name: newRole.trim(), permissions: [] },
      });
      setNewRole(""); setMsg("Role created"); void load();
    } catch (e: any) { setMsg(e?.message || "Create failed"); }
  };

  const seedDefaults = async () => {
    try {
      const r = await api<{ created: number }>("/admin/company-roles", {
        method: "POST", body: { company_id: companyId, seed_defaults: true },
      });
      setMsg(`${r.created} default role(s) created`); void load();
    } catch (e: any) { setMsg(e?.message || "Seed failed"); }
  };

  const deleteRole = async (r: Role) => {
    if (Platform.OS === "web" && !window.confirm(`Delete role "${r.name}"?`)) return;
    try {
      await api(`/admin/company-roles/${r.role_id}`, { method: "DELETE" });
      setMsg("Role deleted"); void load();
    } catch (e: any) { setMsg(e?.message || "Delete failed"); }
  };

  const setStaffRole = async (u: Staff, role_id: string) => {
    try {
      await api(`/admin/company-staff/${u.user_id}`, { method: "PATCH", body: { role_id } });
      setMsg(`${u.name} → role updated`); void load();
    } catch (e: any) { setMsg(e?.message || "Update failed"); }
  };

  const toggleStaffDisabled = async (u: Staff) => {
    try {
      await api(`/admin/company-staff/${u.user_id}`, { method: "PATCH", body: { disabled: !u.disabled } });
      void load();
    } catch (e: any) { setMsg(e?.message || "Update failed"); }
  };

  const createStaff = async () => {
    const p = newStaff;
    if (!p.name.trim() || !p.email.trim() || !p.role_id) {
      setMsg("Name, email and role are required"); return;
    }
    try {
      await api("/admin/company-staff", {
        method: "POST",
        body: { company_id: companyId, ...p, password: p.password || undefined },
      });
      setNewStaff({ name: "", email: "", password: "", role_id: "" });
      setShowAddStaff(false); setMsg("Staff user created"); void load();
    } catch (e: any) { setMsg(e?.message || "Create failed"); }
  };

  const t = stats?.totals || {};

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.surfaceSecondary }} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="awm-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={st.headerTitle}>Access & Workflow Management</Text>
        <Pressable onPress={() => void load()} hitSlop={10} testID="awm-refresh">
          <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>

      {/* Firm + tabs */}
      <View style={st.topBar}>
        {Platform.OS === "web" ? (
          <select
            value={companyId}
            onChange={(e) => setCompanyId((e.target as HTMLSelectElement).value)}
            style={st.firmSelect as any}
            data-testid="awm-firm-select"
          >
            {companies.map((c) => (
              <option key={c.company_id} value={c.company_id}>{c.name}</option>
            ))}
          </select>
        ) : null}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>
          {TABS.map((tb) => (
            <Pressable key={tb.key} onPress={() => setTab(tb.key)}
              style={[st.tabBtn, tab === tb.key && st.tabBtnOn]}
              testID={`awm-tab-${tb.key}`}>
              <Ionicons name={tb.icon} size={14}
                color={tab === tb.key ? "#fff" : colors.onSurfaceSecondary} />
              <Text style={[st.tabTxt, tab === tb.key && { color: "#fff" }]}>{tb.label}</Text>
            </Pressable>
          ))}
        </ScrollView>
      </View>

      {msg ? (
        <Pressable onPress={() => setMsg(null)} style={st.msgBar}>
          <Text style={st.msgTxt}>{msg} (tap to dismiss)</Text>
        </Pressable>
      ) : null}

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 16, gap: 12 }}>
        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 24 }} /> : null}

        {/* ── DASHBOARD ─────────────────────────────────────────────── */}
        {tab === "dashboard" && stats ? (
          <>
            <View style={st.statGrid}>
              <StatCard label="Total Roles" value={t.roles} tone="#2563EB" />
              <StatCard label="Staff Users" value={t.staff_users} tone="#7C3AED" />
              <StatCard label="Employees" value={t.employees} tone="#0891B2" />
              <StatCard label="Active Workflows" value={`${t.active_workflows}/${t.workflows}`} tone="#16A34A" />
              <StatCard label="Pending Approvals" value={t.pending_approvals} tone="#D97706" />
              <StatCard label="Rejected Requests" value={t.rejected_requests} tone="#DC2626" />
              <StatCard label="Pending Onboarding" value={t.pending_onboarding} tone="#DB2777" />
            </View>
            <View style={st.card}>
              <Text style={st.cardTitle}>Recently Modified Workflows</Text>
              {(stats.recent_workflows || []).length === 0 ? (
                <Text style={st.hint}>No workflows configured yet.</Text>
              ) : stats.recent_workflows.map((w: any, i: number) => (
                <Text key={i} style={st.listLine}>
                  • {w.module} — {w.levels} level(s), {w.enabled ? "ENABLED" : "disabled"}
                  {w.updated_at ? ` · ${String(w.updated_at).slice(0, 16).replace("T", " ")}` : ""}
                </Text>
              ))}
            </View>
            <View style={st.card}>
              <Text style={st.cardTitle}>Recent Permission / Access Changes</Text>
              {(stats.recent_audit || []).length === 0 ? (
                <Text style={st.hint}>No changes recorded yet.</Text>
              ) : stats.recent_audit.map((a: any) => (
                <Text key={a.audit_id} style={st.listLine}>
                  • {a.detail} — {a.by_name || a.by} · {String(a.at || "").slice(0, 16).replace("T", " ")}
                </Text>
              ))}
            </View>
          </>
        ) : null}

        {/* ── ROLES ─────────────────────────────────────────────────── */}
        {tab === "roles" ? (
          <View style={st.card}>
            <Text style={st.cardTitle}>{roles.length} role(s)</Text>
            <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
              <TextInput
                value={newRole} onChangeText={setNewRole}
                placeholder="New role name (e.g. Auditor)"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={[st.input, { flex: 1, minWidth: 220 }]}
                testID="awm-new-role"
              />
              <Pressable onPress={createRole} style={st.primaryBtn} testID="awm-create-role">
                <Text style={st.primaryBtnTxt}>Create Role</Text>
              </Pressable>
              <Pressable onPress={seedDefaults} style={st.ghostBtn} testID="awm-seed-roles">
                <Text style={st.ghostBtnTxt}>Seed Default Roles</Text>
              </Pressable>
            </View>
            {roles.map((r) => (
              <View key={r.role_id} style={st.roleRow}>
                <View style={{ flex: 1 }}>
                  <Text style={st.roleName}>{r.name}</Text>
                  <Text style={st.hint}>
                    {r.permissions.length} permission(s) · {r.staff_count || 0} user(s)
                  </Text>
                </View>
                <Pressable onPress={() => setTab("matrix")} style={st.smallBtn}>
                  <Text style={st.smallBtnTxt}>Edit in Matrix</Text>
                </Pressable>
                <Pressable onPress={() => deleteRole(r)} hitSlop={8} testID={`awm-del-role-${r.role_id}`}>
                  <Ionicons name="trash-outline" size={17} color="#DC2626" />
                </Pressable>
              </View>
            ))}
          </View>
        ) : null}

        {/* ── USERS ─────────────────────────────────────────────────── */}
        {tab === "users" ? (
          <View style={st.card}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text style={st.cardTitle}>{staff.length} staff user(s)</Text>
              <Pressable onPress={() => setShowAddStaff((v) => !v)} style={st.primaryBtn} testID="awm-add-staff">
                <Text style={st.primaryBtnTxt}>{showAddStaff ? "Close" : "+ Add User"}</Text>
              </Pressable>
            </View>
            {showAddStaff ? (
              <View style={{ gap: 8 }}>
                <TextInput value={newStaff.name} onChangeText={(v) => setNewStaff((s) => ({ ...s, name: v }))}
                  placeholder="Full name" placeholderTextColor={colors.onSurfaceTertiary} style={st.input} />
                <TextInput value={newStaff.email} onChangeText={(v) => setNewStaff((s) => ({ ...s, email: v.toLowerCase() }))}
                  placeholder="Email (login id)" autoCapitalize="none"
                  placeholderTextColor={colors.onSurfaceTertiary} style={st.input} />
                <TextInput value={newStaff.password} onChangeText={(v) => setNewStaff((s) => ({ ...s, password: v }))}
                  placeholder="Password (blank = link existing employee login)"
                  placeholderTextColor={colors.onSurfaceTertiary} style={st.input} secureTextEntry />
                {Platform.OS === "web" ? (
                  <select value={newStaff.role_id}
                    onChange={(e) => setNewStaff((s) => ({ ...s, role_id: (e.target as HTMLSelectElement).value }))}
                    style={st.firmSelect as any} data-testid="awm-new-staff-role">
                    <option value="">— pick role —</option>
                    {roles.map((r) => <option key={r.role_id} value={r.role_id}>{r.name}</option>)}
                  </select>
                ) : null}
                <Pressable onPress={createStaff} style={st.primaryBtn} testID="awm-save-staff">
                  <Text style={st.primaryBtnTxt}>Create Staff User</Text>
                </Pressable>
              </View>
            ) : null}
            {staff.map((u) => (
              <View key={u.user_id} style={st.roleRow}>
                <View style={{ flex: 1 }}>
                  <Text style={st.roleName}>
                    {u.name}{u.disabled ? "  (disabled)" : ""}{u.linked_employee ? "  🔗" : ""}
                  </Text>
                  <Text style={st.hint}>{u.email || "—"}</Text>
                </View>
                {Platform.OS === "web" ? (
                  <select
                    value={u.company_role_id || ""}
                    onChange={(e) => setStaffRole(u, (e.target as HTMLSelectElement).value)}
                    style={{ ...(st.firmSelect as any), maxWidth: 180, padding: 6 }}
                    data-testid={`awm-staff-role-${u.user_id}`}
                  >
                    <option value="" disabled>— role —</option>
                    {roles.map((r) => <option key={r.role_id} value={r.role_id}>{r.name}</option>)}
                  </select>
                ) : (
                  <Text style={st.hint}>{u.role_name}</Text>
                )}
                <Pressable onPress={() => toggleStaffDisabled(u)} style={st.smallBtn}>
                  <Text style={st.smallBtnTxt}>{u.disabled ? "Enable" : "Disable"}</Text>
                </Pressable>
              </View>
            ))}
          </View>
        ) : null}

        {/* ── PERMISSION MATRIX ─────────────────────────────────────── */}
        {tab === "matrix" ? (
          <View style={st.card}>
            <Text style={st.cardTitle}>Permission Matrix — modules × roles (R = view, W = add/edit)</Text>
            {roles.length === 0 ? (
              <Text style={st.hint}>Create roles first (Roles tab).</Text>
            ) : (
              <ScrollView horizontal showsHorizontalScrollIndicator>
                <View>
                  <View style={st.mxRow}>
                    <Text style={[st.mxModule, st.mxHead]}>Module</Text>
                    {roles.map((r) => (
                      <Text key={r.role_id} style={[st.mxCell, st.mxHead]} numberOfLines={2}>
                        {r.name}
                      </Text>
                    ))}
                  </View>
                  {catalog.map((c) => (
                    <View key={c.module} style={st.mxRow}>
                      <Text style={st.mxModule}>{c.module}</Text>
                      {roles.map((r) => (
                        <View key={r.role_id} style={[st.mxCell, { flexDirection: "row", gap: 6, justifyContent: "center" }]}>
                          {(["read", "write"] as const).map((kind) => {
                            const key = c[kind];
                            const on = r.permissions.includes(key);
                            return (
                              <Pressable key={kind} onPress={() => togglePerm(r, key)}
                                style={[st.permDot, on && (kind === "read" ? st.permDotR : st.permDotW)]}
                                testID={`awm-mx-${r.role_id}-${key}`}>
                                <Text style={[st.permDotTxt, on && { color: "#fff" }]}>
                                  {kind === "read" ? "R" : "W"}
                                </Text>
                              </Pressable>
                            );
                          })}
                        </View>
                      ))}
                    </View>
                  ))}
                </View>
              </ScrollView>
            )}
            <Text style={st.hint}>Changes save instantly and apply on the staff member&apos;s next screen load.</Text>
          </View>
        ) : null}

        {/* ── WORKFLOW BUILDER ──────────────────────────────────────── */}
        {tab === "workflows" ? (
          <View style={st.card}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text style={st.cardTitle}>Approval Workflows</Text>
              <Pressable onPress={() => router.push("/approval-workflows")}
                style={st.primaryBtn} testID="awm-open-builder">
                <Text style={st.primaryBtnTxt}>Open Workflow Builder →</Text>
              </Pressable>
            </View>
            {(wf?.modules || []).map((m: any) => {
              const w = wf?.workflows?.[m.key];
              return (
                <View key={m.key} style={st.roleRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={st.roleName}>{m.label}</Text>
                    <Text style={st.hint}>
                      {w
                        ? `${(w.levels || []).length} level(s) — ${(w.levels || [])
                            .map((l: any) => l.role_name || "Company Admin").join(" → ") || "—"}`
                        : "No chain configured (direct approval)"}
                    </Text>
                  </View>
                  <View style={[st.chip, { backgroundColor: w?.enabled ? "#DCFCE7" : "#F1F5F9" }]}>
                    <Text style={[st.chipTxt, { color: w?.enabled ? "#15803D" : "#64748B" }]}>
                      {w?.enabled ? "ENABLED" : "OFF"}
                    </Text>
                  </View>
                </View>
              );
            })}
          </View>
        ) : null}

        {/* ── ACTIVITY MONITOR (Phase C) ────────────────────────────── */}
        {tab === "activity" ? (
          <>
            <View style={st.statGrid}>
              <StatCard label="Users Online (45 min)" value={activity?.online_count} tone="#16A34A" />
              <StatCard label="Pending Approvals" value={activity?.pending_approvals} tone="#D97706" />
              <StatCard label="Escalated (pending)" value={activity?.escalated_pending} tone="#DC2626" />
              <StatCard label="SLA Breached" value={activity?.sla_breached_pending} tone="#B91C1C" />
              <StatCard label="Running Workflows" value={activity?.running_workflows} tone="#2563EB" />
            </View>
            <View style={st.card}>
              <Text style={st.cardTitle}>
                Live — logged-in users {activity?.as_of ? `(as of ${String(activity.as_of).slice(11, 19)} UTC, refreshes every 10s)` : ""}
              </Text>
              {!activity ? (
                <ActivityIndicator color={colors.brandPrimary} />
              ) : (activity.online_users || []).length === 0 ? (
                <Text style={st.hint}>No users active in the last 45 minutes.</Text>
              ) : activity.online_users.map((u: any) => (
                <View key={u.user_id} style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 }}>
                  <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: "#16A34A" }} />
                  <Text style={st.listLine}>
                    {u.name}{u.employee_code ? ` (#${u.employee_code})` : ""} — {u.is_company_staff ? "staff" : u.role}
                    {" · last active "}{String(u.last_active || "").slice(11, 16)} UTC
                  </Text>
                </View>
              ))}
            </View>
            <View style={st.card}>
              <Text style={st.cardTitle}>Recent Permission Changes</Text>
              {(activity?.recent_permission_changes || []).length === 0 ? (
                <Text style={st.hint}>No recent changes.</Text>
              ) : activity.recent_permission_changes.map((a: any) => (
                <Text key={a.audit_id} style={st.listLine}>
                  • {a.detail} — {a.by_name || a.by} · {String(a.at || "").slice(0, 16).replace("T", " ")}
                </Text>
              ))}
            </View>
          </>
        ) : null}

        {/* ── AUDIT LOGS ────────────────────────────────────────────── */}
        {tab === "audit" ? (
          <View style={st.card}>
            <Text style={st.cardTitle}>{audit.length} audit event(s) — roles, permissions, workflows & onboarding decisions</Text>
            {audit.length === 0 ? (
              <Text style={st.hint}>No events yet. Role/permission/workflow changes and onboarding decisions appear here.</Text>
            ) : audit.map((a) => (
              <View key={a.audit_id} style={st.auditRow}>
                <View style={[st.chip, {
                  backgroundColor: a.source === "onboarding" ? "#FEF3C7" : "#DBEAFE",
                }]}>
                  <Text style={[st.chipTxt, {
                    color: a.source === "onboarding" ? "#92400E" : "#1D4ED8",
                  }]}>
                    {(a.action || "").replace(/_/g, " ").toUpperCase()}
                  </Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={st.listLine}>{a.detail}</Text>
                  <Text style={st.hint}>
                    {a.by_name || a.by} ({a.by_role || "—"}) · {String(a.at || "").slice(0, 19).replace("T", " ")}
                  </Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}
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
  topBar: {
    padding: 12, gap: 10, backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  firmSelect: {
    padding: 9, borderRadius: 8, borderColor: colors.border, borderWidth: 1,
    fontSize: 13.5, width: "100%", maxWidth: 380,
    backgroundColor: colors.surface, color: colors.onSurface,
  },
  tabBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 18,
    borderWidth: 1, borderColor: colors.border,
  },
  tabBtnOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  msgBar: {
    backgroundColor: "#ECFDF5", padding: 9, borderBottomWidth: 1, borderBottomColor: "#A7F3D0",
  },
  msgTxt: { color: "#065F46", fontSize: 12.5, fontWeight: "600" },
  statGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  statCard: {
    backgroundColor: colors.surface, borderRadius: 10, padding: 14,
    borderWidth: 1, borderColor: colors.border, minWidth: 150, flexGrow: 1,
  },
  statVal: { fontSize: 22, fontWeight: "900", color: colors.onSurface },
  statLbl: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 2 },
  card: {
    backgroundColor: colors.surface, borderRadius: 12, padding: 14,
    borderWidth: 1, borderColor: colors.border, gap: 10,
  },
  cardTitle: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface },
  hint: { fontSize: 12, color: colors.onSurfaceTertiary, lineHeight: 17 },
  listLine: { fontSize: 12.5, color: colors.onSurface, lineHeight: 19 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 9, fontSize: 13.5,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  primaryBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 14, paddingVertical: 9, alignSelf: "flex-start",
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  ghostBtn: {
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 14, paddingVertical: 9,
  },
  ghostBtnTxt: { color: colors.brandPrimary, fontWeight: "800", fontSize: 12.5 },
  smallBtn: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 6,
  },
  smallBtnTxt: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  roleRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    borderTopWidth: 1, borderTopColor: colors.divider, paddingVertical: 10,
  },
  roleName: { fontSize: 13.5, fontWeight: "700", color: colors.onSurface },
  chip: { borderRadius: 10, paddingHorizontal: 8, paddingVertical: 3 },
  chipTxt: { fontSize: 10, fontWeight: "800" },
  mxRow: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.divider },
  mxModule: {
    width: 190, fontSize: 12, color: colors.onSurface, fontWeight: "600",
    paddingVertical: 9, paddingRight: 8,
  },
  mxCell: { width: 110, paddingVertical: 7, alignItems: "center", fontSize: 11.5, color: colors.onSurface },
  mxHead: { fontWeight: "800", color: colors.onSurfaceSecondary, textAlign: "center" },
  permDot: {
    width: 26, height: 26, borderRadius: 13, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  permDotR: { backgroundColor: "#0891B2", borderColor: "#0891B2" },
  permDotW: { backgroundColor: "#16A34A", borderColor: "#16A34A" },
  permDotTxt: { fontSize: 10.5, fontWeight: "800", color: colors.onSurfaceTertiary },
  auditRow: {
    flexDirection: "row", gap: 10, alignItems: "flex-start",
    borderTopWidth: 1, borderTopColor: colors.divider, paddingVertical: 8,
  },
});
