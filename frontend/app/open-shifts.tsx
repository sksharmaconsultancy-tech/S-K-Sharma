/**
 * Admin screen — Open shifts (missed OUT punches)
 *
 * Complements /attendance-approvals (which handles missed IN). Lists
 * employees who punched IN today but never punched OUT, ordered by how
 * long they've been open. Admin can:
 *   • Approve OUT punch on the employee's behalf (goes through the
 *     existing /admin/attendance/approve-punch endpoint).
 *   • Trigger the server-side auto-close job on-demand.
 */
import React, { useCallback, useEffect, useState } from "react";
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

type OpenShift = {
  user_id: string;
  name?: string | null;
  employee_code?: string | null;
  company_id?: string | null;
  company_name?: string | null;
  last_in_at: string;
  elapsed_hours: number;
  punch_count: number;
  will_auto_close: boolean;
  last_location_lat?: number | null;
  last_location_lng?: number | null;
  last_location_at?: string | null;
};

const fmtWhen = (iso?: string | null) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString([], {
      hour: "2-digit",
      minute: "2-digit",
      day: "2-digit",
      month: "short",
    });
  } catch {
    return iso;
  }
};

const fmtElapsed = (hours: number): string => {
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (h === 0) return `${m} min`;
  if (m === 0) return `${h} hr`;
  return `${h}h ${m}m`;
};

