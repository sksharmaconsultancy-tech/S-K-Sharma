/**
 * Iter 569 — Administration → Security Settings → 2FA/MFA.
 *
 * Super admin: full settings (OTP rules, channel toggles, WhatsApp/SMS
 * provider configuration, trusted-device policy).
 * All admins: "My Security" (masked contacts, preferred method, sessions,
 * trusted devices with revoke, logout from all devices).
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, ScrollView, Platform, Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, clearToken } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";
import { formatDateTime } from "@/src/utils/date";

const MASK = "••••••••";

export default function Security2FAScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const isAdmin = isSuper || user?.role === "sub_admin" || user?.role === "company_admin";

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [my, setMy] = useState<any>(null);
  const [st, setSt] = useState<any>(null);
  const [devices, setDevices] = useState<any[]>([]);

  const notify = (m: string) => {
    setMsg(m);
    setTimeout(() => setMsg(null), 4000);
  };

  const load = async () => {
    setLoading(true);
    try {
      const mine = await api("/auth/2fa/my-security");
      setMy(mine);
      const devs = await api("/auth/2fa/trusted-devices");
      setDevices(devs.devices || []);
      if (isSuper) {
        const s = await api("/admin/security-settings/2fa");
        setSt(s);
      }
    } catch (e: any) {
      notify(e?.message || "Failed to load security settings");
    } finally {
      setLoading(false);
    }
  };
  // Load only after AuthContext hydrates — `isSuper` is false while
  // `user` is still null on cold navigation (would skip the settings API).
  useEffect(() => {
    if (user) load();
  }, [user?.user_id]);  // eslint-disable-line react-hooks/exhaustive-deps

  const saveSettings = async () => {
    if (!st) return;
    setSaving(true);
    try {
      await api("/admin/security-settings/2fa", {
        method: "PUT",
        body: {
          otp_length: Number(st.otp_length) || 6,
          otp_validity_min: Number(st.otp_validity_min) || 5,
          resend_cooldown_sec: Number(st.resend_cooldown_sec) || 30,
          max_attempts: Number(st.max_attempts) || 5,
          trusted_days: Number(st.trusted_days) || 30,
          email_enabled: !!st.email_enabled,
          whatsapp_enabled: !!st.whatsapp_enabled,
          sms_enabled: !!st.sms_enabled,
          trusted_device_enabled: !!st.trusted_device_enabled,
          security_alerts_enabled: !!st.security_alerts_enabled,
          otp_email_via_smtp: !!st.otp_email_via_smtp,
          fallback_to_admin_email: !!st.fallback_to_admin_email,
          whatsapp_config: st.whatsapp_config || {},
          sms_config: st.sms_config || {},
        },
      });
      notify("Security settings saved ✓");
      load();
    } catch (e: any) {
      notify(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const setPreferred = async (method: string) => {
    try {
      await api("/auth/2fa/preferred-method", { method: "PUT", body: { method } });
      setMy({ ...my, preferred_method: method });
      notify(`Preferred method set to ${method}`);
    } catch (e: any) {
      notify(e?.message || "Failed");
    }
  };

  const revokeDevice = async (device_id: string) => {
    try {
      await api("/auth/2fa/trusted-devices/revoke", { method: "POST", body: { device_id } });
      setDevices(devices.filter((d) => d.device_id !== device_id));
      notify("Device revoked");
    } catch (e: any) {
      notify(e?.message || "Failed");
    }
  };

  const logoutAll = async () => {
    if (Platform.OS === "web" && !globalThis.confirm("Log out from ALL devices? You will need to sign in again.")) return;
    try {
      await api("/auth/logout-all", { method: "POST" });
      await clearToken();
      if (Platform.OS === "web") window.location.assign("/");
    } catch (e: any) {
      notify(e?.message || "Failed");
    }
  };

  const upSt = (patch: any) => setSt({ ...st, ...patch });
  const upWa = (k: string, v: string) => setSt({ ...st, whatsapp_config: { ...st.whatsapp_config, [k]: v } });
  const upSms = (k: string, v: string) => setSt({ ...st, sms_config: { ...st.sms_config, [k]: v } });

  if (!isAdmin) {
    return (
      <View style={styles.center}>
        <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
        <Text style={styles.dimTxt}>Admins only</Text>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>Security · 2FA/MFA</Text>
            <Text style={styles.hsub}>Login security for Super & Sub admins</Text>
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      {msg ? <View style={styles.toast}><Text style={styles.toastTxt}>{msg}</Text></View> : null}

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {/* ── My Security ─────────────────────────────────────────── */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>My Security</Text>
            <Row label="2FA Status"
              value={my?.twofa_required ? "ENABLED (mandatory)" : "Not required for your role"}
              valueColor={my?.twofa_required ? "#15803d" : undefined} />
            <Row label="Email" value={my?.masked_email || "—"} />
            <Row label="Mobile" value={my?.masked_mobile || "—"} />
            <Row label="Last 2FA Verification" value={my?.last_verified_at ? formatDateTime(my.last_verified_at) : "—"} />
            <Row label="Active Sessions" value={String(my?.active_sessions ?? 0)} />
            <Row label="Trusted Devices" value={String(my?.trusted_devices ?? 0)} />

            <Text style={styles.label}>Preferred verification method</Text>
            <View style={styles.chipStrip}>
              {(my?.methods || []).map((m: any) => (
                <Pressable
                  key={m.method}
                  onPress={() => setPreferred(m.method)}
                  style={[styles.chip, my?.preferred_method === m.method && styles.chipActive]}
                  testID={`2fa-pref-${m.method}`}
                >
                  <Text style={[styles.chipTxt, my?.preferred_method === m.method && styles.chipTxtActive]}>
                    {m.method.toUpperCase()} · {m.target}{m.configured ? "" : " (not configured)"}
                  </Text>
                </Pressable>
              ))}
            </View>

            <Pressable onPress={logoutAll} style={[styles.dangerBtn]} testID="2fa-logout-all">
              <Ionicons name="log-out-outline" size={15} color="#fff" />
              <Text style={styles.primaryBtnTxt}>Logout from all devices</Text>
            </Pressable>
          </View>

          {/* ── Trusted devices ─────────────────────────────────────── */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Trusted Devices</Text>
            {devices.length === 0 ? (
              <Text style={styles.dimTxt}>No trusted devices.</Text>
            ) : devices.map((d) => (
              <View key={d.device_id} style={styles.devRow}>
                <Ionicons name="laptop-outline" size={18} color={colors.brandPrimary} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.devName}>{d.device_name || d.browser || "Device"}</Text>
                  <Text style={styles.devMeta}>
                    Last used: {d.last_used_at ? formatDateTime(d.last_used_at) : "—"} · IP: {d.ip_address || "—"}
                    {d.expired ? "  ·  EXPIRED" : ""}
                  </Text>
                </View>
                <Pressable onPress={() => revokeDevice(d.device_id)} style={styles.revokeBtn} testID={`revoke-${d.device_id}`}>
                  <Text style={styles.revokeTxt}>Revoke</Text>
                </Pressable>
              </View>
            ))}
          </View>

          {/* ── Super-admin settings ────────────────────────────────── */}
          {isSuper && st ? (
            <>
              <View style={styles.card}>
                <Text style={styles.cardTitle}>2FA Policy (Super Admin)</Text>
                <Row label="Super Admin" value="✓ Mandatory (cannot be disabled)" valueColor="#15803d" />
                <Row label="Sub Super Admin" value="✓ Mandatory (cannot be disabled)" valueColor="#15803d" />
                <View style={styles.numGrid}>
                  <NumField label="OTP Length" value={st.otp_length} onChange={(v) => upSt({ otp_length: v })} />
                  <NumField label="OTP Validity (min)" value={st.otp_validity_min} onChange={(v) => upSt({ otp_validity_min: v })} />
                  <NumField label="Resend Cooldown (sec)" value={st.resend_cooldown_sec} onChange={(v) => upSt({ resend_cooldown_sec: v })} />
                  <NumField label="Max OTP Attempts" value={st.max_attempts} onChange={(v) => upSt({ max_attempts: v })} />
                </View>
                <ToggleRow label={`Email OTP ${st.email_configured ? "(Resend configured ✓)" : "(no API key!)"}`}
                  value={!!st.email_enabled} onChange={(v) => upSt({ email_enabled: v })} />
                <ToggleRow label="WhatsApp OTP" value={!!st.whatsapp_enabled} onChange={(v) => upSt({ whatsapp_enabled: v })} />
                <ToggleRow label="SMS OTP" value={!!st.sms_enabled} onChange={(v) => upSt({ sms_enabled: v })} />
                <ToggleRow label="Trusted Device (30-day skip)" value={!!st.trusted_device_enabled}
                  onChange={(v) => upSt({ trusted_device_enabled: v })} />
                <ToggleRow label="Security Alert Emails (OTP lockout / new-IP login)" value={!!st.security_alerts_enabled}
                  onChange={(v) => upSt({ security_alerts_enabled: v })} />
                <Text style={styles.label}>OTP email delivery</Text>
                <ToggleRow label="Send OTP via own SMTP (Email Settings) — delivers to EVERY sub user's email" value={!!st.otp_email_via_smtp}
                  onChange={(v) => upSt({ otp_email_via_smtp: v })} />
                <ToggleRow label="If undeliverable, forward OTP to Super Admin email" value={!!st.fallback_to_admin_email}
                  onChange={(v) => upSt({ fallback_to_admin_email: v })} />
                {st.trusted_device_enabled ? (
                  <View style={styles.numGrid}>
                    <NumField label="Trusted for (days)" value={st.trusted_days} onChange={(v) => upSt({ trusted_days: v })} />
                  </View>
                ) : null}
              </View>

              <View style={styles.card}>
                <Text style={styles.cardTitle}>WhatsApp OTP Provider (Meta Cloud API)</Text>
                <Text style={styles.dimTxt}>
                  Add your Meta WhatsApp Business credentials to activate this channel.
                  Until then it shows as not configured during login.
                </Text>
                <TextField label="Access Token" value={st.whatsapp_config?.access_token || ""}
                  onChange={(v) => upWa("access_token", v)} secure placeholder="EAAG... (kept secret)" />
                <TextField label="Phone Number ID" value={st.whatsapp_config?.phone_number_id || ""}
                  onChange={(v) => upWa("phone_number_id", v)} placeholder="1234567890" />
                <TextField label="Template Name (optional)" value={st.whatsapp_config?.template_name || ""}
                  onChange={(v) => upWa("template_name", v)} placeholder="otp_template" />
              </View>

              <View style={styles.card}>
                <Text style={styles.cardTitle}>SMS OTP Provider</Text>
                <Text style={styles.label}>Provider</Text>
                <View style={styles.chipStrip}>
                  {["", "twilio", "msg91", "fast2sms"].map((p) => (
                    <Pressable key={p || "none"} onPress={() => upSms("provider", p)}
                      style={[styles.chip, (st.sms_config?.provider || "") === p && styles.chipActive]}>
                      <Text style={[styles.chipTxt, (st.sms_config?.provider || "") === p && styles.chipTxtActive]}>
                        {p === "" ? "Not configured" : p.toUpperCase()}
                      </Text>
                    </Pressable>
                  ))}
                </View>
                {st.sms_config?.provider === "twilio" ? (
                  <>
                    <TextField label="Account SID" value={st.sms_config?.twilio_sid || ""} onChange={(v) => upSms("twilio_sid", v)} secure />
                    <TextField label="Auth Token" value={st.sms_config?.twilio_token || ""} onChange={(v) => upSms("twilio_token", v)} secure />
                    <TextField label="Sender Number" value={st.sms_config?.twilio_from || ""} onChange={(v) => upSms("twilio_from", v)} placeholder="+1..." />
                  </>
                ) : null}
                {st.sms_config?.provider === "msg91" ? (
                  <>
                    <TextField label="Auth Key" value={st.sms_config?.msg91_authkey || ""} onChange={(v) => upSms("msg91_authkey", v)} secure />
                    <TextField label="Sender ID" value={st.sms_config?.msg91_sender || ""} onChange={(v) => upSms("msg91_sender", v)} />
                    <TextField label="DLT Template ID" value={st.sms_config?.msg91_template_id || ""} onChange={(v) => upSms("msg91_template_id", v)} />
                  </>
                ) : null}
                {st.sms_config?.provider === "fast2sms" ? (
                  <TextField label="API Key" value={st.sms_config?.fast2sms_key || ""} onChange={(v) => upSms("fast2sms_key", v)} secure />
                ) : null}
              </View>

              <Pressable onPress={saveSettings} disabled={saving}
                style={[styles.primaryBtn, saving && { opacity: 0.6 }]} testID="2fa-save-settings">
                {saving ? <ActivityIndicator color="#fff" /> : (
                  <>
                    <Ionicons name="save-outline" size={15} color="#fff" />
                    <Text style={styles.primaryBtnTxt}>Save Security Settings</Text>
                  </>
                )}
              </Pressable>
            </>
          ) : null}
          <View style={{ height: 40 }} />
        </ScrollView>
      )}
    </View>
  );
}

