/**
 * Employee Rejoin (Rehire) Wizard — Iter 475.
 *
 * Re-activates a separated employee (resigned / terminated / retired /
 * absconded / contract completed) WITHOUT losing any history:
 *   A. Previous employment details (read-only reference)
 *   B. New employment details (rejoin date, reason, revised role/salary)
 *   C. Service summary (previous service · gap · new period)
 *   D. Full employment history (all periods)
 *
 * UAN / ESIC IP always CONTINUE (never re-issued). Employee-code, leave
 * and gratuity behaviour follow the Firm-Master rejoin policy.
 *
 * Backend: GET /admin/employees/{id}/rejoin-info · POST .../rejoin
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, TextInput,
  ActivityIndicator, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

const alertUser = (title: string, msg: string) => {
  if (Platform.OS === "web") window.alert(`${title}\n\n${msg}`);
  else Alert.alert(title, msg);
};

const REASONS = ["Rehired — performance", "Business requirement",
  "Seasonal work resumed", "Contract renewed", "Returned after break",
  "Transferred back", "Other"];

export default function EmployeeRejoinScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const params = useLocalSearchParams<{ user_id?: string }>();
  const userId = String(params.user_id || "");
  const isAdmin = ["super_admin", "company_admin", "sub_admin"].includes(user?.role || "");

  const [info, setInfo] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Section B form
  const [rejoinDate, setRejoinDate] = useState("");
  const [reason, setReason] = useState("");
  const [department, setDepartment] = useState("");
  const [designation, setDesignation] = useState("");
  const [employeeType, setEmployeeType] = useState("");
  const [salaryMonthly, setSalaryMonthly] = useState("");
  const [complianceBasic, setComplianceBasic] = useState("");
  const [complianceGross, setComplianceGross] = useState("");
  const [leaveOpening, setLeaveOpening] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await api<any>(`/admin/employees/${userId}/rejoin-info`);
      setInfo(r);
      setDepartment(r?.previous?.department || "");
      setDesignation(r?.previous?.designation || "");
      setEmployeeType(r?.previous?.employee_type || "");
      const today = new Date().toISOString().slice(0, 10);
      setRejoinDate(today);
    } catch (e: any) {
      setError(e?.message || "Failed to load employee");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => { if (userId && isAdmin) load(); }, [userId, isAdmin, load]);

  const submit = async () => {
    if (!rejoinDate.trim()) return alertUser("Required", "Enter the Rejoin Date (YYYY-MM-DD).");
    if (!reason.trim()) return alertUser("Required", "Select or enter a Rejoin Reason.");
    setSaving(true);
    try {
      const body: any = { rejoin_date: rejoinDate.trim(), rejoin_reason: reason.trim() };
      if (department.trim()) body.department = department.trim();
      if (designation.trim()) body.designation = designation.trim();
      if (employeeType.trim()) body.employee_type = employeeType.trim();
      if (salaryMonthly.trim()) body.salary_monthly = Number(salaryMonthly);
      if (complianceBasic.trim()) body.compliance_basic = Number(complianceBasic);
      if (complianceGross.trim()) body.compliance_gross = Number(complianceGross);
      if (leaveOpening.trim()) body.leave_opening_balance = Number(leaveOpening);
      const r = await api<any>(`/admin/employees/${userId}/rejoin`, {
        method: "POST", body,
      });
      alertUser("Rejoined ✅", r.message || "Employee rejoined successfully.");
      router.back();
    } catch (e: any) {
      alertUser("Rejoin failed", e?.message || "Please check the details and retry.");
    } finally {
      setSaving(false);
    }
  };

  if (!isAdmin) {
    return (
      <SafeAreaView style={styles.safe}><Text style={styles.err}>Admin access only.</Text></SafeAreaView>
    );
  }

  const P = info?.previous || {};
  const S = info?.service || {};
  const policy = info?.policy || {};
  const history = info?.employment_history || [];

  const ro = (label: string, value: any) => (
    <View style={styles.roRow} key={label}>
      <Text style={styles.roLabel}>{label}</Text>
      <Text style={styles.roValue}>{value != null && String(value).trim() !== "" ? String(value) : "—"}</Text>
    </View>
  );

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="rejoin-back">
          <Ionicons name="arrow-back" size={20} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Rejoin Employee</Text>
      </View>
      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
      ) : error ? (
        <Text style={styles.err}>{error}</Text>
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 60 }}>
          {!info?.eligible && (
            <View style={styles.warnBox}>
              <Text style={styles.warnTxt}>
                This employee is ACTIVE — only a separated employee (resigned /
                terminated / retired / absconded / contract completed) can be rejoined.
              </Text>
            </View>
          )}

          {/* A — previous employment (read-only) */}
          <Text style={styles.section}>A · Previous Employment (read-only)</Text>
          <View style={styles.card} testID="rejoin-previous-card">
            {ro("Employee Code", P.employee_code)}
            {ro("Name", P.name)}
            {ro("Previous DOJ", P.doj)}
            {ro("Last Working Date", P.last_working_date)}
            {ro("Separation Reason", P.separation_reason)}
            {ro("Department", P.department)}
            {ro("Designation", P.designation)}
            {ro("Previous Salary", P.salary_monthly)}
            {ro("Compliance Gross", P.compliance_gross)}
            {ro("Company", P.company_name)}
            {ro("UAN (continues)", P.uan_no)}
            {ro("ESIC IP (continues)", P.esi_ip_no)}
            {ro("Aadhaar", P.aadhaar_no)}
            {ro("PAN", P.pan_no)}
          </View>

          {/* C — service summary */}
          <Text style={styles.section}>Service Summary</Text>
          <View style={[styles.card, { flexDirection: "row", justifyContent: "space-between" }]}>
            <View style={{ alignItems: "center", flex: 1 }}>
              <Text style={styles.kpiLabel}>Previous Service</Text>
              <Text style={styles.kpiValue}>{S.previous_service || "—"}</Text>
            </View>
            <View style={{ alignItems: "center", flex: 1 }}>
              <Text style={styles.kpiLabel}>Gap</Text>
              <Text style={styles.kpiValue}>{S.gap_days != null ? `${S.gap_days} Days` : "—"}</Text>
            </View>
            <View style={{ alignItems: "center", flex: 1 }}>
              <Text style={styles.kpiLabel}>New Period</Text>
              <Text style={styles.kpiValue}>#{history.length + 2}</Text>
            </View>
          </View>

          {/* B — new employment details */}
          <Text style={styles.section}>B · New Employment Details</Text>
          <View style={styles.card}>
            <Text style={styles.inLabel}>Rejoin Date * (YYYY-MM-DD)</Text>
            <TextInput style={styles.input} value={rejoinDate} onChangeText={setRejoinDate}
              placeholder="2026-06-01" testID="rejoin-date-input" />
            <Text style={styles.inLabel}>Rejoin Reason *</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
              {REASONS.map((r) => (
                <Pressable key={r} onPress={() => setReason(r)}
                  style={[styles.chip, reason === r && styles.chipOn]}>
                  <Text style={[styles.chipTxt, reason === r && styles.chipTxtOn]}>{r}</Text>
                </Pressable>
              ))}
            </View>
            <TextInput style={styles.input} value={reason} onChangeText={setReason}
              placeholder="Reason for rejoin" testID="rejoin-reason-input" />
            <Text style={styles.inLabel}>Department</Text>
            <TextInput style={styles.input} value={department} onChangeText={setDepartment} />
            <Text style={styles.inLabel}>Designation</Text>
            <TextInput style={styles.input} value={designation} onChangeText={setDesignation} />
            <Text style={styles.inLabel}>Employee Type</Text>
            <TextInput style={styles.input} value={employeeType} onChangeText={setEmployeeType}
              placeholder="e.g. permanent / contract" />
            <Text style={styles.inLabel}>New Actual Salary (monthly, optional)</Text>
            <TextInput style={styles.input} value={salaryMonthly} onChangeText={setSalaryMonthly}
              keyboardType="numeric" placeholder={String(P.salary_monthly || "")} />
            <Text style={styles.inLabel}>New Compliance Basic (optional)</Text>
            <TextInput style={styles.input} value={complianceBasic} onChangeText={setComplianceBasic}
              keyboardType="numeric" />
            <Text style={styles.inLabel}>New Compliance Gross (optional)</Text>
            <TextInput style={styles.input} value={complianceGross} onChangeText={setComplianceGross}
              keyboardType="numeric" placeholder={String(P.compliance_gross || "")} />
            {String(policy.leave_balance) === "manual" && (
              <>
                <Text style={styles.inLabel}>Leave Opening Balance (manual policy)</Text>
                <TextInput style={styles.input} value={leaveOpening} onChangeText={setLeaveOpening}
                  keyboardType="numeric" />
              </>
            )}
          </View>

          {/* policy summary */}
          <View style={[styles.card, { backgroundColor: "#F0F9FF", borderColor: "#BAE6FD" }]}>
            <Text style={{ fontWeight: "800", color: "#075985", marginBottom: 4 }}>Firm Rejoin Policy</Text>
            <Text style={styles.polTxt}>• Employee Code: {policy.employee_code === "new" ? "Generate NEW code (old code stays linked)" : "Continue existing code"}</Text>
            <Text style={styles.polTxt}>• Leave Balance: {String(policy.leave_balance || "continue")}</Text>
            <Text style={styles.polTxt}>• Gratuity Service: {policy.gratuity_service === "fresh" ? "Fresh employment" : "Continue previous service"}</Text>
            <Text style={styles.polTxt}>• UAN & ESIC IP: ALWAYS continue (never re-issued)</Text>
            <Text style={styles.polTxt}>• Attendance & payroll restart from the Rejoin Date; all history stays locked.</Text>
          </View>

          {/* D — employment history */}
          {history.length > 0 && (
            <>
              <Text style={styles.section}>Employment History</Text>
              {history.map((h: any) => (
                <View key={h.employment_id} style={styles.card}>
                  <Text style={{ fontWeight: "800", color: colors.onSurface }}>
                    Employment #{h.sequence} · {h.employee_code || ""}
                  </Text>
                  <Text style={styles.polTxt}>
                    {h.doj || "?"} → {h.lwd || "?"} · {h.department || "—"} · {h.designation || "—"}
                  </Text>
                  <Text style={styles.polTxt}>
                    Salary ₹{h.salary_monthly ?? "—"} · Left: {h.reason_for_leaving || "—"}
                  </Text>
                </View>
              ))}
            </>
          )}

          <Pressable
            onPress={submit}
            disabled={saving || !info?.eligible}
            style={[styles.submitBtn, (saving || !info?.eligible) && { opacity: 0.5 }]}
            testID="rejoin-submit"
          >
            {saving ? <ActivityIndicator color="#fff" /> : (
              <Text style={styles.submitTxt}>Rejoin Employee</Text>
            )}
          </Pressable>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.lg, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  backBtn: { padding: 6 },
  title: { fontSize: type.h3, fontWeight: "800", color: colors.onSurface },
  err: { color: colors.danger, padding: spacing.lg },
  section: { fontWeight: "800", color: colors.onSurfaceSecondary, marginTop: 14, marginBottom: 6, fontSize: 12, textTransform: "uppercase", letterSpacing: 0.6 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: 14, marginBottom: 8,
  },
  roRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  roLabel: { color: colors.onSurfaceTertiary, fontSize: 12.5 },
  roValue: { color: colors.onSurface, fontWeight: "700", fontSize: 12.5, maxWidth: "60%", textAlign: "right" },
  kpiLabel: { fontSize: 11, color: colors.onSurfaceTertiary },
  kpiValue: { fontSize: 14, fontWeight: "800", color: colors.brandPrimary, marginTop: 2 },
  inLabel: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 8, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: Platform.OS === "web" ? 8 : 10,
    color: colors.onSurface, backgroundColor: colors.background, fontSize: 13,
  },
  chip: { borderWidth: 1, borderColor: colors.border, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11.5, color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff", fontWeight: "700" },
  warnBox: { backgroundColor: "#FEF2F2", borderColor: "#FECACA", borderWidth: 1, borderRadius: radius.lg, padding: 12, marginBottom: 8 },
  warnTxt: { color: "#991B1B", fontSize: 12.5, lineHeight: 18 },
  polTxt: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2, lineHeight: 17 },
  submitBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.lg, alignItems: "center",
    paddingVertical: 14, marginTop: 16, minHeight: 48, justifyContent: "center",
  },
  submitTxt: { color: "#fff", fontWeight: "800", fontSize: 15 },
});
