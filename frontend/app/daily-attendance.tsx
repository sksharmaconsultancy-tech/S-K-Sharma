/**
 * Iter 148 — Daily Attendance (employer PWA dashboard).
 *
 * Date-wise view of every employee's punches, firm-wise:
 *   ◀ date ▶ navigation + firm picker → per-employee cards with
 *   IN/OUT punch chips, worked hours and Present/Absent status.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  Pressable,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { api } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, shadow } from "@/src/theme";

type Punch = { time: string; kind: "in" | "out"; machine: string };
type Row = {
  user_id: string;
  name: string;
  employee_code: string;
  company_name: string;
  status: "present" | "absent";
  punches: Punch[];
  first_in: string | null;
  last_out: string | null;
  worked_hrs: number;
  still_in: boolean;
};

function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

function niceDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return dt.toLocaleDateString("en-IN", {
    weekday: "short", day: "numeric", month: "short", year: "numeric",
  });
}

export default function DailyAttendance() {
  const { user } = useAuth();
  const router = useRouter();
  const { selectedCompanyId } = useSelectedCompany();

  const isAdmin =
    user?.role === "super_admin" ||
    (user?.role as string) === "sub_admin" ||
    user?.role === "company_admin";
  const canPickFirm = user?.role !== "company_admin";

  const [date, setDate] = useState<string>(isoDate(new Date()));
  const [companyId, setCompanyId] = useState<string | "all">(
    selectedCompanyId || "all",
  );
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<"all" | "present" | "absent">("all");

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const q = companyId && companyId !== "all" ? `&company_id=${companyId}` : "";
      const r = await api(`/admin/daily-attendance?date=${date}${q}`);
      setData(r);
    } catch (e: any) {
      setData({ rows: [], total: 0, present: 0, absent: 0, error: e?.message });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [date, companyId]);

  useEffect(() => { if (isAdmin) load(); }, [isAdmin, load]);

  const shiftDay = (delta: number) => {
    const [y, m, d] = date.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    dt.setDate(dt.getDate() + delta);
    setDate(isoDate(dt));
  };

  const today = isoDate(new Date());
  const rows: Row[] = useMemo(() => {
    const all: Row[] = data?.rows || [];
    if (filter === "present") return all.filter((r) => r.status === "present");
    if (filter === "absent") return all.filter((r) => r.status === "absent");
    return all;
  }, [data, filter]);

  if (!isAdmin) {
    return (
      <SafeAreaView style={styles.root}>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Admins only</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      {/* Header */}
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={styles.backBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Daily Attendance</Text>
        <View style={{ width: 38 }} />
      </View>

      {/* Date navigation */}
      <View style={styles.dateRow}>
        <Pressable onPress={() => shiftDay(-1)} style={styles.dateArrow} testID="da-prev">
          <Ionicons name="chevron-back" size={20} color={colors.brandPrimary} />
        </Pressable>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={styles.dateText}>{niceDate(date)}</Text>
          {date !== today && (
            <Pressable onPress={() => setDate(today)} hitSlop={6}>
              <Text style={styles.todayLink}>Jump to today</Text>
            </Pressable>
          )}
        </View>
        <Pressable
          onPress={() => shiftDay(1)}
          style={[styles.dateArrow, date >= today && { opacity: 0.3 }]}
          disabled={date >= today}
          testID="da-next"
        >
          <Ionicons name="chevron-forward" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>

      {/* Firm picker (super / sub admins) */}
      {canPickFirm && (
        <View style={styles.pickerWrap}>
          <CompanyPicker
            value={companyId}
            onChange={setCompanyId}
            label="Firm"
            compact
            testID="da-firm-picker"
          />
        </View>
      )}

      {/* Summary chips (tap to filter) */}
      <View style={styles.chipsRow}>
        {([
          ["all", `All ${data?.total ?? 0}`, colors.brandPrimary],
          ["present", `Present ${data?.present ?? 0}`, "#16a34a"],
          ["absent", `Absent ${data?.absent ?? 0}`, "#dc2626"],
        ] as const).map(([key, lbl, clr]) => (
          <Pressable
            key={key}
            onPress={() => setFilter(key)}
            style={[styles.chip, filter === key && { backgroundColor: clr, borderColor: clr }]}
            testID={`da-chip-${key}`}
          >
            <Text style={[styles.chipT, filter === key && { color: "#fff" }]}>{lbl}</Text>
          </Pressable>
        ))}
      </View>

      {loading ? (
        <ActivityIndicator style={{ marginTop: 48 }} color={colors.brandPrimary} />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(r) => r.user_id}
          contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); load(true); }}
            />
          }
          ListEmptyComponent={
            <View style={styles.center}>
              <Ionicons name="calendar-clear-outline" size={36} color={colors.onSurfaceTertiary} />
              <Text style={styles.emptyT}>
                {data?.error ? data.error : "No employees found for this filter."}
              </Text>
            </View>
          }
          renderItem={({ item }) => (
            <View style={[styles.card, item.status === "absent" && styles.cardAbsent]}>
              <View style={styles.cardTop}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.empName} numberOfLines={1}>
                    {item.name || "—"}
                    {item.employee_code ? (
                      <Text style={styles.empCode}>  ·  {item.employee_code}</Text>
                    ) : null}
                  </Text>
                  {!!item.company_name && (companyId === "all") && (
                    <Text style={styles.firmT} numberOfLines={1}>{item.company_name}</Text>
                  )}
                </View>
                {item.status === "present" ? (
                  <View style={[styles.badge, item.still_in ? styles.badgeIn : styles.badgeDone]}>
                    <Text style={styles.badgeT}>
                      {item.still_in ? "IN NOW" : `${item.worked_hrs} hrs`}
                    </Text>
                  </View>
                ) : (
                  <View style={[styles.badge, styles.badgeAbsent]}>
                    <Text style={[styles.badgeT, { color: "#b91c1c" }]}>ABSENT</Text>
                  </View>
                )}
              </View>

              {item.punches.length > 0 && (
                <View style={styles.punchRow}>
                  {item.punches.map((p, i) => (
                    <View
                      key={i}
                      style={[styles.punchChip, p.kind === "in" ? styles.pIn : styles.pOut]}
                    >
                      <Ionicons
                        name={p.kind === "in" ? "log-in-outline" : "log-out-outline"}
                        size={12}
                        color={p.kind === "in" ? "#15803d" : "#b91c1c"}
                      />
                      <Text style={[styles.punchT, { color: p.kind === "in" ? "#15803d" : "#b91c1c" }]}>
                        {p.kind.toUpperCase()} {p.time}
                      </Text>
                    </View>
                  ))}
                </View>
              )}
            </View>
          )}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  center: { alignItems: "center", marginTop: 60, gap: 10 },
  forbT: { color: colors.onSurfaceTertiary, fontWeight: "600" },
  emptyT: { color: colors.onSurfaceTertiary, textAlign: "center", paddingHorizontal: 24 },

  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 12, paddingVertical: 10,
  },
  backBtn: { width: 38, height: 38, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, textAlign: "center", fontSize: 17, fontWeight: "700", color: colors.onSurface },

  dateRow: {
    flexDirection: "row", alignItems: "center",
    marginHorizontal: 16, backgroundColor: colors.surfaceSecondary,
    borderRadius: radius?.lg ?? 14, borderWidth: 1, borderColor: colors.border,
    paddingVertical: 8, paddingHorizontal: 6,
  },
  dateArrow: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  dateText: { fontSize: 15, fontWeight: "700", color: colors.onSurface },
  todayLink: { fontSize: 11.5, color: colors.brandPrimary, fontWeight: "600", marginTop: 2 },

  pickerWrap: { marginHorizontal: 16, marginTop: 10 },

  chipsRow: { flexDirection: "row", gap: 8, marginHorizontal: 16, marginTop: 12 },
  chip: {
    paddingVertical: 7, paddingHorizontal: 14, borderRadius: 20,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  chipT: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },

  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius?.lg ?? 14,
    borderWidth: 1, borderColor: colors.border,
    padding: 12, marginBottom: 10, ...(shadow?.sm ?? {}),
  },
  cardAbsent: { opacity: 0.75 },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  empName: { fontSize: 14.5, fontWeight: "700", color: colors.onSurface },
  empCode: { fontSize: 12, fontWeight: "600", color: colors.onSurfaceTertiary },
  firmT: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 1 },

  badge: { borderRadius: 8, paddingVertical: 4, paddingHorizontal: 10 },
  badgeIn: { backgroundColor: "#dcfce7" },
  badgeDone: { backgroundColor: "#e0e7ff" },
  badgeAbsent: { backgroundColor: "#fee2e2" },
  badgeT: { fontSize: 11.5, fontWeight: "800", color: "#3730a3" },

  punchRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 10 },
  punchChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderRadius: 8, paddingVertical: 4, paddingHorizontal: 8, borderWidth: 1,
  },
  pIn: { backgroundColor: "#f0fdf4", borderColor: "#bbf7d0" },
  pOut: { backgroundColor: "#fef2f2", borderColor: "#fecaca" },
  punchT: { fontSize: 11.5, fontWeight: "700" },
});
