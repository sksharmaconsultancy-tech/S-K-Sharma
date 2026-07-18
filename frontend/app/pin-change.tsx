import React, { useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

/**
 * Forced PIN change screen. Users land here when `pin_must_change` is
 * true on the server (e.g. after an admin resets their PIN or on first
 * login with an auto-generated temp PIN).
 */
export default function PinChangeScreen() {
  const { user, loading, refresh, logout } = useAuth();
  const router = useRouter();

  const [currentPin, setCurrentPin] = useState("");
  const [newPin, setNewPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brandPrimary} />
      </View>
    );
  }
  if (!user) return <Redirect href="/" />;
  if (!user.pin_must_change && !success) return <Redirect href="/(tabs)" />;

  const submit = async () => {
    setError(null);
    const cur = currentPin.trim();
    const nu = newPin.trim();
    const cf = confirmPin.trim();
    if (!/^\d{6}$/.test(cur)) { setError("Current PIN must be 6 digits"); return; }
    if (!/^\d{6}$/.test(nu)) { setError("New PIN must be exactly 6 digits"); return; }
    if (nu !== cf) { setError("New PIN and confirmation do not match"); return; }
    if (nu === cur) { setError("New PIN must be different from current PIN"); return; }
    if (new Set(nu).size === 1) { setError("PIN cannot be all the same digit"); return; }
    if (["123456", "654321", "000000", "111111"].includes(nu)) {
      setError("Please choose a less obvious PIN");
      return;
    }
    setBusy(true);
    try {
      await api("/auth/pin-change", {
        method: "POST",
        body: { current_pin: cur, new_pin: nu },
      });
      setSuccess(true);
      await refresh();
      // Iter 184 — root guard routes admins to the Portal Dashboard.
      router.replace("/");
    } catch (e: any) {
      setError(e.message || "Could not change PIN");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.root} testID="pin-change-screen">
      <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={{ flex: 1 }}
        >
          <KeyboardAwareScrollView bottomOffset={62}
            contentContainerStyle={styles.scroll}
            keyboardShouldPersistTaps="handled"
          >
            <View style={styles.iconWrap}>
              <Ionicons name="key" size={30} color={colors.onCta} />
            </View>
            <Text style={styles.title}>Set a new PIN</Text>
            <Text style={styles.subtitle}>
              For your security, please change the temporary PIN before continuing.
            </Text>

            <Text style={styles.label}>Current PIN (temporary)</Text>
            <TextInput
              testID="pin-change-current"
              value={currentPin}
              onChangeText={(t) => setCurrentPin(t.replace(/\D/g, "").slice(0, 6))}
              placeholder="6-digit temp PIN"
              placeholderTextColor={colors.onSurfaceTertiary}
              keyboardType="number-pad"
              secureTextEntry
              maxLength={6}
              style={styles.input}
            />

            <Text style={styles.label}>New PIN</Text>
            <TextInput
              testID="pin-change-new"
              value={newPin}
              onChangeText={(t) => setNewPin(t.replace(/\D/g, "").slice(0, 6))}
              placeholder="Choose a 6-digit PIN"
              placeholderTextColor={colors.onSurfaceTertiary}
              keyboardType="number-pad"
              secureTextEntry
              maxLength={6}
              style={styles.input}
            />

            <Text style={styles.label}>Confirm new PIN</Text>
            <TextInput
              testID="pin-change-confirm"
              value={confirmPin}
              onChangeText={(t) => setConfirmPin(t.replace(/\D/g, "").slice(0, 6))}
              placeholder="Repeat your new PIN"
              placeholderTextColor={colors.onSurfaceTertiary}
              keyboardType="number-pad"
              secureTextEntry
              maxLength={6}
              style={styles.input}
            />

            {error && (
              <View style={styles.errBox} testID="pin-change-error">
                <Ionicons name="alert-circle" size={16} color={colors.onError} />
                <Text style={styles.errTxt}>{error}</Text>
              </View>
            )}

            <Pressable
              testID="pin-change-submit"
              style={[styles.cta, busy && { opacity: 0.7 }]}
              onPress={submit}
              disabled={busy}
            >
              {busy ? (
                <ActivityIndicator color={colors.onCta} />
              ) : (
                <>
                  <Text style={styles.ctaTxt}>Save new PIN</Text>
                  <Ionicons name="checkmark" size={18} color={colors.onCta} />
                </>
              )}
            </Pressable>

            <Pressable onPress={() => logout()} style={styles.altLink} testID="pin-change-signout">
              <Text style={styles.altLinkTxt}>Sign out</Text>
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
  scroll: { padding: spacing.lg, paddingBottom: spacing.xl },
  iconWrap: {
    width: 60, height: 60, borderRadius: 30,
    backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
    alignSelf: "center",
    marginBottom: spacing.md,
    marginTop: spacing.lg,
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
    letterSpacing: 4,
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
  altLink: { alignSelf: "center", marginTop: spacing.lg, padding: spacing.sm },
  altLinkTxt: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "600" },
});
