/**
 * Iter 85 — Appearance / Theme Switcher screen.
 *
 * Shows all 7 palettes as preview cards. Tapping a card immediately
 * applies the palette (mutates `colors` + `shadow`), persists the choice
 * to AsyncStorage, and re-renders the whole app via the version-keyed
 * root layout so every screen adopts the new theme in a single frame.
 */
import React from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { useTheme } from "@/src/context/ThemeContext";
import { colors, radius, spacing, type } from "@/src/theme";

export default function AppearanceScreen() {
  const router = useRouter();
  const { user } = useAuth();
  // Iter 85 — Theme switching is a SUPER-ADMIN-only privilege. Sub super
  // admins, company admins, and employees all see the "Admins only" gate.
  const isSuper = user?.role === "super_admin";
  const { themeId, setThemeId, presets } = useTheme();

  if (!isSuper) {
    return (
      <View style={styles.root}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Super Admin only</Text>
          <Text style={[styles.forbT, { fontSize: 12, marginTop: 4 }]}>
            Theme switching is restricted to Super Admins.
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>Appearance</Text>
            <Text style={styles.hsub}>
              Pick a theme — applies instantly across the portal
            </Text>
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Portal Theme</Text>
          <Text style={styles.smallHint}>
            Your selection is saved on this device and applied to all screens
            in the Web Portal and mobile app.
            {Platform.OS === "web"
              ? "  On the Web Portal, the sidebar, dashboards and tables adopt the new palette."
              : ""}
          </Text>

          <View style={styles.grid}>
            {presets.map((p) => {
              const active = p.id === themeId;
              return (
                <Pressable
                  key={p.id}
                  onPress={() => setThemeId(p.id)}
                  style={[styles.presetCard, active && styles.presetCardActive]}
                  testID={`theme-${p.id}`}
                >
                  {/* Header stripe (uses the preset's primary color) */}
                  <View style={[styles.stripe, { backgroundColor: p.primary }]}>
                    <Text style={styles.stripeTxt}>{p.name}</Text>
                    {active ? (
                      <View style={styles.activeBadge}>
                        <Ionicons name="checkmark" size={12} color={p.primary} />
                      </View>
                    ) : null}
                  </View>

                  {/* Preview panel */}
                  <View style={styles.previewPanel}>
                    <View style={styles.swatchRow}>
                      <View style={[styles.swatch, { backgroundColor: p.primary }]}>
                        <Text style={styles.swatchTxt}>Primary</Text>
                      </View>
                      <View style={[styles.swatch, { backgroundColor: p.accent }]}>
                        <Text style={styles.swatchTxt}>Accent</Text>
                      </View>
                    </View>

                    <Text style={styles.presetDesc} numberOfLines={2}>
                      {p.description}
                    </Text>

                    {/* Sample button + chip so admins see how the palette
                        looks on real UI elements. */}
                    <View style={styles.miniPreviewRow}>
                      <View style={[styles.miniBtn, { backgroundColor: p.primary }]}>
                        <Text style={styles.miniBtnTxt}>Save</Text>
                      </View>
                      <View style={[styles.miniBtn, { backgroundColor: p.accent }]}>
                        <Text style={styles.miniBtnTxt}>Action</Text>
                      </View>
                      <View style={[styles.miniChip, {
                        borderColor: p.primary,
                        backgroundColor: p.colors.brandTertiary,
                      }]}>
                        <Text style={[styles.miniChipTxt, { color: p.colors.onBrandTertiary }]}>
                          Chip
                        </Text>
                      </View>
                    </View>
                  </View>
                </Pressable>
              );
            })}
          </View>
        </View>

        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    paddingHorizontal: spacing.md,
    height: 52,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
  },
  h1: { ...type.h5, color: colors.onSurface, fontWeight: "700" },
  hsub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },
  scroll: { padding: spacing.md, paddingBottom: 40 },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: { marginTop: 8, color: colors.onSurfaceTertiary, ...type.body },

  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cardTitle: {
    ...type.h6,
    color: colors.onSurface,
    fontWeight: "700",
    marginBottom: 4,
  },
  smallHint: { ...type.caption, color: colors.onSurfaceSecondary, marginBottom: 14 },

  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
  },
  presetCard: {
    width: Platform.OS === "web" ? 300 : "100%" as any,
    minWidth: 280,
    borderRadius: radius.lg,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    overflow: "hidden",
  },
  presetCardActive: {
    borderColor: colors.brandPrimary,
    borderWidth: 3,
  },
  stripe: {
    paddingVertical: 10,
    paddingHorizontal: 14,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  stripeTxt: {
    color: "#FFF",
    fontWeight: "800",
    fontSize: 14,
    flex: 1,
  },
  activeBadge: {
    width: 20, height: 20, borderRadius: 10,
    backgroundColor: "#FFF",
    alignItems: "center", justifyContent: "center",
  },

  previewPanel: {
    padding: 12,
    gap: 10,
  },
  swatchRow: { flexDirection: "row", gap: 8 },
  swatch: {
    flex: 1,
    height: 36,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  swatchTxt: { color: "#FFF", fontSize: 11, fontWeight: "700" },

  presetDesc: {
    fontSize: 12,
    color: colors.onSurfaceSecondary,
    lineHeight: 16,
    minHeight: 32,
  },

  miniPreviewRow: {
    flexDirection: "row",
    gap: 6,
    alignItems: "center",
  },
  miniBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
  },
  miniBtnTxt: { color: "#FFF", fontWeight: "700", fontSize: 11 },
  miniChip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 12,
    borderWidth: 1,
  },
  miniChipTxt: { fontWeight: "700", fontSize: 11 },
});
