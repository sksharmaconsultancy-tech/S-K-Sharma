/**
 * Iter 733 — BRANCH P&L + STATE COMPLIANCE (user request).
 * Tabs: Budget/P&L | Approvals | Movements | PF-ESIC | State Rules.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Redirect } from "expo-router";
import { api, apiBinary } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

const TABS = ["Budget/P&L", "Approvals", "Movements", "PF-ESIC", "State Rules"] as const;
const ym = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

export default function BranchComplianceScreen() {
  const { user, loading: authLoading } = useAuth();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Budget/P&L");
  const [month, setMonth] = useState(ym());
  const [rows, setRows] = useState<any[]>([]);
  const [extra, setExtra] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [budBranch, setBudBranch] = useState("");
  const [budAmt, setBudAmt] = useState("");
  const [states, setStates] = useState<any[]>([]);
  const cid = user?.role === "company_admin" ? user.company_id : companyId;

  const endpointFor = (t: string) =>
    t === "Budget/P&L" ? `/admin/branch-extras/pnl?company_id=${cid}&month=${month}` :
    t === "Approvals" ? `/admin/branch-extras/pending-approvals?company_id=${cid}` :
    t === "Movements" ? `/admin/branch-extras/movements?company_id=${cid}&month=${month}` :
    t === "PF-ESIC" ? `/admin/branch-extras/pf-esic-split?company_id=${cid}&month=${month}` : "";

  const load = useCallback(async () => {
    if (!cid) return;
    setLoading(true); setMsg(null);
    try {
      if (tab === "State Rules") {
        const r = await api<{ states: any[] }>("/admin/branch-extras/states");
        setStates(r.states || []); setRows([]);
      } else {
        const r = await api<any>(endpointFor(tab));
        setRows(r.rows || r.pending || []); setExtra(r.totals || null);
        if (r.run_found === false) setMsg(`⚠ ${month} की कोई salary run नहीं मिली — पहले salary process करें`);
      }
    } catch (e: any) { setMsg(e?.message || "Load failed"); }
    finally { setLoading(false); }
  }, [cid, tab, month]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const saveBudget = async () => {
    try {
      await api("/admin/branch-extras/budget", { method: "POST", body: { company_id: cid, branch: budBranch, month, budget: Number(budAmt) || 0 } });
      setMsg("Budget saved ✓"); setBudBranch(""); setBudAmt(""); await load();
    } catch (e: any) { setMsg(e?.message || "failed"); }
  };

  const dl = async (fmt: string) => {
    const base = tab === "Budget/P&L" ? "pnl" : tab === "Movements" ? "movements" : tab === "PF-ESIC" ? "pf-esic-split" : "state-report";
    try {
      const res = await apiBinary(`/admin/branch-extras/${base}?company_id=${cid}&month=${month}&fmt=${fmt}`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a"); a.href = res.webBlobUrl; a.download = `${base}_${month}.${fmt === "pdf" ? "pdf" : "xlsx"}`; a.click();
      }
    } catch (e: any) { setMsg(e?.message || "Export failed"); }
  };

  const loadStateReport = async () => {
    setLoading(true);
    try {
      const r = await api<any>(`/admin/branch-extras/state-report?company_id=${cid}&month=${month}`);
      setRows(r.rows || []); setExtra(r.totals || null);
      if (r.note) setMsg(r.note);
    } catch (e: any) { setMsg(e?.message || "failed"); }
    finally { setLoading(false); }
  };

  if (authLoading) return <View style={st.center}><ActivityIndicator /></View>;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role)) return <Redirect href="/" />;

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: 12 }}>
        <Text style={st.h1}>🏢 Branch P&L + State Compliance</Text>
        {user.role !== "company_admin" && <CompanyPicker value={companyId} onChange={setCompanyId} />}
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View style={st.row}>
            {TABS.map((t) => (
              <Pressable key={t} style={[st.chip, tab === t && st.chipOn]} onPress={() => { setTab(t); setRows([]); }} testID={`bc-tab-${t}`}>
                <Text style={[st.chipTxt, tab === t && st.chipTxtOn]}>{t}</Text>
              </Pressable>
            ))}
          </View>
        </ScrollView>
        <View style={st.row}>
          <TextInput style={[st.input, { width: 100 }]} value={month} onChangeText={setMonth} placeholder="YYYY-MM" placeholderTextColor={colors.onSurfaceTertiary} />
          <Pressable style={st.btn} onPress={load}><Text style={st.btnTxt}>Load</Text></Pressable>
          {tab !== "Approvals" && tab !== "State Rules" && (<>
            <Pressable style={st.miniBtn} onPress={() => dl("xlsx")}><Text style={st.miniTxt}>Excel</Text></Pressable>
            <Pressable style={st.miniBtn} onPress={() => dl("pdf")}><Text style={st.miniTxt}>PDF</Text></Pressable>
          </>)}
        </View>

        {tab === "Budget/P&L" && (
          <View style={st.card}>
            <Text style={st.h2}>Branch Budget set करें ({month})</Text>
            <View style={st.row}>
              <TextInput style={[st.input, { flex: 1 }]} value={budBranch} onChangeText={setBudBranch} placeholder="Branch name" placeholderTextColor={colors.onSurfaceTertiary} />
              <TextInput style={[st.input, { width: 110 }]} value={budAmt} onChangeText={setBudAmt} placeholder="Budget ₹" keyboardType="numeric" placeholderTextColor={colors.onSurfaceTertiary} />
              <Pressable style={st.btn} onPress={saveBudget} testID="bc-budget-save"><Text style={st.btnTxt}>Save</Text></Pressable>
            </View>
          </View>
        )}

        {tab === "State Rules" && (
          <View style={{ gap: 8 }}>
            <Pressable style={st.btn} onPress={loadStateReport} testID="bc-state-report">
              <Text style={st.btnTxt}>📊 {month} की State Statutory Report (PT/LWF/Min Wage)</Text>
            </Pressable>
            {states.map((s) => (
              <View key={s.state} style={st.item}>
                <View style={{ flex: 1 }}>
                  <Text style={st.itemName}>{s.state}</Text>
                  <Text style={st.itemSub}>
                    PT: {(s.pt_slabs || []).length ? (s.pt_slabs || []).map((x: any) => `${x[0]}-${x[1] > 9999999 ? "∞" : x[1]}: ₹${x[2]}`).join(" · ") : "लागू नहीं"}
                  </Text>
                  <Text style={st.itemSub}>LWF: EE ₹{s.lwf_employee} / ER ₹{s.lwf_employer} ({s.lwf_frequency}) · Min Wage (daily): US ₹{s.min_wage_daily?.unskilled} · SS ₹{s.min_wage_daily?.semi_skilled} · SK ₹{s.min_wage_daily?.skilled}</Text>
                </View>
              </View>
            ))}
            <Text style={st.note}>Defaults approximate हैं — filing से पहले latest notification verify करें। Branch Master में हर branch का State set करें (branch-state API)।</Text>
          </View>
        )}

        {loading ? <ActivityIndicator /> : rows.length > 0 && tab !== "State Rules" && (
          <View style={st.card}>
            {rows.map((r, i) => (
              <View key={i} style={st.item}>
                <View style={{ flex: 1 }}>
                  {tab === "Budget/P&L" && (<>
                    <Text style={st.itemName}>{r.branch} · {r.employees} emp</Text>
                    <Text style={st.itemSub}>Budget ₹{r.budget} · Actual ₹{r.actual_gross} · Variance <Text style={{ color: r.variance < 0 ? "#b3261e" : "#0a7a4f" }}>₹{r.variance}</Text>{r.utilization_pct != null ? ` · ${r.utilization_pct}%` : ""}</Text>
                  </>)}
                  {tab === "Approvals" && (<>
                    <Text style={st.itemName}>{r.type} · {r.employee}</Text>
                    <Text style={st.itemSub}>{r.branch} · {r.detail}</Text>
                  </>)}
                  {tab === "Movements" && (<>
                    <Text style={st.itemName}>{r.kind} · {r.employee}</Text>
                    <Text style={st.itemSub}>{r.from_branch} → {r.to_branch} · {r.effective}{r.till !== "-" ? ` till ${r.till}` : ""} · {r.status}</Text>
                  </>)}
                  {tab === "PF-ESIC" && (<>
                    <Text style={st.itemName}>{r.branch} · {r.count} emp</Text>
                    <Text style={st.itemSub}>PF: wages ₹{r.pf_wages} · EE ₹{r.pf_employee} · ER ₹{r.pf_employer} | ESIC: EE ₹{r.esic_employee} · ER ₹{r.esic_employer}</Text>
                  </>)}
                </View>
              </View>
            ))}
          </View>
        )}
        {tab === "State Rules" && rows.length > 0 && (
          <View style={st.card}>
            <Text style={st.h2}>State Statutory — {month}{extra ? ` · PT ₹${extra.pt} · LWF EE ₹${extra.lwf_employee} / ER ₹${extra.lwf_employer}` : ""}</Text>
            {rows.map((r, i) => (
              <View key={i} style={st.item}>
                <View style={{ flex: 1 }}>
                  <Text style={st.itemName}>{r.name} ({r.code}) · {r.state}</Text>
                  <Text style={st.itemSub}>Gross ₹{r.gross} · PT ₹{r.pt} · LWF ₹{r.lwf_ee}/{r.lwf_er} · Daily ₹{r.daily_rate} vs MW ₹{r.min_wage} {r.below_min_wage ? <Text style={{ color: "#b3261e", fontWeight: "800" }}>BELOW MIN WAGE ⚠</Text> : null}</Text>
                </View>
              </View>
            ))}
          </View>
        )}
        {!loading && rows.length === 0 && tab !== "State Rules" && <Text style={st.note}>कोई data नहीं</Text>}
        {msg && <Text style={st.note}>{msg}</Text>}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  h1: { fontSize: 19, fontWeight: "800", color: colors.onSurface },
  h2: { fontSize: 14, fontWeight: "700", color: colors.onSurface },
  row: { flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, gap: 8 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 8, color: colors.onSurface },
  chip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, borderWidth: 1, borderColor: colors.border },
  chipOn: { backgroundColor: colors.cta, borderColor: colors.cta },
  chipTxt: { fontSize: 12, color: colors.onSurface },
  chipTxtOn: { color: "#fff", fontWeight: "700" },
  btn: { backgroundColor: colors.cta, borderRadius: radius.md, paddingVertical: 10, paddingHorizontal: 14, minHeight: 42, justifyContent: "center", alignItems: "center" },
  btnTxt: { color: "#fff", fontWeight: "700", fontSize: 12 },
  miniBtn: { paddingHorizontal: 10, paddingVertical: 7, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  miniTxt: { fontSize: 11, color: colors.onSurface, fontWeight: "600" },
  item: { flexDirection: "row", gap: 8, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: 10 },
  itemName: { fontWeight: "700", color: colors.onSurface, fontSize: 13 },
  itemSub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  note: { fontSize: 12, color: colors.onSurfaceSecondary },
});
