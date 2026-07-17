/**
 * Iter 104 — Attendance Policy Variant picker (Policy 1 / Policy 2) shown
 * inside Firm Master, so a NEW or EXISTING firm (esp. Textile) can switch
 * variants without opening the full Attendance Policy screen.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Platform, Alert } from "react-native";

import { api } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

const OPTIONS = [
  { key: "policy_1", label: "Policy 1", desc: "Standard OT — full day + hours beyond duty go to OT" },
  { key: "policy_2", label: "Policy 2", desc: "Textile rule — below 8 hrs = Half Day, rest logic to OT" },
];

export default function PolicyVariantPicker({ companyId, onVariantChange }: { companyId: string | null; onVariantChange?: (v: string | null) => void }) {
  const [variant, setVariant] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    api<any>(`/attendance/policy?company_id=${encodeURIComponent(companyId)}`)
      .then((r) => {
        const v = (r.policy || r)?.policy_variant || "policy_1";
        setVariant(v);
        onVariantChange?.(v);
      })
      .catch(() => { setVariant("policy_1"); onVariantChange?.("policy_1"); })
      .finally(() => setLoading(false));
  }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = async (key: string) => {
    if (!companyId || saving) return;
    const prev = variant;
    setVariant(key);
    onVariantChange?.(key);
    setSaving(true);
    try {
      await api(`/attendance/policy?company_id=${encodeURIComponent(companyId)}`, {
        method: "PATCH", body: { policy_variant: key },
      });
    } catch (e: any) {
      setVariant(prev);
      onVariantChange?.(prev);
      const msg = e?.message || "Failed to save policy variant";
      if (Platform.OS === "web") globalThis.alert(msg); else Alert.alert("Policy", msg);
    } finally { setSaving(false); }
  };

  if (!companyId) return <Text style={styles.hint}>Select a firm first.</Text>;
  if (loading) return <ActivityIndicator size="small" color={colors.brandPrimary} />;

  return (
    <View>
      <Text style={styles.hint}>
        Attendance calculation variant for this firm (used by Textile policies).
      </Text>
      <View style={{ flexDirection: "row", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        {OPTIONS.map((o) => {
          const on = variant === o.key;
          return (
            <Pressable key={o.key} onPress={() => pick(o.key)}
              style={[styles.opt, on && styles.optOn]} testID={`fm-variant-${o.key}`}>
              <Text style={[styles.optTitle, on && { color: "#fff" }]}>{o.label}</Text>
              <Text style={[styles.optDesc, on && { color: "rgba(255,255,255,0.85)" }]}>{o.desc}</Text>
            </Pressable>
          );
        })}
        {saving ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  hint: { fontSize: 11.5, color: colors.onSurfaceTertiary },
  opt: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 10, maxWidth: 260, backgroundColor: colors.surface,
  },
  optOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  optTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  optDesc: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 2 },
});
