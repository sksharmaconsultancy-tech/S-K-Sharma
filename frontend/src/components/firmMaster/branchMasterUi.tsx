/**
 * Iter 737 — shared primitives for the Branch Master UI
 * (Firm Master → 18. Branches / Locations).
 */
import React from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, radius, spacing } from "@/src/theme";

export const showWebMsg = (msg: string) => {
  if (Platform.OS === "web") window.alert(msg);
};

export function BmField({
  label, value, onChangeText, placeholder, keyboardType, testID, width,
}: {
  label: string;
  value: string;
  onChangeText: (t: string) => void;
  placeholder?: string;
  keyboardType?: "default" | "decimal-pad" | "number-pad" | "email-address" | "phone-pad";
  testID?: string;
  width?: number;
}) {
  return (
    <View style={[{ marginBottom: spacing.xs }, width ? { width } : { flex: 1, minWidth: 150 }]}>
      <Text style={bm.fLabel}>{label}</Text>
      <TextInput
        testID={testID}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.onSurfaceTertiary}
        keyboardType={keyboardType || "default"}
        style={bm.fInput}
      />
    </View>
  );
}

export function BmToggle({
  label, value, onChange, testID,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
  testID?: string;
}) {
  return (
    <Pressable onPress={() => onChange(!value)} style={bm.toggleRow} testID={testID}>
      <Ionicons
        name={value ? "checkbox" : "square-outline"}
        size={18}
        color={value ? colors.brandPrimary : colors.onSurfaceTertiary}
      />
      <Text style={bm.toggleTxt}>{label}</Text>
    </Pressable>
  );
}

export function BmChip({
  label, on, onPress, testID, warn,
}: {
  label: string;
  on?: boolean;
  onPress: () => void;
  testID?: string;
  warn?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={[bm.chip, on && bm.chipOn, warn && bm.chipWarn]}
      testID={testID}
    >
      <Text style={[bm.chipTxt, on && { color: "#FFF" }, warn && { color: "#B45309" }]}>
        {label}
      </Text>
    </Pressable>
  );
}

export function BmChipRow({
  label, options, value, onChange, testID,
}: {
  label: string;
  options: string[];
  value?: string | null;
  onChange: (v: string) => void;
  testID?: string;
}) {
  return (
    <View style={{ marginBottom: spacing.xs, minWidth: 200, flex: 1 }}>
      <Text style={bm.fLabel}>{label}</Text>
      <View style={bm.chipsWrap}>
        {options.map((o) => (
          <BmChip key={o} label={o} on={value === o} onPress={() => onChange(o)}
                  testID={testID ? `${testID}-${o}` : undefined} />
        ))}
      </View>
    </View>
  );
}

export function BmBtn({
  label, onPress, kind = "primary", busy, icon, testID, small,
}: {
  label: string;
  onPress: () => void;
  kind?: "primary" | "ghost" | "danger";
  busy?: boolean;
  icon?: keyof typeof Ionicons.glyphMap;
  testID?: string;
  small?: boolean;
}) {
  const bg = kind === "primary" ? colors.brandPrimary
    : kind === "danger" ? "#FEE2E2" : colors.surfaceSecondary;
  const fg = kind === "primary" ? "#FFF"
    : kind === "danger" ? "#B91C1C" : colors.onSurfaceSecondary;
  return (
    <Pressable
      onPress={onPress}
      disabled={busy}
      style={[bm.btn, small && bm.btnSmall, { backgroundColor: bg }, busy && { opacity: 0.7 }]}
      testID={testID}
    >
      {busy ? <ActivityIndicator color={fg} size="small" /> : (
        <>
          {icon ? <Ionicons name={icon} size={small ? 12 : 14} color={fg} /> : null}
          <Text style={[bm.btnTxt, small && { fontSize: 11.5 }, { color: fg }]}>{label}</Text>
        </>
      )}
    </Pressable>
  );
}

export function StatusPill({ active }: { active: boolean }) {
  return (
    <View style={[bm.statusPill, { backgroundColor: active ? "#DCFCE7" : "#FEE2E2" }]}>
      <Text style={[bm.statusPillTxt, { color: active ? "#15803D" : "#B91C1C" }]}>
        {active ? "Active" : "Inactive"}
      </Text>
    </View>
  );
}

export const bm = StyleSheet.create({
  fLabel: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  fInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  toggleRow: {
    flexDirection: "row", alignItems: "center", gap: 7,
    paddingVertical: 6, paddingRight: 14,
  },
  toggleTxt: { fontSize: 12.5, fontWeight: "600", color: colors.onSurface },
  chip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 12,
    paddingHorizontal: 9, paddingVertical: 4, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipWarn: { borderColor: "#F59E0B", backgroundColor: "#FFFBEB" },
  chipTxt: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 5 },
  btn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5,
    borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 8,
  },
  btnSmall: { paddingHorizontal: 10, paddingVertical: 6 },
  btnTxt: { fontSize: 12.5, fontWeight: "800" },
  statusPill: { borderRadius: 10, paddingHorizontal: 8, paddingVertical: 2, alignSelf: "flex-start" },
  statusPillTxt: { fontSize: 10.5, fontWeight: "800" },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  secTitle: {
    fontSize: 12.5, fontWeight: "800", color: colors.onSurface,
    marginTop: spacing.sm, marginBottom: 6,
  },
});
