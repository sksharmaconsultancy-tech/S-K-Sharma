/**
 * Iter 731 — ASSET PROFILE (QR target). Full asset info + consolidated
 * lifecycle history. Admin-only (token required by API).
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, Redirect } from "expo-router";
import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

export default function AssetProfileScreen() {
  const { user, loading: authLoading } = useAuth();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [d, setD] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try { setD(await api<any>(`/admin/assets/${id}/profile`)); }
    catch (e: any) { setErr(e?.message || "Load failed"); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  if (authLoading) return <View style={st.center}><ActivityIndicator /></View>;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role)) return <Redirect href="/" />;
  if (err) return <View style={st.center}><Text style={st.note}>{err}</Text></View>;
  if (!d) return <View style={st.center}><ActivityIndicator /></View>;

  const a = d.asset;
  const L = (k: string, v: any) => v ? (
    <View style={st.line} key={k}><Text style={st.lineLbl}>{k}</Text><Text style={st.lineVal}>{String(v)}</Text></View>
  ) : null;

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: 12 }}>
        <Text style={st.h1}>{a.asset_code} · {a.name}</Text>
        <View style={st.card}>
          {L("Status", a.status)}
          {L("Category", a.category)}
          {L("Brand / Model", [a.brand, a.model].filter(Boolean).join(" / "))}
          {L("Serial No", a.serial_number)}
          {L("IMEI", a.imei)}
          {L("Assigned To", a.assigned_to_name)}
          {L("Branch / Location", [a.branch, a.location].filter(Boolean).join(" / "))}
          {L("Purchase", a.purchase_date ? `${a.purchase_date} · ₹${a.purchase_cost || 0}` : null)}
          {L("Vendor", a.vendor)}
          {L("Warranty End", a.warranty_end)}
          {L("AMC End", a.amc_end)}
          {L("Remarks", a.remarks)}
        </View>
        <View style={st.card}>
          <Text style={st.h2}>📜 पूरी History</Text>
          {(d.history || []).map((h: any) => (
            <View key={h.history_id} style={st.hist}>
              <Text style={st.histAction}>{h.action}</Text>
              <Text style={st.note}>{h.details || ""}</Text>
              <Text style={st.histMeta}>{(h.at || "").slice(0, 16).replace("T", " ")} · {h.by}</Text>
            </View>
          ))}
          {(d.history || []).length === 0 && <Text style={st.note}>कोई history नहीं</Text>}
        </View>
        {(d.repairs || []).length > 0 && (
          <View style={st.card}>
            <Text style={st.h2}>🔧 Service History</Text>
            {d.repairs.map((r: any) => (
              <Text key={r.repair_id} style={st.note}>{r.complaint_date} · {r.complaint_details} · ₹{r.repair_cost || 0} · {r.status}</Text>
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  h1: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  h2: { fontSize: 15, fontWeight: "700", color: colors.onSurface },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, gap: 6 },
  note: { fontSize: 12, color: colors.onSurfaceSecondary },
  line: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
  lineLbl: { color: colors.onSurfaceSecondary, fontSize: 13 },
  lineVal: { color: colors.onSurface, fontSize: 13, fontWeight: "600", flexShrink: 1, textAlign: "right" },
  hist: { borderLeftWidth: 2, borderColor: colors.cta, paddingLeft: 10, paddingVertical: 4 },
  histAction: { fontWeight: "700", color: colors.onSurface, fontSize: 13 },
  histMeta: { fontSize: 10, color: colors.onSurfaceTertiary, marginTop: 2 },
});
