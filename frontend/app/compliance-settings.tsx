/**
 * Iter 127f — STANDARD COMPLIANCE SETTINGS (global, all firms).
 *
 * One screen with the statutory PF / ESIC configuration that every firm's
 * Compliance Salary Process uses: rates, ceilings, wage-base floor and
 * whole-rupee rounding rules. Super Admin edits; Sub Admins can view.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import DateField from "@/src/components/DateField";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

type Cfg = Record<string, any>;

const NUM_FIELDS: { key: string; label: string; suffix: string; group: "pf" | "esic" | "base" }[] = [
  { key: "pf_percent_employee", label: "PF — Employee share", suffix: "%", group: "pf" },
  { key: "pf_percent_employer_epf", label: "PF — Employer EPF share", suffix: "%", group: "pf" },
  { key: "pf_percent_employer_eps", label: "PF — Employer EPS (Pension)", suffix: "%", group: "pf" },
  { key: "pf_admin_percent", label: "EPF Admin Charges (A/c 2)", suffix: "%", group: "pf" },
  { key: "pf_edli_percent", label: "EDLI Contribution (A/c 21)", suffix: "%", group: "pf" },
  { key: "pf_edli_admin_percent", label: "EDLI Admin Charges (A/c 22)", suffix: "%", group: "pf" },
  { key: "pf_wage_cap", label: "EPF wage ceiling", suffix: "₹", group: "pf" },
  { key: "esic_percent_employee", label: "ESIC — Employee share", suffix: "%", group: "esic" },
  { key: "esic_percent_employer", label: "ESIC — Employer share", suffix: "%", group: "esic" },
  { key: "esic_gross_threshold", label: "ESIC eligibility limit (Basic ≤)", suffix: "₹", group: "esic" },
  { key: "stat_wage_floor_pct", label: "Wage base floor (% of gross)", suffix: "%", group: "base" },
];

const ROUND_OPTS = ["nearest", "ceil", "floor", "none"] as const;
const ROUND_LABEL: Record<string, string> = {
  nearest: "Nearest ₹", ceil: "Round UP ₹", floor: "Round DOWN ₹", none: "Exact (paise)",
};

export default function ComplianceSettingsScreen() {
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";

  // Iter 127g — scope: "standard" (all firms) OR a specific firm whose
  // overrides are saved on its Firm Master.
  const [scope, setScope] = useState<string>("standard");
  const [companies, setCompanies] = useState<{ company_id: string; name: string }[]>([]);
  const [hasOverride, setHasOverride] = useState(false);

  const [form, setForm] = useState<Cfg>({});
  const [meta, setMeta] = useState<{ updated_at?: string; updated_by_name?: string }>({});
  // Iter 160 — effective date + change log (Standard scope only).
  const [effectiveFrom, setEffectiveFrom] = useState<string>(new Date().toISOString().slice(0, 10));
  const [log, setLog] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<any>("/companies");
        const list = (r?.companies || r || []).filter((c: any) => c.is_active !== false);
        setCompanies(list.map((c: any) => ({ company_id: c.company_id, name: c.name })));
      } catch { /* noop */ }
    })();
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setBanner(null);
    try {
      let settings: Cfg;
      if (scope === "standard") {
        const r = await api<any>(
          "/admin/compliance-settings",
        );
        settings = r.settings || {};
        setHasOverride(false);
        setMeta({ updated_at: r.updated_at, updated_by_name: r.updated_by_name });
        setLog(r.log || []);
        if (r.effective_from) setEffectiveFrom(r.effective_from);
      } else {
        const r = await api<{ effective: Cfg; has_override: boolean; overrides: Cfg }>(
          `/admin/compliance-settings/firm/${scope}`,
        );
        settings = r.effective || {};
        setHasOverride(!!r.has_override);
        setMeta({
          updated_at: r.overrides?.updated_at,
          updated_by_name: r.overrides?.updated_by_name,
        });
      }
      const f: Cfg = {};
      for (const { key } of NUM_FIELDS) f[key] = String(settings?.[key] ?? "");
      f.pf_rounding = settings?.pf_rounding || "nearest";
      f.esic_rounding = settings?.esic_rounding || "ceil";
      setForm(f);
    } catch (e: any) {
      setBanner({ kind: "err", msg: e?.message || "Failed to load settings" });
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    setBanner(null);
    try {
      const body: Cfg = { pf_rounding: form.pf_rounding, esic_rounding: form.esic_rounding };
      for (const { key, label } of NUM_FIELDS) {
        const v = Number(form[key]);
        if (!Number.isFinite(v) || v < 0) {
          setBanner({ kind: "err", msg: `${label} must be a valid number` });
          setSaving(false);
          return;
        }
        body[key] = v;
      }
      if (scope === "standard") {
        await api("/admin/compliance-settings", { method: "PUT", body: { ...body, effective_from: effectiveFrom } });
        await load();
        setBanner({ kind: "ok", msg: "Standard settings saved — applies to ALL firms from the next Salary Process / Re-calculate." });
      } else {
        await api(`/admin/compliance-settings/firm/${scope}`, { method: "PUT", body });
        const nm = companies.find((c) => c.company_id === scope)?.name || "firm";
        await load();
        setBanner({ kind: "ok", msg: `Saved for ${nm} only — this firm now uses its own settings instead of the Standard.` });
      }
    } catch (e: any) {
      setBanner({ kind: "err", msg: e?.message || "Save failed" });
    } finally {
      setSaving(false);
    }
  };

  const clearOverride = async () => {
    if (scope === "standard") return;
    setSaving(true);
    try {
      await api(`/admin/compliance-settings/firm/${scope}`, { method: "PUT", body: { clear: true } });
      await load();
      setBanner({ kind: "ok", msg: "Firm override removed — this firm follows the Standard settings again." });
    } catch (e: any) {
      setBanner({ kind: "err", msg: e?.message || "Failed to clear override" });
    } finally {
      setSaving(false);
    }
  };

  const Section = ({ title, icon, children }: any) => (
    <View style={styles.card}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <Ionicons name={icon} size={16} color={colors.brandPrimary} />
        <Text style={styles.cardTitle}>{title}</Text>
      </View>
      {children}
    </View>
  );

  const NumRow = ({ f }: { f: (typeof NUM_FIELDS)[number] }) => (
    <View style={styles.fieldRow}>
      <Text style={styles.fieldLbl}>{f.label}</Text>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
        <TextInput
          style={[styles.input, !isSuper && styles.inputLocked]}
          value={String(form[f.key] ?? "")}
          onChangeText={(v) => setForm((p) => ({ ...p, [f.key]: v.replace(/[^0-9.]/g, "") }))}
          keyboardType="numeric"
          editable={isSuper}
          testID={`cs-${f.key}`}
        />
        <Text style={styles.suffix}>{f.suffix}</Text>
      </View>
    </View>
  );

  const RoundPicker = ({ k, label }: { k: string; label: string }) => (
    <View style={styles.fieldRow}>
      <Text style={styles.fieldLbl}>{label}</Text>
      <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
        {ROUND_OPTS.map((o) => (
          <Pressable
            key={o}
            disabled={!isSuper}
            onPress={() => setForm((p) => ({ ...p, [k]: o }))}
            style={[styles.chip, form[k] === o && styles.chipActive]}
            testID={`cs-${k}-${o}`}
          >
            <Text style={[styles.chipTxt, form[k] === o && styles.chipTxtActive]}>
              {ROUND_LABEL[o]}
            </Text>
          </Pressable>
        ))}
      </View>
    </View>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title}>Standard Compliance Settings</Text>
        <Text style={styles.sub}>
          These statutory rules apply GLOBALLY to the Compliance Salary Process of{" "}
          <Text style={{ fontWeight: "800" }}>every firm</Text>. Re-calculate a month after
          changing them to apply the new rules.
          {meta.updated_at ? `  Last updated ${meta.updated_at.slice(0, 10)}${meta.updated_by_name ? ` by ${meta.updated_by_name}` : ""}.` : ""}
        </Text>
        {!isSuper ? (
          <View style={styles.roCard}>
            <Ionicons name="lock-closed" size={14} color="#92400E" />
            <Text style={styles.roTxt}>View only — the Super Admin manages these global settings.</Text>
          </View>
        ) : null}

        {/* Iter 127g — scope picker: Standard (all firms) vs a single firm */}
        <View style={styles.scopeRow}>
          <Pressable
            onPress={() => setScope("standard")}
            style={[styles.chip, scope === "standard" && styles.chipActive]}
            testID="cs-scope-standard"
          >
            <Text style={[styles.chipTxt, scope === "standard" && styles.chipTxtActive]}>
              Standard (All Firms)
            </Text>
          </Pressable>
          {companies.map((c) => (
            <Pressable
              key={c.company_id}
              onPress={() => setScope(c.company_id)}
              style={[styles.chip, scope === c.company_id && styles.chipActive]}
              testID={`cs-scope-${c.company_id}`}
            >
              <Text style={[styles.chipTxt, scope === c.company_id && styles.chipTxtActive]} numberOfLines={1}>
                {c.name}
              </Text>
            </Pressable>
          ))}
        </View>
        {scope !== "standard" ? (
          <View style={[styles.roCard, { backgroundColor: hasOverride ? "#EFF6FF" : "#F8FAFC", borderColor: hasOverride ? "#93C5FD" : colors.border }]}>
            <Ionicons name={hasOverride ? "business" : "link-outline"} size={14} color={hasOverride ? "#1D4ED8" : colors.onSurfaceSecondary} />
            <Text style={[styles.roTxt, { color: hasOverride ? "#1D4ED8" : colors.onSurfaceSecondary }]}>
              {hasOverride
                ? "This firm has its OWN saved settings (overriding the Standard). Both Compliance & Actual salary use them."
                : "This firm currently follows the Standard settings. Save below to give it firm-specific rules."}
            </Text>
          </View>
        ) : null}

        {banner ? (
          <View style={[styles.banner, banner.kind === "ok" ? styles.bannerOk : styles.bannerErr]}>
            <Text style={{ color: banner.kind === "ok" ? "#166534" : "#B91C1C", fontSize: 12, fontWeight: "600" }}>
              {banner.msg}
            </Text>
          </View>
        ) : null}

        {loading ? (
          <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
        ) : (
          <>
            <Section title="Provident Fund (PF)" icon="shield-checkmark-outline">
              {NUM_FIELDS.filter((f) => f.group === "pf").map((f) => <NumRow key={f.key} f={f} />)}
              {/* Iter 160 — employer TOTAL per EPF Act accounts */}
              <View style={[styles.fieldRow, { backgroundColor: "#F0F9FF", borderRadius: 8, paddingHorizontal: 8 }]}>
                <Text style={[styles.fieldLbl, { fontWeight: "700" }]}>Employer TOTAL (EPF + EPS + A/c 2 + A/c 21 + A/c 22)</Text>
                <Text style={{ fontWeight: "800", color: colors.brandPrimary, fontSize: 13 }}>
                  {(["pf_percent_employer_epf", "pf_percent_employer_eps", "pf_admin_percent", "pf_edli_percent", "pf_edli_admin_percent"]
                    .reduce((n, k) => n + (Number(form[k]) || 0), 0)).toFixed(2)}%
                </Text>
              </View>
              <RoundPicker k="pf_rounding" label="PF rounding" />
              <Text style={styles.hint}>
                PF wages = max(Basic, floor% of gross) capped at the ceiling — unless the
                employee&apos;s &quot;PF Basic Salary&quot; is filled in the Employee Master (then that
                amount is used).
              </Text>
            </Section>

            <Section title="ESIC" icon="medkit-outline">
              {NUM_FIELDS.filter((f) => f.group === "esic").map((f) => <NumRow key={f.key} f={f} />)}
              <RoundPicker k="esic_rounding" label="ESIC rounding" />
              <Text style={styles.hint}>
                ESIC is applied on BASIC salary — an employee is covered only when
                Basic ≤ the eligibility limit. Statutory practice rounds ESIC UP
                to the next rupee.
              </Text>
            </Section>

            <Section title="Wage Base" icon="calculator-outline">
              {NUM_FIELDS.filter((f) => f.group === "base").map((f) => <NumRow key={f.key} f={f} />)}
              <Text style={styles.hint}>
                PF & ESIC wage base = max(Basic, this % of Gross Earning) — new labour code rule.
              </Text>
            </Section>

            {scope === "standard" ? (
              <Section title="Effective Date & Change Log" icon="calendar-outline">
                <View style={styles.fieldRow}>
                  <Text style={styles.fieldLbl}>Effective from (policy applies to salary months on/after this date)</Text>
                  <DateField value={effectiveFrom} onChangeISO={(v) => v && setEffectiveFrom(v)} testID="cs-effective-from" />
                </View>
                {log.length === 0 ? (
                  <Text style={styles.hint}>No changes logged yet — every save is recorded here with its effective date.</Text>
                ) : (
                  log.map((l, i) => {
                    const s = l.settings || {};
                    return (
                      <View key={l.log_id || i} style={{ borderTopWidth: i ? 1 : 0, borderTopColor: colors.border, paddingVertical: 6 }}>
                        <Text style={{ fontSize: 12, fontWeight: "700", color: colors.onSurface }}>
                          Effective {l.effective_from}
                          <Text style={{ fontWeight: "400", color: colors.onSurfaceTertiary }}>
                            {"  ·  saved "}{(l.updated_at || "").slice(0, 10)} by {l.updated_by_name || "—"}
                          </Text>
                        </Text>
                        <Text style={{ fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 }}>
                          PF {s.pf_percent_employee}% / EPF {s.pf_percent_employer_epf}% / EPS {s.pf_percent_employer_eps}% ·
                          A/c2 {s.pf_admin_percent ?? 0.5}% · A/c21 {s.pf_edli_percent ?? 0.5}% · A/c22 {s.pf_edli_admin_percent ?? 0}% ·
                          Ceiling ₹{s.pf_wage_cap} · ESIC {s.esic_percent_employee}%/{s.esic_percent_employer}% (limit ₹{s.esic_gross_threshold}) ·
                          Floor {s.stat_wage_floor_pct}%
                        </Text>
                      </View>
                    );
                  })
                )}
              </Section>
            ) : null}

            {isSuper ? (
              <>
                <Pressable
                  style={[styles.saveBtn, saving && { opacity: 0.6 }]}
                  onPress={save}
                  disabled={saving}
                  testID="cs-save"
                >
                  {saving ? <ActivityIndicator size="small" color="#fff" /> : (
                    <>
                      <Ionicons name="save-outline" size={16} color="#fff" />
                      <Text style={styles.saveTxt}>
                        {scope === "standard"
                          ? "Save Standard Settings (All Firms)"
                          : `Save for ${companies.find((c) => c.company_id === scope)?.name || "this firm"} only`}
                      </Text>
                    </>
                  )}
                </Pressable>
                {scope !== "standard" && hasOverride ? (
                  <Pressable
                    style={[styles.saveBtn, { backgroundColor: "#DC2626", marginTop: 10 }, saving && { opacity: 0.6 }]}
                    onPress={clearOverride}
                    disabled={saving}
                    testID="cs-clear-override"
                  >
                    <Ionicons name="refresh-outline" size={16} color="#fff" />
                    <Text style={styles.saveTxt}>Remove Firm Override (use Standard)</Text>
                  </Pressable>
                ) : null}
              </>
            ) : null}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F4F7F7" },
  scroll: { padding: spacing.lg, paddingBottom: 80, maxWidth: 760, width: "100%", alignSelf: "center" },
  title: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 4, marginBottom: 14 },
  roCard: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#FFFBEB", borderWidth: 1, borderColor: "#FCD34D",
    borderRadius: radius.md, padding: 10, marginBottom: 12,
  },
  roTxt: { flex: 1, fontSize: 12, color: "#92400E" },
  scopeRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  banner: { padding: 10, borderRadius: radius.md, borderWidth: 1, marginBottom: 12 },
  bannerOk: { backgroundColor: "#DCFCE7", borderColor: "#86EFAC" },
  bannerErr: { backgroundColor: "#FEE2E2", borderColor: "#FCA5A5" },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.md, marginBottom: spacing.md,
  },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  fieldRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 7, gap: 12, flexWrap: "wrap",
  },
  fieldLbl: { fontSize: 13, color: colors.onSurface, flexShrink: 1 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, minWidth: 110,
    textAlign: "right", color: colors.onSurface, backgroundColor: "#fff",
  },
  inputLocked: { backgroundColor: "#F1F5F9", color: colors.onSurfaceTertiary },
  suffix: { fontSize: 12, color: colors.onSurfaceSecondary, width: 16 },
  chip: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border, backgroundColor: "#fff",
  },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtActive: { color: "#fff" },
  hint: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 8 },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingVertical: 13, marginTop: 4,
  },
  saveTxt: { color: "#fff", fontSize: 14, fontWeight: "800" },
});
