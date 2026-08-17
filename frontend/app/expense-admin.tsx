/**
 * Iter 605 — Expense Claims Phase 4: Reports, Categories & Payroll feed.
 * Tabs: Reports (month summary by status/category/employee) ·
 * Categories master (add / rename / deactivate) ·
 * Payroll feed (paid-via-payroll reimbursements per employee).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, RefreshControl, Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";
import { STATUS_META } from "./my-expenses";

const inr = (v: any) => `₹${Number(v || 0).toLocaleString("en-IN")}`;
const nowMonth = () => new Date().toISOString().slice(0, 7);
const GROUPS = ["Travel", "Food", "Accommodation", "Office", "Client / Business", "Other"];

export default function ExpenseAdmin() {
  const router = useRouter();
  const { selectedCompanyId } = useSelectedCompany();
  const [tab, setTab] = useState<"reports" | "categories" | "payroll">("reports");
  const [month, setMonth] = useState(nowMonth());
  const [report, setReport] = useState<any>(null);
  const [cats, setCats] = useState<any[]>([]);
  const [payFeed, setPayFeed] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");
  const [newName, setNewName] = useState("");
  const [newGroup, setNewGroup] = useState("Other");

  const cidQ = selectedCompanyId ? `&company_id=${selectedCompanyId}` : "";

  const load = useCallback(async () => {
    setLoading(true); setMsg("");
    try {
      if (tab === "reports") {
        setReport(await api(`/expense/reports?month=${month}${cidQ}`));
      } else if (tab === "categories") {
        const r = await api(`/expense/categories?include_inactive=1${cidQ.replace("&", "&")}`);
        setCats(r.categories || []);
      } else {
        setPayFeed(await api(`/expense/payroll-reimbursements?month=${month}${cidQ}`));
      }
    } catch (e: any) { setMsg(String(e?.message || e)); }
    finally { setLoading(false); }
  }, [tab, month, cidQ]);
  useEffect(() => { load(); }, [load]);

  const toggleCat = async (c: any) => {
    try {
      await api("/expense/categories", {
        method: "POST",
        body: { category_id: c.category_id, company_id: c.company_id, active: !c.active },
      });
      await load();
    } catch (e: any) { setMsg(String(e?.message || e)); }
  };

  const addCat = async () => {
    if (!newName.trim()) return;
    try {
      await api("/expense/categories", {
        method: "POST",
        body: { name: newName.trim(), group: newGroup, company_id: selectedCompanyId || undefined },
      });
      setNewName(""); setMsg("Category added ✓");
      await load();
    } catch (e: any) { setMsg(String(e?.message || e)); }
  };

  const catGroups: Record<string, any[]> = {};
  cats.forEach((c) => { (catGroups[c.group] = catGroups[c.group] || []).push(c); });

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={{ padding: 4 }}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Expense Reports &amp; Settings</Text>
          <Text style={s.subtitle}>Monthly analysis · categories · payroll feed</Text>
        </View>
      </View>

      <View style={s.tabs}>
        {([["reports", "Reports", "stats-chart-outline"],
          ["categories", "Categories", "pricetags-outline"],
          ["payroll", "Payroll Feed", "cash-outline"]] as const).map(([k, l, ic]) => (
            <Pressable key={k} style={[s.tab, tab === k && s.tabOn]} onPress={() => setTab(k)}
              testID={`expadm-tab-${k}`}>
              <Ionicons name={ic as any} size={15} color={tab === k ? "#fff" : colors.onSurfaceSecondary} />
              <Text style={[s.tabTxt, tab === k && { color: "#fff" }]}>{l}</Text>
            </Pressable>
          ))}
      </View>

      <ScrollView contentContainerStyle={s.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.brandPrimary} />}>
        {msg ? <Text style={s.msg}>{msg}</Text> : null}

        {tab !== "categories" ? (
          <View style={s.monthRow}>
            <Text style={s.lbl}>Month (YYYY-MM)</Text>
            <TextInput style={s.monthInput} value={month} onChangeText={setMonth}
              placeholder="2026-06" placeholderTextColor={colors.onSurfaceTertiary} testID="expadm-month" />
            <Pressable style={s.goBtn} onPress={load}><Text style={s.goTxt}>Load</Text></Pressable>
          </View>
        ) : null}

        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} /> : null}

        {/* ─── REPORTS ─── */}
        {tab === "reports" && !loading && report ? (
          <>
            <View style={s.sumRow}>
              <View style={s.sumBox}><Text style={s.sumLbl}>Claims</Text>
                <Text style={s.sumVal}>{report.total_claims}</Text></View>
              <View style={s.sumBox}><Text style={s.sumLbl}>Claimed</Text>
                <Text style={s.sumVal}>{inr(report.total_amount)}</Text></View>
              <View style={s.sumBox}><Text style={s.sumLbl}>Paid out</Text>
                <Text style={[s.sumVal, { color: "#047857" }]}>{inr(report.total_paid)}</Text></View>
            </View>

            <Text style={s.secTitle}>By status</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
              {Object.entries(report.by_status || {}).map(([st, v]: any) => {
                const meta = STATUS_META[st] || { label: st, color: "#64748B" };
                return (
                  <View key={st} style={[s.stChip, { borderColor: `${meta.color}55` }]}>
                    <Text style={[s.stChipTxt, { color: meta.color }]}>
                      {meta.label}: {v.count} · {inr(v.amount)}
                    </Text>
                  </View>
                );
              })}
            </View>

            <Text style={s.secTitle}>By category</Text>
            {(report.by_category || []).map((r: any) => (
              <View key={r.name} style={s.line}>
                <Text style={s.lineName}>{r.name}</Text>
                <Text style={s.lineCount}>{r.count}</Text>
                <Text style={s.lineAmt}>{inr(r.amount)}</Text>
              </View>
            ))}
            {(report.by_category || []).length === 0 ? <Text style={s.muted}>No claims this month.</Text> : null}

            <Text style={s.secTitle}>By employee</Text>
            {(report.by_employee || []).map((r: any, i: number) => (
              <View key={i} style={s.line}>
                <Text style={s.lineName}>{r.name}{r.employee_code ? ` (${r.employee_code})` : ""}</Text>
                <Text style={s.lineCount}>{r.count}</Text>
                <Text style={s.lineAmt}>{inr(r.amount)}</Text>
              </View>
            ))}
          </>
        ) : null}

        {/* ─── CATEGORIES ─── */}
        {tab === "categories" && !loading ? (
          <>
            <View style={s.addBox}>
              <TextInput style={[s.monthInput, { flex: 1 }]} value={newName} onChangeText={setNewName}
                placeholder="New category name" placeholderTextColor={colors.onSurfaceTertiary}
                testID="expadm-newcat" />
              <Pressable style={s.goBtn} onPress={addCat} testID="expadm-addcat">
                <Text style={s.goTxt}>Add</Text>
              </Pressable>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 10 }}>
              {GROUPS.map((g) => (
                <Pressable key={g} onPress={() => setNewGroup(g)}
                  style={[s.gChip, newGroup === g && s.gChipOn]}>
                  <Text style={[s.gChipTxt, newGroup === g && { color: "#fff" }]}>{g}</Text>
                </Pressable>
              ))}
            </ScrollView>

            {Object.entries(catGroups).map(([g, list]) => (
              <View key={g}>
                <Text style={s.secTitle}>{g}</Text>
                {list.map((c) => (
                  <View key={c.category_id} style={s.line}>
                    <Text style={[s.lineName, !c.active && { color: colors.onSurfaceTertiary, textDecorationLine: "line-through" }]}>
                      {c.name}
                    </Text>
                    <Switch value={!!c.active} onValueChange={() => toggleCat(c)}
                      trackColor={{ true: colors.brandPrimary }} />
                  </View>
                ))}
              </View>
            ))}
          </>
        ) : null}

        {/* ─── PAYROLL FEED ─── */}
        {tab === "payroll" && !loading && payFeed ? (
          <>
            <Text style={s.hint}>
              Claims paid via “Add to Payroll” appear here as the “Expense Reimbursement” salary head —
              kept separate from wages, PF and ESIC.
            </Text>
            <Text style={s.secTitle}>Per-employee reimbursement · {payFeed.month}</Text>
            {(payFeed.per_employee || []).length === 0 ? (
              <Text style={s.muted}>No payroll reimbursements for this month.</Text>
            ) : null}
            {(payFeed.per_employee || []).map((r: any) => {
              const claim = (payFeed.claims || []).find((c: any) => c.user_id === r.user_id);
              return (
                <View key={r.user_id} style={s.line}>
                  <Text style={s.lineName}>
                    {claim?.employee?.name || r.user_id}
                    {claim?.employee?.employee_code ? ` (${claim.employee.employee_code})` : ""}
                  </Text>
                  <Text style={s.lineAmt}>{inr(r.amount)}</Text>
                </View>
              );
            })}
            {(payFeed.claims || []).length > 0 ? (
              <>
                <Text style={s.secTitle}>Underlying claims</Text>
                {(payFeed.claims || []).map((c: any) => (
                  <View key={c.claim_id} style={s.line}>
                    <Text style={s.lineName}>{c.claim_no} · {c.employee?.name}</Text>
                    <Text style={s.lineCount}>{c.payment_date}</Text>
                    <Text style={s.lineAmt}>{inr(c.paid_amount)}</Text>
                  </View>
                ))}
              </>
            ) : null}
          </>
        ) : null}
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceTertiary },
  tabs: {
    flexDirection: "row", gap: 6, paddingHorizontal: 12, paddingVertical: 10,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  tab: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderRadius: 999, paddingHorizontal: 13, paddingVertical: 8, minHeight: 38,
    backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border,
  },
  tabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, fontWeight: "800", color: colors.onSurfaceSecondary },
  body: { padding: 16 },
  msg: { fontSize: 12.5, color: "#059669", fontWeight: "700", marginBottom: 8 },
  monthRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 14 },
  lbl: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  monthInput: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 10, paddingHorizontal: 12, paddingVertical: 9,
    fontSize: 14, color: colors.onSurface, minHeight: 44, minWidth: 110,
  },
  goBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: 10,
    paddingHorizontal: 16, minHeight: 44, alignItems: "center", justifyContent: "center",
  },
  goTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  sumRow: { flexDirection: "row", gap: 8, marginBottom: 6 },
  sumBox: {
    flex: 1, backgroundColor: colors.surface, borderRadius: 12,
    padding: 10, borderWidth: 1, borderColor: colors.border,
  },
  sumLbl: { fontSize: 11, color: colors.onSurfaceTertiary, fontWeight: "700" },
  sumVal: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginTop: 2 },
  secTitle: {
    fontSize: 12, fontWeight: "800", color: colors.onSurfaceTertiary,
    textTransform: "uppercase", marginTop: 18, marginBottom: 8,
  },
  stChip: {
    borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 6,
    backgroundColor: colors.surface,
  },
  stChipTxt: { fontSize: 11.5, fontWeight: "800" },
  line: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.surface, borderRadius: 10, padding: 12,
    borderWidth: 1, borderColor: colors.border, marginBottom: 6,
  },
  lineName: { flex: 1, fontSize: 13, fontWeight: "700", color: colors.onSurface },
  lineCount: { fontSize: 12, color: colors.onSurfaceTertiary, fontWeight: "700" },
  lineAmt: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  muted: { color: colors.onSurfaceTertiary, fontSize: 13 },
  addBox: { flexDirection: "row", gap: 10, marginBottom: 10 },
  gChip: {
    borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, marginRight: 8,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  gChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  gChipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  hint: {
    fontSize: 12, color: "#1E40AF", backgroundColor: "#EFF6FF",
    borderRadius: 10, padding: 10, marginBottom: 4, lineHeight: 17,
  },
});
