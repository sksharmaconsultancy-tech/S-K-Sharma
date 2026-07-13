import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Modal,
  Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, spacing, type } from "@/src/theme";
import { useAuth } from "@/src/context/AuthContext";
import LocationPill from "@/src/components/LocationPill";

type Record = {
  record_id: string;
  date: string;   // YYYY-MM-DD
  at: string;     // ISO
  kind: "in" | "out";
  distance_m: number;
  biometric_method?: string;
  location_status?: "inside" | "outside" | "no-gps" | string;
};

type DaySummary = {
  date: string;         // YYYY-MM-DD
  day: number;          // day-of-month (1..31)
  weekday: number;      // 0..6 (Sun..Sat)
  isToday: boolean;
  isFuture: boolean;
  isWeekend: boolean;
  present: boolean;
  firstIn?: string | null;
  lastOut?: string | null;
  totalMinutes: number;
  punches: number;
  status: "present" | "half" | "absent" | "weekend" | "future";
};

const WEEKDAY_LABELS = ["S", "M", "T", "W", "T", "F", "S"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function ymd(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function fmtHM(mins: number): string {
  if (!mins || mins <= 0) return "—";
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h <= 0) return `${m}m`;
  if (m <= 0) return `${h}h`;
  return `${h}h ${m}m`;
}

function fmtTime(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "—";
  }
}

/**
 * Aggregate raw punch records into per-day summaries for a given month.
 * A "day" is a calendar day in the user's local timezone. Duty minutes are
 * the sum of contiguous (in → out) pairs; a lone "in" without a matching
 * "out" is treated as still-open (contributes 0 to totals but marks present).
 */
function buildMonth(
  records: Record[],
  year: number,
  month: number,   // 0..11
  todayStr: string,
): DaySummary[] {
  // Bucket records by date string
  const byDate: { [k: string]: Record[] } = {};
  for (const r of records) {
    if (!byDate[r.date]) byDate[r.date] = [];
    byDate[r.date].push(r);
  }

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const out: DaySummary[] = [];
  for (let d = 1; d <= daysInMonth; d++) {
    const dt = new Date(year, month, d);
    const key = ymd(dt);
    const wk = dt.getDay();
    const isWeekend = wk === 0; // Sunday only counted as weekend by default
    const dayRecs = (byDate[key] || []).slice().sort((a, b) => a.at.localeCompare(b.at));
    let firstIn: string | null = null;
    let lastOut: string | null = null;
    let totalMs = 0;
    let openIn: string | null = null;
    for (const r of dayRecs) {
      if (r.kind === "in") {
        if (!firstIn) firstIn = r.at;
        openIn = r.at;
      } else if (r.kind === "out") {
        lastOut = r.at;
        if (openIn) {
          totalMs += new Date(r.at).getTime() - new Date(openIn).getTime();
          openIn = null;
        }
      }
    }
    const totalMinutes = Math.max(0, Math.round(totalMs / 60000));
    const present = dayRecs.length > 0;
    const isFuture = key > todayStr;
    const isToday = key === todayStr;
    let status: DaySummary["status"];
    if (isFuture) status = "future";
    else if (present) status = totalMinutes >= 240 ? "present" : "half";
    else if (isWeekend) status = "weekend";
    else status = "absent";
    out.push({
      date: key,
      day: d,
      weekday: wk,
      isToday,
      isFuture,
      isWeekend,
      present,
      firstIn,
      lastOut,
      totalMinutes,
      punches: dayRecs.length,
      status,
    });
  }
  return out;
}

