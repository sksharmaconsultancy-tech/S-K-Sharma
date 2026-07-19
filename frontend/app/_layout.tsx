import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect } from "react";
import { LogBox } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { KeyboardProvider } from "react-native-keyboard-controller";

import { useIconFonts } from "@/src/hooks/use-icon-fonts";
import { AuthProvider } from "@/src/context/AuthContext";
import { SelectedCompanyProvider } from "@/src/context/SelectedCompanyContext";
import { AutoPunchProvider } from "@/src/context/AutoPunchContext";
import { RefreshBusProvider } from "@/src/context/RefreshBusContext";
import BiometricLockOverlay from "@/src/components/BiometricLockOverlay";
import AdminWebShell from "@/src/components/AdminWebShell";
import { refreshRemindersOnBoot } from "@/src/utils/punchReminders";
import { setupPWA } from "@/src/utils/pwa";
import { ThemeProvider, useTheme } from "@/src/context/ThemeContext";

LogBox.ignoreAllLogs(true);

// Deep-link preservation — capture the path the browser ACTUALLY opened
// before any router hydration/remount can clobber it. app/index.tsx uses
// this to restore direct URLs (e.g. /salary-run) after the auth bootstrap
// remounts the Stack and resets it to "/".
if (typeof window !== "undefined" && !(window as any).__bootPath) {
  (window as any).__bootPath = window.location.pathname + window.location.search;
}

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [loaded, error] = useIconFonts();

  useEffect(() => {
    if (loaded || error) SplashScreen.hideAsync();
  }, [loaded, error]);

  // Re-schedule daily punch reminders after every cold start. Safe / idempotent.
  useEffect(() => {
    refreshRemindersOnBoot();
    setupPWA();
  }, []);

  // Iter 93 — Web only: silence the LogBox "Uncaught Error" overlay for
  // transient Cloudflare security checks (the api client already retries
  // them once and tags the error).
  useEffect(() => {
    LogBox.ignoreLogs(["Security check in progress"]);
    if (typeof window === "undefined" || !window.addEventListener) return;
    const onRejection = (e: any) => {
      if (e?.reason?.isChallenge) {
        console.warn("[cf] security check on API call — suppressed:", e.reason?.message);
        e.preventDefault?.();
      }
    };
    window.addEventListener("unhandledrejection", onRejection);
    return () => window.removeEventListener("unhandledrejection", onRejection);
  }, []);

  if (!loaded && !error) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <KeyboardProvider>
        <SafeAreaProvider>
          <ThemeProvider>
            <ThemedTree />
          </ThemeProvider>
        </SafeAreaProvider>
      </KeyboardProvider>
    </GestureHandlerRootView>
  );
}

/**
 * Iter 85 — Wrapping the theme-dependent tree in a version-keyed
 * component ensures every screen re-mounts (and thus re-reads the
 * mutable `colors` object) when the admin picks a new palette.
 */
function ThemedTree() {
  const { version } = useTheme();
  return (
    <AuthProvider key={`theme-v-${version}`}>
      <SelectedCompanyProvider>
        <RefreshBusProvider>
          <AutoPunchProvider>
            <StatusBar style="dark" />
            <AdminWebShell>
              <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: "#FAFAF9" } }} />
            </AdminWebShell>
            <BiometricLockOverlay />
          </AutoPunchProvider>
        </RefreshBusProvider>
      </SelectedCompanyProvider>
    </AuthProvider>
  );
}
