/**
 * Iter 576 — Communication → SMS (MSG91) — Phase 1.
 * Company-wise MSG91 config (secrets masked), event toggles, rate limits,
 * Send Test SMS, and recent SMS log (masked mobiles).
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, ScrollView, Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";
import { formatDateTime } from "@/src/utils/date";

const TOGGLES: [string, string][] = [
  ["salary", "Salary SMS"], ["attendance", "Attendance SMS"],
  ["leave", "Leave SMS"], ["payroll", "Payroll SMS"],
  ["compliance", "Compliance SMS"], ["onboarding", "Employee Onboarding SMS"],
];

export default function SmsSettingsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const [st, setSt] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [logSummary, setLogSummary] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [testMobile, setTestMobile] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const notify = (m: string) => { setMsg(m); setTimeout(() => setMsg(null), 5000); };

  const load = async () => {
    try {
      const s = await api("/admin/sms-settings");
      setSt(s);
      const l = await api("/admin/sms-logs");
      setLogs(l.logs || []);
      setLogSummary(l.summary || null);
    } catch (e: any) { notify(e?.message || "Load failed"); }
  };
  useEffect(() => { if (user) load(); }, [user?.user_id]);  // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setSaving(true);
    try {
      await api("/admin/sms-settings", { method: "PUT", body: {
        enabled: !!st.enabled, otp_enabled: !!st.otp_enabled,
        authkey: st.authkey || "", sender_id: st.sender_id || "",
        entity_id: st.entity_id || "", otp_flow_id: st.otp_flow_id || "",
        default_flow_id: st.default_flow_id || "", toggles: st.toggles || {},
        rate_otp_per_10min: Number(st.rate_otp_per_10min) || 3,
        rate_mobile_per_hour: Number(st.rate_mobile_per_hour) || 5,
        rate_user_per_min: Number(st.rate_user_per_min) || 10,
      }});
      notify("SMS settings saved ✓"); load();
    } catch (e: any) { notify(e?.message || "Save failed"); }
    finally { setSaving(false); }
  };

  const sendTest = async () => {
    try {
      const r = await api("/admin/sms-settings/test", { method: "POST", body: { mobile: testMobile } });
      notify(r.delivered ? `Test SMS sent ✓ (request ${r.request_id || ""})` : `Failed: ${r.error}`);
      load();
    } catch (e: any) { notify(e?.message || "Test failed"); }
  };

  if (!st) return <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>;
  const upT = (k: string, v: boolean) => setSt({ ...st, toggles: { ...st.toggles, [k]: v } });

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>SMS (MSG91)</Text>
            <Text style={styles.hsub}>API: {st.api_status} · DLT-compliant templates</Text>
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>
      {msg ? <View style={styles.toast}><Text style={styles.toastTxt}>{msg}</Text></View> : null}
      <ScrollView contentContainerStyle={styles.scroll}>
        {isSuper ? (
          <>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>MSG91 Configuration</Text>
              <Row label="SMS Service"><Switch value={!!st.enabled} onValueChange={(v) => setSt({ ...st, enabled: v })} trackColor={{ true: colors.brandPrimary }} /></Row>
              <Row label="OTP via SMS (login 2FA)"><Switch value={!!st.otp_enabled} onValueChange={(v) => setSt({ ...st, otp_enabled: v })} trackColor={{ true: colors.brandPrimary }} /></Row>
              <Field label="Auth Key (kept secret — server-side only)" value={st.authkey || ""} onChange={(v: string) => setSt({ ...st, authkey: v })} secure placeholder={st.authkey_set ? "•••••••• (saved)" : "MSG91 Auth Key"} />
              <Field label="Sender ID / DLT Header" value={st.sender_id || ""} onChange={(v: string) => setSt({ ...st, sender_id: v })} placeholder="e.g. SKSHRM" />
              <Field label="DLT Entity / PE ID" value={st.entity_id || ""} onChange={(v: string) => setSt({ ...st, entity_id: v })} placeholder="1234567890..." />
              <Field label="OTP Flow ID (DLT-approved, ##otp## variable)" value={st.otp_flow_id || ""} onChange={(v: string) => setSt({ ...st, otp_flow_id: v })} />
              <Field label="Default Flow ID (test/notifications)" value={st.default_flow_id || ""} onChange={(v: string) => setSt({ ...st, default_flow_id: v })} />
            </View>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Notification Toggles</Text>
              {TOGGLES.map(([k, lbl]) => (
                <Row key={k} label={lbl}><Switch value={!!st.toggles?.[k]} onValueChange={(v) => upT(k, v)} trackColor={{ true: colors.brandPrimary }} /></Row>
              ))}
            </View>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Rate Limits</Text>
              <Field label="Max OTP per user / 10 min" value={String(st.rate_otp_per_10min ?? 3)} onChange={(v: string) => setSt({ ...st, rate_otp_per_10min: v.replace(/\D/g, "") })} />
              <Field label="Max OTP per mobile / hour" value={String(st.rate_mobile_per_hour ?? 5)} onChange={(v: string) => setSt({ ...st, rate_mobile_per_hour: v.replace(/\D/g, "") })} />
              <Field label="Max SMS per user / minute" value={String(st.rate_user_per_min ?? 10)} onChange={(v: string) => setSt({ ...st, rate_user_per_min: v.replace(/\D/g, "") })} />
            </View>
            <Pressable onPress={save} disabled={saving} style={[styles.primaryBtn, saving && { opacity: 0.6 }]} testID="sms-save">
              {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryBtnTxt}>Save SMS Settings</Text>}
            </Pressable>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Send Test SMS</Text>
              <Field label="Mobile number (10-digit Indian)" value={testMobile} onChange={setTestMobile} placeholder="98XXXXXXXX" />
              <Pressable onPress={sendTest} style={[styles.primaryBtn, { backgroundColor: "#16a34a" }]} testID="sms-test">
                <Text style={styles.primaryBtnTxt}>Send Test SMS</Text>
              </Pressable>
            </View>
          </>
        ) : null}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>
            SMS Log{logSummary ? ` · ${logSummary.total} (✓${logSummary.sent} ✗${logSummary.failed} · OTP ${logSummary.otp})` : ""}
          </Text>
          {logs.length === 0 ? <Text style={styles.dim}>No SMS sent yet.</Text> : logs.slice(0, 50).map((r) => (
            <View key={r.log_id} style={styles.logRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.logTitle}>{r.notification_type} → {r.mobile}</Text>
                <Text style={styles.dim}>{formatDateTime(r.at)}{r.error ? ` · ${r.error}` : r.request_id ? ` · req ${r.request_id}` : ""}</Text>
              </View>
              <Text style={[styles.status, { color: r.status === "SENT" ? "#15803d" : "#dc2626" }]}>{r.status}</Text>
            </View>
          ))}
        </View>
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={styles.row}>
      <Text style={[styles.rowLabel, { flex: 1 }]}>{label}</Text>
      {children}
    </View>
  );
}

function Field({ label, value, onChange, secure, placeholder }: any) {
  return (
    <View style={{ marginBottom: 8 }}>
      <Text style={styles.lbl}>{label}</Text>
      <TextInput style={styles.input} value={value} onChangeText={onChange}
        placeholder={placeholder} placeholderTextColor={colors.onSurfaceTertiary}
        secureTextEntry={!!secure} autoCapitalize="none" />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: {
    paddingHorizontal: spacing.md, height: 52, flexDirection: "row", alignItems: "center",
    borderBottomWidth: 1, borderBottomColor: colors.divider, backgroundColor: colors.surface,
  },
  h1: { ...type.h5, color: colors.onSurface, fontWeight: "700" },
  hsub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },
  scroll: { padding: spacing.md, maxWidth: 860, width: "100%", alignSelf: "center" },
  toast: { backgroundColor: "#065f46", padding: 10, alignItems: "center" },
  toastTxt: { color: "#fff", fontWeight: "700", fontSize: 12 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    padding: spacing.md, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border,
  },
  cardTitle: { ...type.h6, color: colors.onSurface, fontWeight: "700", marginBottom: 8 },
  row: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 7, borderBottomWidth: 1, borderBottomColor: colors.divider, gap: 10,
  },
  rowLabel: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  lbl: { ...type.tiny, color: colors.onSurfaceSecondary, fontWeight: "700", marginBottom: 4, marginTop: 8, textTransform: "uppercase" },
  input: {
    borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 9, color: colors.onSurface, backgroundColor: colors.surface,
  },
  primaryBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md, paddingVertical: 12,
    marginBottom: spacing.md, alignItems: "center",
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "700" },
  dim: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  logRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  logTitle: { fontSize: 13, fontWeight: "600", color: colors.onSurface },
  status: { fontSize: 11, fontWeight: "800" },
});
