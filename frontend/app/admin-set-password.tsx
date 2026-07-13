/**
 * Set Password — Iter 64.
 *
 * Any signed-in admin (super_admin / company_admin / sub_admin) can set or
 * change their web-portal password from this screen. Uses the existing
 * ``POST /api/auth/admin-set-password`` endpoint.
 *
 * • First-time set: only "new password" and "confirm" required.
 * • Subsequent change: also asks for the current password.
 */
import React, { useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ActivityIndicator,
  Alert,
  Platform,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

function showMsg(msg: string) {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert("Set password", msg);
}

export default function AdminSetPasswordScreen() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const hasExistingPassword = !!user?.password_set_at;

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const strengthHint = useMemo(() => {
    if (!newPassword) return "";
    const lengthOk = newPassword.length >= 8;
    const hasDigit = /\d/.test(newPassword);
    const hasLower = /[a-z]/.test(newPassword);
    const hasUpper = /[A-Z]/.test(newPassword);
    const total = [lengthOk, hasDigit, hasLower, hasUpper].filter(Boolean).length;
    if (total <= 2) return "Weak";
    if (total === 3) return "Fair";
    return "Strong";
  }, [newPassword]);

  const isAdmin =
    user?.role === "super_admin" ||
    user?.role === "company_admin" ||
    user?.role === "sub_admin";

  const submit = async () => {
    setErr(null);
    if (!newPassword || newPassword.length < 8) {
      setErr("Password must be at least 8 characters");
      return;
    }
    if (newPassword !== confirmPassword) {
      setErr("New password and confirmation don't match");
      return;
    }
    if (hasExistingPassword && !currentPassword) {
      setErr("Enter your current password to change it");
      return;
    }
    setBusy(true);
    try {
      await api("/auth/admin-set-password", {
        method: "POST",
        body: {
          current_password: hasExistingPassword ? currentPassword : undefined,
          new_password: newPassword,
        },
      });
      await refresh();
      showMsg(
        hasExistingPassword
          ? "Password updated. Use it to sign in on the web portal."
          : "Password set. You can now sign in on the web portal with email + password.",
      );
      router.back();
    } catch (e: any) {
      setErr(e?.message || "Could not set password");
    } finally {
      setBusy(false);
    }
  };

  if (!isAdmin) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Only administrators can set a web password.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={8}>
          <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>
            {hasExistingPassword ? "Change web password" : "Set web password"}
          </Text>
          <Text style={styles.hsub}>
            Used only on the web/admin portal — PIN stays for mobile.
          </Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.card}>
          {hasExistingPassword ? (
            <>
              <Text style={styles.label}>Current password</Text>
              <View style={styles.pwWrap}>
                <TextInput
                  style={styles.input}
                  value={currentPassword}
                  onChangeText={setCurrentPassword}
                  placeholder="Enter your current password"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  secureTextEntry={!showPw}
                  autoCapitalize="none"
                  autoComplete="password"
                  testID="set-pw-current"
                />
              </View>
            </>
          ) : (
            <View style={styles.info}>
              <Ionicons name="information-circle" size={16} color={colors.brandPrimary} />
              <Text style={styles.infoTxt}>
                You don&apos;t have a web password yet. Set one below to enable email + password sign-in.
              </Text>
            </View>
          )}

          <Text style={styles.label}>New password</Text>
          <View style={styles.pwWrap}>
            <TextInput
              style={styles.input}
              value={newPassword}
              onChangeText={setNewPassword}
              placeholder="At least 8 characters, mix of letters & digits"
              placeholderTextColor={colors.onSurfaceTertiary}
              secureTextEntry={!showPw}
              autoCapitalize="none"
              autoComplete="new-password"
              testID="set-pw-new"
            />
            <Pressable
              onPress={() => setShowPw((v) => !v)}
              style={styles.eyeBtn}
              hitSlop={8}
            >
              <Ionicons
                name={showPw ? "eye-off-outline" : "eye-outline"}
                size={20}
                color={colors.onSurfaceSecondary}
              />
            </Pressable>
          </View>
          {strengthHint ? (
            <Text
              style={[
                styles.strength,
                strengthHint === "Weak" && { color: "#DC2626" },
                strengthHint === "Fair" && { color: "#B45309" },
                strengthHint === "Strong" && { color: "#166534" },
              ]}
            >
              Strength: {strengthHint}
            </Text>
          ) : null}

          <Text style={styles.label}>Confirm new password</Text>
          <View style={styles.pwWrap}>
            <TextInput
              style={styles.input}
              value={confirmPassword}
              onChangeText={setConfirmPassword}
              placeholder="Re-enter new password"
              placeholderTextColor={colors.onSurfaceTertiary}
              secureTextEntry={!showPw}
              autoCapitalize="none"
              autoComplete="new-password"
              testID="set-pw-confirm"
            />
          </View>

          {err ? (
            <View style={styles.errBox}>
              <Ionicons name="alert-circle" size={16} color="#B91C1C" />
              <Text style={styles.errTxt}>{err}</Text>
            </View>
          ) : null}

          <Pressable
            style={[styles.cta, busy && { opacity: 0.6 }]}
            onPress={submit}
            disabled={busy}
            testID="set-pw-submit"
          >
            {busy ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="key" size={18} color="#fff" />
                <Text style={styles.ctaTxt}>
                  {hasExistingPassword ? "Update password" : "Set password"}
                </Text>
              </>
            )}
          </Pressable>

          <Text style={styles.foot}>
            Tip: after setting a password, log out and sign back in via the
            &quot;Admin sign in&quot; page using your email + password.
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  h1: { color: colors.onSurface, fontSize: type.xl, fontWeight: "800" },
  hsub: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },
  scroll: { padding: spacing.lg, maxWidth: 520, alignSelf: "center", width: "100%" },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  label: {
    marginTop: spacing.md,
    marginBottom: 4,
    color: colors.onSurfaceSecondary,
    fontSize: 12,
    fontWeight: "800",
    textTransform: "uppercase",
  },
  pwWrap: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  input: {
    flex: 1,
    paddingHorizontal: 12,
    paddingVertical: 12,
    color: colors.onSurface,
    fontSize: 15,
  },
  eyeBtn: { paddingHorizontal: 12, paddingVertical: 12 },
  strength: {
    marginTop: 4,
    fontSize: 12,
    fontWeight: "700",
  },
  info: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 6,
    backgroundColor: colors.brandTertiary,
    padding: spacing.md,
    borderRadius: radius.md,
    marginBottom: 4,
  },
  infoTxt: {
    flex: 1,
    color: colors.onSurface,
    fontSize: 13,
    lineHeight: 18,
  },
  errBox: {
    marginTop: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    padding: spacing.sm,
    backgroundColor: "#FEE2E2",
    borderRadius: radius.md,
  },
  errTxt: { color: "#B91C1C", fontSize: 13, flex: 1 },
  cta: {
    marginTop: spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.brandPrimary,
    paddingVertical: 14,
    borderRadius: radius.md,
  },
  ctaTxt: { color: "#fff", fontSize: 15, fontWeight: "800" },
  foot: {
    marginTop: spacing.md,
    color: colors.onSurfaceSecondary,
    fontSize: 12,
    textAlign: "center",
    lineHeight: 18,
  },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: { marginTop: 8, color: colors.onSurfaceSecondary, textAlign: "center" },
});
