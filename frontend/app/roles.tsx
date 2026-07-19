/**
 * Roles & Permissions — RBAC Phase 1.
 *
 * Company-level staff roles (HR Manager, Payroll Manager, ...) with a
 * checkbox permission matrix (module × View/Manage), plus Staff Users
 * management (create login, assign role, lock/unlock, reset password).
 * Staff log in through the SAME employer (AWP) login page.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Modal, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { confirmYesNo } from "@/src/utils/confirm";
import { colors } from "@/src/theme";

const toast = (m: string) => (Platform.OS === "web" ? window.alert(m) : Alert.alert("Roles", m));

export default function RolesScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const role = user?.role as string;
  const isStaff = !!(user as any)?.is_company_staff;

  const [companyId, setCompanyId] = useState<string>(
    role === "company_admin" ? (user?.company_id || "") : (selectedCompanyId || ""));
  const [loading, setLoading] = useState(true);
  const [roles, setRoles] = useState<any[]>([]);
  const [staff, setStaff] = useState<any[]>([]);
  const [catalog, setCatalog] = useState<any[]>([]);

  // role editor
  const [editRole, setEditRole] = useState<any>(null); // {role_id?, name, permissions:Set}
  const [saving, setSaving] = useState(false);

  // staff form
  const [staffForm, setStaffForm] = useState<any>(null); // {name,email,phone,password,role_id}

  const q = companyId ? `company_id=${companyId}` : "";
  // Follow the global active-firm picker.
  useEffect(() => {
    if (role !== "company_admin" && selectedCompanyId) setCompanyId(selectedCompanyId);
  }, [selectedCompanyId, role]);
  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    try {
      const [r, st, c] = await Promise.all([
        api(`/admin/company-roles?${q}`),
        api(`/admin/company-staff?${q}`),
        api("/admin/company-roles/catalog"),
      ]);
      setRoles(r.roles || []); setStaff(st.staff || []); setCatalog(c.catalog || []);
    } catch (e: any) { toast(e?.message || "Failed to load"); }
    finally { setLoading(false); }
  }, [companyId, q]);
  useEffect(() => { load(); }, [load]);

  const seedDefaults = async () => {
    try {
      const r = await api("/admin/company-roles", { method: "POST", body: { company_id: companyId, seed_defaults: true } });
      toast(`${r.created} default role(s) created.`);
      await load();
    } catch (e: any) { toast(e?.message || "Failed"); }
  };

  const saveRole = async () => {
    if (!editRole) return;
    const perms = Array.from(editRole.permissions) as string[];
    if (!editRole.name?.trim()) return toast("Enter a role name.");
    setSaving(true);
    try {
      if (editRole.role_id) {
        await api(`/admin/company-roles/${editRole.role_id}`, { method: "PATCH", body: { name: editRole.name, permissions: perms } });
      } else {
        await api("/admin/company-roles", { method: "POST", body: { company_id: companyId, name: editRole.name, permissions: perms } });
      }
      setEditRole(null); await load();
    } catch (e: any) { toast(e?.message || "Save failed"); }
    finally { setSaving(false); }
  };

  const deleteRole = async (r: any) => {
    if (!(await confirmYesNo(`Delete role "${r.name}"?`))) return;
    try { await api(`/admin/company-roles/${r.role_id}`, { method: "DELETE" }); await load(); }
    catch (e: any) { toast(e?.message || "Delete failed"); }
  };

  const saveStaff = async () => {
    const f = staffForm;
    if (!f?.name?.trim() || !f?.email?.trim()) return toast("Name and email are required.");
    if (!f.role_id) return toast("Pick a role.");
    if (!f.user_id && !f.password) return toast("Set a password.");
    setSaving(true);
    try {
      if (f.user_id) {
        const body: any = { role_id: f.role_id, name: f.name };
        if (f.password) body.password = f.password;
        await api(`/admin/company-staff/${f.user_id}`, { method: "PATCH", body });
      } else {
        await api("/admin/company-staff", {
          method: "POST",
          body: { company_id: companyId, name: f.name, email: f.email, phone: f.phone, password: f.password, role_id: f.role_id },
        });
      }
      setStaffForm(null); await load();
      toast("Saved. Staff can now log in on the Employer login page.");
    } catch (e: any) { toast(e?.message || "Save failed"); }
    finally { setSaving(false); }
  };

  const toggleLock = async (u: any) => {
    try { await api(`/admin/company-staff/${u.user_id}`, { method: "PATCH", body: { disabled: !u.disabled } }); await load(); }
    catch (e: any) { toast(e?.message || "Failed"); }
  };

  const deleteStaff = async (u: any) => {
    if (!(await confirmYesNo(`Delete staff login for ${u.name}?`))) return;
    try { await api(`/admin/company-staff/${u.user_id}`, { method: "DELETE" }); await load(); }
    catch (e: any) { toast(e?.message || "Failed"); }
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

  const togglePerm = (key: string) => {
    const next = new Set(editRole.permissions);
    if (next.has(key)) next.delete(key); else next.add(key);
    setEditRole({ ...editRole, permissions: next });
  };

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.hBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Roles &amp; Permissions</Text>
          <Text style={s.subtitle}>Company staff roles · permission matrix · staff logins</Text>
        </View>
        <Pressable style={s.newBtn} onPress={() => setEditRole({ name: "", permissions: new Set() })} testID="new-role">
          <Ionicons name="add" size={16} color="#fff" />
          <Text style={s.newBtnTxt}>New Role</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={s.body}>
        {role !== "company_admin" ? (
          <View style={{ marginBottom: 12 }}>
            <CompanyPicker value={companyId} onChange={(v: any) => setCompanyId(v || "")} />
          </View>
        ) : null}
        {!companyId ? <Text style={s.muted}>Select a firm to manage its roles.</Text> : null}
        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} /> : null}

        {!loading && companyId ? (
          <View>
            {/* Roles */}
            <View style={s.secHead}>
              <Text style={s.secTitle}>Roles ({roles.length})</Text>
              {roles.length === 0 ? (
                <Pressable style={s.seedBtn} onPress={seedDefaults} testID="seed-defaults">
                  <Ionicons name="sparkles-outline" size={14} color={colors.brandPrimary} />
                  <Text style={s.seedTxt}>Create 6 Standard Roles</Text>
                </Pressable>
              ) : null}
            </View>
            <View style={s.cardsWrap}>
              {roles.map((r) => (
                <View key={r.role_id} style={s.roleCard} testID={`role-${r.name.replace(/\s+/g, "-")}`}>
                  <View style={s.roleTop}>
                    <View style={s.roleIcon}><Ionicons name="key-outline" size={16} color={colors.brandPrimary} /></View>
                    <Text style={s.roleName}>{r.name}</Text>
                  </View>
                  <Text style={s.roleMeta}>{r.permissions.length} permission(s) · {r.staff_count} user(s)</Text>
                  <View style={s.roleActions}>
                    <Pressable style={s.actBtn} onPress={() => setEditRole({ ...r, permissions: new Set(r.permissions) })} testID={`edit-role-${r.name.replace(/\s+/g, "-")}`}>
                      <Ionicons name="create-outline" size={13} color={colors.brandPrimary} />
                      <Text style={[s.actTxt, { color: colors.brandPrimary }]}>Edit Matrix</Text>
                    </Pressable>
                    <Pressable style={s.actBtn} onPress={() => deleteRole(r)}>
                      <Ionicons name="trash-outline" size={13} color="#DC2626" />
                      <Text style={[s.actTxt, { color: "#DC2626" }]}>Delete</Text>
                    </Pressable>
                  </View>
                </View>
              ))}
            </View>

            {/* Staff users */}
            <View style={[s.secHead, { marginTop: 20 }]}>
              <Text style={s.secTitle}>Staff Users ({staff.length})</Text>
              <Pressable style={s.seedBtn} onPress={() => setStaffForm({ name: "", email: "", phone: "", password: "", role_id: roles[0]?.role_id || "" })} testID="add-staff">
                <Ionicons name="person-add-outline" size={14} color={colors.brandPrimary} />
                <Text style={s.seedTxt}>Add Staff User</Text>
              </Pressable>
            </View>
            {staff.length === 0 ? <Text style={s.muted}>No staff logins yet.</Text> : staff.map((u) => (
              <View key={u.user_id} style={s.staffRow} testID={`staff-${u.email}`}>
                <View style={s.avatar}><Text style={s.avatarTxt}>{(u.name || "?")[0]}</Text></View>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <Text style={s.staffName}>{u.name}</Text>
                    <View style={s.rolePill}><Text style={s.rolePillTxt}>{u.role_name}</Text></View>
                    {u.disabled ? <View style={[s.rolePill, { backgroundColor: "rgba(220,38,38,0.1)" }]}>
                      <Text style={[s.rolePillTxt, { color: "#DC2626" }]}>LOCKED</Text></View> : null}
                  </View>
                  <Text style={s.staffMeta}>{u.email}{u.phone ? ` · ${u.phone}` : ""}</Text>
                </View>
                <Pressable hitSlop={8} onPress={() => setStaffForm({ ...u, role_id: u.company_role_id, password: "" })} testID={`edit-staff-${u.email}`}>
                  <Ionicons name="create-outline" size={18} color={colors.brandPrimary} />
                </Pressable>
                <Pressable hitSlop={8} onPress={() => toggleLock(u)} testID={`lock-staff-${u.email}`}>
                  <Ionicons name={u.disabled ? "lock-open-outline" : "lock-closed-outline"} size={18} color="#D97706" />
                </Pressable>
                <Pressable hitSlop={8} onPress={() => deleteStaff(u)}>
                  <Ionicons name="trash-outline" size={18} color="#DC2626" />
                </Pressable>
              </View>
            ))}
          </View>
        ) : null}
        <View style={{ height: 40 }} />
      </ScrollView>

      {/* Role / matrix editor */}
      <Modal transparent visible={!!editRole} animationType="fade" onRequestClose={() => setEditRole(null)}>
        <View style={s.modalRoot}>
          <Pressable style={s.backdrop} onPress={() => setEditRole(null)} />
          {editRole ? (
            <View style={s.modalCard}>
              <ScrollView showsVerticalScrollIndicator={false}>
                <View style={s.modalHead}>
                  <Text style={s.modalTitle}>{editRole.role_id ? "Edit Role" : "New Role"}</Text>
                  <Pressable onPress={() => setEditRole(null)} hitSlop={10}><Ionicons name="close" size={22} color={colors.onSurfaceSecondary} /></Pressable>
                </View>
                <Text style={s.lbl}>Role Name</Text>
                <TextInput style={s.input} value={editRole.name} onChangeText={(v) => setEditRole({ ...editRole, name: v })}
                  placeholder="e.g. HR Manager" placeholderTextColor={colors.onSurfaceTertiary} testID="role-name" />

                <Text style={[s.lbl, { marginTop: 14 }]}>Permission Matrix</Text>
                <View style={s.matrixHead}>
                  <Text style={[s.mModule, s.mHeadTxt]}>Module</Text>
                  <Text style={[s.mCell, s.mHeadTxt]}>View</Text>
                  <Text style={[s.mCell, s.mHeadTxt]}>Manage</Text>
                </View>
                {catalog.map((c) => (
                  <View key={c.module} style={s.matrixRow}>
                    <Text style={s.mModule}>{c.module}</Text>
                    {[c.read, c.write].map((key) => (
                      <Pressable key={key} style={s.mCell} onPress={() => togglePerm(key)} testID={`perm-${key}`}>
                        <Ionicons
                          name={editRole.permissions.has(key) ? "checkbox" : "square-outline"}
                          size={20}
                          color={editRole.permissions.has(key) ? colors.brandPrimary : colors.onSurfaceTertiary}
                        />
                      </Pressable>
                    ))}
                  </View>
                ))}
                <Pressable style={[s.saveBtn, saving && { opacity: 0.6 }]} disabled={saving} onPress={saveRole} testID="save-role">
                  {saving ? <ActivityIndicator color="#fff" size="small" /> :
                    <><Ionicons name="checkmark" size={16} color="#fff" /><Text style={s.saveBtnTxt}>Save Role</Text></>}
                </Pressable>
                <View style={{ height: 10 }} />
              </ScrollView>
            </View>
          ) : null}
        </View>
      </Modal>

      {/* Staff form */}
      <Modal transparent visible={!!staffForm} animationType="fade" onRequestClose={() => setStaffForm(null)}>
        <View style={s.modalRoot}>
          <Pressable style={s.backdrop} onPress={() => setStaffForm(null)} />
          {staffForm ? (
            <View style={s.modalCard}>
              <ScrollView showsVerticalScrollIndicator={false}>
                <View style={s.modalHead}>
                  <Text style={s.modalTitle}>{staffForm.user_id ? "Edit Staff User" : "Add Staff User"}</Text>
                  <Pressable onPress={() => setStaffForm(null)} hitSlop={10}><Ionicons name="close" size={22} color={colors.onSurfaceSecondary} /></Pressable>
                </View>
                <Text style={s.lbl}>Full Name</Text>
                <TextInput style={s.input} value={staffForm.name} onChangeText={(v) => setStaffForm({ ...staffForm, name: v })} testID="staff-name" />
                <Text style={s.lbl}>Email (login username)</Text>
                <TextInput style={[s.input, staffForm.user_id && { opacity: 0.6 }]} value={staffForm.email} editable={!staffForm.user_id}
                  autoCapitalize="none" keyboardType="email-address"
                  onChangeText={(v) => setStaffForm({ ...staffForm, email: v })} testID="staff-email" />
                {!staffForm.user_id ? (
                  <>
                    <Text style={s.lbl}>Mobile (optional)</Text>
                    <TextInput style={s.input} value={staffForm.phone} keyboardType="phone-pad"
                      onChangeText={(v) => setStaffForm({ ...staffForm, phone: v })} />
                  </>
                ) : null}
                <Text style={s.lbl}>{staffForm.user_id ? "Reset Password (leave blank to keep)" : "Password"}</Text>
                <TextInput style={s.input} value={staffForm.password} secureTextEntry
                  onChangeText={(v) => setStaffForm({ ...staffForm, password: v })} testID="staff-password" />
                <Text style={s.lbl}>Role</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                  {roles.map((r) => (
                    <Pressable key={r.role_id} onPress={() => setStaffForm({ ...staffForm, role_id: r.role_id })}
                      style={[s.chip, staffForm.role_id === r.role_id && s.chipOn]}
                      testID={`staff-role-${r.name.replace(/\s+/g, "-")}`}>
                      <Text style={[s.chipTxt, staffForm.role_id === r.role_id && s.chipTxtOn]}>{r.name}</Text>
                    </Pressable>
                  ))}
                </View>
                <Pressable style={[s.saveBtn, saving && { opacity: 0.6 }]} disabled={saving} onPress={saveStaff} testID="save-staff">
                  {saving ? <ActivityIndicator color="#fff" size="small" /> :
                    <><Ionicons name="checkmark" size={16} color="#fff" /><Text style={s.saveBtnTxt}>Save Staff User</Text></>}
                </Pressable>
                <Text style={[s.muted, { marginTop: 10, textAlign: "center" }]}>
                  Staff sign in on the same Employer login page with email &amp; password.
                </Text>
                <View style={{ height: 10 }} />
              </ScrollView>
            </View>
          ) : null}
        </View>
      </Modal>
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
  newBtn: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: colors.brandPrimary, borderRadius: 12, paddingHorizontal: 13, height: 38 },
  newBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  body: { padding: 16, width: "100%", maxWidth: 1000, alignSelf: "center" },
  muted: { fontSize: 12, color: colors.onSurfaceTertiary },

  secHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 },
  secTitle: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface },
  seedBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1, borderColor: "rgba(37,99,235,0.35)",
    borderRadius: 10, paddingHorizontal: 12, height: 34, backgroundColor: "rgba(37,99,235,0.06)",
  },
  seedTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },

  cardsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  roleCard: {
    width: 300, backgroundColor: colors.surfaceSecondary, borderRadius: 16, padding: 14,
    borderWidth: 1, borderColor: colors.border,
  },
  roleTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  roleIcon: { width: 30, height: 30, borderRadius: 9, backgroundColor: "rgba(37,99,235,0.1)", alignItems: "center", justifyContent: "center" },
  roleName: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  roleMeta: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 6 },
  roleActions: { flexDirection: "row", gap: 8, marginTop: 10 },
  actBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1, borderColor: colors.border,
    borderRadius: 10, paddingHorizontal: 10, height: 30, backgroundColor: colors.surface,
  },
  actTxt: { fontSize: 11.5, fontWeight: "800" },

  staffRow: {
    flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: colors.surfaceSecondary,
    borderRadius: 14, borderWidth: 1, borderColor: colors.border, padding: 12, marginBottom: 8,
  },
  avatar: { width: 36, height: 36, borderRadius: 18, backgroundColor: "rgba(37,99,235,0.1)", alignItems: "center", justifyContent: "center" },
  avatarTxt: { fontSize: 14, fontWeight: "800", color: colors.brandPrimary },
  staffName: { fontSize: 13.5, fontWeight: "700", color: colors.onSurface },
  staffMeta: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 2 },
  rolePill: { backgroundColor: "rgba(37,99,235,0.1)", borderRadius: 8, paddingHorizontal: 7, paddingVertical: 2 },
  rolePillTxt: { fontSize: 10, fontWeight: "800", color: colors.brandPrimary },

  modalRoot: { flex: 1, alignItems: "center", justifyContent: "center", padding: 16 },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(15,23,42,0.45)" },
  modalCard: {
    width: "100%", maxWidth: 520, maxHeight: "92%", backgroundColor: colors.surfaceSecondary,
    borderRadius: 18, padding: 18,
    ...Platform.select({ web: { boxShadow: "0 20px 50px rgba(15,23,42,0.25)" } as any, default: { elevation: 8 } }),
  },
  modalHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  modalTitle: { fontSize: 15.5, fontWeight: "800", color: colors.onSurface },
  lbl: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 10, marginBottom: 5 },
  input: {
    height: 44, borderRadius: 12, borderWidth: 1, borderColor: colors.border, paddingHorizontal: 12,
    fontSize: 14, color: colors.onSurface, backgroundColor: colors.surface,
  },
  matrixHead: {
    flexDirection: "row", alignItems: "center", paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  mHeadTxt: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceSecondary },
  matrixRow: {
    flexDirection: "row", alignItems: "center", paddingVertical: 9,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  mModule: { flex: 1, fontSize: 12.5, fontWeight: "600", color: colors.onSurface },
  mCell: { width: 70, alignItems: "center" },
  chip: {
    paddingHorizontal: 12, height: 32, borderRadius: 16, backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center",
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "600", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7,
    backgroundColor: colors.brandPrimary, borderRadius: 14, height: 48, marginTop: 16,
  },
  saveBtnTxt: { fontSize: 14, fontWeight: "800", color: "#fff" },
});
