/**
 * Firm-wise Compliance Policy — Iter 59 (Web only).
 *
 * Super Admin picks a firm and overrides the global Compliance defaults.
 * Any field left blank inherits the global default (see
 * utils/compliance_salary.py). Overrides are stored at
 * companies.compliance_policy and picked up by every subsequent
 * Compliance Salary Run.
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
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };
type Policy = {
  pf_employee_rate?: number;
  pf_employer_rate?: number;
  pf_admin_rate?: number;
  pf_wage_cap?: number;
  esic_employee_rate?: number;
  esic_employer_rate?: number;
  esic_wage_threshold?: number;
  tds_regime?: string;
  apply_pf?: boolean;
  apply_esic?: boolean;
  apply_pt?: boolean;
  apply_tds?: boolean;
  // Iter 68 — Salary structure defaults (percent of monthly gross).
  basic_pct?: number;
  hra_pct?: number;
  conveyance_pct?: number;
  medical_pct?: number;
  special_pct?: number;
  others_pct?: number;
  stat_wage_floor_pct?: number;
  // Iter 85 — Enabled allowance heads for this firm. Basic is ALWAYS
  // included implicitly; the rest are opt-in per firm and drive which
  // columns appear on the Compliance Salary Process grid.
  enabled_allowances?: string[];
  allow_percent_bifurcation?: boolean;
  notes?: string;
};

const NUM_FIELDS: { key: keyof Policy; label: string; hint: string; global: string }[] = [
  { key: "pf_employee_rate", label: "PF Employee %", hint: "e.g. 12", global: "Global default: 12%" },
  { key: "pf_employer_rate", label: "PF Employer %", hint: "e.g. 12", global: "Global default: 12%" },
  { key: "pf_admin_rate", label: "PF Admin %", hint: "e.g. 0.5", global: "Global default: 0.5%" },
  { key: "pf_wage_cap", label: "PF Wage Cap (₹)", hint: "e.g. 15000", global: "Statutory cap: ₹15,000" },
  { key: "esic_employee_rate", label: "ESIC Employee %", hint: "e.g. 0.75", global: "Global default: 0.75%" },
  { key: "esic_employer_rate", label: "ESIC Employer %", hint: "e.g. 3.25", global: "Global default: 3.25%" },
  { key: "esic_wage_threshold", label: "ESIC Wage Threshold (₹)", hint: "e.g. 21000", global: "Statutory: ₹21,000" },
  { key: "stat_wage_floor_pct", label: "Wage Floor %", hint: "e.g. 50", global: "New labour code default: 50% of Gross" },
];

// Iter 68 — Salary structure defaults (% of monthly gross).  Editable
// only from Firm Settings; the Compliance Salary screen reads these
// values as read-only.
const STRUCTURE_FIELDS: { key: keyof Policy; label: string; hint: string; global: string }[] = [
  { key: "basic_pct", label: "Basic %", hint: "e.g. 40", global: "Global default: 40%" },
  { key: "hra_pct", label: "HRA %", hint: "e.g. 20", global: "Global default: 20%" },
  { key: "conveyance_pct", label: "Conveyance %", hint: "e.g. 5", global: "Global default: 5%" },
  { key: "medical_pct", label: "Medical %", hint: "e.g. 3", global: "Global default: 3%" },
  { key: "special_pct", label: "Special %", hint: "e.g. 32", global: "Global default: 32%" },
  { key: "others_pct", label: "Others %", hint: "e.g. 0", global: "Global default: 0%" },
];

const TOGGLES: { key: keyof Policy; label: string }[] = [
  { key: "apply_pf", label: "Apply PF" },
  { key: "apply_esic", label: "Apply ESIC" },
  { key: "apply_pt", label: "Apply Professional Tax" },
  { key: "apply_tds", label: "Apply TDS" },
];

// Iter 85 — Allowance head catalogue used on the Compliance Policy
// toggle grid. `basic` is locked ON (statutory).
const ALLOWANCES_META: { key: string; label: string; hint?: string }[] = [
  { key: "basic",      label: "Basic",       hint: "Statutory floor — always applied" },
  { key: "hra",        label: "HRA",         hint: "House Rent Allowance" },
  { key: "conveyance", label: "Conveyance",  hint: "Travel / conveyance allowance" },
  { key: "medical",    label: "Medical",     hint: "Medical reimbursement" },
  { key: "special",    label: "Special",     hint: "Special allowance" },
  { key: "others",     label: "Others",      hint: "Any other statutory head" },
];

// Iter 85 — Default enabled set when a firm hasn't chosen yet.
const DEFAULT_ALLOWANCES = ["basic", "hra", "conveyance", "medical", "special"];

export function isAllowanceEnabled(list: string[] | undefined, key: string): boolean {
  const arr = (list && list.length > 0) ? list : DEFAULT_ALLOWANCES;
  if (key === "basic") return true;  // always
  return arr.includes(key);
}

export function toggleAllowance(list: string[] | undefined, key: string): string[] {
  const arr = (list && list.length > 0) ? [...list] : [...DEFAULT_ALLOWANCES];
  if (!arr.includes("basic")) arr.unshift("basic");
  if (key === "basic") return arr;  // locked
  const i = arr.indexOf(key);
  if (i >= 0) arr.splice(i, 1);
  else arr.push(key);
  return arr;
}

function showMsg(msg: string, title = "Compliance Policy") {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

export default function CompliancePolicyScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState<string>("");
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  useEffect(() => {
    if (globalCid) setCompanyId(globalCid);
  }, [globalCid]);
  const [policy, setPolicy] = useState<Policy>({});
  // Iter 178 — state-wise PT catalogue.
  const [ptStates, setPtStates] = useState<{ state: string; slabs: any[]; has_pt: boolean }[]>([]);
  useEffect(() => {
    api<{ states: any[] }>("/admin/pt-states").then((r) => setPtStates(r.states || [])).catch(() => {});
  }, []);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isSuper) return;
    (async () => {
      try {
        const r = await api<{ companies: Company[] }>("/companies");
        setCompanies(r.companies || []);
        if (r.companies?.length && !companyId) setCompanyId(r.companies[0].company_id);
      } catch (e: any) {
        showMsg(e?.message || "Could not load companies");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSuper]);

  const loadPolicy = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      const r = await api<{ policy: Policy }>(
        `/admin/companies/${companyId}/compliance-policy`,
      );
      setPolicy(r.policy || {});
    } catch (e: any) {
      showMsg(e?.message || "Could not load policy");
    } finally {
      setLoading(false);
    }
  }, [companyId]);

  useEffect(() => {
    void loadPolicy();
  }, [loadPolicy]);

  const setNum = (k: keyof Policy, v: string) => {
    const cleaned = v.trim();
    if (cleaned === "") {
      setPolicy((p) => {
        const next = { ...p };
        delete next[k];
        return next;
      });
      return;
    }
    const n = Number(cleaned);
    if (Number.isFinite(n)) {
      setPolicy((p) => ({ ...p, [k]: n }));
    }
  };

  const setToggle = (k: keyof Policy, v: boolean | null) => {
    setPolicy((p) => {
      const next = { ...p };
      if (v === null) delete next[k];
      else (next as any)[k] = v;
      return next;
    });
  };

  const save = async () => {
    if (!companyId) return;
    setSaving(true);
    try {
      const body: any = { ...policy };
      await api(`/admin/companies/${companyId}/compliance-policy`, {
        method: "PUT",
        body,
      });
      showMsg("Firm-wise compliance policy saved.");
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!isSuper || Platform.OS !== "web") {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>
            Firm-wise Compliance Policy is available only to the Super Admin on the Web portal.
          </Text>
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
            <Text style={styles.h1}>Compliance Policy — Firm-wise</Text>
            <Text style={styles.hsub}>
              Override statutory defaults per firm. Blank = inherit global.
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.card}>
          <Text style={styles.label}>Company (Firm)</Text>
          <select
            testID="cp-company"
            value={companyId}
            onChange={(e) => setCompanyId((e.target as HTMLSelectElement).value)}
            style={{
              padding: 10,
              borderRadius: 8,
              borderColor: colors.borderStrong,
              borderWidth: 1,
              fontSize: 14,
              width: "100%",
            } as any}
          >
            <option value="">— select —</option>
            {companies.map((c) => (
              <option key={c.company_id} value={c.company_id}>
                {c.name}
              </option>
            ))}
          </select>
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: 20 }} />
        ) : (
          <>
            <View style={styles.card}>
              <Text style={styles.stepTitle}>Applied statutes</Text>
              {TOGGLES.map((t) => {
                const v = (policy as any)[t.key] as boolean | undefined;
                return (
                  <View key={t.key as string} style={styles.toggleRow}>
                    <Text style={styles.toggleLbl}>{t.label}</Text>
                    <View style={{ flexDirection: "row", gap: 6 }}>
                      {[
                        { lbl: "Inherit", val: null },
                        { lbl: "On", val: true },
                        { lbl: "Off", val: false },
                      ].map((opt) => {
                        const active =
                          (opt.val === null && v === undefined) ||
                          (opt.val === true && v === true) ||
                          (opt.val === false && v === false);
                        return (
                          <Pressable
                            key={String(opt.val)}
                            onPress={() => setToggle(t.key, opt.val as any)}
                            style={[styles.chip, active && styles.chipActive]}
                          >
                            <Text
                              style={[
                                styles.chipTxt,
                                { color: active ? "#fff" : colors.onSurfaceSecondary },
                              ]}
                            >
                              {opt.lbl}
                            </Text>
                          </Pressable>
                        );
                      })}
                    </View>
                  </View>
                );
              })}
            </View>

            <View style={styles.card}>
              <Text style={styles.stepTitle}>Rates & thresholds</Text>
              <View style={styles.gridRow}>
                {NUM_FIELDS.map((f) => (
                  <View key={f.key as string} style={styles.gridCol}>
                    <Text style={styles.label}>{f.label}</Text>
                    <TextInput
                      testID={`cp-${f.key as string}`}
                      value={
                        (policy as any)[f.key] === undefined ||
                        (policy as any)[f.key] === null
                          ? ""
                          : String((policy as any)[f.key])
                      }
                      onChangeText={(v) => setNum(f.key, v)}
                      placeholder={f.hint}
                      placeholderTextColor={colors.onSurfaceTertiary}
                      keyboardType="decimal-pad"
                      style={styles.input}
                    />
                    <Text style={styles.smallHint}>{f.global}</Text>
                  </View>
                ))}
                <View style={styles.gridCol}>
                  <Text style={styles.label}>TDS Regime</Text>
                  <select
                    value={policy.tds_regime ?? ""}
                    onChange={(e) =>
                      setPolicy((p) => ({
                        ...p,
                        tds_regime:
                          (e.target as HTMLSelectElement).value || undefined,
                      }))
                    }
                    style={{
                      padding: 10,
                      borderRadius: 8,
                      borderColor: colors.borderStrong,
                      borderWidth: 1,
                      fontSize: 14,
                      width: "100%",
                    } as any}
                  >
                    <option value="">Inherit</option>
                    <option value="new">New Regime</option>
                    <option value="old">Old Regime</option>
                  </select>
                </View>
              </View>
            </View>

            {/* Iter 85 — Allowance selection card.  Basic is always on
                (statutory floor); the remaining heads are opt-in per
                firm and drive which columns appear on the Compliance
                Salary Process grid. */}
            <View style={styles.card}>
              <View style={styles.cardHead}>
                <Ionicons name="options-outline" size={18} color={colors.brandPrimary} />
                <Text style={styles.cardTitle}>Compliance Allowances</Text>
              </View>
              <Text style={styles.smallHint}>
                Pick which allowance heads apply to this firm. Basic is
                always included (statutory). Only the enabled ones are
                shown on the Compliance Salary Process grid.
              </Text>
              <View style={styles.allowGrid}>
                {ALLOWANCES_META.map((a) => {
                  const enabled = isAllowanceEnabled(policy.enabled_allowances, a.key);
                  const locked = a.key === "basic";
                  return (
                    <Pressable
                      key={a.key}
                      onPress={() => {
                        if (locked) return;
                        setPolicy((p) => ({
                          ...p,
                          enabled_allowances: toggleAllowance(
                            p.enabled_allowances, a.key,
                          ),
                        }));
                      }}
                      style={[
                        styles.allowChip,
                        enabled && styles.allowChipOn,
                        locked && styles.allowChipLocked,
                      ]}
                      testID={`allow-${a.key}`}
                    >
                      <Ionicons
                        name={enabled ? "checkbox" : "square-outline"}
                        size={16}
                        color={enabled ? "#fff" : colors.brandPrimary}
                      />
                      <View style={{ flex: 1 }}>
                        <Text style={[styles.allowLabel, enabled && { color: "#fff" }]}>
                          {a.label}
                          {locked ? "  ·  (Always on)" : ""}
                        </Text>
                        {a.hint ? (
                          <Text
                            style={[
                              styles.allowHint,
                              enabled && { color: "rgba(255,255,255,0.85)" },
                            ]}
                          >
                            {a.hint}
                          </Text>
                        ) : null}
                      </View>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            {/* Iter 178 — State-wise Professional Tax */}
            <View style={styles.card} testID="pt-state-card">
              <Text style={styles.label}>Professional Tax — State (auto slabs)</Text>
              <Text style={{ fontSize: 11, color: colors.onSurfaceSecondary, marginBottom: 8 }}>
                Pick the firm&apos;s state — statutory monthly PT slabs apply automatically
                in Compliance Salary. Per-employee PT override still wins.
              </Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                {ptStates.map((s) => {
                  const on = (policy as any).pt_state === s.state;
                  return (
                    <Pressable key={s.state}
                      onPress={() => setPolicy((p) => ({ ...p, pt_state: on ? "" : s.state } as any))}
                      style={[styles.allowChip, on && styles.allowChipOn, { minWidth: 120 }]}
                      testID={`pt-state-${s.state}`}>
                      <Text style={[styles.allowLabel, on && { color: "#fff" }]}>
                        {s.state}{s.has_pt ? "" : " (No PT)"}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
              {(policy as any).pt_state ? (
                <View style={{ marginTop: 8 }}>
                  <Text style={[styles.label, { fontSize: 11 }]}>
                    {(policy as any).pt_state} slabs (monthly gross → PT ₹):
                  </Text>
                  {(ptStates.find((s) => s.state === (policy as any).pt_state)?.slabs || []).map((sl: any, i: number) => (
                    <Text key={i} style={{ fontSize: 11, color: colors.onSurfaceSecondary }}>
                      {sl.upto == null ? "Above previous slab" : `Up to ₹${sl.upto}`} → ₹{sl.amount}
                    </Text>
                  ))}
                  {!(ptStates.find((s) => s.state === (policy as any).pt_state)?.slabs || []).length ? (
                    <Text style={{ fontSize: 11, color: colors.onSurfaceSecondary }}>No Professional Tax in this state.</Text>
                  ) : null}
                </View>
              ) : null}
            </View>

            <View style={styles.card}>
              <Text style={styles.label}>Notes</Text>
              <TextInput
                value={policy.notes ?? ""}
                onChangeText={(v) => setPolicy((p) => ({ ...p, notes: v || undefined }))}
                placeholder="Free-form notes for the compliance team..."
                placeholderTextColor={colors.onSurfaceTertiary}
                multiline
                style={[styles.input, { minHeight: 60, textAlignVertical: "top" }]}
              />
            </View>

            <Pressable
              onPress={save}
              disabled={saving || !companyId}
              style={[styles.primaryBtn, (saving || !companyId) && { opacity: 0.5 }]}
              testID="cp-save"
            >
              {saving ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="save-outline" size={16} color="#fff" />
                  <Text style={styles.primaryBtnTxt}>Save firm-wise policy</Text>
                </>
              )}
            </Pressable>
          </>
        )}
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
  stepTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800", marginBottom: 8 },
  smallHint: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 2 },
  gridRow: { flexDirection: "row", gap: 12, flexWrap: "wrap" },
  gridCol: { flex: 1, minWidth: 220, marginBottom: 8 },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  toggleLbl: { color: colors.onSurface, fontSize: 13, fontWeight: "600" },
  chip: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11, fontWeight: "700" },

  // Iter 85 — Compliance Allowances toggle grid.
  cardHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 6,
  },
  cardTitle: {
    fontSize: 15,
    fontWeight: "800",
    color: colors.onSurface,
  },
  allowGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 10,
  },
  allowChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surface,
    minWidth: 220,
    flexGrow: 1,
    flexBasis: 220,
  },
  allowChipOn: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandPrimary,
  },
  allowChipLocked: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandPrimary,
    opacity: 0.9,
  },
  allowLabel: {
    fontSize: 13,
    fontWeight: "800",
    color: colors.onSurface,
  },
  allowHint: {
    fontSize: 11,
    color: colors.onSurfaceSecondary,
    marginTop: 2,
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
});
