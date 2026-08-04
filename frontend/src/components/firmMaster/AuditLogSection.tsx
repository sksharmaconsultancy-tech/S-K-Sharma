/**
 * Iter 484 — Firm Master → 15. Audit Log. Read-only trail of every save
 * (who, when, which sections) from db.firm_master_audit.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api/client";
import { colors } from "@/src/theme";
import { Card } from "./primitives";

const ACTION_LABELS: Record<string, string> = {
  master_saved: "Firm Master saved",
  contacts_saved: "Contact Details saved",
  config_exported: "Configuration exported",
  company_cloned: "Company cloned",
};

export default function AuditLogSection({ companyId }: { companyId: string }) {
  const [entries, setEntries] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ entries: any[] }>(`/admin/firm-master/${companyId}/audit`);
      setEntries(r.entries || []);
    } catch {} finally { setLoading(false); }
  }, [companyId]);
  useEffect(() => { void load(); }, [load]);

  return (
    <Card icon="time" title="Audit Log"
          subtitle="Every change to this firm's master — who, when and which sections">
      <Pressable onPress={load} style={st.refreshBtn}>
        <Ionicons name="refresh" size={13} color={colors.brandPrimary} />
        <Text style={st.refreshTxt}>Refresh</Text>
      </Pressable>
      {loading ? <Text style={st.mute}>Loading…</Text> : null}
      {!loading && entries.length === 0 ? (
        <Text style={st.mute}>No audit entries yet — they appear from the next save.</Text>
      ) : null}
      {entries.map((e) => (
        <View key={e.audit_id} style={st.row}>
          <View style={st.dot} />
          <View style={{ flex: 1 }}>
            <Text style={st.action}>
              {ACTION_LABELS[e.action] || e.action}
              {e.detail ? <Text style={st.mute}>  ·  {e.detail}</Text> : null}
            </Text>
            {(e.sections || []).length ? (
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 3 }}>
                {e.sections.map((s: string) => (
                  <View key={s} style={st.secChip}><Text style={st.secChipTxt}>{s}</Text></View>
                ))}
              </View>
            ) : null}
            <Text style={st.meta}>
              {String(e.at || "").replace("T", " ").slice(0, 19)} · {e.by_name || e.by} ({e.by_role})
            </Text>
          </View>
        </View>
      ))}
    </Card>
  );
}

const st = StyleSheet.create({
  refreshBtn: { flexDirection: "row", alignItems: "center", gap: 5, alignSelf: "flex-start" },
  refreshTxt: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },
  mute: { fontSize: 11.5, color: colors.onSurfaceTertiary },
  row: {
    flexDirection: "row", gap: 10, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  dot: {
    width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brandPrimary,
    marginTop: 5,
  },
  action: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  meta: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 3 },
  secChip: {
    backgroundColor: colors.brandTertiary, borderRadius: 999,
    paddingHorizontal: 8, paddingVertical: 2,
  },
  secChipTxt: { fontSize: 10, color: colors.brandPrimary, fontWeight: "700" },
});
