/**
 * Employee Groups — Iter 75.
 *
 * Admin-only screen for managing per-firm attendance/salary policy
 * templates ("groups"). Companies define named groups like "Worker",
 * "Staff", "Office" — each carrying a full attendance policy (shift,
 * weekly-off, working hours, CL/PL days, salary tiers, OT allow,
 * full-day / half-day hours).
 *
 * Editing a group offers a "Push to members" toggle: when ON, the new
 * template is materialised onto every existing member of that group
 * (individual salary + bio_code are preserved unless the admin also
 * opts into `overwrite_salary`).
 *
 * Backend: /api/admin/employee-groups {GET,POST,PATCH,DELETE,/apply}
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
  Switch,
  Modal,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, shadow, spacing, type } from "@/src/theme";

type Policy = {
  salary?: number;
  salary_mode?: "monthly" | "daily" | "hourly";
  salary_1?: number; day_1?: number;
  salary_2?: number; day_2?: number;
  salary_3?: number; day_3?: number;
  shift_name?: string | null;
  working_hours?: number;
  ot_allow?: boolean;
  full_day_salary?: boolean;
  fullday_hours?: number;
  halfday_hours?: number;
  cl_days?: number;
  pl_days?: number;
  weekly_off?: number; // 0=Sun..6=Sat
  week_off_min_hours?: number;
  weekly_off_attendance?: boolean;
};

type Group = {
  group_id: string;
  company_id: string;
  name: string;
  description?: string | null;
  policy?: Policy;
  member_count?: number;
  updated_at?: string;
};

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const showMsg = (title: string, body: string) => {
  if (Platform.OS === "web") window.alert(`${title}\n\n${body}`);
  else Alert.alert(title, body);
};

const confirm = (title: string, body: string): Promise<boolean> =>
  new Promise((resolve) => {
    if (Platform.OS === "web") {
      resolve(window.confirm(`${title}\n\n${body}`));
      return;
    }
    Alert.alert(title, body, [
      { text: "Cancel", style: "cancel", onPress: () => resolve(false) },
      { text: "Continue", style: "destructive", onPress: () => resolve(true) },
    ]);
  });

function n(v: any): number | undefined {
  if (v === "" || v === null || v === undefined) return undefined;
  const x = Number(v);
  return Number.isFinite(x) ? x : undefined;
}

export default function EmployeeGroupsScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const { selectedCompanyId: selectedCid } = useSelectedCompany();
  const isSuper = user?.role === "super_admin";
  const isAdmin = user?.role === "super_admin" || user?.role === "company_admin" || user?.role === "sub_admin";

  const [groups, setGroups] = useState<Group[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<Group | null>(null);
  const [creating, setCreating] = useState(false);

  const effectiveCid = useMemo(() => {
    if (!isSuper) return null;
    return selectedCid && selectedCid !== "all" ? selectedCid : null;
  }, [isSuper, selectedCid]);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    setLoading(true);
    setErr(null);
    try {
      const qs = effectiveCid ? `?company_id=${encodeURIComponent(effectiveCid)}` : "";
      const res = await api<{ groups: Group[] }>(`/admin/employee-groups${qs}`);
      setGroups(res.groups || []);
    } catch (e: any) {
      setErr(e?.message || "Could not load groups");
    } finally {
      setLoading(false);
    }
  }, [isAdmin, effectiveCid]);

  useEffect(() => {
    load();
  }, [load]);

  const onDelete = async (g: Group) => {
    const ok = await confirm(
      "Delete group?",
      `Delete “${g.name}”? Members keep their current policy but lose the group link.\n\n(${g.member_count ?? 0} members)`,
    );
    if (!ok) return;
    try {
      await api(`/admin/employee-groups/${g.group_id}`, { method: "DELETE" });
      await load();
    } catch (e: any) {
      showMsg("Delete failed", e?.message || "Could not delete group.");
    }
  };

  const onPushToMembers = async (g: Group) => {
    if (!g.member_count) {
      showMsg("Push to members", "This group has no members yet.");
      return;
    }
    const overwriteSalary = await confirm(
      `Push “${g.name}” template?`,
      `Apply this template to ${g.member_count} employee${g.member_count === 1 ? "" : "s"}.\n\nIndividual salary and biometric IDs will be PRESERVED. Continue?`,
    );
    if (!overwriteSalary) return;
    try {
      const res = await api<{ propagated_to: number }>(
        `/admin/employee-groups/${g.group_id}/apply`,
        { method: "POST" },
      );
      showMsg("Applied", `Policy pushed to ${res.propagated_to} employee${res.propagated_to === 1 ? "" : "s"}.`);
      await load();
    } catch (e: any) {
      showMsg("Push failed", e?.message || "Could not push template.");
    }
  };

  if (!isAdmin) {
    return (
      <SafeAreaView style={styles.centerScreen}>
        <Ionicons name="lock-closed-outline" size={40} color={colors.brand} />
        <Text style={styles.errTitle}>Admins only</Text>
        <Pressable onPress={() => router.replace("/(tabs)" as any)} style={styles.retryBtn}>
          <Text style={styles.retryBtnTxt}>Back to dashboard</Text>
        </Pressable>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Header */}
        <View style={styles.headerRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Employee Groups</Text>
            <Text style={styles.subtitle}>
              Reusable attendance & salary policy templates per firm. New employees
              tagged with a group name automatically inherit the template. Editing a
              group can push updates to every existing member.
            </Text>
          </View>
          {isSuper && (
            <View style={styles.firmPicker} testID="firm-picker-wrap">
              <CompanyPicker />
            </View>
          )}
          <Pressable
            style={styles.cta}
            onPress={() => setCreating(true)}
            testID="grp-new-btn"
          >
            <Ionicons name="add" size={18} color={colors.onCta} />
            <Text style={styles.ctaText}>New group</Text>
          </Pressable>
        </View>

        {loading ? (
          <View style={{ padding: 32, alignItems: "center" }}>
            <ActivityIndicator color={colors.brand} size="large" />
          </View>
        ) : err ? (
          <View style={styles.errBox}>
            <Ionicons name="alert-circle" size={16} color={colors.error} />
            <Text style={styles.errText}>{err}</Text>
          </View>
        ) : isSuper && !effectiveCid ? (
          <View style={styles.emptyCard}>
            <Ionicons name="business-outline" size={32} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyTitle}>Pick a firm</Text>
            <Text style={styles.emptyBody}>
              Groups are per-firm. Select a company from the picker above to see or
              create group policies.
            </Text>
          </View>
        ) : groups.length === 0 ? (
          <View style={styles.emptyCard}>
            <Ionicons name="people-outline" size={32} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyTitle}>No groups yet</Text>
            <Text style={styles.emptyBody}>
              Create your first group (e.g. “Worker”, “Staff”, “Office”). Then tag
              your employees with the group name to auto-apply the policy.
            </Text>
          </View>
        ) : (
          groups.map((g) => (
            <View key={g.group_id} style={styles.card} testID={`grp-${g.name}`}>
              <View style={styles.cardHeader}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardTitle}>{g.name}</Text>
                  {g.description ? (
                    <Text style={styles.cardSub}>{g.description}</Text>
                  ) : null}
                </View>
                <View style={styles.memberBadge}>
                  <Ionicons name="people-outline" size={12} color={colors.onBrandTertiary} />
                  <Text style={styles.memberBadgeTxt}>
                    {g.member_count ?? 0} member{g.member_count === 1 ? "" : "s"}
                  </Text>
                </View>
              </View>

              <View style={styles.policyGrid}>
                <MetaChip label="Shift" value={g.policy?.shift_name || "—"} />
                <MetaChip
                  label="Weekly off"
                  value={
                    typeof g.policy?.weekly_off === "number"
                      ? DAYS[g.policy.weekly_off]
                      : "—"
                  }
                />
                <MetaChip
                  label="Working hrs"
                  value={g.policy?.working_hours ? `${g.policy.working_hours} h` : "—"}
                />
                <MetaChip
                  label="Full-day hrs"
                  value={g.policy?.fullday_hours ? `${g.policy.fullday_hours} h` : "—"}
                />
                <MetaChip
                  label="Half-day hrs"
                  value={g.policy?.halfday_hours ? `${g.policy.halfday_hours} h` : "—"}
                />
                <MetaChip
                  label="CL / PL"
                  value={`${g.policy?.cl_days ?? "—"} / ${g.policy?.pl_days ?? "—"}`}
                />
                <MetaChip
                  label="OT"
                  value={g.policy?.ot_allow ? "Allowed" : "No"}
                />
              </View>

              <View style={styles.actionsRow}>
                <Pressable
                  style={styles.secondaryBtn}
                  onPress={() => setEditing(g)}
                  testID={`grp-edit-${g.name}`}
                >
                  <Ionicons name="create-outline" size={14} color={colors.brand} />
                  <Text style={styles.secondaryBtnTxt}>Edit</Text>
                </Pressable>
                <Pressable
                  style={styles.secondaryBtn}
                  onPress={() => onPushToMembers(g)}
                  testID={`grp-push-${g.name}`}
                >
                  <Ionicons name="cloud-upload-outline" size={14} color={colors.brand} />
                  <Text style={styles.secondaryBtnTxt}>Push to members</Text>
                </Pressable>
                <Pressable
                  style={[styles.secondaryBtn, styles.dangerBtn]}
                  onPress={() => onDelete(g)}
                  testID={`grp-del-${g.name}`}
                >
                  <Ionicons name="trash-outline" size={14} color={colors.error} />
                  <Text style={[styles.secondaryBtnTxt, { color: colors.error }]}>
                    Delete
                  </Text>
                </Pressable>
              </View>
            </View>
          ))
        )}
      </ScrollView>

      {/* Create modal */}
      <GroupEditor
        visible={creating}
        initial={null}
        companyId={effectiveCid}
        onClose={() => setCreating(false)}
        onSaved={async () => {
          setCreating(false);
          await load();
        }}
      />

      {/* Edit modal */}
      <GroupEditor
        visible={!!editing}
        initial={editing}
        companyId={effectiveCid}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          setEditing(null);
          await load();
        }}
      />
    </SafeAreaView>
  );
}

