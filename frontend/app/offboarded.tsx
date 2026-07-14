import React from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { formatDate } from "@/src/utils/date";

/**
 * Locked screen shown to employees whose company has marked an exit /
 * left date on or before today. Users see the notification, cannot access
 * any tab, and can only sign out (which clears their token).
 */
export default function OffboardedScreen() {
  const { user, loading, logout } = useAuth();
  const [signingOut, setSigningOut] = React.useState(false);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brandPrimary} size="large" />
      </View>
    );
  }

  // If somehow rendered while user is not offboarded, bounce them out.
  if (!user) return <Redirect href="/" />;
  if (!user.offboarded) return <Redirect href="/(tabs)" />;

  const companyLabel = user.company_name?.trim()
    ? user.company_name.trim()
    : "your company";

  const onSignOut = async () => {
    setSigningOut(true);
    try {
      await logout();
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <View style={styles.root} testID="offboarded-screen">
      <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
        <View style={styles.card}>
          <View style={styles.iconWrap}>
            <Ionicons name="lock-closed" size={38} color={colors.onError} />
          </View>

          <Text style={styles.title}>Access blocked</Text>

          <Text style={styles.message} testID="offboarded-message">
            You are no longer to use this app due to you have left company
            {" "}
            <Text style={styles.company}>({companyLabel})</Text>.
          </Text>

          {user.exit_date ? (
            <View style={styles.metaPill}>
              <Ionicons name="calendar-outline" size={14} color={colors.onSurfaceSecondary} />
              <Text style={styles.metaTxt}>Exit date: {formatDate(user.exit_date)}</Text>
            </View>
          ) : null}

          <Text style={styles.help}>
            If this is a mistake, please contact your HR / company administrator
            to update your exit date.
          </Text>
        </View>

        <View style={styles.bottom}>
          <Pressable
            testID="offboarded-signout"
            style={({ pressed }) => [styles.cta, pressed && { opacity: 0.92 }]}
            onPress={onSignOut}
            disabled={signingOut}
          >
            {signingOut ? (
              <ActivityIndicator color={colors.onCta} />
            ) : (
              <>
                <Ionicons name="log-out-outline" size={18} color={colors.onCta} />
                <Text style={styles.ctaTxt}>Sign out</Text>
              </>
            )}
          </Pressable>
          <Text style={styles.legal}>
            S.K. Sharma & Co. · Powered by biometric attendance & compliance
          </Text>
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  safe: { flex: 1, paddingHorizontal: spacing.lg, justifyContent: "space-between" },
  center: {
    flex: 1, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface,
  },
  card: {
    marginTop: spacing.xl * 2,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.xl,
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.border,
    ...shadow.card,
  },
  iconWrap: {
    width: 72, height: 72, borderRadius: 36,
    backgroundColor: colors.error,
    alignItems: "center", justifyContent: "center",
    marginBottom: spacing.md,
  },
  title: {
    color: colors.onSurface,
    fontSize: type.xl,
    fontWeight: "700",
    marginBottom: spacing.sm,
  },
  message: {
    color: colors.onSurface,
    fontSize: type.base,
    lineHeight: 22,
    textAlign: "center",
    marginBottom: spacing.md,
  },
  company: { color: colors.brandPrimary, fontWeight: "700" },
  metaPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceTertiary,
    marginBottom: spacing.md,
  },
  metaTxt: { color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "600" },
  help: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    lineHeight: 18,
    textAlign: "center",
  },
  bottom: { paddingBottom: spacing.md },
  cta: {
    backgroundColor: colors.cta,
    borderRadius: radius.pill,
    paddingVertical: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    ...shadow.cta,
  },
  ctaTxt: { color: colors.onCta, fontSize: type.lg, fontWeight: "700" },
  legal: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    textAlign: "center",
    marginTop: spacing.md,
  },
});
