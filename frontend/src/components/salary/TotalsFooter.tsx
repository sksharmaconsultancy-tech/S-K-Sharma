/**
 * TotalsFooter — sticky enterprise footer summary for the salary process
 * screens. Shows run totals (Gross / PF / ESIC / PT / Advance / Net …) in
 * a horizontally scrollable strip pinned to the bottom of the screen.
 */
import React from "react";
import { View, Text, StyleSheet, ScrollView } from "react-native";

import { colors } from "@/src/theme";

export type TotalItem = { label: string; value: number | string; tone?: string };

function fmt(v: number | string): string {
  if (typeof v === "string") return v;
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `₹${Math.round(v)}`;
}

export default function TotalsFooter({ items }: { items: TotalItem[] }) {
  if (!items.length) return null;
  return (
    <View style={st.wrap} testID="totals-footer">
      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        contentContainerStyle={st.row}>
        {items.map((it) => (
          <View key={it.label} style={st.item}>
            <Text style={st.label} numberOfLines={1}>{it.label}</Text>
            <Text style={[st.value, it.tone ? { color: it.tone } : null]} numberOfLines={1}>
              {fmt(it.value)}
            </Text>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: {
    borderTopWidth: 1, borderTopColor: colors.border ?? "#E2E8F0",
    backgroundColor: colors.surfaceSecondary ?? "#FFFFFF",
    paddingVertical: 8, paddingHorizontal: 12,
  },
  row: { gap: 18, alignItems: "center", paddingRight: 12 },
  item: { minWidth: 86 },
  label: { fontSize: 10, fontWeight: "700", color: colors.textSecondary, textTransform: "uppercase" },
  value: { fontSize: 14.5, fontWeight: "800", color: colors.textPrimary, marginTop: 1 },
});
