/**
 * Employer Access Rights — Iter 58.
 *
 * Super Admin controls which Company Admin (employer) features each firm's
 * admins can access on the web portal. Stored as `employer_permissions: []`
 * on the companies doc — empty array means "all features enabled".
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  Switch,
  TextInput,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { NAV_COMPANY_ADMIN } from "@/src/components/AdminWebShell";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };
type AccessRights = {
  company_id: string;
  company_name?: string;
  permissions: string[];
  all_features_enabled: boolean;
  known_permissions: string[];
};

const PERMISSION_GROUPS: { label: string; keys: [string, string, string][] }[] = [
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
      ["Salary process (Actual + Arrear)", "salary_process:read", "salary_process:write"],
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
  {
    label: "Portal credentials",
    keys: [
      ["Portal credentials (EPFO/ESIC/Shram Suvidha)",
       "portal_credentials:read", "portal_credentials:write"],
    ],
  },
];

function showMsg(msg: string) {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert("Access rights", msg);
}

export default function EmployerAccessRightsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [current, setCurrent] = useState<AccessRights | null>(null);
  const [dirtyPerms, setDirtyPerms] = useState<Set<string>>(new Set());
  const [allEnabled, setAllEnabled] = useState(true);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  // Iter 93 — firm admin login credentials
  const [creds, setCreds] = useState<{ name?: string; email?: string; login_id?: string | null; has_password?: boolean; has_pin?: boolean } | null>(null);
  const [credLoginId, setCredLoginId] = useState("");
  const [credPassword, setCredPassword] = useState("");
  const [credPin, setCredPin] = useState("");
  const [credSaving, setCredSaving] = useState(false);
  // Iter 93 — per-sidebar-button visibility ({route: false} == hidden)
  const [menuRights, setMenuRights] = useState<Record<string, boolean>>({});

  const isSuper = user?.role === "super_admin";

  useEffect(() => {
    if (!isSuper) return;
    (async () => {
      try {
        const r = await api<{ companies: Company[] }>("/companies");
        setCompanies(r.companies || []);
      } catch (e: any) {
        showMsg(e?.message || "Could not load companies");
      }
    })();
  }, [isSuper]);

  const loadRights = useCallback(async (companyId: string) => {
    setLoading(true);
    try {
      const r = await api<AccessRights>(
        `/admin/companies/${companyId}/access-rights`,
      );
      setCurrent(r);
      setDirtyPerms(new Set(r.permissions));
      setAllEnabled(r.all_features_enabled);
      setMenuRights((r as any).menu_rights || {});
    } catch (e: any) {
      showMsg(e?.message || "Could not load rights");
    } finally {
      setLoading(false);
    }
  }, []);

  const pick = (companyId: string) => {
    setSelected(companyId);
    loadRights(companyId);
    setCreds(null); setCredLoginId(""); setCredPassword(""); setCredPin("");
    api<any>(`/admin/companies/${companyId}/admin-credentials`)
      .then((r) => { setCreds(r); setCredLoginId(r.login_id || ""); })
      .catch(() => setCreds(null));
  };

  const saveCredentials = async () => {
    if (!selected || credSaving) return;
    if (!credLoginId.trim() && !credPassword.trim() && !credPin.trim()) {
      showMsg("Enter a User ID, password and/or PIN first");
      return;
    }
    if (credPin.trim() && credPin.trim().length !== 6) {
      showMsg("PIN must be exactly 6 digits");
      return;
    }
    setCredSaving(true);
    try {
      const r = await api<any>(`/admin/companies/${selected}/admin-credentials`, {
        method: "POST",
        body: {
          login_id: credLoginId.trim() || null,
          password: credPassword.trim() || null,
          pin: credPin.trim() || null,
        },
      });
      setCreds((c) => ({ ...(c || {}), login_id: r.login_id, has_password: r.has_password, has_pin: r.has_pin }));
      setCredPassword("");
      setCredPin("");
      showMsg("Login credentials saved. The employer can now sign in on App & Web.");
    } catch (e: any) {
      showMsg(e?.message || "Could not save credentials");
    } finally {
      setCredSaving(false);
    }
  };

  const toggle = (key: string) => {
    setAllEnabled(false);   // once you edit, you're in explicit mode
    setDirtyPerms((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const setAll = (on: boolean) => {
    if (on) {
      // "All features" mode → send permissions=null to reset the field
      setAllEnabled(true);
      setDirtyPerms(new Set(current?.known_permissions || []));
    } else {
      setAllEnabled(false);
      setDirtyPerms(new Set());   // start blank so admin explicitly picks
    }
  };

  const save = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const body = allEnabled
        ? { permissions: null, menu_rights: menuRights }
        : { permissions: Array.from(dirtyPerms), menu_rights: menuRights };
      const r = await api<AccessRights>(
        `/admin/companies/${selected}/access-rights`,
        { method: "PATCH", body },
      );
      setCurrent(r);
      showMsg(
        allEnabled
          ? "All features enabled for this company."
          : `Saved — ${r.permissions.length} permissions active.`,
      );
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const filteredCompanies = React.useMemo(() => {
    if (!search.trim()) return companies;
    const q = search.trim().toLowerCase();
    return companies.filter((c) => c.name.toLowerCase().includes(q));
  }, [companies, search]);

  if (!isSuper) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Only the Super Admin can manage employer access rights.</Text>
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
            <Text style={styles.h1}>Employer access rights</Text>
            <Text style={styles.hsub}>Choose which functions each employer can access on the portal</Text>
          </View>
        </View>
      </SafeAreaView>

      <View style={styles.body}>
        {/* Left column — company list */}
        <View style={styles.leftCol}>
          <TextInput
            testID="ear-search"
            value={search}
            onChangeText={setSearch}
            placeholder="Search company…"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={styles.input}
            autoCapitalize="none"
          />
          <ScrollView style={{ flex: 1, marginTop: 8 }}>
            {filteredCompanies.map((c) => {
              const on = selected === c.company_id;
              return (
                <Pressable
                  key={c.company_id}
                  onPress={() => pick(c.company_id)}
                  style={[styles.compRow, on && styles.compRowOn]}
                  testID={`ear-comp-${c.company_id}`}
                >
                  <Ionicons
                    name={on ? "business" : "business-outline"}
                    size={16}
                    color={on ? colors.brandPrimary : colors.onSurfaceTertiary}
                  />
                  <Text
                    style={[styles.compTxt, on && { color: colors.brandPrimary, fontWeight: "800" }]}
                    numberOfLines={1}
                  >
                    {c.name}
                  </Text>
                </Pressable>
              );
            })}
            {filteredCompanies.length === 0 ? (
              <Text style={styles.smallHint}>No companies found.</Text>
            ) : null}
          </ScrollView>
        </View>

        {/* Right column — permissions editor */}
        <View style={styles.rightCol}>
          {!selected ? (
            <View style={styles.hint}>
              <Ionicons name="arrow-back-outline" size={20} color={colors.onSurfaceTertiary} />
              <Text style={styles.hintTxt}>Pick a company on the left to configure access.</Text>
            </View>
          ) : loading ? (
            <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
          ) : (
            <ScrollView contentContainerStyle={{ padding: 4 }}>
              <View style={styles.masterRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.masterTitle}>{current?.company_name || "—"}</Text>
                  <Text style={styles.smallHint}>
                    {allEnabled
                      ? "All features enabled — this employer sees every module."
                      : `Restricted mode — ${dirtyPerms.size} permission${dirtyPerms.size === 1 ? "" : "s"} active.`}
                  </Text>
                </View>
                <View style={styles.masterToggle}>
                  <Text style={styles.tinyLabel}>All features</Text>
                  <Switch
                    value={allEnabled}
                    onValueChange={setAll}
                    testID="ear-all-toggle"
                  />
                </View>
              </View>

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
                            value={allEnabled || dirtyPerms.has(readKey)}
                            onValueChange={() => toggle(readKey)}
                            disabled={allEnabled}
                            testID={`ear-perm-${readKey}`}
                          />
                        </View>
                        <View style={styles.permToggle}>
                          <Text style={styles.tinyLabel}>Manage</Text>
                          <Switch
                            value={allEnabled || dirtyPerms.has(writeKey)}
                            onValueChange={() => toggle(writeKey)}
                            disabled={allEnabled}
                            testID={`ear-perm-${writeKey}`}
                          />
                        </View>
                      </View>
                    </View>
                  ))}
                </View>
              ))}

              {/* Iter 93 — Per-sidebar-button access. Every web-portal menu
                  button can be allowed / blocked for this firm's admin. */}
              <View style={styles.permGroup}>
                <Text style={styles.permGroupTitle}>Sidebar Menu Access (Web Portal)</Text>
                <Text style={styles.smallHint}>
                  Blocked buttons disappear from the employer&apos;s sidebar. Dashboard is always visible.
                </Text>
                {NAV_COMPANY_ADMIN.map((item) => {
                  const renderRow = (nav: typeof item, indent = false) => {
                    const route = nav.route || "";
                    if (!route || route === "/(tabs)") return null;
                    const allowed = menuRights[route] !== false;
                    return (
                      <Pressable
                        key={`${route}|${nav.label}`}
                        onPress={() =>
                          setMenuRights((prev) => ({ ...prev, [route]: !allowed }))
                        }
                        style={[styles.menuRow, indent && { marginLeft: 18 }]}
                        testID={`ear-menu-${route.replace(/[^a-z0-9]/gi, "_")}`}
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
                    return (
                      <View key={item.label}>
                        <Text style={styles.menuGroupLbl}>{item.label}</Text>
                        {item.children.map((c) => renderRow(c, true))}
                      </View>
                    );
                  }
                  return renderRow(item);
                })}
              </View>

              {/* Iter 93 — Login credentials (User ID + Password) for the
                  firm's admin so the employer can sign in on App & Web. */}
              <View style={styles.permGroup}>
                <Text style={styles.permGroupTitle}>Login Credentials (App & Web)</Text>
                {creds ? (
                  <Text style={styles.smallHint}>
                    Admin: {creds.name || "—"} · {creds.email || "no email"} · User ID:{" "}
                    {creds.login_id || "not set"} · Password: {creds.has_password ? "set" : "not set"} ·
                    PIN: {creds.has_pin ? "set" : "not set"}
                  </Text>
                ) : null}
                <View style={{ flexDirection: "row", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                  <TextInput
                    value={credLoginId}
                    onChangeText={setCredLoginId}
                    placeholder="User ID (e.g. kankani)"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    autoCapitalize="none"
                    autoCorrect={false}
                    style={styles.credInput}
                    testID="ear-cred-loginid"
                  />
                  <TextInput
                    value={credPassword}
                    onChangeText={setCredPassword}
                    placeholder="New password (min 6)"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    secureTextEntry
                    style={styles.credInput}
                    testID="ear-cred-password"
                  />
                  <TextInput
                    value={credPin}
                    onChangeText={(t) => setCredPin(t.replace(/\D/g, "").slice(0, 6))}
                    placeholder="App PIN (6 digits)"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    keyboardType="number-pad"
                    secureTextEntry
                    style={styles.credInput}
                    testID="ear-cred-pin"
                  />
                  <Pressable
                    onPress={saveCredentials}
                    disabled={credSaving}
                    style={[styles.primaryBtn, credSaving && { opacity: 0.6 }]}
                    testID="ear-cred-save"
                  >
                    {credSaving ? (
                      <ActivityIndicator color="#fff" size="small" />
                    ) : (
                      <Text style={styles.primaryBtnTxt}>Set credentials</Text>
                    )}
                  </Pressable>
                </View>
                <Text style={styles.smallHint}>
                  The employer signs in with this User ID (or their email) + password on both
                  the mobile app and the web portal — or with the 6-digit PIN on the App
                  (PIN tab of the admin login).
                </Text>
              </View>

              <View style={{ flexDirection: "row", gap: 8, marginTop: 14 }}>
                <Pressable
                  onPress={save}
                  disabled={saving}
                  style={[styles.primaryBtn, saving && { opacity: 0.6 }, { flex: 1 }]}
                  testID="ear-save"
                >
                  {saving ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <>
                      <Ionicons name="save-outline" size={15} color="#fff" />
                      <Text style={styles.primaryBtnTxt}>Save access rights</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </ScrollView>
          )}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
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
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: {
    marginTop: 8,
    color: colors.onSurfaceSecondary,
    fontSize: type.body,
    textAlign: "center",
  },

  body: { flex: 1, flexDirection: "row" },
  leftCol: {
    width: 280,
    padding: spacing.md,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.divider,
    backgroundColor: colors.surface,
  },
  rightCol: { flex: 1, padding: spacing.lg },

  input: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.onSurface,
    backgroundColor: colors.background,
  },
  compRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
    paddingHorizontal: 6,
    borderRadius: 6,
  },
  compRowOn: { backgroundColor: colors.brandTertiary },
  compTxt: { color: colors.onSurface, fontSize: 13 },
  smallHint: {
    fontSize: 11,
    color: colors.onSurfaceTertiary,
    padding: 8,
    textAlign: "center",
  },
  tinyLabel: {
    fontSize: 9,
    color: colors.onSurfaceTertiary,
    fontWeight: "800",
    textTransform: "uppercase",
  },

  hint: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  hintTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm },

  masterRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    marginBottom: spacing.md,
  },
  masterTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800" },
  masterToggle: { alignItems: "center", gap: 2 },

  permGroup: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: 10,
    marginBottom: 8,
  },
  credInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 8,
    fontSize: 13,
    color: colors.onSurface,
    backgroundColor: colors.background,
    minWidth: 180,
    flexGrow: 1,
  },
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
    fontSize: 11,
    fontWeight: "800",
    color: colors.onSurfaceTertiary,
    textTransform: "uppercase",
    marginTop: 8,
    marginBottom: 2,
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

  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    paddingHorizontal: 16,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800" },
});
