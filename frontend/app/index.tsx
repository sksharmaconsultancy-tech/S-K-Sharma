import { Redirect, useRouter } from "expo-router";
import { useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Platform, useWindowDimensions } from "react-native";
import { Image } from "expo-image";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { DESKTOP_MIN } from "@/src/components/AdminWebShell";

export default function Landing() {
  const { user, loading, authError, clearAuthError } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const router = useRouter();
  const { width } = useWindowDimensions();

  // QR-scoped landing: when the visitor arrived via an Employee QR we hide
  // the Admin / Company options; via an Employer QR we hide Employee sign-in.
  const [qrType, setQrType] = useState<string | null>(() => {
    if (Platform.OS === "web" && typeof window !== "undefined") {
      try { return window.localStorage.getItem("qr_entry_type"); } catch { return null; }
    }
    return null;
  });
  const clearQrType = () => {
    try { window.localStorage.removeItem("qr_entry_type"); } catch {}
    setQrType(null);
  };

  if (loading) {
    return (
      <View style={styles.center} testID="landing-loading">
        <ActivityIndicator color={colors.brandPrimary} size="large" />
      </View>
    );
  }
  if (user) {
    if (user.pin_must_change) return <Redirect href="/pin-change" />;
    if (user.role === "employee" && user.offboarded) return <Redirect href="/offboarded" />;
    if (user.role === "employee" && user.approval_rejected) return <Redirect href="/register-choice" />;
    if (user.role === "employee" && user.approval_pending) return <Redirect href="/pending-approval" />;
    if (user.role === "employee" && !user.onboarded) return <Redirect href="/register-choice" />;
    // Iter 67 — SUB-ADMIN ONLY firm-select gate.  Super Admin & Company
    // Admin flows are unchanged (they land on the dashboard directly).
    const isSubAdmin = (user.role as string) === "sub_admin";
    if (isSubAdmin && !selectedCompanyId) return <Redirect href="/firm-select" />;
    return <Redirect href="/(tabs)" />;
  }

  const isWeb = Platform.OS === "web";
  // Desktop web (≥960px) gets the split-screen enterprise landing. A
  // phone-sized web viewport (mobile browser / installed PWA) falls
  // through to the SAME mobile landing the native app shows.
  const isWebDesktop = isWeb && width >= DESKTOP_MIN;

  if (isWebDesktop) {
    // Iter 65 — Professional enterprise landing on web. Split-screen with
    // a navy hero pane on the LEFT (branding + trust chips + tagline) and
    // a clean CTA card on the RIGHT (Admin sign in + Company sign in).
    return (
      <View style={styles.webRoot} testID="landing-screen">
        <View style={styles.webLeftPane}>
          <View style={styles.webLeftBlob} />
          <View style={styles.webLeftBlob2} />
          <View style={styles.webLeftContent}>
            <View style={styles.webLogo}>
              <Image
                source={require("../assets/images/logo-mark.png")}
                style={{ width: 60, height: 60 }}
                contentFit="contain"
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
              A single workplace platform for biometric attendance, payroll and
              labour-law compliance — trusted by industry-leading firms across India.
            </Text>
            <View style={styles.webFeatRow}>
              <WebFeature icon="shield-checkmark" title="Geofenced attendance" body="Auto punch-in / out with GPS + face verification." />
              <WebFeature icon="cash-outline" title="Automated payroll" body="Salary runs, PF / ESI / TDS challans, one click." />
              <WebFeature icon="lock-closed" title="Enterprise-grade security" body="Role-based access, encrypted PII, audit trails." />
            </View>
            <View style={styles.webFoot}>
              <Text style={styles.webFootTxt}>© 2026 S.K. Sharma & Co. · Trusted by 500+ firms</Text>
            </View>
          </View>
        </View>

        <View style={styles.webRightPane}>
          <View style={styles.webCard}>
            <View style={styles.webBadge}>
              <Ionicons name="business" size={12} color={colors.brandPrimary} />
              <Text style={styles.webBadgeTxt}>Web portal</Text>
            </View>
            <Text style={styles.webCardTitle}>Sign in to continue</Text>
            <Text style={styles.webCardSub}>
              Choose your role to access the S.K. Sharma & Co. portal.
            </Text>

            {authError && (
              <View style={styles.errorBanner} testID="auth-error-banner">
                <Ionicons name="alert-circle" size={18} color={colors.onError} />
                <Text style={styles.errorTxt}>{authError}</Text>
                <Pressable onPress={clearAuthError} hitSlop={8}>
                  <Ionicons name="close" size={16} color={colors.onError} />
                </Pressable>
              </View>
            )}

            <Pressable
              testID="admin-pin-login-button"
              style={({ pressed }) => [styles.webCtaPrimary, pressed && { opacity: 0.92 }]}
              onPress={() => router.push("/admin-pin-login")}
            >
              <Ionicons name="shield-checkmark-outline" size={20} color="#ffffff" />
              <View style={{ flex: 1 }}>
                <Text style={styles.webCtaPrimaryTxt}>Admin sign in</Text>
                <Text style={styles.webCtaPrimarySub}>
                  For Super Admins, Company Admins & Sub-Admins
                </Text>
              </View>
              <Ionicons name="arrow-forward" size={18} color="#ffffff" />
            </Pressable>

            <Pressable
              testID="company-login-button"
              style={({ pressed }) => [styles.webCtaSecondary, pressed && { opacity: 0.9 }]}
              onPress={() => router.push("/company-login")}
            >
              <Ionicons name="business-outline" size={20} color="#0F172A" />
              <View style={{ flex: 1 }}>
                <Text style={styles.webCtaSecondaryTxt}>Company sign in / register</Text>
                <Text style={styles.webCtaSecondarySub}>
                  Employer / firm owner portal onboarding
                </Text>
              </View>
              <Ionicons name="arrow-forward" size={16} color="#0F172A" />
            </Pressable>

            <View style={styles.webEmpNote} testID="employee-web-note">
              <Ionicons name="phone-portrait-outline" size={16} color={colors.onSurfaceSecondary} />
              <Text style={styles.webEmpNoteTxt}>
                Employees: sign in from the S.K. Sharma & Co. mobile app.
              </Text>
            </View>

            <Text style={styles.legal}>
              By continuing you agree to our Terms & Privacy.
            </Text>
          </View>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root} testID="landing-screen">
      <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
        {/* Decorative navy blob top-right */}
        <View style={styles.blob} />
        <View style={styles.blob2} />

        <View style={styles.center}>
          <View style={styles.logoWrap}>
            <Image
              source={require("../assets/images/logo-mark.png")}
              style={styles.logo}
              contentFit="contain"
            />
          </View>
          <Text style={styles.brand} numberOfLines={1} adjustsFontSizeToFit>S.K. Sharma & Co.</Text>
          <View style={styles.tagRow}>
            <Text style={styles.tagPill}>COMPLIANCE</Text>
            <View style={styles.tagDot} />
            <Text style={styles.tagPill}>PAYROLL</Text>
            <View style={styles.tagDot} />
            <Text style={styles.tagPill}>MANPOWER</Text>
          </View>
          <Text style={styles.subtitle}>
            One workplace app for biometric attendance, payroll and labour-law compliance.
          </Text>
        </View>

        <View style={styles.bottom}>
          {authError && (
            <View style={styles.errorBanner} testID="auth-error-banner">
              <Ionicons name="alert-circle" size={18} color={colors.onError} />
              <Text style={styles.errorTxt}>{authError}</Text>
              <Pressable onPress={clearAuthError} hitSlop={8}>
                <Ionicons name="close" size={16} color={colors.onError} />
              </Pressable>
            </View>
          )}

          <View style={styles.trustRow}>
            <TrustItem icon="shield-checkmark" label="Geo-fenced" />
            <View style={styles.trustDivider} />
            <TrustItem icon="finger-print" label="Biometric" />
            <View style={styles.trustDivider} />
            <TrustItem icon="lock-closed" label="Encrypted" />
          </View>

          {qrType !== "employee" ? (
            <Pressable
              testID="admin-pin-login-button"
              style={({ pressed }) => [styles.cta, pressed && { opacity: 0.92 }]}
              onPress={() => router.push("/admin-pin-login")}
            >
              <Ionicons name="shield-checkmark-outline" size={18} color={colors.onCta} />
              <Text style={styles.ctaTxt}>Admin sign in</Text>
            </Pressable>
          ) : null}

          {qrType !== "employee" ? (
            <Pressable
              testID="company-login-button"
              style={({ pressed }) => [styles.ctaSecondary, pressed && { opacity: 0.9 }]}
              onPress={() => router.push("/company-login")}
            >
              <Ionicons name="business-outline" size={18} color={colors.brandPrimary} />
              <Text style={styles.ctaSecondaryTxt}>Company sign in / register</Text>
            </Pressable>
          ) : null}

          {/* Iter 64 — Employee sign-in is a MOBILE-ONLY entry point.
              The web/admin portal is strictly for admins & company owners
              since employees don't have access to the desktop workflows
              (payroll runs, compliance, master sheets, etc.). Hiding the
              button on web keeps the landing focused and removes an
              unnecessary "dead-end" that led to confusion earlier. */}
          {!isWebDesktop && qrType !== "employer" ? (
            <Pressable
              testID="employee-pin-login-button"
              style={({ pressed }) => [
                qrType === "employee" ? styles.cta : styles.ctaSecondary,
                pressed && { opacity: 0.9 },
              ]}
              onPress={() => router.push("/pin-login")}
            >
              <Ionicons
                name="person-outline"
                size={18}
                color={qrType === "employee" ? colors.onCta : colors.brandPrimary}
              />
              <Text style={qrType === "employee" ? styles.ctaTxt : styles.ctaSecondaryTxt}>
                Employee sign in
              </Text>
            </Pressable>
          ) : isWebDesktop ? (
            <View style={styles.webEmpNote} testID="employee-web-note">
              <Ionicons
                name="phone-portrait-outline"
                size={16}
                color={colors.onSurfaceSecondary}
              />
              <Text style={styles.webEmpNoteTxt}>
                Employees: please sign in from the S.K. Sharma & Co. mobile app.
              </Text>
            </View>
          ) : null}

          {qrType ? (
            <Pressable onPress={clearQrType} style={{ marginTop: spacing.md }} testID="show-all-signin">
              <Text style={{ color: colors.onSurfaceTertiary, fontSize: 12, textAlign: "center", fontWeight: "600" }}>
                Show all sign-in options
              </Text>
            </Pressable>
          ) : null}

          <Text style={styles.legal}>
            By continuing you agree to S.K. Sharma & Co. Terms & Privacy.
          </Text>
        </View>
      </SafeAreaView>
    </View>
  );
}

