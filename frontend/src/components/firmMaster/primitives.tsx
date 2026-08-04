/**
 * Iter 484 — Shared primitives for the redesigned Firm Master ERP sections.
 * Modern card-based fields with inline validation, searchable dropdowns and
 * checkbox rows. All colors come from the theme tokens so every theme
 * preset (including the dark ones) renders correctly.
 */
import React, { useState } from "react";
import {
  View, Text, StyleSheet, TextInput, Pressable, ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, radius, spacing } from "@/src/theme";

export function Card({
  icon, title, subtitle, children, accent,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  accent?: string;
}) {
  return (
    <View style={[st.card, accent ? { borderTopColor: accent, borderTopWidth: 3 } : null]}>
      <View style={st.cardHead}>
        <View style={[st.cardIcon, accent ? { backgroundColor: accent + "22" } : null]}>
          <Ionicons name={icon} size={15} color={accent || colors.brandPrimary} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={st.cardTitle}>{title}</Text>
          {subtitle ? <Text style={st.cardSub}>{subtitle}</Text> : null}
        </View>
      </View>
      <View style={st.cardBody}>{children}</View>
    </View>
  );
}

export function FieldV2({
  label, value, onChange, placeholder, keyboardType, required, error, hint,
  disabled, maxLength, autoCapitalize, rightSlot, testID,
}: {
  label: string;
  value: string | null | undefined;
  onChange: (v: string) => void;
  placeholder?: string;
  keyboardType?: "default" | "numeric" | "email-address" | "phone-pad";
  required?: boolean;
  error?: string | null;
  hint?: string | null;
  disabled?: boolean;
  maxLength?: number;
  autoCapitalize?: "none" | "characters" | "words" | "sentences";
  rightSlot?: React.ReactNode;
  testID?: string;
}) {
  return (
    <View style={st.field}>
      <Text style={st.fieldLbl}>
        {label}{required ? <Text style={{ color: colors.error }}> *</Text> : null}
      </Text>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
        <TextInput
          value={value ?? ""}
          onChangeText={onChange}
          placeholder={placeholder}
          placeholderTextColor={colors.onSurfaceTertiary}
          keyboardType={keyboardType || "default"}
          maxLength={maxLength}
          editable={!disabled}
          autoCapitalize={autoCapitalize}
          style={[st.input, { flex: 1 },
            error ? { borderColor: colors.error } : null,
            disabled ? { opacity: 0.5 } : null]}
          testID={testID}
        />
        {rightSlot}
      </View>
      {error ? <Text style={st.errTxt}>⚠ {error}</Text> : null}
      {!error && hint ? <Text style={st.hintTxt}>{hint}</Text> : null}
    </View>
  );
}

export function DropdownV2({
  label, value, options, onChange, searchable, required, error, testID,
}: {
  label: string;
  value: string | null | undefined;
  options: string[];
  onChange: (v: string) => void;
  searchable?: boolean;
  required?: boolean;
  error?: string | null;
  testID?: string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const filtered = searchable && q.trim()
    ? options.filter((o) => o.toLowerCase().includes(q.trim().toLowerCase()))
    : options;
  return (
    <View style={[st.field, open ? { zIndex: 50 } : null]}>
      <Text style={st.fieldLbl}>
        {label}{required ? <Text style={{ color: colors.error }}> *</Text> : null}
      </Text>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        style={[st.input, st.ddBtn, error ? { borderColor: colors.error } : null]}
        testID={testID}
      >
        <Text style={[st.ddTxt, !value && { color: colors.onSurfaceTertiary }]} numberOfLines={1}>
          {value || "— select —"}
        </Text>
        <Ionicons name={open ? "chevron-up" : "chevron-down"} size={13} color={colors.onSurfaceSecondary} />
      </Pressable>
      {open ? (
        <View style={st.ddList}>
          {searchable ? (
            <TextInput
              value={q}
              onChangeText={setQ}
              placeholder="Type to search..."
              placeholderTextColor={colors.onSurfaceTertiary}
              style={st.ddSearch}
              autoFocus
            />
          ) : null}
          <ScrollView style={{ maxHeight: 220 }} keyboardShouldPersistTaps="handled">
            <Pressable onPress={() => { onChange(""); setOpen(false); setQ(""); }} style={st.ddItem}>
              <Text style={[st.ddItemTxt, { fontStyle: "italic", color: colors.onSurfaceTertiary }]}>Clear</Text>
            </Pressable>
            {filtered.map((opt) => (
              <Pressable
                key={opt}
                onPress={() => { onChange(opt); setOpen(false); setQ(""); }}
                style={[st.ddItem, value === opt && { backgroundColor: colors.brandTertiary }]}
              >
                <Text style={st.ddItemTxt}>{opt}</Text>
              </Pressable>
            ))}
            {filtered.length === 0 ? (
              <Text style={[st.ddItemTxt, { padding: 10, color: colors.onSurfaceTertiary }]}>No match</Text>
            ) : null}
          </ScrollView>
        </View>
      ) : null}
      {error ? <Text style={st.errTxt}>⚠ {error}</Text> : null}
    </View>
  );
}

export function CheckRow({
  label, value, onChange, testID,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
  testID?: string;
}) {
  return (
    <Pressable onPress={() => onChange(!value)} style={st.checkRow} testID={testID}>
      <Ionicons
        name={value ? "checkbox" : "square-outline"}
        size={18}
        color={value ? colors.brandPrimary : colors.onSurfaceTertiary}
      />
      <Text style={st.checkLbl}>{label}</Text>
    </Pressable>
  );
}

export function MiniBtn({
  icon, label, onPress, tone, disabled, testID,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  onPress: () => void;
  tone?: "primary" | "danger" | "neutral";
  disabled?: boolean;
  testID?: string;
}) {
  const c = tone === "danger" ? colors.error : tone === "neutral" ? colors.onSurfaceSecondary : colors.brandPrimary;
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={[st.miniBtn, { borderColor: c + "66" }, disabled && { opacity: 0.45 }]}
      testID={testID}
    >
      <Ionicons name={icon} size={13} color={c} />
      <Text style={[st.miniBtnTxt, { color: c }]}>{label}</Text>
    </Pressable>
  );
}

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

const st = StyleSheet.create({
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "visible",
  },
  cardHead: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.md, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  cardIcon: {
    width: 30, height: 30, borderRadius: 8, alignItems: "center",
    justifyContent: "center", backgroundColor: colors.brandTertiary,
  },
  cardTitle: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  cardSub: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 1 },
  cardBody: { padding: spacing.md, gap: 10 },
  field: { minWidth: 160, flex: 1 },
  fieldLbl: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  errTxt: { fontSize: 10.5, color: colors.error, marginTop: 3 },
  hintTxt: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 3 },
  ddBtn: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  ddTxt: { fontSize: 13, color: colors.onSurface, flex: 1 },
  ddList: {
    position: "absolute", top: 58, left: 0, right: 0, zIndex: 100,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.sm, elevation: 6,
    shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 8, shadowOffset: { width: 0, height: 3 },
  },
  ddSearch: {
    borderBottomWidth: 1, borderBottomColor: colors.divider,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 12.5, color: colors.onSurface,
  },
  ddItem: { paddingHorizontal: 10, paddingVertical: 8 },
  ddItemTxt: { fontSize: 12.5, color: colors.onSurface },
  checkRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 5, minWidth: 200 },
  checkLbl: { fontSize: 12.5, color: colors.onSurface },
  miniBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6,
    backgroundColor: colors.surface,
  },
  miniBtnTxt: { fontSize: 11.5, fontWeight: "700" },
});
