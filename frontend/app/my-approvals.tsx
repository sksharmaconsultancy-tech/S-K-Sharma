/**
 * Iter 707 — Employee PWA Pending Approval Center.
 * All of MY requests across every module (leave, expense, tour, advance +
 * engine-routed workflows) with level progress, current approver, timeline,
 * and Edit/Resubmit for returned items. Auto-refreshes every 25s.
 */
import React, { useCallback, useRef, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, Pressable, ActivityIndicator,
  RefreshControl, ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors } from "@/src/theme";

const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: "Pending", color: "#D97706", bg: "rgba(217,119,6,0.12)" },
  under_review: { label: "Under Review", color: "#0369A1", bg: "rgba(3,105,161,0.12)" },
  approved: { label: "Approved", color: "#059669", bg: "rgba(5,150,105,0.12)" },
  rejected: { label: "Rejected", color: "#DC2626", bg: "rgba(220,38,38,0.12)" },
  returned: { label: "Returned", color: "#B45309", bg: "rgba(180,83,9,0.12)" },
  cancelled: { label: "Cancelled", color: "#6B7280", bg: "rgba(107,114,128,0.12)" },
};
const TABS = ["all", "pending", "approved", "rejected", "returned", "cancelled"] as const;

export default function MyApprovals() {
  const router = useRouter();
  const { user } = useAuth();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<string>("pending");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [expanded, setExpanded] = useState<string | null>(null);
  const pollRef = useRef<any>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try { setData(await api<any>("/my-approvals")); }
    catch { /* keep last */ }
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => {
    load();
    pollRef.current = setInterval(() => load(true), 25000);
    return () => clearInterval(pollRef.current);
  }, [load]));

  if (!user) return null;
  const counts = data?.counts || {};
  const types: string[] = ["all", ...Array.from(new Set((data?.items || []).map((i: any) => i.type)))] as string[];
  const items = (data?.items || []).filter((i: any) =>
    (tab === "all" || (tab === "pending" ? ["pending", "under_review"].includes(i.status) : i.status === tab)) &&
    (typeFilter === "all" || i.type === typeFilter));

  const Progress = ({ it }: { it: any }) => {
    if (!it.steps?.length && it.level_total <= 1) return null;
    const steps = it.steps?.length ? it.steps
      : Array.from({ length: it.level_total }, (_, i) => ({
        level: i + 1, name: `Level ${i + 1}`,
        state: i + 1 < it.level_current ? "done" : i + 1 === it.level_current ? "current" : "todo" }));
    return (
      <View style={{ marginTop: 8 }}>
        <View style={{ flexDirection: "row", alignItems: "center" }}>
          {steps.map((st: any, i: number) => (
            <React.Fragment key={i}>
              <View style={[s.dot,
                st.state === "done" && { backgroundColor: "#059669" },
                st.state === "current" && { backgroundColor: "#D97706" },
                ["rejected", "returned"].includes(st.state) && { backgroundColor: "#DC2626" }]}>
                {st.state === "done" ? <Ionicons name="checkmark" size={9} color="#fff" /> : null}
              </View>
              {i < steps.length - 1 ? (
                <View style={[s.line, st.state === "done" && { backgroundColor: "#059669" }]} />
              ) : null}
            </React.Fragment>
          ))}
        </View>
        {["pending", "under_review"].includes(it.status) ? (
          <Text style={s.lvlTxt}>
            Level {it.level_current} of {it.level_total}
            {it.pending_with ? ` — ${it.pending_with} approval pending` : ""}
          </Text>
        ) : null}
      </View>
    );
  };

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.hBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>🔔 Pending Approvals</Text>
          <Text style={s.subtitle}>All your requests · every approval level · live status</Text>
        </View>
      </View>

      <View style={{ paddingHorizontal: 16, paddingTop: 10 }}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View style={{ flexDirection: "row", gap: 6 }}>
            {TABS.map((t) => {
              const n = t === "all" ? (data?.items || []).length
                : t === "pending" ? (counts.pending || 0) + (counts.under_review || 0)
                : counts[t] || 0;
              return (
                <Pressable key={t} style={[s.tab, tab === t && s.tabOn]} onPress={() => setTab(t)} testID={`ma-tab-${t}`}>
                  <Text style={[s.tabT, tab === t && s.tabTOn]}>
                    {t[0].toUpperCase() + t.slice(1)} ({n})
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </ScrollView>
        {types.length > 2 ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
            <View style={{ flexDirection: "row", gap: 6 }}>
              {types.map((t) => (
                <Pressable key={t} style={[s.fChip, typeFilter === t && s.fChipOn]}
                  onPress={() => setTypeFilter(t)} testID={`ma-type-${t}`}>
                  <Text style={[s.fChipT, typeFilter === t && { color: "#fff" }]}>{t === "all" ? "All Types" : t}</Text>
                </Pressable>
              ))}
            </View>
          </ScrollView>
        ) : null}
      </View>

      {loading && !data ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 40 }} /> : (
        <FlatList
          data={items}
          keyExtractor={(i: any) => `${i.type_key}-${i.record_id}`}
          contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={false} onRefresh={() => load()} />}
          ListEmptyComponent={
            <Text style={s.empty}>Nothing here — requests you submit will appear with their live approval status.</Text>
          }
          renderItem={({ item: it }) => {
            const m = STATUS_META[it.status] || STATUS_META.pending;
            const open = expanded === `${it.type_key}-${it.record_id}`;
            return (
              <View style={s.card} testID={`ma-item-${it.ref}`}>
                <Pressable onPress={() => setExpanded(open ? null : `${it.type_key}-${it.record_id}`)}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                    <View style={s.icoWrap}>
                      <Ionicons name={it.icon || "document-outline"} size={15} color={colors.brandPrimary} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={s.ref}>{it.type} · {it.ref}</Text>
                      <Text style={s.meta} numberOfLines={1}>
                        {it.detail || ""}
                        {it.from_date ? ` · ${it.from_date}${it.to_date && it.to_date !== it.from_date ? ` → ${it.to_date}` : ""}` : ""}
                      </Text>
                    </View>
                    {it.amount ? <Text style={s.amt}>₹{it.amount}</Text> : null}
                    <View style={[s.chip, { backgroundColor: m.bg }]}>
                      <Text style={[s.chipT, { color: m.color }]}>{m.label}</Text>
                    </View>
                  </View>
                  <Progress it={it} />
                </Pressable>

                {it.status === "returned" ? (
                  <View style={s.retBox}>
                    <Text style={s.retT}>↩ Returned for correction{it.remarks ? ` — ${it.remarks}` : ""}</Text>
                    {it.edit_route ? (
                      <Pressable style={s.editBtn} onPress={() => router.push(it.edit_route as any)}
                        testID={`ma-edit-${it.ref}`}>
                        <Text style={s.editBtnT}>Edit &amp; Resubmit</Text>
                      </Pressable>
                    ) : null}
                  </View>
                ) : null}

                {open ? (
                  <View style={s.detailBox}>
                    <Text style={s.dRow}>Submitted: {String(it.submitted_at || "").slice(0, 16).replace("T", " ")}</Text>
                    <Text style={s.dRow}>Last action: {String(it.last_action_at || "").slice(0, 16).replace("T", " ")}</Text>
                    {it.pending_with && ["pending", "under_review"].includes(it.status) ? (
                      <Text style={s.dRow}>Currently with: {it.pending_with}</Text>
                    ) : null}
                    {it.remarks ? <Text style={s.dRow}>Remarks: {it.remarks}</Text> : null}
                    {(it.history || []).length ? (
                      <>
                        <Text style={[s.dRow, { fontWeight: "800", marginTop: 6 }]}>Approval Timeline</Text>
                        {it.history.map((h: any, i: number) => (
                          <View key={i} style={{ flexDirection: "row", gap: 8, marginTop: 5 }}>
                            <View style={[s.dot, { marginTop: 3, backgroundColor: colors.brandPrimary }]} />
                            <Text style={[s.dRow, { flex: 1, marginTop: 0 }]}>
                              {String(h.at || "").slice(0, 16).replace("T", " ")} · {String(h.action || "").toUpperCase()}
                              {h.level ? ` (L${h.level})` : ""} by {h.by || "—"}
                              {h.remarks ? ` — ${h.remarks}` : ""}
                            </Text>
                          </View>
                        ))}
                      </>
                    ) : null}
                    {it.view_route ? (
                      <Pressable style={[s.editBtn, { marginTop: 10 }]}
                        onPress={() => router.push(it.view_route as any)} testID={`ma-view-${it.ref}`}>
                        <Text style={s.editBtnT}>View Details</Text>
                      </Pressable>
                    ) : null}
                  </View>
                ) : null}
              </View>
            );
          }}
        />
      )}
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surfaceSecondary, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  hBtn: { width: 38, height: 38, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceTertiary },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 1 },
  tab: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 10, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  tabOn: { backgroundColor: "rgba(37,99,235,0.1)", borderColor: colors.brandPrimary },
  tabT: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTOn: { color: colors.brandPrimary },
  fChip: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 9, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  fChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  fChipT: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  empty: { fontSize: 12.5, color: colors.onSurfaceTertiary, textAlign: "center", marginTop: 40, paddingHorizontal: 20 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 14, padding: 12,
    borderWidth: 1, borderColor: colors.border, marginBottom: 10,
  },
  icoWrap: { width: 30, height: 30, borderRadius: 9, backgroundColor: "rgba(37,99,235,0.1)", alignItems: "center", justifyContent: "center" },
  ref: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  meta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 1 },
  amt: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  chip: { borderRadius: 8, paddingHorizontal: 7, paddingVertical: 4 },
  chipT: { fontSize: 10, fontWeight: "800" },
  dot: { width: 14, height: 14, borderRadius: 7, backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  line: { flex: 1, height: 2.5, backgroundColor: colors.surfaceTertiary, marginHorizontal: 2 },
  lvlTxt: { fontSize: 11, fontWeight: "700", color: "#D97706", marginTop: 5 },
  retBox: {
    marginTop: 8, backgroundColor: "rgba(180,83,9,0.08)", borderRadius: 10, padding: 9,
    borderWidth: 1, borderColor: "rgba(180,83,9,0.25)",
  },
  retT: { fontSize: 11.5, fontWeight: "700", color: "#B45309" },
  editBtn: {
    marginTop: 8, backgroundColor: colors.brandPrimary, borderRadius: 9, minHeight: 40,
    alignItems: "center", justifyContent: "center", paddingHorizontal: 14, alignSelf: "flex-start",
  },
  editBtnT: { color: "#fff", fontWeight: "800", fontSize: 12 },
  detailBox: { marginTop: 10, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border, paddingTop: 8 },
  dRow: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 3 },
});
