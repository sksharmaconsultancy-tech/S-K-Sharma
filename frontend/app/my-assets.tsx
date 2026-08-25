/**
 * Iter 731 — MY ASSETS (Employee PWA). View assigned assets, acknowledge,
 * report issue / request repair / request return. Read-only master info.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Redirect } from "expo-router";
import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

export default function MyAssetsScreen() {
  const { user, loading: authLoading } = useAuth();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<{ id: string; type: string } | null>(null);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try { const r = await api<{ assets: any[] }>("/my/assets"); setItems(r.assets || []); }
    catch (e: any) { setMsg(e?.message || "Load failed"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const ack = async (id: string) => {
    try { await api(`/my/assets/${id}/ack`, { method: "POST" }); setMsg("Acknowledged ✓"); await load(); }
    catch (e: any) { setMsg(e?.message || "failed"); }
  };
  const sendReport = async () => {
    if (!report) return;
    try {
      await api(`/my/assets/${report.id}/report`, { method: "POST", body: { type: report.type, note } });
      setMsg("Request भेज दी गई ✓"); setReport(null); setNote("");
    } catch (e: any) { setMsg(e?.message || "failed"); }
  };

  if (authLoading) return <View style={st.center}><ActivityIndicator /></View>;
  if (!user) return <Redirect href="/" />;

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: 12 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}>
        <Text style={st.h1}>💼 My Assets</Text>
        {items.map((asg) => {
          const a = asg.asset || {};
          return (
            <View key={asg.assignment_id} style={st.card}>
              <Text style={st.name}>{a.name} · {a.asset_code}</Text>
              <Text style={st.sub}>{a.category}{a.brand ? ` · ${a.brand} ${a.model || ""}` : ""}{a.serial_number ? ` · SN ${a.serial_number}` : ""}</Text>
              <Text style={st.sub}>Issue: {asg.assigned_date} · Condition: {asg.condition_at_issue}{asg.accessories ? ` · ${asg.accessories}` : ""}</Text>
              {a.warranty_end && <Text style={st.sub}>Warranty till {a.warranty_end}</Text>}
              {asg.location && <Text style={st.sub}>Location: {asg.location}</Text>}
              <View style={st.row}>
                {!asg.acknowledged && (
                  <Pressable style={st.ackBtn} onPress={() => ack(asg.assignment_id)} testID="ma-ack">
                    <Text style={st.ackTxt}>✓ Acknowledge</Text>
                  </Pressable>
                )}
                {asg.acknowledged && <Text style={[st.sub, { color: "#0a7a4f", fontWeight: "700" }]}>✓ Acknowledged</Text>}
                {[["issue", "Report Issue"], ["repair", "Request Repair"], ["return", "Request Return"]].map(([t, l]) => (
                  <Pressable key={t} style={st.miniBtn} onPress={() => { setReport({ id: asg.assignment_id, type: t }); setNote(""); }}>
                    <Text style={st.miniTxt}>{l}</Text>
                  </Pressable>
                ))}
              </View>
              {report?.id === asg.assignment_id && (
                <View style={{ gap: 6 }}>
                  <TextInput style={st.input} value={note} onChangeText={setNote}
                    placeholder={`${report.type === "issue" ? "Issue" : report.type === "repair" ? "Repair" : "Return"} details लिखें…`}
                    placeholderTextColor={colors.onSurfaceTertiary} multiline testID="ma-note" />
                  <View style={st.row}>
                    <Pressable style={st.ackBtn} onPress={sendReport} testID="ma-send"><Text style={st.ackTxt}>भेजें</Text></Pressable>
                    <Pressable style={st.miniBtn} onPress={() => setReport(null)}><Text style={st.miniTxt}>Cancel</Text></Pressable>
                  </View>
                </View>
              )}
            </View>
          );
        })}
        {!loading && items.length === 0 && <Text style={st.sub}>आपको कोई asset issue नहीं हुआ है</Text>}
        {msg && <Text style={st.sub}>{msg}</Text>}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  h1: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, gap: 6 },
  name: { fontWeight: "800", color: colors.onSurface, fontSize: 15 },
  sub: { fontSize: 12, color: colors.onSurfaceSecondary },
  row: { flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 6 },
  ackBtn: { backgroundColor: colors.cta, borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 9, minHeight: 40, justifyContent: "center" },
  ackTxt: { color: "#fff", fontWeight: "700", fontSize: 12 },
  miniBtn: { paddingHorizontal: 10, paddingVertical: 7, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  miniTxt: { fontSize: 11, color: colors.onSurface, fontWeight: "600" },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: 10, color: colors.onSurface, minHeight: 60, textAlignVertical: "top" },
});
