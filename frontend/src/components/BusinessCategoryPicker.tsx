import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Modal,
  ScrollView,
  ActivityIndicator,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius, spacing, type } from "@/src/theme";

export type BusinessCategoryValue = {
  category: string | null;
  subcategory: string | null;
  label: string; // human-readable display, e.g. "Industry — Textile"
};

export type BusinessCategoryDef = {
  key: string;
  label: string;
  subcategories: string[];
};

type Props = {
  label?: string;
  value: BusinessCategoryValue;
  onChange: (v: BusinessCategoryValue) => void;
  placeholder?: string;
  required?: boolean;
  testID?: string;
  disabled?: boolean;
};

let CACHED: BusinessCategoryDef[] | null = null;

/** Fetches taxonomy once and caches it for the app session. */
export async function fetchBusinessCategories(): Promise<BusinessCategoryDef[]> {
  if (CACHED) return CACHED;
  const r = await api<{ categories: BusinessCategoryDef[] }>(
    "/business-categories",
    { auth: false },
  );
  CACHED = r.categories || [];
  return CACHED;
}

export function buildLabel(
  cat: BusinessCategoryDef | undefined,
  sub: string | null,
): string {
  if (!cat) return "";
  return sub ? `${cat.label} — ${sub}` : cat.label;
}

