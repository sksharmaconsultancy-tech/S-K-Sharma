/**
 * SelectedCompanyBadge — Iter 62.
 *
 * Small "Currently viewing: {firm name}" pill that operators can render on
 * any page (typically dashboards) so they always know which firm is
 * currently in scope from the GlobalCompanyPicker. When "All firms" is
 * selected the badge stays hidden.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing } from "@/src/theme";

type Props = {
  variant?: "default" | "banner";
  hideWhenAll?: boolean;
};

export default function SelectedCompanyBadge({
  variant = "default",
  hideWhenAll = true,
}: Props) {
  const { selectedCompany, setSelectedCompanyId } = useSelectedCompany();
  if (Platform.OS !== "web") return null;
  if (!selectedCompany && hideWhenAll) return null;

  const banner = variant === "banner";

  return (
    <View style={[styles.wrap, banner && styles.banner]} testID="selected-company-badge">
      <Ionicons
        name="eye-outline"
        size={14}
        color={banner ? "#fff" : colors.brandPrimary}
      />
      <Text style={[styles.label, banner && styles.labelOnDark]}>
        Currently viewing:
      </Text>
      <Text style={[styles.firm, banner && styles.firmOnDark]} numberOfLines={1}>
        {selectedCompany
          ? `${selectedCompany.name}${selectedCompany.company_code ? ` · ${selectedCompany.company_code}` : ""}`
          : "All firms"}
      </Text>
      {selectedCompany ? (
        <Pressable
          onPress={() => setSelectedCompanyId(null)}
          hitSlop={8}
          style={[styles.clearBtn, banner && styles.clearBtnOnDark]}
          testID="selected-company-badge-clear"
        >
          <Ionicons
            name="close"
            size={12}
            color={banner ? "#fff" : colors.brandPrimary}
          />
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: colors.brandTertiary,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    alignSelf: "flex-start",
  },
  banner: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderRadius: radius.md,
    alignSelf: "stretch",
  },
  label: { color: colors.brandPrimary, fontSize: 11, fontWeight: "700" },
  labelOnDark: { color: "#FFE4B5" },
  firm: {
    color: colors.onSurface,
    fontSize: 12,
    fontWeight: "800",
    flexShrink: 1,
    maxWidth: 240,
  },
  firmOnDark: { color: "#fff", maxWidth: 320 },
  clearBtn: {
    padding: 2,
    borderRadius: 999,
    backgroundColor: "rgba(0,0,0,0.04)",
  },
  clearBtnOnDark: { backgroundColor: "rgba(255,255,255,0.15)" },
});
