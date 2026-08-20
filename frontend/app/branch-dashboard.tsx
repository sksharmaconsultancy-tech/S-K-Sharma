/**
 * Iter 624 — BRANCH DASHBOARD + COST ALLOCATION (user spec §7-8, §13).
 * ONE consolidated payroll per employee; branch cost = salary ÷ payable
 * days × days worked per branch (Gross + Net + PF/ESIC liability shares).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";

const inr = (n: number) => `₹${Math.round(n || 0).toLocaleString("en-IN")}`;

export default function BranchDashboard() {
  const router = useRouter();
  const [companies, setCompanies] = useState<any[]>([]);
  const [cid, setCid] = useState("");
  const now = new Date();
  const [month, setMonth] = useState(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`);
  const [busy, setBusy] = useState(false);
  const [dash, setDash] = useState<any | null>(null);
  const [alloc, setAlloc] = useState<any | null>(null);
  const [showEmp, setShowEmp] = useState(false);

  useEffect(() => {
    api<{ companies: any[] }>("/companies?lite=1").then((r) => {
      setCompanies(r.companies || []);
      if (r.companies?.length) setCid((p) => p || r.companies[0].company_id);
    }).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!cid || !/^\d{4}-\d{2}$/.test(month)) return;
    setBusy(true);
    try {
      const [d, a] = await Promise.all([
        api(`/admin/branch-management/dashboard?company_id=${cid}&month=${month}`),
        api(`/admin/branch-management/allocation?company_id=${cid}&month=${month}`),
      ]);
      setDash(d);
      setAlloc(a);
    } catch { setDash(null); setAlloc(null); } finally { setBusy(false); }
  }, [cid, month]);
  useEffect(() => { load(); }, [load]);

  const cards = (dash?.cards || []).filter((c: any) =>
    c.home_employees || c.worked_days || c.gross_cost || c.branch_id);

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={8}>
          <Ionicons name="arrow-back" size={22} color="#0F172A" />
        </Pressable>
        <Text style={st.h1}>Branch Dashboard</Text>
        <TextInput style={st.month} value={month} onChangeText={setMonth}
          placeholder="YYYY-MM" testID="bd-month" />
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0 }} contentContainerStyle={{ paddingHorizontal: 12, gap: 6 }}>
        {companies.map((c) => (
          <Pressable key={c.company_id} onPress={() => setCid(c.company_id)}
            style={[st.chip, cid === c.company_id && st.chipOn]}>
            <Text style={[st.chipTxt, cid === c.company_id && st.chipTxtOn]}>{c.name}</Text>
          </Pressable>
        ))}
      </ScrollView>
      {busy ? <ActivityIndicator style={{ marginTop: 24 }} /> : (
        <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 60, gap: 10 }}>
          <View style={st.kpiRow}>
            <View style={st.kpi}><Text style={st.kpiN}>{dash?.cross_branch_employees ?? 0}</Text><Text style={st.kpiL}>Cross-Branch Employees</Text></View>
            <View style={st.kpi}><Text style={st.kpiN}>{dash?.guest_assignments ?? 0}</Text><Text style={st.kpiL}>Guest / Temp Assignments</Text></View>
          </View>
          {cards.map((c: any) => (
            <View key={c.branch_id || "main"} style={st.card} testID={`bd-card-${c.branch_id || "main"}`}>
              <View style={st.rowBetween}>
                <Text style={st.cardT}>{c.branch}{c.code ? ` · ${c.code}` : ""}</Text>
                {!c.active ? <Text style={st.inactive}>INACTIVE</Text> : null}
              </View>
              <View style={st.statGrid}>
                <Stat l="Employees" v={String(c.home_employees)} />
                <Stat l="Present Today" v={String(c.present_today)} />
                <Stat l="Worked Days" v={String(c.worked_days)} />
                <Stat l="Guest Days" v={String(c.guest_days)} />
                <Stat l="Gross Cost" v={inr(c.gross_cost)} strong />
                <Stat l="Net Cost" v={inr(c.net_cost)} strong />
                <Stat l="PF Liability" v={inr(c.pf_liability)} />
                <Stat l="ESIC Liability" v={inr(c.esic_liability)} />
                <Stat l="Joiners" v={String(c.joiners)} />
                <Stat l="Exits" v={String(c.exits)} />
              </View>
            </View>
          ))}
          {!cards.length ? (
            <Text style={st.hint}>No processed salary / attendance found for {month}. Process the salary sheet first — allocation is derived from the consolidated payroll (single payslip per employee).</Text>
          ) : null}

          <Pressable style={st.toggle} onPress={() => setShowEmp((v) => !v)} testID="bd-toggle-emp">
            <Text style={st.toggleTxt}>{showEmp ? "▼" : "▶"} Employee-wise Allocation ({alloc?.employees?.length || 0})</Text>
          </Pressable>
          {showEmp ? (alloc?.employees || []).map((e: any) => (
            <View key={e.user_id} style={st.card}>
              <View style={st.rowBetween}>
                <Text style={st.cardT}>{e.name}</Text>
                {e.cross_branch ? <Text style={st.cross}>CROSS-BRANCH</Text> : null}
              </View>
              <Text style={st.sub}>
                Home: {e.home_branch} · {e.present_days} days · Gross {inr(e.gross)} · Net {inr(e.net)} (one payroll record)
              </Text>
              {e.allocation.map((p: any, i: number) => (
                <Text key={i} style={[st.sub, { marginLeft: 8 }]}>
                  • {p.branch}: {p.days} days → Gross {inr(p.gross)} · Net {inr(p.net)}{p.guest ? "  (guest)" : ""}
                </Text>
              ))}
            </View>
          )) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function Stat({ l, v, strong }: { l: string; v: string; strong?: boolean }) {
  return (
    <View style={st.stat}>
      <Text style={[st.statV, strong && { color: "#2563EB" }]}>{v}</Text>
      <Text style={st.statL}>{l}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F8FAFC" },
  header: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14 },
  h1: { fontSize: 18, fontWeight: "800", color: "#0F172A", flex: 1 },
  month: { borderWidth: 1, borderColor: "#CBD5E1", borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6, fontSize: 13, backgroundColor: "#fff", width: 100 },
  chip: { borderWidth: 1, borderColor: "#CBD5E1", borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6, backgroundColor: "#fff" },
  chipOn: { backgroundColor: "#2563EB", borderColor: "#2563EB" },
  chipTxt: { fontSize: 12, color: "#334155", fontWeight: "600" },
  chipTxtOn: { color: "#fff" },
  kpiRow: { flexDirection: "row", gap: 10 },
  kpi: { flex: 1, backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#E2E8F0", padding: 12, alignItems: "center" },
  kpiN: { fontSize: 20, fontWeight: "900", color: "#2563EB" },
  kpiL: { fontSize: 11, color: "#64748B", marginTop: 2, textAlign: "center" },
  card: { backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#E2E8F0", padding: 12, gap: 6 },
  cardT: { fontSize: 14, fontWeight: "800", color: "#0F172A" },
  sub: { fontSize: 12, color: "#64748B" },
  hint: { fontSize: 12, color: "#94A3B8", textAlign: "center", marginTop: 16 },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  inactive: { fontSize: 10, fontWeight: "800", color: "#B91C1C" },
  cross: { fontSize: 10, fontWeight: "800", color: "#9A3412" },
  statGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  stat: { minWidth: 86, backgroundColor: "#F8FAFC", borderRadius: 8, padding: 8 },
  statV: { fontSize: 13, fontWeight: "800", color: "#0F172A" },
  statL: { fontSize: 10, color: "#64748B", marginTop: 1 },
  toggle: { paddingVertical: 8 },
  toggleTxt: { fontSize: 13, fontWeight: "800", color: "#2563EB" },
});
