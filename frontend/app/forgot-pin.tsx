import React, { useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

/**
 * Self-service admin PIN recovery. Users enter their email — if it
 * belongs to a company_admin or super_admin, a fresh 6-digit temp PIN
 * is emailed to them.
 */
export default function ForgotPinScreen() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const submit = async () => {
    setError(null);
    const e = email.trim().toLowerCase();
    if (!e || !e.includes("@")) {
      setError("Enter a valid email address");
      return;
    }
    setBusy(true);
    try {
      await api("/auth/forgot-pin", {
        method: "POST",
        auth: false,
        body: { identifier: e },
      });
      setSent(true);
    } catch (err: any) {
      setError(err.message || "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.root} testID="forgot-pin-screen">
      <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Forgot PIN</Text>
          <View style={{ width: 26 }} />
        </View>

        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
          <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            <View style={styles.iconWrap}>
              <Ionicons name="mail-open-outline" size={30} color={colors.onCta} />
            </View>

            {sent ? (
              <>
                <Text style={styles.title}>Check your inbox</Text>
                <Text style={styles.subtitle}>
                  If <Text style={{ fontWeight: "700" }}>{email}</Text> belongs to an administrator,
                  we&apos;ve just sent a fresh 6-digit temporary PIN to it. Open the email and use that
                  code to sign in. You&apos;ll be asked to set a new personal PIN on first sign-in.
                </Text>
                <View style={styles.tipsBox}>
                  <Row icon="time-outline" text="Email usually arrives within a minute" />
                  <Row icon="alert-circle-outline" text="Check Spam / Junk if not in Inbox" />
                  <Row icon="shield-checkmark-outline" text="Your previous PIN has been invalidated" />
                </View>
                <Pressable
                  style={styles.cta}
                  onPress={() => router.replace("/admin-pin-login")}
                  testID="forgot-pin-back-to-login"
                >
                  <Text style={styles.ctaTxt}>Back to sign in</Text>
                  <Ionicons name="arrow-forward" size={18} color={colors.onCta} />
                </Pressable>
              </>
            ) : (
              <>
                <Text style={styles.title}>Reset your admin PIN</Text>
                <Text style={styles.subtitle}>
                  Enter your registered admin email. We&apos;ll send a fresh temporary PIN so you can
                  sign in and pick a new one.
                </Text>
                <Text style={styles.label}>Registered email</Text>
                <TextInput
                  testID="forgot-pin-email"
                  value={email}
                  onChangeText={setEmail}
                  placeholder="you@company.com"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  autoCorrect={false}
                  style={styles.input}
                />

                {error && (
                  <View style={styles.errBox} testID="forgot-pin-error">
                    <Ionicons name="alert-circle" size={16} color={colors.onError} />
                    <Text style={styles.errTxt}>{error}</Text>
                  </View>
                )}

                <Pressable
                  testID="forgot-pin-submit"
                  style={[styles.cta, busy && { opacity: 0.7 }]}
                  onPress={submit}
                  disabled={busy}
                >
                  {busy ? (
                    <ActivityIndicator color={colors.onCta} />
                  ) : (
                    <>
                      <Text style={styles.ctaTxt}>Send temporary PIN</Text>
                      <Ionicons name="paper-plane" size={16} color={colors.onCta} />
                    </>
                  )}
                </Pressable>

                <Pressable onPress={() => router.back()} style={styles.altLink}>
                  <Ionicons name="arrow-back" size={14} color={colors.brandPrimary} />
                  <Text style={styles.altLinkTxt}>Back to sign in</Text>
                </Pressable>
              </>
            )}
          </KeyboardAwareScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}

function Row({ icon, text }: { icon: any; text: string }) {
  return (
    <View style={styles.tipRow}>
      <Ionicons name={icon} size={16} color={colors.brandPrimary} />
      <Text style={styles.tipTxt}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xl },
  iconWrap: {
    width: 60, height: 60, borderRadius: 30,
    backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
    alignSelf: "center",
    marginBottom: spacing.md,
  },
  title: { color: colors.onSurface, fontSize: type.xl, fontWeight: "800", textAlign: "center" },
  subtitle: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    lineHeight: 20,
    textAlign: "center",
    marginTop: 6,
    marginBottom: spacing.lg,
  },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "600", marginTop: spacing.md, marginBottom: 6 },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 14, paddingVertical: 12,
    color: colors.onSurface, fontSize: type.base,
  },
  errBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.error,
    borderRadius: radius.md,
    padding: spacing.sm,
    marginTop: spacing.md,
  },
  errTxt: { color: colors.onError, fontSize: type.sm, flex: 1 },
  cta: {
    marginTop: spacing.lg,
    backgroundColor: colors.cta,
    borderRadius: radius.pill,
    paddingVertical: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    ...shadow.cta,
  },
  ctaTxt: { color: colors.onCta, fontSize: type.lg, fontWeight: "700" },
  altLink: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    marginTop: spacing.lg,
  },
  altLinkTxt: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "600" },
  tipsBox: {
    alignSelf: "stretch",
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: 10,
    marginBottom: spacing.md,
  },
  tipRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  tipTxt: { color: colors.onSurface, fontSize: type.sm, flex: 1 },
});
