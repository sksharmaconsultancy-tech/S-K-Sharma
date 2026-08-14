/**
 * Iter 569 — 2FA OTP verification screen (Super/Sub admin login).
 *
 * Reached from the admin login when the server returns `twofa_required`.
 * No session exists yet — only a short-lived pending_token. The full
 * session is created server-side ONLY after the OTP verifies.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api, saveToken, saveDeviceToken } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type MethodInfo = { method: string; target: string; configured: boolean };

const METHOD_LABEL: Record<string, string> = {
  email: "Email", whatsapp: "WhatsApp", sms: "SMS",
};
const METHOD_ICON: Record<string, any> = {
  email: "mail-outline", whatsapp: "logo-whatsapp", sms: "chatbox-outline",
};

export default function Verify2FAScreen() {
  const router = useRouter();
  const { refresh } = useAuth();
  const params = useLocalSearchParams<Record<string, string>>();

  const pendingToken = String(params.pending_token || "");
  const maskedEmail = String(params.masked_email || "");
  const maskedMobile = String(params.masked_mobile || "");
  const trustedEnabled = params.trusted_enabled === "1";
  const methods: MethodInfo[] = useMemo(() => {
    try { return JSON.parse(String(params.methods || "[]")); } catch { return []; }
  }, [params.methods]);

  const [method, setMethod] = useState(String(params.method || "email"));
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [resending, setResending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(() => {
    const note = String(params.delivery_note || "");
    if (note.startsWith("sent_to_admin:")) {
      return `Email provider is in TEST mode — the OTP was sent to the administrator's email (${note.split(":")[1] || ""}). Ask your admin for the code, or verify a domain at resend.com to deliver directly.`;
    }
    if (params.delivered === "1") return null;
    return params.delivery_error
      ? "We could not send the OTP using this method. Please try another verification method."
      : null;
  });
  const [cooldown, setCooldown] = useState(Number(params.resend_cooldown || 30));
  const [expiresIn, setExpiresIn] = useState(Number(params.otp_expires_in || 300));
  const [trustDevice, setTrustDevice] = useState(false);
  const inputRef = useRef<TextInput>(null);

  // countdown ticks
  useEffect(() => {
    const t = setInterval(() => {
      setCooldown((c) => (c > 0 ? c - 1 : 0));
      setExpiresIn((e) => (e > 0 ? e - 1 : 0));
    }, 1000);
    return () => clearInterval(t);
  }, []);

  if (!pendingToken) {
    return (
      <View style={styles.center}>
        <Text style={styles.errTxt}>Verification session missing. Please sign in again.</Text>
        <Pressable style={styles.primaryBtn} onPress={() => router.replace("/admin-pin-login")}>
          <Text style={styles.primaryBtnTxt}>Back to sign in</Text>
        </Pressable>
      </View>
    );
  }

  const verify = async () => {
    setError(null);
    const code = otp.trim();
    if (!/^\d{6}$/.test(code)) { setError("Enter the 6-digit OTP"); return; }
    setBusy(true);
    try {
      const r = await api<any>("/auth/2fa/verify", {
        method: "POST", auth: false,
        body: { pending_token: pendingToken, otp: code, trust_device: trustDevice },
      });
      if (r.device_token) await saveDeviceToken(r.device_token);
      await saveToken(r.session_token);
      await refresh();
      router.replace(r.pin_must_change ? "/pin-change" : "/");
    } catch (e: any) {
      setError(e?.message || "Verification failed");
      setOtp("");
    } finally {
      setBusy(false);
    }
  };

  const resend = async (newMethod?: string) => {
    if (resending) return;
    setError(null); setInfo(null);
    setResending(true);
    try {
      const r = await api<any>("/auth/2fa/resend", {
        method: "POST", auth: false,
        body: { pending_token: pendingToken, method: newMethod || method },
      });
      setMethod(r.method);
      setCooldown(Number(r.resend_cooldown || 30));
      setExpiresIn(Number(r.otp_expires_in || 300));
      setOtp("");
      const note = String(r.delivery_note || "");
      if (note.startsWith("sent_to_admin:")) {
        setInfo(`OTP sent to the administrator's email (${note.split(":")[1] || ""}) — email provider is in TEST mode.`);
      } else if (r.delivered) {
        setInfo(`A new OTP was sent via ${METHOD_LABEL[r.method] || r.method}.`);
      } else {
        setError("We could not send the OTP using this method. Please try another verification method.");
      }
    } catch (e: any) {
      setError(e?.message || "Could not resend OTP");
    } finally {
      setResending(false);
    }
  };

  const target = method === "email" ? maskedEmail : maskedMobile;
  const otherMethods = methods.filter((m) => m.method !== method);
  const mm = Math.floor(expiresIn / 60);
  const ss = String(expiresIn % 60).padStart(2, "0");

  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.card} testID="verify-2fa-screen">
        <View style={styles.iconWrap}>
          <Ionicons name="shield-checkmark" size={28} color="#fff" />
        </View>
        <Text style={styles.title}>Verify Your Identity</Text>
        <Text style={styles.sub}>
          For your security, a one-time code is required to access the payroll portal.
        </Text>

        <View style={styles.sentBox}>
          <Ionicons name={METHOD_ICON[method] || "mail-outline"} size={16} color={colors.brandPrimary} />
          <Text style={styles.sentTxt}>
            OTP sent via {METHOD_LABEL[method] || method} to <Text style={styles.sentTarget}>{target || "your registered contact"}</Text>
          </Text>
        </View>
        {maskedEmail && maskedMobile ? (
          <Text style={styles.contactHint}>Email: {maskedEmail}   ·   Mobile: {maskedMobile}</Text>
        ) : null}

        <Text style={styles.label}>Enter 6-digit OTP</Text>
        <TextInput
          ref={inputRef}
          style={styles.otpInput}
          value={otp}
          onChangeText={(v) => setOtp(v.replace(/[^0-9]/g, "").slice(0, 6))}
          keyboardType="number-pad"
          maxLength={6}
          placeholder="○ ○ ○ ○ ○ ○"
          placeholderTextColor={colors.onSurfaceTertiary}
          autoFocus
          onSubmitEditing={verify}
          testID="2fa-otp-input"
        />
        <Text style={[styles.expiry, expiresIn === 0 && { color: "#dc2626" }]}>
          {expiresIn > 0 ? `OTP expires in ${mm}:${ss}` : "OTP expired — request a new one below"}
        </Text>

        {error ? <Text style={styles.errTxt}>{error}</Text> : null}
        {info ? <Text style={styles.infoTxt}>{info}</Text> : null}

        {trustedEnabled ? (
          <Pressable style={styles.trustRow} onPress={() => setTrustDevice(!trustDevice)} testID="2fa-trust-device">
            <Ionicons
              name={trustDevice ? "checkbox" : "square-outline"}
              size={20}
              color={trustDevice ? colors.brandPrimary : colors.onSurfaceTertiary}
            />
            <Text style={styles.trustTxt}>Trust this device for 30 days</Text>
          </Pressable>
        ) : null}

        <Pressable
          onPress={verify}
          disabled={busy || otp.length !== 6}
          style={[styles.primaryBtn, (busy || otp.length !== 6) && { opacity: 0.5 }]}
          testID="2fa-verify-btn"
        >
          {busy ? <ActivityIndicator color="#fff" /> : (
            <>
              <Ionicons name="lock-open-outline" size={16} color="#fff" />
              <Text style={styles.primaryBtnTxt}>Verify OTP</Text>
            </>
          )}
        </Pressable>

        <Pressable
          onPress={() => resend()}
          disabled={cooldown > 0 || resending}
          style={[styles.linkBtn, (cooldown > 0 || resending) && { opacity: 0.5 }]}
          testID="2fa-resend-btn"
        >
          {resending ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : (
            <Text style={styles.linkTxt}>
              {cooldown > 0 ? `Resend OTP in ${cooldown}s` : "Resend OTP"}
            </Text>
          )}
        </Pressable>

        {otherMethods.length > 0 ? (
          <View style={styles.altBox}>
            <Text style={styles.altTitle}>Unable to receive the OTP?</Text>
            {otherMethods.map((m) => (
              <Pressable
                key={m.method}
                onPress={() => m.configured && cooldown === 0 && resend(m.method)}
                disabled={!m.configured || cooldown > 0}
                style={[styles.altBtn, (!m.configured || cooldown > 0) && { opacity: 0.45 }]}
                testID={`2fa-alt-${m.method}`}
              >
                <Ionicons name={METHOD_ICON[m.method]} size={15} color={colors.brandPrimary} />
                <Text style={styles.altBtnTxt}>
                  Send OTP by {METHOD_LABEL[m.method]} ({m.target})
                  {!m.configured ? " — not configured" : ""}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}

        <Pressable onPress={() => router.replace("/admin-pin-login")} style={styles.backRow}>
          <Ionicons name="arrow-back" size={14} color={colors.onSurfaceSecondary} />
          <Text style={styles.backTxt}>Back to sign in</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1, backgroundColor: colors.surfaceSecondary,
    alignItems: "center", justifyContent: "center", padding: spacing.md,
  },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 14 },
  card: {
    width: "100%", maxWidth: 440,
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: 28, borderWidth: 1, borderColor: colors.border,
    ...(Platform.OS === "web" ? { boxShadow: "0 8px 30px rgba(0,0,0,0.08)" } as any : {}),
  },
  iconWrap: {
    alignSelf: "center", width: 56, height: 56, borderRadius: 28,
    backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center",
    marginBottom: 14,
  },
  title: { ...type.h4, color: colors.onSurface, fontWeight: "800", textAlign: "center" },
  sub: {
    ...type.caption, color: colors.onSurfaceSecondary, textAlign: "center",
    marginTop: 6, marginBottom: 16,
  },
  sentBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: 10, marginBottom: 6,
  },
  sentTxt: { flex: 1, fontSize: 12, color: colors.onSurfaceSecondary },
  sentTarget: { fontWeight: "800", color: colors.onSurface },
  contactHint: { fontSize: 11, color: colors.onSurfaceTertiary, textAlign: "center", marginBottom: 8 },
  label: {
    ...type.tiny, color: colors.onSurfaceSecondary, fontWeight: "700",
    textTransform: "uppercase", marginTop: 10, marginBottom: 6, textAlign: "center",
  },
  otpInput: {
    borderWidth: 2, borderColor: colors.brandPrimary, borderRadius: radius.md,
    paddingVertical: 14, textAlign: "center",
    fontSize: 26, fontWeight: "800", letterSpacing: 12,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  expiry: { fontSize: 11, color: colors.onSurfaceTertiary, textAlign: "center", marginTop: 8 },
  errTxt: { color: "#dc2626", fontSize: 12, fontWeight: "600", textAlign: "center", marginTop: 10 },
  infoTxt: { color: "#15803d", fontSize: 12, fontWeight: "600", textAlign: "center", marginTop: 10 },
  trustRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    justifyContent: "center", marginTop: 14,
  },
  trustTxt: { fontSize: 13, color: colors.onSurfaceSecondary },
  primaryBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingVertical: 13, marginTop: 16,
    flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 8,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 15 },
  linkBtn: { alignItems: "center", paddingVertical: 12 },
  linkTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 13 },
  altBox: {
    borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: 12, marginTop: 4,
  },
  altTitle: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 8 },
  altBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 8, paddingHorizontal: 10,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    marginBottom: 6, backgroundColor: colors.surfaceSecondary,
  },
  altBtnTxt: { fontSize: 12, color: colors.onSurface, fontWeight: "600", flex: 1 },
  backRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    justifyContent: "center", marginTop: 10,
  },
  backTxt: { fontSize: 12, color: colors.onSurfaceSecondary },
});