function Row({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, valueColor ? { color: valueColor, fontWeight: "700" } : null]}>{value}</Text>
    </View>
  );
}

function ToggleRow({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <View style={styles.row}>
      <Text style={[styles.rowLabel, { flex: 1 }]}>{label}</Text>
      <Switch value={value} onValueChange={onChange} trackColor={{ true: colors.brandPrimary }} />
    </View>
  );
}

function NumField({ label, value, onChange }: { label: string; value: any; onChange: (v: string) => void }) {
  return (
    <View style={styles.numField}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        style={styles.input}
        value={String(value ?? "")}
        onChangeText={(v) => onChange(v.replace(/[^0-9]/g, ""))}
        keyboardType="number-pad"
      />
    </View>
  );
}

function TextField({ label, value, onChange, secure, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; secure?: boolean; placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  const masked = secure && value === MASK;
  return (
    <View style={{ marginBottom: 8 }}>
      <Text style={styles.label}>{label}</Text>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <TextInput
          style={[styles.input, { flex: 1 }]}
          value={value}
          onChangeText={onChange}
          placeholder={placeholder}
          placeholderTextColor={colors.onSurfaceTertiary}
          secureTextEntry={!!secure && !show && !masked}
          autoCapitalize="none"
        />
        {secure ? (
          <Pressable onPress={() => setShow(!show)} hitSlop={8}>
            <Ionicons name={show ? "eye-off-outline" : "eye-outline"} size={18} color={colors.onSurfaceTertiary} />
          </Pressable>
        ) : null}
      </View>
      {masked ? <Text style={styles.dimTxt}>Saved — leave as ●●● to keep, or type a new value.</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40, gap: 8 },
  header: {
    paddingHorizontal: spacing.md, height: 52,
    flexDirection: "row", alignItems: "center",
    borderBottomWidth: 1, borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
  },
  h1: { ...type.h5, color: colors.onSurface, fontWeight: "700" },
  hsub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },
  scroll: { padding: spacing.md, paddingBottom: 40, maxWidth: 860, width: "100%", alignSelf: "center" },
  toast: {
    backgroundColor: "#065f46", padding: 10, alignItems: "center",
  },
  toastTxt: { color: "#fff", fontWeight: "700", fontSize: 12 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    padding: spacing.md, marginBottom: spacing.md,
    borderWidth: 1, borderColor: colors.border,
  },
  cardTitle: { ...type.h6, color: colors.onSurface, fontWeight: "700", marginBottom: 8 },
  dimTxt: { ...type.caption, color: colors.onSurfaceSecondary, marginBottom: 6 },
  row: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 7, borderBottomWidth: 1, borderBottomColor: colors.divider, gap: 10,
  },
  rowLabel: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  rowValue: { fontSize: 13, color: colors.onSurface },
  label: {
    ...type.tiny, color: colors.onSurfaceSecondary, fontWeight: "700",
    marginBottom: 4, marginTop: 8, textTransform: "uppercase",
  },
  input: {
    borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 9,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  numGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 4, marginBottom: 4 },
  numField: { flexGrow: 1, minWidth: 140 },
  chipStrip: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 4 },
  chip: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 14,
    borderWidth: 1, borderColor: colors.borderStrong, backgroundColor: colors.surface,
  },
  chipActive: { borderColor: colors.brandPrimary, backgroundColor: colors.brandPrimary },
  chipTxt: { color: colors.onSurfaceSecondary, fontWeight: "600", fontSize: 12 },
  chipTxtActive: { color: "#fff" },
  primaryBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingVertical: 12, marginTop: 8,
    flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "700" },
  dangerBtn: {
    backgroundColor: "#dc2626", borderRadius: radius.md,
    paddingVertical: 11, marginTop: 12,
    flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6,
  },
  devRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  devName: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  devMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  revokeBtn: {
    borderWidth: 1, borderColor: "#dc2626", borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 6,
  },
  revokeTxt: { color: "#dc2626", fontWeight: "700", fontSize: 12 },
});
