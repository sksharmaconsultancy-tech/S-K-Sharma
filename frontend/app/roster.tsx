/**
 * Daily roster (resort / hospitality)
 *
 * Supervisor lists every employee in scope + their punch state today,
 * multi-selects rows, and bulk-marks them IN / OUT / Absent. Ideal for
 * live-in staff whose phones never leave the premises.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
  Alert,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing, type } from "@/src/theme";

type RosterRow = {
  user_id: string;
  name: string;
  employee_code?: string | null;
  is_live_in: boolean;
  shift_start?: string | null;
  shift_end?: string | null;
  first_in?: string | null;
  last_out?: string | null;
  punch_count: number;
  state: "in" | "done" | "absent";
};

const fmtTime = (iso?: string | null) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
};

const showMsg = (msg: string) => {
  if (Platform.OS === "web") window.alert(msg);
  else Alert.alert("Roster", msg);
};

export default function RosterScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";

  const [rows, setRows] = useState<RosterRow[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [companyFilter, setCompanyFilter] = useState<string | "all">("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<"all" | "live_in" | "commute">("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q =
        isSuper && companyFilter !== "all"
          ? `?company_id=${companyFilter}`
          : "";
      const r = await api<{ roster: RosterRow[] }>(
        `/admin/attendance/roster${q}`,
      );
      setRows(r.roster || []);
      setSelected(new Set());
    } catch (e: any) {
      showMsg(e?.message || "Could not load roster.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [companyFilter, isSuper]);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    if (filter === "all") return rows;
    if (filter === "live_in") return rows.filter((r) => r.is_live_in);
    return rows.filter((r) => !r.is_live_in);
  }, [rows, filter]);

  const toggle = (uid: string) => {
    // Iter 68 — Once an employee has ANY punch (auto / manual) for the
    // day, disable further roster-driven changes.  Prevents accidental
    // double-marking and preserves data integrity.
    const target = rows.find((r) => r.user_id === uid);
    if (target && (target.punch_count || 0) > 0) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  };

  const selectAllShown = () => {
    // Only select rows that don't already have punches recorded.
    setSelected(new Set(filtered.filter((r) => !r.punch_count).map((r) => r.user_id)));
  };
  const clearAll = () => setSelected(new Set());

  const doBatch = async (action: "in" | "out" | "absent") => {
    if (selected.size === 0) {
      showMsg("Select at least one employee first.");
      return;
    }
    setBusy(true);
    try {
      const marks = Array.from(selected).map((user_id) => ({ user_id, action }));
      const r = await api<{
        results: { user_id: string; ok: boolean; detail?: string }[];
      }>("/admin/attendance/roster/mark", {
        method: "POST",
        body: { marks },
      });
      const ok = r.results.filter((x) => x.ok).length;
      const failed = r.results.filter((x) => !x.ok);
      let msg = `Recorded ${action.toUpperCase()} for ${ok} employees.`;
      if (failed.length > 0) {
        msg += ` ${failed.length} skipped (${failed
          .slice(0, 3)
          .map((f) => f.detail || "unknown")
          .join(", ")}).`;
      }
      showMsg(msg);
      await load();
    } catch (e: any) {
      showMsg(e?.message || "Could not update roster.");
    } finally {
      setBusy(false);
    }
  };

  const stateBadge = (s: RosterRow["state"]) => {
    if (s === "in") return { bg: "#E7F5EA", fg: "#0F5B22", label: "IN" };
    if (s === "done") return { bg: "#EEF2F7", fg: "#334155", label: "Done" };
    return { bg: "#FDECE2", fg: "#7A1B00", label: "Absent" };
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8} testID="ros-back">
            <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Daily roster</Text>
            <Text style={styles.subtitle}>
              {filtered.length} shown · {selected.size} selected
            </Text>
          </View>
          <Pressable
            onPress={() => {
              setRefreshing(true);
              load();
            }}
            hitSlop={8}
            testID="ros-refresh"
          >
            <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
          </Pressable>
        </View>
      </SafeAreaView>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              load();
            }}
            tintColor={colors.brandPrimary}
          />
        }
      >
        {isSuper && (
          <View style={{ marginBottom: spacing.md }}>
            <CompanyPicker
              testID="ros-company-picker"
              value={companyFilter}
              onChange={setCompanyFilter}
              label=""
              compact={false}
            />
          </View>
        )}

        <View style={styles.filterRow}>
          {(["all", "live_in", "commute"] as const).map((f) => (
            <Pressable
              key={f}
              onPress={() => setFilter(f)}
              style={[styles.filterChip, filter === f && styles.filterChipOn]}
              testID={`ros-filter-${f}`}
            >
              <Text
                style={[
                  styles.filterChipTxt,
                  filter === f && styles.filterChipTxtOn,
                ]}
              >
                {f === "all" ? "All" : f === "live_in" ? "Live-in" : "Commute"}
              </Text>
            </Pressable>
          ))}
        </View>

        <View style={styles.selectBar}>
          <Pressable onPress={selectAllShown} testID="ros-select-all">
            <Text style={styles.selectTxt}>Select all shown</Text>
          </Pressable>
          <View style={{ flex: 1 }} />
          {selected.size > 0 ? (
            <Pressable onPress={clearAll} testID="ros-clear-selection">
              <Text style={styles.selectTxtMuted}>Clear</Text>
            </Pressable>
          ) : null}
        </View>

        {loading ? (
          <ActivityIndicator
            style={{ marginTop: 60 }}
            color={colors.brandPrimary}
          />
        ) : filtered.length === 0 ? (
          <View style={styles.empty} testID="ros-empty">
            <Ionicons
              name="people-outline"
              size={40}
              color={colors.onSurfaceTertiary}
            />
            <Text style={styles.emptyT}>No employees in this filter</Text>
          </View>
        ) : (
          filtered.map((r) => {
            const on = selected.has(r.user_id);
            const b = stateBadge(r.state);
            const alreadyPunched = (r.punch_count || 0) > 0;
            return (
              <Pressable
                key={r.user_id}
                onPress={() => toggle(r.user_id)}
                disabled={alreadyPunched}
                style={[
                  styles.row,
                  on && styles.rowOn,
                  alreadyPunched && { opacity: 0.55 },
                ]}
                testID={`ros-row-${r.user_id}`}
              >
                <View
                  style={[
                    styles.check,
                    on && styles.checkOn,
                    alreadyPunched && { backgroundColor: colors.borderStrong, borderColor: colors.borderStrong },
                  ]}
                >
                  {alreadyPunched ? (
                    <Ionicons name="lock-closed" size={10} color="#fff" />
                  ) : on ? (
                    <Ionicons name="checkmark" size={12} color="#fff" />
                  ) : null}
                </View>
                <View style={{ flex: 1 }}>
                  <View style={styles.rowTop}>
                    <Text style={styles.name} numberOfLines={1}>
                      {r.name}
                    </Text>
                    {r.is_live_in ? (
                      <View style={styles.livePill}>
                        <Ionicons
                          name="home"
                          size={10}
                          color={colors.onBrandTertiary}
                        />
                        <Text style={styles.livePillTxt}>Live-in</Text>
                      </View>
                    ) : null}
                  </View>
                  <Text style={styles.meta} numberOfLines={1}>
                    {r.employee_code ? `${r.employee_code} · ` : ""}
                    {r.shift_start && r.shift_end
                      ? `Shift ${r.shift_start}–${r.shift_end}`
                      : "No shift"}
                  </Text>
                  <View style={styles.timesRow}>
                    <Text style={styles.timeTxt}>
                      IN {fmtTime(r.first_in)}
                    </Text>
                    <Text style={styles.timeTxt}>
                      OUT {fmtTime(r.last_out)}
                    </Text>
                    <Text style={styles.timeTxt}>
                      {r.punch_count} punch{r.punch_count === 1 ? "" : "es"}
                    </Text>
                  </View>
                </View>
                <View style={[styles.stateBadge, { backgroundColor: b.bg }]}>
                  <Text style={[styles.stateBadgeTxt, { color: b.fg }]}>
                    {b.label}
                  </Text>
                </View>
              </Pressable>
            );
          })
        )}

        <View style={{ height: 120 }} />
      </ScrollView>

      {/* Bottom action bar */}
      {selected.size > 0 ? (
        <View style={styles.actionBar}>
          <Pressable
            onPress={() => doBatch("in")}
            disabled={busy}
            style={[styles.actBtn, { backgroundColor: colors.success }]}
            testID="ros-mark-in"
          >
            {busy ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="log-in-outline" size={15} color="#fff" />
                <Text style={styles.actBtnTxt}>Mark IN</Text>
              </>
            )}
          </Pressable>
          <Pressable
            onPress={() => doBatch("out")}
            disabled={busy}
            style={[styles.actBtn, { backgroundColor: colors.brandPrimary }]}
            testID="ros-mark-out"
          >
            <Ionicons name="log-out-outline" size={15} color="#fff" />
            <Text style={styles.actBtnTxt}>Mark OUT</Text>
          </Pressable>
          <Pressable
            onPress={() => doBatch("absent")}
            disabled={busy}
            style={[styles.actBtn, { backgroundColor: colors.error }]}
            testID="ros-mark-absent"
          >
            <Ionicons name="close-outline" size={15} color="#fff" />
            <Text style={styles.actBtnTxt}>Mark Absent</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    backgroundColor: colors.surface,
  },
  title: { color: colors.onSurface, fontSize: type.xl, fontWeight: "800" },
  subtitle: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 2,
  },
  scroll: { padding: spacing.lg },
  filterRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: spacing.md,
  },
  filterChip: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.surface,
  },
  filterChipOn: { backgroundColor: colors.brandPrimary },
  filterChipTxt: {
    color: colors.brandPrimary,
    fontSize: 12,
    fontWeight: "700",
  },
  filterChipTxtOn: { color: "#fff" },
  selectBar: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: spacing.sm,
  },
  selectTxt: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "700",
  },
  selectTxtMuted: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    fontWeight: "700",
  },
  empty: { alignItems: "center", padding: spacing.xl },
  emptyT: {
    color: colors.onSurface,
    fontSize: type.lg,
    fontWeight: "800",
    marginTop: 12,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: "transparent",
  },
  rowOn: { borderColor: colors.brandPrimary },
  check: {
    width: 22,
    height: 22,
    borderRadius: 5,
    borderWidth: 1.5,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  checkOn: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  rowTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  name: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  meta: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },
  timesRow: {
    flexDirection: "row",
    gap: 10,
    marginTop: 6,
    flexWrap: "wrap",
  },
  timeTxt: { color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "600" },
  livePill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingHorizontal: 6,
    paddingVertical: 2,
    backgroundColor: colors.brandTertiary,
    borderRadius: 4,
  },
  livePillTxt: {
    color: colors.onBrandTertiary,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 0.4,
  },
  stateBadge: {
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  stateBadgeTxt: {
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.5,
  },
  actionBar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: "row",
    gap: 8,
    padding: spacing.md,
    paddingBottom: spacing.lg,
    backgroundColor: colors.surface,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.divider,
  },
  actBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderRadius: radius.md,
  },
  actBtnTxt: {
    color: "#fff",
    fontSize: type.sm,
    fontWeight: "800",
  },
});
