/**
 * Iter 706 — ESS → My Tours: dashboard cards + tour list.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, Pressable, ActivityIndicator, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors } from "@/src/theme";

export const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  draft: { label: "Draft", color: "#64748B", bg: "rgba(100,116,139,0.12)" },
  submitted: { label: "Submitted", color: "#0369A1", bg: "rgba(3,105,161,0.12)" },
  pending_approval: { label: "Pending Approval", color: "#D97706", bg: "rgba(217,119,6,0.12)" },
  approved: { label: "Approved", color: "#059669", bg: "rgba(5,150,105,0.12)" },
  active: { label: "Active", color: "#DC2626", bg: "rgba(220,38,38,0.12)" },
  completed: { label: "Completed", color: "#2563EB", bg: "rgba(37,99,235,0.12)" },
  returned: { label: "Returned", color: "#B45309", bg: "rgba(180,83,9,0.12)" },
  rejected: { label: "Rejected", color: "#DC2626", bg: "rgba(220,38,38,0.12)" },
  cancelled: { label: "Cancelled", color: "#6B7280", bg: "rgba(107,114,128,0.12)" },
};

export default function MyTours() {
  const router = useRouter();
  const { user } = useAuth();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");

  const load = useCallback(async () => {
    try {
      const r = await api<any>("/tours/mine");
      setData(r);
    } catch { /* keep last */ }
    finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!user) return null;
  const counts = data?.counts || {};
  const tours = (data?.tours || []).filter(
    (t: any) => filter === "all" || t.status === filter);

  const cards: [string, string][] = [
    ["total", "Total"], ["draft", "Draft"], ["pending_approval", "Pending"],
    ["approved", "Approved"], ["active", "Active"], ["completed", "Completed"],
    ["returned", "Returned"], ["rejected", "Rejected"], ["cancelled", "Cancelled"],
  ];

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.hBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>My Tours</Text>
          <Text style={s.subtitle}>Official tours · client visits · tracking</Text>
        </View>
        <Pressable style={s.newBtn} onPress={() => router.push("/tour-request" as any)} testID="new-tour-btn">
          <Ionicons name="add" size={16} color="#fff" />
          <Text style={s.newBtnT}>New Tour</Text>
        </Pressable>
      </View>

      {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 40 }} /> : (
        <FlatList
          data={tours}
          keyExtractor={(t: any) => t.tour_id}
          contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={false} onRefresh={load} />}
          ListHeaderComponent={
            <>
              <View style={s.cardsWrap}>
                {cards.map(([k, lbl]) => (
                  <Pressable key={k} style={[s.statCard, filter === (k === "total" ? "all" : k) && s.statCardOn]}
                    onPress={() => setFilter(k === "total" ? "all" : k)} testID={`tour-stat-${k}`}>
                    <Text style={s.statVal}>{counts[k] ?? 0}</Text>
                    <Text style={s.statLbl}>{lbl}</Text>
                  </Pressable>
                ))}
              </View>
              {tours.length === 0 ? (
                <Text style={[s.muted, { textAlign: "center", marginTop: 30 }]}>
                  No tours here yet. Tap “New Tour” to create your first tour request.
                </Text>
              ) : null}
            </>
          }
          renderItem={({ item }) => {
            const m = STATUS_META[item.status] || STATUS_META.draft;
            return (
              <Pressable style={s.tourCard} testID={`tour-${item.tour_no}`}
                onPress={() => router.push(`/tour-detail?id=${item.tour_id}` as any)}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <View style={s.tourIcon}>
                    <Ionicons name="airplane-outline" size={16} color={colors.brandPrimary} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.tourNo}>{item.tour_no}</Text>
                    <Text style={s.tourType}>{item.tour_type}</Text>
                  </View>
                  <View style={[s.chip, { backgroundColor: m.bg }]}>
                    {item.status === "active" ? <Text style={{ fontSize: 9 }}>🔴</Text> : null}
                    <Text style={[s.chipT, { color: m.color }]}>{m.label}</Text>
                  </View>
                </View>
                <Text style={s.dest} numberOfLines={1}>
                  {item.from_location ? `${item.from_location} → ` : ""}
                  {(item.destinations || []).join(", ")}
                </Text>
                <Text style={s.dates}>
                  {item.start_date} → {item.end_date} · {item.total_days} day{item.total_days === 1 ? "" : "s"}
                  {item.total_estimated ? ` · Est ₹${item.total_estimated}` : ""}
                </Text>
              </Pressable>
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
    flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16,
    paddingVertical: 12, backgroundColor: colors.surfaceSecondary,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  hBtn: { width: 38, height: 38, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceTertiary },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 1 },
  newBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brandPrimary,
    borderRadius: 10, paddingHorizontal: 12, height: 38,
  },
  newBtnT: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  muted: { fontSize: 12, color: colors.onSurfaceTertiary },
  cardsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 14 },
  statCard: {
    minWidth: 74, flexGrow: 1, backgroundColor: colors.surfaceSecondary, borderRadius: 12,
    borderWidth: 1, borderColor: colors.border, paddingVertical: 10, alignItems: "center",
  },
  statCardOn: { borderColor: colors.brandPrimary, backgroundColor: "rgba(37,99,235,0.06)" },
  statVal: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  statLbl: { fontSize: 10.5, fontWeight: "700", color: colors.onSurfaceTertiary, marginTop: 1 },
  tourCard: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 14, padding: 12,
    borderWidth: 1, borderColor: colors.border, marginBottom: 10,
  },
  tourIcon: { width: 30, height: 30, borderRadius: 9, backgroundColor: "rgba(37,99,235,0.1)", alignItems: "center", justifyContent: "center" },
  tourNo: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  tourType: { fontSize: 11, color: colors.onSurfaceTertiary },
  chip: { flexDirection: "row", alignItems: "center", gap: 3, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4 },
  chipT: { fontSize: 10.5, fontWeight: "800" },
  dest: { fontSize: 12.5, fontWeight: "600", color: colors.onSurfaceSecondary, marginTop: 8 },
  dates: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 2 },
});
