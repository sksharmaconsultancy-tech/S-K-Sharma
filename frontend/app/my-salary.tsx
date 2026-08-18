/**
 * Iter 610 — ESS: My Salary / CTC + PF + ESIC (real payroll data only).
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/api/client";
import { colors } from "@/src/theme";

const inr = (v: any) => (v == null ? "Not Available" : `₹${Number(v).toLocaleString("en-IN")}`);

export default function MySalary() {
  const router = useRouter();
  const [tab, setTab] = useState<"salary" | "pf" | "esic">("salary");
  const [data, setData] = useState<any>(null);
  const [openM, setOpenM] = useState<string | null>(null);

  useEffect(() => { api("/ess/salary").then(setData).catch(() => setData({ months: [], pf: [], esic: [] })); }, []);

  const Row = ({ l, v, bold }: any) => (
    <View style={s.row}><Text style={[s.lbl, bold && s.bold]}>{l}</Text><Text style={[s.val, bold && s.bold]}>{v}</Text></View>
  );

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="arrow-back" size={22} color={colors.onSurface} /></Pressable>
        <Text style={s.title}>My Salary · PF · ESIC</Text>
      </View>
      <View style={s.tabs}>
        {(["salary", "pf", "esic"] as const).map((t) => (
          <Pressable key={t} style={[s.tab, tab === t && s.tabOn]} onPress={() => setTab(t)} testID={`sal-tab-${t}`}>
            <Text style={[s.tabTxt, tab === t && { color: "#fff" }]}>{t === "salary" ? "Salary / CTC" : t.toUpperCase()}</Text>
          </Pressable>
        ))}
      </View>
      {!data ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 40 }} /> : (
        <ScrollView contentContainerStyle={s.body}>
          {tab === "salary" && (data.months || []).length === 0 ? (
            <Text style={s.muted}>No processed salary months yet.</Text>) : null}

          {tab === "salary" && (data.months || []).map((m: any) => (
            <Pressable key={m.month} style={s.card} onPress={() => setOpenM(openM === m.month ? null : m.month)} testID={`sal-month-${m.month}`}>
              <View style={s.cardTop}>
                <Text style={s.month}>{m.month}</Text>
                <Text style={s.net}>Net {inr(m.net)}</Text>
              </View>
              <Text style={s.sub}>Gross {inr(m.gross)} · CTC {inr(m.ctc)} · {m.present_days ?? m.attendance_days ?? "—"} days{m.ot_hours ? ` · OT ${m.ot_hours}h` : ""}</Text>
              {openM === m.month ? (
                <View style={{ marginTop: 8 }}>
                  <Text style={s.secT}>Earnings</Text>
                  {Object.entries(m.earnings || {}).map(([k, v]: any) => Number(v) > 0 ? (
                    <Row key={k} l={k.replace("_", " ").toUpperCase()} v={inr(v)} />) : null)}
                  <Row l="GROSS" v={inr(m.gross)} bold />
                  <Text style={s.secT}>Deductions</Text>
                  {Object.entries(m.deductions || {}).map(([k, v]: any) => Number(v) > 0 ? (
                    <Row key={k} l={k.toUpperCase()} v={inr(v)} />) : null)}
                  <Row l="TOTAL DEDUCTION" v={inr(m.total_deduction)} bold />
                  <Row l="NET SALARY" v={inr(m.net)} bold />
                  <Row l="CTC (incl. employer PF+ESIC)" v={inr(m.ctc)} bold />
                </View>
              ) : <Text style={s.hint}>Tap for full breakup</Text>}
            </Pressable>
          ))}

          {tab === "pf" ? (
            <>
              <View style={s.card}><Row l="UAN" v={data.uan || (data.pf?.[0]?.uan) || "Not Available"} bold /></View>
              {(data.pf || []).length === 0 ? <Text style={s.muted}>No PF contribution months yet.</Text> : null}
              {(data.pf || []).map((m: any) => (
                <View key={m.month} style={s.card}>
                  <View style={s.cardTop}><Text style={s.month}>{m.month}</Text>
                    <Text style={[s.sub, { color: m.applicable ? "#059669" : "#B45309" }]}>{m.applicable ? "PF Applicable" : "Not Applicable"}</Text></View>
                  <Row l="PF Wage" v={inr(m.pf_wage)} />
                  <Row l="Employee Contribution (12%)" v={inr(m.employee)} />
                  <Row l="Employer EPF (3.67%)" v={inr(m.employer_epf)} />
                  <Row l="Employer EPS / Pension (8.33%)" v={inr(m.employer_eps)} />
                </View>
              ))}
            </>
          ) : null}

          {tab === "esic" ? (
            <>
              <View style={s.card}><Row l="ESIC / IP Number" v={data.esi_ip_no || (data.esic?.[0]?.ip_no) || "Not Available"} bold /></View>
              {(data.esic || []).length === 0 ? <Text style={s.muted}>No ESIC contribution months yet.</Text> : null}
              {(data.esic || []).map((m: any) => (
                <View key={m.month} style={s.card}>
                  <View style={s.cardTop}><Text style={s.month}>{m.month}</Text>
                    <Text style={[s.sub, { color: m.applicable ? "#059669" : "#B45309" }]}>{m.applicable ? "Covered" : "Not Applicable"}</Text></View>
                  <Row l="ESIC Wage" v={inr(m.esic_wage)} />
                  <Row l="Employee Contribution (0.75%)" v={inr(m.employee)} />
                  <Row l="Employer Contribution (3.25%)" v={inr(m.employer)} />
                </View>
              ))}
            </>
          ) : null}
          <Text style={s.hint}>Figures come directly from processed payroll — nothing is estimated.</Text>
          <View style={{ height: 40 }} />
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { flex: 1, fontSize: 17, fontWeight: "800", color: colors.onSurface },
  tabs: { flexDirection: "row", gap: 8, padding: 12, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  tab: { flex: 1, borderRadius: 999, paddingVertical: 9, alignItems: "center", backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, minHeight: 40 },
  tabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, fontWeight: "800", color: colors.onSurfaceSecondary },
  body: { padding: 16 },
  muted: { color: colors.onSurfaceTertiary, fontSize: 13, textAlign: "center", marginTop: 20 },
  card: { backgroundColor: colors.surface, borderRadius: 14, padding: 14, borderWidth: 1, borderColor: colors.border, marginBottom: 10 },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  month: { fontSize: 14, fontWeight: "800", color: colors.brandPrimary },
  net: { fontSize: 14.5, fontWeight: "800", color: "#059669" },
  sub: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: 3 },
  secT: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceTertiary, textTransform: "uppercase", marginTop: 8, marginBottom: 2 },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 },
  lbl: { fontSize: 12.5, color: colors.onSurfaceSecondary },
  val: { fontSize: 12.5, color: colors.onSurface, fontWeight: "700" },
  bold: { fontWeight: "800", color: colors.onSurface },
  hint: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 6, textAlign: "center" },
});
