/**
 * EmployeeDropdown — Iter 520 (user request).
 *
 * Searchable employee DROPDOWN (collapsed until tapped) used by the
 * ESIC Leave entry form, Full & Final report and other report pickers.
 * Modes:
 *   • single (default) — pick one employee, closes on select.
 *   • multi            — checkbox list + "All Employees" clear row.
 */
import React, { useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ScrollView, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, radius } from "@/src/theme";

export type EmpLite = { user_id: string; name?: string; employee_code?: string };

type Props = {
  employees: EmpLite[];
  value: string[];               // selected user_ids (0/1 in single mode)
  onChange: (ids: string[]) => void;
  multi?: boolean;
  label?: string;
  placeholder?: string;
  testID?: string;
};

export default function EmployeeDropdown({
  employees, value, onChange, multi = false,
  label, placeholder = "Select employee…", testID = "emp-dd",
}: Props) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return employees.slice(0, 200);
    return employees
      .filter((e) =>
        (e.name || "").toLowerCase().includes(s) ||
        String(e.employee_code || "").toLowerCase().includes(s))
      .slice(0, 200);
  }, [employees, q]);

  const summary = useMemo(() => {
    if (!value.length) return "";
    if (!multi || value.length === 1) {
      const e = employees.find((x) => x.user_id === value[0]);
      return e ? `${e.employee_code ? `${e.employee_code} · ` : ""}${e.name || e.user_id}` : "";
    }
    return `${value.length} employees selected`;
  }, [value, employees, multi]);

  const toggle = (id: string) => {
    if (multi) {
      onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id]);
    } else {
      onChange([id]);
      setOpen(false);
      setQ("");
    }
  };

  return (
    <View style={{ marginTop: 4 }}>
      {label ? <Text style={s.lbl}>{label}</Text> : null}
      <Pressable style={s.field} onPress={() => setOpen((v) => !v)} testID={testID}>
        <Ionicons name="person-outline" size={14} color={colors.onSurfaceTertiary} />
        <Text style={[s.fieldTxt, !summary && { color: colors.onSurfaceTertiary }]}
          numberOfLines={1}>
          {summary || placeholder}
        </Text>
        {value.length ? (
          <Pressable onPress={() => { onChange([]); setQ(""); }} hitSlop={6}
            testID={`${testID}-clear`}>
            <Ionicons name="close-circle" size={16} color={colors.onSurfaceTertiary} />
          </Pressable>
        ) : null}
        <Ionicons name={open ? "chevron-up" : "chevron-down"} size={15}
          color={colors.onSurfaceSecondary} />
      </Pressable>
      {open ? (
        <View style={s.panel}>
          <View style={s.searchRow}>
            <Ionicons name="search-outline" size={13} color={colors.onSurfaceTertiary} />
            <TextInput
              value={q} onChangeText={setQ} autoFocus
              placeholder="Search name or code…"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={s.searchInput} testID={`${testID}-search`}
            />
          </View>
          <ScrollView style={{ maxHeight: 240 }} nestedScrollEnabled keyboardShouldPersistTaps="handled">
            {multi ? (
              <Pressable style={s.row} onPress={() => onChange([])} testID={`${testID}-all`}>
                <Ionicons
                  name={!value.length ? "checkbox" : "square-outline"} size={16}
                  color={!value.length ? colors.brandPrimary : colors.onSurfaceTertiary} />
                <Text style={[s.rowTxt, { fontWeight: "800" }]}>All Employees</Text>
              </Pressable>
            ) : null}
            {filtered.map((e) => {
              const on = value.includes(e.user_id);
              return (
                <Pressable key={e.user_id} style={[s.row, on && s.rowOn]}
                  onPress={() => toggle(e.user_id)}
                  testID={`${testID}-opt-${e.employee_code || e.user_id}`}>
                  {multi ? (
                    <Ionicons name={on ? "checkbox" : "square-outline"} size={16}
                      color={on ? colors.brandPrimary : colors.onSurfaceTertiary} />
                  ) : (
                    <Ionicons name={on ? "radio-button-on" : "radio-button-off"} size={15}
                      color={on ? colors.brandPrimary : colors.onSurfaceTertiary} />
                  )}
                  <Text style={s.rowTxt} numberOfLines={1}>
                    {e.employee_code ? `${e.employee_code} · ` : ""}{e.name || e.user_id}
                  </Text>
                </Pressable>
              );
            })}
            {!filtered.length ? (
              <Text style={s.empty}>No employee matches “{q}”.</Text>
            ) : null}
          </ScrollView>
          {multi ? (
            <Pressable style={s.doneBtn} onPress={() => setOpen(false)} testID={`${testID}-done`}>
              <Text style={s.doneTxt}>Done{value.length ? ` (${value.length})` : " — All"}</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  lbl: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  field: {
    flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1,
    borderColor: colors.border, borderRadius: radius.sm ?? 8,
    paddingHorizontal: 10, paddingVertical: 9, backgroundColor: colors.surface,
    minHeight: 40,
  },
  fieldTxt: { flex: 1, fontSize: 13, color: colors.onSurface },
  panel: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 10,
    backgroundColor: colors.surface, marginTop: 4, overflow: "hidden",
  },
  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 10, paddingVertical: 7,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  searchInput: {
    flex: 1, fontSize: 12.5, color: colors.onSurface, paddingVertical: 0,
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
  },
  row: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 10, paddingVertical: 9,
    borderBottomWidth: 0.5, borderBottomColor: colors.border,
  },
  rowOn: { backgroundColor: "#EFF6FF" },
  rowTxt: { flex: 1, fontSize: 12.5, color: colors.onSurface },
  empty: { padding: 12, fontSize: 12, color: colors.onSurfaceTertiary, textAlign: "center" },
  doneBtn: {
    backgroundColor: colors.brandPrimary, alignItems: "center", paddingVertical: 9,
  },
  doneTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
});
