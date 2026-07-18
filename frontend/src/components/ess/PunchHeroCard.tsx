// Iter 180 — Glassmorphic main attendance card: live clock, punch
// status, working hours, shift window and the primary punch CTA.
import React, { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, radius, shadow } from "@/src/theme";

type Rec = { kind: string; at?: string; created_at?: string; status?: string };

function recTime(r: Rec): Date | null {
  const v = r.at || r.created_at;
  if (!v) return null;
  const d = new Date(v);
  return isNaN(d.getTime()) ? null : d;
}

function fmtHM(mins: number): string {
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

export default function PunchHeroCard({
  records, shiftStart, shiftEnd, punchingEnabled, onPunch,
}: {
  records: Rec[];
  shiftStart?: string | null;
  shiftEnd?: string | null;
  punchingEnabled: boolean;
  onPunch: () => void;
}) {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const nowMin = now.getMinutes();
  const { punchedIn, firstIn, lastOut, workedMins } = useMemo(() => {
    const recs = (records || []).filter((r) => r.status !== "rejected");
    const last = recs[recs.length - 1];
    const isIn = last?.kind === "in";
    let fIn: Date | null = null;
    let lOut: Date | null = null;
    let mins = 0;
    let openIn: Date | null = null;
    for (const r of recs) {
      const t = recTime(r);
      if (!t) continue;
      if (r.kind === "in") {
        if (!fIn) fIn = t;
        openIn = t;
      } else if (r.kind === "out") {
        lOut = t;
        if (openIn) {
          mins += (t.getTime() - openIn.getTime()) / 60000;
          openIn = null;
        }
      }
    }
    if (openIn) mins += (Date.now() - openIn.getTime()) / 60000;
    return { punchedIn: isIn, firstIn: fIn, lastOut: lOut, workedMins: Math.max(0, mins) };
  }, [records, nowMin]);

  const statusLabel = punchedIn ? "Working now" : (records || []).length ? "Shift complete" : "Not punched in";
  const statusColor = punchedIn ? colors.success : (records || []).length ? colors.brandPrimary : colors.warning;
  const timeStr = now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  return (
    <View style={st.card} testID="hero-shift">
      {/* live clock + status */}
      <View style={st.topRow}>
        <View>
          <Text style={st.clock}>{timeStr}</Text>
          <View style={st.statusRow}>
            <View style={[st.statusDot, { backgroundColor: statusColor }]} />
            <Text style={[st.statusTxt, { color: statusColor }]}>{statusLabel}</Text>
          </View>
        </View>
        {punchingEnabled ? (
          <Pressable onPress={onPunch} testID="hero-punch-cta"
            style={({ pressed }) => [st.punchBtn,
              punchedIn && { backgroundColor: colors.error },
              pressed && { transform: [{ scale: 0.96 }] }]}>
            <Ionicons name="finger-print" size={22} color="#fff" />
            <Text style={st.punchTxt}>{punchedIn ? "Punch Out" : "Punch In"}</Text>
          </Pressable>
        ) : (
          <View style={st.viewOnly}>
            <Ionicons name="eye-outline" size={15} color={colors.onSurfaceTertiary} />
            <Text style={st.viewOnlyTxt}>View only</Text>
          </View>
        )}
      </View>

      <View style={st.divider} />

      {/* metrics strip */}
      <View style={st.metricsRow}>
        <View style={st.metric}>
          <Text style={st.metricVal}>
            {firstIn ? firstIn.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) : "--:--"}
          </Text>
          <Text style={st.metricLbl}>Punch In</Text>
        </View>
        <View style={st.metricDiv} />
        <View style={st.metric}>
          <Text style={st.metricVal}>
            {lastOut && !punchedIn
              ? lastOut.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })
              : "--:--"}
          </Text>
          <Text style={st.metricLbl}>Punch Out</Text>
        </View>
        <View style={st.metricDiv} />
        <View style={st.metric}>
          <Text style={[st.metricVal, { color: colors.brandPrimary }]}>{fmtHM(workedMins)}</Text>
          <Text style={st.metricLbl}>Working Hrs</Text>
        </View>
        <View style={st.metricDiv} />
        <View style={st.metric}>
          <Text style={st.metricVal}>
            {shiftStart && shiftEnd ? `${shiftStart}–${shiftEnd}` : "—"}
          </Text>
          <Text style={st.metricLbl}>Shift</Text>
        </View>
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  card: {
    borderRadius: 16,
    padding: 16,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    ...(Platform.OS === "web"
      ? ({ backdropFilter: "blur(12px)" } as any)
      : null),
    ...shadow.card,
  },
  topRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  clock: {
    fontSize: 26, fontWeight: "800", color: colors.onSurface,
    fontVariant: ["tabular-nums"] as any, letterSpacing: 0.5,
  },
  statusRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  statusTxt: { fontSize: 11.5, fontWeight: "800" },
  punchBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.brandPrimary, borderRadius: 14,
    paddingHorizontal: 18, paddingVertical: 13, minHeight: 48,
    ...shadow.cta,
  },
  punchTxt: { fontSize: 14, fontWeight: "800", color: "#fff" },
  viewOnly: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 10,
  },
  viewOnlyTxt: { fontSize: 12, color: colors.onSurfaceTertiary, fontWeight: "700" },
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: colors.divider, marginVertical: 14 },
  metricsRow: { flexDirection: "row", alignItems: "center" },
  metric: { flex: 1, alignItems: "center" },
  metricDiv: { width: StyleSheet.hairlineWidth, height: 26, backgroundColor: colors.divider },
  metricVal: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  metricLbl: { fontSize: 9.5, color: colors.onSurfaceTertiary, marginTop: 3, fontWeight: "600" },
});
