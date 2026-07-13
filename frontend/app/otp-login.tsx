import React, { useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api, saveToken } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

type Channel = "sms" | "email";
type Step = "identifier" | "code";

export default function OtpLoginScreen() {
  const { user, loading, refresh } = useAuth();
  const router = useRouter();

  const [channel] = useState<Channel>("email");
  const [identifier, setIdentifier] = useState("");
  const [step, setStep] = useState<Step>("identifier");
  const [code, setCode] = useState("");
  const [devCode, setDevCode] = useState<string | null>(null);
  const [delivered, setDelivered] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);

  React.useEffect(() => {
    if (secondsLeft <= 0) return;
    const t = setTimeout(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearTimeout(t);
  }, [secondsLeft]);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brandPrimary} />
      </View>
    );
  }
  if (user) {
    if (user.role === "employee" && !user.onboarded) return <Redirect href="/onboarding" />;
    return <Redirect href="/(tabs)" />;
  }

  const sendOtp = async () => {
    setError(null);
    setDevCode(null);
    const ident = identifier.trim();
    if (!ident) {
      setError(channel === "sms" ? "Enter your phone number" : "Enter your email");
      return;
    }
    setBusy(true);
    try {
      const r = await api<{ expires_in: number; dev_code?: string; dev_note?: string; delivered?: boolean; delivery_error?: string }>(
        "/auth/otp/request",
        { method: "POST", auth: false, body: { identifier: ident, channel } },
      );
      if (r.dev_code) setDevCode(r.dev_code);
      setDelivered(!!r.delivered);
      setSecondsLeft(Math.min(60, r.expires_in || 60));
      setStep("code");
    } catch (e: any) {
      setError(e.message || "Failed to send code");
    } finally {
      setBusy(false);
    }
  };

  const verifyOtp = async () => {
    setError(null);
    if (!/^\d{6}$/.test(code.trim())) {
      setError("Enter the 6-digit code");
      return;
    }
    setBusy(true);
    try {
      const r = await api<{ session_token: string; user: any }>(
        "/auth/otp/verify",
        {
          method: "POST",
          auth: false,
          body: { identifier: identifier.trim(), code: code.trim(), channel },
        },
      );
      await saveToken(r.session_token);
      await refresh();
      // Redirect handled by top-level guard once user is set
      if (r.user?.role === "employee" && !r.user?.onboarded) router.replace("/onboarding");
      else router.replace("/(tabs)");
    } catch (e: any) {
      setError(e.message || "Verification failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.root} testID="otp-login-screen">
      <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Sign in with OTP</Text>
          <View style={{ width: 26 }} />
        </View>

        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={{ flex: 1 }}
        >
          <KeyboardAwareScrollView bottomOffset={62}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.scroll}
          >
            {step === "identifier" ? (
              <>
                <View style={styles.iconWrap}>
                  <Ionicons name="chatbubble-ellipses-outline" size={30} color={colors.accent} />
                </View>
                <Text style={styles.title}>Get a login code</Text>
                <Text style={styles.subtitle}>
                  We&apos;ll email you a 6-digit code to verify your identity.
                  No password needed.
                </Text>

                <Text style={styles.label}>Email address</Text>
                <TextInput
                  testID="otp-identifier-input"
                  value={identifier}
                  onChangeText={setIdentifier}
                  placeholder="you@company.com"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  autoCorrect={false}
                  style={styles.input}
                />

                {error && <Text style={styles.err}>{error}</Text>}

                <Pressable
                  testID="otp-send"
                  style={[styles.cta, busy && { opacity: 0.7 }]}
                  onPress={sendOtp}
                  disabled={busy}
                >
                  {busy ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <>
                      <Text style={styles.ctaTxt}>Send code</Text>
                      <Ionicons name="arrow-forward" size={18} color="#fff" />
                    </>
                  )}
                </Pressable>

                {/* Iter 77 - Employee Code + Phone-last-4 alt route */}
                <Pressable
                  testID="switch-to-emp-code"
                  style={styles.altRow}
                  onPress={() => router.push("/emp-code-login")}
                >
                  <Ionicons name="card-outline" size={16} color={colors.brand} />
                  <Text style={styles.altRowTxt}>
                    Employee? Sign in with your Employee Code
                  </Text>
                  <Ionicons name="chevron-forward" size={16} color={colors.brand} />
                </Pressable>
              </>
            ) : (
              <>
                <View style={styles.iconWrap}>
                  <Ionicons name="lock-closed-outline" size={30} color={colors.accent} />
                </View>
                <Text style={styles.title}>Enter the 6-digit code</Text>
                <Text style={styles.subtitle}>
                  Sent to <Text style={{ fontWeight: "700" }}>{identifier}</Text>{"  "}
                  <Text
                    style={styles.changeLink}
                    onPress={() => { setStep("identifier"); setCode(""); setDevCode(null); }}
                  >
                    (change)
                  </Text>
                </Text>

                {delivered && (
                  <View style={styles.deliveredBox} testID="otp-delivered">
                    <Ionicons name="checkmark-circle" size={14} color="#218739" />
                    <Text style={styles.deliveredTxt}>
                      Email sent. Use the code from the <Text style={{ fontWeight: "700" }}>most recent</Text> message —
                      older codes are no longer valid. Check Spam if you don&apos;t see it in Inbox.
                    </Text>
                  </View>
                )}

                {devCode && (
                  <View style={styles.devBox} testID="otp-dev-code">
                    <Ionicons name="warning-outline" size={14} color={colors.onAccentTint} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.devLbl}>
                        {delivered ? "BACKUP CODE (dev mode)" : "DEV MODE"}
                      </Text>
                      <Text style={styles.devVal}>{devCode}</Text>
                      <Text style={styles.devHint}>
                        {delivered
                          ? "Same code sent to your email. Also shown here as a backup while dev mode is on."
                          : "Email delivery failed — you can use this code to sign in for now."}
                      </Text>
                    </View>
                  </View>
                )}

                <Text style={styles.label}>Code</Text>
                <TextInput
                  testID="otp-code-input"
                  value={code}
                  onChangeText={setCode}
                  placeholder="000000"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="number-pad"
                  maxLength={6}
                  style={[styles.input, styles.codeInput]}
                />

                {error && <Text style={styles.err}>{error}</Text>}

                <Pressable
                  testID="otp-verify"
                  style={[styles.cta, busy && { opacity: 0.7 }]}
                  onPress={verifyOtp}
                  disabled={busy}
                >
                  {busy ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <Text style={styles.ctaTxt}>Verify & sign in</Text>
                  )}
                </Pressable>

                <Pressable
                  testID="otp-resend"
                  style={styles.secondary}
                  onPress={sendOtp}
                  disabled={busy || secondsLeft > 0}
                >
                  <Text style={styles.secondaryTxt}>
                    {secondsLeft > 0 ? `Resend in ${secondsLeft}s` : "Resend code"}
                  </Text>
                </Pressable>
              </>
            )}
          </KeyboardAwareScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { fontSize: type.lg, color: colors.onSurface, fontWeight: "700" },
  scroll: { padding: spacing.lg },
  iconWrap: {
    width: 60, height: 60, borderRadius: 30,
    backgroundColor: colors.ctaTint,
    alignItems: "center", justifyContent: "center",
    marginBottom: spacing.md,
  },
  title: {
    color: colors.onSurface, fontSize: type.xl, fontWeight: "700",
    letterSpacing: -0.3,
  },
  subtitle: {
    color: colors.onSurfaceSecondary, fontSize: type.base, lineHeight: 20,
    marginTop: 6,
  },
  changeLink: { color: colors.accent, fontWeight: "600" },
  channelRow: {
    flexDirection: "row", gap: 8, marginTop: spacing.lg,
  },
  channelChip: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 12, paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  channelChipActive: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  channelTxt: { color: colors.onSurfaceSecondary, fontSize: type.base, fontWeight: "600" },
  channelTxtActive: { color: "#fff" },
  label: {
    color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: spacing.lg,
  },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, color: colors.onSurface, fontSize: type.base,
    marginTop: 6, backgroundColor: colors.surfaceSecondary,
  },
  codeInput: {
    fontSize: 26, letterSpacing: 12, textAlign: "center", fontWeight: "700",
  },
  err: { color: colors.error, fontSize: type.sm, marginTop: spacing.md },
  cta: {
    marginTop: spacing.lg, backgroundColor: colors.cta,
    paddingVertical: 16, borderRadius: radius.pill,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    ...shadow.cta,
  },
  ctaTxt: { color: colors.onCta, fontSize: type.lg, fontWeight: "700" },
  secondary: {
    marginTop: spacing.md, paddingVertical: 12,
    alignItems: "center", justifyContent: "center",
  },
  secondaryTxt: { color: colors.brandPrimary, fontSize: type.base, fontWeight: "600" },
  devBox: {
    flexDirection: "row", gap: 10,
    marginTop: spacing.lg,
    backgroundColor: colors.ctaTint,
    padding: spacing.md,
    borderRadius: radius.md,
    alignItems: "flex-start",
  },
  devLbl: { color: colors.onAccentTint, fontSize: 10, letterSpacing: 1, fontWeight: "700" },
  devVal: {
    color: colors.onSurface, fontSize: 26, fontWeight: "700",
    letterSpacing: 8, marginTop: 4,
  },
  devHint: { color: colors.onAccentTint, fontSize: type.sm, marginTop: 4, lineHeight: 18 },
  deliveredBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    backgroundColor: "#E7F5EA",
    borderRadius: radius.md,
    padding: spacing.sm,
    marginTop: spacing.sm,
    borderWidth: 1,
    borderColor: "#B7E0C0",
  },
  deliveredTxt: {
    flex: 1,
    color: "#0F5B22",
    fontSize: type.sm,
    lineHeight: 18,
  },
  // Iter 77 - Alt-login row
  altRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    marginTop: spacing.md,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brand,
    backgroundColor: "rgba(31, 82, 84, 0.06)",
  },
  altRowTxt: {
    color: colors.brand,
    fontWeight: "700",
    fontSize: type.sm,
    flexShrink: 1,
    textAlign: "center",
  },
});
