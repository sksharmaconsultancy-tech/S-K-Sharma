/**
 * Test — ESIC portal quick launcher.
 *
 * Opens the ESIC employer portal in a NEW TAB (the operator's own browser
 * reaches the portal fine) and makes the firm's saved ESIC User ID +
 * Password one-tap fillable: the User ID is auto-copied to the clipboard
 * on open, and both fields have Copy buttons so the operator just pastes
 * them into the portal and types the captcha.
 *
 * Note: browsers do not allow one website to type into another site's
 * tab (cross-origin security), so paste is the fastest safe fill.
 */
import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Platform,
  Linking,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect } from "expo-router";
import * as Clipboard from "expo-clipboard";

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { api } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

const ESIC_URL =
  "https://portal.esic.gov.in/EmployerPortal/ESICInsurancePortal/Portal_Loginnew.aspx";

type Creds = { user_id: string; password: string; login_url: string };

function openInNewTab(url: string) {
  if (Platform.OS === "web") {
    globalThis.open(url, "_blank", "noopener");
  } else {
    void Linking.openURL(url);
  }
}

export default function TestPortalScreen() {
  const { user, loading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [creds, setCreds] = useState<Creds | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<"user" | "pass" | null>(null);
  const [revealPass, setRevealPass] = useState(false);

  const copy = useCallback(async (value: string, which: "user" | "pass") => {
    await Clipboard.setStringAsync(value);
    setCopied(which);
    setTimeout(() => setCopied(null), 1500);
  }, []);

  const launch = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      const c = await api<Creds>(
        `/admin/portal-automation/esic-credentials${
          selectedCompanyId ? `?company_id=${selectedCompanyId}` : ""
        }`,
      );
      setCreds(c);
      // Auto-copy the User ID so the operator can paste it straight away.
      if (c.user_id) await copy(c.user_id, "user");
      openInNewTab(ESIC_URL);
    } catch (e: any) {
      setError(e?.message || "Could not load ESIC credentials.");
    } finally {
      setBusy(false);
    }
  }, [selectedCompanyId, copy]);

  if (loading) return null;
  const role = user?.role as string;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.wrap}>
        <Text style={st.title}>Test — ESIC Portal</Text>
        <Text style={st.subtitle}>
          Opens the ESIC employer portal in a new tab and copies your saved
          User ID to the clipboard. Paste the User ID &amp; Password below into
          the portal, enter the captcha, and sign in.
        </Text>

        <View style={st.card}>
          <View style={st.cardHead}>
            <View style={st.iconWrap}>
              <Ionicons name="medkit" size={22} color="#0891B2" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={st.cardTitle}>ESIC Employer Portal</Text>
              <Text style={st.cardUrl} numberOfLines={2}>{ESIC_URL}</Text>
            </View>
          </View>

          <Pressable
            style={[st.openBtn, busy && st.openBtnDisabled]}
            onPress={launch}
            disabled={busy}
            testID="btn-open-esic-portal"
          >
            {busy ? (
              <ActivityIndicator color="#fff" size="small" />
            ) : (
              <Ionicons name="open-outline" size={18} color="#fff" />
            )}
            <Text style={st.openBtnTxt}>Open ESIC Portal (New Tab)</Text>
          </Pressable>
        </View>

        {error ? (
          <View style={st.errorBox}>
            <Ionicons name="alert-circle" size={16} color="#DC2626" />
            <Text style={st.errorTxt}>{error}</Text>
          </View>
        ) : null}

        {creds ? (
          <View style={st.credCard}>
            <Text style={st.credHead}>Your ESIC Login (from Firm Master)</Text>

            <CredRow
              label="User ID"
              value={creds.user_id}
              display={creds.user_id}
              copied={copied === "user"}
              onCopy={() => copy(creds.user_id, "user")}
            />
            <CredRow
              label="Password"
              value={creds.password}
              display={revealPass ? creds.password : "•".repeat(Math.min(creds.password.length, 12))}
              copied={copied === "pass"}
              onCopy={() => copy(creds.password, "pass")}
              trailing={
                <Pressable onPress={() => setRevealPass((v) => !v)} hitSlop={8} style={st.eyeBtn}>
                  <Ionicons
                    name={revealPass ? "eye-off-outline" : "eye-outline"}
                    size={18}
                    color={colors.textSecondary}
                  />
                </Pressable>
              }
            />

            <View style={st.hintBox}>
              <Ionicons name="information-circle-outline" size={15} color="#2563EB" />
              <Text style={st.hintTxt}>
                User ID copied — paste it (Ctrl+V) into the portal, then tap Copy
                on the Password and paste it too.
              </Text>
            </View>
          </View>
        ) : null}
      </View>
    </SafeAreaView>
  );
}

