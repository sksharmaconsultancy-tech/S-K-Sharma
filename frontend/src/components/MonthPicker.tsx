/**
 * MonthPicker — Iter 64.
 *
 * A friendly Month + Year selector used everywhere we previously asked
 * users to type a `YYYY-MM` string (Salary Run, Compliance Run,
 * Attendance Sheet, Reports Hub, Attendance Email).
 *
 * • Value shape stays `YYYY-MM` so all backend contracts continue to work.
 * • Users see a labelled 12-month dropdown ("June 2026") plus a year
 *   selector so they can quickly jump across years without scrolling
 *   through hundreds of options.
 * • Supports an optional "any month" state via the ``allowEmpty`` flag –
 *   emits an empty string, matching existing "leave blank for all" flows.
 * • On web, we render two native ``<select>`` boxes; on native we use a
 *   simple modal list. Both branches keep the same 44-pt touch target.
 */
import React, { useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Modal,
  ScrollView,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, radius } from "@/src/theme";

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

type Props = {
  value: string; // "YYYY-MM" or "" (only when allowEmpty)
  onChange: (v: string) => void;
  allowEmpty?: boolean;
  emptyLabel?: string;
  yearsBack?: number;
  yearsForward?: number;
  disabled?: boolean;
  testID?: string;
};

function parseValue(v: string): { year: number; month: number } | null {
  const m = /^(\d{4})-(\d{2})$/.exec(v || "");
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  if (!Number.isFinite(year) || month < 1 || month > 12) return null;
  return { year, month };
}

function labelFor(v: string, emptyLabel: string): string {
  const p = parseValue(v);
  if (!p) return emptyLabel;
  return `${MONTH_NAMES[p.month - 1]} ${p.year}`;
}

export default function MonthPicker({
  value,
  onChange,
  allowEmpty = true,
  emptyLabel = "All months",
  yearsBack = 4,
  yearsForward = 1,
  disabled = false,
  testID,
}: Props) {
  const now = new Date();
  const currentYear = now.getFullYear();
  const currentMonth = now.getMonth() + 1;

  const parsed = parseValue(value);
  const selectedYear = parsed?.year ?? currentYear;
  const selectedMonth = parsed?.month ?? 0; // 0 = "all months"

  const years = useMemo(() => {
    const out: number[] = [];
    for (let y = currentYear + yearsForward; y >= currentYear - yearsBack; y--) {
      out.push(y);
    }
    return out;
  }, [currentYear, yearsBack, yearsForward]);

  const emit = (y: number, m: number) => {
    if (m === 0) {
      if (allowEmpty) onChange("");
      return;
    }
    const mm = String(m).padStart(2, "0");
    onChange(`${y}-${mm}`);
  };

  // ---------------- Web branch: two native <select> boxes ---------------
  if (Platform.OS === "web") {
    return (
      <View style={styles.rowWrap} testID={testID}>
        <select
          disabled={disabled}
          value={selectedMonth ? String(selectedMonth) : ""}
          onChange={(e) => {
            const m = Number((e.target as HTMLSelectElement).value);
            emit(selectedYear, Number.isFinite(m) ? m : 0);
          }}
          style={{ ...(styles.selectBase as any), flex: 1.4 }}
          data-testid={testID ? `${testID}-month` : undefined}
        >
          {allowEmpty ? <option value="">{emptyLabel}</option> : null}
          {MONTH_NAMES.map((name, idx) => (
            <option key={name} value={String(idx + 1)}>
              {name}
            </option>
          ))}
        </select>
        <select
          disabled={disabled || (allowEmpty && selectedMonth === 0)}
          value={String(selectedYear)}
          onChange={(e) => {
            const y = Number((e.target as HTMLSelectElement).value);
            const m = selectedMonth || currentMonth; // if user was on "all", pick current
            emit(y, m);
          }}
          style={{ ...(styles.selectBase as any), flex: 1 }}
          data-testid={testID ? `${testID}-year` : undefined}
        >
          {years.map((y) => (
            <option key={y} value={String(y)}>
              {y}
            </option>
          ))}
        </select>
      </View>
    );
  }

  // ---------------- Native branch: modal list -------------------------
  return <NativeMonthPicker
    value={value}
    onChange={onChange}
    allowEmpty={allowEmpty}
    emptyLabel={emptyLabel}
    years={years}
    disabled={disabled}
    testID={testID}
  />;
}

