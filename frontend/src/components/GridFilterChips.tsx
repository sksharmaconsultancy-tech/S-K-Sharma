import React, { useMemo } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors } from "@/src/theme";

/**
 * Iter 183 — Branch / Department / Contractor filter chips for the
 * Salary Process grids (Compliance + Actual). Values are derived from
 * the run rows themselves, so only groups that actually have data are
 * rendered. Rows saved before this iteration (without these fields)
 * simply show no chips.
 */
export type GridFilters = { branch: string; dept: string; contractor: string };

export const GRID_FILTER_DEFAULT: GridFilters = {
  branch: "all",
  dept: "all",
  contractor: "all",
};

export function rowMatchesFilters(r: any, f: GridFilters): boolean {
  if (f.branch !== "all" && String(r?.branch_name || "").trim() !== f.branch) return false;
  if (f.dept !== "all" && String(r?.department || "").trim() !== f.dept) return false;
  if (f.contractor !== "all" && String(r?.contractor_name || "").trim() !== f.contractor) return false;
  return true;
}

const GROUPS: {
  key: keyof GridFilters;
  rowField: string;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
}[] = [
  { key: "branch", rowField: "branch_name", label: "Branch", icon: "git-branch-outline" },
  { key: "dept", rowField: "department", label: "Dept", icon: "layers-outline" },
  { key: "contractor", rowField: "contractor_name", label: "Contractor", icon: "briefcase-outline" },
];

export default function GridFilterChips({
  rows,
  filters,
  onChange,
  testPrefix,
  hide = [],
}: {
  rows: any[];
  filters: GridFilters;
  onChange: (f: GridFilters) => void;
  testPrefix: string;
  /** Iter 255 — keys ("branch" | "dept" | "contractor") to hide. */
  hide?: string[];
}) {
  const GROUPS_SHOWN = GROUPS.filter((g) => !hide.includes(g.key));
  const options = useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const g of GROUPS_SHOWN) {
      const set = new Set<string>();
      for (const r of rows || []) {
        const v = String((r as any)?.[g.rowField] || "").trim();
        if (v) set.add(v);
      }
      out[g.key] = [...set].sort((a, b) => a.localeCompare(b));
    }
    return out;
  }, [rows, hide]);  // eslint-disable-line react-hooks/exhaustive-deps

  const anyGroup = GROUPS_SHOWN.some((g) => (options[g.key] || []).length > 0);
  if (!anyGroup) return null;

  const active = GROUPS_SHOWN.filter((g) => filters[g.key] !== "all").length;

  return (
    <View style={styles.wrap} testID={`${testPrefix}-filter-chips`}>
      {GROUPS_SHOWN.map((g) => {
        const vals = options[g.key] || [];
        if (vals.length === 0) return null;
        return (
          <View key={g.key} style={styles.group}>
            <View style={styles.groupLabel}>
              <Ionicons name={g.icon} size={12} color={colors.onSurfaceSecondary} />
              <Text style={styles.groupLabelTxt}>{g.label}:</Text>
            </View>
            {["all", ...vals].map((v) => {
              const on = filters[g.key] === v;
              return (
                <Pressable
                  key={v}
                  onPress={() => onChange({ ...filters, [g.key]: v })}
                  style={[styles.chip, on && styles.chipOn]}
                  testID={`${testPrefix}-filter-${g.key}-${v === "all" ? "all" : v.replace(/\s+/g, "_")}`}
                >
                  <Text style={[styles.chipTxt, on && styles.chipTxtOn]}>
                    {v === "all" ? "All" : v}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        );
      })}
      {active > 0 ? (
        <Pressable
          onPress={() => onChange(GRID_FILTER_DEFAULT)}
          style={styles.clearBtn}
          testID={`${testPrefix}-filter-clear`}
        >
          <Ionicons name="close-circle-outline" size={13} color={colors.error} />
          <Text style={styles.clearTxt}>Clear filters</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 6,
    marginTop: 8,
  },
  group: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 5,
    marginRight: 8,
  },
  groupLabel: { flexDirection: "row", alignItems: "center", gap: 4 },
  groupLabelTxt: {
    color: colors.onSurfaceSecondary,
    fontSize: 11,
    fontWeight: "700",
  },
  chip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipOn: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandPrimary,
  },
  chipTxt: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  clearBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 5,
  },
  clearTxt: { color: colors.error, fontSize: 11, fontWeight: "700" },
});
