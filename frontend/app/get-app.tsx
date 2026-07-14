/**
 * Iter 106 — "Get the App" landing page (QR target).
 * Employees / Employers land here after scanning a QR code:
 *   Step 1 — install the app (PWA "Add to Home Screen")
 *   Step 2 — register yourself (employee joining form or company signup)
 * Params: ?type=employee|employer & company=<COMPANY_CODE>
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView, Platform, Image } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { colors, radius, spacing, type } from "@/src/theme";

const LOGO = require("../assets/images/logo-mark.png");

export default function GetAppScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ type?: string; company?: string }>();
  const isEmployer = (params?.type as string) === "employer";
  const companyCode = ((params?.company as string) || "").toUpperCase();

  const [installEvt, setInstallEvt] = useState<any>(null);
  const [installed, setInstalled] = useState(false);
  const [isStandalone, setIsStandalone] = useState(false);

  // Remember HOW the person arrived (employee QR vs employer QR) so the
  // landing page can hide irrelevant sign-in options after PWA install.
  useEffect(() => {
    if (Platform.OS !== "web") return;
    try {
      window.localStorage.setItem("qr_entry_type", isEmployer ? "employer" : "employee");
    } catch {}
  }, [isEmployer]);

  useEffect(() => {
    if (Platform.OS !== "web") return;
    // already running as an installed app?
    const standalone =
      window.matchMedia?.("(display-mode: standalone)")?.matches ||
      (window.navigator as any).standalone === true;
    setIsStandalone(!!standalone);
    // setupPWA() (runs at app start) stashes the install prompt on
    // window.__pwaInstallEvent — pick it up here even if it fired before
    // this screen mounted.
    const stashed = (window as any).__pwaInstallEvent || (window as any).__pwaInstallEvt;
    if (stashed) setInstallEvt(stashed);
    const onReady = () =>
      setInstallEvt((window as any).__pwaInstallEvent || (window as any).__pwaInstallEvt || null);
    const onPrompt = (e: any) => { e.preventDefault(); setInstallEvt(e); };
    const onInstalled = () => setInstalled(true);
    window.addEventListener("pwa-installable", onReady);
    window.addEventListener("pwa-install-ready", onReady);
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("pwa-installable", onReady);
      window.removeEventListener("pwa-install-ready", onReady);
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  const install = async () => {
    if (installEvt) {
      installEvt.prompt();
      try {
        const r = await installEvt.userChoice;
        if (r?.outcome === "accepted") setInstalled(true);
      } catch {}
      setInstallEvt(null);
      (window as any).__pwaInstallEvent = null;
      (window as any).__pwaInstallEvt = null;
    }
  };

  const goRegister = () => {
    if (isEmployer) router.push("/company-register");
    else router.push(
      companyCode ? `/employee-signup?company=${encodeURIComponent(companyCode)}` : "/employee-signup");
  };

  const iosHint =
    Platform.OS === "web" && /iphone|ipad|ipod/i.test(navigator?.userAgent || "");

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.body}>
        <Image source={LOGO} style={styles.logo} resizeMode="contain" />
        <Text style={styles.title}>
          {isEmployer ? "Employer Registration" : "Employee Registration"}
        </Text>
        <Text style={styles.sub}>
          {isEmployer
            ? "Register your company and manage attendance, salary & compliance."
            : companyCode
              ? `Join your company (${companyCode}) — attendance, leaves & payslips.`
              : "Join your company — attendance, leaves & payslips."}
        </Text>

        {/* STEP 1 — install */}
        <View style={styles.stepCard} testID="getapp-step1">
          <View style={styles.stepBadge}><Text style={styles.stepBadgeTxt}>1</Text></View>
          <Text style={styles.stepTitle}>Download / Install the App</Text>
          {isStandalone || installed ? (
            <Text style={styles.okTxt}>✓ App is installed — continue to Step 2</Text>
          ) : installEvt ? (
            <Pressable style={styles.installBtn} onPress={install} testID="getapp-install">
              <Ionicons name="download-outline" size={18} color="#fff" />
              <Text style={styles.installTxt}>Install App</Text>
            </Pressable>
          ) : (
            <Text style={styles.hintTxt}>
              {iosHint
                ? 'Tap the Share button (□↑) in Safari, then choose "Add to Home Screen".'
                : 'Open your browser menu (⋮) and choose "Install app" / "Add to Home Screen".'}
            </Text>
          )}
        </View>

        {/* STEP 2 — register */}
        <View style={styles.stepCard} testID="getapp-step2">
          <View style={styles.stepBadge}><Text style={styles.stepBadgeTxt}>2</Text></View>
          <Text style={styles.stepTitle}>Register Yourself</Text>
          <Text style={styles.hintTxt}>
            {isEmployer
              ? "Fill your company details — our team will activate your account."
              : "Fill your details — your employer will approve your joining."}
          </Text>
          <Pressable
            style={[styles.installBtn, { backgroundColor: isEmployer ? "#1E3A8A" : "#16A34A" }]}
            onPress={goRegister}
            testID="getapp-register"
          >
            <Ionicons name="person-add-outline" size={18} color="#fff" />
            <Text style={styles.installTxt}>
              {isEmployer ? "Register Company" : "Register as Employee"}
            </Text>
          </Pressable>
        </View>

        <Pressable onPress={() => router.push(isEmployer ? "/company-login" : "/pin-login")}
          style={{ marginTop: 18 }} testID="getapp-login">
          <Text style={{ color: colors.brandPrimary, fontWeight: "800", fontSize: 13, textAlign: "center" }}>
            Already registered? Log in →
          </Text>
        </Pressable>
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  body: { padding: spacing.lg, alignItems: "center", maxWidth: 560, width: "100%", alignSelf: "center" },
  logo: { width: 120, height: 120, marginTop: 10 },
  title: { ...type.h1, color: colors.onSurface, fontWeight: "900", marginTop: 8, textAlign: "center" },
  sub: {
    color: colors.onSurfaceSecondary, fontSize: 13, textAlign: "center",
    marginTop: 6, marginBottom: spacing.lg, lineHeight: 19,
  },
  stepCard: {
    width: "100%", backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.divider, padding: spacing.lg, marginBottom: spacing.md,
  },
  stepBadge: {
    width: 26, height: 26, borderRadius: 13, backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center", marginBottom: 8,
  },
  stepBadgeTxt: { color: "#fff", fontWeight: "900", fontSize: 13 },
  stepTitle: { fontSize: 15.5, fontWeight: "800", color: colors.onSurface },
  hintTxt: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 6, lineHeight: 18 },
  okTxt: { fontSize: 13, color: "#16A34A", fontWeight: "800", marginTop: 8 },
  installBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingVertical: 13, marginTop: 12,
  },
  installTxt: { color: "#fff", fontWeight: "900", fontSize: 14 },
});
