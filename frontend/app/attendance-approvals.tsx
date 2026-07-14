import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Alert,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing, type } from "@/src/theme";

type Row = {
  user_id: string;
  name: string;
  employee_code?: string | null;
  email?: string | null;
  phone?: string | null;
  company_id?: string | null;
  company_name?: string | null;
  distance_m: number;
  geofence_radius_m: number;
  last_seen_at: string;
  last_location_lat: number;
  last_location_lng: number;
  punches_today: number;
};

type Payload = {
  date: string;
  not_punched_in: Row[];
  not_punched_out: Row[];
};

type Kind = "in" | "out";

function fmtRelative(iso?: string | null): string {
  if (!iso) return "—";
  try {
    const then = new Date(iso).getTime();
    const now = Date.now();
    const diff = Math.max(0, now - then);
    const min = Math.round(diff / 60000);
    if (min < 1) return "just now";
    if (min < 60) return `${min} min ago`;
    const h = Math.round(min / 60);
    if (h < 24) return `${h} hr ago`;
    return new Date(iso).toLocaleString();
  } catch {
    return String(iso);
  }
}

export default function AttendanceApprovalsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [tab, setTab] = useState<Kind>("in");
  const [data, setData] = useState<Payload | null>(null);
  const [companies, setCompanies] = useState<any[]>([]);
  const [companyFilter, setCompanyFilter] = useState<string | "all">("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [approving, setApproving] = useState<string | null>(null);

  const isSuper = user?.role === "super_admin";
  const isAdmin = user?.role === "company_admin" || isSuper;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q =
        isSuper && companyFilter !== "all"
          ? `?company_id=${companyFilter}`
          : "";
      const r = await api<Payload>(
        `/admin/attendance/present-not-punched${q}`,
      );
      setData(r);
    } catch (e: any) {
      const msg = e?.message || "Failed to load report";
      if (Platform.OS === "web") {
         
        window.alert(msg);
      } else {
        Alert.alert("Report", msg);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [companyFilter, isSuper]);

  useEffect(() => {
    if (isSuper && companies.length === 0) {
      api<{ companies: any[] }>("/companies")
        .then((r) => setCompanies(r.companies || []))
        .catch(() => {});
    }
  }, [isSuper, companies.length]);

  useEffect(() => {
    load();
  }, [load]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const doApprove = async (row: Row, kind: Kind) => {
    setApproving(row.user_id);
    try {
      await api("/admin/attendance/approve-punch", {
        method: "POST",
        body: { user_id: row.user_id, kind },
      });
      // Optimistic — remove the row from local state immediately
      setData((d) => {
        if (!d) return d;
        if (kind === "in") {
          return {
            ...d,
            not_punched_in: d.not_punched_in.filter(
              (x) => x.user_id !== row.user_id,
            ),
          };
        }
        return {
          ...d,
          not_punched_out: d.not_punched_out.filter(
            (x) => x.user_id !== row.user_id,
          ),
        };
      });
      // Then re-fetch to ensure consistency (row might move to the other list)
      load();
    } catch (e: any) {
      const msg = e?.message || "Approval failed";
      if (Platform.OS === "web") {
         
        window.alert(msg);
      } else {
        Alert.alert("Approval failed", msg);
      }
    } finally {
      setApproving(null);
    }
  };

  const confirmApprove = (row: Row, kind: Kind) => {
    const label = kind === "in" ? "Punch-In" : "Punch-Out";
    const message =
      `Approve ${label} for ${row.name} (${row.employee_code || "—"})?\n\n` +
      `They are ${Math.round(row.distance_m)}m from the office. ` +
      `A ${label.toLowerCase()} record will be created on their behalf.`;
    if (Platform.OS === "web") {
       
      if (window.confirm(message)) doApprove(row, kind);
      return;
    }
    Alert.alert(
      `Approve ${label}`,
      message,
      [
        { text: "Cancel", style: "cancel" },
        { text: `Approve ${label}`, style: "default", onPress: () => doApprove(row, kind) },
      ],
    );
  };

  const list = useMemo(() => {
    if (!data) return [];
    return tab === "in" ? data.not_punched_in : data.not_punched_out;
  }, [data, tab]);

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]}>
          <View style={styles.header}>
            <Pressable onPress={() => router.back()} hitSlop={8}>
              <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
            </Pressable>
            <Text style={styles.h1}>Attendance approvals</Text>
            <View style={{ width: 26 }} />
          </View>
        </SafeAreaView>
        <View style={styles.forbCenter}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbTitle}>Admins only</Text>
        </View>
      </View>
    );
  }

  const inCount = data?.not_punched_in?.length ?? 0;
  const outCount = data?.not_punched_out?.length ?? 0;

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Attendance approvals</Text>
          <Pressable onPress={() => { setRefreshing(true); load(); }} hitSlop={8}>
            <Ionicons name="refresh" size={22} color={colors.onSurface} />
          </Pressable>
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
        {/* Intro card */}
        <View style={styles.introCard}>
          <View style={styles.introIcon}>
            <Ionicons name="location" size={20} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.introTitle}>Present but not punched</Text>
            <Text style={styles.introSub}>
              Employees whose last known location is inside the office
              geofence but who haven&apos;t punched-in (or out) yet today. Approve
              to create the punch on their behalf.
            </Text>
          </View>
        </View>

        {/* Super admin company filter */}
        {isSuper && (
          <View style={{ marginBottom: spacing.md }}>
            <CompanyPicker
              testID="approvals-company-picker"
              value={companyFilter}
              onChange={setCompanyFilter}
              companies={companies}
              label=""
              compact={false}
            />
          </View>
        )}

        {/* Tabs */}
        <View style={styles.tabBar}>
          <TabBtn
            active={tab === "in"}
            label="Not punched-in"
            count={inCount}
            onPress={() => setTab("in")}
            testID="tab-not-in"
          />
          <TabBtn
            active={tab === "out"}
            label="Not punched-out"
            count={outCount}
            onPress={() => setTab("out")}
            testID="tab-not-out"
          />
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
        ) : list.length === 0 ? (
          <View style={styles.empty} testID="approvals-empty">
            <Ionicons
              name={tab === "in" ? "checkmark-done-circle-outline" : "log-out-outline"}
              size={40}
              color={colors.onSurfaceTertiary}
            />
            <Text style={styles.emptyTitle}>
              {tab === "in"
                ? "Everyone in-office has punched in ✓"
                : "Nobody is pending a punch-out ✓"}
            </Text>
            <Text style={styles.emptySub}>
              Employees appear here only if their app has pinged a location
              within the last hour and they&apos;re inside the office geofence.
            </Text>
          </View>
        ) : (
          list.map((row) => (
            <RowCard
              key={row.user_id}
              row={row}
              kind={tab}
              busy={approving === row.user_id}
              onApprove={() => confirmApprove(row, tab)}
              showCompany={isSuper}
            />
          ))
        )}

        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

