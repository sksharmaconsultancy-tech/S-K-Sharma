/**
 * Iter 730 — F&F CALCULATOR (user request).
 * Single-employee Full & Final settlement: earned salary + gratuity +
 * leave encashment + bonus − advances/notice/other → net payable + PDF.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Redirect } from "expo-router";
import { api, apiBinary } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

type Emp = { user_id: string; name: string; employee_code?: string; exit_date?: string };

export default function FnfCalculatorScreen() {
  const { user, loading: authLoading } = useAuth();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [emps, setEmps] = useState<Emp[]>([]);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<Emp | null>(null);
  const [exitDate, setExitDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [leaveDays, setLeaveDays] = useState("0");
  const [bonus, setBonus] = useState("0");
  const [notice, setNotice] = useState("0");
  const [otherEarn, setOtherEarn] = useState("0");
  const [otherDed, setOtherDed] = useState("0");
  const [data, setData] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const cid = user?.role === "company_admin" ? user.company_id : companyId;

  const loadEmps = useCallback(async () => {
    if (!cid) return;
    try {
      const r = await api<{ employees: any[] }>(`/admin/employees?company_id=${cid}`);
      setEmps((r.employees || []).map((e) => ({ user_id: e.user_id, name: e.name, employee_code: e.employee_code, exit_date: e.exit_date })));
    } catch { /* ignore */ }
  }, [cid]);
  useEffect(() => { loadEmps(); }, [loadEmps]);

  const matches = useMemo(() => {
    const n = q.trim().toLowerCase();
    if (!n) return [];
    return emps.filter((e) => `${e.name} ${e.employee_code || ""}`.toLowerCase().includes(n)).slice(0, 6);
  }, [q, emps]);

  const qs = () => `user_id=${sel!.user_id}&exit_date=${exitDate}` +
    `&leave_encash_days=${Number(leaveDays) || 0}&bonus_amount=${Number(bonus) || 0}` +
    `&notice_recovery=${Number(notice) || 0}&other_earning=${Number(otherEarn) || 0}` +
    `&other_deduction=${Number(otherDed) || 0}`;

  const compute = async () => {
    if (!sel) { setMsg("पहले employee चुनें"); return; }
    setBusy(true); setMsg(null);
    try { setData(await api<any>(`/admin/fnf/calc?${qs()}`)); }
    catch (e: any) { setMsg(e?.message || "Compute failed"); }
    finally { setBusy(false); }
  };

  const downloadPdf = async () => {
    if (!sel) return;
    setPdfBusy(true);
    try {
      const res = await apiBinary(`/admin/fnf/calc?${qs()}&fmt=pdf`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl; a.download = `FnF_${sel.employee_code || sel.user_id}.pdf`; a.click();
      }
    } catch (e: any) { setMsg(e?.message || "PDF failed"); }
    finally { setPdfBusy(false); }
  };

  if (authLoading) return <View style={st.center}><ActivityIndicator /></View>;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role)) return <Redirect href="/" />;

  const L = (label: string, val: number, strong?: boolean, neg?: boolean) => (
    <View style={st.line} key={label}>
      <Text style={[st.lineLbl, strong && st.strong]}>{label}</Text>
      <Text style={[st.lineVal, strong && st.strong, neg && { color: "#b3261e" }]}>₹{val}</Text>
    </View>
  );

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: 12 }}>
        <Text style={st.h1}>🧾 F&F Calculator</Text>
        {user.role !== "company_admin" && <CompanyPicker value={companyId} onChange={setCompanyId} />}
        <View style={st.card}>
          <TextInput style={st.input} value={sel ? `${sel.name} (${sel.employee_code || ""})` : q}
            onChangeText={(t) => { setSel(null); setData(null); setQ(t); }}
            placeholder="Employee खोजें (name/code)" placeholderTextColor={colors.onSurfaceTertiary} testID="fnf-emp-search" />
          {!sel && matches.map((e) => (
            <Pressable key={e.user_id} style={st.opt} onPress={() => { setSel(e); setQ(""); if (e.exit_date) setExitDate(String(e.exit_date).slice(0, 10)); }}>
              <Text style={st.optTxt}>{e.name} · {e.employee_code}{e.exit_date ? ` · exited ${e.exit_date}` : ""}</Text>
            </Pressable>
          ))}
          <View style={st.row}>
            <View style={st.f}><Text style={st.fl}>Exit Date</Text><TextInput style={st.input} value={exitDate} onChangeText={setExitDate} placeholder="YYYY-MM-DD" placeholderTextColor={colors.onSurfaceTertiary} /></View>
            <View style={st.f}><Text style={st.fl}>Leave Encash Days</Text><TextInput style={st.input} value={leaveDays} onChangeText={setLeaveDays} keyboardType="numeric" /></View>
          </View>
          <View style={st.row}>
            <View style={st.f}><Text style={st.fl}>Bonus / Ex-gratia ₹</Text><TextInput style={st.input} value={bonus} onChangeText={setBonus} keyboardType="numeric" /></View>
            <View style={st.f}><Text style={st.fl}>Notice Recovery ₹</Text><TextInput style={st.input} value={notice} onChangeText={setNotice} keyboardType="numeric" /></View>
          </View>
          <View style={st.row}>
            <View style={st.f}><Text style={st.fl}>Other Earning ₹</Text><TextInput style={st.input} value={otherEarn} onChangeText={setOtherEarn} keyboardType="numeric" /></View>
            <View style={st.f}><Text style={st.fl}>Other Deduction ₹</Text><TextInput style={st.input} value={otherDed} onChangeText={setOtherDed} keyboardType="numeric" /></View>
          </View>
          <Pressable style={[st.btn, busy && { opacity: 0.6 }]} onPress={compute} disabled={busy} testID="fnf-compute">
            {busy ? <ActivityIndicator color="#fff" size="small" /> : <Text style={st.btnTxt}>⚡ Calculate F&F</Text>}
          </Pressable>
          {msg && <Text style={st.note}>{msg}</Text>}
        </View>

        {data && (
          <View style={st.card}>
            <Text style={st.h2}>{data.employee?.name} · Service {data.service_years} yrs · {data.days_worked} days worked ({data.exit_date?.slice(0, 7)})</Text>
            {L("Earned Salary", data.earned_salary)}
            {L(`Gratuity${data.gratuity_eligible ? "" : " (not eligible)"}`, data.gratuity)}
            {L("Leave Encashment", data.leave_encashment)}
            {L("Bonus / Ex-gratia", data.bonus_amount)}
            {L("Other Earnings", data.other_earning)}
            {L("Total Earnings (A)", data.total_earnings, true)}
            {L("Advance Recovery", data.advance_recovery, false, true)}
            {L("Notice Recovery", data.notice_recovery, false, true)}
            {L("Other Deductions", data.other_deduction, false, true)}
            {L("Total Deductions (B)", data.total_deductions, true, true)}
            <View style={[st.line, st.netLine]}>
              <Text style={st.netLbl}>NET PAYABLE</Text>
              <Text style={st.netVal}>₹{data.net_payable}</Text>
            </View>
            <Pressable style={[st.btn, { backgroundColor: "#0a7a4f" }, pdfBusy && { opacity: 0.6 }]} onPress={downloadPdf} disabled={pdfBusy} testID="fnf-pdf">
              {pdfBusy ? <ActivityIndicator color="#fff" size="small" /> : <Text style={st.btnTxt}>📄 Settlement Sheet PDF</Text>}
            </Pressable>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  h1: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  h2: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  row: { flexDirection: "row", gap: 8 },
  f: { flex: 1, gap: 4 },
  fl: { fontSize: 11, color: colors.onSurfaceSecondary, fontWeight: "600" },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, gap: 10 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 8, color: colors.onSurface },
  opt: { paddingVertical: 8, paddingHorizontal: 10, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md },
  optTxt: { color: colors.onSurface, fontSize: 13 },
  btn: { backgroundColor: colors.cta, borderRadius: radius.md, paddingVertical: 12, alignItems: "center", minHeight: 44, justifyContent: "center" },
  btnTxt: { color: "#fff", fontWeight: "700" },
  note: { fontSize: 12, color: colors.onSurfaceSecondary },
  line: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 5, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
  lineLbl: { color: colors.onSurfaceSecondary, fontSize: 13 },
  lineVal: { color: colors.onSurface, fontSize: 13 },
  strong: { fontWeight: "800", color: colors.onSurface },
  netLine: { borderBottomWidth: 0, marginTop: 4 },
  netLbl: { fontSize: 16, fontWeight: "900", color: colors.onSurface },
  netVal: { fontSize: 18, fontWeight: "900", color: "#0a7a4f" },
});
