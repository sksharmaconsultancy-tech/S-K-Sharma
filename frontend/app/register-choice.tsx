import React from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { Redirect, useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";

const LOGO = require("../assets/images/logo-mark.png");

export default function RegisterChoice() {
  const { user, logout } = useAuth();
  const router = useRouter();

  if (!user) return <Redirect href="/" />;
  if (user.onboarded && user.company_id) return <Redirect href="/(tabs)" />;

  return (
    <View style={styles.root} testID="register-choice-screen">
      <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
        <View style={styles.header}>
          <Image source={LOGO} style={styles.brandLogo} contentFit="contain" />
          <View style={{ flex: 1 }}>
            <Text style={styles.brand}>S.K. Sharma & Co.</Text>
            <Text style={styles.brandTag}>Welcome, {user.name?.split(" ")[0] || "there"}</Text>
          </View>
          <Pressable onPress={logout} hitSlop={8}>
            <Ionicons name="log-out-outline" size={22} color={colors.onSurfaceTertiary} />
          </Pressable>
        </View>

        <ScrollView contentContainerStyle={styles.scroll}>
          {user.approval_status === "rejected" ? (
            <View style={styles.rejectBanner} testID="rejected-banner">
              <Ionicons name="alert-circle" size={18} color="#8A1F1F" />
              <Text style={styles.rejectTxt}>
                Your previous request to join was declined
                {user.approval_note ? ` — “${user.approval_note}”` : ""}.
                You can try joining another company or request a new one.
              </Text>
            </View>
          ) : null}

          <Text style={styles.title}>What brings you here?</Text>
          <Text style={styles.subtitle}>
            Pick the option that matches you. You can only do this once, so
            choose carefully.
          </Text>

          <Pressable
            testID="choice-employee"
            style={styles.card}
            onPress={() => router.push("/onboarding")}
          >
            <View style={styles.cardIcon}>
              <Ionicons name="person-outline" size={26} color={colors.onBrandTertiary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardTitle}>I&apos;m an employee</Text>
              <Text style={styles.cardBody}>
                My company is already on S.K. Sharma & Co.. I have a 6-character
                company code from HR.
              </Text>
              <View style={styles.cardCta}>
                <Text style={styles.cardCtaTxt}>Enter company code</Text>
                <Ionicons name="arrow-forward" size={16} color={colors.brandPrimary} />
              </View>
            </View>
          </Pressable>

          <Pressable
            testID="choice-company"
            style={[styles.card, styles.cardAccent]}
            onPress={() => router.push("/register-company")}
          >
            <View style={[styles.cardIcon, styles.cardIconAccent]}>
              <Ionicons name="business-outline" size={26} color="#fff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardTitleAccent}>I want to register my company</Text>
              <Text style={styles.cardBodyAccent}>
                My company isn&apos;t on S.K. Sharma & Co. yet. I&apos;d like to
                get started with compliance, payroll and biometric attendance.
              </Text>
              <View style={styles.cardCtaAccent}>
                <Text style={styles.cardCtaAccentTxt}>Send my details</Text>
                <Ionicons name="arrow-forward" size={16} color="#fff" />
              </View>
            </View>
          </Pressable>

          <Text style={styles.hint}>
            Not sure? Contact your HR to check whether your company is enrolled.
          </Text>
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.md,
  },
  brandLogo: { width: 36, height: 36 },
  brand: { color: colors.onSurface, fontSize: type.base, fontWeight: "600" },
  brandTag: { color: colors.onSurfaceTertiary, fontSize: type.sm },
  scroll: { padding: spacing.lg },
  rejectBanner: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    backgroundColor: "#FDECEC",
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: "#F5C0C0",
  },
  rejectTxt: { flex: 1, color: "#8A1F1F", fontSize: type.sm, lineHeight: 18 },
  title: { color: colors.onSurface, fontSize: 28, fontWeight: "800", letterSpacing: -0.5 },
  subtitle: {
    color: colors.onSurfaceSecondary, fontSize: type.base,
    marginTop: spacing.sm, lineHeight: 22,
  },
  card: {
    marginTop: spacing.lg,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1, borderColor: colors.border,
    flexDirection: "row", gap: 14,
    ...shadow.card,
  },
  cardAccent: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  cardIcon: {
    width: 52, height: 52, borderRadius: 26,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  cardIconAccent: { backgroundColor: "rgba(255,255,255,0.16)" },
  cardTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  cardTitleAccent: { color: "#fff", fontSize: type.lg, fontWeight: "700" },
  cardBody: { color: colors.onSurfaceSecondary, fontSize: type.base, marginTop: 4, lineHeight: 20 },
  cardBodyAccent: { color: "rgba(255,255,255,0.86)", fontSize: type.base, marginTop: 4, lineHeight: 20 },
  cardCta: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: spacing.md },
  cardCtaTxt: { color: colors.brandPrimary, fontSize: type.base, fontWeight: "700" },
  cardCtaAccent: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: spacing.md },
  cardCtaAccentTxt: { color: "#fff", fontSize: type.base, fontWeight: "700" },
  hint: {
    color: colors.onSurfaceTertiary, fontSize: type.sm, textAlign: "center",
    marginTop: spacing.xl, lineHeight: 18,
  },
});