function TabBtn({
  active, label, count, onPress, testID,
}: {
  active: boolean; label: string; count: number; onPress: () => void; testID?: string;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={[styles.tabBtn, active && styles.tabBtnActive]}
      testID={testID}
    >
      <Text style={[styles.tabTxt, active && styles.tabTxtActive]}>{label}</Text>
      <View style={[styles.tabPill, active && styles.tabPillActive]}>
        <Text style={[styles.tabPillTxt, active && styles.tabPillTxtActive]}>
          {count}
        </Text>
      </View>
    </Pressable>
  );
}

function RowCard({
  row, kind, busy, onApprove, showCompany,
}: {
  row: Row;
  kind: Kind;
  busy?: boolean;
  onApprove: () => void;
  showCompany?: boolean;
}) {
  const insideStr = `${Math.round(row.distance_m)}m of ${row.geofence_radius_m}m`;
  return (
    <View style={styles.card} testID={`row-${row.user_id}`}>
      <View style={styles.cardHead}>
        <View style={styles.avatar}>
          <Text style={styles.avatarTxt}>
            {(row.name || "?").slice(0, 1).toUpperCase()}
          </Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.name}>{row.name}</Text>
          <Text style={styles.meta}>
            {row.employee_code || "—"}
            {showCompany && row.company_name ? ` · ${row.company_name}` : ""}
          </Text>
        </View>
        <View style={styles.distancePill}>
          <Ionicons name="navigate" size={11} color={colors.onBrandTertiary} />
          <Text style={styles.distanceTxt}>{insideStr}</Text>
        </View>
      </View>

      <View style={styles.cardMeta}>
        <View style={styles.metaRow}>
          <Ionicons name="time-outline" size={13} color={colors.onSurfaceTertiary} />
          <Text style={styles.metaTxt}>
            Last seen {fmtRelative(row.last_seen_at)}
          </Text>
        </View>
        {row.punches_today > 0 && (
          <View style={styles.metaRow}>
            <Ionicons name="finger-print" size={13} color={colors.onSurfaceTertiary} />
            <Text style={styles.metaTxt}>
              {row.punches_today} punch{row.punches_today > 1 ? "es" : ""} earlier today
            </Text>
          </View>
        )}
      </View>

      <Pressable
        onPress={onApprove}
        disabled={busy}
        style={[
          styles.approveBtn,
          kind === "out" && { backgroundColor: colors.warning || "#B45309" },
          busy && { opacity: 0.7 },
        ]}
        testID={`approve-${kind}-${row.user_id}`}
      >
        {busy ? (
          <ActivityIndicator size="small" color="#fff" />
        ) : (
          <>
            <Ionicons
              name={kind === "in" ? "log-in-outline" : "log-out-outline"}
              size={16}
              color="#fff"
            />
            <Text style={styles.approveTxt}>
              Approve Punch-{kind === "in" ? "In" : "Out"}
            </Text>
          </>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { fontSize: type.lg, color: colors.onSurface, fontWeight: "700", flex: 1, textAlign: "center" },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xl },

  introCard: {
    flexDirection: "row",
    gap: 10,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  introIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.surface,
    alignItems: "center", justifyContent: "center",
  },
  introTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  introSub: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 4, lineHeight: 17 },

  tabBar: {
    flexDirection: "row",
    gap: 6,
    backgroundColor: colors.surfaceSecondary,
    padding: 4,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
  },
  tabBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    borderRadius: 999,
  },
  tabBtnActive: { backgroundColor: colors.brandPrimary },
  tabTxt: { color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "700" },
  tabTxtActive: { color: colors.onCta },
  tabPill: {
    minWidth: 22, paddingHorizontal: 6,
    borderRadius: 999,
    backgroundColor: colors.surface,
    alignItems: "center", justifyContent: "center",
  },
  tabPillActive: { backgroundColor: colors.onCta },
  tabPillTxt: { color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "800" },
  tabPillTxtActive: { color: colors.brandPrimary },

  empty: { alignItems: "center", gap: 8, paddingVertical: 60, paddingHorizontal: spacing.lg },
  emptyTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "700", textAlign: "center" },
  emptySub: { color: colors.onSurfaceTertiary, fontSize: type.sm, textAlign: "center", lineHeight: 20 },

  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 10 },
  avatar: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  avatarTxt: { color: colors.onCta, fontSize: 16, fontWeight: "800" },
  name: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  meta: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 2 },
  distancePill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: 8, paddingVertical: 4,
    borderRadius: 999,
  },
  distanceTxt: { color: colors.onBrandTertiary, fontSize: 11, fontWeight: "700" },

  cardMeta: { marginTop: 10, gap: 4 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  metaTxt: { color: colors.onSurfaceTertiary, fontSize: 12 },

  approveBtn: {
    marginTop: spacing.md,
    backgroundColor: colors.success,
    borderRadius: radius.md,
    paddingVertical: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  approveTxt: { color: "#fff", fontSize: type.base, fontWeight: "700" },

  forbCenter: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  forbTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "600" },
});
