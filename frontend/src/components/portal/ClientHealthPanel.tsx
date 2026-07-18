// Phase 2 — Client Health Scores panel.
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

type Factor = { label: string; score: number; max: number; detail: string };
type Client = {
  company_id: string; name: string; score: number; grade: string;
  employees: number; factors: Factor[];
};

const GRADE_UI: Record<string, { fg: string; bg: string }> = {
  A: { fg: "#16A34A", bg: "#F0FDF4" },
  B: { fg: "#0369A1", bg: "#F0F9FF" },
  C: { fg: "#B45309", bg: "#FFFBEB" },
  D: { fg: "#B91C1C", bg: "#FEF2F2" },
};

export default function ClientHealthPanel() {
  const [clients, setClients] = useState<Client[]>([]);
  const [month, setMonth] = useState("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ month: string; clients: Client[] }>(
        "/admin/portal-dashboard/client-health");
      setClients(r.clients); setMonth(r.month);
    } catch { /* noop */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 24 }} />;

  return (
    <View testID="pd-client-health-panel">
      <Text style={st.head}>
        Health scores for {month} — payroll status, attendance, approvals, tickets & document expiry.
      </Text>
      {clients.length === 0 ? <Text style={st.dim}>No firms.</Text> : null}
      {clients.map((c) => {
        const gui = GRADE_UI[c.grade] || GRADE_UI.D;
        const expanded = open === c.company_id;
        return (
          <Pressable key={c.company_id}
            onPress={() => setOpen(expanded ? null : c.company_id)}
            style={st.card} testID={`pd-health-${c.company_id}`}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
              <View style={[st.gradeBadge, { backgroundColor: gui.bg }]}>
                <Text style={[st.gradeTxt, { color: gui.fg }]}>{c.grade}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={st.name} numberOfLines={1}>{c.name}</Text>
                <Text style={st.meta}>{c.employees} active employees</Text>
              </View>
              <View style={{ alignItems: "flex-end" }}>
                <Text style={[st.score, { color: gui.fg }]}>{c.score}</Text>
                <Text style={st.meta}>/ 100</Text>
              </View>
              <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={15}
                color={colors.onSurfaceTertiary} />
            </View>
            {/* score bar */}
            <View style={st.barBg}>
              <View style={[st.barFg, { width: `${c.score}%`, backgroundColor: gui.fg }]} />
            </View>
            {expanded ? (
              <View style={{ marginTop: 10, gap: 6 }}>
                {c.factors.map((f, i) => (
                  <View key={i} style={st.factorRow}>
                    <Text style={st.factorLbl} numberOfLines={1}>{f.label}</Text>
                    <Text style={st.factorDetail} numberOfLines={1}>{f.detail}</Text>
                    <Text style={[st.factorScore,
                      { color: f.score >= f.max * 0.7 ? "#16A34A" : f.score >= f.max * 0.4 ? "#B45309" : "#B91C1C" }]}>
                      {f.score}/{f.max}
                    </Text>
                  </View>
                ))}
              </View>
            ) : null}
          </Pressable>
        );
      })}
    </View>
  );
}

const st = StyleSheet.create({
  head: { fontSize: 11, color: colors.onSurfaceSecondary, marginBottom: 10 },
  dim: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 16, textAlign: "center" },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.divider, padding: 12, marginBottom: 8,
  },
  gradeBadge: {
    width: 38, height: 38, borderRadius: 10, alignItems: "center", justifyContent: "center",
  },
  gradeTxt: { fontSize: 17, fontWeight: "900" },
  name: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  meta: { fontSize: 10, color: colors.onSurfaceSecondary, marginTop: 1 },
  score: { fontSize: 18, fontWeight: "800" },
  barBg: {
    height: 5, backgroundColor: colors.background, borderRadius: 3,
    overflow: "hidden", marginTop: 10,
  },
  barFg: { height: 5, borderRadius: 3 },
  factorRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  factorLbl: { fontSize: 11, fontWeight: "600", color: colors.onSurface, flex: 1.1 },
  factorDetail: { fontSize: 10.5, color: colors.onSurfaceSecondary, flex: 1, textAlign: "right" },
  factorScore: { fontSize: 11, fontWeight: "800", width: 44, textAlign: "right" },
});
