import React, { useCallback, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";

/**
 * Employees who have just self-onboarded land here until their company
 * admin approves the request. Auto-polls /auth/me every 20 seconds so
 * the screen unlocks automatically once approved.
 */
export default function PendingApprovalScreen() {
  const { user, loading, logout, refresh } = useAuth();
  const [refreshing, setRefreshing] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await refresh();
    } finally {
      setRefreshing(false);
    }
  }, [refresh]);

  // Poll every 20s so the screen unlocks automatically once approved.
  useEffect(() => {
    const t = setInterval(() => {
      refresh().catch(() => {});
    }, 20000);
    return () => clearInterval(t);
  }, [refresh]);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brandPrimary} size="large" />
      </View>
    );
  }

  if (!user) return <Redirect href="/" />;
  // If no longer pending, bounce out to the correct route.
  if (!user.approval_pending) {
    if (user.approval_rejected) return <Redirect href="/register-choice" />;
    return <Redirect href="/(tabs)" />;
  }

  const companyLabel = user.company_name?.trim() || "your company";

  const onSignOut = async () => {
    setSigningOut(true);
    try {
      await logout();
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <View style={styles.root} testID="pending-approval-screen">
      <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />
          }
        >
          <View style={styles.card}>
            <View style={styles.iconWrap}>
              <Ionicons name="hourglass-outline" size={38} color={colors.onCta} />
            </View>

            <Text style={styles.title}>Waiting for approval</Text>

            <Text style={styles.message} testID="pending-approval-message">
              Thanks {user.name?.split(" ")[0] || "there"}! Your details have
              been submitted to
              {" "}
              <Text style={styles.company}>{companyLabel}</Text>.
              A company admin will review and approve your account shortly.
            </Text>

            <View style={styles.stepsBox}>
              <Step icon="checkmark-circle" text="Details submitted" done />
              <Step icon="mail-outline" text="Admin review in progress" active />
              <Step icon="lock-open-outline" text="Access unlocked" />
            </View>

            <Text style={styles.help}>
              Pull down to refresh, or leave this screen open — it will unlock
              automatically once approved.
            </Text>
          </View>
        </ScrollView>

        <View style={styles.bottom}>
          <Pressable
            style={({ pressed }) => [styles.refreshBtn, pressed && { opacity: 0.9 }]}
            onPress={onRefresh}
            disabled={refreshing}
            testID="pending-approval-refresh"
          >
            {refreshing ? (
              <ActivityIndicator color={colors.brandPrimary} />
            ) : (
              <>
                <Ionicons name="refresh" size={18} color={colors.brandPrimary} />
                <Text style={styles.refreshTxt}>Check again</Text>
              </>
            )}
          </Pressable>

          <Pressable
            testID="pending-approval-signout"
            style={({ pressed }) => [styles.cta, pressed && { opacity: 0.9 }]}
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
        </View>
      </SafeAreaView>
    </View>
  );
}

function Step({
  icon,
  text,
  done,
  active,
}: {
  icon: any;
  text: string;
  done?: boolean;
  active?: boolean;
}) {
  const color = done ? colors.brandPrimary : active ? colors.cta : colors.onSurfaceTertiary;
  return (
    <View style={styles.stepRow}>
      <Ionicons name={icon} size={18} color={color} />
      <Text style={[styles.stepTxt, { color: done ? colors.onSurface : color }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  safe: { flex: 1, paddingHorizontal: spacing.lg, justifyContent: "space-between" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  scroll: { flexGrow: 1, justifyContent: "center", paddingVertical: spacing.xl },
  card: {
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
    backgroundColor: colors.cta,
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
  stepsBox: {
    alignSelf: "stretch",
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: 10,
    marginBottom: spacing.md,
  },
  stepRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  stepTxt: { fontSize: type.sm, fontWeight: "600" },
  help: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    lineHeight: 18,
    textAlign: "center",
  },
  bottom: { paddingBottom: spacing.md, gap: spacing.sm },
  refreshBtn: {
    borderRadius: radius.pill,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.surface,
  },
  refreshTxt: { color: colors.brandPrimary, fontSize: type.base, fontWeight: "700" },
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
});
