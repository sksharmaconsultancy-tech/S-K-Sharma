/**
 * MultiCompanyPicker — Iter 62.
 *
 * Searchable multi-select for firms. Designed for pages that run a batch
 * across multiple firms at once (e.g. Compliance Salary Batch).
 *
 * • Uses the SelectedCompanyContext to load the company list (no extra API
 *   call — reuses the cache from the global picker).
 * • Emits changes through ``onChange`` — completely controlled component so
 *   parents keep full ownership of their selection.
 * • Provides "Select all" / "Clear" / "Use current global firm" helpers.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ScrollView,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius } from "@/src/theme";

type Props = {
  value: Set<string>;
  onChange: (next: Set<string>) => void;
  testID?: string;
};

export default function MultiCompanyPicker({ value, onChange, testID }: Props) {
  const { companies, companiesLoading, selectedCompanyId } = useSelectedCompany();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrapRef = useRef<View | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return companies;
    return companies.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        (c.company_code || "").toLowerCase().includes(q),
    );
  }, [companies, query]);

  useEffect(() => {
    if (Platform.OS !== "web" || !open) return;
    const onDocClick = (e: MouseEvent) => {
      const el = wrapRef.current as unknown as HTMLElement | null;
      if (!el || typeof (el as any).contains !== "function") return;
      if (!el.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const toggle = (cid: string) => {
    const next = new Set(value);
    if (next.has(cid)) next.delete(cid);
    else next.add(cid);
    onChange(next);
  };

  const label =
    value.size === 0
      ? companiesLoading
        ? "Loading firms…"
        : "Pick firms"
      : value.size === 1
        ? (companies.find((c) => value.has(c.company_id))?.name || "1 firm")
        : `${value.size} firms selected`;

  const totalMatches = filtered.length;
  const selectedInFilter = filtered.filter((c) => value.has(c.company_id)).length;

  return (
    <View ref={wrapRef as any} style={styles.wrap} testID={testID}>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        style={[styles.trigger, open && styles.triggerOpen]}
        testID={`${testID || "multi-company-picker"}-trigger`}
      >
        <Ionicons name="albums-outline" size={16} color={colors.brandPrimary} />
        <Text style={styles.triggerLabel} numberOfLines={1}>
          {label}
        </Text>
        <Ionicons
          name={open ? "chevron-up" : "chevron-down"}
          size={14}
          color={colors.onSurfaceSecondary}
        />
      </Pressable>

      {open ? (
        <View style={styles.panel}>
          <View style={styles.searchRow}>
            <Ionicons name="search-outline" size={14} color={colors.onSurfaceTertiary} />
            <TextInput
              value={query}
              onChangeText={setQuery}
              placeholder="Search firms…"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.searchInput}
              autoFocus
              testID={`${testID || "multi-company-picker"}-search`}
            />
            {query.length > 0 ? (
              <Pressable onPress={() => setQuery("")} hitSlop={8}>
                <Ionicons name="close-circle" size={16} color={colors.onSurfaceTertiary} />
              </Pressable>
            ) : null}
          </View>

          {/* Bulk-action row */}
          <View style={styles.actionsRow}>
            <Pressable
              onPress={() => {
                const next = new Set(value);
                for (const c of filtered) next.add(c.company_id);
                onChange(next);
              }}
              style={styles.actBtn}
            >
              <Text style={styles.actTxt}>
                Select {query.trim() ? "filtered" : "all"}
                {" ("}
                {selectedInFilter}/{totalMatches}
                {")"}
              </Text>
            </Pressable>
            <Pressable onPress={() => onChange(new Set())} style={styles.actBtn}>
              <Text style={styles.actTxt}>Clear</Text>
            </Pressable>
            {selectedCompanyId ? (
              <Pressable
                onPress={() => onChange(new Set([selectedCompanyId]))}
                style={styles.actBtn}
              >
                <Text style={styles.actTxt}>Use header firm</Text>
              </Pressable>
            ) : null}
          </View>

          <ScrollView style={styles.list} keyboardShouldPersistTaps="handled">
            {filtered.length === 0 ? (
              <View style={styles.empty}>
                <Text style={styles.emptyTxt}>
                  {companiesLoading ? "Loading…" : query.trim() ? "No firms match." : "No firms yet."}
                </Text>
              </View>
            ) : (
              filtered.map((c) => {
                const on = value.has(c.company_id);
                return (
                  <Pressable
                    key={c.company_id}
                    onPress={() => toggle(c.company_id)}
                    style={[styles.row, on && styles.rowActive]}
                  >
                    <Ionicons
                      name={on ? "checkbox" : "square-outline"}
                      size={16}
                      color={on ? colors.brandPrimary : colors.onSurfaceSecondary}
                    />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.rowLabel} numberOfLines={1}>
                        {c.name}
                      </Text>
                      {c.company_code ? (
                        <Text style={styles.rowSub}>{c.company_code}</Text>
                      ) : null}
                    </View>
                  </Pressable>
                );
              })
            )}
          </ScrollView>

          <View style={styles.footer}>
            <Text style={styles.footerTxt}>
              {value.size} of {companies.length} selected
            </Text>
            <Pressable
              onPress={() => setOpen(false)}
              style={styles.doneBtn}
              testID={`${testID || "multi-company-picker"}-done`}
            >
              <Text style={styles.doneTxt}>Done</Text>
            </Pressable>
          </View>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: "relative", minWidth: 280, zIndex: 90 },
  trigger: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
  triggerOpen: { borderColor: colors.brandPrimary },
  triggerLabel: {
    flex: 1,
    color: colors.onSurface,
    fontWeight: "700",
    fontSize: 13,
  },
  panel: {
    position: "absolute",
    top: 46,
    left: 0,
    right: 0,
    minWidth: 320,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.divider,
    ...(Platform.OS === "web"
      ? ({ boxShadow: "0 12px 32px rgba(0,0,0,0.14)" } as any)
      : { elevation: 8 }),
    zIndex: 91,
  },
  searchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  searchInput: {
    flex: 1,
    fontSize: 13,
    color: colors.onSurface,
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : {}),
  },
  actionsRow: {
    flexDirection: "row",
    gap: 6,
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
    flexWrap: "wrap",
  },
  actBtn: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 999,
    backgroundColor: colors.brandTertiary,
  },
  actTxt: { color: colors.brandPrimary, fontSize: 11, fontWeight: "800" },
  list: { maxHeight: 320 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  rowActive: { backgroundColor: colors.brandTertiary },
  rowLabel: { flex: 1, color: colors.onSurface, fontSize: 13, fontWeight: "600" },
  rowSub: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 1 },
  footer: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.divider,
    backgroundColor: colors.background,
    borderBottomLeftRadius: radius.md,
    borderBottomRightRadius: radius.md,
  },
  footerTxt: { color: colors.onSurfaceSecondary, fontSize: 11 },
  doneBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: colors.brandPrimary,
  },
  doneTxt: { color: "#fff", fontSize: 12, fontWeight: "800" },
  empty: { paddingHorizontal: 12, paddingVertical: 16, alignItems: "center" },
  emptyTxt: { color: colors.onSurfaceSecondary, fontSize: 12 },
});
