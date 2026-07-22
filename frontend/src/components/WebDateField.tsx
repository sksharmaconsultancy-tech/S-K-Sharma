/**
 * WebDateField — Iter 243 (user request).
 *
 * A date input that DISPLAYS the value as DD-MM-YYYY and opens the native
 * calendar picker on click. The value is kept internally as ISO
 * (YYYY-MM-DD) so all backend APIs stay unchanged.
 *
 * On web (the admin portal) it overlays a transparent <input type="date">
 * so a real calendar pops up. On native it falls back to a typed field.
 */
import React from "react";
import { Platform, StyleSheet, Text, TextInput, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, radius } from "@/src/theme";

function isoToDmy(iso: string): string {
  if (!iso || iso.length < 10) return "";
  return `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}`;
}

export default function WebDateField({
  value,
  onChange,
  testID,
  placeholder = "DD-MM-YYYY",
}: {
  value: string; // ISO YYYY-MM-DD
  onChange: (iso: string) => void;
  testID?: string;
  placeholder?: string;
}) {
  const display = isoToDmy(value);

  if (Platform.OS === "web") {
    return (
      <View style={st.box}>
        <Text style={[st.display, !display && st.placeholder]}>
          {display || placeholder}
        </Text>
        <Ionicons name="calendar-outline" size={18} color={colors.onSurfaceSecondary} />
        {/* Transparent native date input overlay → opens the calendar. */}
        {/* @ts-ignore web-only element */}
        <input
          type="date"
          value={value || ""}
          onChange={(e: any) => onChange(e.target.value)}
          data-testid={testID}
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            opacity: 0,
            cursor: "pointer",
            border: "none",
            margin: 0,
            padding: 0,
          } as any}
        />
      </View>
    );
  }

  // Native fallback — typed ISO (kept simple; admin uses the web portal).
  return (
    <TextInput
      value={value}
      onChangeText={onChange}
      style={st.native}
      placeholder="YYYY-MM-DD"
      placeholderTextColor={colors.onSurfaceTertiary}
      testID={testID}
    />
  );
}

const st = StyleSheet.create({
  box: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    paddingHorizontal: 12,
    paddingVertical: 10,
    position: "relative",
  },
  display: { fontSize: 14, fontWeight: "600", color: colors.onSurface },
  placeholder: { fontWeight: "400", color: colors.onSurfaceTertiary },
  native: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    color: colors.onSurface,
  },
});
