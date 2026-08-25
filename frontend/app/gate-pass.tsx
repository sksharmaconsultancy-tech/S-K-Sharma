/**
 * Iter 730 — GATE PASS module (user request).
 * Personal gate pass = OUT→IN punch pair inserted → duty hours auto-deduct.
 * Official gate pass = record only (no deduction).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Platform, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect } from "expo-router";
import { api } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

type GP = { gate_pass_id: string; user_id: string; employee_name?: string; date: string; out_time: string; in_time: string; minutes: number; pass_type: string; reason?: string; deducted?: boolean };
type Emp = { user_id: string; name: string; employee_code?: string };

const ym = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

export default function GatePassScreen() {
  const { user, loading: authLoading } = useAuth();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [month, setMonth] = useState(ym());
  const [items, setItems] = useState<GP[]>([]);
  const [emps, setEmps] = useState<Emp[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  // form
  const [q, setQ] = useState("");
  const [selEmp, setSelEmp] = useState<Emp | null>(null);
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [outT, setOutT] = useState("");
  const [inT, setInT] = useState("");
  const [passType, setPassType] = useState<"personal" | "official">("personal");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const cid = user?.role === "company_admin" ? user.company_id : companyId;

  const load = useCallback(async () => {
    if (!cid) return;
    setLoading(true);
    try {
      const [r, el] = await Promise.all([
        api<{ gate_passes: GP[] }>(`/admin/gate-pass?company_id=${cid}&month=${month}`),
        api<{ employees: any[] }>(`/admin/employees?company_id=${cid}`),
      ]);
      setItems(r.gate_passes || []);
      setEmps((el.employees || []).map((e) => ({ user_id: e.user_id, name: e.name, employee_code: e.employee_code })));
    } catch (e: any) { setMsg(e?.message || "Load failed"); }
    finally { setLoading(false); }
  }, [cid, month]);
  useEffect(() => { load(); }, [load]);

  const matches = useMemo(() => {
    const n = q.trim().toLowerCase();
    if (!n) return [];
    return emps.filter((e) => `${e.name} ${e.employee_code || ""}`.toLowerCase().includes(n)).slice(0, 6);
  }, [q, emps]);

  const save = async () => {
    if (!selEmp || !date || !outT || !inT) { setMsg("Employee, date, OUT & IN time भरें"); return; }
    setSaving(true); setMsg(null);
    try {
      await api("/admin/gate-pass", { method: "POST", body: { company_id: cid, user_id: selEmp.user_id, date, out_time: outT, in_time: inT, pass_type: passType, reason } });
      setSelEmp(null); setQ(""); setOutT(""); setInT(""); setReason("");
      setMsg("Gate pass saved ✓" + (passType === "personal" ? " (duty hours auto-deduct होंगे)" : ""));
      await load();
    } catch (e: any) { setMsg(e?.message || "Save failed"); }
    finally { setSaving(false); }
  };

  const del = (g: GP) => {
    const proceed = async () => { try { await api(`/admin/gate-pass/${g.gate_pass_id}`, { method: "DELETE" }); await load(); } catch (e: any) { setMsg(e?.message || "Delete failed"); } };
    if (Platform.OS === "web") { if (window.confirm(`Delete gate pass of ${g.employee_name}?`)) proceed(); }
    else Alert.alert("Delete", `Delete gate pass of ${g.employee_name}?`, [{ text: "Cancel" }, { text: "Delete", style: "destructive", onPress: proceed }]);
  };

  if (authLoading) return <View style={st.center}><ActivityIndicator /></View>;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role)) return <Redirect href="/" />;

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: 12 }}>
        <Text style={st.h1}>🚪 Gate Pass</Text>
        {user.role !== "company_admin" && <CompanyPicker value={companyId} onChange={setCompanyId} />}
        <View style={st.row}>
          <TextInput style={[st.input, { width: 110 }]} value={month} onChangeText={setMonth} placeholder="YYYY-MM" placeholderTextColor={colors.onSurfaceTertiary} />
          <Pressable style={st.btn} onPress={load}><Text style={st.btnTxt}>Load</Text></Pressable>
        </View>

        <View style={st.card}>
          <Text style={st.h2}>नया Gate Pass</Text>
          <TextInput style={st.input} value={selEmp ? `${selEmp.name} (${selEmp.employee_code || ""})` : q}
            onChangeText={(t) => { setSelEmp(null); setQ(t); }} placeholder="Employee खोजें (name/code)" placeholderTextColor={colors.onSurfaceTertiary} testID="gp-emp-search" />
          {!selEmp && matches.map((e) => (
            <Pressable key={e.user_id} style={st.opt} onPress={() => { setSelEmp(e); setQ(""); }}>
              <Text style={st.optTxt}>{e.name} · {e.employee_code}</Text>
            </Pressable>
          ))}
          <View style={st.row}>
            <TextInput style={[st.input, { flex: 1 }]} value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" placeholderTextColor={colors.onSurfaceTertiary} />
            <TextInput style={[st.input, { width: 84 }]} value={outT} onChangeText={setOutT} placeholder="OUT 14:00" placeholderTextColor={colors.onSurfaceTertiary} testID="gp-out" />
            <TextInput style={[st.input, { width: 84 }]} value={inT} onChangeText={setInT} placeholder="IN 15:30" placeholderTextColor={colors.onSurfaceTertiary} testID="gp-in" />
          </View>
          <View style={st.row}>
            {(["personal", "official"] as const).map((t) => (
              <Pressable key={t} style={[st.chip, passType === t && st.chipOn]} onPress={() => setPassType(t)}>
                <Text style={[st.chipTxt, passType === t && st.chipTxtOn]}>{t === "personal" ? "Personal (deduct)" : "Official (no deduct)"}</Text>
              </Pressable>
            ))}
          </View>
          <TextInput style={st.input} value={reason} onChangeText={setReason} placeholder="Reason" placeholderTextColor={colors.onSurfaceTertiary} />
          <Pressable style={[st.btn, saving && { opacity: 0.6 }]} onPress={save} disabled={saving} testID="gp-save">
            {saving ? <ActivityIndicator color="#fff" size="small" /> : <Text style={st.btnTxt}>Save Gate Pass</Text>}
          </Pressable>
          {msg && <Text style={st.msg}>{msg}</Text>}
        </View>

        {loading ? <ActivityIndicator /> : items.map((g) => (
          <View key={g.gate_pass_id} style={st.item}>
            <View style={{ flex: 1 }}>
              <Text style={st.itemName}>{g.employee_name}</Text>
              <Text style={st.itemSub}>{g.date} · OUT {g.out_time} → IN {g.in_time} · {Math.floor(g.minutes / 60)}h {g.minutes % 60}m · {g.pass_type}{g.reason ? ` · ${g.reason}` : ""}</Text>
            </View>
            {g.deducted && <Text style={st.badge}>deducted</Text>}
            <Pressable onPress={() => del(g)} hitSlop={8}><Ionicons name="trash-outline" size={18} color="#d33" /></Pressable>
          </View>
        ))}
        {!loading && items.length === 0 && <Text style={st.itemSub}>इस महीने कोई gate pass नहीं</Text>}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  h1: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  h2: { fontSize: 15, fontWeight: "700", color: colors.onSurface },
  row: { flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, gap: 8 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 8, color: colors.onSurface, backgroundColor: colors.surface },
  opt: { paddingVertical: 8, paddingHorizontal: 10, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md },
  optTxt: { color: colors.onSurface, fontSize: 13 },
  chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: colors.border },
  chipOn: { backgroundColor: colors.cta, borderColor: colors.cta },
  chipTxt: { fontSize: 12, color: colors.onSurface },
  chipTxtOn: { color: "#fff", fontWeight: "700" },
  btn: { backgroundColor: colors.cta, borderRadius: radius.md, paddingVertical: 10, paddingHorizontal: 16, alignItems: "center", minHeight: 44, justifyContent: "center" },
  btnTxt: { color: "#fff", fontWeight: "700" },
  msg: { color: colors.onSurfaceSecondary, fontSize: 12 },
  item: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: colors.surface, borderRadius: radius.md, padding: 12 },
  itemName: { fontWeight: "700", color: colors.onSurface },
  itemSub: { fontSize: 12, color: colors.onSurfaceSecondary },
  badge: { fontSize: 10, color: "#0a7", fontWeight: "700" },
});
