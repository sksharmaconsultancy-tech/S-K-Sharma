/**
 * FirmDropdown — Iter 479 (user request: "Always show Firm Picker as a
 * dropdown list").
 *
 * Simple select-style dropdown for choosing a firm inside page forms
 * (replaces chip rows that overflow with many firms). Inline expanding
 * list (no absolute positioning → never clipped inside sheets/modals),
 * with a search box when the list is long.
 */
import React, { useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, radius } from "@/src/theme";

export type FirmOpt = { company_id: string; name: string };

export default function FirmDropdown({
  value,
  onChange,
  options,
  placeholder = "Select firm…",
  allowNull = false,
  nullLabel = "Unassigned",
  testID,
}: {
  value: string | null;
  onChange: (cid: string | null) => void;
  options: FirmOpt[];
  placeholder?: string;
  allowNull?: boolean;
  nullLabel?: string;
  testID?: string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const selected = options.find((o) => o.company_id === value);
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((o) => o.name.toLowerCase().includes(needle));
  }, [options, q]);

  const pick = (cid: string | null) => {
    onChange(cid);
    setOpen(false);
    setQ("");
  };

  return (
    <View style={st.wrap}>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        style={[st.field, open && st.fieldOpen]}
        testID={testID || "firm-dropdown"}
      >
        <Ionicons name="business-outline" size={15} color={colors.brandPrimary} />
        <Text
          style={[st.fieldTxt, !selected && !value && { color: colors.onSurfaceTertiary }]}
          numberOfLines={1}
        >
          {selected?.name || (value === null && allowNull ? nullLabel : placeholder)}
        </Text>
        <Ionicons
          name={open ? "chevron-up" : "chevron-down"}
          size={16}
          color={colors.onSurfaceSecondary}
        />
      </Pressable>
      {open ? (
        <View style={st.panel}>
          {options.length > 6 ? (
            <TextInput
              value={q}
              onChangeText={setQ}
              placeholder="Search firm…"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={st.search}
              autoFocus
            />
          ) : null}
          <ScrollView style={{ maxHeight: 240 }} keyboardShouldPersistTaps="handled">
            {allowNull ? (
              <Pressable onPress={() => pick(null)} style={st.row}>
                <Ionicons
                  name={value === null ? "radio-button-on" : "radio-button-off"}
                  size={15}
                  color={colors.brandPrimary}
                />
                <Text style={st.rowTxt}>{nullLabel}</Text>
              </Pressable>
            ) : null}
            {filtered.map((o) => (
              <Pressable
                key={o.company_id}
                onPress={() => pick(o.company_id)}
                style={[st.row, o.company_id === value && st.rowOn]}
                testID={`firm-opt-${o.company_id}`}
              >
                <Ionicons
                  name={o.company_id === value ? "radio-button-on" : "radio-button-off"}
                  size={15}
                  color={colors.brandPrimary}
                />
                <Text style={st.rowTxt} numberOfLines={1}>{o.name}</Text>
              </Pressable>
            ))}
            {!filtered.length ? (
              <Text style={st.empty}>No firms match &quot;{q}&quot;</Text>
            ) : null}
          </ScrollView>
        </View>
      ) : null}
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { width: "100%" },
  field: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 11,
    backgroundColor: colors.surface,
  },
  fieldOpen: { borderColor: colors.brandPrimary },
  fieldTxt: { flex: 1, fontSize: 13.5, fontWeight: "600", color: colors.onSurface },
  panel: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    marginTop: 4,
    backgroundColor: colors.surface,
    overflow: "hidden",
  },
  search: {
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    paddingHorizontal: 12,
    paddingVertical: 9,
    fontSize: 13,
    color: colors.onSurface,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  rowOn: { backgroundColor: colors.surfaceSecondary },
  rowTxt: { flex: 1, fontSize: 13, fontWeight: "600", color: colors.onSurface },
  empty: { padding: 12, fontSize: 12, color: colors.onSurfaceTertiary },
});
