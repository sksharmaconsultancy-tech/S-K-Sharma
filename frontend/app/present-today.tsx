import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing, type } from "@/src/theme";

type PunchEntry = {
  at: string;
  kind: "in" | "out";
  source?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  outside_note?: string | null;
  branch_id?: string | null;
  branch_name?: string | null;
  approved_by?: string | null;
};

type PresentUser = {
  user_id: string;
  name: string;
  employee_code?: string | null;
  company_id?: string | null;
  company_name?: string | null;
  first_in?: string | null;
  last_out?: string | null;
  still_in?: boolean;
  hours: number;
  punches: number;
  timeline?: PunchEntry[];
};

const fmtTime = (iso?: string | null) => {
  if (!iso) return "—";
  // Punch times are stored as wall-clock (machine/IST time) — show verbatim.
  const m = /T(\d{2}):(\d{2})/.exec(iso);
  return m ? `${m[1]}:${m[2]}` : "—";
};

const fmtHM = (h: number) => {
  const hh = Math.floor(h);
  const mm = Math.round((h - hh) * 60);
  if (hh <= 0 && mm <= 0) return "0h";
  if (hh <= 0) return `${mm}m`;
  if (mm <= 0) return `${hh}h`;
  return `${hh}h ${mm}m`;
};

export default function PresentTodayScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ company_id?: string }>();
  const { user } = useAuth();
  const [present, setPresent] = useState<PresentUser[]>([]);
  const [date, setDate] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [companyFilter, setCompanyFilter] = useState<string | "all">(
    (params.company_id as string) || "all",
  );
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const toggleExpanded = useCallback((uid: string) => {
    setExpanded((prev) => ({ ...prev, [uid]: !prev[uid] }));
  }, []);

  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q =
        isSuper && companyFilter !== "all"
          ? `?company_id=${companyFilter}`
          : "";
      const r = await api<{ date: string; present: PresentUser[] }>(
        `/admin/attendance/today${q}`,
      );
      setPresent(r.present || []);
      setDate(r.date);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [companyFilter, isSuper]);

  useEffect(() => {
    load();
  }, [load]);

  const stillIn = present.filter((p) => p.still_in).length;
  const totalHours = present.reduce((s, p) => s + (p.hours || 0), 0);

  return (
    <View style={styles.root}>
      <SafeAreaView
        edges={["top"]}
        style={{ backgroundColor: colors.surface }}
      >
        <View style={styles.header}>
          <Pressable
            onPress={() => router.back()}
            hitSlop={12}
            testID="present-back"
          >
            <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Present today</Text>
            <Text style={styles.subtitle}>
              {date ? new Date(date + "T00:00:00").toLocaleDateString() : ""}
            </Text>
          </View>
          <Pressable
            onPress={() => {
              setRefreshing(true);
              load();
            }}
            hitSlop={12}
            testID="present-refresh"
          >
            <Ionicons
              name="refresh"
              size={20}
              color={colors.brandPrimary}
            />
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
              testID="present-company-picker"
              value={companyFilter}
              onChange={setCompanyFilter}
              label=""
              compact={false}
            />
          </View>
        )}

        <View style={styles.summary}>
          <View style={styles.summaryCard} testID="present-count">
            <Text style={styles.summaryLabel}>PRESENT</Text>
            <Text style={styles.summaryValue}>{present.length}</Text>
          </View>
          <View style={styles.summaryCard} testID="still-in-count">
            <Text style={styles.summaryLabel}>STILL IN</Text>
            <Text style={styles.summaryValue}>{stillIn}</Text>
          </View>
          <View style={styles.summaryCard} testID="total-hours-today">
            <Text style={styles.summaryLabel}>TOTAL HOURS</Text>
            <Text style={styles.summaryValue}>{fmtHM(totalHours)}</Text>
          </View>
        </View>

        {loading ? (
          <ActivityIndicator
            style={{ marginTop: 40 }}
            color={colors.brandPrimary}
          />
        ) : present.length === 0 ? (
          <View style={styles.empty} testID="present-empty">
            <Ionicons
              name="people-outline"
              size={40}
              color={colors.onSurfaceTertiary}
            />
            <Text style={styles.emptyTitle}>Nobody has punched in yet</Text>
            <Text style={styles.emptyBody}>
              As employees start their shift, they will appear here with their
              in-time and out-time.
            </Text>
          </View>
        ) : (
          <View style={styles.list}>
            {present.map((p) => {
              const isOpen = !!expanded[p.user_id];
              const timeline = p.timeline || [];
              const cycles = Math.ceil((p.punches || 0) / 2);
              return (
              <Pressable
                key={p.user_id}
                onPress={() => toggleExpanded(p.user_id)}
                style={({ pressed }) => [
                  styles.row,
                  isOpen && styles.rowOpen,
                  pressed && { opacity: 0.85 },
                ]}
                testID={`present-row-${p.user_id}`}
                accessibilityRole="button"
                accessibilityLabel={`${p.name}, tap to ${
                  isOpen ? "collapse" : "expand"
                } punch timeline`}
              >
                <View style={styles.avatar}>
                  <Ionicons
                    name="person"
                    size={18}
                    color={colors.brandPrimary}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <View style={styles.rowTop}>
                    <Text style={styles.name} numberOfLines={1}>
                      {p.name}
                    </Text>
                    {p.still_in ? (
                      <View style={styles.pillIn}>
                        <View style={styles.dotIn} />
                        <Text style={styles.pillInTxt}>Still in</Text>
                      </View>
                    ) : (
                      <View style={styles.pillDone}>
                        <Ionicons
                          name="checkmark"
                          size={11}
                          color="#0F5B22"
                        />
                        <Text style={styles.pillDoneTxt}>Done</Text>
                      </View>
                    )}
                  </View>
                  <Text style={styles.meta} numberOfLines={1}>
                    {p.employee_code ? `${p.employee_code} · ` : ""}
                    {p.company_name || ""}
                    {cycles > 1 ? ` · ${cycles} in/out cycles` : ""}
                  </Text>
                  <View style={styles.timesRow}>
                    <View style={styles.timeCell}>
                      <Text style={styles.timeLabel}>IN</Text>
                      <Text style={styles.timeVal}>{fmtTime(p.first_in)}</Text>
                    </View>
                    <View style={styles.timeCell}>
                      <Text style={styles.timeLabel}>OUT</Text>
                      <Text style={styles.timeVal}>{fmtTime(p.last_out)}</Text>
                    </View>
                    <View style={styles.timeCell}>
                      <Text style={styles.timeLabel}>DUTY</Text>
                      <Text style={styles.timeVal}>{fmtHM(p.hours || 0)}</Text>
                    </View>
                  </View>

                  {/* Expand affordance */}
                  <View style={styles.expandRow}>
                    <Text style={styles.expandHint}>
                      {isOpen
                        ? "Hide timeline"
                        : `Show timeline · ${p.punches || 0} punch${
                            (p.punches || 0) === 1 ? "" : "es"
                          }`}
                    </Text>
                    <Ionicons
                      name={isOpen ? "chevron-up" : "chevron-down"}
                      size={16}
                      color={colors.onSurfaceSecondary}
                    />
                  </View>

                  {isOpen && (
                    <View
                      style={styles.timeline}
                      testID={`present-timeline-${p.user_id}`}
                    >
                      {timeline.length === 0 ? (
                        <Text style={styles.timelineEmpty}>
                          No individual punches available.
                        </Text>
                      ) : (
                        timeline.map((t, idx) => {
                          const isIn = t.kind === "in";
                          const isLast = idx === timeline.length - 1;
                          const src = (t.source || "").toLowerCase();
                          const srcLabel =
                            src === "auto"
                              ? "Auto"
                              : src === "approved"
                                ? "Admin approved"
                                : src === "manual"
                                  ? "Manual"
                                  : t.source || "";
                          return (
                            <View
                              key={`${p.user_id}-${idx}`}
                              style={styles.tRow}
                            >
                              <View style={styles.tRail}>
                                <View
                                  style={[
                                    styles.tDot,
                                    isIn ? styles.tDotIn : styles.tDotOut,
                                  ]}
                                />
                                {!isLast && <View style={styles.tLine} />}
                              </View>
                              <View style={styles.tBody}>
                                <View style={styles.tHeader}>
                                  <View
                                    style={[
                                      styles.kindPill,
                                      isIn
                                        ? styles.kindPillIn
                                        : styles.kindPillOut,
                                    ]}
                                  >
                                    <Text
                                      style={[
                                        styles.kindPillTxt,
                                        {
                                          color: isIn
                                            ? "#0F5B22"
                                            : "#7A1B00",
                                        },
                                      ]}
                                    >
                                      {isIn ? "IN" : "OUT"}
                                    </Text>
                                  </View>
                                  <Text style={styles.tTime}>
                                    {fmtTime(t.at)}
                                  </Text>
                                  {srcLabel ? (
                                    <View style={styles.srcPill}>
                                      <Text style={styles.srcPillTxt}>
                                        {srcLabel}
                                      </Text>
                                    </View>
                                  ) : null}
                                </View>
                                {t.branch_name ? (
                                  <Text style={styles.tMeta} numberOfLines={1}>
                                    <Ionicons
                                      name="business-outline"
                                      size={11}
                                      color={colors.onSurfaceTertiary}
                                    />{" "}
                                    {t.branch_name}
                                  </Text>
                                ) : null}
                                {t.outside_note ? (
                                  <Text
                                    style={[styles.tMeta, { color: colors.warning }]}
                                    numberOfLines={2}
                                  >
                                    <Ionicons
                                      name="alert-circle-outline"
                                      size={11}
                                      color={colors.warning}
                                    />{" "}
                                    {t.outside_note}
                                  </Text>
                                ) : null}
                                {typeof t.latitude === "number" &&
                                typeof t.longitude === "number" ? (
                                  <Text style={styles.tCoord} numberOfLines={1}>
                                    {t.latitude.toFixed(5)},{" "}
                                    {t.longitude.toFixed(5)}
                                  </Text>
                                ) : null}
                              </View>
                            </View>
                          );
                        })
                      )}
                    </View>
                  )}
                </View>
              </Pressable>
              );
            })}
          </View>
        )}
        <View style={{ height: 40 }} />
      </ScrollView>
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
  summary: {
    flexDirection: "row",
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  summaryCard: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    alignItems: "center",
  },
  summaryLabel: {
    color: colors.onSurfaceSecondary,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.6,
  },
  summaryValue: {
    color: colors.onSurface,
    fontSize: 22,
    fontWeight: "800",
    marginTop: 4,
  },
  empty: {
    alignItems: "center",
    padding: spacing.xl,
    marginTop: spacing.lg,
  },
  emptyTitle: {
    color: colors.onSurface,
    fontSize: type.lg,
    fontWeight: "700",
    marginTop: 12,
    textAlign: "center",
  },
  emptyBody: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 6,
    textAlign: "center",
    lineHeight: 20,
  },
  list: { gap: spacing.md },
  row: {
    flexDirection: "row",
    gap: 12,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  rowTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  name: {
    flex: 1,
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "700",
  },
  meta: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    marginTop: 2,
  },
  timesRow: {
    flexDirection: "row",
    marginTop: 8,
    gap: 12,
  },
  timeCell: {
    flex: 1,
    backgroundColor: colors.background,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  timeLabel: {
    color: colors.onSurfaceTertiary,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 0.5,
  },
  timeVal: {
    color: colors.onSurface,
    fontSize: type.sm,
    fontWeight: "700",
    marginTop: 2,
  },
  pillIn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#FFF6E5",
    borderRadius: 20,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  dotIn: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.warning,
  },
  pillInTxt: {
    color: "#7A4A00",
    fontSize: 10,
    fontWeight: "800",
  },
  pillDone: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    backgroundColor: "#E7F5EA",
    borderRadius: 20,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  pillDoneTxt: {
    color: "#0F5B22",
    fontSize: 10,
    fontWeight: "800",
  },
  rowOpen: {
    borderWidth: 1,
    borderColor: colors.brandPrimary,
  },
  expandRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 10,
    paddingTop: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.divider,
  },
  expandHint: {
    color: colors.onSurfaceSecondary,
    fontSize: 11,
    fontWeight: "700",
  },
  timeline: {
    marginTop: 12,
    gap: 10,
  },
  timelineEmpty: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    fontStyle: "italic",
  },
  tRow: {
    flexDirection: "row",
    gap: 10,
  },
  tRail: {
    width: 14,
    alignItems: "center",
  },
  tDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginTop: 4,
  },
  tDotIn: { backgroundColor: "#22A65A" },
  tDotOut: { backgroundColor: "#E85D2F" },
  tLine: {
    flex: 1,
    width: 2,
    backgroundColor: colors.divider,
    marginTop: 2,
    marginBottom: 2,
  },
  tBody: {
    flex: 1,
    gap: 3,
    paddingBottom: 4,
  },
  tHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  kindPill: {
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  kindPillIn: { backgroundColor: "#E7F5EA" },
  kindPillOut: { backgroundColor: "#FDECE2" },
  kindPillTxt: {
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.5,
  },
  tTime: {
    color: colors.onSurface,
    fontSize: type.sm,
    fontWeight: "700",
  },
  srcPill: {
    backgroundColor: colors.background,
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  srcPillTxt: {
    color: colors.onSurfaceSecondary,
    fontSize: 10,
    fontWeight: "700",
  },
  tMeta: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
  },
  tCoord: {
    color: colors.onSurfaceTertiary,
    fontSize: 10,
    fontFamily: "monospace",
  },
});
