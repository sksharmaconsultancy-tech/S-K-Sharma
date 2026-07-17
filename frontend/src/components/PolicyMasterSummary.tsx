/**
 * Iter 175 — Read-only summary of the firm's Attendance Policy Master
 * (core rules + Policy Master Sub Points) shown inside Firm Master, linked
 * to the Attendance Policy Master screen.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

const CAP = (s: any) => {
  const v = String(s ?? "").trim();
  return v ? v.charAt(0).toUpperCase() + v.slice(1) : "—";
};
const YN = (v: any) => (v ? "Yes" : "No");

export default function PolicyMasterSummary({ companyId }: { companyId: string | null }) {
  const router = useRouter();
  const [policy, setPolicy] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    api<any>(`/attendance/policy?company_id=${encodeURIComponent(companyId)}`)
      .then((r) => setPolicy(r.policy || r))
      .catch(() => setPolicy(null))
      .finally(() => setLoading(false));
  }, [companyId]);

  if (!companyId) return null;
  if (loading) return <ActivityIndicator size="small" color={colors.brandPrimary} />;
  if (!policy) return null;

  const pm = policy.policy_master || {};
  const punchTypes = (Array.isArray(pm.punch_types) ? pm.punch_types : [])
    .map((p: string) => (p === "gps" ? "GPS" : CAP(p))).join(", ") || "Biometric";
  const weekOff = (policy.weekly_off_days || [])
    .map((d: number) => ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d]).join(", ") || "None";

  const rows: [string, string][] = [
    ["Attendance Basis", CAP(pm.attendance_basis || "monthly")],
    ["Shift Type", CAP(pm.shift_type || "fixed")],
    ["Punch Type", punchTypes],
    ["Grace Time", `${policy.grace_minutes_late ?? 0} min`],
    ["Half-Day Rule", `< ${policy.half_day_hours ?? 4} hrs`],
    ["Full-Day / Late Mark", `${policy.full_day_hours ?? 8} hrs · grace ${policy.grace_minutes_late ?? 0}m`],
    ["OT Rule", `after ${policy.overtime_threshold_hours ?? 8} hrs × ${policy.overtime_multiplier ?? 1}`],
    ["Weekly Off", weekOff],
    ["Contractor Required", YN(pm.contractor_assignment_required)],
    ["Site-wise Attendance", YN(pm.site_wise_attendance)],
    ["Client-wise Attendance", YN(pm.client_wise_attendance)],
    ["Multiple Punch", YN(pm.multiple_punch_allowed !== false)],
    ["Auto Shift Detection", YN(pm.auto_shift_detection)],
    ["WFH Allowed", YN(pm.wfh_allowed)],
    ["Geo-fencing Required", YN(pm.geofencing_required !== false)],
  ];

  return (
    <View style={st.box} testID="fm-policy-summary">
      <View style={st.head}>
        <Text style={st.title}>Attendance Policy Master — set points</Text>
        <Pressable
          onPress={() => router.push("/attendance-policy")}
          style={st.linkBtn}
          testID="fm-open-policy-master"
        >
          <Ionicons name="open-outline" size={12} color={colors.brandPrimary} />
          <Text style={st.linkTxt}>Open Policy Master</Text>
        </Pressable>
      </View>
      <View style={st.grid}>
        {rows.map(([k, v]) => (
          <View key={k} style={st.cell}>
            <Text style={st.k}>{k}</Text>
            <Text style={st.v}>{v}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  box: {
    marginTop: 10,
    backgroundColor: colors.background,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.divider,
    padding: 10,
  },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  title: { fontSize: 11.5, fontWeight: "800", color: colors.onSurfaceSecondary },
  linkBtn: { flexDirection: "row", alignItems: "center", gap: 4 },
  linkTxt: { fontSize: 11, fontWeight: "700", color: colors.brandPrimary },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  cell: { minWidth: 150, flexGrow: 1, flexBasis: "30%" },
  k: { fontSize: 10, color: colors.onSurfaceTertiary, fontWeight: "700" },
  v: { fontSize: 11.5, color: colors.onSurface, fontWeight: "600" },
});
