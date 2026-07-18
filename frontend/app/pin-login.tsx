import React, { useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, KeyboardAvoidingView, Platform, useWindowDimensions,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";
import { LinearGradient } from "expo-linear-gradient";

import { api, saveToken } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, spacing } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

/**
 * Employee sign-in — premium enterprise PWA design (Microsoft 365 / SAP /
 * Zoho One inspired). Blue gradient backdrop + glassmorphism card.
 *
 * Supports Mobile / Username identifiers + 6-digit PIN or employer-set
 * password. Auth logic is unchanged — visual redesign only.
 */
type IdentType = "phone" | "login_id";

const IDENT_TABS: { key: IdentType; label: string; icon: keyof typeof Ionicons.glyphMap; placeholder: string; keyboardType: "phone-pad" | "number-pad" | "default" }[] = [
  { key: "phone", label: "Mobile", icon: "call-outline", placeholder: "+91 98765 43210", keyboardType: "phone-pad" },
  { key: "login_id", label: "Username", icon: "person-circle-outline", placeholder: "Username from employer", keyboardType: "default" },
];

const BLUE = "#1D4ED8";
const BLUE2 = "#2563EB";
const INK = "#0F172A";
const INK2 = "#475569";
const INK3 = "#94A3B8";
const FIELD_BORDER = "#E2E8F0";

