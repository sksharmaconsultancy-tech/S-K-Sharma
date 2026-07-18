/**
 * Test — ESIC / EPFO auto-login via an automated Chrome control window.
 *
 * No browser tabs. The app hands off to a small self-updating PC runner
 * that opens its OWN Selenium-controlled Chrome window, fills the firm's
 * saved User ID + Password (fetched live), reads the captcha with the
 * app's AI, and lets the operator click Login. Runs on the operator's
 * machine so the government portal's IP block doesn't apply; ChromeDriver
 * and the login script auto-update themselves every run.
 */
import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Platform,
  ScrollView,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { apiBinary } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

export default function TestPortalScreen() {
  const { user, loading } = useAuth();

  if (loading) return null;
  const role = user?.role as string;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={st.wrap}>
        <Text style={st.title}>Test — Portal Auto-Login</Text>
        <Text style={st.subtitle}>
          Opens an automated Chrome control window that logs into the ESIC or
          EPFO (PF) employer portal for you — fills your User ID &amp; Password
          and reads the captcha automatically.
        </Text>

        <AutomationCard />
      </ScrollView>
    </SafeAreaView>
  );
}

function AutomationCard() {
  const { selectedCompanyId } = useSelectedCompany();
  const [busy, setBusy] = useState<"runner" | "ext" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const download = useCallback(
    async (kind: "runner" | "ext") => {
      setError(null);
      setBusy(kind);
      try {
        if (Platform.OS !== "web") {
          setError(
            "Please open this page on a computer (Chrome/Edge browser) to download and run the auto-login.",
          );
          return;
        }
        const origin = (globalThis as any).location?.origin || "";
        const ep =
          kind === "runner"
            ? "/admin/portal-automation/runner-download"
            : "/admin/portal-automation/extension-download";
        const qs = `?api_base=${encodeURIComponent(origin)}${
          selectedCompanyId ? `&company_id=${selectedCompanyId}` : ""
        }`;
        const { webBlobUrl } = await apiBinary(`${ep}${qs}`);
        if (Platform.OS === "web" && webBlobUrl) {
          const a = document.createElement("a");
          a.href = webBlobUrl;
          a.download =
            kind === "runner"
              ? "sks-autologin-pc.zip"
              : "sks-auto-login-extension.zip";
          document.body.appendChild(a);
          a.click();
          a.remove();
        }
      } catch (e: any) {
        setError(e?.message || "Download failed.");
      } finally {
        setBusy(null);
      }
    },
    [selectedCompanyId],
  );

  return (
    <View style={st.autoCard}>
      <View style={st.cardHead}>
        <View style={[st.iconWrap, { backgroundColor: "#05966916" }]}>
          <Ionicons name="hardware-chip-outline" size={22} color="#059669" />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={st.cardTitle}>Automated Chrome Login</Text>
          <Text style={st.autoSub}>
            Opens a controlled Chrome window, fills User ID + Password and reads
            the captcha automatically. Download once — the script &amp;
            ChromeDriver auto-update themselves every run.
          </Text>
        </View>
      </View>

      <Pressable
        style={[st.dlBtn, busy === "runner" && st.disabled]}
        onPress={() => download("runner")}
        disabled={busy !== null}
        testID="btn-download-runner"
      >
        {busy === "runner" ? (
          <ActivityIndicator color="#fff" size="small" />
        ) : (
          <Ionicons name="download-outline" size={18} color="#fff" />
        )}
        <Text style={st.dlBtnTxt}>Get Automated Chrome Login</Text>
      </Pressable>

      <Text style={st.step}>
        1. Download the zip, then unzip and MOVE the folder to a fixed
        location (see below) — needs Chrome + Python.{"\n"}
        2. Open that folder. Windows: double-click{" "}
        <Text style={st.mono}>run_esic.bat</Text> (or{" "}
        <Text style={st.mono}>run_pf.bat</Text>). Mac/Linux: run{" "}
        <Text style={st.mono}>./run.sh esic</Text>.{"\n"}
        3. A controlled Chrome window opens and logs in automatically —
        check the captcha and click Login. It self-updates in that folder
        every run, so you never download again.
      </Text>

      <View style={st.folderBox}>
        <Ionicons name="folder-open-outline" size={16} color="#059669" />
        <View style={{ flex: 1 }}>
          <Text style={st.folderHead}>Keep the folder here (first time):</Text>
          <Text style={st.folderPath}>Windows:  C:\SKS-AutoLogin</Text>
          <Text style={st.folderPath}>Mac:  /Users/&lt;you&gt;/SKS-AutoLogin</Text>
          <Text style={st.folderPath}>Linux:  /home/&lt;you&gt;/SKS-AutoLogin</Text>
          <Text style={st.folderNote}>
            Run it from this same folder each time so it can auto-update
            itself in place.
          </Text>
        </View>
      </View>

      <Pressable
        style={[st.linkBtn, busy === "ext" && st.disabled]}
        onPress={() => download("ext")}
        disabled={busy !== null}
        testID="btn-download-extension"
      >
        {busy === "ext" ? (
          <ActivityIndicator color={colors.brandPrimary} size="small" />
        ) : (
          <Ionicons name="extension-puzzle-outline" size={16} color={colors.brandPrimary} />
        )}
        <Text style={st.linkTxt}>Prefer a Chrome extension? Download here (no Python)</Text>
      </Pressable>

      {error ? (
        <View style={st.errorBox}>
          <Ionicons name="alert-circle" size={16} color="#DC2626" />
          <Text style={st.errorTxt}>{error}</Text>
        </View>
      ) : null}
    </View>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  wrap: { padding: 20, gap: 14, maxWidth: 640, width: "100%", alignSelf: "center" },
  title: { fontSize: 22, fontWeight: "800", color: colors.textPrimary },
  subtitle: { fontSize: 13, color: colors.textSecondary, lineHeight: 19 },
  autoCard: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    borderWidth: 1, borderColor: "#05966955", padding: 16, gap: 12,
  },
  cardHead: { flexDirection: "row", alignItems: "flex-start", gap: 12 },
  iconWrap: {
    width: 44, height: 44, borderRadius: 12, alignItems: "center",
    justifyContent: "center",
  },
  cardTitle: { fontSize: 15, fontWeight: "800", color: colors.textPrimary },
  autoSub: { fontSize: 12, color: colors.textSecondary, marginTop: 3, lineHeight: 17 },
  dlBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 8, backgroundColor: "#059669", borderRadius: 10,
    paddingVertical: 14, minHeight: 48,
  },
  dlBtnTxt: { color: "#fff", fontSize: 14.5, fontWeight: "800" },
  disabled: { opacity: 0.7 },
  step: { fontSize: 12.5, color: colors.textSecondary, lineHeight: 19 },
  mono: { fontWeight: "800", color: colors.textPrimary },
  folderBox: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    backgroundColor: "#ECFDF5", borderRadius: 10, padding: 12,
    borderWidth: 1, borderColor: "#05966933",
  },
  folderHead: { fontSize: 12.5, fontWeight: "800", color: "#065F46", marginBottom: 3 },
  folderPath: { fontSize: 12.5, color: "#065F46", fontWeight: "700", lineHeight: 19 },
  folderNote: { fontSize: 11.5, color: "#047857", marginTop: 4, lineHeight: 16 },
  linkBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 8,
    paddingVertical: 8, paddingHorizontal: 12,
  },
  linkTxt: { color: colors.brandPrimary, fontSize: 13, fontWeight: "800" },
  errorBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#FEE2E2", borderRadius: 10, padding: 12,
  },
  errorTxt: { color: "#991B1B", fontSize: 13, flex: 1 },
});
