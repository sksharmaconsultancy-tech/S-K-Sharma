import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  TextInput,
  Switch,
  Platform,
  Alert,
  KeyboardAvoidingView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

type Policy = {
  salary: number;
  // Payment cadence: monthly (default), daily, or hourly. Payroll uses
  // this to interpret the `salary` field on the pay-run.
  salary_mode?: "monthly" | "daily" | "hourly" | null;
  salary_1: number; day_1: number;
  salary_2: number; day_2: number;
  salary_3: number; day_3: number;
  shift_name: string | null;
  shift_dummy: string | null;
  dummy_weekly_off: number | null;
  working_hours: number;
  full_day_salary: boolean;
  ot_allow: boolean;
  fullday_hours: number;
  halfday_hours: number;
  cl_days: number;
  pl_days: number;
  weekly_off: number;
  week_off_min_hours: number;
  bio_code: string | null;
  weekly_off_attendance: boolean;
  policy_confirmed: boolean;
  policy_confirmed_at: string | null;
  // Iter 85 — Compliance salary block (parallel to actual salary above).
  compliance_gross?: number | null;
  compliance_structure_source?: "firm" | "custom" | null;
  compliance_basic_pct?: number | null;
  compliance_hra_pct?: number | null;
  compliance_conveyance_pct?: number | null;
  compliance_medical_pct?: number | null;
  compliance_special_pct?: number | null;
  compliance_others_pct?: number | null;
  compliance_basic_amt?: number | null;
  compliance_hra_amt?: number | null;
  compliance_conveyance_amt?: number | null;
  compliance_medical_amt?: number | null;
  compliance_special_amt?: number | null;
  compliance_others_amt?: number | null;
};

type PolicyPayload = {
  user_id: string;
  name: string;
  employee_code?: string | null;
  email?: string | null;
  join_date?: string | null;
  policy: Policy;
};

const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const SHIFT_OPTIONS = ["Morning", "Day", "General", "Evening", "Night", "Rotational"];

/**
 * Small helper to keep numeric input parsing consistent. Returns 0 for
 * empty/invalid strings so the form always sends a number to the API.
 */
