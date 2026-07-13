import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";

import { api, saveToken } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

/**
 * Company (employer) sign-in — Mobile OR Email + 6-digit PIN.
 * Logs in as company_admin. A "Register your company" link at the
 * bottom routes to the self-registration flow.
 */
export default function CompanyLoginScreen() {
  const { user, loading, refresh } = useAuth();
  const router = useRouter();

  type Mode = "identifier" | "code";
  const [mode, setMode] = useState<Mode>("identifier");
  const [identifier, setIdentifier] = useState("");
  const [companyCode, setCompanyCode] = useState("");
  // Iter 106 — firm QR codes land here with ?company=<CODE>: prefill the
  // company-code login mode so the employer only types their user + PIN.
  const params = useLocalSearchParams<{ company?: string }>();
  useEffect(() => {
    const c = (params?.company as string) || "";
    if (c) {
      setCompanyCode(c.toUpperCase());
      setMode("code");
    }
  }, [params?.company]);
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPin, setShowPin] = useState(false);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brandPrimary} />
      </View>
    );
  }
  if (user) {
    if (user.pin_must_change) return <Redirect href="/pin-change" />;
    return <Redirect href="/(tabs)" />;
  }

  const submit = async () => {
    setError(null);
    const p = pin.trim();
    if (!/^\d{6}$/.test(p)) {
      setError("PIN must be exactly 6 digits");
      return;
    }
    let body: Record<string, string> = { pin: p };
    if (mode === "identifier") {
      const id = identifier.trim();
      if (!id) {
        setError("Enter your registered mobile number or email");
        return;
      }
      body.identifier = id;
    } else {
      const code = companyCode.trim().toUpperCase();
      if (!code) {
        setError("Enter your company code");
        return;
      }
      body.company_code = code;
    }
    setBusy(true);
    try {
      const r = await api<{ session_token: string; pin_must_change: boolean }>(
        "/auth/admin-pin-login",
        { method: "POST", auth: false, body },
      );
      await saveToken(r.session_token);
      await refresh();
      router.replace(r.pin_must_change ? "/pin-change" : "/(tabs)");
    } catch (e: any) {
      setError(e.message || "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.root} testID="company-login-screen">
      <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
        <View style={[styles.header, Platform.OS === "web" && styles.headerWeb]}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={[styles.h1, Platform.OS === "web" && styles.h1Web]}>
            Company sign in
          </Text>
          <View style={{ width: 26 }} />
        </View>

        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
          <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            <View style={[styles.iconWrap, Platform.OS === "web" && styles.iconWrapWeb]}>
              <Ionicons name="business" size={30} color={Platform.OS === "web" ? "#0369A1" : colors.onCta} />
            </View>
            <Text style={styles.title}>Company admin sign in</Text>
            <Text style={styles.subtitle}>
              Sign in with your registered mobile/email OR your firm{"'"}s
              Company Code, along with your 6-digit PIN.
            </Text>

            <View style={styles.modeRow} testID="company-mode-row">
              <Pressable
                testID="company-mode-identifier"
                style={[
                  styles.modeBtn,
                  mode === "identifier" && styles.modeBtnOn,
                ]}
                onPress={() => {
                  setError(null);
                  setMode("identifier");
                }}
              >
                <Ionicons
                  name="mail-outline"
                  size={14}
                  color={mode === "identifier" ? "#fff" : colors.brandPrimary}
                />
                <Text
                  style={[
                    styles.modeTxt,
                    mode === "identifier" && styles.modeTxtOn,
                  ]}
                >
                  Mobile / Email
                </Text>
              </Pressable>
              <Pressable
                testID="company-mode-code"
                style={[styles.modeBtn, mode === "code" && styles.modeBtnOn]}
                onPress={() => {
                  setError(null);
                  setMode("code");
                }}
              >
                <Ionicons
                  name="key-outline"
                  size={14}
                  color={mode === "code" ? "#fff" : colors.brandPrimary}
                />
                <Text
                  style={[styles.modeTxt, mode === "code" && styles.modeTxtOn]}
                >
                  Company Code
                </Text>
              </Pressable>
            </View>

            {mode === "identifier" ? (
              <>
                <Text style={styles.label}>Mobile or email</Text>
                <TextInput
                  testID="company-identifier-input"
                  value={identifier}
                  onChangeText={setIdentifier}
                  placeholder="+91 98765 43210  or  admin@yourfirm.com"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  autoCapitalize="none"
                  autoCorrect={false}
                  keyboardType="email-address"
                  style={styles.input}
                />
              </>
            ) : (
              <>
                <Text style={styles.label}>Company code</Text>
                <TextInput
                  testID="company-code-input"
                  value={companyCode}
                  onChangeText={(t) =>
                    setCompanyCode(t.replace(/\s/g, "").toUpperCase())
                  }
                  placeholder="e.g. ABC123"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  autoCapitalize="characters"
                  autoCorrect={false}
                  style={styles.input}
                  maxLength={16}
                />
                <Text style={styles.hintTxt}>
                  Shared with you when your company was registered. Case does
                  not matter.
                </Text>
              </>
            )}

            <Text style={styles.label}>PIN</Text>
            <View style={styles.pinRow}>
              <TextInput
                testID="company-pin-input"
                value={pin}
                onChangeText={(t) => setPin(t.replace(/\D/g, "").slice(0, 6))}
                placeholder="6-digit PIN"
                placeholderTextColor={colors.onSurfaceTertiary}
                keyboardType="number-pad"
                secureTextEntry={!showPin}
                maxLength={6}
                style={[styles.input, { flex: 1, marginTop: 0 }]}
              />
              <Pressable onPress={() => setShowPin((v) => !v)} hitSlop={8} style={styles.eyeBtn}>
                <Ionicons name={showPin ? "eye-off-outline" : "eye-outline"} size={20} color={colors.onSurfaceSecondary} />
              </Pressable>
            </View>

            {error && (
              <View style={styles.errBox} testID="company-login-error">
                <Ionicons name="alert-circle" size={16} color={colors.onError} />
                <Text style={styles.errTxt}>{error}</Text>
              </View>
            )}

            <Pressable
              testID="company-login-submit"
              style={[styles.cta, busy && { opacity: 0.7 }]}
              onPress={submit}
              disabled={busy}
            >
              {busy ? (
                <ActivityIndicator color={colors.onCta} />
              ) : (
                <>
                  <Text style={styles.ctaTxt}>Sign in</Text>
                  <Ionicons name="arrow-forward" size={18} color={colors.onCta} />
                </>
              )}
            </Pressable>

            <Pressable onPress={() => router.push("/forgot-pin")} style={styles.forgotLink} testID="company-forgot-pin">
              <Text style={styles.forgotTxt}>Forgot PIN?</Text>
            </Pressable>

            <View style={styles.dividerRow}>
              <View style={styles.dividerLine} />
              <Text style={styles.dividerTxt}>Not registered yet?</Text>
              <View style={styles.dividerLine} />
            </View>

            <Pressable
              onPress={() => router.push("/company-register")}
              style={styles.signupBtn}
              testID="company-register-link"
            >
              <Ionicons name="business-outline" size={16} color={colors.brandPrimary} />
              <Text style={styles.signupTxt}>Register your company</Text>
            </Pressable>
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
    color: colors.onSurfaceSecondary, fontSize: type.sm, lineHeight: 20,
    textAlign: "center", marginTop: 6, marginBottom: spacing.lg,
  },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "600", marginTop: spacing.md, marginBottom: 6 },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 14, paddingVertical: 12,
    color: colors.onSurface, fontSize: type.base,
  },
  pinRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  eyeBtn: { padding: 8 },
  errBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.error, borderRadius: radius.md,
    padding: spacing.sm, marginTop: spacing.md,
  },
  errTxt: { color: colors.onError, fontSize: type.sm, flex: 1 },
  cta: {
    marginTop: spacing.lg,
    backgroundColor: colors.cta, borderRadius: radius.pill,
    paddingVertical: 16, flexDirection: "row",
    alignItems: "center", justifyContent: "center", gap: 8,
    ...shadow.cta,
  },
  ctaTxt: { color: colors.onCta, fontSize: type.lg, fontWeight: "700" },
  forgotLink: { alignSelf: "center", padding: spacing.sm, marginTop: spacing.sm },
  forgotTxt: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "600", textDecorationLine: "underline" },
  dividerRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    marginTop: spacing.xl, marginBottom: spacing.md,
  },
  dividerLine: { flex: 1, height: 1, backgroundColor: colors.border },
  dividerTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm },
  signupBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    borderWidth: 1, borderColor: colors.brandPrimary,
    borderRadius: radius.pill, paddingVertical: 14,
  },
  signupTxt: { color: colors.brandPrimary, fontSize: type.base, fontWeight: "700" },
  modeRow: {
    flexDirection: "row",
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.pill,
    padding: 4,
    marginTop: spacing.md,
    gap: 4,
  },
  modeBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    borderRadius: radius.pill,
  },
  modeBtnOn: {
    backgroundColor: colors.brandPrimary,
  },
  modeTxt: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "700",
  },
  modeTxtOn: {
    color: "#fff",
  },
  hintTxt: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    marginTop: 6,
    lineHeight: 18,
  },
});
