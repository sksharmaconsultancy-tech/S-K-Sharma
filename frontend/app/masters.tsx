/**
 * Masters — Iter 59.
 *
 * Super Admin (and Sub-Admins) manage 3 employee-organisation masters here:
 *   • Employee Group      (used for group-wise reports / exports)
 *   • Employee Department
 *   • Employee Designation
 *
 * All three types live in the same `masters` MongoDB collection, keyed by
 * `type`. Groups additionally carry a list of member user_ids.
 *
 * Web-focused single-screen CRUD.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  TextInput,
  ActivityIndicator,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useOnRefresh } from "@/src/context/RefreshBusContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };
type MasterType = "group" | "department" | "designation" | "allowance" | "deduction";
type Master = {
  master_id: string;
  type: MasterType;
  company_id: string;
  name: string;
  member_user_ids?: string[];
  updated_at?: string;
};
type EmployeeLite = { user_id: string; name: string; employee_code?: string };

const TABS: { key: MasterType; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: "group", label: "Groups", icon: "people-outline" },
  { key: "department", label: "Departments", icon: "business-outline" },
  { key: "designation", label: "Designations", icon: "ribbon-outline" },
  { key: "allowance", label: "Allowances", icon: "cash-outline" },
  { key: "deduction", label: "Deductions", icon: "remove-circle-outline" },
];

function showMsg(msg: string, title = "Masters") {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

export default function MastersScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin" || user?.role === "sub_admin";

  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState<string>("");
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  useEffect(() => {
    if (globalCid) setCompanyId(globalCid);
  }, [globalCid]);
  const [tab, setTab] = useState<MasterType>("group");
  const [items, setItems] = useState<Master[]>([]);
  const [loading, setLoading] = useState(false);
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);

  // Group editor state
  const [employees, setEmployees] = useState<EmployeeLite[]>([]);
  const [editing, setEditing] = useState<Master | null>(null);
  const [selectedMemberIds, setSelectedMemberIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!isSuper) return;
    (async () => {
      try {
        const r = await api<{ companies: Company[] }>("/companies");
        // Iter 68 — Alphabetical company list for consistent UX
        const sorted = (r.companies || []).slice().sort((a, b) =>
          (a.name || "").localeCompare(b.name || "", "en", { sensitivity: "base" }),
        );
        setCompanies(sorted);
        if (sorted.length && !companyId) setCompanyId(sorted[0].company_id);
      } catch (e: any) {
        showMsg(e?.message || "Could not load companies");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSuper]);

  const loadItems = useCallback(async () => {
    // Iter 77 - Masters is now globally scoped: no firm picker required.
    // Query without company_id -> super/sub admin sees ALL firm masters +
    // any ``__global__``-scoped entries.
    setLoading(true);
    try {
      const r = await api<{ items: Master[] }>(
        `/admin/masters?type=${tab}`,
      );
      // Iter 68 - Alphabetise the master list for consistent readability.
      const sorted = (r.items || []).slice().sort((a, b) =>
        (a.name || "").localeCompare(b.name || "", "en", { sensitivity: "base" }),
      );
      setItems(sorted);
    } catch (e: any) {
      showMsg(e?.message || "Could not load masters");
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => {
    void loadItems();
  }, [loadItems]);
  useOnRefresh(loadItems);

  const loadEmployees = useCallback(async () => {
    // For group membership picker, still need employees. Load without firm
    // filter so we get everyone across all firms.
    try {
      const r = await api<{ employees: EmployeeLite[] }>(
        `/admin/employees`,
      );
      setEmployees(r.employees || []);
    } catch {
      setEmployees([]);
    }
  }, []);

  useEffect(() => {
    if (tab === "group") void loadEmployees();
  }, [tab, loadEmployees]);

  const create = async () => {
    const name = newName.trim();
    if (!name) return showMsg("Enter a name");
    // Iter 68 - Clear the typed value immediately so the input is ready for
    // the next entry, regardless of whether the API call succeeds or fails.
    const nameToCreate = name;
    setNewName("");
    setSaving(true);
    try {
      // Iter 77 - Masters are now created with global scope.
      await api("/admin/masters", {
        method: "POST",
        body: { type: tab, company_id: "__global__", name: nameToCreate, member_user_ids: [] },
      });
      await loadItems();
    } catch (e: any) {
      // Surface a friendly message and restore the typed value so the user
      // can correct + retry without retyping.
      const err = e?.message || "Failed to create";
      showMsg(err);
      if (
        !/already exists/i.test(err) &&
        !/duplicate/i.test(err)
      ) {
        setNewName(nameToCreate);
      }
    } finally {
      setSaving(false);
    }
  };

  const remove = async (m: Master) => {
    if (Platform.OS === "web") {
      if (!globalThis.confirm(`Delete ${tab} "${m.name}"?`)) return;
    }
    try {
      await api(`/admin/masters/${m.master_id}`, { method: "DELETE" });
      await loadItems();
    } catch (e: any) {
      showMsg(e?.message || "Delete failed");
    }
  };

  const openGroupEditor = (m: Master) => {
    setEditing(m);
    setSelectedMemberIds(new Set(m.member_user_ids || []));
  };

  const saveGroup = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await api(`/admin/masters/${editing.master_id}`, {
        method: "PATCH",
        body: {
          type: "group",
          company_id: editing.company_id,
          name: editing.name,
          member_user_ids: Array.from(selectedMemberIds),
        },
      });
      setEditing(null);
      setSelectedMemberIds(new Set());
      await loadItems();
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const toggleMember = (uid: string) => {
    setSelectedMemberIds((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  };

  const memberCount = useMemo(
    () => (m: Master) => (m.member_user_ids ? m.member_user_ids.length : 0),
    [],
  );

  if (!isSuper) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Only Super/Sub-admins can manage masters.</Text>
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
            <Text style={styles.h1}>Employee Masters</Text>
            <Text style={styles.hsub}>
              Groups · Departments · Designations — used across attendance sheets & reports.
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Iter 77c — Shift Master shortcut (asked by user: Shift Master
            was missing from Masters). Opens the global Shift Master
            catalogue screen. */}
        <Pressable
          onPress={() => router.push("/shift-master")}
          style={styles.shortcutCard}
          testID="mst-open-shift-master"
        >
          <View style={styles.shortcutIcon}>
            <Ionicons name="time-outline" size={20} color={colors.brand} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.shortcutTitle}>Shift Master</Text>
            <Text style={styles.shortcutSub}>
              Global shift catalogue (Day, Night, General ...). Assigned per
              employee under Attendance Policy.
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
        </Pressable>

        {/* Iter 77 - Masters are now GLOBALLY scoped. The firm picker used
            to live here; we removed it because the list already merges
            all firms + adding a new master creates it under the
            "__global__" scope so every firm can pick it. */}
        <View style={styles.globalHintCard}>
          <Ionicons name="globe-outline" size={16} color={colors.brand} />
          <Text style={styles.globalHintTxt}>
            Global masters - visible to every firm. Add a new entry below
            and it becomes available across the entire organisation.
          </Text>
        </View>

        {/* Tabs */}
        <View style={styles.tabsRow}>
          {TABS.map((t) => (
            <Pressable
              key={t.key}
              onPress={() => setTab(t.key)}
              style={[styles.tab, tab === t.key && styles.tabActive]}
              testID={`mst-tab-${t.key}`}
            >
              <Ionicons
                name={t.icon}
                size={14}
                color={tab === t.key ? "#fff" : colors.onSurfaceSecondary}
              />
              <Text
                style={[
                  styles.tabTxt,
                  { color: tab === t.key ? "#fff" : colors.onSurfaceSecondary },
                ]}
              >
                {t.label}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Add row */}
        <View style={styles.card}>
          <Text style={styles.label}>Add {TABS.find((t) => t.key === tab)?.label.slice(0, -1)}</Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <TextInput
              testID="mst-name"
              value={newName}
              onChangeText={setNewName}
              onSubmitEditing={create}
              returnKeyType="done"
              blurOnSubmit={false}
              placeholder={
                tab === "group"
                  ? "e.g. Karol Bagh Site A"
                  : tab === "department"
                    ? "e.g. HR, Finance, Ops"
                    : tab === "designation"
                      ? "e.g. Manager, Guard, Housekeeping"
                      : tab === "allowance"
                        ? "e.g. Petrol Allowance, Meal Allowance"
                        : "e.g. Late Fine, Tea & Snacks, Loan Recovery"
              }
              placeholderTextColor={colors.onSurfaceTertiary}
              style={[styles.input, { flex: 1 }]}
            />
            <Pressable
              onPress={create}
              disabled={saving || !newName.trim() || !companyId}
              style={[
                styles.primaryBtn,
                { paddingHorizontal: 16 },
                (saving || !newName.trim() || !companyId) && { opacity: 0.5 },
              ]}
              testID="mst-add"
            >
              {saving ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.primaryBtnTxt}>Add</Text>
              )}
            </Pressable>
          </View>
        </View>

        {/* List */}
        <View style={styles.card}>
          <Text style={styles.stepTitle}>
            {items.length} {TABS.find((t) => t.key === tab)?.label.toLowerCase()}
          </Text>
          {loading ? (
            <ActivityIndicator style={{ marginTop: 12 }} />
          ) : items.length === 0 ? (
            <Text style={styles.smallHint}>No entries yet. Add one above.</Text>
          ) : (
            items.map((m) => (
              <View key={m.master_id} style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowName}>{m.name}</Text>
                  {tab === "group" ? (
                    <Text style={styles.smallHint}>{memberCount(m)} members</Text>
                  ) : null}
                </View>
                {tab === "group" ? (
                  <Pressable
                    onPress={() => openGroupEditor(m)}
                    style={styles.linkBtn}
                    testID={`mst-edit-${m.master_id}`}
                  >
                    <Ionicons name="people-outline" size={14} color={colors.brandPrimary} />
                    <Text style={styles.linkBtnTxt}>Members</Text>
                  </Pressable>
                ) : null}
                <Pressable
                  onPress={() => remove(m)}
                  style={styles.iconBtn}
                  testID={`mst-del-${m.master_id}`}
                >
                  <Ionicons name="trash-outline" size={16} color="#B02A2A" />
                </Pressable>
              </View>
            ))
          )}
        </View>

        {/* Group member editor */}
        {editing ? (
          <View style={styles.card}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <Ionicons name="people-outline" size={18} color={colors.brandPrimary} />
              <Text style={styles.stepTitle}>Members of “{editing.name}”</Text>
              <View style={{ flex: 1 }} />
              <Pressable onPress={() => setEditing(null)}>
                <Ionicons name="close" size={20} color={colors.onSurfaceSecondary} />
              </Pressable>
            </View>
            {employees.length === 0 ? (
              <Text style={styles.smallHint}>No employees found for this firm.</Text>
            ) : (
              employees.map((e) => {
                const on = selectedMemberIds.has(e.user_id);
                return (
                  <Pressable
                    key={e.user_id}
                    onPress={() => toggleMember(e.user_id)}
                    style={styles.memberRow}
                  >
                    <Ionicons
                      name={on ? "checkbox" : "square-outline"}
                      size={20}
                      color={on ? colors.brandPrimary : colors.onSurfaceTertiary}
                    />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.rowName}>{e.name}</Text>
                      {e.employee_code ? (
                        <Text style={styles.smallHint}>#{e.employee_code}</Text>
                      ) : null}
                    </View>
                  </Pressable>
                );
              })
            )}
            <Pressable
              onPress={saveGroup}
              style={[styles.primaryBtn, saving && { opacity: 0.5 }]}
              disabled={saving}
              testID="mst-save-members"
            >
              {saving ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.primaryBtnTxt}>
                  Save {selectedMemberIds.size} member{selectedMemberIds.size === 1 ? "" : "s"}
                </Text>
              )}
            </Pressable>
          </View>
        ) : null}

        <View style={{ height: 40 }} />
      </ScrollView>
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
  scroll: { padding: spacing.lg, maxWidth: 960, alignSelf: "center", width: "100%" },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: { marginTop: 8, color: colors.onSurfaceSecondary, textAlign: "center" },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  label: {
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    fontWeight: "800",
    marginBottom: 6,
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
  stepTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800", marginBottom: 4 },
  smallHint: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 2 },
  tabsRow: { flexDirection: "row", gap: 8, marginBottom: 10, flexWrap: "wrap" },
  tab: {
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 999,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.divider,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  tabActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12, fontWeight: "700" },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  rowName: { color: colors.onSurface, fontSize: 14, fontWeight: "700" },
  memberRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    marginTop: 10,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800" },
  linkBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    backgroundColor: colors.brandTertiary,
  },
  linkBtnTxt: { color: colors.brandPrimary, fontSize: 12, fontWeight: "700" },
  iconBtn: {
    padding: 6,
    borderRadius: 6,
    backgroundColor: "#FBE9E9",
  },
  // Iter 77c — Shift Master shortcut card
  shortcutCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.divider,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  shortcutIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  shortcutTitle: {
    color: colors.onSurface,
    fontWeight: "800",
    fontSize: type.base,
  },
  shortcutSub: {
    color: colors.onSurfaceSecondary,
    fontSize: 11,
    marginTop: 2,
  },
  globalHintCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    padding: 10,
    marginBottom: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  globalHintTxt: {
    flex: 1,
    color: colors.onSurface,
    fontSize: 12,
    lineHeight: 16,
  },
});
