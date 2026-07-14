/**
 * DateField - Iter 86.
 *
 * Cross-platform date picker used by every admin screen that needs a
 * single-day filter (Punch Approvals, Users Log Report, Attendance
 * Grid, etc.).
 *
 * Behaviour:
 *  - Value is always stored in ISO YYYY-MM-DD (so backend calls stay
 *    unchanged).
 *  - On web we render a native <input type="date"> so the browser's
 *    built-in calendar popover opens on click. The browser shows the
 *    date in the user's locale format (DD-MM-YYYY in India / most of
 *    the world), which matches the app-wide DD-MM-YYYY standard.
 *  - On native we render a normal TextInput with a "DD-MM-YYYY"
 *    placeholder; a full native date-picker modal is left for later
 *    iterations since the admin surface is desktop-first.
 *  - Optional prefix icon + label rendered inline (matches the visual
 *    style already used across admin screens).
 */
import React from "react";
import { Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, radius } from "@/src/theme";

type Props = {
  /** Current ISO YYYY-MM-DD value (empty string means "no date picked"). */
  value: string;
  onChangeISO: (iso: string) => void;
  label?: string;
  placeholder?: string;
  testID?: string;
  /** Optional min / max in ISO YYYY-MM-DD (web only). */
  min?: string;
  max?: string;
  /** Compact style — for header bars. */
  compact?: boolean;
};

export default function DateField({
  value,
  onChangeISO,
  label,
  placeholder = "DD-MM-YYYY",
  testID,
  min,
  max,
  compact = false,
}: Props) {
  // Web: keep a ref so clicking ANYWHERE on the field (icon, label or
  // input text) opens the browser's calendar popover — previously only
  // the tiny native indicator was clickable.
  const webRef = React.useRef<any>(null);
  const openPicker = () => {
    try {
      webRef.current?.showPicker?.();
      webRef.current?.focus?.();
    } catch {
      webRef.current?.focus?.();
    }
  };
  if (Platform.OS === "web") {
    return (
      <Pressable
        onPress={openPicker}
        style={[styles.wrap, compact && { paddingVertical: 4 }]}
      >
        <Ionicons name="calendar-outline" size={16} color={colors.brandPrimary} />
        {label ? <Text style={styles.label}>{label}</Text> : null}
        {/* Native browser calendar. Locale = user's system locale, which
            in India renders as DD-MM-YYYY. */}
        <input
          ref={webRef}
          type="date"
          value={value || ""}
          min={min || undefined}
          max={max || undefined}
          onClick={openPicker}
          onChange={(e) => onChangeISO((e.target as HTMLInputElement).value || "")}
          data-testid={testID}
          style={styles.webInput as any}
        />
      </Pressable>
    );
  }
  return (
    <View style={[styles.wrap, compact && { paddingVertical: 4 }]}>
      <Ionicons name="calendar-outline" size={16} color={colors.brandPrimary} />
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <TextInput
        value={value}
        onChangeText={onChangeISO}
        placeholder={placeholder}
        placeholderTextColor={colors.onSurfaceTertiary}
        style={styles.nativeInput}
        maxLength={10}
        testID={testID}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.surface,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.divider,
    // Iter 93 — never collapse below a usable width inside crowded
    // header bars (Punch Approvals date bar on narrow screens).
    minWidth: 170,
  },
  label: {
    fontSize: 12,
    color: colors.onSurfaceSecondary,
    fontWeight: "700",
    letterSpacing: 0.4,
  },
  webInput: {
    fontSize: 13,
    color: colors.onSurface,
    border: "none",
    outline: "none",
    background: "transparent",
    fontFamily: "inherit",
    padding: 0,
    minWidth: 140,
    cursor: "pointer",
  },
  nativeInput: {
    fontSize: 13,
    color: colors.onSurface,
    minWidth: 130,
    paddingVertical: 2,
  },
});