export default function HistoryScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [records, setRecords] = useState<Record[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const now = new Date();
  const [cursor, setCursor] = useState<{ y: number; m: number }>({
    y: now.getFullYear(),
    m: now.getMonth(),
  });
  const [selected, setSelected] = useState<string | null>(null);

  // Iter 97 — punch photo (selfie) viewer for the employee's own punches.
  const [photo, setPhoto] = useState<{ loading: boolean; b64: string | null; open: boolean }>(
    { loading: false, b64: null, open: false },
  );
  const openPunchPhoto = async (recordId: string) => {
    setPhoto({ loading: true, b64: null, open: true });
    try {
      const r = await api<{ selfie_base64: string | null }>(`/attendance/${recordId}/selfie`);
      setPhoto({ loading: false, b64: r.selfie_base64 || null, open: true });
    } catch {
      setPhoto({ loading: false, b64: null, open: true });
    }
  };

  const monthLabel = `${MONTH_NAMES[cursor.m]} ${cursor.y}`;
  const isCurrentMonth =
    cursor.y === now.getFullYear() && cursor.m === now.getMonth();
  const canGoNext = !isCurrentMonth;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Pull 45 days by default; cover previous month cursor too.
      // Backend supports `days`; we pull enough for the visible month + today.
      const daysBack = Math.max(
        45,
        Math.ceil(
          (Date.now() - new Date(cursor.y, cursor.m, 1).getTime()) / 86_400_000,
        ) + 5,
      );
      const r = await api<{ records: Record[] }>(
        `/attendance/history?days=${daysBack}`,
      );
      setRecords(r.records || []);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [cursor.y, cursor.m]);
  useEffect(() => { load(); }, [load]);

  const todayStr = ymd(now);
  const days = useMemo(
    () => buildMonth(records, cursor.y, cursor.m, todayStr),
    [records, cursor.y, cursor.m, todayStr],
  );

  const stats = useMemo(() => {
    let present = 0;
    let half = 0;
    let absent = 0;
    let totalMinutes = 0;
    for (const d of days) {
      if (d.isFuture) continue;
      if (d.status === "present") present++;
      else if (d.status === "half") half++;
      else if (d.status === "absent") absent++;
      totalMinutes += d.totalMinutes;
    }
    return { present, half, absent, totalMinutes };
  }, [days]);

  const selectedDay = useMemo(
    () => days.find((d) => d.date === selected) || null,
    [days, selected],
  );

  const selectedRecords = useMemo(() => {
    if (!selected) return [];
    return records
      .filter((r) => r.date === selected)
      .sort((a, b) => a.at.localeCompare(b.at));
  }, [records, selected]);

  // Grid cells: pad with empty slots so day 1 lands on the correct weekday col
  const gridCells = useMemo(() => {
    const first = new Date(cursor.y, cursor.m, 1).getDay();
    const cells: (DaySummary | null)[] = Array(first).fill(null);
    for (const d of days) cells.push(d);
    while (cells.length % 7 !== 0) cells.push(null);
    return cells;
  }, [days, cursor.y, cursor.m]);

  // Break cells into weekly rows so React Native doesn't accidentally
  // reflow 7 items into 6 columns due to sub-pixel rounding of `100/7%`.
  const weekRows = useMemo(() => {
    const rows: (DaySummary | null)[][] = [];
    for (let i = 0; i < gridCells.length; i += 7) {
      rows.push(gridCells.slice(i, i + 7));
    }
    return rows;
  }, [gridCells]);

  const goPrev = () =>
    setCursor((c) =>
      c.m === 0 ? { y: c.y - 1, m: 11 } : { y: c.y, m: c.m - 1 },
    );
  const goNext = () => {
    if (!canGoNext) return;
    setCursor((c) =>
      c.m === 11 ? { y: c.y + 1, m: 0 } : { y: c.y, m: c.m + 1 },
    );
  };

  // Super admins don't track their own attendance — redirect them out.
  if (user?.role === "super_admin") {
    return <Redirect href="/(tabs)" />;
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Attendance</Text>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); load(); }}
            tintColor={colors.brandPrimary}
          />
        }
      >
        {/* Month picker */}
        <View style={styles.monthBar} testID="history-month-bar">
          <Pressable onPress={goPrev} style={styles.arrowBtn} hitSlop={8} testID="history-month-prev">
            <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={styles.monthCenter}>
            <Text style={styles.monthTxt} testID="history-month-label">
              {monthLabel}
            </Text>
            <Text style={styles.monthSub}>Full-month view</Text>
          </View>
          <Pressable
            onPress={goNext}
            style={[styles.arrowBtn, !canGoNext && styles.arrowBtnDisabled]}
            hitSlop={8}
            disabled={!canGoNext}
            testID="history-month-next"
          >
            <Ionicons
              name="chevron-forward"
              size={22}
              color={canGoNext ? colors.onSurface : colors.onSurfaceTertiary}
            />
          </Pressable>
        </View>

        {/* KPI row */}
        <View style={styles.kpiRow}>
          <View style={[styles.kpi, { backgroundColor: colors.brandTertiary }]}>
            <Text style={styles.kpiValue}>{stats.present}</Text>
            <Text style={styles.kpiLabel}>Full days</Text>
          </View>
          <View style={[styles.kpi, { backgroundColor: "#FFF4E5" }]}>
            <Text style={[styles.kpiValue, { color: "#B45309" }]}>{stats.half}</Text>
            <Text style={styles.kpiLabel}>Half days</Text>
          </View>
          <View style={[styles.kpi, { backgroundColor: "#FEE2E2" }]}>
            <Text style={[styles.kpiValue, { color: "#B91C1C" }]}>{stats.absent}</Text>
            <Text style={styles.kpiLabel}>Absent</Text>
          </View>
        </View>
        <View style={styles.totalCard}>
          <Ionicons name="time-outline" size={18} color={colors.brandPrimary} />
          <Text style={styles.totalTxt}>
            Total duty this month:{" "}
            <Text style={styles.totalStrong}>{fmtHM(stats.totalMinutes)}</Text>
          </Text>
        </View>

        {/* Weekday header */}
        <View style={styles.weekRow}>
          {WEEKDAY_LABELS.map((w, i) => (
            <Text
              key={`w-${i}`}
              style={[
                styles.weekLbl,
                (i === 0 || i === 6) && { color: colors.brandPrimary },
              ]}
            >
              {w}
            </Text>
          ))}
        </View>

        {/* Calendar grid */}
        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
        ) : (
          <View style={styles.grid}>
            {weekRows.map((row, wIdx) => (
              <View key={`wk-${wIdx}`} style={styles.weekLine}>
                {row.map((cell, cIdx) => {
                  if (!cell) {
                    return (
                      <View
                        key={`e-${wIdx}-${cIdx}`}
                        style={styles.cell}
                      />
                    );
                  }
                  const isSel = selected === cell.date;
                  const bg = statusBg(cell.status);
                  const fg = statusFg(cell.status);
                  return (
                    <Pressable
                      key={cell.date}
                      onPress={() =>
                        setSelected((s) => (s === cell.date ? null : cell.date))
                      }
                      style={[
                        styles.cell,
                        styles.dayCell,
                        { backgroundColor: bg },
                        isSel && styles.dayCellSelected,
                        cell.isToday && styles.dayCellToday,
                      ]}
                      testID={`day-${cell.date}`}
                    >
                      <Text style={[styles.dayNum, { color: fg }]}>
                        {cell.day}
                      </Text>
                      {cell.totalMinutes > 0 ? (
                        <Text style={[styles.dayMeta, { color: fg }]}>
                          {fmtHM(cell.totalMinutes)}
                        </Text>
                      ) : cell.status === "half" ? (
                        <Text style={[styles.dayMeta, { color: fg }]}>½</Text>
                      ) : (
                        <View style={styles.dayMetaSpacer} />
                      )}
                    </Pressable>
                  );
                })}
              </View>
            ))}
          </View>
        )}

        {/* Legend */}
        <View style={styles.legendRow}>
          <LegendDot color={colors.success} label="Present" />
          <LegendDot color="#F59E0B" label="Half day" />
          <LegendDot color={colors.error} label="Absent" />
          <LegendDot color={colors.border} label="Off / future" />
        </View>

        {/* Day drilldown */}
        {selectedDay && (
          <View style={styles.detail} testID={`detail-${selectedDay.date}`}>
            <Text style={styles.detailTitle}>
              {new Date(selectedDay.date).toLocaleDateString([], {
                weekday: "long",
                day: "2-digit",
                month: "short",
                year: "numeric",
              })}
            </Text>
            <View style={styles.detailRow}>
              <View style={styles.detailPill}>
                <Ionicons name="log-in-outline" size={14} color={colors.brandPrimary} />
                <Text style={styles.detailPillTxt}>In: {fmtTime(selectedDay.firstIn)}</Text>
              </View>
              <View style={styles.detailPill}>
                <Ionicons name="log-out-outline" size={14} color={colors.brandPrimary} />
                <Text style={styles.detailPillTxt}>Out: {fmtTime(selectedDay.lastOut)}</Text>
              </View>
              <View style={styles.detailPill}>
                <Ionicons name="time-outline" size={14} color={colors.brandPrimary} />
                <Text style={styles.detailPillTxt}>{fmtHM(selectedDay.totalMinutes)}</Text>
              </View>
            </View>
            {selectedRecords.length === 0 ? (
              <Text style={styles.detailEmpty}>No punches on this day.</Text>
            ) : (
              selectedRecords.map((r) => (
                <View key={r.record_id} style={styles.detailItem}>
                  <View
                    style={[
                      styles.detailIcon,
                      { backgroundColor: r.kind === "in" ? colors.brandTertiary : "#F3F4F6" },
                    ]}
                  >
                    <Ionicons
                      name={r.kind === "in" ? "arrow-down-circle" : "arrow-up-circle"}
                      size={18}
                      color={r.kind === "in" ? colors.onBrandTertiary : colors.onSurfaceSecondary}
                    />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.detailItemTitle}>
                      Punched {r.kind === "in" ? "In" : "Out"}
                    </Text>
                    <Text style={styles.detailItemSub}>
                      {fmtTime(r.at)}
                      {typeof r.distance_m === "number" && r.distance_m > 0
                        ? ` · ${Math.round(r.distance_m)}m from office`
                        : ""}
                    </Text>
                    <View style={{ marginTop: 4 }}>
                      <LocationPill
                        status={r.location_status}
                        distanceM={r.distance_m}
                      />
                    </View>
                  </View>
                  <View style={{ alignItems: "flex-end", gap: 4 }}>
                    <Text style={styles.detailItemMethod}>
                      {r.biometric_method || "—"}
                    </Text>
                    <Pressable
                      onPress={() => openPunchPhoto(r.record_id)}
                      style={photoStyles.iconBtn}
                      testID={`hist-photo-${r.record_id}`}
                    >
                      <Ionicons name="camera-outline" size={16} color={colors.brandPrimary} />
                    </Pressable>
                  </View>
                </View>
              ))
            )}
          </View>
        )}

        <View style={{ height: 40 }} />
      </ScrollView>

      {/* Iter 97 — punch selfie viewer */}
      <Modal visible={photo.open} transparent animationType="fade" onRequestClose={() => setPhoto((p) => ({ ...p, open: false }))}>
        <Pressable style={photoStyles.overlay} onPress={() => setPhoto((p) => ({ ...p, open: false }))}>
          <View style={photoStyles.box}>
            <View style={photoStyles.boxHead}>
              <Text style={photoStyles.boxTitle}>Punch Photo</Text>
              <Pressable onPress={() => setPhoto((p) => ({ ...p, open: false }))} hitSlop={10}>
                <Ionicons name="close" size={22} color={colors.onSurfaceSecondary} />
              </Pressable>
            </View>
            {photo.loading ? (
              <ActivityIndicator size="large" color={colors.brandPrimary} style={{ marginVertical: 48 }} />
            ) : photo.b64 ? (
              <Image source={{ uri: `data:image/jpeg;base64,${photo.b64}` }} style={photoStyles.img} resizeMode="contain" />
            ) : (
              <View style={photoStyles.noPhoto}>
                <Ionicons name="camera-outline" size={34} color={colors.onSurfaceTertiary} />
                <Text style={photoStyles.noPhotoTxt}>No photo captured for this punch.</Text>
              </View>
            )}
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <View style={styles.legendItem}>
      <View style={[styles.legendSwatch, { backgroundColor: color }]} />
      <Text style={styles.legendTxt}>{label}</Text>
    </View>
  );
}

