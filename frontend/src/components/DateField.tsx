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
  // Iter 245 (user request) — HYBRID field: the date can be TYPED manually
  // as DD-MM-YYYY *and* picked from the calendar (calendar icon). Works the
  // same on desktop web, mobile PWA (employer + employee) and native.
  const isoToDmy = (iso: string) =>
    iso && iso.length >= 10
      ? `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}`
      : "";
  // Accepts: DD-MM-YYYY, D-M-YYYY, DD/MM/YYYY, DD.MM.YYYY, DDMMYYYY, ISO.
  const parseTyped = (t: string): string | null => {
    const s = t.trim();
    if (!s) return "";
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s; // already ISO
    let m = s.replace(/[/.\s]/g, "-").match(/^(\d{1,2})-(\d{1,2})-(\d{4})$/);
    if (!m) {
      const digits = s.replace(/\D/g, "");
      if (digits.length === 8) {
        m = ["", digits.slice(0, 2), digits.slice(2, 4), digits.slice(4)] as any;
      }
    }
    if (!m) return null;
    const dd = Number(m[1]), mm = Number(m[2]), yyyy = Number(m[3]);
    if (dd < 1 || dd > 31 || mm < 1 || mm > 12 || yyyy < 1900 || yyyy > 2200) return null;
    return `${yyyy}-${String(mm).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
  };

  const [text, setText] = React.useState(isoToDmy(value));
  React.useEffect(() => { setText(isoToDmy(value)); }, [value]);

  const commit = () => {
    const iso = parseTyped(text);
    if (iso !== null) onChangeISO(iso);
    else setText(isoToDmy(value)); // invalid — revert to last good value
  };

  // Web: hidden native <input type="date"> supplies the calendar popover,
  // opened from the calendar icon.
  const webRef = React.useRef<any>(null);
  const openPicker = () => {
    try {
      webRef.current?.showPicker?.();
      webRef.current?.focus?.();
    } catch {
      webRef.current?.focus?.();
    }
  };

  return (
    <View style={[styles.wrap, compact && { paddingVertical: 4 }]}>
      <Pressable onPress={Platform.OS === "web" ? openPicker : undefined} hitSlop={8}>
        <Ionicons name="calendar-outline" size={16} color={colors.brandPrimary} />
      </Pressable>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <TextInput
        value={text}
        onChangeText={setText}
        onBlur={commit}
        onSubmitEditing={commit}
        placeholder={placeholder}
        placeholderTextColor={colors.onSurfaceTertiary}
        style={styles.nativeInput}
        maxLength={10}
        keyboardType={Platform.OS === "web" ? undefined : "numbers-and-punctuation"}
        testID={testID}
      />
      {Platform.OS === "web" ? (
        /* Hidden calendar input — the icon opens its picker. */
        // @ts-ignore web-only element
        <input
          ref={webRef}
          type="date"
          value={value || ""}
          min={min || undefined}
          max={max || undefined}
          onChange={(e) => onChangeISO((e.target as HTMLInputElement).value || "")}
          data-testid={testID ? `${testID}-picker` : undefined}
          tabIndex={-1}
          style={{
            position: "absolute", left: 0, bottom: 0, width: 1, height: 1,
            opacity: 0, border: "none", padding: 0, margin: 0,
            pointerEvents: "none",
          } as any}
        />
      ) : null}
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
  nativeInput: {
    fontSize: 13,
    color: colors.onSurface,
    minWidth: 130,
    paddingVertical: 2,
  },
});
