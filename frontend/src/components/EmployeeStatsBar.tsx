// Iter 182 — Premium Employee Master widgets: gradient stat cards +
// skeleton loading rows (SAP/Workday-style polish, azure/indigo palette).
import React, { useEffect, useRef } from "react";
import { View, Text, StyleSheet, Animated } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";

import { colors, shadow } from "@/src/theme";

export function EmployeeStatsBar({ employees }: { employees: any[] }) {
  const isResigned = (e: any) =>
    !!e.exit_date || e.employment_status === "resigned" || e.disabled === true;
  const total = employees.length;
  const resigned = employees.filter(isResigned).length;
  const active = total - resigned;
  const onroll = employees.filter((e) => !isResigned(e) && e.is_onroll !== false).length;
  const offroll = active - onroll;
  const CARDS: { label: string; value: number; icon: string; grad: [string, string] }[] = [
    { label: "Total Employees", value: total, icon: "people", grad: ["#2563EB", "#4338CA"] },
    { label: "Active", value: active, icon: "checkmark-circle", grad: ["#059669", "#10B981"] },
    { label: "On-roll", value: onroll, icon: "shield-checkmark", grad: ["#0891B2", "#2563EB"] },
    { label: "Off-roll", value: offroll, icon: "briefcase", grad: ["#B45309", "#F59E0B"] },
    { label: "Resigned", value: resigned, icon: "log-out", grad: ["#B91C1C", "#EF4444"] },
  ];
  return (
    <View style={st.row} testID="emp-stats-bar">
      {CARDS.map((c) => (
        <View key={c.label} style={st.card}>
          <LinearGradient colors={c.grad} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
            style={st.icon}>
            <Ionicons name={`${c.icon}-outline` as any} size={15} color="#fff" />
          </LinearGradient>
          <View>
            <Text style={st.val}>{c.value}</Text>
            <Text style={st.lbl} numberOfLines={1}>{c.label}</Text>
          </View>
        </View>
      ))}
    </View>
  );
}

export function EmployeeListSkeleton({ rows = 6 }: { rows?: number }) {
  const pulse = useRef(new Animated.Value(0.4)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 650, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0.4, duration: 650, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse]);
  return (
    <View testID="emp-skeleton">
      {Array.from({ length: rows }).map((_, i) => (
        <Animated.View key={i} style={[st.skelRow, { opacity: pulse }]}>
          <View style={st.skelAvatar} />
          <View style={{ flex: 1, gap: 8 }}>
            <View style={[st.skelBar, { width: "42%" }]} />
            <View style={[st.skelBar, { width: "68%", height: 8 }]} />
          </View>
          <View style={[st.skelBar, { width: 54, height: 22, borderRadius: 8 }]} />
        </Animated.View>
      ))}
    </View>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  card: {
    flexDirection: "row", alignItems: "center", gap: 10,
    flexGrow: 1, minWidth: 128, backgroundColor: colors.surfaceSecondary,
    borderRadius: 16, borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: 12, paddingVertical: 10, ...shadow.card,
  },
  icon: {
    width: 32, height: 32, borderRadius: 10,
    alignItems: "center", justifyContent: "center",
  },
  val: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  lbl: { fontSize: 9.5, color: colors.onSurfaceSecondary, marginTop: 1, fontWeight: "600" },
  skelRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: colors.surfaceSecondary, borderRadius: 16,
    borderWidth: 1, borderColor: colors.border, padding: 14, marginBottom: 8,
  },
  skelAvatar: { width: 42, height: 42, borderRadius: 21, backgroundColor: colors.surfaceTertiary },
  skelBar: { height: 11, borderRadius: 6, backgroundColor: colors.surfaceTertiary },
});
