/**
 * PolicyTabs — Iter 68.
 *
 * Small tab strip shown at the top of both `/attendance-policy` and
 * `/compliance-policy` so the two pages present themselves as ONE merged
 * "Firm Policy" section without requiring a full rewrite of either screen.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { colors, radius } from "@/src/theme";

type Props = {
  active: "attendance" | "compliance";
  companyId?: string | null;
};

const TABS: {
  key: "attendance" | "compliance";
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  route: string;
}[] = [
  { key: "attendance", label: "Attendance Rules", icon: "calendar-outline", route: "/attendance-policy" },
  { key: "compliance", label: "Statutory & Salary", icon: "shield-checkmark-outline", route: "/compliance-policy" },
];

export default function PolicyTabs({ active, companyId }: Props) {
  const router = useRouter();
  const go = (route: string) => {
    const qs = companyId ? `?company_id=${encodeURIComponent(companyId)}` : "";
    router.replace(`${route}${qs}` as any);
  };
  return (
    <View style={styles.wrap}>
      <View style={styles.head}>
        <Ionicons name="settings-outline" size={14} color={colors.brandPrimary} />
        <Text style={styles.headTxt}>FIRM POLICY</Text>
      </View>
      <View style={styles.row}>
        {TABS.map((t) => {
          const on = t.key === active;
          return (
            <Pressable
              key={t.key}
              onPress={() => (!on ? go(t.route) : undefined)}
              style={[styles.tab, on && styles.tabActive]}
              testID={`policy-tabs-${t.key}`}
            >
              <Ionicons
                name={t.icon}
                size={14}
                color={on ? "#ffffff" : colors.onSurfaceSecondary}
              />
              <Text style={[styles.tabTxt, on && styles.tabTxtActive]}>{t.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: 12,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  head: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 8,
  },
  headTxt: {
    color: colors.onSurfaceSecondary,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.9,
  },
  row: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  tab: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  tabActive: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  tabTxt: {
    color: colors.onSurfaceSecondary,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.3,
  },
  tabTxtActive: { color: "#ffffff" },
});