function TrustItem({ icon, label }: { icon: any; label: string }) {
  return (
    <View style={styles.trustItem}>
      <Ionicons name={icon} size={16} color={colors.accent} />
      <Text style={styles.trustLbl}>{label}</Text>
    </View>
  );
}

function WebFeature({
  icon,
  title,
  body,
}: {
  icon: any;
  title: string;
  body: string;
}) {
  return (
    <View style={styles.webFeat}>
      <View style={styles.webFeatIcon}>
        <Ionicons name={icon} size={18} color="#0EA5E9" />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.webFeatTitle}>{title}</Text>
        <Text style={styles.webFeatBody}>{body}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  safe: { flex: 1, paddingHorizontal: spacing.lg },
  blob: {
    position: "absolute",
    top: -100,
    right: -80,
    width: 320,
    height: 320,
    borderRadius: 160,
    backgroundColor: colors.brandPrimary,
    opacity: 0.06,
  },
  blob2: {
    position: "absolute",
    bottom: 200,
    left: -100,
    width: 260,
    height: 260,
    borderRadius: 130,
    backgroundColor: colors.cta,
    opacity: 0.06,
  },
  center: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingHorizontal: spacing.md,
  },
  logoWrap: {
    width: 160, height: 160, borderRadius: 32,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center", justifyContent: "center",
    padding: 6,
    ...shadow.card,
  },
  logo: { width: "100%", height: "100%" },
  brand: {
    color: colors.onSurface,
    fontSize: 28,
    lineHeight: 34,
    fontWeight: "800",
    letterSpacing: -0.8,
    textAlign: "center",
    marginTop: spacing.lg,
    paddingHorizontal: spacing.md,
  },
  tagRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: spacing.md,
  },
  tagPill: {
    color: colors.accent,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1.5,
  },
  tagDot: {
    width: 3, height: 3, borderRadius: 1.5,
    backgroundColor: colors.borderStrong,
  },
  subtitle: {
    color: colors.onSurfaceSecondary,
    fontSize: type.base,
    marginTop: spacing.md,
    lineHeight: 22,
    textAlign: "center",
    maxWidth: 320,
  },
  bottom: { paddingBottom: spacing.md },
  trustRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: 12,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  trustItem: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  trustDivider: { width: 1, height: 20, backgroundColor: colors.border },
  trustLbl: { color: colors.onSurface, fontSize: type.sm, fontWeight: "600" },
  cta: {
    backgroundColor: colors.cta,
    borderRadius: radius.pill,
    paddingVertical: 18,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    ...shadow.cta,
  },
  ctaTxt: { color: colors.onCta, fontSize: type.lg, fontWeight: "700" },
  dividerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginTop: spacing.md,
  },
  dividerLine: { flex: 1, height: 1, backgroundColor: colors.border },
  dividerTxt: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    letterSpacing: 1.5,
    fontWeight: "700",
  },
  ctaSecondary: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.pill,
    paddingVertical: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    marginTop: spacing.md,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
  },
  ctaSecondaryTxt: { color: colors.brandPrimary, fontSize: type.base, fontWeight: "600" },
  legal: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    textAlign: "center",
    marginTop: spacing.md,
    lineHeight: 18,
  },
  errorBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.error,
    borderRadius: radius.md,
    paddingVertical: 10,
    paddingHorizontal: 12,
    marginBottom: spacing.md,
  },
  errorTxt: { flex: 1, color: colors.onError, fontSize: type.sm, lineHeight: 18 },
  webEmpNote: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    paddingHorizontal: 12,
    marginTop: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
  },
  webEmpNoteTxt: {
    color: colors.onSurfaceSecondary,
    fontSize: 12,
    fontWeight: "600",
    flexShrink: 1,
    textAlign: "center",
  },

  // -------- Iter 65: Professional web landing (sky-blue palette) --------
  webRoot: {
    flex: 1,
    flexDirection: "row",
    backgroundColor: colors.background,
    minHeight: 720,
  },
  webLeftPane: {
    flex: 1,
    // Iter 66 — Switched from dark navy to a soft sky-blue that reduces
    // eye strain during long portal sessions. Text switches to dark
    // navy for readable contrast.
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
    position: "absolute",
    top: -160,
    right: -160,
    width: 480,
    height: 480,
    borderRadius: 240,
    backgroundColor: "#93C5FD",
    opacity: 0.35,
  },
  webLeftBlob2: {
    position: "absolute",
    bottom: -140,
    left: -120,
    width: 380,
    height: 380,
    borderRadius: 190,
    backgroundColor: "#BAE6FD",
    opacity: 0.55,
  },
  webLeftContent: { zIndex: 1 },
  webLogo: {
    width: 88,
    height: 88,
    borderRadius: 22,
    backgroundColor: "#ffffff",
    borderWidth: 1,
    borderColor: "#DBEAFE",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.lg,
    shadowColor: "#0F172A",
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
  },
  webBrand: {
    color: "#0F172A",
    fontSize: 40,
    fontWeight: "800",
    letterSpacing: -1,
    marginBottom: spacing.md,
  },
  webTagRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginBottom: spacing.lg,
  },
  webTagPill: {
    color: "#0369A1",
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 2,
  },
  webDot: {
    width: 4,
    height: 4,
    borderRadius: 2,
    backgroundColor: "#60A5FA",
  },
  webTagline: {
    color: "#334155",
    fontSize: 16,
    lineHeight: 26,
    marginBottom: spacing.xl,
    maxWidth: 460,
  },
  webFeatRow: { gap: 14, marginBottom: spacing.xl },
  webFeat: { flexDirection: "row", alignItems: "flex-start", gap: 12 },
  webFeatIcon: {
    width: 36,
    height: 36,
    borderRadius: 10,
    backgroundColor: "#ffffff",
    borderWidth: 1,
    borderColor: "#DBEAFE",
    alignItems: "center",
    justifyContent: "center",
  },
  webFeatTitle: { color: "#0F172A", fontSize: 14, fontWeight: "700" },
  webFeatBody: {
    color: "#64748B",
    fontSize: 12,
    lineHeight: 18,
    marginTop: 2,
  },
  webFoot: { marginTop: spacing.xl },
  webFootTxt: {
    color: "#64748B",
    fontSize: 11,
  },

  webRightPane: {
    flex: 1.2,
    backgroundColor: "#F8FAFC",
    minHeight: 720,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: spacing.xl,
  },
  webCard: {
    width: "100%",
    maxWidth: 440,
    backgroundColor: "#ffffff",
    borderRadius: 20,
    padding: spacing.xl * 1.2,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    shadowColor: "#0F172A",
    shadowOpacity: 0.06,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 12 },
  },
  webBadge: {
    flexDirection: "row",
    alignSelf: "flex-start",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    backgroundColor: "#DBEAFE",
    borderWidth: 0,
    marginBottom: spacing.md,
  },
  webBadgeTxt: {
    color: "#0369A1",
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  webCardTitle: {
    color: "#0F172A",
    fontSize: 26,
    fontWeight: "800",
    letterSpacing: -0.4,
  },
  webCardSub: {
    color: "#64748B",
    fontSize: 14,
    lineHeight: 22,
    marginTop: 4,
    marginBottom: spacing.lg,
  },
  webCtaPrimary: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    // Iter 66 — Softer sky-blue instead of the vivid royal-blue that was
    // straining the eyes. Sky-500 pairs nicely with the pale sky-blue
    // hero on the left without competing for attention.
    backgroundColor: "#0EA5E9",
    paddingHorizontal: spacing.md,
    paddingVertical: 14,
    borderRadius: radius.md,
    marginBottom: spacing.md,
    shadowColor: "#0EA5E9",
    shadowOpacity: 0.20,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 6 },
  },
  webCtaPrimaryTxt: { color: "#ffffff", fontSize: 15, fontWeight: "800" },
  webCtaPrimarySub: {
    color: "rgba(255,255,255,0.85)",
    fontSize: 11,
    marginTop: 2,
  },
  webCtaSecondary: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: "#F1F5F9",
    paddingHorizontal: spacing.md,
    paddingVertical: 14,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: "#CBD5E1",
    marginBottom: spacing.md,
  },
  webCtaSecondaryTxt: { color: "#0F172A", fontSize: 14, fontWeight: "700" },
  webCtaSecondarySub: {
    color: "#64748B",
    fontSize: 11,
    marginTop: 2,
  },
});