function statusBg(s: DaySummary["status"]): string {
  switch (s) {
    case "present": return "#DCFCE7";
    case "half":    return "#FEF3C7";
    case "absent":  return "#FEE2E2";
    case "weekend": return colors.surfaceSecondary;
    case "future":  return "transparent";
  }
}
function statusFg(s: DaySummary["status"]): string {
  switch (s) {
    case "present": return "#166534";
    case "half":    return "#B45309";
    case "absent":  return "#B91C1C";
    case "weekend": return colors.onSurfaceTertiary;
    case "future":  return colors.onSurfaceTertiary;
  }
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { fontSize: type.xl, color: colors.onSurface, fontWeight: "700" },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xl },

  monthBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    paddingVertical: 10, paddingHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  arrowBtn: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface,
  },
  arrowBtnDisabled: { opacity: 0.4 },
  monthCenter: { alignItems: "center", flex: 1 },
  monthTxt: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  monthSub: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },

  kpiRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.sm },
  kpi: {
    flex: 1, borderRadius: radius.md, paddingVertical: 12,
    alignItems: "center", justifyContent: "center",
  },
  kpiValue: { color: colors.onBrandTertiary, fontSize: 22, fontWeight: "800" },
  kpiLabel: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 2, fontWeight: "600" },

  totalCard: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandTertiary, borderRadius: radius.md,
    paddingVertical: 10, paddingHorizontal: 12,
    marginBottom: spacing.md,
  },
  totalTxt: { color: colors.onSurface, fontSize: type.sm },
  totalStrong: { fontWeight: "800", color: colors.brandPrimary },

  weekRow: {
    flexDirection: "row",
    marginBottom: 6,
  },
  weekLbl: {
    flex: 1,
    textAlign: "center",
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.5,
  },

  grid: { flexDirection: "column" },
  weekLine: { flexDirection: "row" },
  cell: {
    flex: 1,
    aspectRatio: 1,
    padding: 2,
  },
  dayCell: {
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "transparent",
  },
  dayCellSelected: {
    borderColor: colors.brandPrimary,
    borderWidth: 2,
  },
  dayCellToday: {
    borderColor: colors.cta,
    borderWidth: 2,
  },
  dayNum: { fontSize: 14, fontWeight: "700" },
  dayMeta: { fontSize: 9, fontWeight: "600", marginTop: 2 },
  dayMetaSpacer: { height: 11 },

  legendRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "center",
    gap: 12,
    marginTop: spacing.md,
    marginBottom: spacing.md,
  },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  legendSwatch: { width: 10, height: 10, borderRadius: 5 },
  legendTxt: { color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "600" },

  detail: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
    marginTop: spacing.md,
  },
  detailTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "700", marginBottom: 8 },
  detailRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 8 },
  detailPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 999,
  },
  detailPillTxt: { color: colors.onBrandTertiary, fontSize: 11, fontWeight: "600" },
  detailEmpty: { color: colors.onSurfaceTertiary, fontSize: type.sm, textAlign: "center", marginTop: 8 },
  detailItem: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.surface,
    borderRadius: radius.sm,
    borderWidth: 1, borderColor: colors.border,
    paddingVertical: 8, paddingHorizontal: 10,
    marginTop: 6,
  },
  detailIcon: {
    width: 30, height: 30, borderRadius: 15,
    alignItems: "center", justifyContent: "center",
  },
  detailItemTitle: { color: colors.onSurface, fontSize: type.sm, fontWeight: "700" },
  detailItemSub: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 1 },
  detailItemMethod: { color: colors.onSurfaceTertiary, fontSize: 11, textTransform: "capitalize" },
});

// Iter 97 — punch selfie viewer styles.
const photoStyles = StyleSheet.create({
  iconBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.brandTertiary,
  },
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  box: {
    width: "100%",
    maxWidth: 380,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  boxHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  boxTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800" },
  img: { width: "100%", height: 340, borderRadius: radius.sm, backgroundColor: "#111" },
  noPhoto: { alignItems: "center", paddingVertical: 40, gap: 8 },
  noPhotoTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm, textAlign: "center" },
});
