/**
 * Iter 709 — lightweight READ-ONLY chart primitives (no extra deps).
 * HBar (horizontal bars), TrendLine (svg polyline), Donut (svg arcs),
 * StackedBars (two-segment monthly bars), KpiCard.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import Svg, { Polyline, Circle, Line as SvgLine, Text as SvgText } from "react-native-svg";

import { colors } from "@/src/theme";

export const PALETTE = ["#2563EB", "#059669", "#D97706", "#DC2626", "#7C3AED",
  "#0D9488", "#DB2777", "#4338CA", "#B45309", "#64748B", "#0369A1", "#16A34A"];

export const fmtMoney = (v: number) =>
  v >= 10000000 ? `₹${(v / 10000000).toFixed(2)} Cr`
    : v >= 100000 ? `₹${(v / 100000).toFixed(2)} L`
    : v >= 1000 ? `₹${(v / 1000).toFixed(1)} K` : `₹${Math.round(v)}`;

export function KpiCard({ label, value, tint }: { label: string; value: string; tint?: string }) {
  return (
    <View style={[s.kpi, tint ? { borderTopColor: tint, borderTopWidth: 3 } : null]}>
      <Text style={s.kpiVal}>{value}</Text>
      <Text style={s.kpiLbl}>{label}</Text>
    </View>
  );
}

export function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={s.card}>
      <Text style={s.cardT}>{title}</Text>
      {children}
    </View>
  );
}

export function HBar({ data, money = false }: {
  data: { label: string; value: number }[]; money?: boolean }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  if (!data.length) return <Text style={s.empty}>No data</Text>;
  return (
    <View style={{ gap: 7 }}>
      {data.map((d, i) => (
        <View key={`${d.label}-${i}`}>
          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
            <Text style={s.barLbl} numberOfLines={1}>{d.label}</Text>
            <Text style={s.barVal}>{money ? fmtMoney(d.value) : d.value}</Text>
          </View>
          <View style={s.barTrack}>
            <View style={[s.barFill, {
              width: `${Math.max(2, (d.value / max) * 100)}%`,
              backgroundColor: PALETTE[i % PALETTE.length] }]} />
          </View>
        </View>
      ))}
    </View>
  );
}

export function TrendLine({ points, labels, money = false, color = "#2563EB" }: {
  points: number[]; labels: string[]; money?: boolean; color?: string }) {
  const W = 320, H = 130, P = 8;
  if (!points.length || points.every((p) => !p)) return <Text style={s.empty}>No data</Text>;
  const max = Math.max(...points, 1), min = Math.min(...points, 0);
  const x = (i: number) => P + (i * (W - 2 * P)) / Math.max(1, points.length - 1);
  const y = (v: number) => H - P - ((v - min) / Math.max(1, max - min)) * (H - 2 * P);
  const pts = points.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  return (
    <View>
      <Svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`}>
        {[0.25, 0.5, 0.75].map((f) => (
          <SvgLine key={f} x1={P} x2={W - P} y1={H * f} y2={H * f}
            stroke={colors.border} strokeWidth={0.6} />
        ))}
        <Polyline points={pts} fill="none" stroke={color} strokeWidth={2.5} />
        {points.map((v, i) => (
          <Circle key={i} cx={x(i)} cy={y(v)} r={3.4} fill={color} />
        ))}
        <SvgText x={P} y={12} fontSize={9} fill={colors.onSurfaceTertiary}>
          {money ? fmtMoney(max) : String(max)}
        </SvgText>
      </Svg>
      <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
        {labels.map((l, i) => (
          <Text key={i} style={s.axisLbl}>{l.slice(5)}</Text>
        ))}
      </View>
    </View>
  );
}

export function Donut({ data, money = false }: {
  data: { label: string; value: number }[]; money?: boolean }) {
  const total = data.reduce((a, d) => a + d.value, 0);
  if (!total) return <Text style={s.empty}>No data</Text>;
  const R = 44, C = 2 * Math.PI * R;
  let acc = 0;
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
      <Svg width={110} height={110} viewBox="0 0 110 110">
        {data.map((d, i) => {
          const frac = d.value / total;
          const dash = `${frac * C} ${C}`;
          const off = -acc * C;
          acc += frac;
          return (
            <Circle key={i} cx={55} cy={55} r={R} fill="none"
              stroke={PALETTE[i % PALETTE.length]} strokeWidth={16}
              strokeDasharray={dash} strokeDashoffset={off}
              transform="rotate(-90 55 55)" />
          );
        })}
      </Svg>
      <View style={{ flex: 1, minWidth: 130, gap: 4 }}>
        {data.map((d, i) => (
          <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <View style={{ width: 9, height: 9, borderRadius: 3, backgroundColor: PALETTE[i % PALETTE.length] }} />
            <Text style={[s.barLbl, { flex: 1 }]} numberOfLines={1}>{d.label}</Text>
            <Text style={s.barVal}>
              {money ? fmtMoney(d.value) : d.value} ({Math.round((d.value / total) * 100)}%)
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}

export function StackedBars({ data, keys, colorsArr, money = true }: {
  data: { label: string; a: number; b: number }[];
  keys: [string, string]; colorsArr?: [string, string]; money?: boolean }) {
  const [cA, cB] = colorsArr || ["#059669", "#DC2626"];
  const max = Math.max(1, ...data.map((d) => d.a + d.b));
  if (!data.length) return <Text style={s.empty}>No data</Text>;
  return (
    <View>
      <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 10, height: 130 }}>
        {data.map((d, i) => (
          <View key={i} style={{ flex: 1, alignItems: "center", justifyContent: "flex-end", height: "100%" }}>
            <View style={{ width: "72%", justifyContent: "flex-end" }}>
              <View style={{ height: Math.max(2, (d.b / max) * 110), backgroundColor: cB, borderTopLeftRadius: 3, borderTopRightRadius: 3 }} />
              <View style={{ height: Math.max(2, (d.a / max) * 110), backgroundColor: cA }} />
            </View>
            <Text style={s.axisLbl}>{d.label.slice(5)}</Text>
          </View>
        ))}
      </View>
      <View style={{ flexDirection: "row", gap: 14, marginTop: 6 }}>
        {[[keys[0], cA], [keys[1], cB]].map(([k, c]) => (
          <View key={k as string} style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
            <View style={{ width: 9, height: 9, borderRadius: 3, backgroundColor: c as string }} />
            <Text style={s.barLbl}>{k}</Text>
          </View>
        ))}
        {money ? <Text style={[s.axisLbl, { marginLeft: "auto" }]}>max {fmtMoney(max)}</Text> : null}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  kpi: {
    minWidth: 100, flexGrow: 1, backgroundColor: colors.surfaceSecondary,
    borderRadius: 12, borderWidth: 1, borderColor: colors.border,
    paddingVertical: 12, paddingHorizontal: 12,
  },
  kpiVal: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  kpiLbl: { fontSize: 10.5, fontWeight: "700", color: colors.onSurfaceTertiary, marginTop: 2 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 14, padding: 14,
    borderWidth: 1, borderColor: colors.border, marginBottom: 12,
  },
  cardT: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  empty: { fontSize: 12, color: colors.onSurfaceTertiary, paddingVertical: 12 },
  barLbl: { fontSize: 11.5, color: colors.onSurfaceSecondary, fontWeight: "600" },
  barVal: { fontSize: 11.5, fontWeight: "800", color: colors.onSurface },
  barTrack: { height: 9, borderRadius: 5, backgroundColor: colors.surfaceTertiary, marginTop: 3, overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 5 },
  axisLbl: { fontSize: 9, color: colors.onSurfaceTertiary, marginTop: 3 },
});