function NativeMonthPicker({
  value,
  onChange,
  allowEmpty,
  emptyLabel,
  years,
  disabled,
  testID,
}: {
  value: string;
  onChange: (v: string) => void;
  allowEmpty: boolean;
  emptyLabel: string;
  years: number[];
  disabled?: boolean;
  testID?: string;
}) {
  const [open, setOpen] = useState(false);
  const parsed = parseValue(value);
  const [year, setYear] = useState<number>(parsed?.year ?? new Date().getFullYear());
  const label = labelFor(value, emptyLabel);

  return (
    <>
      <Pressable
        onPress={() => !disabled && setOpen(true)}
        style={[styles.trigger, disabled && styles.triggerDisabled]}
        testID={testID}
      >
        <Ionicons name="calendar-outline" size={14} color={colors.brandPrimary} />
        <Text style={styles.triggerTxt} numberOfLines={1}>
          {label}
        </Text>
        <Ionicons name="chevron-down" size={14} color={colors.onSurfaceSecondary} />
      </Pressable>

      <Modal
        visible={open}
        transparent
        animationType="fade"
        onRequestClose={() => setOpen(false)}
      >
        <Pressable style={styles.modalOverlay} onPress={() => setOpen(false)}>
          <Pressable style={styles.modalCard} onPress={() => {}}>
            {/* Year strip */}
            <View style={styles.yearRow}>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={{ gap: 8, paddingHorizontal: 4 }}
              >
                {years.map((y) => (
                  <Pressable
                    key={y}
                    onPress={() => setYear(y)}
                    style={[
                      styles.yearChip,
                      year === y && styles.yearChipActive,
                    ]}
                  >
                    <Text
                      style={[
                        styles.yearChipTxt,
                        year === y && styles.yearChipTxtActive,
                      ]}
                    >
                      {y}
                    </Text>
                  </Pressable>
                ))}
              </ScrollView>
            </View>

            {/* 12 months grid */}
            <View style={styles.monthsGrid}>
              {allowEmpty ? (
                <Pressable
                  onPress={() => {
                    onChange("");
                    setOpen(false);
                  }}
                  style={[
                    styles.monthCell,
                    styles.monthCellFull,
                    !value && styles.monthCellActive,
                  ]}
                >
                  <Text
                    style={[
                      styles.monthCellTxt,
                      !value && styles.monthCellTxtActive,
                    ]}
                  >
                    {emptyLabel}
                  </Text>
                </Pressable>
              ) : null}
              {MONTH_NAMES.map((name, idx) => {
                const mm = String(idx + 1).padStart(2, "0");
                const key = `${year}-${mm}`;
                const on = value === key;
                return (
                  <Pressable
                    key={name}
                    onPress={() => {
                      onChange(key);
                      setOpen(false);
                    }}
                    style={[styles.monthCell, on && styles.monthCellActive]}
                  >
                    <Text
                      style={[styles.monthCellTxt, on && styles.monthCellTxtActive]}
                    >
                      {name}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  rowWrap: { flexDirection: "row", gap: 8, alignItems: "center" },
  selectBase: {
    padding: 10,
    borderRadius: 8,
    borderColor: colors.borderStrong,
    borderWidth: 1,
    fontSize: 14,
    backgroundColor: colors.surface,
    color: colors.onSurface,
  },
  trigger: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
  triggerDisabled: { opacity: 0.5 },
  triggerTxt: {
    flex: 1,
    color: colors.onSurface,
    fontSize: 14,
    fontWeight: "600",
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.4)",
    justifyContent: "center",
    padding: 20,
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 16,
    maxWidth: 460,
    alignSelf: "center",
    width: "100%",
  },
  yearRow: { marginBottom: 12 },
  yearChip: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  yearChipActive: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  yearChipTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  yearChipTxtActive: { color: "#fff" },
  monthsGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  monthCell: {
    width: "31%",
    paddingVertical: 12,
    alignItems: "center",
    borderRadius: 10,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  monthCellFull: { width: "100%" },
  monthCellActive: {
    backgroundColor: colors.brandTertiary,
    borderColor: colors.brandPrimary,
  },
  monthCellTxt: {
    fontSize: 13,
    fontWeight: "700",
    color: colors.onSurface,
  },
  monthCellTxtActive: { color: colors.brandPrimary },
});
