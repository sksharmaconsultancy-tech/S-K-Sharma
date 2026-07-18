// Iter 180 — Compact monthly attendance calendar for the ESS home.
// Colors: present (green), half day (amber), absent (red tint),
// weekly off (grey), future (plain). Taps through to full History.
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { colors, shadow } from "@/src/theme";

type Cell = {
  present?: number; weekly_off?: boolean; anomaly?: boolean;
  punches?: number; hours?: number;
};
type MonthResp = {
  month: string;
  day_labels: string[];
  day_full_dates: string[];
  days: Record<string, Cell>;
  totals?: { present_days?: number };
};

const DOW = ["S", "M", "T", "W", "T", "F", "S"];

export default function MonthCalendarCard() {
  const router = useRouter();
  const [data, setData] = useState<MonthResp | null>(null);
  const month = new Date().toISOString().slice(0, 7);

  useEffect(() => {
    let alive = true;
    api<MonthResp>(`/attendance/my-month?month=${month}`)
      .then((r) => { if (alive) setData(r); })
      .catch(() => {});
    return () => { alive = false; };
  }, [month]);

  const today = new Date().toISOString().slice(0, 10);
  const first = new Date(`${month}-01T00:00:00`);
  const lead = first.getDay(); // 0=Sun
  const nDays = data?.day_full_dates?.length
    || new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();

  const cellFor = (i: number): { bg: string; fg: string } => {
    const date = data?.day_full_dates?.[i];
    const lbl = data?.day_labels?.[i];
    const c: Cell = (lbl && data?.days?.[lbl]) || {};
    const future = date ? date > today : false;
    if (future) return { bg: "transparent", fg: colors.onSurfaceTertiary };
    if ((c.present || 0) >= 1) return { bg: colors.success, fg: "#fff" };
    if ((c.present || 0) > 0) return { bg: colors.warning, fg: "#fff" };
    if (c.weekly_off) return { bg: colors.surfaceTertiary, fg: colors.onSurfaceTertiary };
    return { bg: `${colors.error}22`, fg: colors.error };
  };

  const monthLabel = first.toLocaleDateString("en-IN", { month: "long", year: "numeric" });

  return (
    <Pressable onPress={() => router.push("/history")} style={st.card} testID="ess-month-calendar">
      <View style={st.head}>
        <Text style={st.title}>📅 {monthLabel}</Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
          {data?.totals?.present_days != null ? (
            <Text style={st.presentTxt}>{data.totals.present_days} days present</Text>
          ) : null}
          <Ionicons name="chevron-forward" size={14} color={colors.onSurfaceTertiary} />
        </View>
      </View>
      <View style={st.dowRow}>
        {DOW.map((d, i) => <Text key={i} style={st.dow}>{d}</Text>)}
      </View>
      <View style={st.grid}>
        {Array.from({ length: lead }).map((_, i) => <View key={`x${i}`} style={st.cell} />)}
        {Array.from({ length: nDays }).map((_, i) => {
          const ui = cellFor(i);
          const date = data?.day_full_dates?.[i];
          const isToday = date === today;
          return (
            <View key={i} style={[st.cell, { backgroundColor: ui.bg },
              isToday && st.todayRing]}>
              <Text style={[st.cellTxt, { color: ui.fg }]}>{i + 1}</Text>
            </View>
          );
        })}
      </View>
      <View style={st.legend}>
        {[
          { c: colors.success, l: "Present" },
          { c: colors.warning, l: "Half" },
          { c: `${colors.error}55`, l: "Absent" },
          { c: colors.surfaceTertiary, l: "Week Off" },
        ].map((x) => (
          <View key={x.l} style={st.legendItem}>
            <View style={[st.legendDot, { backgroundColor: x.c }]} />
            <Text style={st.legendTxt}>{x.l}</Text>
          </View>
        ))}
      </View>
    </Pressable>
  );
}

const CELL = 100 / 7;
const st = StyleSheet.create({
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 16,
    borderWidth: 1, borderColor: colors.border, padding: 14,
    ...shadow.card,
  },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 },
  title: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  presentTxt: { fontSize: 10.5, fontWeight: "700", color: colors.success },
  dowRow: { flexDirection: "row", marginBottom: 4 },
  dow: {
    width: `${CELL}%`, textAlign: "center", fontSize: 9,
    fontWeight: "800", color: colors.onSurfaceTertiary,
  },
  grid: { flexDirection: "row", flexWrap: "wrap" },
  cell: {
    width: `${CELL}%`, aspectRatio: 1.15, alignItems: "center",
    justifyContent: "center", borderRadius: 8, marginVertical: 1,
  },
  todayRing: { borderWidth: 1.5, borderColor: colors.brandPrimary },
  cellTxt: { fontSize: 10.5, fontWeight: "700" },
  legend: { flexDirection: "row", gap: 12, marginTop: 10, flexWrap: "wrap" },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  legendDot: { width: 9, height: 9, borderRadius: 3 },
  legendTxt: { fontSize: 9.5, color: colors.onSurfaceSecondary, fontWeight: "600" },
});
