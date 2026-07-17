import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ActivityIndicator,
  Alert,
  Platform,
  Modal,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { useOnRefresh } from "@/src/context/RefreshBusContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";

/**
 * InlineCompanyPicker — Iter 72 bug-fix.
 *
 * The Attendance Policy page referenced this component but nobody
 * ever defined or imported it, so opening `/attendance-policy` as a
 * super-admin without a `?company_id=` in the URL crashed React with
 * an "InlineCompanyPicker is not defined" ReferenceError.  This
 * lightweight picker fills the gap: it pulls the firm list from
 * `useSelectedCompany()` (already loaded once at boot) and calls
 * `onPick(company_id)` when the operator picks one.  Web uses a
 * native `<select>`; mobile falls back to a chip grid.  When there
 * are no firms yet (fresh install / after the seed wipe) it renders
 * a friendly empty-state with a "Go to Companies" nudge.
 */
function InlineCompanyPicker({ onPick }: { onPick: (cid: string) => void }) {
  const { companies, selectedCompanyId, companiesLoading } = useSelectedCompany();
  const router = useRouter();
  if (companiesLoading) {
    return (
      <View style={{ alignItems: "center", padding: 16 }}>
        <ActivityIndicator color={colors.brandPrimary} />
      </View>
    );
  }
  if (!companies || companies.length === 0) {
    return (
      <View style={{ alignItems: "center", gap: 8 }}>
        <Text style={{ color: colors.onSurfaceSecondary, textAlign: "center" }}>
          No firms exist yet. Create one first — the attendance policy is
          configured per firm.
        </Text>
        <Pressable
          onPress={() => router.push("/companies")}
          style={styles.cta}
          testID="ap-goto-companies"
        >
          <Ionicons name="business" size={16} color={colors.onCta} />
          <Text style={styles.ctaTxt}>Add a firm</Text>
        </Pressable>
      </View>
    );
  }
  if (Platform.OS === "web") {
    return (
      <select
        value={selectedCompanyId || ""}
        onChange={(e) => {
          const v = (e.target as HTMLSelectElement).value;
          if (v) onPick(v);
        }}
        style={{
          padding: 10,
          borderRadius: 8,
          border: `1px solid ${colors.divider}`,
          fontSize: 14,
          width: "100%",
          backgroundColor: colors.surface,
          color: colors.onSurface,
        } as any}
      >
        <option value="">— pick a firm —</option>
        {companies.map((c) => (
          <option key={c.company_id} value={c.company_id}>
            {c.name}
            {c.company_code ? ` · ${c.company_code}` : ""}
          </option>
        ))}
      </select>
    );
  }
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
      {companies.map((c) => (
        <Pressable
          key={c.company_id}
          onPress={() => onPick(c.company_id)}
          style={{
            borderWidth: 1,
            borderColor:
              selectedCompanyId === c.company_id
                ? colors.brandPrimary
                : colors.divider,
            borderRadius: 999,
            paddingHorizontal: 12,
            paddingVertical: 6,
            backgroundColor:
              selectedCompanyId === c.company_id
                ? colors.brandPrimary
                : colors.surface,
          }}
        >
          <Text
            style={{
              color:
                selectedCompanyId === c.company_id ? "#fff" : colors.onSurface,
              fontSize: 13,
              fontWeight: "600",
            }}
          >
            {c.name}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

type Shift = { name: string; start: string; end: string };

type Policy = {
  shifts: Shift[];
  weekly_off_days: number[];
  grace_minutes_late: number;
  half_day_hours: number;
  full_day_hours: number;
  break_hours: number;
  overtime_threshold_hours: number;
  overtime_multiplier: number;
  night_shift_allowance_enabled: boolean;
  night_shift_start: string;
  night_shift_end: string;
  notes?: string | null;
  punch_approval_required?: boolean;
  // Textile industry extensions
  policy_variant?: "policy_1" | "policy_2" | null;
  duty_hours_rounding_minutes?: number;
  standard_working_hours?: number;
  week_off_full_day_payment_default?: boolean;
  // Iter 77d — Minimum working hours on a week-off day for full-day
  // attendance credit. 0 disables the rule.
  week_off_min_working_hours?: number;
  // Iter 131 — OT Calculation config (Textile Policy 2 only):
  // OT hourly rate = (%Basic per-day + %Gross per-day) ÷ full-day hours.
  ot_pct_basic?: number;
  ot_pct_gross?: number;
  // Iter 175 — Policy Master Sub Points.
  policy_master?: Record<string, any>;
};

type PolicyResponse = {
  company_id: string;
  business_category: string | null;
  business_subcategory: string | null;
  weekday_labels: string[];
  policy: Policy;
  is_default_preset: boolean;
};

type Preset = {
  business_category: string;
  label: string;
  policy: Policy;
};

const HHMM_RE = /^[0-2][0-9]:[0-5][0-9]$/;

function normalisePolicy(p: Policy): Policy {
  // Iter 96 — defensive normalisation. Legacy default-preset policy docs
  // (older shape: {workday_hours, grace_minutes, half_day_hours, weekly_off_days,
  // punch_approval_required}) were causing the UI to crash with
  // "Cannot read properties of undefined (reading 'toFixed')" when NumRow tried
  // to render an undefined numeric field. Coerce every numeric field the UI
  // reads to a sane default so the page always renders.
  const anyp = p as any;
  return {
    ...p,
    shifts: (p.shifts || []).map((s) => ({
      name: s.name?.trim() || "Shift",
      start: s.start,
      end: s.end,
    })),
    weekly_off_days: Array.from(new Set((p.weekly_off_days || []).map((d) => Number(d))))
      .filter((d) => d >= 0 && d <= 6)
      .sort((a, b) => a - b),
    grace_minutes_late: Number(p.grace_minutes_late ?? anyp.grace_minutes ?? 10),
    half_day_hours: Number(p.half_day_hours ?? 4),
    full_day_hours: Number(p.full_day_hours ?? anyp.workday_hours ?? 8),
    break_hours: Number(p.break_hours ?? 0),
    overtime_threshold_hours: Number(p.overtime_threshold_hours ?? anyp.workday_hours ?? 8),
    overtime_multiplier: Number(p.overtime_multiplier ?? 1),
    night_shift_allowance_enabled: !!p.night_shift_allowance_enabled,
    night_shift_start: p.night_shift_start || "22:00",
    night_shift_end: p.night_shift_end || "06:00",
    duty_hours_rounding_minutes: Number(p.duty_hours_rounding_minutes ?? 0),
    standard_working_hours: Number(p.standard_working_hours ?? anyp.workday_hours ?? 8),
    week_off_min_working_hours: Number(p.week_off_min_working_hours ?? 0),
    ot_pct_basic: Number(p.ot_pct_basic ?? 0),
    ot_pct_gross: Number(p.ot_pct_gross ?? 0),
    punch_approval_required: p.punch_approval_required ?? true,
  };
}

export default function AttendancePolicyScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const params = useLocalSearchParams<{ company_id?: string }>();
  const isSuper = user?.role === "super_admin" || user?.role === "sub_admin";
  // Iter 68 — Fall back to the global picker for super/sub admins when no
  // explicit ?company_id= is in the URL, so firm impersonation works here
  // too.  Company Admin uses their own firm implicitly.
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  const queryCompanyId = params.company_id || globalCid || undefined;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<{
    company_id: string;
    business_category: string | null;
    business_subcategory: string | null;
    weekday_labels: string[];
    is_default_preset: boolean;
  } | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetOpen, setPresetOpen] = useState(false);

  const canManage = user?.role === "company_admin" || user?.role === "super_admin";

  const qs = isSuper && queryCompanyId ? `?company_id=${queryCompanyId}` : "";

  const missingCompanyForSuper = isSuper && !queryCompanyId;

  const load = useCallback(async () => {
    if (missingCompanyForSuper) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const r = await api<PolicyResponse>(`/attendance/policy${qs}`);
      setMeta({
        company_id: r.company_id,
        business_category: r.business_category,
        business_subcategory: r.business_subcategory,
        weekday_labels: r.weekday_labels,
        is_default_preset: r.is_default_preset,
      });
      setPolicy(normalisePolicy(r.policy));
      // Presets are useful even for company_admin to preview / re-apply
      try {
        const pr = await api<{ presets: Preset[] }>("/attendance/policy/presets");
        setPresets(pr.presets || []);
      } catch {}
    } catch (e: any) {
      setError(e?.message || "Could not load policy");
    } finally {
      setLoading(false);
    }
  }, [qs, missingCompanyForSuper]);

  useEffect(() => {
    if (!canManage) return;
    load();
  }, [canManage, load]);
  // Iter 72 — Refresh on top-bar Refresh click.
  useOnRefresh(load);

  const validate = (p: Policy): string | null => {
    if (!p.shifts.length) return "Please add at least one shift";
    const names = new Set<string>();
    for (const s of p.shifts) {
      if (!s.name?.trim()) return "Every shift needs a name";
      const key = s.name.trim().toLowerCase();
      if (names.has(key)) return `Duplicate shift name: ${s.name}`;
      names.add(key);
      if (!HHMM_RE.test(s.start) || !HHMM_RE.test(s.end))
        return `Shift '${s.name}' — start/end must be HH:MM`;
    }
    if (p.half_day_hours >= p.full_day_hours)
      return "Full-day hours must be greater than half-day hours";
    if (p.overtime_threshold_hours < p.full_day_hours)
      return "Overtime threshold cannot be less than full-day hours";
    if (p.overtime_multiplier < 1 || p.overtime_multiplier > 4)
      return "Overtime multiplier must be between 1.0 and 4.0";
    if (!HHMM_RE.test(p.night_shift_start) || !HHMM_RE.test(p.night_shift_end))
      return "Night shift times must be in HH:MM";
    return null;
  };

  const save = async () => {
    if (!policy) return;
    const err = validate(policy);
    if (err) {
      setError(err);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api(`/attendance/policy${qs}`, {
        method: "PATCH",
        body: { policy: normalisePolicy(policy) },
      });
      showToast("Attendance policy saved");
      await load();
    } catch (e: any) {
      setError(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const resetToBusinessDefault = async () => {
    const confirmMsg =
      "Reset to the default policy for this business type? Your current customisations will be replaced.";
    const proceed = async () => {
      setSaving(true);
      setError(null);
      try {
        await api(`/attendance/policy/reset${qs}`, { method: "POST", body: {} });
        await load();
        showToast("Reset to business-type default");
      } catch (e: any) {
        setError(e?.message || "Reset failed");
      } finally {
        setSaving(false);
      }
    };
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && window.confirm(confirmMsg)) proceed();
    } else {
      Alert.alert("Reset attendance policy", confirmMsg, [
        { text: "Cancel", style: "cancel" },
        { text: "Reset", style: "destructive", onPress: proceed },
      ]);
    }
  };

  const applyPreset = (p: Preset) => {
    setPresetOpen(false);
    setPolicy(normalisePolicy(p.policy));
    showToast(`${p.label} preset loaded — remember to save`);
  };

  if (!canManage) {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
          <Header title="Attendance Policy" onBack={() => router.back()} />
        </SafeAreaView>
        <View style={styles.forbidden}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbTitle}>Company admin only</Text>
          <Text style={styles.forbBody}>
            Only the company admin (or super admin) can configure attendance rules.
          </Text>
        </View>
      </View>
    );
  }

  if (missingCompanyForSuper) {
    return (
      <View style={styles.root} testID="ap-pick-company">
        <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
          <Header title="Attendance Policy" onBack={() => router.back()} />
        </SafeAreaView>
        <View style={styles.forbidden}>
          <Ionicons name="business-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbTitle}>Pick a company to configure</Text>
          <Text style={styles.forbBody}>
            Attendance policy is per-company. Choose a firm below to load and
            edit its policy.
          </Text>
          <View style={{ marginTop: 16, width: 320, maxWidth: "100%" }}>
            <InlineCompanyPicker
              onPick={(cid) =>
                router.replace(`/attendance-policy?company_id=${encodeURIComponent(cid)}`)
              }
            />
          </View>
          <Pressable
            testID="ap-pick-company-back"
            onPress={() => router.back()}
            style={[styles.cta, { marginTop: 16 }]}
          >
            <Ionicons name="arrow-back" size={16} color={colors.onCta} />
            <Text style={styles.ctaTxt}>Go back</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root} testID="attendance-policy-screen">
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <Header
          title="Attendance Policy"
          onBack={() => router.back()}
          right={
            !loading && policy ? (
              <Pressable
                testID="ap-preset-btn"
                onPress={() => setPresetOpen(true)}
                style={styles.headBtn}
                hitSlop={6}
              >
                <Ionicons name="albums-outline" size={16} color={colors.brandPrimary} />
                <Text style={styles.headBtnTxt}>Presets</Text>
              </Pressable>
            ) : null
          }
        />
      </SafeAreaView>

      {loading || !policy ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
        </View>
      ) : (
        <KeyboardAwareScrollView bottomOffset={64} contentContainerStyle={styles.scroll}>
          <View style={styles.hero} testID="ap-hero">
            <View style={styles.heroIcon}>
              <Ionicons name="time-outline" size={22} color={colors.brandPrimary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.heroTitle}>
                {meta?.business_category
                  ? formatCategoryLabel(meta.business_category, meta.business_subcategory)
                  : "Custom policy"}
              </Text>
              <Text style={styles.heroSub}>
                {meta?.is_default_preset
                  ? "You are viewing the default preset for this business type. Save any change to make it your own."
                  : "Custom policy in effect for this company."}
              </Text>
            </View>
          </View>

          {/* Iter 86 — Standard Policy reference panel.
              Shows the firm-wide default rules that apply to every
              non-textile company. Textile firms keep their bespoke
              policy_variant math; for them the panel is still shown
              as a reference cross-check. */}
          <StandardPolicyPanel category={meta?.business_category || ""} />

          {/* Iter 76 — Shift Master (Global) card. Only super_admin can
              add/edit/delete. Shifts here are then assigned PER EMPLOYEE
              from the Employee Master screen — no firm-wide bundle. */}
          <ShiftMasterSection isSuper={isSuper} />

          {/* Iter 175 — Policy Master Sub Points (user catalogue). */}
          <SectionTitle
            title="Policy Master — Sub Points"
            hint="Core policy configuration — these settings are shown in Firm Master (linked to this Attendance Policy Master)."
          />
          <PolicyMasterSubPoints
            value={policy.policy_master || {}}
            onChange={(pm) => setPolicy({ ...policy, policy_master: pm })}
          />

          {/* Weekly off */}
          <SectionTitle title="Weekly off" hint="Days that don’t count as working days." />
          <View style={styles.chipsRow}>
            {(meta?.weekday_labels || ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]).map((lbl, idx) => {
              const on = policy.weekly_off_days.includes(idx);
              return (
                <Pressable
                  key={lbl}
                  testID={`ap-weekday-${idx}`}
                  style={[styles.chip, on && styles.chipOn]}
                  onPress={() => {
                    const set = new Set(policy.weekly_off_days);
                    if (on) set.delete(idx);
                    else set.add(idx);
                    setPolicy({ ...policy, weekly_off_days: Array.from(set).sort((a, b) => a - b) });
                  }}
                >
                  <Text style={[styles.chipTxt, on && styles.chipTxtOn]}>{lbl}</Text>
                </Pressable>
              );
            })}
          </View>
          {policy.weekly_off_days.length === 0 && (
            <Text style={styles.helper}>
              No fixed weekly off — appropriate for rotational rosters (hotels, hospitals, sites).
            </Text>
          )}

          {/* Hours */}
          <SectionTitle title="Hours & thresholds" hint="How worked hours map to attendance." />
          <NumRow
            label="Grace period for late-in (minutes)"
            value={policy.grace_minutes_late}
            onChange={(v) => setPolicy({ ...policy, grace_minutes_late: Math.max(0, Math.min(120, v)) })}
            step={5}
            testID="ap-grace"
          />
          <NumRow
            label="Half-day threshold (hours)"
            value={policy.half_day_hours}
            onChange={(v) => setPolicy({ ...policy, half_day_hours: v })}
            step={0.5}
            decimals={1}
            testID="ap-half"
          />
          <NumRow
            label="Full-day threshold (hours)"
            value={policy.full_day_hours}
            onChange={(v) => setPolicy({ ...policy, full_day_hours: v })}
            step={0.5}
            decimals={1}
            testID="ap-full"
          />
          <NumRow
            label="Break hours (unpaid)"
            value={policy.break_hours}
            onChange={(v) => setPolicy({ ...policy, break_hours: Math.max(0, Math.min(4, v)) })}
            step={0.25}
            decimals={2}
            testID="ap-break"
          />

          {/* Iter 76 — Round-hours preset available for ALL companies
              (previously only exposed on Textile). Applies to daily
              worked hours computed by _pair_punches on the backend. */}
          <View style={styles.roundRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.roundLabel}>Round HRS to nearest (minutes)</Text>
              <Text style={styles.roundHint}>
                Daily worked hours are rounded to this step. Off = no
                rounding. 15 min uses a special rule: 0-15 → :00,
                16-45 → :30, 46-59 → next hour.
              </Text>
            </View>
            <View style={styles.roundSegment}>
              {[0, 15, 30].map((v) => {
                const active = (policy.duty_hours_rounding_minutes ?? 0) === v;
                return (
                  <Pressable
                    key={v}
                    onPress={() => setPolicy({ ...policy, duty_hours_rounding_minutes: v })}
                    style={[styles.roundBtn, active && styles.roundBtnOn]}
                    testID={`ap-round-${v}`}
                  >
                    <Text style={[styles.roundBtnTxt, active && styles.roundBtnTxtOn]}>
                      {v === 0 ? "Off" : `${v} min`}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>

          {/* Overtime */}
          <SectionTitle
            title="Overtime"
            hint="OT is tracked for reports only — payroll continues on monthly salary."
          />
          <NumRow
            label="OT starts after (hours worked)"
            value={policy.overtime_threshold_hours}
            onChange={(v) => setPolicy({ ...policy, overtime_threshold_hours: v })}
            step={0.5}
            decimals={1}
            testID="ap-ot-threshold"
          />

          {/* Night shift — temporarily disabled (Iter 77c) per user request.
              To re-enable, restore the block below. */}
          {/*
          <SectionTitle title="Night-shift allowance" />
          <Pressable
            style={styles.toggleRow}
            testID="ap-night-toggle"
            onPress={() =>
              setPolicy({
                ...policy,
                night_shift_allowance_enabled: !policy.night_shift_allowance_enabled,
              })
            }
          >
            <View style={{ flex: 1 }}>
              <Text style={styles.toggleLabel}>Enable night-shift allowance</Text>
              <Text style={styles.toggleHint}>
                Applies to punches falling inside the night-shift window below.
              </Text>
            </View>
            <View
              style={[
                styles.toggle,
                policy.night_shift_allowance_enabled && styles.toggleOn,
              ]}
            >
              <View
                style={[
                  styles.toggleKnob,
                  policy.night_shift_allowance_enabled && styles.toggleKnobOn,
                ]}
              />
            </View>
          </Pressable>
          {policy.night_shift_allowance_enabled && (
            <View style={styles.rowSplit}>
              <View style={{ flex: 1 }}>
                <TimeInput
                  label="Night start"
                  value={policy.night_shift_start}
                  onChange={(v) => setPolicy({ ...policy, night_shift_start: v })}
                  testID="ap-night-start"
                />
              </View>
              <View style={{ width: 12 }} />
              <View style={{ flex: 1 }}>
                <TimeInput
                  label="Night end"
                  value={policy.night_shift_end}
                  onChange={(v) => setPolicy({ ...policy, night_shift_end: v })}
                  testID="ap-night-end"
                />
              </View>
            </View>
          )}
          */}

          <SectionTitle
            title="Auto-punch approvals"
            hint="When ON, every geofence auto-punch waits for admin approval before it counts. Manual punches are always accepted."
          />
          <Pressable
            style={styles.toggleRow}
            testID="ap-approval-toggle"
            onPress={() =>
              setPolicy({
                ...policy,
                punch_approval_required: !(policy.punch_approval_required ?? true),
              })
            }
          >
            <View style={{ flex: 1 }}>
              <Text style={styles.toggleLabel}>
                Require admin approval for auto punches
              </Text>
              <Text style={styles.toggleHint}>
                Recommended for firms that want to verify each auto punch-in / punch-out before it
                counts toward hours.
              </Text>
            </View>
            <View
              style={[
                styles.toggle,
                (policy.punch_approval_required ?? true) && styles.toggleOn,
              ]}
            >
              <View
                style={[
                  styles.toggleKnob,
                  (policy.punch_approval_required ?? true) && styles.toggleKnobOn,
                ]}
              />
            </View>
          </Pressable>

          {meta?.business_category === "textile" ? (
            <TextilePolicySection
              policy={policy}
              onChange={(patch) => setPolicy({ ...policy, ...patch })}
            />
          ) : null}

          <SectionTitle title="Notes" hint="Optional — surfaced on employee onboarding." />
          <TextInput
            testID="ap-notes"
            value={policy.notes || ""}
            onChangeText={(t) => setPolicy({ ...policy, notes: t })}
            multiline
            placeholder="E.g. Rotational off — one compensatory day per week."
            placeholderTextColor={colors.onSurfaceTertiary}
            style={[styles.input, { height: 84 }]}
          />

          {error && (
            <View style={styles.errBox}>
              <Ionicons name="alert-circle" size={16} color={colors.onError} />
              <Text style={styles.errTxt}>{error}</Text>
            </View>
          )}

          <View style={{ height: spacing.md }} />

          <Pressable
            testID="ap-save"
            style={[styles.cta, saving && { opacity: 0.7 }]}
            onPress={save}
            disabled={saving}
          >
            {saving ? (
              <ActivityIndicator color={colors.onCta} />
            ) : (
              <>
                <Ionicons name="checkmark-circle" size={18} color={colors.onCta} />
                <Text style={styles.ctaTxt}>Save policy</Text>
              </>
            )}
          </Pressable>

          <Pressable
            testID="ap-reset"
            style={styles.resetBtn}
            onPress={resetToBusinessDefault}
          >
            <Ionicons name="refresh" size={16} color={colors.brandPrimary} />
            <Text style={styles.resetTxt}>
              Reset to {meta?.business_category ? "business-type default" : "generic default"}
            </Text>
          </Pressable>

          <View style={{ height: 40 }} />
        </KeyboardAwareScrollView>
      )}

      {/* Preset picker */}
      <Modal transparent animationType="slide" visible={presetOpen} onRequestClose={() => setPresetOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setPresetOpen(false)} />
        <View style={styles.sheet}>
          <View style={styles.grip} />
          <View style={styles.sheetHead}>
            <Text style={styles.sheetTitle}>Apply preset</Text>
            <Pressable onPress={() => setPresetOpen(false)} hitSlop={10}>
              <Ionicons name="close" size={22} color={colors.onSurface} />
            </Pressable>
          </View>
          <Text style={styles.sheetSub}>
            Load the default rules for a business type. Values become editable — nothing is saved
            until you tap &quot;Save policy&quot;.
          </Text>
          <ScrollView contentContainerStyle={{ paddingBottom: spacing.xl }}>
            {presets.map((p) => (
              <Pressable
                key={p.business_category}
                testID={`ap-preset-${p.business_category}`}
                style={styles.presetRow}
                onPress={() => applyPreset(p)}
              >
                <View style={{ flex: 1 }}>
                  <Text style={styles.presetName}>{p.label}</Text>
                  <Text style={styles.presetHint}>
                    {p.policy.shifts.length} shift
                    {p.policy.shifts.length === 1 ? "" : "s"} · OT after {p.policy.overtime_threshold_hours} hrs @{" "}
                    {p.policy.overtime_multiplier}×
                    {p.policy.night_shift_allowance_enabled ? " · night allowance" : ""}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
              </Pressable>
            ))}
          </ScrollView>
        </View>
      </Modal>
    </View>
  );
}

// ---------- helpers ----------

function showToast(msg: string) {
  if (Platform.OS === "web") {
    console.log(msg);
    return;
  }
  Alert.alert("Saved", msg);
}

function formatCategoryLabel(cat: string, sub?: string | null): string {
  const nice = cat
    .split("_")
    .map((p) => (p.length ? p[0].toUpperCase() + p.slice(1) : p))
    .join(" ")
    .replace("It Company", "IT Company")
    .replace("Hotel Resort", "Hotel / Resort");
  return sub ? `${nice} — ${sub}` : nice;
}

function Header({
  title,
  onBack,
  right,
}: {
  title: string;
  onBack: () => void;
  right?: React.ReactNode;
}) {
  return (
    <View style={styles.header}>
      <Pressable onPress={onBack} hitSlop={8}>
        <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
      </Pressable>
      <Text style={styles.h1}>{title}</Text>
      <View style={{ minWidth: 26, alignItems: "flex-end" }}>{right || <View style={{ width: 26 }} />}</View>
    </View>
  );
}

// Iter 175 — Policy Master Sub Points editor (user-specified catalogue).
// Choice rows (single-select chips), multi-select punch types and Yes/No
// flags. Stored under attendance_policy.policy_master.
const PM_FLAGS: { key: string; label: string }[] = [
  { key: "contractor_assignment_required", label: "Contractor Assignment Required" },
  { key: "site_wise_attendance", label: "Site-wise Attendance" },
  { key: "client_wise_attendance", label: "Client-wise Attendance" },
  { key: "multiple_punch_allowed", label: "Multiple Punch Allowed" },
  { key: "auto_shift_detection", label: "Auto Shift Detection" },
  { key: "wfh_allowed", label: "WFH Allowed" },
  { key: "geofencing_required", label: "Geo-fencing Required" },
];

function PolicyMasterSubPoints({
  value,
  onChange,
}: {
  value: Record<string, any>;
  onChange: (v: Record<string, any>) => void;
}) {
  const set = (patch: Record<string, any>) => onChange({ ...value, ...patch });
  const punchTypes: string[] = Array.isArray(value.punch_types) ? value.punch_types : ["biometric", "mobile"];
  const togglePunch = (p: string) => {
    const next = punchTypes.includes(p) ? punchTypes.filter((x) => x !== p) : [...punchTypes, p];
    set({ punch_types: next.length ? next : [p] });
  };
  const Choice = ({ label, k, options, def }: { label: string; k: string; options: string[]; def: string }) => (
    <View style={pmStyles.row}>
      <Text style={pmStyles.lbl}>{label}</Text>
      <View style={pmStyles.chips}>
        {options.map((o) => {
          const on = (value[k] || def) === o;
          return (
            <Pressable key={o} onPress={() => set({ [k]: o })}
              style={[pmStyles.chip, on && pmStyles.chipOn]} testID={`pm-${k}-${o}`}>
              <Text style={[pmStyles.chipTxt, on && { color: "#fff" }]}>
                {o.charAt(0).toUpperCase() + o.slice(1)}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
  return (
    <View style={pmStyles.card} testID="policy-master-subpoints">
      <Choice label="Attendance Basis" k="attendance_basis" options={["monthly", "daily", "hourly"]} def="monthly" />
      <Choice label="Shift Type" k="shift_type" options={["fixed", "rotational", "open"]} def="fixed" />
      <View style={pmStyles.row}>
        <Text style={pmStyles.lbl}>Punch Type (multi-select)</Text>
        <View style={pmStyles.chips}>
          {["biometric", "mobile", "manual", "gps"].map((p) => {
            const on = punchTypes.includes(p);
            return (
              <Pressable key={p} onPress={() => togglePunch(p)}
                style={[pmStyles.chip, on && pmStyles.chipOn]} testID={`pm-punch-${p}`}>
                <Text style={[pmStyles.chipTxt, on && { color: "#fff" }]}>
                  {p === "gps" ? "GPS" : p.charAt(0).toUpperCase() + p.slice(1)}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>
      {PM_FLAGS.map((f) => {
        const dflt = f.key === "multiple_punch_allowed" || f.key === "geofencing_required";
        const on = value[f.key] === undefined ? dflt : !!value[f.key];
        return (
          <View key={f.key} style={pmStyles.row}>
            <Text style={pmStyles.lbl}>{f.label}</Text>
            <View style={pmStyles.chips}>
              {[true, false].map((b) => (
                <Pressable key={String(b)} onPress={() => set({ [f.key]: b })}
                  style={[pmStyles.chip, on === b && pmStyles.chipOn]}
                  testID={`pm-${f.key}-${b ? "yes" : "no"}`}>
                  <Text style={[pmStyles.chipTxt, on === b && { color: "#fff" }]}>{b ? "Yes" : "No"}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        );
      })}
      <Text style={pmStyles.note}>
        These sub-points are saved with the Attendance Policy and shown in the
        Firm Master (linked). Grace Time, Late Mark, Half-Day, OT, Weekly Off
        and Holiday rules are configured in the sections below.
      </Text>
    </View>
  );
}

const pmStyles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.divider,
    padding: 12,
    marginBottom: 14,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    flexWrap: "wrap",
    gap: 6,
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  lbl: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface, flexShrink: 1 },
  chips: { flexDirection: "row", gap: 6, flexWrap: "wrap" },
  chip: {
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 6,
  },
  chipOn: { backgroundColor: colors.brandPrimary },
  chipTxt: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },
  note: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 8, lineHeight: 15 },
});

function SectionTitle({ title, hint }: { title: string; hint?: string }) {
  return (
    <View style={{ marginTop: spacing.lg }}>
      <Text style={styles.section}>{title}</Text>
      {hint ? <Text style={styles.sectionHint}>{hint}</Text> : null}
    </View>
  );
}

/**
 * Iter 86 — Standard Policy reference panel.
 *
 * Renders the standard non-textile attendance rules (fetched from
 * `/api/attendance/standard-policy`) as a compact read-only table.
 * Purpose: give admins a quick cheat-sheet of the firm-wide defaults
 * so they know what applies when they haven't customised the policy
 * for a specific firm.  Textile firms see the panel too but with a
 * banner noting textile uses its own bespoke rules.
 */
function StandardPolicyPanel({ category }: { category: string }) {
  const [summary, setSummary] = useState<{
    title: string;
    applies_to: string;
    rules: { label: string; value: string }[];
    override: string;
  } | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    (async () => {
      try {
        const r = await api<{
          summary: {
            title: string;
            applies_to: string;
            rules: { label: string; value: string }[];
            override: string;
          };
        }>("/attendance/standard-policy");
        setSummary(r.summary);
      } catch (e: any) {
        setErr(e?.message || "Could not load standard policy");
      }
    })();
  }, []);
  const isTextile = category === "textile";
  return (
    <View style={sppStyles.card} testID="ap-standard-policy-panel">
      <Pressable
        style={sppStyles.header}
        onPress={() => setExpanded((v) => !v)}
        testID="ap-standard-policy-toggle"
      >
        <View style={sppStyles.headerLeft}>
          <View style={sppStyles.iconWrap}>
            <Ionicons name="shield-checkmark-outline" size={18} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={sppStyles.title}>Standard Policy (Non-Textile Firms)</Text>
            <Text style={sppStyles.sub}>
              {isTextile
                ? "Textile firms follow their own 12-hour rotational policy variant. This card is shown for reference."
                : "Firm-wide defaults applied when no custom policy is set."}
            </Text>
          </View>
        </View>
        <Ionicons
          name={expanded ? "chevron-up" : "chevron-down"}
          size={18}
          color={colors.onSurfaceSecondary}
        />
      </Pressable>
      {expanded ? (
        <View style={sppStyles.body}>
          {err ? (
            <Text style={sppStyles.err}>{err}</Text>
          ) : !summary ? (
            <ActivityIndicator color={colors.brandPrimary} />
          ) : (
            <>
              <Text style={sppStyles.appliesTo}>{summary.applies_to}</Text>
              {summary.rules.map((r) => (
                <View key={r.label} style={sppStyles.row}>
                  <Text style={sppStyles.rowLabel}>{r.label}</Text>
                  <Text style={sppStyles.rowValue}>{r.value}</Text>
                </View>
              ))}
              <View style={sppStyles.footer}>
                <Ionicons name="information-circle-outline" size={14} color={colors.onSurfaceSecondary} />
                <Text style={sppStyles.footerTxt}>{summary.override}</Text>
              </View>
            </>
          )}
        </View>
      ) : null}
    </View>
  );
}

const sppStyles = StyleSheet.create({
  card: {
    marginTop: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.divider,
    overflow: "hidden",
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 14,
    paddingVertical: 12,
    gap: 10,
  },
  headerLeft: { flexDirection: "row", alignItems: "center", gap: 10, flex: 1 },
  iconWrap: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  title: { color: colors.onSurface, fontSize: 14, fontWeight: "800" },
  sub: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 2 },
  body: {
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.divider,
    backgroundColor: colors.background,
  },
  appliesTo: {
    color: colors.onSurfaceSecondary,
    fontSize: 12,
    marginBottom: 10,
    fontStyle: "italic",
  },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
    gap: 8,
  },
  rowLabel: { color: colors.onSurface, fontSize: 12, fontWeight: "700", flexShrink: 0, minWidth: 120 },
  rowValue: { color: colors.onSurfaceSecondary, fontSize: 12, flex: 1, textAlign: "right" },
  footer: { flexDirection: "row", alignItems: "flex-start", gap: 6, marginTop: 10 },
  footerTxt: { color: colors.onSurfaceSecondary, fontSize: 11, flex: 1, lineHeight: 15 },
  err: { color: "#dc2626", fontSize: 12 },
});

/** Textile industry policy configuration. Only rendered when the company's
 * business category is "textile". Two mutually-exclusive variants:
 *
 * • **Policy 1** – Hourly + Daily calc; OT-enabled employees may work a
 *   24-hr duty when starting evening; week-off day work → Full Day
 *   Payment (per-employee flag).
 * • **Policy 2** – 8-hr day = 1 Present Day. Extras → OT. Week-off /
 *   govt-holiday worked → NO present day (all hours = OT).
 */
function TextilePolicySection({
  policy,
  onChange,
}: {
  policy: Policy;
  onChange: (patch: Partial<Policy>) => void;
}) {
  const variant = (policy.policy_variant || null) as "policy_1" | "policy_2" | null;
  const rounding = policy.duty_hours_rounding_minutes ?? 0;
  const standardHrs = policy.standard_working_hours ?? policy.full_day_hours ?? 8;
  const weekOffFullDefault = !!policy.week_off_full_day_payment_default;

  return (
    <>
      <SectionTitle
        title="Textile industry"
        hint="Choose the calculation model for this firm. Employee-level toggles (OT applicable, Week-off Full Day, Week-off / govt holiday) are set on each Employee Master."
      />

      {/* Variant radio */}
      <View style={styles.textileVariantRow}>
        {[
          { key: "policy_1", label: "Policy 1", sub: "Hourly + Daily · 24-hr OT allowed" },
          { key: "policy_2", label: "Policy 2", sub: "8 hrs = 1 Present Day · extras → OT" },
        ].map((opt) => {
          const active = variant === opt.key;
          return (
            <Pressable
              key={opt.key}
              testID={`textile-variant-${opt.key}`}
              onPress={() =>
                onChange({ policy_variant: opt.key as "policy_1" | "policy_2" })
              }
              style={[styles.variantCard, active && styles.variantCardActive]}
            >
              <View style={styles.variantRadio}>
                <View
                  style={[
                    styles.variantRadioOuter,
                    active && styles.variantRadioOuterActive,
                  ]}
                >
                  {active ? <View style={styles.variantRadioDot} /> : null}
                </View>
                <Text style={[styles.variantLabel, active && styles.variantLabelActive]}>
                  {opt.label}
                </Text>
              </View>
              <Text
                style={[
                  styles.variantSub,
                  active && { color: colors.brandPrimary },
                ]}
              >
                {opt.sub}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* Iter 98 — plain-language rules explainer for the selected variant */}
      {variant === "policy_2" ? (
        <View style={styles.variantRules} testID="textile-policy2-rules">
          <Text style={styles.variantRulesTitle}>📋 Policy 2 — how it works</Text>
          <Text style={styles.variantRulesLine}>• {standardHrs} duty hours = 1 Present Day.</Text>
          <Text style={styles.variantRulesLine}>• Hours beyond {standardHrs} hrs → counted as OT (only if the employee&apos;s &quot;OT applicable&quot; flag is ON in Employee Master; otherwise extra hours are ignored).</Text>
          <Text style={styles.variantRulesLine}>• Less than {standardHrs} hrs worked → NO Half Day / Absent — ALL worked hours are counted as OT hours instead.</Text>
          <Text style={styles.variantRulesLine}>• Week-off / Govt Holiday: if the employee&apos;s &quot;Week-off / Govt-Holiday enabled&quot; flag is ON and they work on their off day → NO present day is given; ALL worked hours become OT.</Text>
          <Text style={styles.variantRulesLine}>• Duty hours are rounded per the rounding rule below ({rounding === 0 ? "no rounding" : `${rounding} min`}).</Text>
        </View>
      ) : variant === "policy_1" ? (
        <View style={styles.variantRules} testID="textile-policy1-rules">
          <Text style={styles.variantRulesTitle}>📋 Policy 1 — how it works</Text>
          <Text style={styles.variantRulesLine}>• Hourly + Daily basis calculation — OT is folded into Total Duty Hours (paid per-hour, no separate OT column).</Text>
          <Text style={styles.variantRulesLine}>• OT-allowed employees can work up to a 24-hr duty (Day + Night combo). OT-not-allowed employees are capped at standard shift hours.</Text>
          <Text style={styles.variantRulesLine}>• Week-off day work → Full Day Payment if the employee&apos;s &quot;Week-off Full Day&quot; flag is ON.</Text>
          <Text style={styles.variantRulesLine}>• Week-off days are free from the standard-hours cap (min hours rule below applies).</Text>
        </View>
      ) : null}

      {/* Duty hours rounding dropdown */}
      <SectionTitle
        title="Duty hours rounding"
        hint="Round the total on-duty minutes. 15 min uses the special rule: 0-15 → :00, 16-45 → :30, 46-59 → next hour."
      />
      <View style={styles.chipsRow}>
        {[0, 15, 30].map((step) => {
          const active = rounding === step;
          return (
            <Pressable
              key={step}
              testID={`rounding-${step}`}
              onPress={() => onChange({ duty_hours_rounding_minutes: step })}
              style={[styles.roundChip, active && styles.roundChipActive]}
            >
              <Text
                style={[styles.roundChipTxt, active && styles.roundChipTxtActive]}
              >
                {step === 0 ? "No round" : `${step} min`}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* Standard working hours (used by Policy 2 as the present-day threshold) */}
      <SectionTitle
        title="Standard working hours"
        hint="Duty hours that make up 1 Present Day (Policy 2). Extras beyond this → OT."
      />
      <TextInput
        testID="textile-standard-hrs"
        value={String(standardHrs)}
        onChangeText={(t) => {
          const n = Number(t);
          if (!Number.isNaN(n) && n > 0 && n <= 16) {
            onChange({ standard_working_hours: n });
          } else if (t === "") {
            // Iter 76 — leaving the field blank falls back to full_day
            // hours instead of writing 0 (the backend rejects 0 as
            // outside the 1..16 range).
            onChange({ standard_working_hours: undefined });
          }
        }}
        keyboardType="decimal-pad"
        placeholder="8"
        placeholderTextColor={colors.onSurfaceTertiary}
        style={styles.input}
      />

      {/* Week-off Full Day Payment — company default */}
      <Pressable
        testID="textile-weekoff-fdp-toggle"
        onPress={() =>
          onChange({ week_off_full_day_payment_default: !weekOffFullDefault })
        }
        style={styles.toggleRow}
      >
        <View style={{ flex: 1 }}>
          <Text style={styles.toggleLabel}>
            Week-off Full-Day Payment (default)
          </Text>
          <Text style={styles.toggleHint}>
            Company-wide default for the per-employee &quot;Week-off Full
            Day&quot; flag. Employees flagged True get full-day pay when
            they work on a weekly-off day. Individual employees can still
            override this from Employee Master.
          </Text>
        </View>
        <View style={[styles.toggle, weekOffFullDefault && styles.toggleOn]}>
          <View
            style={[
              styles.toggleKnob,
              weekOffFullDefault && styles.toggleKnobOn,
            ]}
          />
        </View>
      </Pressable>

      {/* Iter 77d — Week-off minimum working hours */}
      <Text style={[styles.label, { marginTop: 12 }]}>
        Min working hours on week-off for full-day credit
      </Text>
      <Text style={styles.smallHint}>
        When an employee works on their weekly-off day and their duty
        hours are &ge; this value, they earn a FULL DAY attendance. Set
        0 to disable (any positive work is treated as full-day for
        legacy setups).
      </Text>
      <TextInput
        testID="textile-weekoff-min-hours"
        value={
          policy.week_off_min_working_hours !== undefined &&
          policy.week_off_min_working_hours !== null
            ? String(policy.week_off_min_working_hours)
            : ""
        }
        onChangeText={(t) => {
          if (t === "") {
            onChange({ week_off_min_working_hours: 0 });
            return;
          }
          const n = Number(t);
          if (!Number.isNaN(n) && n >= 0 && n <= 16) {
            onChange({ week_off_min_working_hours: n });
          }
        }}
        keyboardType="decimal-pad"
        placeholder="0 (disabled)"
        placeholderTextColor={colors.onSurfaceTertiary}
        style={styles.input}
      />

      {/* Iter 131 (user directive) — OT Calculation config, Policy 2 only.
          Iter 131b — EITHER Basic OR Gross: filling one disables the other. */}
      {variant === "policy_2" ? (
        <>
          <SectionTitle
            title="OT Calculation"
            hint="Choose ONE base — enter the % in either Basic or Gross. The other option is disabled automatically. OT hourly rate = per-day base × % ÷ full-day hours. Used by Salary Process (OT)."
          />
          <View style={{ flexDirection: "row", gap: 12 }}>
            <View style={{ flex: 1, opacity: (policy.ot_pct_gross || 0) > 0 ? 0.4 : 1 }}>
              <Text style={styles.label}>
                % of Basic{(policy.ot_pct_gross || 0) > 0 ? "  (disabled — Gross selected)" : ""}
              </Text>
              <TextInput
                testID="ot-pct-basic"
                editable={!((policy.ot_pct_gross || 0) > 0)}
                value={policy.ot_pct_basic ? String(policy.ot_pct_basic) : ""}
                onChangeText={(t) => {
                  if (t === "") { onChange({ ot_pct_basic: 0 }); return; }
                  const n = Number(t);
                  if (!Number.isNaN(n) && n >= 0 && n <= 500) {
                    onChange({ ot_pct_basic: n, ot_pct_gross: 0 });
                  }
                }}
                keyboardType="decimal-pad"
                placeholder="e.g. 100"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.input}
              />
            </View>
            <View style={{ flex: 1, opacity: (policy.ot_pct_basic || 0) > 0 ? 0.4 : 1 }}>
              <Text style={styles.label}>
                % of Gross{(policy.ot_pct_basic || 0) > 0 ? "  (disabled — Basic selected)" : ""}
              </Text>
              <TextInput
                testID="ot-pct-gross"
                editable={!((policy.ot_pct_basic || 0) > 0)}
                value={policy.ot_pct_gross ? String(policy.ot_pct_gross) : ""}
                onChangeText={(t) => {
                  if (t === "") { onChange({ ot_pct_gross: 0 }); return; }
                  const n = Number(t);
                  if (!Number.isNaN(n) && n >= 0 && n <= 500) {
                    onChange({ ot_pct_gross: n, ot_pct_basic: 0 });
                  }
                }}
                keyboardType="decimal-pad"
                placeholder="e.g. 50"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.input}
              />
            </View>
          </View>
          <Text style={styles.smallHint}>
            Only ONE can be active. To switch, clear the filled field first (set
            it to 0 / empty) — the other unlocks instantly.
          </Text>
        </>
      ) : null}
    </>
  );
}

function ShiftRow({
  value,
  onChange,
  onRemove,
  testID,
}: {
  value: Shift;
  onChange: (v: Shift) => void;
  onRemove?: () => void;
  testID?: string;
}) {
  const duration = useMemo(() => {
    try {
      const [sh, sm] = value.start.split(":").map(Number);
      const [eh, em] = value.end.split(":").map(Number);
      if ([sh, sm, eh, em].some((n) => Number.isNaN(n))) return "";
      let mins = eh * 60 + em - (sh * 60 + sm);
      if (mins <= 0) mins += 24 * 60; // overnight shifts
      const h = Math.floor(mins / 60);
      const m = mins % 60;
      return `${h}h${m ? ` ${m}m` : ""}`;
    } catch {
      return "";
    }
  }, [value.start, value.end]);

  return (
    <View style={styles.shiftCard} testID={testID}>
      <View style={styles.shiftHead}>
        <TextInput
          testID={`${testID}-name`}
          value={value.name}
          onChangeText={(t) => onChange({ ...value, name: t })}
          placeholder="Shift name"
          placeholderTextColor={colors.onSurfaceTertiary}
          style={[styles.input, styles.shiftName]}
        />
        {onRemove ? (
          <Pressable onPress={onRemove} hitSlop={6} testID={`${testID}-remove`}>
            <Ionicons name="trash-outline" size={18} color={colors.error} />
          </Pressable>
        ) : null}
      </View>
      <View style={styles.rowSplit}>
        <View style={{ flex: 1 }}>
          <TimeInput
            label="Start"
            value={value.start}
            onChange={(v) => onChange({ ...value, start: v })}
            testID={`${testID}-start`}
          />
        </View>
        <View style={{ width: 12 }} />
        <View style={{ flex: 1 }}>
          <TimeInput
            label="End"
            value={value.end}
            onChange={(v) => onChange({ ...value, end: v })}
            testID={`${testID}-end`}
          />
        </View>
      </View>
      {duration ? <Text style={styles.shiftDur}>Duration: {duration}</Text> : null}
    </View>
  );
}


// ---------------------------------------------------------------------------
// Iter 76 — Shift Master (Global catalogue)
// ---------------------------------------------------------------------------
type ShiftMaster = {
  shift_id: string;
  name: string;
  start: string;
  end: string;
  duty_hours?: number;
  description?: string | null;
};

/** Iter 139 — decimal Duty HRS from In/Out time; overnight wraps. */
function dutyHoursOf(start: string, end: string): number | null {
  const [sh, sm] = (start || "").split(":").map(Number);
  const [eh, em] = (end || "").split(":").map(Number);
  if ([sh, sm, eh, em].some((n) => Number.isNaN(n))) return null;
  let mins = eh * 60 + em - (sh * 60 + sm);
  if (mins <= 0) mins += 24 * 60;
  return Math.round((mins / 60) * 100) / 100;
}

function ShiftMasterSection({ isSuper }: { isSuper: boolean }) {
  const [shifts, setShifts] = useState<ShiftMaster[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<ShiftMaster | null>(null);
  const [creating, setCreating] = useState(false);
  const [expanded, setExpanded] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api<{ shifts: ShiftMaster[] }>("/shift-masters");
      setShifts(res.shifts || []);
    } catch {
      /* silent — page will still work with 0 masters */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const remove = async (id: string) => {
    if (Platform.OS === "web" && !window.confirm("Delete this shift from the master catalogue?")) return;
    try {
      await api(`/shift-masters/${id}`, { method: "DELETE" });
      await load();
    } catch (e: any) {
      showToast(e?.message || "Delete failed");
    }
  };

  return (
    <View style={styles.masterCard}>
      <Pressable
        style={styles.masterHead}
        onPress={() => setExpanded((x) => !x)}
      >
        <View style={{ flex: 1 }}>
          <Text style={styles.masterTitle}>Shift Master (Global)</Text>
          <Text style={styles.masterHint}>
            Central catalogue of shifts shared across every firm.
            {isSuper ? " Only Super Admin can edit." : " Only Super Admin can add or edit."}
          </Text>
        </View>
        <Ionicons
          name={expanded ? "chevron-up" : "chevron-down"}
          size={20}
          color={colors.onSurfaceSecondary}
        />
      </Pressable>

      {expanded && (
        <>
          {loading ? (
            <ActivityIndicator color={colors.brand} style={{ margin: 12 }} />
          ) : shifts.length === 0 ? (
            <Text style={styles.masterEmpty}>
              No global shifts defined yet.{isSuper ? " Add one below." : ""}
            </Text>
          ) : (
            <View style={{ gap: 8 }}>
              {shifts.map((s) => (
                <View key={s.shift_id} style={styles.masterRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.masterRowName}>{s.name}</Text>
                    <Text style={styles.masterRowSub}>
                      {s.start} – {s.end} · Duty HRS{" "}
                      {s.duty_hours ?? dutyHoursOf(s.start, s.end) ?? "—"}
                      {s.description ? ` · ${s.description}` : ""}
                    </Text>
                  </View>
                  {isSuper && (
                    <>
                      <Pressable
                        onPress={() => setEditing(s)}
                        hitSlop={6}
                        style={styles.masterIconBtn}
                      >
                        <Ionicons name="create-outline" size={16} color={colors.brandPrimary} />
                      </Pressable>
                      <Pressable
                        onPress={() => remove(s.shift_id)}
                        hitSlop={6}
                        style={styles.masterIconBtn}
                      >
                        <Ionicons name="trash-outline" size={16} color={colors.error} />
                      </Pressable>
                    </>
                  )}
                </View>
              ))}
            </View>
          )}

          {isSuper && (
            <Pressable
              style={styles.masterAddBtn}
              onPress={() => setCreating(true)}
              testID="ap-add-shift-master"
            >
              <Ionicons name="add-circle-outline" size={18} color={colors.brandPrimary} />
              <Text style={styles.addTxt}>Add shift to master</Text>
            </Pressable>
          )}
        </>
      )}

      <ShiftMasterEditor
        visible={creating || !!editing}
        initial={editing}
        onClose={() => { setCreating(false); setEditing(null); }}
        onSaved={async () => { setCreating(false); setEditing(null); await load(); }}
      />
    </View>
  );
}

function ShiftMasterEditor({
  visible,
  initial,
  onClose,
  onSaved,
}: {
  visible: boolean;
  initial: ShiftMaster | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("18:00");
  const [desc, setDesc] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (visible) {
      setName(initial?.name || "");
      setStart(initial?.start || "09:00");
      setEnd(initial?.end || "18:00");
      setDesc(initial?.description || "");
    }
  }, [visible, initial]);

  const save = async () => {
    if (!name.trim()) { showToast("Shift name is required"); return; }
    setSaving(true);
    try {
      const body = { name: name.trim(), start, end, description: desc.trim() || null };
      if (initial) {
        await api(`/shift-masters/${initial.shift_id}`, { method: "PATCH", body });
      } else {
        await api("/shift-masters", { method: "POST", body });
      }
      onSaved();
    } catch (e: any) {
      showToast(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.modalRoot}>
        <Pressable style={styles.modalBackdrop} onPress={onClose} />
        <View style={styles.modalSheet}>
          <View style={styles.modalHead}>
            <Text style={styles.modalTitle}>
              {initial ? `Edit ${initial.name}` : "New shift"}
            </Text>
            <Pressable onPress={onClose} hitSlop={8}>
              <Ionicons name="close" size={22} color={colors.onSurfaceSecondary} />
            </Pressable>
          </View>
          <Text style={styles.fieldLabel}>Name</Text>
          <TextInput
            value={name}
            onChangeText={setName}
            placeholder="e.g. Day Shift"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={styles.input}
          />
          <View style={styles.rowSplit}>
            <View style={{ flex: 1 }}>
              <TimeInput label="In Time" value={start} onChange={setStart} />
            </View>
            <View style={{ width: 12 }} />
            <View style={{ flex: 1 }}>
              <TimeInput label="Out Time" value={end} onChange={setEnd} />
            </View>
          </View>
          {/* Iter 139 — Duty HRS auto-calculated live from In/Out time. */}
          <Text style={styles.shiftDur}>
            Duty HRS: {dutyHoursOf(start, end) ?? "—"}
          </Text>
          <Text style={styles.fieldLabel}>Description (optional)</Text>
          <TextInput
            value={desc}
            onChangeText={setDesc}
            placeholder="Short note"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={styles.input}
          />
          <Pressable
            onPress={save}
            disabled={saving}
            style={[styles.saveModalBtn, saving && { opacity: 0.6 }]}
          >
            {saving ? (
              <ActivityIndicator color={colors.onCta} size="small" />
            ) : (
              <Text style={styles.saveModalBtnTxt}>{initial ? "Save changes" : "Add shift"}</Text>
            )}
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

// Picker used by the Attendance Policy — the operator now picks WHICH
// of the global shifts apply to this firm rather than defining them
// inline. The tick list writes into `policy.shifts` as `{name,start,end}`
// dicts so downstream payroll code is unchanged.
function ShiftPicker({
  selectedNames,
  onChange,
}: {
  selectedNames: string[];
  onChange: (shifts: Shift[]) => void;
}) {
  const [masters, setMasters] = useState<ShiftMaster[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const res = await api<{ shifts: ShiftMaster[] }>("/shift-masters");
        if (alive) setMasters(res.shifts || []);
      } catch {
        /* silent */
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  const toggle = (m: ShiftMaster) => {
    const isOn = selectedNames.includes(m.name);
    if (isOn) {
      onChange(
        selectedNames
          .filter((n) => n !== m.name)
          .map((n) => {
            const src = masters.find((x) => x.name === n);
            return src
              ? { name: src.name, start: src.start, end: src.end }
              : { name: n, start: "09:00", end: "18:00" };
          }),
      );
    } else {
      const next = [
        ...selectedNames.map((n) => {
          const src = masters.find((x) => x.name === n);
          return src
            ? { name: src.name, start: src.start, end: src.end }
            : { name: n, start: "09:00", end: "18:00" };
        }),
        { name: m.name, start: m.start, end: m.end },
      ];
      onChange(next);
    }
  };

  if (loading) return <ActivityIndicator color={colors.brand} style={{ margin: 12 }} />;
  if (masters.length === 0) {
    return (
      <Text style={styles.masterEmpty}>
        No shifts in the master catalogue yet — Super Admin must add at
        least one shift above before employees can be assigned.
      </Text>
    );
  }
  return (
    <View style={styles.pickerWrap}>
      {masters.map((m) => {
        const on = selectedNames.includes(m.name);
        return (
          <Pressable
            key={m.shift_id}
            onPress={() => toggle(m)}
            style={[styles.pickerChip, on && styles.pickerChipOn]}
            testID={`ap-shift-pick-${m.name}`}
          >
            <Ionicons
              name={on ? "checkmark-circle" : "ellipse-outline"}
              size={16}
              color={on ? colors.onBrandPrimary : colors.brand}
            />
            <View style={{ flex: 1 }}>
              <Text style={[styles.pickerChipName, on && styles.pickerChipNameOn]}>
                {m.name}
              </Text>
              <Text style={[styles.pickerChipSub, on && styles.pickerChipSubOn]}>
                {m.start} – {m.end}
              </Text>
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

function TimeInput({
  label,
  value,
  onChange,
  testID,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  testID?: string;
}) {
  return (
    <View>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        testID={testID}
        value={value}
        onChangeText={(t) => {
          // Auto-insert colon and clamp to HH:MM
          const digits = t.replace(/[^0-9]/g, "").slice(0, 4);
          if (digits.length <= 2) onChange(digits);
          else onChange(`${digits.slice(0, 2)}:${digits.slice(2)}`);
        }}
        placeholder="HH:MM"
        placeholderTextColor={colors.onSurfaceTertiary}
        keyboardType="number-pad"
        maxLength={5}
        style={styles.input}
      />
    </View>
  );
}

function NumRow({
  label,
  value,
  onChange,
  step = 1,
  decimals = 0,
  testID,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  decimals?: number;
  testID?: string;
}) {
  const fmt = (n: number) => (decimals ? n.toFixed(decimals) : String(Math.round(n)));
  return (
    <View style={styles.numRow} testID={testID}>
      <Text style={styles.numLabel}>{label}</Text>
      <View style={styles.numControls}>
        <Pressable
          testID={`${testID}-dec`}
          onPress={() => onChange(Math.max(0, Math.round((value - step) * 100) / 100))}
          style={styles.stepBtn}
          hitSlop={6}
        >
          <Ionicons name="remove" size={16} color={colors.onSurface} />
        </Pressable>
        <TextInput
          testID={`${testID}-input`}
          value={fmt(value)}
          onChangeText={(t) => {
            const n = parseFloat(t.replace(/[^0-9.]/g, ""));
            if (!Number.isNaN(n)) onChange(n);
          }}
          style={styles.numInput}
          keyboardType="decimal-pad"
        />
        <Pressable
          testID={`${testID}-inc`}
          onPress={() => onChange(Math.round((value + step) * 100) / 100)}
          style={styles.stepBtn}
          hitSlop={6}
        >
          <Ionicons name="add" size={16} color={colors.onSurface} />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  h1: { fontSize: type.lg, color: colors.onSurface, fontWeight: "700" },
  headBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
  },
  headBtnTxt: { color: colors.brandPrimary, fontSize: 12, fontWeight: "700" },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xl },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },

  hero: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  heroIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  heroTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  heroSub: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 2, lineHeight: 16 },

  section: {
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "700",
    letterSpacing: 0.3,
    textTransform: "uppercase",
  },
  sectionHint: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 4, lineHeight: 16 },

  label: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "600",
    marginTop: spacing.md,
    marginBottom: 6,
  },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.onSurface,
    fontSize: type.base,
  },
  helper: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 4 },

  shiftCard: {
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    marginTop: spacing.sm,
  },
  shiftHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  shiftName: { flex: 1 },
  shiftDur: {
    color: colors.brandPrimary,
    fontSize: 12,
    marginTop: 6,
    fontWeight: "600",
  },

  addRow: {
    marginTop: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: radius.md,
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: colors.brandPrimary,
    alignSelf: "flex-start",
  },
  addTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: type.sm },

  chipsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: spacing.sm,
  },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
    minWidth: 46,
    alignItems: "center",
  },
  chipOn: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandPrimary,
  },
  chipTxt: { color: colors.onSurface, fontSize: type.sm, fontWeight: "600" },
  chipTxtOn: { color: colors.onCta },

  rowSplit: { flexDirection: "row", marginTop: spacing.sm },

  numRow: {
    marginTop: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  numLabel: { color: colors.onSurface, fontSize: type.sm, flex: 1 },
  numControls: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
    paddingHorizontal: 4,
  },
  stepBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
  },
  numInput: {
    minWidth: 46,
    textAlign: "center",
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "700",
    paddingVertical: 4,
  },

  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginTop: spacing.md,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  toggleLabel: { color: colors.onSurface, fontSize: type.base, fontWeight: "600" },
  toggleHint: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 2 },
  toggle: {
    width: 44,
    height: 26,
    borderRadius: 13,
    backgroundColor: colors.border,
    padding: 2,
    justifyContent: "center",
  },
  toggleOn: { backgroundColor: colors.brandPrimary },
  toggleKnob: {
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: "#fff",
  },
  toggleKnobOn: { alignSelf: "flex-end" },

  // Textile industry section
  textileVariantRow: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  variantRules: {
    marginTop: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
    padding: spacing.md,
    gap: 6,
  },
  variantRulesTitle: {
    color: colors.brandPrimary,
    fontSize: 13,
    fontWeight: "800",
    marginBottom: 2,
  },
  variantRulesLine: {
    color: colors.onSurface,
    fontSize: 12,
    lineHeight: 18,
  },
  variantCard: {
    flex: 1,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
    padding: spacing.sm,
  },
  variantCardActive: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  variantRadio: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  variantRadioOuter: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 2,
    borderColor: colors.borderStrong,
    alignItems: "center",
    justifyContent: "center",
  },
  variantRadioOuterActive: { borderColor: colors.brandPrimary },
  variantRadioDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.brandPrimary,
  },
  variantLabel: {
    color: colors.onSurface,
    fontWeight: "700",
    fontSize: type.base,
  },
  variantLabelActive: { color: colors.brandPrimary },
  variantSub: {
    color: colors.onSurfaceSecondary,
    fontSize: 12,
    marginTop: 4,
  },
  roundChip: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surfaceSecondary,
  },
  roundChipActive: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  roundChipTxt: {
    color: colors.onSurfaceSecondary,
    fontWeight: "600",
    fontSize: 13,
  },
  roundChipTxtActive: { color: colors.onBrandPrimary },

  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.error,
    padding: spacing.sm,
    borderRadius: radius.md,
    marginTop: spacing.md,
  },
  errTxt: { color: colors.onError, fontSize: type.sm, flex: 1 },

  cta: {
    marginTop: spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.cta,
    paddingVertical: 14,
    borderRadius: radius.pill,
    ...shadow.cta,
  },
  ctaTxt: { color: colors.onCta, fontSize: type.lg, fontWeight: "700" },

  resetBtn: {
    marginTop: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
  },
  resetTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: type.sm },

  forbidden: { alignItems: "center", padding: spacing.xl, gap: 8, marginTop: 40 },
  forbTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  forbBody: { color: colors.onSurfaceSecondary, textAlign: "center" },

  backdrop: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0,0,0,0.4)",
  },
  sheet: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    padding: spacing.md,
    maxHeight: "80%",
  },
  grip: {
    alignSelf: "center",
    width: 44,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    marginBottom: 4,
  },
  sheetHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 8,
  },
  sheetTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  sheetSub: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginBottom: spacing.sm,
  },
  presetRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  presetName: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  presetHint: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 2 },

  // Iter 76 — Shift Master + Picker styles
  masterCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
    gap: 8,
  },
  masterHead: { flexDirection: "row", alignItems: "center" },
  masterTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800" },
  masterHint: { color: colors.onSurfaceSecondary, marginTop: 2, fontSize: type.sm },
  masterEmpty: { color: colors.onSurfaceTertiary, fontStyle: "italic", padding: 8 },
  masterRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    padding: 10,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  masterRowName: { color: colors.onSurface, fontWeight: "700" },
  masterRowSub: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },
  masterIconBtn: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  masterAddBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    padding: 10,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderStyle: "dashed" as any,
    marginTop: 4,
  },
  modalRoot: { flex: 1, justifyContent: "center", padding: spacing.lg },
  modalBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.4)" },
  modalSheet: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    maxWidth: 460,
    width: "100%",
    alignSelf: "center",
    gap: 10,
  },
  modalHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  modalTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800" },
  fieldLabel: { color: colors.onSurfaceTertiary, fontWeight: "600", fontSize: type.sm, marginTop: 4 },
  saveModalBtn: {
    marginTop: spacing.md,
    backgroundColor: colors.cta,
    paddingVertical: 12,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  saveModalBtnTxt: { color: colors.onCta, fontWeight: "800" },

  pickerWrap: { gap: 6 },
  pickerChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: 10,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  pickerChipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  pickerChipName: { color: colors.onSurface, fontWeight: "700" },
  pickerChipNameOn: { color: colors.onBrandPrimary },
  pickerChipSub: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },
  pickerChipSubOn: { color: "rgba(255,255,255,0.85)" },

  // Iter 76 — "Round HRS to nearest" row
  roundRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    flexWrap: "wrap",
  },
  roundLabel: {
    color: colors.onSurface,
    fontWeight: "600",
    fontSize: type.base,
  },
  roundHint: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    marginTop: 2,
  },
  roundSegment: {
    flexDirection: "row",
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
    backgroundColor: colors.surfaceSecondary,
  },
  roundBtn: {
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  roundBtnOn: { backgroundColor: colors.brand },
  roundBtnTxt: { color: colors.onSurface, fontWeight: "600", fontSize: type.sm },
  roundBtnTxtOn: { color: colors.onBrandPrimary },
});
