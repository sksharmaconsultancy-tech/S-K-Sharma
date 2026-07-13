/**
 * GlobalCompanyPicker — Iter 62.
 *
 * Compact searchable dropdown surfaced in the AdminWebShell header so the
 * super/sub admin can pick a firm once and have every page respect it via
 * the SelectedCompanyContext.
 *
 *  • Trigger button shows the currently selected firm (or "All firms")
 *  • Panel: search-by-name/code + scrollable list + "All firms" reset
 *  • Selection persists in localStorage across page reloads
 *  • Iter 86 — Recently-used firms pinned at the top (last 3 selected),
 *    keyboard navigation (Arrow Up/Down, Enter, Esc), taller list for
 *    long-term comfort on portfolios with many firms.
 *
 * Separate from the existing modal-based CompanyPicker.tsx (which is a
 * bottom-sheet style form control used inside individual pages).
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

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany, type CompanyLite } from "@/src/context/SelectedCompanyContext";
import { colors, radius } from "@/src/theme";

const RECENT_KEY = "skc:recent_firms";
const RECENT_MAX = 3;

function loadRecent(): string[] {
  if (Platform.OS !== "web") return [];
  try {
    const raw = (globalThis as any).localStorage?.getItem(RECENT_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function pushRecent(cid: string): void {
  if (Platform.OS !== "web" || !cid) return;
  try {
    const cur = loadRecent().filter((x) => x !== cid);
    cur.unshift(cid);
    const trimmed = cur.slice(0, RECENT_MAX);
    (globalThis as any).localStorage?.setItem(RECENT_KEY, JSON.stringify(trimmed));
  } catch {
    /* noop */
  }
}

