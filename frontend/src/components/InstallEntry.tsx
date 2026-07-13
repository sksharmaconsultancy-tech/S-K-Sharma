import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, Platform, ActivityIndicator } from "react-native";
import { Image } from "expo-image";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import {
  setManifestHref, isStandalonePWA, isIOS, isIOSWeb, canInstallNow, promptInstall,
  setAppleWebAppTitle,
} from "@/src/utils/pwa";

type Props = {
  kind: "employer" | "employee";
  title: string;
  subtitle: string;
  loginPath: string;      // where "Continue" / installed app goes
  manifestHref: string;   // per-entry manifest
  accentIcon: any;
};

/**
 * Branded install landing for the /employer and /employee deep links.
 * - Web browser: shows a one-tap "Install app" button (Chrome/Android) or an
 *   iOS "Add to Home Screen" hint, plus a "Continue to sign in" button.
 * - Installed (standalone) or native: forwards straight to the login.
 */
export default function InstallEntry({
  kind, title, subtitle, loginPath, manifestHref, accentIcon,
}: Props) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const isWeb = Platform.OS === "web";

  const [installable, setInstallable] = useState(false);
  const [installed, setInstalled] = useState(false);

  useEffect(() => {
    if (!isWeb) return;
    setManifestHref(manifestHref);
    setAppleWebAppTitle(title);
    setInstallable(canInstallNow());
    const onCan = () => setInstallable(true);
    const onDone = () => { setInstalled(true); setInstallable(false); };
    window.addEventListener("pwa-installable", onCan);
    window.addEventListener("pwa-installed", onDone);
    return () => {
      window.removeEventListener("pwa-installable", onCan);
      window.removeEventListener("pwa-installed", onDone);
    };
  }, [isWeb, manifestHref, title]);

  if (loading) {
    return (
      <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} size="large" /></View>
    );
  }

  // Employees are NOT allowed into the Employer portal — send them to the
  // Employee app instead of into the admin experience.
  if (kind === "employer" && user?.role === "employee") {
    return (
      <View style={styles.root} testID="employer-blocked-for-employee">
        <SafeAreaView style={{ flex: 1 }} edges={["top", "bottom"]}>
          <View style={styles.center}>
            <View style={styles.logoWrap}>
              <Ionicons name="lock-closed" size={44} color="#B91C1C" />
            </View>
            <Text style={styles.brand}>Employers only</Text>
            <Text style={styles.subtitle}>
              You are signed in as an employee. The Employer Portal is only for
              Super Admins, Company Admins and Sub Admins.
            </Text>
          </View>
          <View style={styles.bottom}>
            <Pressable
              style={({ pressed }) => [styles.cta, pressed && { opacity: 0.92 }]}
              onPress={() => router.replace("/employee" as any)}
              testID="btn-goto-employee"
            >
              <Ionicons name="person" size={18} color={colors.onCta} />
              <Text style={styles.ctaTxt}>Go to Employee App</Text>
            </Pressable>
          </View>
        </SafeAreaView>
      </View>
    );
  }

  // Already signed in → into the app.
  if (user) return <Redirect href="/(tabs)" />;

  // Native app OR the installed standalone PWA → go straight to the login.
  if (!isWeb || isStandalonePWA()) return <Redirect href={loginPath as any} />;

  const ios = isIOS();

  const onInstall = async () => {
    const res = await promptInstall();
    if (res === "accepted") setInstalled(true);
    else if (res === "unavailable") {
      // Fallback for browsers without beforeinstallprompt.
      window.alert(
        isIOSWeb()
          ? "Tap the Share icon in Safari, then 'Add to Home Screen' to install."
          : "Open your browser menu and choose 'Install app' / 'Add to Home Screen'.",
      );
    }
  };

  return (
    <View style={styles.root} testID={`install-entry-${kind}`}>
      <SafeAreaView style={{ flex: 1 }} edges={["top", "bottom"]}>
        <View style={styles.blob} />
        <View style={styles.blob2} />

        <View style={styles.center}>
          <View style={styles.logoWrap}>
            <Image source={require("../../assets/images/logo-mark.png")}
              style={styles.logo} contentFit="contain" />
          </View>
          <Text style={styles.brand}>S.K. Sharma & Co.</Text>
          <View style={styles.kindPill}>
            <Ionicons name={accentIcon} size={14} color={colors.brandPrimary} />
            <Text style={styles.kindPillTxt}>{title}</Text>
          </View>
          <Text style={styles.subtitle}>{subtitle}</Text>
        </View>

        <View style={styles.bottom}>
          {installed ? (
            <View style={styles.installedBox} testID="install-done">
              <Ionicons name="checkmark-circle" size={18} color="#166534" />
              <Text style={styles.installedTxt}>
                Installed! Open the “{title}” icon from your home screen.
              </Text>
            </View>
          ) : ios ? (
            // iOS Safari cannot trigger a native install — show clear steps.
            <View style={styles.iosCard} testID="ios-install-steps">
              <Text style={styles.iosCardTitle}>
                <Ionicons name="phone-portrait-outline" size={15} color={colors.brandPrimary} />
                {"  "}Install on your iPhone / iPad
              </Text>
              <View style={styles.iosStep}>
                <View style={styles.iosNum}><Text style={styles.iosNumTxt}>1</Text></View>
                <Text style={styles.iosStepTxt}>
                  Open this page in <Text style={{ fontWeight: "800" }}>Safari</Text> (if not already).
                </Text>
              </View>
              <View style={styles.iosStep}>
                <View style={styles.iosNum}><Text style={styles.iosNumTxt}>2</Text></View>
                <Text style={styles.iosStepTxt}>
                  Tap the <Ionicons name="share-outline" size={14} color={colors.onSurface} /> Share
                  button at the bottom of Safari.
                </Text>
              </View>
              <View style={styles.iosStep}>
                <View style={styles.iosNum}><Text style={styles.iosNumTxt}>3</Text></View>
                <Text style={styles.iosStepTxt}>
                  Scroll and tap <Text style={{ fontWeight: "800" }}>“Add to Home Screen”</Text>, then
                  <Text style={{ fontWeight: "800" }}> Add</Text>.
                </Text>
              </View>
            </View>
          ) : (
            <Pressable style={({ pressed }) => [styles.cta, pressed && { opacity: 0.92 }]}
              onPress={onInstall} testID="btn-install">
              <Ionicons name="download-outline" size={18} color={colors.onCta} />
              <Text style={styles.ctaTxt}>
                {installable ? "Install app on this phone" : "Add to Home Screen"}
              </Text>
            </Pressable>
          )}

          <Pressable style={({ pressed }) => [styles.ctaSecondary, pressed && { opacity: 0.9 }]}
            onPress={() => router.push(loginPath as any)} testID="btn-continue">
            <Ionicons name="arrow-forward" size={18} color={colors.brandPrimary} />
            <Text style={styles.ctaSecondaryTxt}>Continue to sign in</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  root: { flex: 1, backgroundColor: colors.surface },
  blob: {
    position: "absolute", top: -80, right: -60, width: 220, height: 220,
    borderRadius: 110, backgroundColor: "#DCEAF2", opacity: 0.6,
  },
  blob2: {
    position: "absolute", bottom: -70, left: -50, width: 180, height: 180,
    borderRadius: 90, backgroundColor: "#DCEAF2", opacity: 0.4,
  },
  logoWrap: {
    width: 96, height: 96, borderRadius: 24, backgroundColor: "#FFFFFF",
    alignItems: "center", justifyContent: "center", marginBottom: spacing.lg, ...shadow.card,
  },
  logo: { width: 60, height: 60 },
  brand: { ...type.h1, color: colors.onSurface, fontWeight: "800", marginBottom: spacing.sm },
  kindPill: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#E8F1F6", paddingHorizontal: 12, paddingVertical: 6,
    borderRadius: 999, marginBottom: spacing.md,
  },
  kindPillTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12.5, letterSpacing: 0.4 },
  subtitle: {
    ...type.body, color: colors.onSurfaceSecondary, textAlign: "center",
    paddingHorizontal: spacing.lg,
  },
  bottom: { paddingHorizontal: spacing.lg, paddingBottom: spacing.lg, gap: spacing.sm },
  cta: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.cta, paddingVertical: 16, borderRadius: radius.lg, ...shadow.card,
  },
  ctaTxt: { color: colors.onCta, fontWeight: "800", fontSize: 15.5 },
  ctaSecondary: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.border,
    paddingVertical: 15, borderRadius: radius.lg,
  },
  ctaSecondaryTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 15 },
  installedBox: {
    flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#DCFCE7",
    paddingVertical: 14, paddingHorizontal: 14, borderRadius: radius.lg,
  },
  installedTxt: { color: "#166534", fontWeight: "600", fontSize: 13.5, flex: 1 },
  iosCard: {
    backgroundColor: "#F1F5F9", borderRadius: radius.lg, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, gap: 10,
  },
  iosCardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface, marginBottom: 2 },
  iosStep: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  iosNum: {
    width: 22, height: 22, borderRadius: 11, backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center", marginTop: 1,
  },
  iosNumTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  iosStepTxt: { flex: 1, fontSize: 13.5, color: colors.onSurface, lineHeight: 19 },
});
