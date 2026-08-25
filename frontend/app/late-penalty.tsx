/**
 * Iter 730 — LATE PENALTY AUTO (user request).
 * Config (free lates + N lates = ½ day) → monthly report → one-tap apply
 * into the draft compliance salary run's Other Deduction.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Redirect } from "expo-router";
import { api } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

type Row = { user_id: string; employee_code?: string; name?: string; late_days: number; chargeable: number; penalty_days: number; daily_rate: number; penalty_amount: number };

const ym = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

export default function LatePenaltyScreen() {
  const { user, loading: authLoading } = useAuth();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [month, setMonth] = useState(ym());
  const [freeLates, setFreeLates] = useState("3");
  const [perHalf, setPerHalf] = useState("3");
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const cid = user?.role === "company_admin" ? user.company_id : companyId;

  const loadCfg = useCallback(async () => {
    if (!cid) return;
    try {
      const r = await api<{ config: any }>(`/admin/late-penalty/config?company_id=${cid}`);
      setFreeLates(String(r.config.free_lates)); setPerHalf(String(r.config.lates_per_half_day));
    } catch { /* defaults */ }
  }, [cid]);
  useEffect(() => { loadCfg(); }, [loadCfg]);

  const saveCfgAndLoad = async () => {
    if (!cid) { setMsg("पहले firm चुनें"); return; }
    setLoading(true); setMsg(null);
    try {
      await api("/admin/late-penalty/config", { method: "POST", body: { company_id: cid, enabled: true, free_lates: Number(freeLates) || 0, lates_per_half_day: Number(perHalf) || 3 } });
      const r = await api<{ rows: Row[]; total_penalty: number }>(`/admin/late-penalty/report?company_id=${cid}&month=${month}`);
      setRows(r.rows || []); setTotal(r.total_penalty || 0);
      if (!(r.rows || []).length) setMsg("इस महीने कोई late mark नहीं मिला");
    } catch (e: any) { setMsg(e?.message || "Load failed"); }
    finally { setLoading(false); }
  };

  const apply = async () => {
    if (!cid) return;
    setApplying(true); setMsg(null);
    try {
      const r = await api<{ applied: number; note?: string }>("/admin/late-penalty/apply", { method: "POST", body: { company_id: cid, month } });
      setMsg(`✓ ${r.applied} employees पर penalty लगी। ${r.note || ""}`);
    } catch (e: any) { setMsg(e?.message || "Apply failed"); }
    finally { setApplying(false); }
  };

  if (authLoading) return <View style={st.center}><ActivityIndicator /></View>;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role)) return <Redirect href="/" />;

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: 12 }}>
        <Text style={st.h1}>⏰ Late Penalty (Auto)</Text>
        {user.role !== "company_admin" && <CompanyPicker value={companyId} onChange={setCompanyId} />}
        <View style={st.card}>
          <Text style={st.lbl}>Rule: महीने में <Text style={st.b}>{freeLates}</Text> late FREE, उसके बाद हर <Text style={st.b}>{perHalf}</Text> late = आधे दिन की salary कटौती</Text>
          <View style={st.row}>
            <TextInput style={[st.input, { width: 100 }]} value={month} onChangeText={setMonth} placeholder="YYYY-MM" placeholderTextColor={colors.onSurfaceTertiary} />
            <TextInput style={[st.input, { width: 70 }]} value={freeLates} onChangeText={setFreeLates} keyboardType="numeric" placeholder="Free" placeholderTextColor={colors.onSurfaceTertiary} />
            <TextInput style={[st.input, { width: 70 }]} value={perHalf} onChangeText={setPerHalf} keyboardType="numeric" placeholder="Per ½" placeholderTextColor={colors.onSurfaceTertiary} />
            <Pressable style={st.btn} onPress={saveCfgAndLoad} testID="lp-load">
              {loading ? <ActivityIndicator color="#fff" size="small" /> : <Text style={st.btnTxt}>Report</Text>}
            </Pressable>
          </View>
        </View>
        {rows.length > 0 && (
          <View style={st.card}>
            <View style={st.tr}>
              {["Name", "Late", "Charge", "½Days", "Amount"].map((h, i) => (
                <Text key={h} style={[st.th, i === 0 && { flex: 2, textAlign: "left" }]}>{h}</Text>
              ))}
            </View>
            {rows.map((r) => (
              <View key={r.user_id} style={st.tr}>
                <Text style={[st.td, { flex: 2, textAlign: "left" }]}>{r.name} ({r.employee_code})</Text>
                <Text style={st.td}>{r.late_days}</Text>
                <Text style={st.td}>{r.chargeable}</Text>
                <Text style={st.td}>{r.penalty_days}</Text>
                <Text style={[st.td, { fontWeight: "700" }]}>{r.penalty_amount}</Text>
              </View>
            ))}
            <Text style={[st.lbl, { fontWeight: "800" }]}>कुल Penalty: ₹{total}</Text>
            <Pressable style={[st.btn, { backgroundColor: "#b3261e" }, applying && { opacity: 0.6 }]} onPress={apply} disabled={applying} testID="lp-apply">
              {applying ? <ActivityIndicator color="#fff" size="small" /> : <Text style={st.btnTxt}>Salary में Apply करें (Other Deduction)</Text>}
            </Pressable>
            <Text style={st.note}>Apply के बाद Compliance Salary run को Reprocess (With EXISTING Data) करें — net salary refresh हो जाएगी।</Text>
          </View>
        )}
        {msg && <Text style={st.note}>{msg}</Text>}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  h1: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  row: { flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, gap: 10 },
  lbl: { color: colors.onSurfaceSecondary, fontSize: 13 },
  b: { fontWeight: "800", color: colors.onSurface },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 8, color: colors.onSurface },
  btn: { backgroundColor: colors.cta, borderRadius: radius.md, paddingVertical: 10, paddingHorizontal: 16, alignItems: "center", minHeight: 44, justifyContent: "center" },
  btnTxt: { color: "#fff", fontWeight: "700" },
  tr: { flexDirection: "row", paddingVertical: 6, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
  th: { flex: 1, fontSize: 11, fontWeight: "800", color: colors.onSurfaceSecondary, textAlign: "center" },
  td: { flex: 1, fontSize: 12, color: colors.onSurface, textAlign: "center" },
  note: { fontSize: 12, color: colors.onSurfaceSecondary },
});
