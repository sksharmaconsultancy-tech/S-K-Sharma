/**
 * Iter 580 — Administration → Audit Notifications.
 * Instant critical-activity emails, failed-login alerts, daily summary.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator, ScrollView, Switch } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

export default function AuditNotificationsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [st, setSt] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const notify = (m: string) => { setMsg(m); setTimeout(() => setMsg(null), 5000); };

  useEffect(() => {
    if (user?.role === "super_admin") {
      api("/admin/audit-notify-settings").then(setSt).catch((e) => notify(e?.message || "Load failed"));
    }
  }, [user?.user_id]);  // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setSaving(true);
    try {
      await api("/admin/audit-notify-settings", { method: "PUT", body: {
        enabled: !!st.enabled, instant_enabled: !!st.instant_enabled,
        daily_enabled: !!st.daily_enabled, failed_login_notify: !!st.failed_login_notify,
        recipients: st.recipients, cc: st.cc,
      }});
      notify("Saved ✓");
    } catch (e: any) { notify(e?.message || "Save failed"); }
    finally { setSaving(false); }
  };

  const sendNow = async () => {
    try {
      const r = await api("/admin/audit-notify-settings/send-daily-now", { method: "POST" });
      notify(r.sent ? `Daily summary sent ✓ (${r.total} activities on ${r.date})` : "Not sent — add recipients & enable first");
    } catch (e: any) { notify(e?.message || "Failed"); }
  };

  if (user?.role !== "super_admin") {
    return <View style={styles.center}><Text style={styles.dim}>Super Admin only</Text></View>;
  }
  if (!st) return <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>;

  const listVal = (v: any) => Array.isArray(v) ? v.join(", ") : String(v || "");

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>Audit Notifications</Text>
            <Text style={styles.hsub}>Instant critical alerts · Daily summary (08:00 IST)</Text>
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>
      {msg ? <View style={styles.toast}><Text style={styles.toastTxt}>{msg}</Text></View> : null}
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.card}>
          <Row label="Email Notifications"><Switch value={!!st.enabled} onValueChange={(v) => setSt({ ...st, enabled: v })} trackColor={{ true: colors.brandPrimary }} /></Row>
          <Row label="Instant Critical Activity Alerts"><Switch value={!!st.instant_enabled} onValueChange={(v) => setSt({ ...st, instant_enabled: v })} trackColor={{ true: colors.brandPrimary }} /></Row>
          <Row label="Daily Summary (08:00 IST)"><Switch value={!!st.daily_enabled} onValueChange={(v) => setSt({ ...st, daily_enabled: v })} trackColor={{ true: colors.brandPrimary }} /></Row>
          <Row label="Failed Login Alerts"><Switch value={!!st.failed_login_notify} onValueChange={(v) => setSt({ ...st, failed_login_notify: v })} trackColor={{ true: colors.brandPrimary }} /></Row>
          <Text style={styles.lbl}>Recipients (comma-separated)</Text>
          <TextInput style={styles.input} value={listVal(st.recipients)} autoCapitalize="none"
            onChangeText={(v) => setSt({ ...st, recipients: v.split(",").map((x: string) => x.trim()) })}
            placeholder="admin@firm.com, owner@firm.com" placeholderTextColor={colors.onSurfaceTertiary} />
          <Text style={styles.lbl}>CC (optional)</Text>
          <TextInput style={styles.input} value={listVal(st.cc)} autoCapitalize="none"
            onChangeText={(v) => setSt({ ...st, cc: v.split(",").map((x: string) => x.trim()) })}
            placeholder="cc@firm.com" placeholderTextColor={colors.onSurfaceTertiary} />
          <Text style={styles.dim}>Critical = employee delete, bank/salary field change, payroll unlock, permission/role change, challan modification, firm access change.</Text>
        </View>
        <Pressable onPress={save} disabled={saving} style={[styles.btn, saving && { opacity: 0.6 }]} testID="an-save">
          {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnTxt}>Save Settings</Text>}
        </Pressable>
        <Pressable onPress={sendNow} style={[styles.btn, { backgroundColor: "#16a34a" }]} testID="an-send-now">
          <Text style={styles.btnTxt}>Send Yesterday&apos;s Summary Now (Test)</Text>
        </Pressable>
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

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: {
    paddingHorizontal: spacing.md, height: 52, flexDirection: "row", alignItems: "center",
    borderBottomWidth: 1, borderBottomColor: colors.divider, backgroundColor: colors.surface,
  },
  h1: { ...type.h5, color: colors.onSurface, fontWeight: "700" },
  hsub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },
  scroll: { padding: spacing.md, maxWidth: 720, width: "100%", alignSelf: "center" },
  toast: { backgroundColor: "#065f46", padding: 10, alignItems: "center" },
  toastTxt: { color: "#fff", fontWeight: "700", fontSize: 12 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    padding: spacing.md, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border,
  },
  row: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.divider, gap: 10,
  },
  rowLabel: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  lbl: { ...type.tiny, color: colors.onSurfaceSecondary, fontWeight: "700", marginBottom: 4, marginTop: 10, textTransform: "uppercase" },
  input: {
    borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 9, color: colors.onSurface, backgroundColor: colors.surface,
  },
  dim: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 10 },
  btn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md, paddingVertical: 12,
    marginBottom: spacing.md, alignItems: "center",
  },
  btnTxt: { color: "#fff", fontWeight: "700" },
});
