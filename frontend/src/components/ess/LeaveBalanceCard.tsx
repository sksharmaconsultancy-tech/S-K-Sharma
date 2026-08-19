/**
 * Iter 615 (ESS Phase 2) — Leave Balance card on the employee home screen.
 * Shows current-year CL / PL balances from GET /leaves/balance. Hidden
 * entirely when the firm has no CL/PL policy and nothing was taken.
 */
import React, { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, shadow, spacing } from "@/src/theme";

type Balance = {
  year: number;
  cl_pl_applicable: boolean;
  enforced: boolean;
  cl_allowed: number; cl_taken: number; cl_balance: number;
  pl_allowed: number; pl_taken: number; pl_balance: number;
  other_taken: number;
};

export default function LeaveBalanceCard() {
  const router = useRouter();
  const [d, setD] = useState<Balance | null>(null);

  useEffect(() => {
    api<Balance>("/leaves/balance").then(setD).catch(() => setD(null));
  }, []);

  if (!d) return null;
  const relevant = d.cl_pl_applicable || d.enforced || d.cl_allowed > 0 ||
    d.pl_allowed > 0 || d.cl_taken > 0 || d.pl_taken > 0;
  if (!relevant) return null;

  return (
    <Pressable
      style={s.card}
      onPress={() => router.push("/leaves")}
      testID="ess-leave-balance-card"
    >
      <View style={s.headRow}>
        <Ionicons name="calendar-outline" size={16} color={colors.brandPrimary} />
        <Text style={s.title}>Leave Balance · {d.year}</Text>
        <View style={{ flex: 1 }} />
        <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
      </View>
      <View style={s.row}>
        <View style={s.pill}>
          <Text style={s.pillBig}>{d.cl_balance}</Text>
          <Text style={s.pillLabel}>CL left</Text>
          <Text style={s.pillSub}>of {d.cl_allowed} · taken {d.cl_taken}</Text>
        </View>
        <View style={s.pill}>
          <Text style={s.pillBig}>{d.pl_balance}</Text>
          <Text style={s.pillLabel}>PL left</Text>
          <Text style={s.pillSub}>of {d.pl_allowed} · taken {d.pl_taken}</Text>
        </View>
        {d.other_taken > 0 ? (
          <View style={s.pill}>
            <Text style={s.pillBig}>{d.other_taken}</Text>
            <Text style={s.pillLabel}>Other</Text>
            <Text style={s.pillSub}>days taken</Text>
          </View>
        ) : null}
      </View>
    </Pressable>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.borderLight, padding: spacing.md, gap: 10,
    marginBottom: spacing.sm, ...shadow.sm,
  },
  headRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  row: { flexDirection: "row", gap: 8 },
  pill: {
    flex: 1, backgroundColor: colors.background, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.borderLight,
    paddingVertical: 10, alignItems: "center", gap: 1,
  },
  pillBig: { fontSize: 20, fontWeight: "800", color: colors.brandPrimary },
  pillLabel: { fontSize: 11.5, fontWeight: "700", color: colors.onSurface },
  pillSub: { fontSize: 10, color: colors.onSurfaceTertiary },
});