export default function GlobalCompanyPicker({ compact = false }: { compact?: boolean }) {
  const {
    companies,
    companiesLoading,
    selectedCompanyId,
    selectedCompany,
    setSelectedCompanyId,
  } = useSelectedCompany();
  const { user } = useAuth();
  const isSubAdmin = (user?.role as string) === "sub_admin";
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [recent, setRecent] = useState<string[]>(() => loadRecent());
  // Cursor for keyboard navigation across the (pinned + filtered) list.
  const [cursor, setCursor] = useState<number>(-1);
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

  // Recent firms — only those still in the visible companies list.
  const recentPinned = useMemo<CompanyLite[]>(() => {
    if (query.trim()) return []; // hide pinned section while searching
    const byId = new Map(companies.map((c) => [c.company_id, c] as const));
    return recent
      .map((cid) => byId.get(cid))
      .filter((c): c is CompanyLite => Boolean(c))
      .filter((c) => c.company_id !== selectedCompanyId); // don't repeat current
  }, [recent, companies, query, selectedCompanyId]);

  // Ordered pickable list for keyboard cursor (pinned then filtered — skipping duplicates).
  const orderedPickable = useMemo<CompanyLite[]>(() => {
    const pinnedIds = new Set(recentPinned.map((c) => c.company_id));
    return [...recentPinned, ...filtered.filter((c) => !pinnedIds.has(c.company_id))];
  }, [recentPinned, filtered]);

  // Close on outside click (web only)
  useEffect(() => {
    if (Platform.OS !== "web" || !open) return;
    const onDocClick = (e: MouseEvent) => {
      const el = wrapRef.current as unknown as HTMLElement | null;
      if (!el) return;
      if (!el.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
        setCursor(-1);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  // Reset cursor when list changes.
  useEffect(() => {
    setCursor(orderedPickable.length > 0 ? 0 : -1);
  }, [orderedPickable.length]);

  const commitSelection = (cid: string | null) => {
    setSelectedCompanyId(cid);
    if (cid) {
      pushRecent(cid);
      setRecent(loadRecent());
    }
    setOpen(false);
    setQuery("");
    setCursor(-1);
  };

  const label = selectedCompany
    ? `${selectedCompany.name}${selectedCompany.company_code ? ` · ${selectedCompany.company_code}` : ""}`
    : companiesLoading
      ? "Loading…"
      : isSubAdmin
        ? "Select firm…"
        : companies.length > 0
          ? "All firms"
          : "No firms";

  return (
    <View ref={wrapRef as any} style={[styles.wrap, compact && { minWidth: 200 }]}>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        style={[styles.trigger, open && styles.triggerOpen]}
        testID="global-company-picker-trigger"
      >
        <Ionicons name="business-outline" size={16} color={colors.brandPrimary} />
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
              testID="global-company-picker-search"
              value={query}
              onChangeText={setQuery}
              placeholder="Search by name or code…"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.searchInput}
              autoFocus
              onKeyPress={(e: any) => {
                const key = e?.nativeEvent?.key;
                if (key === "ArrowDown") {
                  e.preventDefault?.();
                  setCursor((c) => Math.min(orderedPickable.length - 1, c + 1));
                } else if (key === "ArrowUp") {
                  e.preventDefault?.();
                  setCursor((c) => Math.max(0, c - 1));
                } else if (key === "Enter") {
                  e.preventDefault?.();
                  const picked = orderedPickable[cursor];
                  if (picked) commitSelection(picked.company_id);
                } else if (key === "Escape") {
                  e.preventDefault?.();
                  setOpen(false);
                  setQuery("");
                  setCursor(-1);
                }
              }}
            />
            {query.length > 0 ? (
              <Pressable onPress={() => setQuery("")} hitSlop={8}>
                <Ionicons name="close-circle" size={16} color={colors.onSurfaceTertiary} />
              </Pressable>
            ) : null}
          </View>

          <ScrollView style={styles.list} keyboardShouldPersistTaps="handled">
            {isSubAdmin ? null : (
              <Pressable
                onPress={() => commitSelection(null)}
                style={[styles.row, !selectedCompanyId && styles.rowActive]}
                testID="global-company-picker-all"
              >
                <Ionicons
                  name={!selectedCompanyId ? "radio-button-on" : "radio-button-off"}
                  size={16}
                  color={colors.brandPrimary}
                />
                <Text style={styles.rowLabel}>All firms (default)</Text>
              </Pressable>
            )}

            {recentPinned.length > 0 ? (
              <>
                <View style={styles.sectionHdr}>
                  <Ionicons name="time-outline" size={12} color={colors.onSurfaceSecondary} />
                  <Text style={styles.sectionHdrTxt}>RECENT</Text>
                </View>
                {recentPinned.map((c, i) => {
                  const on = c.company_id === selectedCompanyId;
                  const isCursor = i === cursor;
                  return (
                    <Pressable
                      key={`rc-${c.company_id}`}
                      onPress={() => commitSelection(c.company_id)}
                      style={[styles.row, on && styles.rowActive, isCursor && styles.rowCursor]}
                      testID={`global-company-picker-recent-${c.company_id}`}
                    >
                      <Ionicons
                        name={on ? "radio-button-on" : "radio-button-off"}
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
                })}
                <View style={styles.sectionHdr}>
                  <Ionicons name="list-outline" size={12} color={colors.onSurfaceSecondary} />
                  <Text style={styles.sectionHdrTxt}>ALL FIRMS</Text>
                </View>
              </>
            ) : null}

            {filtered.length === 0 && recentPinned.length === 0 ? (
              <View style={styles.empty}>
                <Text style={styles.emptyTxt}>
                  {companiesLoading ? "Loading…" : query.trim() ? "No firms match." : "No firms yet."}
                </Text>
              </View>
            ) : (
              filtered
                .filter((c) => !recentPinned.some((rc) => rc.company_id === c.company_id))
                .map((c, i) => {
                  const on = c.company_id === selectedCompanyId;
                  const cursorIdx = recentPinned.length + i;
                  const isCursor = cursorIdx === cursor;
                  return (
                    <Pressable
                      key={c.company_id}
                      onPress={() => commitSelection(c.company_id)}
                      style={[styles.row, on && styles.rowActive, isCursor && styles.rowCursor]}
                      testID={`global-company-picker-${c.company_id}`}
                    >
                      <Ionicons
                        name={on ? "radio-button-on" : "radio-button-off"}
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
              {filtered.length} firm{filtered.length === 1 ? "" : "s"}
              {selectedCompanyId ? " · locked to session" : ""}
              {"   ·   ↑↓ Enter Esc"}
            </Text>
          </View>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: "relative", minWidth: 260, zIndex: 100 },
  trigger: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
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
    top: 44,
    left: 0,
    right: 0,
    minWidth: 320,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.divider,
    ...(Platform.OS === "web"
      ? ({ boxShadow: "0 12px 32px rgba(0,0,0,0.12)" } as any)
      : { elevation: 8 }),
    zIndex: 101,
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
  list: { maxHeight: 480 },
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
  rowCursor: { backgroundColor: "rgba(59,130,246,0.08)" },
  rowLabel: { flex: 1, color: colors.onSurface, fontSize: 13, fontWeight: "600" },
  rowSub: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 1 },
  sectionHdr: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 12, paddingVertical: 4,
    backgroundColor: colors.surfaceSecondary,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  sectionHdrTxt: {
    color: colors.onSurfaceSecondary, fontSize: 10,
    fontWeight: "800", letterSpacing: 0.6,
  },
  footer: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.divider,
    backgroundColor: colors.background,
    borderBottomLeftRadius: radius.md,
    borderBottomRightRadius: radius.md,
  },
  footerTxt: { color: colors.onSurfaceSecondary, fontSize: 11 },
  empty: { paddingHorizontal: 12, paddingVertical: 16, alignItems: "center" },
  emptyTxt: { color: colors.onSurfaceSecondary, fontSize: 12 },
});