export default function PinLoginScreen() {
  const { user, loading, refresh } = useAuth();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isWide = width >= 640;

  const [identType, setIdentType] = useState<IdentType>("phone");
  const [ident, setIdent] = useState("");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPin, setShowPin] = useState(false);
  // Iter 96l — username logins can use a PIN or an employer-set password.
  const [secretMode, setSecretMode] = useState<"pin" | "password">("pin");
  const usernameMode = identType === "login_id";

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brandPrimary} />
      </View>
    );
  }
  if (user) {
    if (user.pin_must_change) return <Redirect href="/pin-change" />;
    return <Redirect href="/(tabs)" />;
  }

  const submit = async () => {
    setError(null);
    const v = ident.trim();
    const p = pin.trim();
    if (!v) {
      setError(`Enter your ${IDENT_TABS.find((t) => t.key === identType)?.label || "identifier"}`);
      return;
    }
    if (identType === "phone" && v.replace(/\D/g, "").length < 8) {
      setError("Enter a valid mobile number");
      return;
    }

    // Username + Password path (employer-set credentials).
    if (usernameMode && secretMode === "password") {
      if (!p) { setError("Enter your password"); return; }
      setBusy(true);
      try {
        const r = await api<{ session_token: string; user: any; password_must_change: boolean }>(
          "/auth/employee-password-login",
          { method: "POST", auth: false, body: { login_id: v, password: p } },
        );
        await saveToken(r.session_token);
        await refresh();
        router.replace("/(tabs)");
      } catch (e: any) {
        setError(e.message || "Sign-in failed");
      } finally {
        setBusy(false);
      }
      return;
    }

    // PIN path (all identifier types).
    if (!/^\d{6}$/.test(p)) {
      setError("PIN must be exactly 6 digits");
      return;
    }
    setBusy(true);
    try {
      const body: any = { pin: p };
      body[identType] = v;
      const r = await api<{ session_token: string; user: any; pin_must_change: boolean }>(
        "/auth/pin-login",
        {
          method: "POST",
          auth: false,
          body,
        },
      );
      await saveToken(r.session_token);
      await refresh();
      router.replace(r.pin_must_change ? "/pin-change" : "/(tabs)");
    } catch (e: any) {
      setError(e.message || "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.root} testID="pin-login-screen">
      <LinearGradient
        colors={["#1E3A8A", BLUE, BLUE2, "#3B82F6"]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={StyleSheet.absoluteFill}
      />
      {/* Decorative orbs for depth */}
      <View style={styles.orb1} pointerEvents="none" />
      <View style={styles.orb2} pointerEvents="none" />
      <View style={styles.orb3} pointerEvents="none" />

      <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8} style={styles.backBtn}>
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

        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
          <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            <View style={[styles.card, isWide && styles.cardWide]}>
              {/* Card header */}
              <LinearGradient
                colors={[BLUE, BLUE2]}
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 1 }}
                style={styles.iconWrap}
              >
                <Ionicons name="person" size={26} color="#fff" />
              </LinearGradient>
              <Text style={styles.title}>Employee Sign In</Text>
              <Text style={styles.subtitle}>
                Use your mobile number or the username your employer gave you.
              </Text>

              {/* Identifier type picker */}
              <View style={styles.segTrack}>
                {IDENT_TABS.map((t) => (
                  <Pressable
                    key={t.key}
                    onPress={() => {
                      setIdentType(t.key);
                      setIdent("");
                      setPin("");
                      setSecretMode("pin");
                      setError(null);
                    }}
                    style={[styles.segBtn, identType === t.key && styles.segBtnOn]}
                    testID={`pin-ident-${t.key}`}
                  >
                    <Ionicons
                      name={t.icon}
                      size={15}
                      color={identType === t.key ? BLUE : INK3}
                    />
                    <Text style={[styles.segTxt, identType === t.key && styles.segTxtOn]}>
                      {t.label}
                    </Text>
                  </Pressable>
                ))}
              </View>

              <Text style={styles.label}>{IDENT_TABS.find((t) => t.key === identType)?.label}</Text>
              <View style={styles.fieldWrap}>
                <Ionicons
                  name={IDENT_TABS.find((t) => t.key === identType)?.icon || "call-outline"}
                  size={18}
                  color={INK3}
                  style={styles.fieldIcon}
                />
                <TextInput
                  testID="pin-phone-input"
                  value={ident}
                  onChangeText={setIdent}
                  placeholder={IDENT_TABS.find((t) => t.key === identType)?.placeholder}
                  placeholderTextColor={INK3}
                  keyboardType={IDENT_TABS.find((t) => t.key === identType)?.keyboardType || "default"}
                  autoCapitalize="none"
                  autoCorrect={false}
                  style={styles.input}
                />
              </View>

              {usernameMode && (
                <View style={[styles.segTrack, { marginTop: 14 }]}>
                  {(["pin", "password"] as const).map((mkey) => (
                    <Pressable
                      key={mkey}
                      onPress={() => { setSecretMode(mkey); setPin(""); setError(null); }}
                      style={[styles.segBtn, secretMode === mkey && styles.segBtnOn]}
                      testID={`pin-mode-${mkey}`}
                    >
                      <Ionicons
                        name={mkey === "pin" ? "keypad-outline" : "lock-closed-outline"}
                        size={15}
                        color={secretMode === mkey ? BLUE : INK3}
                      />
                      <Text style={[styles.segTxt, secretMode === mkey && styles.segTxtOn]}>
                        {mkey === "pin" ? "PIN" : "Password"}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              )}

              <Text style={styles.label}>{usernameMode && secretMode === "password" ? "Password" : "Security PIN"}</Text>
              <View style={styles.fieldWrap}>
                <Ionicons name="lock-closed-outline" size={18} color={INK3} style={styles.fieldIcon} />
                <TextInput
                  testID="pin-pin-input"
                  value={pin}
                  onChangeText={(t) =>
                    usernameMode && secretMode === "password"
                      ? setPin(t)
                      : setPin(t.replace(/\D/g, "").slice(0, 6))
                  }
                  placeholder={usernameMode && secretMode === "password" ? "Your password" : "6-digit PIN"}
                  placeholderTextColor={INK3}
                  keyboardType={usernameMode && secretMode === "password" ? "default" : "number-pad"}
                  autoCapitalize="none"
                  autoCorrect={false}
                  secureTextEntry={!showPin}
                  maxLength={usernameMode && secretMode === "password" ? 64 : 6}
                  style={styles.input}
                />
                <Pressable onPress={() => setShowPin((v) => !v)} hitSlop={8} style={styles.eyeBtn}>
                  <Ionicons
                    name={showPin ? "eye-off-outline" : "eye-outline"}
                    size={19}
                    color={INK3}
                  />
                </Pressable>
              </View>

              {error && (
                <View style={styles.errBox} testID="pin-error">
                  <Ionicons name="alert-circle" size={16} color="#B91C1C" />
                  <Text style={styles.errTxt}>{error}</Text>
                </View>
              )}

              <Pressable
                testID="pin-submit"
                style={({ pressed }) => [styles.ctaOuter, (busy || pressed) && { opacity: 0.85 }]}
                onPress={submit}
                disabled={busy}
              >
                <LinearGradient
                  colors={[BLUE, BLUE2]}
                  start={{ x: 0, y: 0 }}
                  end={{ x: 1, y: 0 }}
                  style={styles.cta}
                >
                  {busy ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <>
                      <Text style={styles.ctaTxt}>Sign in securely</Text>
                      <Ionicons name="arrow-forward" size={18} color="#fff" />
                    </>
                  )}
                </LinearGradient>
              </Pressable>

              <View style={styles.dividerRow}>
                <View style={styles.dividerLine} />
                <Text style={styles.dividerTxt}>New employee?</Text>
                <View style={styles.dividerLine} />
              </View>

              <Pressable
                onPress={() => router.push("/employee-signup")}
                style={styles.signupBtn}
                testID="employee-signup-link"
              >
                <Ionicons name="person-add-outline" size={16} color={BLUE} />
                <Text style={styles.signupTxt}>Create new employee account</Text>
              </Pressable>
            </View>

            <View style={styles.trustRow}>
              <Ionicons name="lock-closed" size={12} color="rgba(255,255,255,0.85)" />
              <Text style={styles.trustTxt}>Secured with end-to-end encryption</Text>
            </View>
            <Text style={styles.footerTxt}>Compliance &amp; Workforce Portal · S.K. Sharma &amp; Co.</Text>
          </KeyboardAwareScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: BLUE },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  orb1: {
    position: "absolute", width: 280, height: 280, borderRadius: 140,
    backgroundColor: "rgba(255,255,255,0.08)", top: -90, right: -70,
  },
  orb2: {
    position: "absolute", width: 200, height: 200, borderRadius: 100,
    backgroundColor: "rgba(255,255,255,0.06)", bottom: 60, left: -80,
  },
  orb3: {
    position: "absolute", width: 120, height: 120, borderRadius: 60,
    backgroundColor: "rgba(96,165,250,0.25)", top: "38%", right: -40,
  },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  backBtn: {
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
  scroll: { padding: spacing.lg, paddingBottom: spacing.xl, flexGrow: 1, justifyContent: "center" },
  card: {
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
    width: "100%",
    alignSelf: "center",
  },
  cardWide: { maxWidth: 460, padding: 32 },
  iconWrap: {
    width: 58, height: 58, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
    alignSelf: "center",
    marginBottom: 14,
    shadowColor: BLUE,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.35,
    shadowRadius: 14,
    elevation: 8,
  },
  title: { color: INK, fontSize: 22, fontWeight: "800", textAlign: "center", letterSpacing: -0.3 },
  subtitle: {
    color: INK2, fontSize: 13, lineHeight: 19,
    textAlign: "center", marginTop: 6, marginBottom: 18,
  },
  segTrack: {
    flexDirection: "row",
    backgroundColor: "#F1F5F9",
    borderRadius: 14,
    padding: 4,
    gap: 4,
  },
  segBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    borderRadius: 11,
  },
  segBtnOn: {
    backgroundColor: "#fff",
    shadowColor: "#0F172A",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.08,
    shadowRadius: 6,
    elevation: 2,
  },
  segTxt: { fontSize: 13, fontWeight: "700", color: INK3 },
  segTxtOn: { color: BLUE },
  label: { color: INK2, fontSize: 12.5, fontWeight: "700", marginTop: 16, marginBottom: 7, letterSpacing: 0.2, textTransform: "uppercase" },
  fieldWrap: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#F8FAFC",
    borderWidth: 1.5,
    borderColor: FIELD_BORDER,
    borderRadius: 14,
    paddingHorizontal: 12,
  },
  fieldIcon: { marginRight: 8 },
  input: {
    flex: 1,
    paddingVertical: Platform.OS === "web" ? 13 : 12,
    color: INK,
    fontSize: 15,
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : {}),
  },
  eyeBtn: { padding: 6 },
  errBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#FEF2F2",
    borderWidth: 1, borderColor: "#FECACA",
    borderRadius: 12,
    padding: 10,
    marginTop: 14,
  },
  errTxt: { color: "#B91C1C", fontSize: 13, flex: 1, fontWeight: "600" },
  ctaOuter: {
    marginTop: 22,
    borderRadius: 14,
    shadowColor: BLUE,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.4,
    shadowRadius: 16,
    elevation: 8,
  },
  cta: {
    borderRadius: 14,
    paddingVertical: 15,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  ctaTxt: { color: "#fff", fontSize: 16, fontWeight: "800", letterSpacing: 0.2 },
  dividerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginTop: 24,
    marginBottom: 14,
  },
  dividerLine: { flex: 1, height: 1, backgroundColor: FIELD_BORDER },
  dividerTxt: { color: INK3, fontSize: 12.5, fontWeight: "600" },
  signupBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    borderWidth: 1.5,
    borderColor: "#BFDBFE",
    backgroundColor: "#EFF6FF",
    borderRadius: 14,
    paddingVertical: 13,
  },
  signupTxt: { color: BLUE, fontSize: 14.5, fontWeight: "800" },
  trustRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, marginTop: 18,
  },
  trustTxt: { color: "rgba(255,255,255,0.85)", fontSize: 12, fontWeight: "600" },
  footerTxt: {
    color: "rgba(255,255,255,0.6)", fontSize: 11, textAlign: "center", marginTop: 6,
  },
});
