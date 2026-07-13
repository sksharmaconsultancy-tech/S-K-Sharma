/**
 * Employee Code + Phone-last-4 login gate - Iter 77.
 *
 * For bulk-imported employees (LAPL / KEPS) who never received a real email
 * and can't OTP via SMS (not wired), this lightweight route lets them sign
 * in with:
 *   - Employee Code   (printed on their ID card)
 *   - Last 4 digits of their phone   (shared secret with HR)
 *
 * Backend: POST /api/auth/emp-code-login
 */
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

export default function EmpCodeLoginScreen() {
  const { user, loading, refresh } = useAuth();
  const router = useRouter();

  const [empCode, setEmpCode] = useState("");
  const [last4, setLast4] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brandPrimary} />
      </View>
    );
  }
  if (user) return <Redirect href="/" />;

  const canSubmit = empCode.trim().length > 0 && /^\d{4}$/.test(last4);

  const submit = async () => {
    if (!canSubmit || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ session_token: string; user: any }>(
        "/auth/emp-code-login",
        {
          method: "POST",
          auth: false,
          body: {
            employee_code: empCode.trim(),
            phone_last4: last4.trim(),
          },
        },
      );
      await saveToken(res.session_token);
      await refresh();
      router.replace("/");
    } catch (e: any) {
      setError(e?.message || "Couldn't sign you in. Try again or contact HR.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top", "left", "right", "bottom"]}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <KeyboardAwareScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.hero}>
            <View style={styles.logoWrap}>
              <Ionicons name="card-outline" size={36} color={colors.brand} />
            </View>
            <Text style={styles.title}>Employee sign-in</Text>
            <Text style={styles.subtitle}>
              Enter your Employee Code and the last 4 digits of the phone
              number on file with HR — or your 4-digit PIN if no phone is
              registered.
            </Text>
          </View>

          <View style={styles.card}>
            <Text style={styles.label}>Employee Code</Text>
            <TextInput
              style={styles.input}
              value={empCode}
              onChangeText={(t) => setEmpCode(t.replace(/[^0-9A-Za-z\-]/g, "").slice(0, 12))}
              placeholder="e.g. 0004"
              placeholderTextColor={colors.onSurfaceTertiary}
              autoCapitalize="characters"
              autoCorrect={false}
              testID="emp-code-input"
            />

            <Text style={[styles.label, { marginTop: spacing.md }]}>
              Phone last 4 digits — or your PIN
            </Text>
            <TextInput
              style={styles.input}
              value={last4}
              onChangeText={(t) => setLast4(t.replace(/\D/g, "").slice(0, 4))}
              placeholder="e.g. 9206 or 1234"
              placeholderTextColor={colors.onSurfaceTertiary}
              keyboardType="number-pad"
              maxLength={4}
              testID="emp-last4-input"
            />

            {error ? (
              <View style={styles.errBox}>
                <Ionicons name="alert-circle" size={14} color={colors.error} />
                <Text style={styles.errText}>{error}</Text>
              </View>
            ) : null}

            <Pressable
              onPress={submit}
              disabled={!canSubmit || busy}
              style={[styles.submitBtn, (!canSubmit || busy) && { opacity: 0.5 }]}
              testID="emp-code-submit"
            >
              {busy ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="log-in-outline" size={16} color="#fff" />
                  <Text style={styles.submitTxt}>Sign in</Text>
                </>
              )}
            </Pressable>

            <View style={styles.dividerRow}>
              <View style={styles.dividerLine} />
              <Text style={styles.dividerTxt}>or</Text>
              <View style={styles.dividerLine} />
            </View>

            <Pressable
              onPress={() => router.replace("/otp-login")}
              style={styles.altBtn}
              testID="use-otp-instead"
            >
              <Ionicons name="mail-outline" size={16} color={colors.brand} />
              <Text style={styles.altTxt}>Sign in with email OTP instead</Text>
            </Pressable>
          </View>

          <View style={styles.footer}>
            <Text style={styles.footerTxt}>
              Don&apos;t remember your code?{" "}
              <Text style={styles.footerTxtBold}>Contact HR</Text>.
            </Text>
          </View>
        </KeyboardAwareScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  scroll: { padding: spacing.lg, gap: spacing.md, minHeight: "100%" },
  hero: { alignItems: "center", marginTop: spacing.md, gap: spacing.xs },
  logoWrap: {
    width: 72, height: 72, borderRadius: 36,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(31, 82, 84, 0.08)",
    marginBottom: spacing.sm,
  },
  title: {
    fontSize: type.h1,
    fontWeight: "800",
    color: colors.onSurface,
    textAlign: "center",
  },
  subtitle: {
    fontSize: type.sm,
    color: colors.onSurfaceSecondary,
    textAlign: "center",
    paddingHorizontal: spacing.md,
    lineHeight: 20,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.divider,
    ...shadow.card,
    gap: 6,
  },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "600" },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 10,
    paddingHorizontal: 12,
    color: colors.onSurface,
    backgroundColor: colors.surface,
    fontSize: type.md,
    ...Platform.select({ web: { outlineWidth: 0 as any } }),
  },
  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: spacing.sm,
    padding: 8,
    borderRadius: radius.md,
    backgroundColor: "rgba(220, 38, 38, 0.08)",
  },
  errText: { color: colors.error, fontSize: type.sm, flex: 1 },
  submitBtn: {
    marginTop: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 14,
    borderRadius: radius.md,
    backgroundColor: colors.brand,
    ...shadow.cta,
  },
  submitTxt: { color: "#fff", fontWeight: "800", fontSize: type.md },
  dividerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: spacing.md,
    marginBottom: 4,
  },
  dividerLine: { flex: 1, height: 1, backgroundColor: colors.divider },
  dividerTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm },
  altBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brand,
  },
  altTxt: { color: colors.brand, fontWeight: "700", fontSize: type.sm },
  footer: { alignItems: "center", marginTop: spacing.lg },
  footerTxt: { color: colors.onSurfaceSecondary, fontSize: type.sm },
  footerTxtBold: { fontWeight: "700", color: colors.onSurface },
});
