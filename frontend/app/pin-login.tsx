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

/**
 * Employee sign-in — supports 4 identifier types: Mobile / UAN / ESI IP / PF No
 * + 6-digit PIN. A "Create new account" link at the bottom routes to signup.
 *
 * The alternate identifiers (UAN, ESI IP, PF No.) support the self-service
 * portal login requested in Iter 61 — employees who don't remember the phone
 * number they registered with can log in using any of these government IDs
 * printed on their payslip.
 */
type IdentType = "phone" | "login_id";

const IDENT_TABS: { key: IdentType; label: string; icon: keyof typeof Ionicons.glyphMap; placeholder: string; keyboardType: "phone-pad" | "number-pad" | "default" }[] = [
  { key: "phone", label: "Mobile", icon: "call-outline", placeholder: "+91 98765 43210", keyboardType: "phone-pad" },
  { key: "login_id", label: "Username", icon: "person-circle-outline", placeholder: "Username from employer", keyboardType: "default" },
];

export default function PinLoginScreen() {
  const { user, loading, refresh } = useAuth();
  const router = useRouter();

  const [identType, setIdentType] = useState<IdentType>("phone");
  const [ident, setIdent] = useState("");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPin, setShowPin] = useState(false);
  // Iter 96l — username logins can use a PIN or an employer-set password.
  const [secretMode, setSecretMode] = useState<"pin" | "password">("pin");
  const usernameMode = identType === "login_id";

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
    const v = ident.trim();
    const p = pin.trim();
    if (!v) {
      setError(`Enter your ${IDENT_TABS.find((t) => t.key === identType)?.label || "identifier"}`);
      return;
    }
    if (identType === "phone" && v.replace(/\D/g, "").length < 8) {
      setError("Enter a valid mobile number");
      return;
    }

    // Username + Password path (employer-set credentials).
    if (usernameMode && secretMode === "password") {
      if (!p) { setError("Enter your password"); return; }
      setBusy(true);
      try {
        const r = await api<{ session_token: string; user: any; password_must_change: boolean }>(
          "/auth/employee-password-login",
          { method: "POST", auth: false, body: { login_id: v, password: p } },
        );
        await saveToken(r.session_token);
        await refresh();
        router.replace("/(tabs)");
      } catch (e: any) {
        setError(e.message || "Sign-in failed");
      } finally {
        setBusy(false);
      }
      return;
    }

    // PIN path (all identifier types).
    if (!/^\d{6}$/.test(p)) {
      setError("PIN must be exactly 6 digits");
      return;
    }
    setBusy(true);
    try {
      const body: any = { pin: p };
      body[identType] = v;
      const r = await api<{ session_token: string; user: any; pin_must_change: boolean }>(
        "/auth/pin-login",
        {
          method: "POST",
          auth: false,
          body,
        },
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
    <View style={styles.root} testID="pin-login-screen">
      <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Employee sign in</Text>
          <View style={{ width: 26 }} />
        </View>

        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
          <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            <View style={styles.iconWrap}>
              <Ionicons name="person" size={30} color={colors.onCta} />
            </View>
            <Text style={styles.title}>Sign in to your account</Text>
            <Text style={styles.subtitle}>
              Use your mobile number or the username your employer gave you.
            </Text>

            {/* Identifier type picker */}
            <View style={styles.identTabsRow}>
              {IDENT_TABS.map((t) => (
                <Pressable
                  key={t.key}
                  onPress={() => {
                    setIdentType(t.key);
                    setIdent("");
                    setPin("");
                    setSecretMode("pin");
                    setError(null);
                  }}
                  style={[styles.identTab, identType === t.key && styles.identTabActive]}
                  testID={`pin-ident-${t.key}`}
                >
                  <Ionicons
                    name={t.icon}
                    size={14}
                    color={identType === t.key ? "#fff" : colors.onSurfaceSecondary}
                  />
                  <Text
                    style={[
                      styles.identTabTxt,
                      { color: identType === t.key ? "#fff" : colors.onSurfaceSecondary },
                    ]}
                  >
                    {t.label}
                  </Text>
                </Pressable>
              ))}
            </View>

            <Text style={styles.label}>{IDENT_TABS.find((t) => t.key === identType)?.label}</Text>
            <TextInput
              testID="pin-phone-input"
              value={ident}
              onChangeText={setIdent}
              placeholder={IDENT_TABS.find((t) => t.key === identType)?.placeholder}
              placeholderTextColor={colors.onSurfaceTertiary}
              keyboardType={IDENT_TABS.find((t) => t.key === identType)?.keyboardType || "default"}
              autoCapitalize={identType === "phone" ? "none" : "none"}
              autoCorrect={false}
              style={styles.input}
            />

            {usernameMode && (
              <View style={styles.identTabsRow}>
                {(["pin", "password"] as const).map((mkey) => (
                  <Pressable
                    key={mkey}
                    onPress={() => { setSecretMode(mkey); setPin(""); setError(null); }}
                    style={[styles.identTab, secretMode === mkey && styles.identTabActive]}
                    testID={`pin-mode-${mkey}`}
                  >
                    <Ionicons
                      name={mkey === "pin" ? "keypad-outline" : "lock-closed-outline"}
                      size={14}
                      color={secretMode === mkey ? "#fff" : colors.onSurfaceSecondary}
                    />
                    <Text style={[styles.identTabTxt, { color: secretMode === mkey ? "#fff" : colors.onSurfaceSecondary }]}>
                      {mkey === "pin" ? "PIN" : "Password"}
                    </Text>
                  </Pressable>
                ))}
              </View>
            )}

            <Text style={styles.label}>{usernameMode && secretMode === "password" ? "Password" : "PIN"}</Text>
            <View style={styles.pinRow}>
              <TextInput
                testID="pin-pin-input"
                value={pin}
                onChangeText={(t) =>
                  usernameMode && secretMode === "password"
                    ? setPin(t)
                    : setPin(t.replace(/\D/g, "").slice(0, 6))
                }
                placeholder={usernameMode && secretMode === "password" ? "Your password" : "6-digit PIN"}
                placeholderTextColor={colors.onSurfaceTertiary}
                keyboardType={usernameMode && secretMode === "password" ? "default" : "number-pad"}
                autoCapitalize="none"
                autoCorrect={false}
                secureTextEntry={!showPin}
                maxLength={usernameMode && secretMode === "password" ? 64 : 6}
                style={[styles.input, { flex: 1, marginTop: 0 }]}
              />
              <Pressable onPress={() => setShowPin((v) => !v)} hitSlop={8} style={styles.eyeBtn}>
                <Ionicons
                  name={showPin ? "eye-off-outline" : "eye-outline"}
                  size={20}
                  color={colors.onSurfaceSecondary}
                />
              </Pressable>
            </View>

            {error && (
              <View style={styles.errBox} testID="pin-error">
                <Ionicons name="alert-circle" size={16} color={colors.onError} />
                <Text style={styles.errTxt}>{error}</Text>
              </View>
            )}

            <Pressable
              testID="pin-submit"
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

            <View style={styles.dividerRow}>
              <View style={styles.dividerLine} />
              <Text style={styles.dividerTxt}>New employee?</Text>
              <View style={styles.dividerLine} />
            </View>

            <Pressable
              onPress={() => router.push("/employee-signup")}
              style={styles.signupBtn}
              testID="employee-signup-link"
            >
              <Ionicons name="person-add-outline" size={16} color={colors.brandPrimary} />
              <Text style={styles.signupTxt}>Create new employee account</Text>
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
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    lineHeight: 20,
    textAlign: "center",
    marginTop: 6,
    marginBottom: spacing.lg,
  },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "600", marginTop: spacing.md, marginBottom: 6 },
  identTabsRow: {
    flexDirection: "row",
    gap: 6,
    marginTop: spacing.md,
    flexWrap: "wrap",
  },
  identTab: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.divider,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  identTabActive: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  identTabTxt: { fontSize: 12, fontWeight: "700" },
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
  dividerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginTop: spacing.xl,
    marginBottom: spacing.md,
  },
  dividerLine: { flex: 1, height: 1, backgroundColor: colors.border },
  dividerTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm },
  signupBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderRadius: radius.pill,
    paddingVertical: 14,
  },
  signupTxt: { color: colors.brandPrimary, fontSize: type.base, fontWeight: "700" },
  altLink: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    marginTop: spacing.lg,
  },
  altLinkTxt: { color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "600" },
});