function CredRow({
  label,
  display,
  onCopy,
  copied,
  trailing,
}: {
  label: string;
  value: string;
  display: string;
  onCopy: () => void;
  copied: boolean;
  trailing?: React.ReactNode;
}) {
  return (
    <View style={st.credRow}>
      <View style={{ flex: 1 }}>
        <Text style={st.credLabel}>{label}</Text>
        <Text style={st.credValue} selectable>{display || "—"}</Text>
      </View>
      {trailing}
      <Pressable style={[st.copyBtn, copied && st.copyBtnOk]} onPress={onCopy} hitSlop={6}>
        <Ionicons
          name={copied ? "checkmark" : "copy-outline"}
          size={16}
          color={copied ? "#059669" : colors.brandPrimary}
        />
        <Text style={[st.copyTxt, copied && { color: "#059669" }]}>
          {copied ? "Copied" : "Copy"}
        </Text>
      </Pressable>
    </View>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  wrap: { padding: 20, gap: 12, maxWidth: 640, width: "100%", alignSelf: "center" },
  title: { fontSize: 22, fontWeight: "800", color: colors.textPrimary },
  subtitle: { fontSize: 13, color: colors.textSecondary, lineHeight: 19 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, padding: 16, gap: 14,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 12 },
  iconWrap: {
    width: 44, height: 44, borderRadius: 12, alignItems: "center",
    justifyContent: "center", backgroundColor: "#0891B216",
  },
  cardTitle: { fontSize: 15, fontWeight: "800", color: colors.textPrimary },
  cardUrl: { fontSize: 11, color: colors.textSecondary, marginTop: 3 },
  openBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 8, backgroundColor: colors.brandPrimary, borderRadius: 10,
    paddingVertical: 14, minHeight: 48,
  },
  openBtnDisabled: { opacity: 0.7 },
  openBtnTxt: { color: "#fff", fontSize: 14.5, fontWeight: "800" },
  errorBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#FEE2E2", borderRadius: 10, padding: 12,
  },
  errorTxt: { color: "#991B1B", fontSize: 13, flex: 1 },
  credCard: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, padding: 16, gap: 12,
  },
  credHead: { fontSize: 13, fontWeight: "800", color: colors.textPrimary },
  credRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    borderWidth: 1, borderColor: colors.border, borderRadius: 10,
    paddingVertical: 10, paddingHorizontal: 12, backgroundColor: colors.surface,
  },
  credLabel: { fontSize: 11, color: colors.textSecondary, fontWeight: "700" },
  credValue: { fontSize: 15, color: colors.textPrimary, fontWeight: "700", marginTop: 2 },
  eyeBtn: { padding: 6 },
  copyBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 8,
    paddingVertical: 7, paddingHorizontal: 11,
  },
  copyBtnOk: { borderColor: "#059669" },
  copyTxt: { color: colors.brandPrimary, fontSize: 13, fontWeight: "800" },
  hintBox: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    backgroundColor: "#EFF6FF", borderRadius: 10, padding: 11,
  },
  hintTxt: { flex: 1, color: "#1D4ED8", fontSize: 12, lineHeight: 17 },
});
