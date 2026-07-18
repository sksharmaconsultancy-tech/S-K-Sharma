// Phase 2 — Enhanced compliance calendar with month navigation and
// completion tracking. Merges statutory deadlines + task due dates +
// tracked-document expiries.
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

type Ev = {
  key: string; date: string; title: string; kind: string;
  type: "statutory" | "task" | "document"; done: boolean;
  company_name?: string | null;
};

const KIND_COLORS: Record<string, string> = {
  EPFO: "#1D4ED8", ESIC: "#7C3AED", TDS: "#B45309", PT: "#0891B2",
  TASK: "#DB2777", DOC: "#C2410C",
};

function shiftMonth(month: string, delta: number): string {
  let y = parseInt(month.slice(0, 4), 10);
  let m = parseInt(month.slice(5, 7), 10) + delta;
  if (m === 0) { y -= 1; m = 12; }
  if (m === 13) { y += 1; m = 1; }
  return `${y}-${String(m).padStart(2, "0")}`;
}

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function CalendarPanel({ companyId }: { companyId: string | null }) {
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [events, setEvents] = useState<Ev[]>([]);
  const [today, setToday] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({ month });
      if (companyId) p.set("company_id", companyId);
      const r = await api<{ events: Ev[]; today: string }>(
        `/admin/portal-dashboard/calendar?${p.toString()}`);
      setEvents(r.events); setToday(r.today);
    } catch { /* noop */ }
    setLoading(false);
  }, [month, companyId]);

  useEffect(() => { load(); }, [load]);

  const toggle = async (ev: Ev) => {
    if (ev.type !== "statutory") return;
    try {
      await api("/admin/portal-dashboard/calendar/toggle", {
        method: "POST",
        body: { month, item_key: ev.key, company_id: companyId || null },
      });
      setEvents((prev) => prev.map((e) =>
        e.key === ev.key && e.type === "statutory" ? { ...e, done: !e.done } : e));
    } catch { /* noop */ }
  };

  const label = `${MONTH_NAMES[parseInt(month.slice(5, 7), 10) - 1]} ${month.slice(0, 4)}`;

  return (
    <View testID="pd-calendar-panel">
      <View style={st.monthBar}>
        <Pressable onPress={() => setMonth(shiftMonth(month, -1))} style={st.navBtn} testID="pd-cal-prev">
          <Ionicons name="chevron-back" size={16} color={colors.brandPrimary} />
        </Pressable>
        <Text style={st.monthTxt}>{label}</Text>
        <Pressable onPress={() => setMonth(shiftMonth(month, 1))} style={st.navBtn} testID="pd-cal-next">
          <Ionicons name="chevron-forward" size={16} color={colors.brandPrimary} />
        </Pressable>
      </View>
      <Text style={st.hint}>
        Statutory deadlines can be ticked ✓ once filed. Task due dates & document expiries are shown automatically.
      </Text>

      {loading ? (
        <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 24 }} />
      ) : events.length === 0 ? (
        <Text style={st.dim}>No events this month.</Text>
      ) : (
        events.map((e, i) => {
          const overdue = !e.done && e.date < today;
          const kc = KIND_COLORS[e.kind] || colors.brandPrimary;
          return (
            <Pressable key={`${e.type}-${e.key}-${i}`}
              onPress={() => toggle(e)}
              disabled={e.type !== "statutory"}
              style={[st.row, e.done && { opacity: 0.55 }]}
              testID={`pd-cal-ev-${e.key}`}>
              <View style={[st.dateBox, overdue && { backgroundColor: "#FEF2F2" }]}>
                <Text style={[st.dateDay, overdue && { color: "#B91C1C" }]}>{e.date.slice(8)}</Text>
                <Text style={[st.dateKind, { color: kc }]}>{e.kind}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[st.title, e.done && { textDecorationLine: "line-through" }]}
                  numberOfLines={2}>{e.title}</Text>
                {e.company_name ? <Text style={st.meta}>🏢 {e.company_name}</Text> : null}
                {overdue ? <Text style={st.overdueTxt}>OVERDUE</Text> : null}
              </View>
              {e.type === "statutory" ? (
                <View style={[st.checkbox, e.done && st.checkboxOn]}>
                  {e.done ? <Ionicons name="checkmark" size={13} color="#fff" /> : null}
                </View>
              ) : (
                <Ionicons
                  name={e.type === "task" ? "clipboard-outline" : "document-text-outline"}
                  size={15} color={colors.onSurfaceTertiary} />
              )}
            </Pressable>
          );
        })
      )}
    </View>
  );
}

const st = StyleSheet.create({
  dim: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 16, textAlign: "center" },
  monthBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 16,
    marginBottom: 6,
  },
  navBtn: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md,
    padding: 7, backgroundColor: colors.surface,
  },
  monthTxt: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface, minWidth: 110, textAlign: "center" },
  hint: { fontSize: 10, color: colors.onSurfaceTertiary, textAlign: "center", marginBottom: 10 },
  row: {
    flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: colors.surface,
    borderRadius: radius.lg, borderWidth: 1, borderColor: colors.divider,
    padding: 10, marginBottom: 7,
  },
  dateBox: {
    width: 46, alignItems: "center", backgroundColor: colors.background,
    borderRadius: radius.md, paddingVertical: 5,
  },
  dateDay: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  dateKind: { fontSize: 7.5, fontWeight: "800" },
  title: { fontSize: 12, fontWeight: "600", color: colors.onSurface },
  meta: { fontSize: 10, color: colors.onSurfaceSecondary, marginTop: 1 },
  overdueTxt: { fontSize: 9, fontWeight: "800", color: "#B91C1C", marginTop: 2 },
  checkbox: {
    width: 22, height: 22, borderRadius: 6, borderWidth: 1.5,
    borderColor: colors.divider, alignItems: "center", justifyContent: "center",
  },
  checkboxOn: { backgroundColor: "#16A34A", borderColor: "#16A34A" },
});
