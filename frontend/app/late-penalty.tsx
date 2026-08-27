/**
 * Iter 730 — LATE PENALTY AUTO (user request).
 * Iter 745 — config ab Attendance Policy me hai (policy-based): yahan
 * sirf rule summary + monthly report + manual apply. Policy me enabled
 * hone par salary process ke time penalty AUTO lagti hai.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Redirect, useRouter } from "expo-router";
import { api } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

type Row = { user_id: string; employee_code?: string; name?: string; late_days: number; chargeable: number; penalty_days: number; daily_rate: number; penalty_amount: number };
type Cfg = { enabled?: boolean; grace_minutes?: number; free_lates?: number; mode?: string; every_n?: number; every_n_days?: number; slabs?: { from: number; to: number | null; days: number }[]; max_days?: number; source?: string };

const ym = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

const cfgSummary = (c: Cfg) => {
  const parts = [`${c.free_lates ?? 3} late FREE / month`];
  if (c.grace_minutes) parts.push(`extra grace ${c.grace_minutes} min`);
  if (c.mode === "slabs") {
    parts.push((c.slabs || []).map((s) => `${s.from}-${s.to ?? "∞"} → ${s.days} din`).join(" · ") || "slab set nahi");
  } else {
    parts.push(`har ${c.every_n ?? 3} late = ${c.every_n_days ?? 0.5} din cut`);
  }
  if (c.max_days) parts.push(`max ${c.max_days} din/month`);
  return parts.join(" · ");
};

export default function LatePenaltyScreen() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [month, setMonth] = useState(ym());
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const cid = user?.role === "company_admin" ? user.company_id : companyId;

  const loadCfg = useCallback(async () => {
    if (!cid) return;
    try {
      const r = await api<{ config: Cfg }>(`/admin/late-penalty/config?company_id=${cid}`);
      setCfg(r.config || null);
    } catch { setCfg(null); }
  }, [cid]);
  useEffect(() => { loadCfg(); }, [loadCfg]);

  const loadReport = async () => {
    if (!cid) { setMsg("पहले firm चुनें"); return; }
    setLoading(true); setMsg(null);
    try {
      const r = await api<{ config: Cfg; rows: Row[]; total_penalty: number }>(`/admin/late-penalty/report?company_id=${cid}&month=${month}`);
      if (r.config) setCfg(r.config);
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
        <Text style={st.h1}>⏰ Late Penalty</Text>
        {user.role !== "company_admin" && <CompanyPicker value={companyId} onChange={setCompanyId} />}
        <View style={st.card}>
          {cfg ? (
            <>
              <Text style={st.lbl}>
                Rule: <Text style={st.b}>{cfgSummary(cfg)}</Text>
              </Text>
              <Text style={st.note}>
                {cfg.source === "policy"
                  ? (cfg.enabled
                    ? "✅ Attendance Policy me ENABLED — har salary process par penalty AUTO lagti hai (Other Deduction · Late Penalty)."
                    : "⚠️ Attendance Policy me DISABLED — auto-deduction OFF hai; neeche se manual apply kar sakte hain.")
                  : "ℹ️ Ye purana firm-level rule hai. Naya config Attendance Policy → Late Penalty section me set karein (wahan enable karte hi auto-apply bhi ho jayega)."}
              </Text>
              <Pressable onPress={() => router.push(cid ? `/attendance-policy?company_id=${cid}` : "/attendance-policy")} testID="lp-goto-policy">
                <Text style={[st.note, { color: colors.cta, fontWeight: "700" }]}>⚙️ Config badalne ke liye: Attendance Policy → Late Penalty →</Text>
              </Pressable>
            </>
          ) : (
            <Text style={st.lbl}>Firm chunte hi rule yahan dikhega.</Text>
          )}
          <View style={st.row}>
            <TextInput style={[st.input, { width: 100 }]} value={month} onChangeText={setMonth} placeholder="YYYY-MM" placeholderTextColor={colors.onSurfaceTertiary} />
            <Pressable style={st.btn} onPress={loadReport} testID="lp-load">
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
