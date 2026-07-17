import { Redirect, Tabs } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { ActivityIndicator, View, StyleSheet, Pressable } from "react-native";
import { useAuth } from "@/src/context/AuthContext";
import FingerprintUnlockGate from "@/src/components/FingerprintUnlockGate";
import { colors, shadow, spacing } from "@/src/theme";

export default function TabsLayout() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={colors.brandPrimary} />
      </View>
    );
  }
  if (!user) return <Redirect href="/" />;
  if (user.pin_must_change) return <Redirect href="/pin-change" />;
  if (user.role === "employee" && user.offboarded) return <Redirect href="/offboarded" />;
  if (user.role === "employee" && user.approval_pending) return <Redirect href="/pending-approval" />;
  if (user.role === "employee" && !user.onboarded) return <Redirect href="/register-choice" />;



  // Iter 165 — employees whose admin enabled Fingerprint verification must
  // unlock the app with the device fingerprint (silent skip when the
  // device/browser has no biometric support).
  const needsFpGate =
    user.role === "employee" && (user as any).effective_fingerprint_required === true;

  const tabs = (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.onSurfaceSecondary,
        tabBarStyle: {
          backgroundColor: colors.surfaceSecondary,
          borderTopColor: colors.border,
          height: 78,
          paddingTop: 10,
          paddingBottom: 22,
          paddingHorizontal: 4,
        },
        tabBarLabelStyle: { fontSize: 11, marginTop: 2, fontWeight: "500" },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Home",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="home-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="attendance"
        options={{
          title: "",
          tabBarLabel: () => null,
          // Iter 177 — the Punch tab shows ONLY for employees. Employers
          // reach the same screen via Dashboard → "My Attendance".
          // NOTE: Expo Router forbids passing both `href` and `tabBarButton`
          // for the same screen, so we use only `href: null` to hide it and
          // let the default tab button behaviour apply otherwise.
          href: user.role === "employee" ? undefined : null,
          tabBarButton: user.role !== "employee"
            ? undefined
            : (props) => (
                <Pressable
                  testID="tab-punch"
                  onPress={props.onPress as any}
                  style={styles.centerTabWrap}
                >
                  <View style={styles.centerTab}>
                    <Ionicons name="finger-print" color="#fff" size={26} />
                  </View>
                </Pressable>
              ),
        }}
      />
      <Tabs.Screen
        name="documents"
        options={{
          title: "Documents",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="document-text-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: "Profile",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="person-circle-outline" color={color} size={size} />
          ),
        }}
      />
    </Tabs>
  );

  if (needsFpGate) {
    return (
      <FingerprintUnlockGate userId={user.user_id} userName={user.name || ""}>
        {tabs}
      </FingerprintUnlockGate>
    );
  }
  return tabs;
}

const styles = StyleSheet.create({
  center: {
    flex: 1, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface, padding: spacing.xl,
  },
  centerTabWrap: {
    flex: 1,
    alignItems: "center",
    justifyContent: "flex-start",
    height: 78,
  },
  centerTab: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: colors.cta,
    alignItems: "center",
    justifyContent: "center",
    marginTop: -26,
    borderWidth: 4,
    borderColor: colors.surfaceSecondary,
    ...shadow.tabPunch,
  },
});
