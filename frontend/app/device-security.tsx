/**
 * Iter 601 — Employee PWA: DEVICE SECURITY (WebAuthn / Passkey).
 *
 * Register this phone as the employee's trusted punch device. The phone's
 * Face ID / Face Unlock / fingerprint stays ON the device — the portal only
 * receives a cryptographic authentication result.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { authenticateDevice, registerDevice, webauthnSupport } from "@/src/utils/webauthnClient";
import { colors, radius, shadow, spacing } from "@/src/theme";

type Dev = {
  credential_ref: string; device_label?: string; status: string;
  registered_at?: string; last_used_at?: string | null;
};

export default function DeviceSecurityScreen() {
  const [support, setSupport] = useState<{ supported: boolean; platform: boolean } | null>(null);
  const [devices, setDevices] = useState<Dev[]>([]);
  const [changeReq, setChangeReq] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api<{ devices: Dev[]; change_request: any }>("/attendance/device/status");
      setDevices(r.devices || []);
      setChangeReq(r.change_request || null);
    } catch { /* not logged in */ }
  }, []);

  useEffect(() => {
    webauthnSupport().then(setSupport);
    load();
  }, [load]);

  const doRegister = async () => {
    setBusy("register"); setErr(""); setMsg("");
    try {
      const label = Platform.OS === "web"
        ? (navigator as any)?.userAgent?.slice(0, 70) || "Browser device"
        : "Mobile device";
      const m = await registerDevice(label);
      setMsg(m);
      await load();
    } catch (e: any) {
      setErr(e?.message || "Registration failed");
    } finally { setBusy(""); }
  };

  const doTest = async () => {
    setBusy("test"); setErr(""); setMsg("");
    try {
      await authenticateDevice();
      setMsg("✓ Device verified — Face ID / fingerprint authentication works");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Verification failed");
    } finally { setBusy(""); }
  };

  const doRequestChange = async () => {
    setBusy("change"); setErr(""); setMsg("");
    try {
      const r = await api<{ message: string }>("/attendance/device/request-change", {
        method: "POST", body: { reason: "New phone" } });
      setMsg(r.message);
      await load();
    } catch (e: any) {
      setErr(e?.message || "Request failed");
    } finally { setBusy(""); }
  };

  const active = devices.filter((d) => d.status === "active");

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.headerRow}>
          <View style={styles.headerIcon}>
            <Ionicons name="phone-portrait-outline" size={20} color={colors.onBrandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Device Security</Text>
            <Text style={styles.subtitle}>Link this phone for secure attendance punching</Text>
          </View>
        </View>

        {/* Support check */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Checking Device Security…</Text>
          {support === null ? <ActivityIndicator /> : (
            <>
              <Row ok={support.supported} label="WebAuthn supported" />
              <Row ok={support.platform} label="Platform authenticator (Face ID / fingerprint) available" />
              {!support.supported || !support.platform ? (
                <Text style={styles.warnTxt}>
                  Device Authentication Not Available{"\n"}
                  Your device/browser does not support the required secure
                  authentication method. Please use a supported device/browser
                  or contact Admin.
                </Text>
              ) : null}
            </>
          )}
        </View>

        {/* Status */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Registered Device</Text>
          {active.length === 0 ? (
            <>
              <Text style={styles.mutedTxt}>
                No device registered yet. This phone will be linked to your
                employee account. Your phone may ask you to verify using Face
                ID, Face Unlock, Fingerprint or Device PIN.
              </Text>
              <Pressable
                style={[styles.btn, (!support?.platform || !!busy) && { opacity: 0.5 }]}
                disabled={!support?.platform || !!busy}
                onPress={doRegister}
                testID="dev-register"
              >
                {busy === "register"
                  ? <ActivityIndicator color="#fff" size="small" />
                  : <Ionicons name="finger-print-outline" size={16} color="#fff" />}
                <Text style={styles.btnTxt}>Register This Device</Text>
              </Pressable>
            </>
          ) : active.map((d) => (
            <View key={d.credential_ref} style={{ gap: 4 }}>
              <Row ok label={`Status: REGISTERED ✓ (Passkey / WebAuthn)`} />
              <Text style={styles.mutedTxt}>
                {d.device_label || "This device"}{"\n"}
                Registered: {d.registered_at ? new Date(d.registered_at).toLocaleString("en-IN") : "—"}{"\n"}
                Last authentication: {d.last_used_at ? new Date(d.last_used_at).toLocaleString("en-IN") : "—"}
              </Text>
              <Pressable style={[styles.btn, { backgroundColor: "#0E7490" }]} onPress={doTest} disabled={!!busy} testID="dev-test">
                {busy === "test"
                  ? <ActivityIndicator color="#fff" size="small" />
                  : <Ionicons name="shield-checkmark-outline" size={16} color="#fff" />}
                <Text style={styles.btnTxt}>Test Device Verification</Text>
              </Pressable>
              {changeReq ? (
                <Text style={styles.warnTxt}>
                  Device change request: {String(changeReq.status).toUpperCase()}
                  {changeReq.status === "approved" ? " — you may now register the new phone." : " — waiting for HR/Admin."}
                </Text>
              ) : (
                <Pressable style={styles.linkBtn} onPress={doRequestChange} disabled={!!busy} testID="dev-request-change">
                  <Text style={styles.linkTxt}>Got a new phone? Request device change (HR approval)</Text>
                </Pressable>
              )}
              {changeReq?.status === "approved" ? (
                <Pressable style={[styles.btn, (!support?.platform || !!busy) && { opacity: 0.5 }]} disabled={!support?.platform || !!busy} onPress={doRegister}>
                  <Ionicons name="finger-print-outline" size={16} color="#fff" />
                  <Text style={styles.btnTxt}>Register New Device</Text>
                </Pressable>
              ) : null}
            </View>
          ))}
          {!!msg && <Text style={styles.okTxt}>{msg}</Text>}
          {!!err && <Text style={styles.errTxt}>{err}</Text>}
        </View>

        {/* Privacy notice */}
        <View style={[styles.card, { backgroundColor: "#F0FDF4", borderColor: "#BBF7D0" }]}>
          <Text style={styles.cardTitle}>🔒 Your privacy</Text>
          <Text style={styles.mutedTxt}>
            Your phone&apos;s biometric information stays on your device. The
            payroll system does NOT receive or store your Face ID, Face
            Unlock, or fingerprint. It only receives a cryptographic
            authentication result from your device.
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function Row({ ok, label }: { ok: boolean; label: string }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
      <Ionicons name={ok ? "checkmark-circle" : "close-circle"} size={15}
        color={ok ? "#047857" : "#DC2626"} />
      <Text style={{ fontSize: 12.5, color: colors.onSurface, flex: 1 }}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.lg, gap: spacing.md, maxWidth: 560, width: "100%", alignSelf: "center" },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  headerIcon: {
    width: 38, height: 38, borderRadius: 10, backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  title: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceSecondary },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.borderLight, padding: spacing.md, gap: 8, ...shadow.sm,
  },
  cardTitle: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  mutedTxt: { fontSize: 12, color: colors.onSurfaceSecondary, lineHeight: 18 },
  warnTxt: { fontSize: 12, color: "#B45309", lineHeight: 18 },
  okTxt: { fontSize: 12.5, color: "#047857", fontWeight: "600" },
  errTxt: { fontSize: 12.5, color: "#DC2626", fontWeight: "600" },
  btn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brandPrimary, borderRadius: 10, paddingVertical: 12,
    marginTop: 6, minHeight: 44,
  },
  btnTxt: { color: "#fff", fontSize: 13.5, fontWeight: "700" },
  linkBtn: { paddingVertical: 8 },
  linkTxt: { color: colors.brandPrimary, fontSize: 12.5, fontWeight: "600" },
});
