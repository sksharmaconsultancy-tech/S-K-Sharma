/**
 * Iter 484 — Firm Master → 16. AI Compliance Health Dashboard.
 * Client-side configuration health checks over the loaded master + link to
 * the full AI Salary Compliance engine.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { colors, spacing } from "@/src/theme";
import { Card } from "./primitives";

export default function HealthSection({ master }: { master: any }) {
  const router = useRouter();
  const g = master.general || {};
  const epf = master.epf || {};
  const esi = master.esi || {};
  const bank = master.bank || {};
  const st_ = master.settings || {};

  const soon = new Date(); soon.setDate(soon.getDate() + 60);
  const soonIso = soon.toISOString().slice(0, 10);
  const today = new Date().toISOString().slice(0, 10);
  const docs = (master.compliance_docs || []).filter((d: any) => (d.number || "").trim());
  const expiring = (master.compliance_docs || []).filter(
    (d: any) => d.expiry_date && d.expiry_date >= today && d.expiry_date <= soonIso);
  const expired = (master.compliance_docs || []).filter(
    (d: any) => d.expiry_date && d.expiry_date < today);

  const checks: { label: string; ok: boolean; warn?: boolean; detail?: string }[] = [
    { label: "Company identity complete", ok: !!(g.company_name || "").trim() && !!(g.company_code || "").trim() },
    { label: "Company logo uploaded", ok: !!master.logo?.image_base64 },
    { label: "EPF registration configured", ok: !!epf.applicable && !!(epf.epf_no || "").trim(),
      detail: epf.applicable ? undefined : "EPF marked not applicable" },
    { label: "ESI registration configured", ok: !!esi.applicable && !!(esi.esi_no || "").trim(),
      detail: esi.applicable ? undefined : "ESI marked not applicable" },
    { label: "Bank details filled", ok: !!(bank.account_no || "").trim() && !!(bank.ifsc || "").trim() },
    { label: "Attendance policy selected", ok: !!st_.attendance_policy_preset },
    { label: `Compliance documents on file (${docs.length})`, ok: docs.length > 0 },
    { label: "No documents expired", ok: expired.length === 0,
      detail: expired.length ? `${expired.length} document(s) EXPIRED` : undefined },
    { label: "No documents expiring in 60 days", ok: expiring.length === 0, warn: true,
      detail: expiring.length ? `${expiring.length} document(s) expiring soon` : undefined },
  ];
  const okCount = checks.filter((c) => c.ok).length;
  const score = Math.round((okCount / checks.length) * 100);
  const scoreColor = score >= 80 ? "#059669" : score >= 50 ? "#D97706" : "#DC2626";

  return (
    <View style={{ gap: spacing.md }}>
      <Card icon="pulse" title="Compliance Health Dashboard"
            subtitle="Automatic configuration health checks for this firm">
        <View style={st.scoreRow}>
          <View style={[st.scoreCircle, { borderColor: scoreColor }]}>
            <Text style={[st.scoreTxt, { color: scoreColor }]}>{score}%</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={st.scoreTitle}>
              {score >= 80 ? "Healthy configuration" : score >= 50 ? "Needs attention" : "Configuration incomplete"}
            </Text>
            <Text style={st.mute}>{okCount} of {checks.length} checks passing</Text>
          </View>
        </View>
        {checks.map((c) => (
          <View key={c.label} style={st.checkRow}>
            <Ionicons
              name={c.ok ? "checkmark-circle" : c.warn ? "alert-circle" : "close-circle"}
              size={16}
              color={c.ok ? "#059669" : c.warn ? "#D97706" : "#DC2626"} />
            <Text style={[st.checkTxt, !c.ok && { fontWeight: "700" }]}>
              {c.label}{!c.ok && c.detail ? <Text style={st.mute}>  — {c.detail}</Text> : null}
            </Text>
          </View>
        ))}
      </Card>
      <Card icon="sparkles" title="AI Salary Compliance Engine" accent="#7C3AED">
        <Text style={st.mute}>
          Run the full AI engine to validate salary registers, PF/ESIC wage
          bases and statutory deductions against the latest rules.
        </Text>
        <Pressable onPress={() => router.push("/ai-salary-compliance" as any)} style={st.aiBtn}>
          <Ionicons name="sparkles" size={14} color="#FFF" />
          <Text style={st.aiBtnTxt}>Open AI Salary Compliance</Text>
        </Pressable>
      </Card>
    </View>
  );
}

const st = StyleSheet.create({
  scoreRow: { flexDirection: "row", alignItems: "center", gap: 14, marginBottom: 6 },
  scoreCircle: {
    width: 74, height: 74, borderRadius: 37, borderWidth: 5,
    alignItems: "center", justifyContent: "center",
  },
  scoreTxt: { fontSize: 17, fontWeight: "900" },
  scoreTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  mute: { fontSize: 11.5, color: colors.onSurfaceTertiary },
  checkRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 },
  checkTxt: { fontSize: 12.5, color: colors.onSurface, flex: 1 },
  aiBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    backgroundColor: "#7C3AED", borderRadius: 8, paddingHorizontal: 14, paddingVertical: 9,
    marginTop: 8,
  },
  aiBtnTxt: { fontSize: 12.5, fontWeight: "800", color: "#FFF" },
});
