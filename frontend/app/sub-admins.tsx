/**
 * Sub-admins management — Super Admin only.
 *
 * A page for the super admin to create / edit / delete delegated
 * sub-admin accounts. Each sub-admin logs in with the same email +
 * password flow as company admins (also phone + password) and receives
 * a role of "sub_admin" with a fine-grained permissions list + company
 * scope. The AdminWebShell reads these permissions to render only the
 * navigation entries the sub-admin is allowed to see.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  TextInput,
  ActivityIndicator,
  Switch,
  Modal,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { NAV_SUPER } from "@/src/components/AdminWebShell";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type SubAdmin = {
  user_id: string;
  name: string;
  email?: string | null;
  phone_e164?: string | null;
  sub_admin_permissions: string[];
  sub_admin_company_scope: "all" | "restricted";
  sub_admin_company_ids: string[];
  disabled?: boolean;
  disabled_reason?: string | null;
  pin_last_login_at?: string | null;
  password_last_login_at?: string | null;
  created_at?: string;
  password_must_change?: boolean;
  // Iter 94 — per-sidebar-button visibility ({route: false} == hidden)
  menu_rights?: Record<string, boolean>;
};

// Routes that are HARD-blocked for sub-admins inside AdminWebShell — no
// point showing a toggle for them here.
const SUB_ADMIN_ALWAYS_BLOCKED = new Set([
  "/sub-admins",
  "/employer-access-rights",
  "/super-admin-access",
  "/attendance-sheet",
  "/masters",
  "/compliance-policy",
  "/portal-automation",
  "/ai-insights",
  "/appearance",
]);

type Company = { company_id: string; name: string };

const PERMISSION_GROUPS: { label: string; keys: [string, string, string][] }[] = [
  {
    label: "Companies & requests",
    keys: [
      ["Companies", "companies:read", "companies:write"],
      ["Company requests", "company_requests:read", "company_requests:write"],
    ],
  },
  {
    label: "Employees & policy",
    keys: [
      ["Employees", "employees:read", "employees:write"],
      ["Attendance policy", "attendance_policy:read", "attendance_policy:write"],
    ],
  },
  {
    label: "Attendance",
    keys: [
      ["Punch approvals", "punch_approvals:read", "punch_approvals:write"],
      ["Biometric devices", "biometric_devices:read", "biometric_devices:write"],
      ["Attendance review", "attendance_review:read", "attendance_review:write"],
    ],
  },
  {
    label: "Payroll",
    keys: [
      ["Salary process", "salary_process:read", "salary_process:write"],
      ["Compliance salary", "compliance_salary:read", "compliance_salary:write"],
    ],
  },
  {
    label: "Communication & tickets",
    keys: [
      ["Messages", "messages:read", "messages:write"],
      ["Tickets", "tickets:read", "tickets:write"],
    ],
  },
];

function showMsg(msg: string, title = "Sub-admins") {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

export default function SubAdminsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [rows, setRows] = useState<SubAdmin[]>([]);
  const [loading, setLoading] = useState(true);
  const [showEditor, setShowEditor] = useState(false);
  const [editing, setEditing] = useState<SubAdmin | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ sub_admins: SubAdmin[] }>("/admin/sub-admins");
      setRows(r.sub_admins || []);
    } catch (e: any) {
      showMsg(e?.message || "Could not load sub-admins");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user?.role === "super_admin") load();
  }, [user?.role, load]);

  const openCreate = () => {
    setEditing(null);
    setShowEditor(true);
  };
  const openEdit = (r: SubAdmin) => {
    setEditing(r);
    setShowEditor(true);
  };

  const deleteOne = async (r: SubAdmin) => {
    if (!globalThis.confirm?.(`Delete sub-admin "${r.name}"?`)) return;
    try {
      await api(`/admin/sub-admins/${r.user_id}`, { method: "DELETE" });
      setRows((prev) => prev.filter((x) => x.user_id !== r.user_id));
    } catch (e: any) {
      showMsg(e?.message || "Delete failed");
    }
  };

  const toggleDisabled = async (r: SubAdmin) => {
    try {
      const upd = await api<{ sub_admin: SubAdmin }>(
        `/admin/sub-admins/${r.user_id}`,
        { method: "PATCH", body: { disabled: !r.disabled } },
      );
      setRows((prev) => prev.map((x) => (x.user_id === r.user_id ? upd.sub_admin : x)));
    } catch (e: any) {
      showMsg(e?.message || "Failed to update status");
    }
  };

  const resetPassword = async (r: SubAdmin) => {
    const pw = globalThis.prompt?.(`New password for ${r.name} (min 6 chars):`);
    if (!pw || pw.length < 6) {
      if (pw !== null && pw !== undefined) showMsg("Password must be at least 6 characters");
      return;
    }
    try {
      await api(`/admin/sub-admins/${r.user_id}/reset-password`, {
        method: "POST",
        body: { password: pw },
      });
      showMsg(`Password reset for ${r.name}. Share the new password with them out-of-band.`);
    } catch (e: any) {
      showMsg(e?.message || "Reset failed");
    }
  };

  if (user?.role !== "super_admin") {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Only the Super Admin can manage sub-admins.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.h1}>Sub-admins</Text>
            <Text style={styles.hsub}>
              Delegated Super Admin accounts with fine-grained access
            </Text>
          </View>
          <Pressable onPress={openCreate} style={styles.newBtn} testID="sub-admins-new">
            <Ionicons name="add" size={16} color="#fff" />
            <Text style={styles.newBtnTxt}>New</Text>
          </Pressable>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {loading ? (
          <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
        ) : rows.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="people-circle-outline" size={44} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyT}>No sub-admins yet</Text>
            <Text style={styles.emptyS}>
              Create a sub-admin to delegate parts of the Super Admin portal to
              your team. They can log in with email + password (or phone +
              password) and only see what you allow.
            </Text>
            <Pressable onPress={openCreate} style={styles.primaryBtn}>
              <Ionicons name="add" size={16} color="#fff" />
              <Text style={styles.primaryBtnTxt}>Create first sub-admin</Text>
            </Pressable>
          </View>
        ) : (
          rows.map((r) => (
            <View key={r.user_id} style={styles.card}>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{r.name || "—"}</Text>
                <Text style={styles.meta} numberOfLines={1}>
                  {r.email || r.phone_e164 || "—"}
                </Text>
                <Text style={styles.meta2}>
                  {r.sub_admin_permissions?.length || 0} permission
                  {(r.sub_admin_permissions?.length || 0) === 1 ? "" : "s"} ·{" "}
                  {r.sub_admin_company_scope === "all"
                    ? "All companies"
                    : `${r.sub_admin_company_ids?.length || 0} companies`}
                  {r.password_must_change ? "  ·  🔐 must change password" : ""}
                </Text>
                <Text style={styles.meta2}>
                  Last login:{" "}
                  {(() => {
                    const a = r.pin_last_login_at || "";
                    const b = r.password_last_login_at || "";
                    const last = a > b ? a : b;
                    return last ? new Date(last).toLocaleDateString("en-IN") : "never";
                  })()}
                  {r.disabled && r.disabled_reason === "auto_inactivity"
                    ? "  ·  ⏸ auto-disabled (30 days inactive)"
                    : ""}
                </Text>
              </View>
              <View style={styles.rowActions}>
                <View style={styles.statusWrap}>
                  <Text style={styles.statusLbl}>
                    {r.disabled ? "Disabled" : "Active"}
                  </Text>
                  <Switch
                    value={!r.disabled}
                    onValueChange={() => toggleDisabled(r)}
                    testID={`sub-admin-toggle-${r.user_id}`}
                  />
                </View>
                <Pressable
                  onPress={() => resetPassword(r)}
                  style={styles.iconBtn}
                  testID={`sub-admin-reset-${r.user_id}`}
                >
                  <Ionicons name="key-outline" size={16} color={colors.brandPrimary} />
                </Pressable>
                <Pressable
                  onPress={() => openEdit(r)}
                  style={styles.iconBtn}
                  testID={`sub-admin-edit-${r.user_id}`}
                >
                  <Ionicons name="create-outline" size={16} color={colors.brandPrimary} />
                </Pressable>
                <Pressable
                  onPress={() => deleteOne(r)}
                  style={styles.iconBtnDanger}
                  testID={`sub-admin-delete-${r.user_id}`}
                >
                  <Ionicons name="trash-outline" size={16} color="#8A1F1F" />
                </Pressable>
              </View>
            </View>
          ))
        )}
        <View style={{ height: 40 }} />
      </ScrollView>

      {showEditor ? (
        <SubAdminEditor
          initial={editing}
          onClose={() => setShowEditor(false)}
          onSaved={(saved) => {
            setShowEditor(false);
            setRows((prev) => {
              const idx = prev.findIndex((x) => x.user_id === saved.user_id);
              if (idx === -1) return [saved, ...prev];
              const next = [...prev];
              next[idx] = saved;
              return next;
            });
          }}
        />
      ) : null}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Editor modal
// ---------------------------------------------------------------------------
function SubAdminEditor({
  initial,
  onClose,
  onSaved,
}: {
  initial: SubAdmin | null;
  onClose: () => void;
  onSaved: (sub: SubAdmin) => void;
}) {
  const isEdit = !!initial;
  const [name, setName] = useState(initial?.name || "");
  const [email, setEmail] = useState(initial?.email || "");
  const [phone, setPhone] = useState(initial?.phone_e164 || "");
  const [password, setPassword] = useState("");
  const [scope, setScope] = useState<"all" | "restricted">(
    initial?.sub_admin_company_scope || "all",
  );
  const [companyIds, setCompanyIds] = useState<string[]>(
    initial?.sub_admin_company_ids || [],
  );
  const [perms, setPerms] = useState<Set<string>>(
    new Set(initial?.sub_admin_permissions || []),
  );
  const [companies, setCompanies] = useState<Company[]>([]);
  const [saving, setSaving] = useState(false);
  // Iter 94 — per-sidebar-button visibility ({route: false} == hidden)
  const [menuRights, setMenuRights] = useState<Record<string, boolean>>(
    initial?.menu_rights || {},
  );

  useEffect(() => {
    (async () => {
      try {
        const r = await api<{ companies: Company[] }>("/companies");
        setCompanies(r.companies || []);
      } catch { /* ignore */ }
    })();
  }, []);

  const togglePerm = (k: string) => {
    setPerms((p) => {
      const next = new Set(p);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };
  const toggleCompany = (id: string) => {
    setCompanyIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const save = async () => {
    if (!name.trim()) return showMsg("Name is required");
    if (!email.trim() || !email.includes("@")) return showMsg("A valid email is required");
    if (!isEdit && (!password || password.length < 6))
      return showMsg("Password must be at least 6 characters");
    if (scope === "restricted" && companyIds.length === 0)
      return showMsg("Pick at least one company or switch scope to All");

    setSaving(true);
    try {
      const body: any = {
        name: name.trim(),
        email: email.trim().toLowerCase(),
        phone: phone.trim() || null,
        permissions: Array.from(perms),
        company_scope: scope,
        company_ids: scope === "restricted" ? companyIds : [],
        menu_rights: menuRights,
      };
      let saved: SubAdmin;
      if (isEdit && initial) {
        const r = await api<{ sub_admin: SubAdmin }>(
          `/admin/sub-admins/${initial.user_id}`,
          { method: "PATCH", body },
        );
        saved = r.sub_admin;
      } else {
        body.password = password;
        const r = await api<{ sub_admin: SubAdmin }>(
          "/admin/sub-admins",
          { method: "POST", body },
        );
        saved = r.sub_admin;
      }
      onSaved(saved);
      showMsg(
        isEdit
          ? "Sub-admin updated."
          : `Sub-admin created. Share the login (${saved.email}) and password with them out-of-band.`,
      );
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.modalRoot}>
        <View style={styles.modalCard}>
          <View style={styles.modalHead}>
            <Text style={styles.modalTitle}>
              {isEdit ? "Edit sub-admin" : "Create sub-admin"}
            </Text>
            <Pressable onPress={onClose} hitSlop={8}>
              <Ionicons name="close" size={22} color={colors.onSurface} />
            </Pressable>
          </View>

          <ScrollView style={{ maxHeight: 620 }} contentContainerStyle={{ padding: 4 }}>
            <View style={styles.gridRow}>
              <View style={styles.gridCol}>
                <Text style={styles.label}>Full name *</Text>
                <TextInput
                  testID="sub-admin-name"
                  value={name}
                  onChangeText={setName}
                  style={styles.input}
                  placeholder="Ramesh Kumar"
                  placeholderTextColor={colors.onSurfaceTertiary}
                />
              </View>
              <View style={styles.gridCol}>
                <Text style={styles.label}>Email (for login) *</Text>
                <TextInput
                  testID="sub-admin-email"
                  value={email}
                  onChangeText={setEmail}
                  style={styles.input}
                  placeholder="ramesh@sksharma.co"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  autoCapitalize="none"
                  keyboardType="email-address"
                />
              </View>
            </View>
            <View style={styles.gridRow}>
              <View style={styles.gridCol}>
                <Text style={styles.label}>Phone (optional, for login)</Text>
                <TextInput
                  testID="sub-admin-phone"
                  value={phone}
                  onChangeText={setPhone}
                  style={styles.input}
                  placeholder="+919812345678"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="phone-pad"
                />
              </View>
              {!isEdit ? (
                <View style={styles.gridCol}>
                  <Text style={styles.label}>Initial password *</Text>
                  <TextInput
                    testID="sub-admin-password"
                    value={password}
                    onChangeText={setPassword}
                    style={styles.input}
                    placeholder="min 6 characters"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    autoCapitalize="none"
                    secureTextEntry
                  />
                </View>
              ) : null}
            </View>

            <Text style={styles.subheading}>Company scope</Text>
            <View style={styles.chipStrip}>
              <Pressable
                onPress={() => setScope("all")}
                style={[styles.chip, scope === "all" && styles.chipOn]}
                testID="sub-admin-scope-all"
              >
                <Text style={[styles.chipTxt, scope === "all" && styles.chipTxtOn]}>
                  All companies
                </Text>
              </Pressable>
              <Pressable
                onPress={() => setScope("restricted")}
                style={[styles.chip, scope === "restricted" && styles.chipOn]}
                testID="sub-admin-scope-restricted"
              >
                <Text style={[styles.chipTxt, scope === "restricted" && styles.chipTxtOn]}>
                  Only chosen companies
                </Text>
              </Pressable>
            </View>
            {scope === "restricted" ? (
              <ScrollView
                horizontal={false}
                style={styles.compBox}
                contentContainerStyle={{ padding: 6 }}
              >
                {companies.map((c) => {
                  const on = companyIds.includes(c.company_id);
                  return (
                    <Pressable
                      key={c.company_id}
                      onPress={() => toggleCompany(c.company_id)}
                      style={styles.compRow}
                    >
                      <View style={[styles.checkBox, on && styles.checkBoxOn]}>
                        {on ? <Ionicons name="checkmark" size={12} color="#fff" /> : null}
                      </View>
                      <Text style={styles.compTxt}>{c.name}</Text>
                    </Pressable>
                  );
                })}
                {companies.length === 0 ? (
                  <Text style={styles.smallHint}>No companies to select.</Text>
                ) : null}
              </ScrollView>
            ) : null}

            <Text style={styles.subheading}>Permissions</Text>
            <Text style={styles.smallHint}>
              Tick what the sub-admin can view or manage. The nav on their web
              portal automatically hides sections they don&apos;t have access to.
            </Text>
            {PERMISSION_GROUPS.map((grp) => (
              <View key={grp.label} style={styles.permGroup}>
                <Text style={styles.permGroupTitle}>{grp.label}</Text>
                {grp.keys.map(([label, readKey, writeKey]) => (
                  <View key={readKey} style={styles.permRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.permLabel}>{label}</Text>
                    </View>
                    <View style={styles.permToggles}>
                      <View style={styles.permToggle}>
                        <Text style={styles.tinyLabel}>View</Text>
                        <Switch
                          value={perms.has(readKey)}
                          onValueChange={() => togglePerm(readKey)}
                          testID={`perm-${readKey}`}
                        />
                      </View>
                      <View style={styles.permToggle}>
                        <Text style={styles.tinyLabel}>Manage</Text>
                        <Switch
                          value={perms.has(writeKey)}
                          onValueChange={() => togglePerm(writeKey)}
                          testID={`perm-${writeKey}`}
                        />
                      </View>
                    </View>
                  </View>
                ))}
              </View>
            ))}

            {/* Iter 94 — Per-sidebar-button access, mirroring the Employer
                Access Rights screen. Blocked buttons vanish from this
                sub-admin's web-portal sidebar. */}
            <Text style={styles.subheading}>Sidebar Menu Access (Web Portal)</Text>
            <Text style={styles.smallHint}>
              Blocked buttons disappear from this sub-admin&apos;s sidebar.
              Dashboard is always visible.
            </Text>
            <View style={styles.permGroup}>
              {NAV_SUPER.map((item) => {
                const renderRow = (nav: typeof item, indent = false) => {
                  const route = nav.route || "";
                  if (!route || route === "/(tabs)") return null;
                  if (SUB_ADMIN_ALWAYS_BLOCKED.has(route.split("?")[0])) return null;
                  const allowed = menuRights[route] !== false;
                  return (
                    <Pressable
                      key={`${route}|${nav.label}`}
                      onPress={() =>
                        setMenuRights((prev) => ({ ...prev, [route]: !allowed }))
                      }
                      style={[styles.menuRow, indent && { marginLeft: 18 }]}
                      testID={`sa-menu-${route.replace(/[^a-z0-9]/gi, "_")}`}
                    >
                      <Ionicons
                        name={allowed ? "checkmark-circle" : "close-circle"}
                        size={18}
                        color={allowed ? "#15803D" : "#DC2626"}
                      />
                      <Text style={styles.menuRowTxt}>{nav.label}</Text>
                      <Text style={[styles.menuRowState, { color: allowed ? "#15803D" : "#DC2626" }]}>
                        {allowed ? "Allowed" : "Blocked"}
                      </Text>
                    </Pressable>
                  );
                };
                if (item.children?.length) {
                  const kids = item.children
                    .map((c) => renderRow(c, true))
                    .filter(Boolean);
                  if (kids.length === 0) return null;
                  return (
                    <View key={item.label}>
                      <Text style={styles.menuGroupLbl}>{item.label}</Text>
                      {kids}
                    </View>
                  );
                }
                return renderRow(item);
              })}
            </View>
          </ScrollView>

          <View style={{ flexDirection: "row", gap: 8, marginTop: 14 }}>
            <Pressable onPress={onClose} style={styles.secondaryBtn}>
              <Text style={styles.secondaryBtnTxt}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={save}
              disabled={saving}
              style={[styles.primaryBtn, saving && { opacity: 0.6 }, { flex: 1 }]}
              testID="sub-admin-save"
            >
              {saving ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="save-outline" size={15} color="#fff" />
                  <Text style={styles.primaryBtnTxt}>
                    {isEdit ? "Save changes" : "Create sub-admin"}
                  </Text>
                </>
              )}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: {
    marginTop: 8,
    color: colors.onSurfaceSecondary,
    fontSize: type.body,
    textAlign: "center",
  },
  header: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  h1: { color: colors.onSurface, fontSize: type.xl, fontWeight: "800" },
  hsub: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },
  newBtn: {
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  newBtnTxt: { color: "#fff", fontWeight: "800", fontSize: type.sm },

  scroll: { padding: spacing.lg },
  empty: { alignItems: "center", padding: spacing.xl, marginTop: 20 },
  emptyT: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800", marginTop: 12 },
  emptyS: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 6,
    textAlign: "center",
    lineHeight: 20,
    maxWidth: 380,
  },

  card: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: 8,
    gap: 10,
  },
  name: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  meta: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },
  meta2: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },
  rowActions: { flexDirection: "row", alignItems: "center", gap: 6 },
  statusWrap: { alignItems: "center", gap: 2 },
  statusLbl: { fontSize: 9, color: colors.onSurfaceTertiary, fontWeight: "800" },
  iconBtn: {
    padding: 8,
    borderRadius: 6,
    backgroundColor: colors.brandTertiary,
  },
  iconBtnDanger: {
    padding: 8,
    borderRadius: 6,
    backgroundColor: "#FDECE2",
  },

  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    paddingHorizontal: 16,
    marginTop: 16,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800" },
  secondaryBtn: {
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  secondaryBtnTxt: { color: colors.brandPrimary, fontWeight: "800" },

  // Modal
  modalRoot: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "center",
    alignItems: "center",
    padding: 20,
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: 20,
    width: "100%",
    maxWidth: 760,
    maxHeight: "92%",
  },
  modalHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 10,
  },
  modalTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800" },

  gridRow: { flexDirection: "row", gap: 10, flexWrap: "wrap" },
  gridCol: { flex: 1, minWidth: 220 },
  label: {
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    fontWeight: "800",
    marginBottom: 4,
    marginTop: 8,
    textTransform: "uppercase",
  },
  subheading: {
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    fontWeight: "800",
    marginTop: 16,
    marginBottom: 6,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  smallHint: { fontSize: 11, color: colors.onSurfaceTertiary, marginBottom: 6 },
  tinyLabel: {
    fontSize: 9,
    color: colors.onSurfaceTertiary,
    fontWeight: "800",
    textTransform: "uppercase",
  },
  input: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  chipStrip: { flexDirection: "row", gap: 6, marginTop: 4 },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
  chipOn: { borderColor: colors.brandPrimary, backgroundColor: colors.brandPrimary },
  chipTxt: { color: colors.onSurfaceSecondary, fontWeight: "700", fontSize: 12 },
  chipTxtOn: { color: "#fff" },

  compBox: {
    marginTop: 8,
    maxHeight: 200,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    backgroundColor: colors.background,
  },
  compRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 6,
  },
  checkBox: {
    width: 18,
    height: 18,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  checkBoxOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  compTxt: { color: colors.onSurface, fontSize: 13 },

  permGroup: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: 10,
    marginBottom: 8,
  },
  permGroupTitle: {
    color: colors.onSurfaceSecondary,
    fontSize: 11,
    fontWeight: "800",
    marginBottom: 6,
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  permRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  permLabel: { color: colors.onSurface, fontSize: 13, fontWeight: "600" },
  permToggles: { flexDirection: "row", gap: 12 },
  permToggle: { alignItems: "center", gap: 2 },

  // Iter 94 — sidebar menu-rights rows
  menuRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 7,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  menuRowTxt: { flex: 1, fontSize: 13, color: colors.onSurface },
  menuRowState: { fontSize: 11, fontWeight: "800" },
  menuGroupLbl: {
    fontSize: 10,
    color: colors.onSurfaceTertiary,
    fontWeight: "800",
    textTransform: "uppercase",
    letterSpacing: 0.4,
    marginTop: 8,
    marginBottom: 2,
  },
});