function MetaChip({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metaChip}>
      <Text style={styles.metaChipLabel}>{label}</Text>
      <Text style={styles.metaChipValue} numberOfLines={1}>{value}</Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Create / Edit modal
// ---------------------------------------------------------------------------
function GroupEditor({
  visible,
  initial,
  companyId,
  onClose,
  onSaved,
}: {
  visible: boolean;
  initial: Group | null;
  companyId: string | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [policy, setPolicy] = useState<Policy>({});
  const [propagate, setPropagate] = useState(true);
  const [overwriteSalary, setOverwriteSalary] = useState(false);
  const [saving, setSaving] = useState(false);
  const isEdit = !!initial;

  useEffect(() => {
    if (visible) {
      setName(initial?.name || "");
      setDesc(initial?.description || "");
      setPolicy({ ...(initial?.policy || {}) });
      setPropagate(true);
      setOverwriteSalary(false);
    }
  }, [visible, initial]);

  const setP = <K extends keyof Policy>(k: K, v: Policy[K]) =>
    setPolicy((prev) => ({ ...prev, [k]: v }));

  const save = async () => {
    if (!name.trim()) {
      showMsg("Missing name", "Group name is required.");
      return;
    }
    setSaving(true);
    try {
      const body: any = {
        name: name.trim(),
        description: desc.trim() || null,
        policy,
      };
      if (companyId) body.company_id = companyId;
      if (isEdit) {
        const qs = new URLSearchParams();
        if (propagate) qs.set("propagate", "true");
        if (overwriteSalary) qs.set("overwrite_salary", "true");
        const query = qs.toString();
        await api(
          `/admin/employee-groups/${initial!.group_id}${query ? "?" + query : ""}`,
          { method: "PATCH", body },
        );
      } else {
        await api("/admin/employee-groups", { method: "POST", body });
      }
      onSaved();
    } catch (e: any) {
      showMsg("Save failed", e?.message || "Could not save group.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <View style={editorStyles.root}>
        <Pressable style={editorStyles.backdrop} onPress={onClose} />
        <View style={editorStyles.sheet}>
          <View style={editorStyles.sheetHeader}>
            <Text style={editorStyles.sheetTitle}>
              {isEdit ? `Edit “${initial?.name}”` : "New group"}
            </Text>
            <Pressable onPress={onClose} hitSlop={8}>
              <Ionicons name="close" size={22} color={colors.onSurfaceSecondary} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={editorStyles.scroll}>
            <Field label="Group name">
              <TextInput
                value={name}
                onChangeText={setName}
                placeholder="e.g. Worker, Staff, Office"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={editorStyles.input}
              />
            </Field>
            <Field label="Description (optional)">
              <TextInput
                value={desc}
                onChangeText={setDesc}
                placeholder="Short note describing the group"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={editorStyles.input}
              />
            </Field>

            <Text style={editorStyles.section}>Attendance</Text>
            <View style={editorStyles.row}>
              <Field label="Shift name" style={{ flex: 1 }}>
                <TextInput
                  value={policy.shift_name || ""}
                  onChangeText={(t) => setP("shift_name", t || null)}
                  placeholder="e.g. General"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={editorStyles.input}
                />
              </Field>
              <Field label="Working hours" style={{ flex: 1 }}>
                <TextInput
                  value={policy.working_hours?.toString() || ""}
                  onChangeText={(t) => setP("working_hours", n(t))}
                  placeholder="8"
                  keyboardType="decimal-pad"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={editorStyles.input}
                />
              </Field>
            </View>

            <View style={editorStyles.row}>
              <Field label="Full-day hrs" style={{ flex: 1 }}>
                <TextInput
                  value={policy.fullday_hours?.toString() || ""}
                  onChangeText={(t) => setP("fullday_hours", n(t))}
                  keyboardType="decimal-pad"
                  placeholder="6"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={editorStyles.input}
                />
              </Field>
              <Field label="Half-day hrs" style={{ flex: 1 }}>
                <TextInput
                  value={policy.halfday_hours?.toString() || ""}
                  onChangeText={(t) => setP("halfday_hours", n(t))}
                  keyboardType="decimal-pad"
                  placeholder="3"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={editorStyles.input}
                />
              </Field>
            </View>

            <View style={editorStyles.row}>
              <Field label="Weekly off" style={{ flex: 1 }}>
                <View style={editorStyles.dayRow}>
                  {DAYS.map((d, i) => (
                    <Pressable
                      key={d}
                      onPress={() => setP("weekly_off", i)}
                      style={[
                        editorStyles.dayPill,
                        policy.weekly_off === i && editorStyles.dayPillOn,
                      ]}
                    >
                      <Text
                        style={[
                          editorStyles.dayPillTxt,
                          policy.weekly_off === i && editorStyles.dayPillTxtOn,
                        ]}
                      >
                        {d}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              </Field>
            </View>

            <View style={editorStyles.row}>
              <Field label="CL days" style={{ flex: 1 }}>
                <TextInput
                  value={policy.cl_days?.toString() || ""}
                  onChangeText={(t) => setP("cl_days", n(t))}
                  keyboardType="number-pad"
                  placeholder="13"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={editorStyles.input}
                />
              </Field>
              <Field label="PL days" style={{ flex: 1 }}>
                <TextInput
                  value={policy.pl_days?.toString() || ""}
                  onChangeText={(t) => setP("pl_days", n(t))}
                  keyboardType="number-pad"
                  placeholder="12"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={editorStyles.input}
                />
              </Field>
            </View>

            <ToggleRow
              label="Allow overtime (OT)"
              value={!!policy.ot_allow}
              onChange={(v) => setP("ot_allow", v)}
            />
            <ToggleRow
              label="Weekly-off counts as attendance"
              value={!!policy.weekly_off_attendance}
              onChange={(v) => setP("weekly_off_attendance", v)}
            />

            <Text style={editorStyles.section}>Salary tiers</Text>
            <Text style={editorStyles.hint}>
              Tier bonuses unlock when present-days ≥ Day N. Salary column stays
              per-employee unless you tick &quot;Overwrite salary&quot; below.
            </Text>
            {[1, 2, 3].map((i) => (
              <View key={i} style={editorStyles.row}>
                <Field label={`Salary ${i}`} style={{ flex: 1 }}>
                  <TextInput
                    value={(policy as any)[`salary_${i}`]?.toString() || ""}
                    onChangeText={(t) =>
                      setPolicy((p) => ({ ...p, [`salary_${i}`]: n(t) } as any))
                    }
                    keyboardType="decimal-pad"
                    placeholder="0"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    style={editorStyles.input}
                  />
                </Field>
                <Field label={`Day ${i}`} style={{ flex: 1 }}>
                  <TextInput
                    value={(policy as any)[`day_${i}`]?.toString() || ""}
                    onChangeText={(t) =>
                      setPolicy((p) => ({ ...p, [`day_${i}`]: n(t) } as any))
                    }
                    keyboardType="number-pad"
                    placeholder="0"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    style={editorStyles.input}
                  />
                </Field>
              </View>
            ))}

            {isEdit && (
              <>
                <Text style={editorStyles.section}>Propagation</Text>
                <ToggleRow
                  label={`Push to ${initial?.member_count ?? 0} existing members`}
                  value={propagate}
                  onChange={setPropagate}
                />
                {propagate && (
                  <ToggleRow
                    label="Also overwrite each employee's salary"
                    value={overwriteSalary}
                    onChange={setOverwriteSalary}
                  />
                )}
                <Text style={editorStyles.hint}>
                  Individual biometric IDs are always preserved.
                </Text>
              </>
            )}

            <Pressable
              onPress={save}
              disabled={saving}
              style={[editorStyles.saveBtn, saving && { opacity: 0.6 }]}
              testID="grp-save-btn"
            >
              {saving ? (
                <ActivityIndicator color={colors.onCta} size="small" />
              ) : (
                <>
                  <Ionicons name="save-outline" size={16} color={colors.onCta} />
                  <Text style={editorStyles.saveBtnTxt}>
                    {isEdit ? "Save changes" : "Create group"}
                  </Text>
                </>
              )}
            </Pressable>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function Field({
  label,
  children,
  style,
}: {
  label: string;
  children: React.ReactNode;
  style?: any;
}) {
  return (
    <View style={[editorStyles.field, style]}>
      <Text style={editorStyles.fieldLabel}>{label}</Text>
      {children}
    </View>
  );
}

function ToggleRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <View style={editorStyles.toggleRow}>
      <Text style={editorStyles.toggleLabel}>{label}</Text>
      <Switch value={value} onValueChange={onChange} />
    </View>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.surface },
  centerScreen: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.lg,
    gap: spacing.sm,
    backgroundColor: colors.surface,
  },
  errTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  retryBtn: {
    marginTop: spacing.md,
    backgroundColor: colors.brand,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
  },
  retryBtnTxt: { color: colors.onBrandPrimary, fontWeight: "700" },
  scroll: {
    padding: spacing.lg,
    gap: spacing.md,
    maxWidth: 1100,
    width: "100%",
    alignSelf: "center",
    paddingBottom: 80,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.md,
    flexWrap: "wrap",
  },
  title: { fontSize: type.h1, fontWeight: "800", color: colors.onSurface },
  subtitle: { color: colors.onSurfaceSecondary, marginTop: 4, lineHeight: 20 },
  firmPicker: { minWidth: 200 },
  cta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.cta,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: radius.pill,
    ...shadow.cta,
  },
  ctaText: { color: colors.onCta, fontWeight: "700" },

  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FEE2E2",
    padding: spacing.sm,
    borderRadius: radius.md,
  },
  errText: { color: colors.error, flex: 1 },

  emptyCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.xl,
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  emptyTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  emptyBody: { color: colors.onSurfaceSecondary, textAlign: "center" },

  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
    ...shadow.card,
  },
  cardHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  cardTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  cardSub: { color: colors.onSurfaceSecondary, marginTop: 2 },
  memberBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.brandTertiary,
    paddingVertical: 4,
    paddingHorizontal: 8,
    borderRadius: radius.pill,
  },
  memberBadgeTxt: { color: colors.onBrandTertiary, fontWeight: "700", fontSize: type.sm },

  policyGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  metaChip: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    paddingVertical: 8,
    paddingHorizontal: 10,
    minWidth: 110,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  metaChipLabel: {
    color: colors.onSurfaceTertiary,
    fontSize: 10,
    letterSpacing: 0.6,
    textTransform: "uppercase",
    fontWeight: "700",
  },
  metaChipValue: { color: colors.onSurface, fontWeight: "600", marginTop: 2 },

  actionsRow: {
    flexDirection: "row",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  secondaryBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderWidth: 1,
    borderColor: colors.brand,
    borderRadius: radius.pill,
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  secondaryBtnTxt: { color: colors.brand, fontWeight: "700", fontSize: type.sm },
  dangerBtn: { borderColor: colors.error },
});

const editorStyles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.4)" },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    maxHeight: "94%",
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  sheetTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  scroll: { padding: spacing.lg, gap: spacing.md, paddingBottom: 60 },
  section: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "700",
    letterSpacing: 0.5,
    textTransform: "uppercase",
    marginTop: spacing.md,
  },
  hint: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: -6 },
  row: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  field: { gap: 6 },
  fieldLabel: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    fontWeight: "600",
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.sm,
    color: colors.onSurface,
    backgroundColor: colors.surface,
    minHeight: 42,
    ...Platform.select({ web: { outlineWidth: 0 as any } }),
  },
  dayRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  dayPill: {
    paddingVertical: 6,
    paddingHorizontal: 10,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
  },
  dayPillOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  dayPillTxt: { color: colors.onSurface, fontWeight: "600", fontSize: type.sm },
  dayPillTxtOn: { color: colors.onBrandPrimary },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 6,
  },
  toggleLabel: { color: colors.onSurface, flex: 1, marginRight: 12 },
  saveBtn: {
    marginTop: spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: colors.cta,
    paddingVertical: 14,
    borderRadius: radius.md,
    ...shadow.cta,
  },
  saveBtnTxt: { color: colors.onCta, fontWeight: "700" },
});
