import React, { useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, Image,
  ActivityIndicator, KeyboardAvoidingView, Platform, useWindowDimensions,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { Redirect, useRouter } from "expo-router";

import { api, saveToken } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { DESKTOP_MIN } from "@/src/components/AdminWebShell";

/**
 * Admin PIN sign-in — accepts email OR phone as the identifier +
 * a 6-digit PIN. Only company_admin / super_admin can log in here.
 */
export default function AdminPinLoginScreen() {
  const { user, loading, refresh } = useAuth();
  const router = useRouter();
  const { width } = useWindowDimensions();

  const [mode, setMode] = useState<"pin" | "password">("pin");
  const [identifier, setIdentifier] = useState("");
  const [pin, setPin] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSecret, setShowSecret] = useState(false);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brandPrimary} />
      </View>
    );
  }
  if (user) {
    // Employees are not allowed in the Employer/Admin portal.
    if (user.role === "employee") return <Redirect href="/employee" />;
    if (user.pin_must_change) return <Redirect href="/pin-change" />;
    return <Redirect href="/" />;
  }

  const submit = async () => {
    setError(null);
    const id = identifier.trim();
    if (!id) {
      setError(mode === "password" ? "Enter your email" : "Enter your email or phone number");
      return;
    }
    if (mode === "pin") {
      const p = pin.trim();
      if (!/^\d{6}$/.test(p)) { setError("PIN must be exactly 6 digits"); return; }
      setBusy(true);
      try {
        const r = await api<{ session_token: string; user: any; pin_must_change: boolean }>(
          "/auth/admin-pin-login",
          { method: "POST", auth: false, body: { identifier: id, pin: p } },
        );
        await saveToken(r.session_token);
        await refresh();
        // Iter 184 — land on "/" so the root guard routes admins to the
        // Portal Dashboard (desktop web) or /(tabs) (mobile).
        router.replace(r.pin_must_change ? "/pin-change" : "/");
      } catch (e: any) {
        setError(e.message || "Sign-in failed");
      } finally {
        setBusy(false);
      }
    } else {
      if (!id.includes("@") && id.length < 3) { setError("Enter your email or User ID"); return; }
      if (!password || password.length < 6) { setError("Enter your password"); return; }
      setBusy(true);
      try {
        const r = await api<{ session_token: string; user: any; password_must_change?: boolean }>(
          "/auth/admin-password-login",
          { method: "POST", auth: false, body: { email: id, password } },
        );
        await saveToken(r.session_token);
        await refresh();
        // Iter 184 — root guard sends admins to the Portal Dashboard.
        router.replace("/");
      } catch (e: any) {
        const msg = e?.message || "Sign-in failed";
        // Iter 64 — When the server tells us the account has no web
        // password yet, auto-switch to PIN mode so the user has a clear
        // next step instead of a dead-end.
        if (/password login is not set up/i.test(msg)) {
          setMode("pin");
          setPassword("");
          setError(
            "This account doesn't have a web password yet. Sign in with your PIN below — you can set a password from Profile after logging in.",
          );
        } else {
          setError(msg);
        }
      } finally {
        setBusy(false);
      }
    }
  };

  // Treat only WIDE web (≥960px) as "web" for layout — a phone-sized web
  // viewport (mobile browser / installed PWA) uses the SAME mobile layout
  // as the native app, including the Employee sign-in link.
  const isWeb = Platform.OS === "web" && width >= DESKTOP_MIN;

  // Iter 65 — Professional enterprise split-layout on web.
  // Left panel: brand hero (navy gradient, logo, trust chips, tagline).
  // Right panel: sign-in card. On mobile we keep the current stacked flow.
  const formContent = (
    <View style={isWeb ? styles.webCard : undefined}>
      {!isWeb && (
        <LinearGradient
          colors={["#1D4ED8", "#2563EB"]}
          start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
          style={styles.iconWrap}
        >
          <Ionicons name="shield-checkmark" size={26} color="#fff" />
        </LinearGradient>
      )}
      {isWeb && (
        <View style={styles.webCardHead}>
          <View style={styles.webBadge}>
            <Ionicons name="shield-checkmark" size={14} color={colors.brandPrimary} />
            <Text style={styles.webBadgeTxt}>Admin portal</Text>
          </View>
          <Text style={styles.webCardTitle}>Welcome back</Text>
          <Text style={styles.webCardSub}>
            Sign in to manage attendance, payroll and compliance across your firms.
          </Text>
        </View>
      )}
      {!isWeb && (
        <>
          <Text style={styles.title}>Employer Sign In</Text>
          <Text style={styles.subtitle}>
            {mode === "pin"
              ? "Enter your registered email or phone number, followed by your 6-digit PIN."
              : "Sign in with your registered email and password."}
          </Text>
        </>
      )}

      <View style={styles.modeRow}>
        <Pressable
          testID="mode-pin"
          onPress={() => { setMode("pin"); setError(null); }}
          style={[styles.modeTab, mode === "pin" && styles.modeTabOn]}
        >
          <Ionicons
            name="keypad-outline"
            size={14}
            color={mode === "pin" ? colors.onCta : colors.brandPrimary}
          />
          <Text style={[styles.modeTxt, mode === "pin" && styles.modeTxtOn]}>PIN</Text>
        </Pressable>
        <Pressable
          testID="mode-password"
          onPress={() => { setMode("password"); setError(null); }}
          style={[styles.modeTab, mode === "password" && styles.modeTabOn]}
        >
          <Ionicons
            name="lock-closed-outline"
            size={14}
            color={mode === "password" ? colors.onCta : colors.brandPrimary}
          />
          <Text style={[styles.modeTxt, mode === "password" && styles.modeTxtOn]}>
            Password
          </Text>
        </Pressable>
      </View>

      <Text style={styles.label}>
        {mode === "pin" ? "Email or phone" : "Email / Mobile no. / User ID"}
      </Text>
      <TextInput
        testID="admin-identifier-input"
        value={identifier}
        onChangeText={setIdentifier}
        placeholder={
          mode === "pin"
            ? "you@company.com  or  +91 98765 43210"
            : "you@company.com  ·  +91 98765 43210  ·  User ID"
        }
        placeholderTextColor={colors.onSurfaceTertiary}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="email-address"
        returnKeyType="next"
        onSubmitEditing={() => { if (!busy) submit(); }}
        blurOnSubmit={false}
        style={styles.input}
      />

      {mode === "pin" ? (
        <>
          <Text style={styles.label}>PIN</Text>
          <View style={styles.pinRow}>
            <TextInput
              testID="admin-pin-input"
              value={pin}
              onChangeText={(t) => setPin(t.replace(/\D/g, "").slice(0, 6))}
              placeholder="6-digit PIN"
              placeholderTextColor={colors.onSurfaceTertiary}
              keyboardType="number-pad"
              secureTextEntry={!showSecret}
              maxLength={6}
              returnKeyType="go"
              onSubmitEditing={() => { if (!busy) submit(); }}
              style={[styles.input, { flex: 1, marginTop: 0 }]}
            />
            <Pressable
              onPress={() => setShowSecret((v) => !v)}
              hitSlop={8}
              style={styles.eyeBtn}
            >
              <Ionicons
                name={showSecret ? "eye-off-outline" : "eye-outline"}
                size={20}
                color={colors.onSurfaceSecondary}
              />
            </Pressable>
          </View>
        </>
      ) : (
        <>
          <Text style={styles.label}>Password</Text>
          <View style={styles.pinRow}>
            <TextInput
              testID="admin-password-input"
              value={password}
              onChangeText={setPassword}
              placeholder="At least 8 characters"
              placeholderTextColor={colors.onSurfaceTertiary}
              secureTextEntry={!showSecret}
              autoCapitalize="none"
              autoCorrect={false}
              returnKeyType="go"
              onSubmitEditing={() => { if (!busy) submit(); }}
              style={[styles.input, { flex: 1, marginTop: 0 }]}
            />
            <Pressable
              onPress={() => setShowSecret((v) => !v)}
              hitSlop={8}
              style={styles.eyeBtn}
            >
              <Ionicons
                name={showSecret ? "eye-off-outline" : "eye-outline"}
                size={20}
                color={colors.onSurfaceSecondary}
              />
            </Pressable>
          </View>
        </>
      )}

      {error && (
        <View style={styles.errBox} testID="admin-pin-error">
          <Ionicons name="alert-circle" size={16} color={colors.onError} />
          <Text style={styles.errTxt}>{error}</Text>
        </View>
      )}

      <Pressable
        testID="admin-pin-submit"
        style={[styles.cta, isWeb && styles.ctaWeb, busy && { opacity: 0.7 }]}
        onPress={submit}
        disabled={busy}
      >
        {busy ? (
          <ActivityIndicator color={colors.onCta} />
        ) : (
          <>
            <Text style={[styles.ctaTxt, isWeb && styles.ctaTxtWeb]}>Sign in</Text>
            <Ionicons name="arrow-forward" size={18} color={isWeb ? "#ffffff" : colors.onCta} />
          </>
        )}
      </Pressable>

      {mode === "pin" ? (
        <Pressable
          onPress={() => router.push("/forgot-pin")}
          style={styles.forgotLink}
          testID="admin-forgot-pin"
        >
          <Text style={styles.forgotTxt}>Forgot PIN?</Text>
        </Pressable>
      ) : null}
    </View>
  );

  if (isWeb) {
    return (
      <View style={styles.webRoot} testID="admin-pin-login-screen">
        {/* Left brand panel */}
        <View style={styles.webLeftPane}>
          <View style={styles.webLeftBlob} />
          <View style={styles.webLeftBlob2} />
          <View style={styles.webLeftContent}>
            <View style={styles.webLogo}>
              <Image
                source={require("../assets/images/logo-mark.png")}
                style={{ width: 76, height: 76, borderRadius: 16 }}
                resizeMode="contain"
              />
            </View>
            <Text style={styles.webBrand}>S.K. Sharma & Co.</Text>
            <View style={styles.webTagRow}>
              <Text style={styles.webTagPill}>COMPLIANCE</Text>
              <View style={styles.webDot} />
              <Text style={styles.webTagPill}>PAYROLL</Text>
              <View style={styles.webDot} />
              <Text style={styles.webTagPill}>MANPOWER</Text>
            </View>
            <Text style={styles.webTagline}>
              One workplace platform for biometric attendance, payroll and
              labour-law compliance — trusted by industry-leading firms.
            </Text>
            <View style={styles.webTrustRow}>
              <WebTrust icon="shield-checkmark" label="Geofenced" />
              <WebTrust icon="finger-print" label="Biometric" />
              <WebTrust icon="lock-closed" label="Encrypted" />
            </View>
            <View style={styles.webFoot}>
              <Text style={styles.webFootTxt}>
                © 2026 S.K. Sharma & Co. · All rights reserved
              </Text>
            </View>
          </View>
        </View>

        {/* Right sign-in pane */}
        <View style={styles.webRightPane}>
          <View style={styles.webTopBar}>
            <Pressable onPress={() => router.push("/")} hitSlop={8} style={styles.webBack}>
              <Ionicons name="chevron-back" size={18} color={colors.onSurfaceSecondary} />
              <Text style={styles.webBackTxt}>Back</Text>
            </Pressable>
          </View>
          <View style={styles.webRightInner}>{formContent}</View>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root} testID="admin-pin-login-screen">
      <LinearGradient
        colors={["#1E3A8A", "#1D4ED8", "#2563EB", "#3B82F6"]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={StyleSheet.absoluteFill}
      />
      <View style={styles.orb1} pointerEvents="none" />
      <View style={styles.orb2} pointerEvents="none" />

      <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8} style={styles.mobBackBtn}>
            <Ionicons name="chevron-back" size={22} color="#fff" />
          </Pressable>
          <View style={styles.brandRow}>
            <View style={styles.brandMark}>
              <Ionicons name="shield-checkmark" size={14} color="#fff" />
            </View>
            <Text style={styles.brandTxt}>S.K. Sharma &amp; Co.</Text>
          </View>
          <View style={{ width: 38 }} />
        </View>

        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={{ flex: 1 }}
        >
          <KeyboardAwareScrollView bottomOffset={62}
            contentContainerStyle={styles.scroll}
            keyboardShouldPersistTaps="handled"
          >
            <View style={styles.mobCard}>
              {formContent}
            </View>
            <View style={styles.trustRowMob}>
              <Ionicons name="lock-closed" size={12} color="rgba(255,255,255,0.85)" />
              <Text style={styles.trustTxtMob}>Secured with end-to-end encryption</Text>
            </View>
            <Text style={styles.footerTxtMob}>Compliance &amp; Workforce Portal · S.K. Sharma &amp; Co.</Text>
          </KeyboardAwareScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}

