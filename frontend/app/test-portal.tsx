/**
 * Test — ESIC / EPFO portal quick launcher.
 *
 * Two buttons open the government employer portals (ESIC & EPFO) in a
 * NEW TAB (the operator's own browser reaches the portals fine) and make
 * the firm's saved User ID + Password one-tap fillable: the User ID is
 * auto-copied to the clipboard on open, and both fields have Copy buttons
 * so the operator just pastes them into the portal and types the captcha.
 *
 * Note: browsers do not allow one website to type into another site's
 * tab (cross-origin security), so paste is the fastest safe fill.
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Platform,
  Linking,
  ScrollView,
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

type PortalKey = "esic" | "epfo";
type Creds = { user_id: string; password: string; login_url: string };

const PORTALS: Record<
  PortalKey,
  { name: string; url: string; icon: any; tint: string; section: string }
> = {
  esic: {
    name: "ESIC Employer Portal",
    url: "https://portal.esic.gov.in/EmployerPortal/ESICInsurancePortal/Portal_Loginnew.aspx",
    icon: "medkit",
    tint: "#0891B2",
    section: "ESIC Detail",
  },
  epfo: {
    name: "EPFO Employer Portal (PF)",
    url: "https://unifiedportal-emp.epfindia.gov.in/epfo/",
    icon: "shield-checkmark",
    tint: "#7C3AED",
    section: "EPF Detail",
  },
};

function openInNewTab(url: string) {
  if (Platform.OS === "web") {
    globalThis.open(url, "_blank", "noopener");
  } else {
    void Linking.openURL(url);
  }
}

/**
 * Build a bookmarklet that, when clicked ON the portal login page, types
 * the User ID + Password into that page's own fields. This is the only
 * browser-safe way to auto-fill a third-party site (cross-origin blocks
 * our app from touching the portal tab directly).
 */
function buildBookmarklet(userId: string, password: string): string {
  const code =
    "(function(){var U=" +
    JSON.stringify(userId) +
    ",P=" +
    JSON.stringify(password) +
    ";function s(e,v){var p=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;" +
    "var d=Object.getOwnPropertyDescriptor(p,'value').set;d.call(e,v);" +
    "e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}" +
    "var pw=document.querySelector('input[type=password]');if(pw)s(pw,P);" +
    "var t=[].slice.call(document.querySelectorAll('input[type=text],input:not([type])'));" +
    "var u=t.filter(function(i){var n=((i.name||'')+(i.id||'')+(i.placeholder||''));" +
    "return !/captcha|code|otp|search/i.test(n)&&i.offsetParent!==null;})[0];if(u)s(u,U);" +
    "if(!pw&&!u){alert('Login fields not found — open the portal LOGIN page first, then click Auto-Fill.');}" +
    "else{try{(u||pw).focus();}catch(e){}}})();";
  return "javascript:" + encodeURIComponent(code);
}

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
        <Text style={st.title}>Test — Statutory Portals</Text>
        <Text style={st.subtitle}>
          Opens a government employer portal in a new tab and copies your saved
          User ID to the clipboard. Paste the User ID &amp; Password below into
          the portal, enter the captcha, and sign in.
        </Text>

        <PortalCard portalKey="esic" />
        <PortalCard portalKey="epfo" />
      </ScrollView>
    </SafeAreaView>
  );
}