export default function BusinessCategoryPicker({
  label = "Business type *",
  value,
  onChange,
  placeholder = "Select business type",
  testID,
  disabled,
}: Props) {
  const [open, setOpen] = useState(false);
  const [categories, setCategories] = useState<BusinessCategoryDef[]>(
    CACHED || [],
  );
  const [loading, setLoading] = useState(!CACHED);
  const [error, setError] = useState<string | null>(null);
  const [expandedKey, setExpandedKey] = useState<string | null>(
    value.category,
  );

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const cats = await fetchBusinessCategories();
      setCategories(cats);
    } catch (e: any) {
      setError(e?.message || "Failed to load categories");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!CACHED) load();
  }, [load]);

  const displayValue = value.label || placeholder;

  const pickCategory = (cat: BusinessCategoryDef) => {
    if (cat.subcategories.length === 0) {
      onChange({
        category: cat.key,
        subcategory: null,
        label: buildLabel(cat, null),
      });
      setOpen(false);
      return;
    }
    setExpandedKey((prev) => (prev === cat.key ? null : cat.key));
  };

  const pickSubcategory = (cat: BusinessCategoryDef, sub: string) => {
    onChange({
      category: cat.key,
      subcategory: sub,
      label: buildLabel(cat, sub),
    });
    setOpen(false);
  };

  return (
    <View testID={testID}>
      {!!label && <Text style={styles.label}>{label}</Text>}
      <Pressable
        testID={testID ? `${testID}-trigger` : "biz-cat-trigger"}
        onPress={() => !disabled && setOpen(true)}
        style={[styles.field, disabled && { opacity: 0.55 }]}
      >
        <Text
          style={[
            styles.fieldTxt,
            !value.label && { color: colors.onSurfaceTertiary },
          ]}
          numberOfLines={1}
        >
          {displayValue}
        </Text>
        <Ionicons
          name="chevron-down"
          size={18}
          color={colors.onSurfaceSecondary}
        />
      </Pressable>

      <Modal
        visible={open}
        transparent
        animationType="slide"
        onRequestClose={() => setOpen(false)}
      >
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)} />
        <View style={styles.sheet}>
          <View style={styles.grip} />
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>Select business type</Text>
            <Pressable
              onPress={() => setOpen(false)}
              hitSlop={10}
              testID="biz-cat-close"
            >
              <Ionicons name="close" size={22} color={colors.onSurface} />
            </Pressable>
          </View>

          {loading ? (
            <View style={styles.center}>
              <ActivityIndicator color={colors.brandPrimary} />
            </View>
          ) : error ? (
            <View style={styles.center}>
              <Ionicons
                name="alert-circle"
                size={22}
                color={colors.error}
              />
              <Text style={styles.errTxt}>{error}</Text>
              <Pressable onPress={load} style={styles.retryBtn}>
                <Text style={styles.retryTxt}>Retry</Text>
              </Pressable>
            </View>
          ) : (
            <ScrollView
              style={{ maxHeight: Platform.OS === "web" ? 480 : "100%" }}
              contentContainerStyle={styles.list}
              showsVerticalScrollIndicator={false}
            >
              {categories.map((cat) => {
                const isSelected = value.category === cat.key;
                const isExpanded = expandedKey === cat.key;
                const hasSubs = cat.subcategories.length > 0;
                return (
                  <View key={cat.key}>
                    <Pressable
                      style={[styles.row, isSelected && styles.rowActive]}
                      onPress={() => pickCategory(cat)}
                      testID={`biz-cat-${cat.key}`}
                    >
                      <View style={styles.rowLeft}>
                        <View
                          style={[
                            styles.radio,
                            isSelected && styles.radioOn,
                          ]}
                        >
                          {isSelected && !hasSubs && (
                            <Ionicons
                              name="checkmark"
                              size={12}
                              color="#fff"
                            />
                          )}
                        </View>
                        <Text
                          style={[
                            styles.rowTxt,
                            isSelected && styles.rowTxtActive,
                          ]}
                        >
                          {cat.label}
                        </Text>
                      </View>
                      {hasSubs && (
                        <Ionicons
                          name={
                            isExpanded ? "chevron-up" : "chevron-down"
                          }
                          size={16}
                          color={colors.onSurfaceTertiary}
                        />
                      )}
                    </Pressable>
                    {hasSubs && isExpanded && (
                      <View style={styles.subList}>
                        {cat.subcategories.map((sub) => {
                          const subActive =
                            isSelected && value.subcategory === sub;
                          return (
                            <Pressable
                              key={sub}
                              style={[
                                styles.subRow,
                                subActive && styles.subRowActive,
                              ]}
                              onPress={() => pickSubcategory(cat, sub)}
                              testID={`biz-cat-${cat.key}-${sub
                                .toLowerCase()
                                .replace(/[^a-z0-9]+/g, "-")}`}
                            >
                              <Ionicons
                                name={
                                  subActive
                                    ? "checkmark-circle"
                                    : "ellipse-outline"
                                }
                                size={16}
                                color={
                                  subActive
                                    ? colors.brandPrimary
                                    : colors.onSurfaceTertiary
                                }
                              />
                              <Text
                                style={[
                                  styles.subTxt,
                                  subActive && styles.subTxtActive,
                                ]}
                              >
                                {sub}
                              </Text>
                            </Pressable>
                          );
                        })}
                      </View>
                    )}
                  </View>
                );
              })}
              <View style={{ height: spacing.xl }} />
            </ScrollView>
          )}
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  label: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "600",
    marginTop: spacing.md,
    marginBottom: 6,
  },
  field: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 14,
    gap: 12,
  },
  fieldTxt: {
    color: colors.onSurface,
    fontSize: type.base,
    flex: 1,
  },
  backdrop: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0,0,0,0.4)",
  },
  sheet: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    maxHeight: "82%",
    paddingBottom: spacing.md,
  },
  grip: {
    alignSelf: "center",
    width: 44,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    marginTop: 8,
    marginBottom: 4,
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  sheetTitle: {
    color: colors.onSurface,
    fontSize: type.lg,
    fontWeight: "700",
  },
  list: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 14,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    marginTop: 4,
  },
  rowActive: { backgroundColor: colors.brandTertiary },
  rowLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    flex: 1,
  },
  radio: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  radioOn: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandPrimary,
  },
  rowTxt: {
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "500",
  },
  rowTxtActive: { fontWeight: "700" },
  subList: {
    paddingLeft: 40,
    paddingRight: spacing.md,
    paddingBottom: 4,
  },
  subRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
  },
  subRowActive: { backgroundColor: colors.brandTertiary },
  subTxt: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
  },
  subTxtActive: {
    color: colors.brandPrimary,
    fontWeight: "700",
  },
  center: {
    padding: spacing.xl,
    alignItems: "center",
    gap: 10,
  },
  errTxt: { color: colors.onSurfaceSecondary, fontSize: type.sm },
  retryBtn: {
    marginTop: 6,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: radius.pill,
    backgroundColor: colors.brandPrimary,
  },
  retryTxt: { color: "#fff", fontWeight: "700" },
});