function WebTrust({ icon, label }: { icon: any; label: string }) {
  return (
    <View style={styles.webTrustItem}>
      <Ionicons name={icon} size={14} color="#0EA5E9" />
      <Text style={styles.webTrustTxt}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#1D4ED8" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  orb1: {
    position: "absolute", width: 280, height: 280, borderRadius: 140,
    backgroundColor: "rgba(255,255,255,0.08)", top: -90, right: -70,
  },
  orb2: {
    position: "absolute", width: 200, height: 200, borderRadius: 100,
    backgroundColor: "rgba(255,255,255,0.06)", bottom: 60, left: -80,
  },
  mobBackBtn: {
    width: 38, height: 38, borderRadius: 12,
    backgroundColor: "rgba(255,255,255,0.16)",
    borderWidth: 1, borderColor: "rgba(255,255,255,0.25)",
    alignItems: "center", justifyContent: "center",
  },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  brandMark: {
    width: 24, height: 24, borderRadius: 8,
    backgroundColor: "rgba(255,255,255,0.2)",
    borderWidth: 1, borderColor: "rgba(255,255,255,0.35)",
    alignItems: "center", justifyContent: "center",
  },
  brandTxt: { color: "#fff", fontSize: 14, fontWeight: "800", letterSpacing: 0.3 },
  mobCard: {
    backgroundColor: "rgba(255,255,255,0.95)",
    borderRadius: 24,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.7)",
    padding: 22,
    shadowColor: "#0B1E56",
    shadowOffset: { width: 0, height: 18 },
    shadowOpacity: 0.35,
    shadowRadius: 32,
    elevation: 14,
  },
  trustRowMob: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, marginTop: 18,
  },
  trustTxtMob: { color: "rgba(255,255,255,0.85)", fontSize: 12, fontWeight: "600" },
  footerTxtMob: {
    color: "rgba(255,255,255,0.6)", fontSize: 11, textAlign: "center", marginTop: 6,
  },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xl, flexGrow: 1, justifyContent: "center" },
  iconWrap: {
    width: 56, height: 56, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
    alignSelf: "center",
    marginBottom: spacing.md,
    shadowColor: "#1D4ED8",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.35,
    shadowRadius: 14,
    elevation: 8,
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
  },
  pinRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  eyeBtn: { padding: 8 },
  modeRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: spacing.md,
    alignSelf: "center",
  },
  modeTab: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  modeTabOn: {
    backgroundColor: colors.brandPrimary,
  },
  modeTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: type.sm },
  modeTxtOn: { color: colors.onCta },
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
  ctaWeb: {
    backgroundColor: "#0EA5E9",
    borderRadius: radius.md,
    shadowColor: "#0EA5E9",
    shadowOpacity: 0.18,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 6 },
  },
  ctaTxtWeb: { color: "#ffffff" },
  altLink: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    marginTop: spacing.lg,
  },
  altLinkTxt: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "600" },
  forgotLink: { alignSelf: "center", padding: spacing.sm, marginTop: spacing.sm },
  forgotTxt: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "600", textDecorationLine: "underline" },

  // -------- Iter 66: Web split-screen (sky-blue palette) --------
  webRoot: {
    flex: 1,
    flexDirection: "row",
    backgroundColor: "#F8FAFC",
    minHeight: 720,
  },
  webLeftPane: {
    flex: 1,
    backgroundColor: "#EFF6FF",
    padding: spacing.xl * 1.5,
    justifyContent: "center",
    overflow: "hidden",
    position: "relative",
    minWidth: 360,
    maxWidth: 620,
    borderRightWidth: 1,
    borderRightColor: "#DBEAFE",
  },
  webLeftBlob: {
    position: "absolute", top: -160, right: -160,
    width: 480, height: 480, borderRadius: 240,
    backgroundColor: "#93C5FD", opacity: 0.35,
  },
  webLeftBlob2: {
    position: "absolute", bottom: -140, left: -120,
    width: 380, height: 380, borderRadius: 190,
    backgroundColor: "#BAE6FD", opacity: 0.55,
  },
  webLeftContent: { zIndex: 1 },
  webLogo: {
    width: 88, height: 88, borderRadius: 22,
    backgroundColor: "#ffffff",
    borderWidth: 1, borderColor: "#DBEAFE",
    alignItems: "center", justifyContent: "center",
    marginBottom: spacing.lg,
    shadowColor: "#0F172A", shadowOpacity: 0.06,
    shadowRadius: 12, shadowOffset: { width: 0, height: 4 },
  },
  webBrand: {
    color: "#0F172A", fontSize: 40, fontWeight: "800",
    letterSpacing: -1, marginBottom: spacing.md,
  },
  webTagRow: {
    flexDirection: "row", alignItems: "center",
    gap: 10, marginBottom: spacing.lg,
  },
  webTagPill: {
    color: "#0369A1", fontSize: 11, fontWeight: "800", letterSpacing: 2,
  },
  webDot: { width: 4, height: 4, borderRadius: 2, backgroundColor: "#60A5FA" },
  webTagline: {
    color: "#334155", fontSize: 16, lineHeight: 26,
    marginBottom: spacing.xl, maxWidth: 460,
  },
  webTrustRow: { flexDirection: "row", gap: 10, flexWrap: "wrap" },
  webTrustItem: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#ffffff",
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: 999, borderWidth: 1, borderColor: "#DBEAFE",
  },
  webTrustTxt: { color: "#0369A1", fontSize: 12, fontWeight: "700" },
  webFoot: { position: "absolute", bottom: -spacing.xl, left: 0, right: 0 },
  webFootTxt: {
    color: "#64748B", fontSize: 11, marginTop: spacing.xl * 2,
  },

  webRightPane: {
    flex: 1.2,
    backgroundColor: "#F8FAFC",
    minHeight: 720,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: spacing.xl,
    position: "relative",
  },
  webTopBar: {
    position: "absolute",
    top: spacing.lg, right: spacing.lg,
    flexDirection: "row",
  },
  webBack: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingVertical: 6, paddingHorizontal: 10, borderRadius: 8,
  },
  webBackTxt: { color: "#475569", fontSize: 13, fontWeight: "600" },
  webRightInner: { width: "100%", maxWidth: 440 },
  webCard: {
    backgroundColor: "#ffffff",
    borderRadius: 20,
    padding: spacing.xl * 1.2,
    borderWidth: 1, borderColor: "#E2E8F0",
    shadowColor: "#0F172A", shadowOpacity: 0.06,
    shadowRadius: 24, shadowOffset: { width: 0, height: 12 },
  },
  webCardHead: { alignItems: "flex-start", marginBottom: spacing.md },
  webBadge: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 999,
    backgroundColor: "#DBEAFE",
    marginBottom: spacing.md,
  },
  webBadgeTxt: {
    color: "#0369A1", fontSize: 11, fontWeight: "800",
    letterSpacing: 0.5, textTransform: "uppercase",
  },
  webCardTitle: {
    color: "#0F172A", fontSize: 26, fontWeight: "800", letterSpacing: -0.4,
  },
  webCardSub: {
    color: "#64748B", fontSize: 14, lineHeight: 22, marginTop: 4,
  },
});