function PortalCard({ portalKey }: { portalKey: PortalKey }) {
  const { selectedCompanyId } = useSelectedCompany();
  const cfg = PORTALS[portalKey];
  const [creds, setCreds] = useState<Creds | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<"user" | "pass" | null>(null);
  const [revealPass, setRevealPass] = useState(false);
  const [codeCopied, setCodeCopied] = useState(false);

  const bookmarklet = useMemo(
    () => (creds ? buildBookmarklet(creds.user_id, creds.password) : ""),
    [creds],
  );

  const copyCode = useCallback(async () => {
    if (!bookmarklet) return;
    await Clipboard.setStringAsync(bookmarklet);
    setCodeCopied(true);
    setTimeout(() => setCodeCopied(false), 1800);
  }, [bookmarklet]);

  const copy = useCallback(async (value: string, which: "user" | "pass") => {
    await Clipboard.setStringAsync(value);
    setCopied(which);
    setTimeout(() => setCopied(null), 1500);
  }, []);

  const launch = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      const qs = `?portal=${portalKey}${
        selectedCompanyId ? `&company_id=${selectedCompanyId}` : ""
      }`;
      const c = await api<Creds>(`/admin/portal-automation/esic-credentials${qs}`);
      setCreds(c);
      if (c.user_id) await copy(c.user_id, "user");
      openInNewTab(cfg.url);
    } catch (e: any) {
      setError(e?.message || "Could not load portal credentials.");
    } finally {
      setBusy(false);
    }
  }, [portalKey, selectedCompanyId, copy, cfg.url]);

  return (
    <View style={st.group}>
      <View style={st.card}>
        <View style={st.cardHead}>
          <View style={[st.iconWrap, { backgroundColor: `${cfg.tint}16` }]}>
            <Ionicons name={cfg.icon} size={22} color={cfg.tint} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={st.cardTitle}>{cfg.name}</Text>
            <Text style={st.cardUrl} numberOfLines={2}>{cfg.url}</Text>
          </View>
        </View>

        <Pressable
          style={[st.openBtn, busy && st.openBtnDisabled]}
          onPress={launch}
          disabled={busy}
          testID={`btn-open-${portalKey}-portal`}
        >
          {busy ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <Ionicons name="open-outline" size={18} color="#fff" />
          )}
          <Text style={st.openBtnTxt}>
            Open {portalKey === "esic" ? "ESIC" : "PF"} Portal (New Tab)
          </Text>
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
          <Text style={st.credHead}>
            Your {portalKey === "esic" ? "ESIC" : "PF (EPFO)"} Login (from Firm Master)
          </Text>

          <CredRow
            label="User ID"
            display={creds.user_id}
            copied={copied === "user"}
            onCopy={() => copy(creds.user_id, "user")}
          />
          <CredRow
            label="Password"
            display={
              revealPass
                ? creds.password
                : "•".repeat(Math.min(creds.password.length, 12))
            }
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

          <View style={st.divider} />

          <Text style={st.autoHead}>
            ⚡ Auto-Fill the portal (one-time setup)
          </Text>
          {Platform.OS === "web" ? (
            <>
              <WebDragButton href={bookmarklet} />
              <Text style={st.autoStep}>
                1. Drag the purple “Auto-Fill” button above onto your browser’s
                Bookmarks bar (press Ctrl+Shift+B to show it).{"\n"}
                2. Open the {portalKey === "esic" ? "ESIC" : "PF"} login page
                (button above).{"\n"}
                3. On that page, click the “Auto-Fill” bookmark — your User ID &
                Password fill in automatically. Enter the captcha and sign in.
              </Text>
            </>
          ) : (
            <Text style={st.autoStep}>
              Open this Test page on a computer (web) to use one-click Auto-Fill.
              On mobile, use the Copy buttons above and paste into the portal.
            </Text>
          )}
          <Pressable
            style={[st.codeBtn, codeCopied && st.copyBtnOk]}
            onPress={copyCode}
            hitSlop={6}
          >
            <Ionicons
              name={codeCopied ? "checkmark" : "code-slash-outline"}
              size={16}
              color={codeCopied ? "#059669" : colors.brandPrimary}
            />
            <Text style={[st.copyTxt, codeCopied && { color: "#059669" }]}>
              {codeCopied ? "Auto-Fill code copied" : "Copy Auto-Fill code (manual bookmark)"}
            </Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

/**
 * Web-only draggable anchor rendered as a real HTML <a> so the user can
 * drag it to the bookmarks bar. On web, react-dom renders lowercase tags
 * directly, so this works even inside react-native-web.
 */
function WebDragButton({ href }: { href: string }) {
  if (Platform.OS !== "web" || !href) return null;
  // React DOM sanitizes `javascript:` hrefs (replaces them with an error).
  // Set the attribute directly on the mounted node to bypass that so the
  // dragged bookmark keeps the real bookmarklet code.
  const setRef = (node: any) => {
    if (node) node.setAttribute("href", href);
  };
  return React.createElement(
    "a",
    {
      ref: setRef,
      draggable: true,
      onClick: (e: any) => e.preventDefault(),
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        background: "#7C3AED",
        color: "#fff",
        padding: "12px 16px",
        borderRadius: 10,
        textDecoration: "none",
        fontWeight: 800,
        fontSize: 14,
        cursor: "grab",
        alignSelf: "flex-start",
        userSelect: "none",
      },
    },
    "🔖 SKS Auto-Fill (drag me to Bookmarks bar)",
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
  wrap: { padding: 20, gap: 16, maxWidth: 640, width: "100%", alignSelf: "center" },
  title: { fontSize: 22, fontWeight: "800", color: colors.textPrimary },
  subtitle: { fontSize: 13, color: colors.textSecondary, lineHeight: 19 },
  group: { gap: 12 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, padding: 16, gap: 14,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 12 },
  iconWrap: {
    width: 44, height: 44, borderRadius: 12, alignItems: "center",
    justifyContent: "center",
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
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 2 },
  autoHead: { fontSize: 13.5, fontWeight: "800", color: colors.textPrimary },
  autoStep: { fontSize: 12.5, color: colors.textSecondary, lineHeight: 19 },
  codeBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 8,
    paddingVertical: 8, paddingHorizontal: 12,
  },
});
