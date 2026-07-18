/**
 * My Advances — Employee Self-Service view (read-only).
 * Shows each advance with outstanding balance, EMI, recovery schedule,
 * next deduction month and full deduction history.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { colors } from "@/src/theme";

const STATUS_COLORS: Record<string, string> = {
  active: "#059669", scheduled: "#2563EB", on_hold: "#D97706",
  closed: "#DC2626", waived: "#64748B",
};
const inr = (v: any) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

export default function MyAdvances() {
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try { setData(await api("/me/advances")); } catch { setData(null); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const sum = data?.summary;
  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.back}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>My Advances</Text>
          <Text style={s.subtitle}>Balances, EMI schedule &amp; deduction history</Text>
        </View>
      </View>
      <ScrollView
        contentContainerStyle={s.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.brandPrimary} />}
      >
        <View style={s.sumRow}>
          <View style={s.sumBox}><Text style={s.sumLbl}>Outstanding</Text>
            <Text style={[s.sumVal, { color: "#DC2626" }]}>{inr(sum?.outstanding)}</Text></View>
          <View style={s.sumBox}><Text style={s.sumLbl}>Recovered</Text>
            <Text style={[s.sumVal, { color: "#059669" }]}>{inr(sum?.recovered)}</Text></View>
          <View style={s.sumBox}><Text style={s.sumLbl}>Active</Text>
            <Text style={s.sumVal}>{sum?.active ?? 0}</Text></View>
        </View>

        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} /> : null}
        {!loading && (data?.advances || []).length === 0 ? (
          <View style={s.empty}>
            <Ionicons name="wallet-outline" size={38} color={colors.onSurfaceTertiary} />
            <Text style={s.muted}>You have no advances.</Text>
          </View>
        ) : null}

        {(data?.advances || []).map((a: any) => {
          const pct = Math.min(100, Math.round(100 * (a.recovered_total || 0) / (a.amount || 1)));
          const c = STATUS_COLORS[a.status] || "#64748B";
          const expanded = open === a.advance_id;
          return (
            <Pressable key={a.advance_id} style={s.card} onPress={() => setOpen(expanded ? null : a.advance_id)} testID={`myadv-${a.voucher_no}`}>
              <View style={s.cardTop}>
                <Text style={s.voucher}>{a.voucher_no}</Text>
                <Text style={s.type}>{a.advance_type}</Text>
                <View style={[s.pill, { backgroundColor: `${c}18` }]}>
                  <Text style={[s.pillTxt, { color: c }]}>{a.status.replace("_", " ").toUpperCase()}</Text>
                </View>
              </View>
              <View style={s.amtRow}>
                <View><Text style={s.amtLbl}>Advance</Text><Text style={s.amtVal}>{inr(a.amount)}</Text></View>
                <View><Text style={s.amtLbl}>Recovered</Text><Text style={[s.amtVal, { color: "#059669" }]}>{inr(a.recovered_total)}</Text></View>
                <View><Text style={s.amtLbl}>Balance</Text><Text style={[s.amtVal, { color: "#DC2626" }]}>{inr(a.remaining_balance)}</Text></View>
                {a.emi_amount ? <View><Text style={s.amtLbl}>EMI</Text><Text style={s.amtVal}>{inr(a.emi_amount)}</Text></View> : null}
              </View>
              <View style={s.track}><View style={[s.fill, { width: `${pct}%` }]} /></View>
              <Text style={s.metaLine}>
                {pct}% recovered{a.next_recovery_month ? ` · Next deduction: ${a.next_recovery_month}` : ""}
              </Text>

              {expanded ? (
                <View style={{ marginTop: 10 }}>
                  <Text style={s.secTitle}>Recovery Schedule</Text>
                  {(a.schedule || []).map((r: any, i: number) => (
                    <View key={i} style={s.line}>
                      <Text style={s.lineMonth}>{r.month}</Text>
                      <Text style={s.lineAmt}>{inr(r.emi)}</Text>
                      <Text style={[s.lineStatus, {
                        color: r.status === "paid" ? "#059669" : r.status === "skipped" ? "#D97706" : colors.onSurfaceTertiary }]}>
                        {r.status.toUpperCase()}</Text>
                    </View>
                  ))}
                  <Text style={s.secTitle}>Deduction History</Text>
                  {(a.transactions || []).length === 0 ? <Text style={s.muted}>No deductions yet</Text> :
                    a.transactions.map((t: any) => (
                      <View key={t.txn_id} style={s.line}>
                        <Text style={s.lineMonth}>{t.salary_month}</Text>
                        <Text style={s.lineAmt}>{inr(t.amount)}</Text>
                        <Text style={s.lineStatus}>{t.process_type}{t.balance_applied ? "" : " (mirror)"}</Text>
                      </View>
                    ))}
                </View>
              ) : null}
              <Text style={s.expandHint}>{expanded ? "Tap to collapse" : "Tap for schedule & history"}</Text>
            </Pressable>
          );
        })}
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surfaceSecondary, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  back: { width: 38, height: 38, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceTertiary },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 1 },
  body: { padding: 16, width: "100%", maxWidth: 700, alignSelf: "center" },
  sumRow: { flexDirection: "row", gap: 10, marginBottom: 14 },
  sumBox: { flex: 1, backgroundColor: colors.surfaceSecondary, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: colors.border },
  sumLbl: { fontSize: 10.5, color: colors.onSurfaceTertiary, fontWeight: "700" },
  sumVal: { fontSize: 16, fontWeight: "800", color: colors.onSurface, marginTop: 3 },
  empty: { alignItems: "center", paddingVertical: 44, gap: 10 },
  muted: { fontSize: 12, color: colors.onSurfaceTertiary },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 16, borderWidth: 1, borderColor: colors.border,
    padding: 14, marginBottom: 12,
  },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  voucher: { fontSize: 12.5, fontWeight: "800", color: colors.brandPrimary },
  type: { flex: 1, fontSize: 13.5, fontWeight: "700", color: colors.onSurface },
  pill: { borderRadius: 8, paddingHorizontal: 7, paddingVertical: 2 },
  pillTxt: { fontSize: 9.5, fontWeight: "800", letterSpacing: 0.4 },
  amtRow: { flexDirection: "row", gap: 18, marginTop: 10, flexWrap: "wrap" },
  amtLbl: { fontSize: 10, color: colors.onSurfaceTertiary, fontWeight: "700" },
  amtVal: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  track: { height: 6, borderRadius: 3, backgroundColor: colors.surfaceTertiary, marginTop: 10 },
  fill: { height: 6, borderRadius: 3, backgroundColor: "#059669" },
  metaLine: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 6 },
  secTitle: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface, marginTop: 10, marginBottom: 4 },
  line: {
    flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  lineMonth: { width: 74, fontSize: 12, fontWeight: "700", color: colors.onSurface },
  lineAmt: { flex: 1, fontSize: 12, color: colors.onSurface },
  lineStatus: { fontSize: 10, fontWeight: "800", color: colors.onSurfaceTertiary },
  expandHint: { fontSize: 10, color: colors.onSurfaceTertiary, marginTop: 8, textAlign: "center" },
});