export default function OpenShiftsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const [items, setItems] = useState<OpenShift[]>([]);
  const [autoCloseAfter, setAutoCloseAfter] = useState(12);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [runningJob, setRunningJob] = useState(false);
  const [companyFilter, setCompanyFilter] = useState<string | "all">("all");

  const showMsg = (msg: string) => {
    if (Platform.OS === "web") window.alert(msg);
    else Alert.alert("Open shifts", msg);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q =
        isSuper && companyFilter !== "all"
          ? `?company_id=${companyFilter}`
          : "";
      const r = await api<{
        open_shifts: OpenShift[];
        count: number;
        auto_close_after_hours: number;
      }>(`/admin/attendance/open-shifts${q}`);
      setItems(r.open_shifts || []);
      setAutoCloseAfter(r.auto_close_after_hours || 12);
    } catch (e: any) {
      showMsg(e?.message || "Could not load open shifts.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [companyFilter, isSuper]);

  useEffect(() => {
    load();
  }, [load]);

  const approveOut = async (userId: string, name?: string | null) => {
    setBusy(userId);
    try {
      await api("/admin/attendance/approve-punch", {
        method: "POST",
        body: { user_id: userId, kind: "out", note: "Admin manual close" },
      });
      setItems((prev) => prev.filter((r) => r.user_id !== userId));
      showMsg(`OUT punch recorded for ${name || "employee"}.`);
    } catch (e: any) {
      showMsg(e?.message || "Could not approve punch.");
    } finally {
      setBusy(null);
    }
  };

  const triggerAutoClose = async () => {
    setRunningJob(true);
    try {
      const r = await api<{ closed: number; scanned: number }>(
        "/admin/attendance/auto-close",
        { method: "POST" },
      );
      showMsg(
        `Auto-close complete. Closed ${r.closed} of ${r.scanned} open shift${
          r.scanned === 1 ? "" : "s"
        }.`,
      );
      await load();
    } catch (e: any) {
      showMsg(e?.message || "Could not run auto-close.");
    } finally {
      setRunningJob(false);
    }
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8} testID="os-back">
            <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Open shifts</Text>
            <Text style={styles.subtitle}>
              Punched IN today but no OUT · auto-close after {autoCloseAfter}h
            </Text>
          </View>
          <Pressable
            onPress={() => {
              setRefreshing(true);
              load();
            }}
            hitSlop={8}
            testID="os-refresh"
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
              testID="os-company-picker"
              value={companyFilter}
              onChange={setCompanyFilter}
              label=""
              compact={false}
            />
          </View>
        )}

        <View style={styles.infoCard}>
          <Ionicons
            name="information-circle-outline"
            size={16}
            color={colors.brandPrimary}
          />
          <Text style={styles.infoTxt}>
            When an employee forgets to punch OUT (phone dead, app force-quit
            or they simply left), the server auto-closes the shift after{" "}
            <Text style={{ fontWeight: "800" }}>{autoCloseAfter}h</Text> or when
            their last known location leaves the geofence for 30+ min. You can
            also close manually below.
          </Text>
        </View>

        <Pressable
          style={[styles.runBtn, runningJob && { opacity: 0.6 }]}
          onPress={triggerAutoClose}
          disabled={runningJob}
          testID="os-run-auto-close"
        >
          {runningJob ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <Ionicons name="flash-outline" size={16} color="#fff" />
              <Text style={styles.runBtnTxt}>Run auto-close now</Text>
            </>
          )}
        </Pressable>

        {loading ? (
          <ActivityIndicator
            style={{ marginTop: 60 }}
            color={colors.brandPrimary}
          />
        ) : items.length === 0 ? (
          <View style={styles.empty} testID="os-empty">
            <Ionicons
              name="checkmark-done-circle-outline"
              size={42}
              color={colors.onSurfaceTertiary}
            />
            <Text style={styles.emptyT}>All shifts closed</Text>
            <Text style={styles.emptyS}>
              No employees are currently on an open shift.
            </Text>
          </View>
        ) : (
          items.map((r) => {
            const isBusy = busy === r.user_id;
            return (
              <View
                key={r.user_id}
                style={styles.card}
                testID={`os-row-${r.user_id}`}
              >
                <View style={styles.cardHead}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.name} numberOfLines={1}>
                      {r.name || "Unknown"}
                    </Text>
                    <Text style={styles.meta} numberOfLines={1}>
                      {r.employee_code ? `${r.employee_code} · ` : ""}
                      {r.company_name || ""}
                    </Text>
                  </View>
                  <View
                    style={[
                      styles.pill,
                      r.will_auto_close ? styles.pillWarn : styles.pillOk,
                    ]}
                  >
                    <Text
                      style={[
                        styles.pillTxt,
                        {
                          color: r.will_auto_close ? "#7A1B00" : "#0F5B22",
                        },
                      ]}
                    >
                      {fmtElapsed(r.elapsed_hours)}
                    </Text>
                  </View>
                </View>

                <View style={styles.rowLine}>
                  <Ionicons
                    name="log-in-outline"
                    size={13}
                    color={colors.onSurfaceTertiary}
                  />
                  <Text style={styles.rowTxt}>
                    IN at {fmtWhen(r.last_in_at)}
                  </Text>
                </View>
                {r.last_location_at ? (
                  <View style={styles.rowLine}>
                    <Ionicons
                      name="location-outline"
                      size={13}
                      color={colors.onSurfaceTertiary}
                    />
                    <Text style={styles.rowTxt} numberOfLines={1}>
                      Last ping {fmtWhen(r.last_location_at)}
                      {typeof r.last_location_lat === "number"
                        ? ` · ${r.last_location_lat.toFixed(4)}, ${(r.last_location_lng || 0).toFixed(4)}`
                        : ""}
                    </Text>
                  </View>
                ) : (
                  <View style={styles.rowLine}>
                    <Ionicons
                      name="alert-circle-outline"
                      size={13}
                      color={colors.warning}
                    />
                    <Text style={[styles.rowTxt, { color: colors.warning }]}>
                      No location shared — app may be force-quit.
                    </Text>
                  </View>
                )}

                <View style={styles.actionsRow}>
                  <Pressable
                    onPress={() => approveOut(r.user_id, r.name)}
                    disabled={isBusy}
                    style={[styles.actBtn, isBusy && { opacity: 0.6 }]}
                    testID={`os-close-${r.user_id}`}
                  >
                    {isBusy ? (
                      <ActivityIndicator color={colors.brandPrimary} />
                    ) : (
                      <>
                        <Ionicons
                          name="log-out-outline"
                          size={15}
                          color={colors.brandPrimary}
                        />
                        <Text style={styles.actBtnTxt}>Punch OUT now</Text>
                      </>
                    )}
                  </Pressable>
                </View>
              </View>
            );
          })
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
  infoCard: {
    flexDirection: "row",
    gap: 10,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  infoTxt: {
    flex: 1,
    color: colors.onBrandTertiary,
    fontSize: type.sm,
    lineHeight: 20,
  },
  runBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 8,
    marginBottom: spacing.lg,
  },
  runBtnTxt: {
    color: "#fff",
    fontSize: type.base,
    fontWeight: "800",
  },
  empty: { alignItems: "center", padding: spacing.xl, marginTop: spacing.md },
  emptyT: {
    color: colors.onSurface,
    fontSize: type.lg,
    fontWeight: "800",
    marginTop: 12,
  },
  emptyS: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 6,
    textAlign: "center",
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  cardHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginBottom: 6,
  },
  name: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  meta: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    marginTop: 2,
  },
  pill: {
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  pillOk: { backgroundColor: "#E7F5EA" },
  pillWarn: { backgroundColor: "#FDECE2" },
  pillTxt: {
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.5,
  },
  rowLine: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 4,
  },
  rowTxt: {
    flex: 1,
    color: colors.onSurfaceSecondary,
    fontSize: 12,
  },
  actionsRow: {
    flexDirection: "row",
    gap: 8,
    marginTop: 10,
  },
  actBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.surface,
  },
  actBtnTxt: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "800",
  },
});
