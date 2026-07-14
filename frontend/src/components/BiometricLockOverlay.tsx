import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";

import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

const LOGO_MARK = require("../../assets/images/logo-mark.png");

/**
 * Full-screen overlay shown when biometric unlock is enabled and the app
 * boots or returns from background after > 30s. Blocks all content behind
 * it until either biometric auth succeeds or the user chooses to sign out.
 *
 * Note: on web `biometricLocked` should never be true (getBiometricCapability
 * returns supported=false), so this overlay is effectively a no-op there.
 */
export default function BiometricLockOverlay() {
  const {
    biometricLocked,
    biometricLabel,
    unlockWithBiometric,
    logout,
  } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!biometricLocked) return;
    // Auto-launch the biometric sheet once when the lock engages.
    let cancelled = false;
    (async () => {
      setBusy(true);
      setError(null);
      const ok = await unlockWithBiometric();
      if (cancelled) return;
      if (!ok) {
        setError("Authentication failed. Tap “Unlock” to try again.");
      }
      setBusy(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [biometricLocked, unlockWithBiometric]);

  if (!biometricLocked) return null;

  const retry = async () => {
    setBusy(true);
    setError(null);
    const ok = await unlockWithBiometric();
    if (!ok) {
      setError("Authentication failed. Please try again or sign out.");
    }
    setBusy(false);
  };

  return (
    <View style={styles.root} testID="biometric-lock-overlay">
      <View style={styles.card}>
        <Image
          source={LOGO_MARK}
          style={styles.logo}
          contentFit="contain"
        />
        <Text style={styles.brand}>S.K. Sharma & Co.</Text>
        <View style={styles.iconWrap}>
          <Ionicons
            name={
              biometricLabel.toLowerCase().includes("face")
                ? "happy-outline"
                : "finger-print"
            }
            size={56}
            color={colors.brandPrimary}
          />
        </View>
        <Text style={styles.title}>App locked</Text>
        <Text style={styles.subtitle}>
          Unlock with {biometricLabel} to continue.
        </Text>
        {error ? <Text style={styles.err}>{error}</Text> : null}
        <Pressable
          testID="biometric-unlock-retry"
          style={[styles.cta, busy && { opacity: 0.7 }]}
          disabled={busy}
          onPress={retry}
        >
          {busy ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <Ionicons name="lock-open-outline" size={18} color="#fff" />
              <Text style={styles.ctaTxt}>Unlock with {biometricLabel}</Text>
            </>
          )}
        </Pressable>
        <Pressable
          testID="biometric-lock-signout"
          style={styles.linkBtn}
          onPress={logout}
        >
          <Text style={styles.linkTxt}>Sign out instead</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    ...(Platform.OS === "web"
      ? ({ position: "fixed" as any } as any)
      : { position: "absolute" as const }),
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(15,23,42,0.96)",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 9999,
    padding: spacing.xl,
  },
  card: {
    width: "100%",
    maxWidth: 360,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.xl,
    alignItems: "center",
  },
  logo: { width: 48, height: 48, marginBottom: 6 },
  brand: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "700",
    letterSpacing: 0.4,
    marginBottom: spacing.lg,
  },
  iconWrap: {
    width: 96,
    height: 96,
    borderRadius: 48,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.md,
  },
  title: {
    color: colors.onSurface,
    fontSize: type.xl,
    fontWeight: "800",
    textAlign: "center",
  },
  subtitle: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    textAlign: "center",
    marginTop: 6,
    lineHeight: 20,
  },
  err: {
    color: colors.error,
    fontSize: type.sm,
    marginTop: spacing.md,
    textAlign: "center",
  },
  cta: {
    marginTop: spacing.lg,
    alignSelf: "stretch",
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.pill,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  ctaTxt: { color: "#fff", fontSize: type.base, fontWeight: "700" },
  linkBtn: { marginTop: spacing.md, paddingVertical: 8 },
  linkTxt: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    fontWeight: "600",
    textDecorationLine: "underline",
  },
});