function num(v: string | number | null | undefined): number {
  if (v === null || v === undefined || v === "") return 0;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

export default function EmployeePolicyScreenGate() {
  // Iter 57 — This assignment workflow is WEB-ONLY. On mobile we render a
  // friendly redirect card so admins know to use the web portal. Doing the
  // Platform check at the top of a wrapper component keeps the hooks-order
  // consistent in the actual screen below.
  const router = useRouter();
  if (Platform.OS !== "web") {
    return (
      <SafeAreaView style={styles.mobileGate} edges={["top", "bottom"]}>
        <Ionicons
          name="desktop-outline"
          size={44}
          color={colors.brandPrimary}
        />
        <Text style={styles.mobileGateTitle}>Web portal only</Text>
        <Text style={styles.mobileGateBody}>
          Employee Policy assignment is available on the web portal only.
          Open the S.K. Sharma & Co. portal on a desktop browser to configure
          per-employee salary, shift and attendance rules.
        </Text>
        <Pressable
          onPress={() => router.back()}
          style={styles.mobileGateBtn}
        >
          <Ionicons name="chevron-back" size={16} color="#fff" />
          <Text style={styles.mobileGateBtnTxt}>Back</Text>
        </Pressable>
      </SafeAreaView>
    );
  }
  return <EmployeePolicyScreen />;
}

function EmployeePolicyScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const params = useLocalSearchParams<{ user_id?: string }>();
  const targetUserId = params.user_id as string | undefined;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [payload, setPayload] = useState<PolicyPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState<Policy | null>(null);
  // Iter 85 — Firm's compliance policy (percentages + toggle). Loaded
  // once so the Compliance Salary section can show inherited defaults
  // and gate the "% bifurcation" vs "manual amounts" UI.
  const [firmComp, setFirmComp] = useState<{
    basic_pct?: number; hra_pct?: number; conveyance_pct?: number;
    medical_pct?: number; special_pct?: number; others_pct?: number;
    allow_percent_bifurcation?: boolean;
  } | null>(null);
  const isAdmin = user?.role === "company_admin" || user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  const load = useCallback(async () => {
    if (!targetUserId) {
      setErr("Missing employee");
      setLoading(false);
      return;
    }
    setLoading(true);
    setErr(null);
    try {
      const r = await api<PolicyPayload & { company_id?: string }>(`/admin/employees/${targetUserId}/policy`);
      setPayload(r);
      setForm(r.policy);
      // Iter 85 — Pull the firm's compliance policy so the compliance
      // section can display firm defaults and honour the
      // ``allow_percent_bifurcation`` toggle.
      const cid = (r as any).company_id || user?.company_id;
      if (cid) {
        try {
          const cp = await api<{ policy: any }>(`/admin/companies/${cid}/compliance-policy`);
          setFirmComp(cp?.policy || {});
        } catch { /* non-fatal */ }
      }
    } catch (e: any) {
      setErr(e?.message || "Failed to load policy");
    } finally {
      setLoading(false);
    }
  }, [targetUserId, user?.company_id]);

  useEffect(() => { load(); }, [load]);

  const showErr = (msg: string) => {
    if (Platform.OS === "web") {
       
      window.alert(msg);
    } else {
      Alert.alert("Policy", msg);
    }
  };

  const save = async () => {
    if (!form || !targetUserId) return;
    // Client-side mandatory validation (Salary 1 + Day 1)
    if (num(form.salary_1) <= 0 || num(form.day_1) <= 0) {
      showErr("Salary 1 and Day 1 are mandatory.");
      return;
    }
    if (num(form.salary_2) > 0 && num(form.day_2) <= 0) {
      showErr("Day 2 is required when Salary 2 is set.");
      return;
    }
    if (num(form.salary_3) > 0 && num(form.day_3) <= 0) {
      showErr("Day 3 is required when Salary 3 is set.");
      return;
    }
    setSaving(true);
    try {
      const r = await api<{ ok: boolean; policy: Policy }>(
        `/admin/employees/${targetUserId}/policy`,
        { method: "PATCH", body: form },
      );
      setForm(r.policy);
      setPayload((p) => (p ? { ...p, policy: r.policy } : p));
      showErr("Policy saved ✓");
      router.back();
    } catch (e: any) {
      showErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Admins only</Text>
        </View>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <View style={styles.root}>
        <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
          <View style={styles.header}>
            <Pressable onPress={() => router.back()} hitSlop={8}>
              <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
            </Pressable>
            <View style={{ flex: 1, alignItems: "center" }}>
              <Text style={styles.h1}>Salary policy</Text>
              {payload && (
                <Text style={styles.hsub}>
                  {payload.name}
                  {payload.employee_code ? ` · ${payload.employee_code}` : ""}
                </Text>
              )}
            </View>
            <View style={{ width: 26 }} />
          </View>
        </SafeAreaView>

        <KeyboardAwareScrollView bottomOffset={62}
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          {loading ? (
            <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
          ) : err ? (
            <View style={styles.empty}>
              <Ionicons name="warning-outline" size={40} color={colors.error} />
              <Text style={styles.emptyT}>{err}</Text>
            </View>
          ) : form ? (
            <>
              {/* Confirmation banner */}
              {form.policy_confirmed ? (
                <View style={[styles.banner, { backgroundColor: colors.brandTertiary }]}>
                  <Ionicons name="checkmark-circle" size={16} color={colors.onBrandTertiary} />
                  <Text style={[styles.bannerTxt, { color: colors.onBrandTertiary }]}>
                    Policy confirmed — edits will overwrite the existing policy.
                  </Text>
                </View>
              ) : (
                <View style={[styles.banner, { backgroundColor: "#FFF4E5" }]}>
                  <Ionicons name="information-circle" size={16} color="#B45309" />
                  <Text style={[styles.bannerTxt, { color: "#B45309" }]}>
                    Set the joining policy now — required before payroll can be processed correctly.
                  </Text>
                </View>
              )}

              {/* SECTION: Actual salary (base pay) */}
              <SectionTitle title="Actual Salary" />

              <Text style={styles.smallLabel}>Payment mode</Text>
              <View style={styles.modeRow} testID="policy-salary-mode">
                {(["monthly", "daily", "hourly"] as const).map((m) => {
                  const active = (form.salary_mode || "monthly") === m;
                  return (
                    <Pressable
                      key={m}
                      testID={`salary-mode-${m}`}
                      onPress={() => setForm({ ...form, salary_mode: m })}
                      style={[styles.modeChip, active && styles.modeChipActive]}
                    >
                      <Ionicons
                        name={
                          m === "monthly"
                            ? "calendar-outline"
                            : m === "daily"
                              ? "today-outline"
                              : "time-outline"
                        }
                        size={13}
                        color={active ? "#fff" : colors.brandPrimary}
                      />
                      <Text
                        style={[
                          styles.modeChipTxt,
                          active && styles.modeChipTxtActive,
                        ]}
                      >
                        {m.charAt(0).toUpperCase() + m.slice(1)}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
              <Text style={styles.help}>
                {form.salary_mode === "daily"
                  ? "Salary below is the per-day rate. Payroll = rate × present-days."
                  : form.salary_mode === "hourly"
                    ? "Salary below is the per-hour rate. Payroll = rate × total duty-hours."
                    : "Salary below is the fixed monthly amount, unaffected by attendance."}
              </Text>

              <NumField
                label={
                  form.salary_mode === "daily"
                    ? "Daily rate (₹)"
                    : form.salary_mode === "hourly"
                      ? "Hourly rate (₹)"
                      : "Monthly salary (₹)"
                }
                value={form.salary}
                onChange={(v) => setForm({ ...form, salary: v })}
                required
                testID="policy-salary"
              />

              {/* ================================================== */}
              {/* SECTION: Compliance Salary (Iter 85)               */}
              {/* Fully INDEPENDENT of Actual Salary. Bifurcation    */}
              {/* respects the firm's ``allow_percent_bifurcation``. */}
              {/* ================================================== */}
              <ComplianceSalarySection
                form={form}
                setForm={setForm}
                firm={firmComp}
                router={router}
                companyId={(payload as any)?.company_id || user?.company_id}
              />

              {/* Iter 85 — Umbrella heading for the remaining sections.
                  Everything below (tiers, shift, hours, leaves, weekly
                  off, biometric) forms the employee's Attendance Policy
                  used by the Actual Salary Process pipeline. */}
              <SectionTitle title="Attendance Policy" />

              {/* SECTION: Attendance-tier bonuses (Salary 1/2/3 + Day 1/2/3) */}
              <SectionTitle title="Attendance tier bonuses" />
              <Text style={styles.help}>
                An extra amount is unlocked when the employee&apos;s present-days
                cross each day threshold. <Text style={{ fontWeight: "700" }}>Tier 1 is mandatory.</Text> Tiers 2 & 3 optional.
              </Text>

              <TierRow
                label="Tier 1 (mandatory)"
                salary={form.salary_1}
                day={form.day_1}
                onSalary={(v) => setForm({ ...form, salary_1: v })}
                onDay={(v) => setForm({ ...form, day_1: v })}
                required
                testID="policy-tier-1"
              />
              <TierRow
                label="Tier 2 (optional)"
                salary={form.salary_2}
                day={form.day_2}
                onSalary={(v) => setForm({ ...form, salary_2: v })}
                onDay={(v) => setForm({ ...form, day_2: v })}
                testID="policy-tier-2"
              />
              <TierRow
                label="Tier 3 (optional)"
                salary={form.salary_3}
                day={form.day_3}
                onSalary={(v) => setForm({ ...form, salary_3: v })}
                onDay={(v) => setForm({ ...form, day_3: v })}
                testID="policy-tier-3"
              />

              {/* SECTION: Shift */}
              <SectionTitle title="Shift" />
              <SelectField
                label="Shift name"
                value={form.shift_name}
                options={SHIFT_OPTIONS}
                onChange={(v) => setForm({ ...form, shift_name: v })}
              />
              <SelectField
                label="Shift name (dummy / alternate)"
                value={form.shift_dummy}
                options={SHIFT_OPTIONS}
                onChange={(v) => setForm({ ...form, shift_dummy: v })}
                clearable
              />
              <SelectField
                label="Dummy weekly off"
                value={form.dummy_weekly_off !== null ? DAY_NAMES[form.dummy_weekly_off] : null}
                options={DAY_NAMES}
                onChange={(v) => {
                  const idx = DAY_NAMES.indexOf(v || "");
                  setForm({ ...form, dummy_weekly_off: idx >= 0 ? idx : null });
                }}
                clearable
              />

              {/* SECTION: Working hours */}
              <SectionTitle title="Hours" />
              <NumField
                label="Working hours per day"
                value={form.working_hours}
                onChange={(v) => setForm({ ...form, working_hours: v })}
                decimal
              />
              <View style={{ flexDirection: "row", gap: 12 }}>
                <View style={{ flex: 1 }}>
                  <NumField
                    label="Full-day min hours"
                    value={form.fullday_hours}
                    onChange={(v) => setForm({ ...form, fullday_hours: v })}
                    decimal
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <NumField
                    label="Half-day min hours"
                    value={form.halfday_hours}
                    onChange={(v) => setForm({ ...form, halfday_hours: v })}
                    decimal
                  />
                </View>
              </View>
              <SwitchRow
                label="Full Day Salary (pay full even below threshold)"
                value={form.full_day_salary}
                onChange={(v) => setForm({ ...form, full_day_salary: v })}
              />
              <SwitchRow
                label="OT Allow (pay overtime beyond expected hours)"
                value={form.ot_allow}
                onChange={(v) => setForm({ ...form, ot_allow: v })}
              />

              {/* SECTION: Leaves */}
              <SectionTitle title="Leave quota (per year)" />
              <View style={{ flexDirection: "row", gap: 12 }}>
                <View style={{ flex: 1 }}>
                  <NumField
                    label="CL days"
                    value={form.cl_days}
                    onChange={(v) => setForm({ ...form, cl_days: v })}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <NumField
                    label="PL days"
                    value={form.pl_days}
                    onChange={(v) => setForm({ ...form, pl_days: v })}
                  />
                </View>
              </View>

              {/* SECTION: Weekly off */}
              <SectionTitle title="Weekly off" />
              <SelectField
                label="Weekly off day"
                value={DAY_NAMES[form.weekly_off]}
                options={DAY_NAMES}
                onChange={(v) => {
                  const idx = DAY_NAMES.indexOf(v || "Sunday");
                  setForm({ ...form, weekly_off: Math.max(0, idx) });
                }}
              />
              <NumField
                label="Week off min hours"
                value={form.week_off_min_hours}
                onChange={(v) => setForm({ ...form, week_off_min_hours: v })}
                decimal
              />
              <SwitchRow
                label="Weekly-off counted as attended day"
                value={form.weekly_off_attendance}
                onChange={(v) => setForm({ ...form, weekly_off_attendance: v })}
              />

              {/* SECTION: Bio code */}
              <SectionTitle title="Biometric" />
              <TextField
                label="Bio code (device / punch-machine id)"
                value={form.bio_code || ""}
                onChange={(v) => setForm({ ...form, bio_code: v || null })}
                keyboardType="default"
              />

              <Pressable
                onPress={save}
                disabled={saving}
                style={[styles.saveBtn, saving && { opacity: 0.7 }]}
                testID="policy-save"
              >
                {saving ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons name="save-outline" size={18} color="#fff" />
                    <Text style={styles.saveTxt}>Save policy</Text>
                  </>
                )}
              </Pressable>

              <View style={{ height: 40 }} />
            </>
          ) : null}
        </KeyboardAwareScrollView>
      </View>
    </KeyboardAvoidingView>
  );
}

/* ------------------------------------------------------------------ */
/* Reusable field components                                           */
/* ------------------------------------------------------------------ */

/**
 * Iter 85 — Compliance Salary block.
 *
 *   • ``compliance_gross`` — monthly gross/CTC figure (independent of
 *     Actual Salary).
 *   • Firm toggle ``allow_percent_bifurcation`` decides whether the
 *     structure is auto-computed from %s or entered as flat amounts.
 *   • Per-employee ``structure_source`` chooses between firm defaults
 *     and a custom override kept on the employee.
 */
function ComplianceSalarySection({
  form, setForm, firm, router, companyId,
}: {
  form: Policy;
  setForm: (p: Policy) => void;
  firm: {
    basic_pct?: number; hra_pct?: number; conveyance_pct?: number;
    medical_pct?: number; special_pct?: number; others_pct?: number;
    allow_percent_bifurcation?: boolean;
  } | null;
  router: any;
  companyId?: string | null;
}) {
  const allowPct = firm?.allow_percent_bifurcation !== false; // default: true
  const source = form.compliance_structure_source || "firm";
  const gross = Number(form.compliance_gross || 0);

  // Resolve effective percentages: firm defaults, then employee override
  // when source === "custom".
  const pct = (k: keyof Policy, firmVal?: number) => {
    if (source === "custom") return Number((form as any)[k] || 0);
    return Number(firmVal || 0);
  };
  const basicPct   = pct("compliance_basic_pct",      firm?.basic_pct);
  const hraPct     = pct("compliance_hra_pct",        firm?.hra_pct);
  const convPct    = pct("compliance_conveyance_pct", firm?.conveyance_pct);
  const medPct     = pct("compliance_medical_pct",    firm?.medical_pct);
  const specialPct = pct("compliance_special_pct",    firm?.special_pct);
  const othersPct  = pct("compliance_others_pct",     firm?.others_pct);

  const totalPct = basicPct + hraPct + convPct + medPct + specialPct + othersPct;

  // Computed amounts (only when % bifurcation is allowed).
  const amt = (p: number) => Math.round((gross * p) / 100);
  const basicAmt = allowPct ? amt(basicPct) : Number(form.compliance_basic_amt || 0);
  const hraAmt   = allowPct ? amt(hraPct)   : Number(form.compliance_hra_amt   || 0);
  const convAmt  = allowPct ? amt(convPct)  : Number(form.compliance_conveyance_amt || 0);
  const medAmt   = allowPct ? amt(medPct)   : Number(form.compliance_medical_amt || 0);
  const spAmt    = allowPct ? amt(specialPct) : Number(form.compliance_special_amt || 0);
  const othAmt   = allowPct ? amt(othersPct)  : Number(form.compliance_others_amt   || 0);
  const totalAmt = basicAmt + hraAmt + convAmt + medAmt + spAmt + othAmt;

  return (
    <>
      <SectionTitle title="Compliance Salary" />

      <Text style={styles.help}>
        Independent of Actual Salary above. Used for PF / ESIC / TDS /
        statutory pay-run.
        {allowPct
          ? " Firm allows % bifurcation — set Gross and the structure is auto-computed."
          : " Firm has disabled % bifurcation — enter each Basic / HRA / … amount manually."}
      </Text>

      <NumField
        label="Compliance Gross / CTC (₹)"
        value={Number(form.compliance_gross || 0)}
        onChange={(v) => setForm({ ...form, compliance_gross: v })}
        testID="policy-compliance-gross"
      />

      {allowPct ? (
        <>
          <Text style={styles.smallLabel}>Structure source</Text>
          <View style={styles.modeRow}>
            {(["firm", "custom"] as const).map((m) => {
              const active = source === m;
              return (
                <Pressable
                  key={m}
                  onPress={() => setForm({ ...form, compliance_structure_source: m })}
                  style={[styles.modeChip, active && styles.modeChipActive]}
                  testID={`policy-comp-source-${m}`}
                >
                  <Ionicons
                    name={m === "firm" ? "business-outline" : "person-outline"}
                    size={13}
                    color={active ? "#fff" : colors.brandPrimary}
                  />
                  <Text
                    style={[
                      styles.modeChipTxt,
                      active && styles.modeChipTxtActive,
                    ]}
                  >
                    {m === "firm" ? "Firm defaults" : "Custom for this employee"}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          {source === "firm" ? (
            <View style={{ marginTop: 4 }}>
              <Text style={styles.help}>
                Using the firm&apos;s compliance policy. Change the firm-wide
                percentages in{" "}
                <Text
                  onPress={() =>
                    router.push(
                      companyId
                        ? `/compliance-policy?company_id=${encodeURIComponent(companyId)}`
                        : "/compliance-policy",
                    )
                  }
                  style={{ color: colors.brandPrimary, fontWeight: "700" }}
                >
                  Firm Settings
                </Text>
                .
              </Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                <RoPctChip label="Basic" pct={basicPct} amt={basicAmt} />
                <RoPctChip label="HRA" pct={hraPct} amt={hraAmt} />
                <RoPctChip label="Conveyance" pct={convPct} amt={convAmt} />
                <RoPctChip label="Medical" pct={medPct} amt={medAmt} />
                <RoPctChip label="Special" pct={specialPct} amt={spAmt} />
                <RoPctChip label="Others" pct={othersPct} amt={othAmt} />
              </View>
            </View>
          ) : (
            <>
              <Text style={styles.help}>
                Enter percentages of Gross for this employee only. Total should
                normally sum to 100%.
              </Text>
              <View style={{ flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
                <View style={{ flex: 1, minWidth: 140 }}>
                  <NumField
                    label="Basic (%)"
                    value={Number(form.compliance_basic_pct || 0)}
                    onChange={(v) => setForm({ ...form, compliance_basic_pct: v })}
                    decimal
                  />
                </View>
                <View style={{ flex: 1, minWidth: 140 }}>
                  <NumField
                    label="HRA (%)"
                    value={Number(form.compliance_hra_pct || 0)}
                    onChange={(v) => setForm({ ...form, compliance_hra_pct: v })}
                    decimal
                  />
                </View>
                <View style={{ flex: 1, minWidth: 140 }}>
                  <NumField
                    label="Conveyance (%)"
                    value={Number(form.compliance_conveyance_pct || 0)}
                    onChange={(v) => setForm({ ...form, compliance_conveyance_pct: v })}
                    decimal
                  />
                </View>
                <View style={{ flex: 1, minWidth: 140 }}>
                  <NumField
                    label="Medical (%)"
                    value={Number(form.compliance_medical_pct || 0)}
                    onChange={(v) => setForm({ ...form, compliance_medical_pct: v })}
                    decimal
                  />
                </View>
                <View style={{ flex: 1, minWidth: 140 }}>
                  <NumField
                    label="Special (%)"
                    value={Number(form.compliance_special_pct || 0)}
                    onChange={(v) => setForm({ ...form, compliance_special_pct: v })}
                    decimal
                  />
                </View>
                <View style={{ flex: 1, minWidth: 140 }}>
                  <NumField
                    label="Others (%)"
                    value={Number(form.compliance_others_pct || 0)}
                    onChange={(v) => setForm({ ...form, compliance_others_pct: v })}
                    decimal
                  />
                </View>
              </View>
            </>
          )}
        </>
      ) : (
        <>
          <Text style={styles.help}>
            % bifurcation disabled by firm. Enter each amount directly.
          </Text>
          <View style={{ flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
            <View style={{ flex: 1, minWidth: 140 }}>
              <NumField
                label="Basic (₹)"
                value={Number(form.compliance_basic_amt || 0)}
                onChange={(v) => setForm({ ...form, compliance_basic_amt: v })}
              />
            </View>
            <View style={{ flex: 1, minWidth: 140 }}>
              <NumField
                label="HRA (₹)"
                value={Number(form.compliance_hra_amt || 0)}
                onChange={(v) => setForm({ ...form, compliance_hra_amt: v })}
              />
            </View>
            <View style={{ flex: 1, minWidth: 140 }}>
              <NumField
                label="Conveyance (₹)"
                value={Number(form.compliance_conveyance_amt || 0)}
                onChange={(v) => setForm({ ...form, compliance_conveyance_amt: v })}
              />
            </View>
            <View style={{ flex: 1, minWidth: 140 }}>
              <NumField
                label="Medical (₹)"
                value={Number(form.compliance_medical_amt || 0)}
                onChange={(v) => setForm({ ...form, compliance_medical_amt: v })}
              />
            </View>
            <View style={{ flex: 1, minWidth: 140 }}>
              <NumField
                label="Special (₹)"
                value={Number(form.compliance_special_amt || 0)}
                onChange={(v) => setForm({ ...form, compliance_special_amt: v })}
              />
            </View>
            <View style={{ flex: 1, minWidth: 140 }}>
              <NumField
                label="Others (₹)"
                value={Number(form.compliance_others_amt || 0)}
                onChange={(v) => setForm({ ...form, compliance_others_amt: v })}
              />
            </View>
          </View>
        </>
      )}

      {/* Totals band */}
      <View style={styles.compTotals}>
        <View style={{ flex: 1 }}>
          <Text style={styles.compTotalsLabel}>Gross ₹</Text>
          <Text style={styles.compTotalsValue}>₹{gross.toLocaleString("en-IN")}</Text>
        </View>
        {allowPct ? (
          <View style={{ flex: 1 }}>
            <Text style={styles.compTotalsLabel}>Structure %</Text>
            <Text
              style={[
                styles.compTotalsValue,
                Math.abs(totalPct - 100) > 0.5 && { color: colors.warning },
              ]}
            >
              {totalPct.toFixed(1)}%
            </Text>
          </View>
        ) : null}
        <View style={{ flex: 1 }}>
          <Text style={styles.compTotalsLabel}>Sum of heads ₹</Text>
          <Text
            style={[
              styles.compTotalsValue,
              gross > 0 && Math.abs(totalAmt - gross) > 5 && { color: colors.warning },
            ]}
          >
            ₹{Math.round(totalAmt).toLocaleString("en-IN")}
          </Text>
        </View>
      </View>
    </>
  );
}

function RoPctChip({ label, pct, amt }: { label: string; pct: number; amt: number }) {
  return (
    <View style={styles.roChip}>
      <Text style={styles.roChipLabel}>{label}</Text>
      <Text style={styles.roChipPct}>{Number(pct || 0)}%</Text>
      <Text style={styles.roChipAmt}>₹{Math.round(amt || 0).toLocaleString("en-IN")}</Text>
    </View>
  );
}

function SectionTitle({ title }: { title: string }) {
  return <Text style={styles.section}>{title}</Text>;
}

function NumField({
  label, value, onChange, required, decimal, testID,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  required?: boolean;
  decimal?: boolean;
  testID?: string;
}) {
  const [text, setText] = useState(value ? String(value) : "");
  useEffect(() => {
    setText(value ? String(value) : "");
  }, [value]);
  return (
    <View style={styles.field}>
      <Text style={styles.label}>
        {label}
        {required ? <Text style={{ color: colors.error }}> *</Text> : null}
      </Text>
      <TextInput
        testID={testID}
        style={styles.input}
        value={text}
        onChangeText={(t) => {
          setText(t);
          const cleaned = t.replace(/[^0-9.]/g, "");
          onChange(num(cleaned));
        }}
        keyboardType={decimal ? "decimal-pad" : "number-pad"}
        placeholder="0"
        placeholderTextColor={colors.onSurfaceTertiary}
      />
    </View>
  );
}

function TextField({
  label, value, onChange, keyboardType,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  keyboardType?: "default" | "email-address" | "number-pad";
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChange}
        keyboardType={keyboardType || "default"}
        placeholderTextColor={colors.onSurfaceTertiary}
      />
    </View>
  );
}

function TierRow({
  label, salary, day, onSalary, onDay, required, testID,
}: {
  label: string;
  salary: number;
  day: number;
  onSalary: (v: number) => void;
  onDay: (v: number) => void;
  required?: boolean;
  testID?: string;
}) {
  return (
    <View style={styles.tierRow} testID={testID}>
      <Text style={styles.tierLabel}>
        {label}
        {required ? <Text style={{ color: colors.error }}> *</Text> : null}
      </Text>
      <View style={{ flexDirection: "row", gap: 8 }}>
        <View style={{ flex: 1.3 }}>
          <NumField
            label="Bonus amount (₹)"
            value={salary}
            onChange={onSalary}
            required={required}
          />
        </View>
        <View style={{ flex: 1 }}>
          <NumField
            label="Day threshold"
            value={day}
            onChange={onDay}
            required={required}
          />
        </View>
      </View>
    </View>
  );
}

function SelectField({
  label, value, options, onChange, clearable,
}: {
  label: string;
  value: string | null;
  options: string[];
  onChange: (v: string | null) => void;
  clearable?: boolean;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.chipsRow}>
        {options.map((opt) => {
          const active = value === opt;
          return (
            <Pressable
              key={opt}
              onPress={() => onChange(active && clearable ? null : opt)}
              style={[styles.chip, active && styles.chipActive]}
            >
              <Text style={[styles.chipTxt, active && styles.chipTxtActive]}>{opt}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function SwitchRow({
  label, value, onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <View style={styles.switchRow}>
      <Text style={styles.switchLabel}>{label}</Text>
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ true: colors.brandPrimary, false: colors.border }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },

  // Iter 57 — mobile-gate for the web-only Employee Policy workflow.
  mobileGate: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    gap: spacing.md,
    backgroundColor: colors.surface,
  },
  mobileGateTitle: {
    color: colors.onSurface,
    fontSize: type.lg,
    fontWeight: "800",
  },
  mobileGateBody: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    textAlign: "center",
    lineHeight: 20,
    maxWidth: 320,
  },
  mobileGateBtn: {
    marginTop: spacing.md,
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: radius.md,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  mobileGateBtnTxt: { color: "#fff", fontWeight: "800", fontSize: type.sm },

  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { fontSize: type.lg, color: colors.onSurface, fontWeight: "700" },
  hsub: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xl },
  empty: { alignItems: "center", paddingVertical: 60, gap: 8 },
  emptyT: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  forbT: { color: colors.onSurface, fontSize: type.lg, fontWeight: "600" },

  banner: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderRadius: radius.md, padding: 10, marginBottom: spacing.md,
  },
  bannerTxt: { fontSize: 12, fontWeight: "600", flex: 1 },

  section: {
    color: colors.brandPrimary, fontSize: type.sm, fontWeight: "800",
    marginTop: spacing.md, marginBottom: 6,
    textTransform: "uppercase", letterSpacing: 0.6,
  },
  help: { color: colors.onSurfaceTertiary, fontSize: 11, marginBottom: 8, lineHeight: 16 },
  smallLabel: {
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.3,
    marginTop: 6,
    marginBottom: 6,
  },
  modeRow: {
    flexDirection: "row",
    gap: 6,
    marginBottom: 8,
  },
  modeChip: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingVertical: 8,
    paddingHorizontal: 8,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
  modeChipActive: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandPrimary,
  },
  modeChipTxt: {
    color: colors.onSurfaceSecondary,
    fontWeight: "600",
    fontSize: 12,
  },
  modeChipTxtActive: { color: "#fff" },

  field: { marginBottom: spacing.sm },
  label: { color: colors.onSurfaceSecondary, fontSize: 12, marginBottom: 4, fontWeight: "600" },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 10, paddingHorizontal: 12,
    color: colors.onSurface, fontSize: 14,
  },

  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: {
    paddingVertical: 6, paddingHorizontal: 12,
    borderRadius: 999,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { color: colors.onSurfaceSecondary, fontSize: 12, fontWeight: "600" },
  chipTxtActive: { color: "#fff" },

  tierRow: {
    marginBottom: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: 10,
  },
  tierLabel: { color: colors.onSurface, fontSize: 13, fontWeight: "700", marginBottom: 6 },

  switchRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    paddingVertical: 8, paddingHorizontal: 12,
    marginBottom: spacing.sm,
  },
  switchLabel: { color: colors.onSurface, fontSize: 13, fontWeight: "500", flex: 1, paddingRight: 12 },

  saveBtn: {
    marginTop: spacing.md,
    backgroundColor: colors.cta,
    borderRadius: radius.md,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  saveTxt: { color: "#fff", fontSize: type.base, fontWeight: "700" },

  // Iter 85 — Compliance Salary section styles.
  roChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
  roChipLabel: { color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "700" },
  roChipPct: { color: colors.brandPrimary, fontSize: 11, fontWeight: "800" },
  roChipAmt: { color: colors.onSurface, fontSize: 11, fontWeight: "600" },
  compTotals: {
    flexDirection: "row",
    gap: 12,
    marginTop: 12,
    padding: 10,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
  },
  compTotalsLabel: {
    fontSize: 10,
    fontWeight: "700",
    textTransform: "uppercase",
    color: colors.onSurfaceSecondary,
    letterSpacing: 0.3,
  },
  compTotalsValue: {
    fontSize: 14,
    fontWeight: "800",
    color: colors.onSurface,
    marginTop: 2,
  },
});
