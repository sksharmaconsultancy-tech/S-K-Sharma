import React, { useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Modal,
  TextInput,
  FlatList,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

export type PickerCompany = {
  company_id: string;
  name: string;
  address?: string | null;
};

type Props = {
  /**
   * Currently selected company_id. Use "all" (or null) for "All companies".
   */
  value: string | "all";
  onChange: (value: string | "all") => void;
  /**
   * Optional pre-loaded list. If not provided the picker loads /api/companies
   * on first open. Useful when the parent already has the list.
   */
  companies?: PickerCompany[];
  label?: string;
  /**
   * When true the "All companies" entry is included at the top. Defaults to true.
   */
  allowAll?: boolean;
  compact?: boolean;
  disabled?: boolean;
  testID?: string;
};

/**
 * Cross-platform company selector with:
 *  - A trigger row showing the current selection + chevron
 *  - A modal sheet with a live "search by name" filter
 *  - A single-tap list of companies
 *
 * The trigger is designed to sit inline in a form/toolbar. The modal is
 * key-lifted so the search input stays visible with the keyboard open.
 */
export default function CompanyPicker({
  value,
  onChange,
  companies: preloaded,
  label = "Company",
  allowAll = true,
  compact = false,
  disabled = false,
  testID = "company-picker",
}: Props) {
  // Iter 77 - Respect the session-lock. When the operator has already
  // picked a firm this session, this picker becomes read-only (no
  // dropdown, small "Locked" hint) so switching requires an explicit
  // logout + re-login.
  const { isLocked, selectedCompany: lockedCompany } = useSelectedCompany();
  const effectiveDisabled = disabled || isLocked;

  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [companies, setCompanies] = useState<PickerCompany[]>(preloaded || []);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (preloaded && preloaded.length > 0) setCompanies(preloaded);
  }, [preloaded]);

  useEffect(() => {
    if (!open) return;
    if (companies.length > 0) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const r = await api<{ companies: PickerCompany[] }>("/companies");
        if (!cancelled) setCompanies(r.companies || []);
      } catch (e: any) {
        if (!cancelled) setErr(e?.message || "Failed to load companies");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, companies.length]);

  const selectedName = useMemo(() => {
    if (value === "all" || !value) return "All companies";
    const c = companies.find((x) => x.company_id === value);
    return c?.name || "Selected company";
  }, [value, companies]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return companies;
    return companies.filter(
      (c) =>
        c.name.toLowerCase().includes(needle) ||
        (c.address || "").toLowerCase().includes(needle),
    );
  }, [q, companies]);

  return (
    <View testID={testID}>
      {!compact && !!label && <Text style={styles.label}>{label}</Text>}
      <Pressable
        onPress={() => !disabled && setOpen(true)}
        disabled={disabled}
        style={[
          compact ? styles.triggerCompact : styles.trigger,
          disabled && { opacity: 0.5 },
        ]}
        testID={`${testID}-trigger`}
      >
        <Ionicons
          name={value === "all" ? "apps-outline" : "business-outline"}
          size={16}
          color={colors.brandPrimary}
        />
        <Text style={styles.triggerTxt} numberOfLines={1}>
          {selectedName}
        </Text>
        <Ionicons
          name="chevron-down"
          size={16}
          color={colors.onSurfaceTertiary}
        />
      </Pressable>

      <Modal
        visible={open}
        transparent
        animationType="slide"
        onRequestClose={() => setOpen(false)}
      >
        <Pressable
          style={styles.backdrop}
          onPress={() => setOpen(false)}
          testID={`${testID}-backdrop`}
        />
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.sheetWrap}
        >
          <View style={styles.sheet}>
            <View style={styles.handle} />
            <View style={styles.sheetHeader}>
              <Text style={styles.sheetTitle}>Select company</Text>
              <Pressable
                onPress={() => setOpen(false)}
                hitSlop={8}
                testID={`${testID}-close`}
              >
                <Ionicons
                  name="close"
                  size={22}
                  color={colors.onSurfaceSecondary}
                />
              </Pressable>
            </View>

            <View style={styles.searchBox}>
              <Ionicons
                name="search"
                size={16}
                color={colors.onSurfaceTertiary}
              />
              <TextInput
                testID={`${testID}-search`}
                value={q}
                onChangeText={setQ}
                placeholder="Search by name…"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.searchInput}
                autoCorrect={false}
                autoCapitalize="none"
              />
              {q.length > 0 && (
                <Pressable
                  onPress={() => setQ("")}
                  hitSlop={8}
                  testID={`${testID}-clear`}
                >
                  <Ionicons
                    name="close-circle"
                    size={16}
                    color={colors.onSurfaceTertiary}
                  />
                </Pressable>
              )}
            </View>

            {loading && companies.length === 0 ? (
              <ActivityIndicator
                style={{ marginTop: 24 }}
                color={colors.brandPrimary}
              />
            ) : err ? (
              <Text style={styles.err} testID={`${testID}-err`}>
                {err}
              </Text>
            ) : (
              <FlatList
                data={
                  allowAll
                    ? [{ company_id: "all", name: "All companies" }, ...filtered]
                    : filtered
                }
                keyExtractor={(item) => item.company_id}
                keyboardShouldPersistTaps="handled"
                contentContainerStyle={{ paddingBottom: 20 }}
                ListEmptyComponent={
                  <Text style={styles.empty}>No companies match &quot;{q}&quot;</Text>
                }
                renderItem={({ item }) => {
                  const selected =
                    (value === "all" && item.company_id === "all") ||
                    value === item.company_id;
                  return (
                    <Pressable
                      testID={`${testID}-option-${item.company_id}`}
                      style={[styles.row, selected && styles.rowSelected]}
                      onPress={() => {
                        onChange(item.company_id as string | "all");
                        setOpen(false);
                        setQ("");
                      }}
                    >
                      <View style={styles.rowIcon}>
                        <Ionicons
                          name={
                            item.company_id === "all"
                              ? "apps-outline"
                              : "business-outline"
                          }
                          size={16}
                          color={colors.brandPrimary}
                        />
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.rowName}>{item.name}</Text>
                        {(item as PickerCompany).address ? (
                          <Text style={styles.rowSub} numberOfLines={1}>
                            {(item as PickerCompany).address}
                          </Text>
                        ) : null}
                      </View>
                      {selected ? (
                        <Ionicons
                          name="checkmark-circle"
                          size={20}
                          color={colors.brandPrimary}
                        />
                      ) : null}
                    </Pressable>
                  );
                }}
              />
            )}
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  label: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "600",
    marginBottom: 6,
  },
  trigger: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    minHeight: 44,
  },
  triggerCompact: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  triggerTxt: {
    flex: 1,
    color: colors.onSurface,
    fontSize: type.sm,
    fontWeight: "600",
  },

  backdrop: {
    ...(Platform.OS === "web"
      ? ({ position: "fixed" as any } as any)
      : { position: "absolute" as const }),
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(15,23,42,0.35)",
  },
  sheetWrap: {
    flex: 1,
    justifyContent: "flex-end",
    // Iter 187 — on mobile web the Modal container can be positioned
    // relative to the (scrolled) document, pushing the sheet below the
    // visible viewport so taps never land. Pin it to the viewport.
    ...(Platform.OS === "web"
      ? ({ position: "fixed", top: 0, left: 0, right: 0, bottom: 0 } as any)
      : null),
  },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: spacing.lg,
    paddingTop: 10,
    paddingBottom: spacing.lg,
    maxHeight: "80%",
  },
  handle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    backgroundColor: colors.border,
    borderRadius: 2,
    marginBottom: 8,
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.md,
  },
  sheetTitle: {
    color: colors.onSurface,
    fontSize: type.lg,
    fontWeight: "800",
  },
  searchBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: Platform.OS === "ios" ? 12 : 8,
    marginBottom: spacing.md,
  },
  searchInput: {
    flex: 1,
    color: colors.onSurface,
    fontSize: type.base,
    padding: 0,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 8,
    borderRadius: radius.md,
  },
  rowSelected: { backgroundColor: colors.brandTertiary },
  rowIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  rowName: {
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "600",
  },
  rowSub: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    marginTop: 2,
  },
  err: {
    color: colors.error,
    fontSize: type.sm,
    marginTop: spacing.md,
    textAlign: "center",
  },
  empty: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    textAlign: "center",
    marginTop: spacing.lg,
  },
});
