/**
 * Per-employee Attendance Policy override - Iter 77.
 *
 * Lets a Super / Company Admin override attendance policy fields for a
 * single employee. Any field left blank inherits the firm-level default.
 *
 * Route: /employee-attendance-policy?user_id=<uid>
 *
 * Backend:
 *   GET    /api/admin/employees/{uid}/attendance-policy-override
 *   PUT    /api/admin/employees/{uid}/attendance-policy-override
 *   DELETE /api/admin/employees/{uid}/attendance-policy-override
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Override = {
  weekly_off_days?: number[] | null;
  grace_minutes_late?: number | null;
  half_day_hours?: number | null;
  full_day_hours?: number | null;
  overtime_threshold_hours?: number | null;   // deprecated (Iter 77)
  overtime_multiplier?: number | null;        // deprecated (Iter 77)
  ot_allowed?: boolean | null;                // Iter 77 - single toggle
  duty_hours_rounding_minutes?: number | null;
  standard_working_hours?: number | null;
  shift_id?: string | null;
  auto_shift_by_first_punch?: boolean | null; // Iter 77c
  week_off_paid_when_absent?: boolean | null; // Iter 77d
  night_shift_allowance_enabled?: boolean | null;
  night_shift_start?: string | null;
  night_shift_end?: string | null;
  notes?: string | null;
};

type Resp = {
  user_id: string;
  name: string;
  employee_code?: string;
  override: Override;
  firm_policy: any;
  has_override: boolean;
};

const showMsg = (msg: string, title = "Attendance policy") => {
  if (Platform.OS === "web") window.alert(`${title}\n\n${msg}`);
  else Alert.alert(title, msg);
};

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Force any keystrokes into a strict HH:MM shape.
 *  - Digits only (colon is auto-inserted)
 *  - Auto-inserts ":" after the first two digits
 *  - Clamps hours to 00-23 and minutes to 00-59
 *  - Accepts "8" -> "8", "20" -> "20", "2000" -> "20:00", "26:99" -> "23:59"
 */
function formatTimeInput(raw: string): string {
  const digits = (raw || "").replace(/\D/g, "").slice(0, 4);
  if (!digits) return "";
  if (digits.length <= 2) {
    // hours only - clamp when 2 digits typed
    if (digits.length === 2) {
      const h = Math.min(23, parseInt(digits, 10));
      return String(h).padStart(2, "0");
    }
    return digits;
  }
  const h = Math.min(23, parseInt(digits.slice(0, 2), 10));
  const m = Math.min(59, parseInt(digits.slice(2), 10));
  const mm =
    digits.length === 3
      ? String(m)                // still typing minutes: "8:3"
      : String(m).padStart(2, "0"); // full HH:MM once 4 digits
  return `${String(h).padStart(2, "0")}:${mm}`;
}

function isValidHHMM(v?: string | null): boolean {
  if (!v) return true; // empty = inherit, allowed
  return /^\d{2}:\d{2}$/.test(v) && Number(v.slice(0, 2)) < 24 && Number(v.slice(3)) < 60;
}

export default function EmployeeAttendancePolicyScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const params = useLocalSearchParams<{ user_id?: string }>();
  const uid = typeof params.user_id === "string" ? params.user_id : "";
  const canEdit =
    user?.role === "super_admin" || user?.role === "company_admin" ||
    (user?.role as string) === "sub_admin";

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [data, setData] = useState<Resp | null>(null);
  const [ov, setOv] = useState<Override>({});
  const [err, setErr] = useState<string | null>(null);
  // Iter 77 - Shift picker options
  const [shifts, setShifts] = useState<
    { shift_id: string; name: string; start?: string; end?: string }[]
  >([]);

  const load = useCallback(async () => {
    if (!uid) return;
    setLoading(true); setErr(null);
    try {
      const r = await api<Resp>(`/admin/employees/${uid}/attendance-policy-override`);
      setData(r);
      setOv(r.override || {});
    } catch (e: any) {
      setErr(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [uid]);

  useEffect(() => { load(); }, [load]);

  // Iter 77c — Fetch the GLOBAL Shift Master catalogue so the "Assigned
  // shift" picker has real options. Runs once on mount and swallows
  // errors silently — the picker will fall back to its empty state.
  useEffect(() => {
    (async () => {
      try {
        const r = await api<{
          shifts: { shift_id: string; name: string; start?: string; end?: string }[]
        }>("/shift-masters");
        setShifts(
          (r.shifts || [])
            .slice()
            .sort((a, b) =>
              (a.name || "").localeCompare(b.name || "", "en", { sensitivity: "base" }),
            ),
        );
      } catch {
        // ignore - picker shows the empty-state hint
      }
    })();
  }, []);

  const firmDefaults = data?.firm_policy || {};

  const setField = (k: keyof Override, v: any) =>
    setOv((prev) => ({ ...prev, [k]: v === "" || v === null || v === undefined ? undefined : v }));

  const toggleWeeklyOff = (day: number) => {
    setOv((prev) => {
      const cur = (prev.weekly_off_days as number[] | undefined) || [];
      const set = new Set(cur);
      if (set.has(day)) set.delete(day); else set.add(day);
      return { ...prev, weekly_off_days: Array.from(set).sort() };
    });
  };

  const numInput = (
    key: keyof Override,
    placeholder: string,
    fallback: any,
    step = 1,
  ) => {
    const raw = ov[key];
    const val =
      raw === undefined || raw === null || raw === "" ? "" : String(raw);
    return (
      <View style={styles.field}>
        <Text style={styles.label}>{placeholder}</Text>
        <View style={styles.rowInputWrap}>
          <TextInput
            style={styles.input}
            value={val}
            keyboardType="decimal-pad"
            onChangeText={(t) => {
              if (t === "") { setField(key, null); return; }
              const n = Number(t);
              if (!Number.isNaN(n)) setField(key, n);
              else setField(key, t as any);
            }}
            placeholder={
              fallback !== undefined && fallback !== null
                ? `Inherit (${fallback})`
                : "Inherit"
            }
            placeholderTextColor={colors.onSurfaceTertiary}
          />
          {val !== "" ? (
            <Pressable onPress={() => setField(key, null)} style={styles.clearField}>
              <Ionicons name="close-circle" size={16} color={colors.onSurfaceTertiary} />
            </Pressable>
          ) : null}
        </View>
      </View>
    );
  };

  const save = async () => {
    if (!canEdit || saving) return;
    if (!isValidHHMM(ov.night_shift_start) || !isValidHHMM(ov.night_shift_end)) {
      showMsg("Night shift times must be in HH:MM format (e.g. 20:00).");
      return;
    }
    setSaving(true);
    try {
      // Filter out undefined so the backend only stores what's set
      const body: any = {};
      for (const [k, v] of Object.entries(ov)) {
        if (v !== undefined && v !== null && v !== "") body[k] = v;
      }
      await api<{ override: Override }>(
        `/admin/employees/${uid}/attendance-policy-override`,
        { method: "PUT", body },
      );
      // Iter 77c — After a successful save, drop the user back to the
      // employee selection page instead of leaving them on this screen.
      if (router.canGoBack()) {
        router.back();
      } else {
        router.replace("/admin");
      }
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
      setSaving(false);
    }
  };

  const clearAll = async () => {
    if (!canEdit || clearing) return;
    setClearing(true);
    try {
      await api(`/admin/employees/${uid}/attendance-policy-override`, {
        method: "DELETE",
      });
      // Iter 77c — Same UX: return to the picker after clearing.
      if (router.canGoBack()) {
        router.back();
      } else {
        router.replace("/admin");
      }
    } catch (e: any) {
      showMsg(e?.message || "Clear failed");
      setClearing(false);
    }
  };

  const hasAny = useMemo(() => {
    return Object.values(ov).some(
      (v) =>
        v !== undefined &&
        v !== null &&
        v !== "" &&
        !(Array.isArray(v) && v.length === 0),
    );
  }, [ov]);

  if (!canEdit) {
    return (
      <SafeAreaView style={styles.centerScreen}>
        <Ionicons name="lock-closed-outline" size={40} color={colors.brand} />
        <Text style={styles.errTitle}>Admins only</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top", "left", "right"]}>
      <View style={styles.toolbar}>
        <Pressable onPress={() => router.back()} style={styles.iconBtn} hitSlop={8}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Employee Attendance Policy</Text>
          <Text style={styles.subtitle}>
            {data?.name} {data?.employee_code ? `· #${data.employee_code}` : ""}
          </Text>
        </View>
        {data?.has_override ? (
          <View style={styles.overridePill}>
            <Text style={styles.overridePillTxt}>Override active</Text>
          </View>
        ) : null}
      </View>

      {loading ? (
        <View style={{ padding: 48, alignItems: "center" }}>
          <ActivityIndicator color={colors.brand} size="large" />
        </View>
      ) : err ? (
        <View style={styles.errBox}>
          <Ionicons name="alert-circle" size={16} color={colors.error} />
          <Text style={styles.errText}>{err}</Text>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <View style={styles.hintBox}>
            <Ionicons name="information-circle-outline" size={18} color={colors.brand} />
            <Text style={styles.hintTxt}>
              Any field left blank inherits the firm / group default. Only override
              what needs to differ for this employee.
            </Text>
          </View>

          {/* Weekly off */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Weekly off days</Text>
            <View style={styles.dayRow}>
              {DAYS.map((label, idx) => {
                const cur = (ov.weekly_off_days as number[] | undefined) || [];
                const on = cur.includes(idx);
                return (
                  <Pressable
                    key={label}
                    onPress={() => toggleWeeklyOff(idx)}
                    style={[styles.dayChip, on && styles.dayChipOn]}
                    testID={`emp-pol-day-${label}`}
                  >
                    <Text style={[styles.dayChipTxt, on && styles.dayChipTxtOn]}>
                      {label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
            {(!ov.weekly_off_days || (ov.weekly_off_days as number[]).length === 0) ? (
              <Text style={styles.inheritHint}>
                Inheriting firm default:{" "}
                {(firmDefaults.weekly_off_days || [])
                  .map((d: number) => DAYS[d])
                  .join(", ") || "None"}
              </Text>
            ) : (
              <Pressable
                onPress={() => setField("weekly_off_days", null)}
                style={{ marginTop: 4 }}
              >
                <Text style={styles.link}>Reset to inherit</Text>
              </Pressable>
            )}

            {/* Iter 77d — Paid holiday scheme: employee gets full-day
                credit on their week-off day even without punches. */}
            <Pressable
              onPress={() =>
                setField(
                  "week_off_paid_when_absent",
                  !(ov as any).week_off_paid_when_absent,
                )
              }
              style={[styles.toggleRow, { marginTop: 12 }]}
              testID="emp-pol-weekoff-paid"
            >
              <View
                style={[
                  styles.toggleBox,
                  (ov as any).week_off_paid_when_absent && styles.toggleBoxOn,
                ]}
              >
                {(ov as any).week_off_paid_when_absent ? (
                  <Ionicons name="checkmark" size={12} color="#fff" />
                ) : null}
              </View>
              <Text style={styles.toggleTxt}>
                Paid on week-off day (even if absent)
              </Text>
            </Pressable>
            {(ov as any).week_off_paid_when_absent ? (
              <Text style={styles.inheritHint}>
                This employee will receive a full-day attendance credit
                on their weekly-off day even if they don&apos;t punch in.
              </Text>
            ) : null}
          </View>

          {/* Iter 77 - Shift picker (replaces the individual hour-threshold
              fields). The chosen shift's start/end times and derived
              full_day / half_day / grace values apply to this employee. */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Assigned shift</Text>
            {shifts.length === 0 ? (
              <Text style={styles.inheritHint}>
                No shifts defined yet. Create shifts under Shift Master to
                assign one here.
              </Text>
            ) : (
              <View style={styles.dayRow}>
                <Pressable
                  onPress={() => setField("shift_id", null)}
                  style={[styles.dayChip, !ov.shift_id && styles.dayChipOn]}
                  testID="emp-pol-shift-none"
                >
                  <Text style={[styles.dayChipTxt, !ov.shift_id && styles.dayChipTxtOn]}>
                    Inherit
                  </Text>
                </Pressable>
                {shifts.map((s) => {
                  const on = ov.shift_id === s.shift_id;
                  return (
                    <Pressable
                      key={s.shift_id}
                      onPress={() => setField("shift_id", s.shift_id)}
                      style={[styles.dayChip, on && styles.dayChipOn]}
                      testID={`emp-pol-shift-${s.name}`}
                    >
                      <Text style={[styles.dayChipTxt, on && styles.dayChipTxtOn]}>
                        {s.name}
                        {s.start && s.end ? ` (${s.start}-${s.end})` : ""}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            )}
            <Text style={styles.inheritHint}>
              Half-day, Full-day, Standard working hours and Grace minutes
              are derived from the selected shift&apos;s start / end times. To
              customise them, edit the shift under Shift Master.
            </Text>

            {/* Iter 77c - Auto-shift-by-first-in-punch */}
            {shifts.length > 0 ? (
              <Pressable
                onPress={() =>
                  setField(
                    "auto_shift_by_first_punch",
                    !(ov as any).auto_shift_by_first_punch,
                  )
                }
                style={[styles.toggleRow, { marginTop: 12 }]}
                testID="emp-pol-auto-shift"
              >
                <View
                  style={[
                    styles.toggleBox,
                    (ov as any).auto_shift_by_first_punch && styles.toggleBoxOn,
                  ]}
                >
                  {(ov as any).auto_shift_by_first_punch ? (
                    <Ionicons name="checkmark" size={12} color="#fff" />
                  ) : null}
                </View>
                <Text style={styles.toggleTxt}>
                  Auto-select shift by first IN punch
                </Text>
              </Pressable>
            ) : null}
            {(ov as any).auto_shift_by_first_punch ? (
              <Text style={styles.inheritHint}>
                Each day the shift whose START time is closest to the
                employee&apos;s first IN punch is auto-selected. The manually
                assigned shift above is ignored while this toggle is ON.
              </Text>
            ) : null}
          </View>

          {/* Iter 77p — Daily Working HRS column. Used as the divisor
              when converting Total Duty HRS -> Days on the Attendance
              Grid + payroll compute. Overrides the firm's
              standard_working_hours for this employee only. Leave
              blank to inherit the firm default / assigned-shift value. */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Daily Working HRS</Text>
            {numInput(
              "standard_working_hours",
              "Daily Working HRS (used to compute Days)",
              (firmDefaults.standard_working_hours || firmDefaults.full_day_hours || 8),
              0.5,
            )}
            <Text style={styles.inheritHint}>
              Days shown on the Attendance Grid & payroll = Total Duty HRS
              / this value. Leave blank to inherit the firm default
              ({firmDefaults.standard_working_hours || firmDefaults.full_day_hours || 8}h)
              or the assigned shift&apos;s length.
            </Text>
          </View>

          {/* Iter 77 - Overtime: only allow/deny (no govt-style hours/multiplier) */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Overtime</Text>
            <Pressable
              onPress={() =>
                setField("ot_allowed", !(ov as any).ot_allowed)
              }
              style={styles.toggleRow}
              testID="emp-pol-ot-allowed"
            >
              <View
                style={[
                  styles.toggleBox,
                  (ov as any).ot_allowed && styles.toggleBoxOn,
                ]}
              >
                {(ov as any).ot_allowed ? (
                  <Ionicons name="checkmark" size={12} color="#fff" />
                ) : null}
              </View>
              <Text style={styles.toggleTxt}>OT allowed for this employee</Text>
            </Pressable>
            <Text style={styles.inheritHint}>
              When OFF, extra hours beyond the standard shift are ignored for
              this employee&apos;s salary calculation.
            </Text>
          </View>

          {/* Iter 77 - Duty-hours rounding is FIRM-wide (Attendance Policy).
              Removed from the per-employee override screen so the firm's
              chosen rounding value applies uniformly to everyone. */}

          {/* Night shift — temporarily hidden (Iter 77c) per user request.
              Restore by removing the JSX-comment wrapper below. */}
          {false && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Night shift</Text>
            <Pressable
              onPress={() =>
                setField(
                  "night_shift_allowance_enabled",
                  !ov.night_shift_allowance_enabled,
                )
              }
              style={styles.toggleRow}
            >
              <View
                style={[
                  styles.toggleBox,
                  ov.night_shift_allowance_enabled && styles.toggleBoxOn,
                ]}
              >
                {ov.night_shift_allowance_enabled ? (
                  <Ionicons name="checkmark" size={12} color="#fff" />
                ) : null}
              </View>
              <Text style={styles.toggleTxt}>Allowance enabled</Text>
            </Pressable>
            <View style={styles.rowSplit}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Start (HH:MM)</Text>
                <TextInput
                  style={[
                    styles.input,
                    !isValidHHMM(ov.night_shift_start) && styles.inputErr,
                  ]}
                  value={ov.night_shift_start ?? ""}
                  onChangeText={(t) => {
                    const f = formatTimeInput(t);
                    setField("night_shift_start", f || null);
                  }}
                  keyboardType="number-pad"
                  maxLength={5}
                  placeholder={firmDefaults.night_shift_start || "22:00"}
                  placeholderTextColor={colors.onSurfaceTertiary}
                />
              </View>
              <View style={{ width: 12 }} />
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>End (HH:MM)</Text>
                <TextInput
                  style={[
                    styles.input,
                    !isValidHHMM(ov.night_shift_end) && styles.inputErr,
                  ]}
                  value={ov.night_shift_end ?? ""}
                  onChangeText={(t) => {
                    const f = formatTimeInput(t);
                    setField("night_shift_end", f || null);
                  }}
                  keyboardType="number-pad"
                  maxLength={5}
                  placeholder={firmDefaults.night_shift_end || "06:00"}
                  placeholderTextColor={colors.onSurfaceTertiary}
                />
              </View>
            </View>
          </View>
          )}

          {/* Notes */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Notes</Text>
            <TextInput
              style={[styles.input, { minHeight: 60 }]}
              value={ov.notes ?? ""}
              onChangeText={(t) => setField("notes", t || null)}
              placeholder="Why does this employee need an override?"
              placeholderTextColor={colors.onSurfaceTertiary}
              multiline
            />
          </View>

          {/* Actions */}
          <View style={styles.actionRow}>
            <Pressable
              onPress={clearAll}
              disabled={clearing || !data?.has_override}
              style={[
                styles.clearBtn,
                (clearing || !data?.has_override) && { opacity: 0.4 },
              ]}
              testID="emp-pol-clear"
            >
              {clearing ? (
                <ActivityIndicator color={colors.error} size="small" />
              ) : (
                <>
                  <Ionicons name="trash-outline" size={14} color={colors.error} />
                  <Text style={styles.clearBtnTxt}>Clear override</Text>
                </>
              )}
            </Pressable>
            <Pressable
              onPress={save}
              disabled={saving || !hasAny}
              style={[styles.saveBtn, (saving || !hasAny) && { opacity: 0.5 }]}
              testID="emp-pol-save"
            >
              {saving ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <>
                  <Ionicons name="save-outline" size={14} color="#fff" />
                  <Text style={styles.saveBtnTxt}>Save override</Text>
                </>
              )}
            </Pressable>
          </View>
          <View style={{ height: 40 }} />
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  centerScreen: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.lg,
    gap: spacing.sm,
  },
  errTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  toolbar: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  iconBtn: { width: 34, height: 34, alignItems: "center", justifyContent: "center" },
  title: { fontSize: type.h2, fontWeight: "800", color: colors.onSurface },
  subtitle: { color: colors.onSurfaceSecondary, marginTop: 2, fontSize: type.sm },
  overridePill: {
    backgroundColor: colors.brand,
    paddingVertical: 4,
    paddingHorizontal: 10,
    borderRadius: radius.pill,
  },
  overridePillTxt: { color: colors.onBrandPrimary, fontSize: 11, fontWeight: "700" },

  scroll: { padding: spacing.md, gap: spacing.md },
  hintBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    padding: 10,
    borderRadius: radius.md,
    backgroundColor: "rgba(31, 82, 84, 0.06)",
    borderWidth: 1,
    borderColor: colors.brand,
  },
  hintTxt: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    flex: 1,
    lineHeight: 18,
  },
  section: {
    padding: spacing.md,
    borderRadius: radius.lg,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  sectionTitle: {
    color: colors.onSurface,
    fontWeight: "800",
    fontSize: type.md,
    marginBottom: 4,
  },
  field: { marginBottom: 6 },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginBottom: 4 },
  rowInputWrap: { flexDirection: "row", alignItems: "center", gap: 6 },
  input: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 8,
    paddingHorizontal: 12,
    color: colors.onSurface,
    backgroundColor: colors.surface,
    fontSize: type.sm,
    ...Platform.select({ web: { outlineWidth: 0 as any } }),
  },
  inputErr: {
    borderColor: colors.error,
    backgroundColor: "rgba(220, 38, 38, 0.05)",
  },
  clearField: { padding: 4 },
  dayRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  dayChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  dayChipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  dayChipTxt: { color: colors.onSurface, fontSize: type.sm, fontWeight: "600" },
  dayChipTxtOn: { color: colors.onBrandPrimary },
  inheritHint: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    fontStyle: "italic",
    marginTop: 4,
  },
  link: {
    color: colors.brand,
    fontSize: type.sm,
    fontWeight: "600",
    textDecorationLine: "underline",
  },
  toggleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  toggleBox: {
    width: 20,
    height: 20,
    borderRadius: 5,
    borderWidth: 2,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  toggleBoxOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  toggleTxt: { color: colors.onSurface, fontSize: type.sm },
  rowSplit: { flexDirection: "row", alignItems: "flex-start" },
  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FEE2E2",
    padding: spacing.sm,
    borderRadius: radius.md,
    margin: spacing.md,
  },
  errText: { color: colors.error, flex: 1 },
  actionRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: spacing.md,
    marginTop: spacing.sm,
  },
  clearBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.error,
  },
  clearBtnTxt: { color: colors.error, fontWeight: "700", fontSize: type.sm },
  saveBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: radius.md,
    backgroundColor: colors.brand,
    flex: 1,
    justifyContent: "center",
  },
  saveBtnTxt: { color: "#fff", fontWeight: "800", fontSize: type.md },
});
