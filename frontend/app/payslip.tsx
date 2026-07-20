import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Row = {
  user_id: string;
  name: string;
  employee_code?: string | null;
  email?: string | null;
  present_days: number;
  absent_days: number;
  off_days: number;
  days_in_month: number;
  working_days: number;
  total_hours: number;
  salary_monthly?: number | null;
  gross: number;
};

type Payload = {
  year: number;
  month: number;
  month_key: string;
  days_in_month: number;
  off_days_total: number;
  rows: Row[];
  totals: { employees: number; gross_total: number; total_hours: number };
};

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function fmtCurrency(n: number | null | undefined): string {
  if (!n) return "₹0";
  try {
    return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
  } catch {
    return `₹${n.toFixed(2)}`;
  }
}

function fmtHours(n: number): string {
  const h = Math.floor(n);
  const m = Math.round((n - h) * 60);
  if (h <= 0) return `${m}m`;
  if (m <= 0) return `${h} h`;
  return `${h} h ${m}m`;
}

export default function PayslipScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const params = useLocalSearchParams<{
    user_id?: string;
    year?: string;
    month?: string;
  }>();

  const now = new Date();
  const targetYear = params.year ? Number(params.year) : now.getFullYear();
  const targetMonth = params.month ? Number(params.month) : now.getMonth() + 1;
  const targetUserId = params.user_id || user?.user_id;

  const [row, setRow] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const load = useCallback(async () => {
    if (!targetUserId) return;
    setLoading(true);
    setNotFound(false);
    try {
      const p = new URLSearchParams({
        year: String(targetYear),
        month: String(targetMonth),
      });
      const isAdmin =
        user?.role === "company_admin" || user?.role === "super_admin" ||
        (user?.role as string) === "sub_admin";
      const r = await api<Payload>(`/admin/payroll/run?${p.toString()}`);
      const found = r.rows.find((x) => x.user_id === targetUserId);
      if (found) {
        setRow(found);
      } else if (!isAdmin && user) {
        // Employee viewing their own payslip — synthesize from own attendance
        setRow({
          user_id: user.user_id,
          name: user.name || "You",
          employee_code: user.employee_code,
          email: user.email,
          present_days: 0,
          absent_days: 0,
          off_days: 0,
          days_in_month: 0,
          working_days: 0,
          total_hours: 0,
          salary_monthly: null,
          gross: 0,
        });
        setNotFound(true);
      } else {
        setNotFound(true);
      }
    } catch {
      setNotFound(true);
    } finally {
      setLoading(false);
    }
  }, [targetUserId, targetYear, targetMonth, user]);

  useEffect(() => { load(); }, [load]);

  const monthLabel = `${MONTHS[targetMonth - 1] || "?"} ${targetYear}`;

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Salary — {monthLabel}</Text>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
        ) : !row ? (
          <View style={styles.empty}>
            <Ionicons name="cash-outline" size={40} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyT}>No data for this month</Text>
          </View>
        ) : (
          <>
            {/* Employee identity */}
            <View style={styles.idCard}>
              <View style={styles.avatar}>
                <Text style={styles.avatarTxt}>
                  {(row.name || "?").slice(0, 1).toUpperCase()}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{row.name}</Text>
                {!!row.employee_code && (
                  <Text style={styles.sub}>ID: {row.employee_code}</Text>
                )}
                {!!row.email && <Text style={styles.sub}>{row.email}</Text>}
              </View>
            </View>

            {/* Gross highlight */}
            <View style={styles.grossCard}>
              <Text style={styles.grossLabel}>Gross salary for {monthLabel}</Text>
              <Text style={styles.grossValue}>{fmtCurrency(row.gross)}</Text>
              {row.salary_monthly ? (
                <Text style={styles.grossHint}>
                  Base {fmtCurrency(row.salary_monthly)} × {row.present_days}/
                  {row.working_days || 0} working days
                </Text>
              ) : (
                <Text style={styles.grossHint}>
                  Base monthly salary not set — ask your employer.
                </Text>
              )}
            </View>

            {/* Attendance summary */}
            <SectionHeader title="Attendance summary" />
            <View style={styles.grid}>
              <StatCard
                icon="checkmark-done-circle"
                color={colors.success}
                value={`${row.present_days}`}
                label="Present days"
              />
              <StatCard
                icon="close-circle"
                color={colors.error}
                value={`${row.absent_days}`}
                label="Absent days"
              />
              <StatCard
                icon="pause-circle"
                color={colors.onSurfaceTertiary}
                value={`${row.off_days}`}
                label="Weekly off"
              />
              <StatCard
                icon="time"
                color={colors.brandPrimary}
                value={fmtHours(row.total_hours)}
                label="Total hours"
              />
            </View>

            <View style={styles.breakdown}>
              <KVRow k="Days in month" v={`${row.days_in_month}`} />
              <KVRow k="Working days" v={`${row.working_days}`} />
              <KVRow k="Present days" v={`${row.present_days}`} />
              <KVRow k="Absent days" v={`${row.absent_days}`} />
              <KVRow k="Weekly off" v={`${row.off_days}`} />
              <View style={styles.divider} />
              <KVRow k="Total worked hours" v={fmtHours(row.total_hours)} />
              <KVRow
                k="Base monthly salary"
                v={row.salary_monthly ? fmtCurrency(row.salary_monthly) : "Not set"}
              />
              <KVRow
                k="Attendance ratio"
                v={
                  row.working_days > 0
                    ? `${((row.present_days / row.working_days) * 100).toFixed(1)}%`
                    : "—"
                }
              />
              <View style={styles.divider} />
              <KVRow k="Gross payable" v={fmtCurrency(row.gross)} strong />
            </View>

            <Text style={styles.footNote}>
              Gross = base_monthly_salary × (present_days / working_days).
              Deductions (PF, ESI, TDS, etc.) will be added in a future release.
            </Text>

            {notFound && (
              <View style={styles.warnBox}>
                <Ionicons name="information-circle-outline" size={16} color={colors.warning || "#B45309"} />
                <Text style={styles.warnTxt}>
                  Payroll for this month has not been processed yet.
                </Text>
              </View>
            )}
          </>
        )}

        <Text style={styles.punchLine}>&ldquo;Your Satisfaction is Our First Ambition&rdquo;</Text>
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

function SectionHeader({ title }: { title: string }) {
  return <Text style={styles.section}>{title}</Text>;
}

function KVRow({ k, v, strong }: { k: string; v: string; strong?: boolean }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowK}>{k}</Text>
      <Text style={[styles.rowV, strong && styles.rowVStrong]}>{v}</Text>
    </View>
  );
}

function StatCard({
  icon, color, value, label,
}: {
  icon: any; color: string; value: string; label: string;
}) {
  return (
    <View style={styles.stat}>
      <View style={[styles.statIcon, { backgroundColor: `${color}22` }]}>
        <Ionicons name={icon} size={16} color={color} />
      </View>
      <Text style={styles.statV}>{value}</Text>
      <Text style={styles.statL}>{label}</Text>
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

  empty: { alignItems: "center", paddingVertical: 60, gap: 8 },
  emptyT: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },

  idCard: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, marginBottom: spacing.md,
  },
  avatar: {
    width: 46, height: 46, borderRadius: 23,
    backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  avatarTxt: { color: "#fff", fontSize: 18, fontWeight: "800" },
  name: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  sub: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },

  grossCard: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.lg,
    padding: spacing.lg,
    marginBottom: spacing.md,
    alignItems: "center",
  },
  grossLabel: { color: "rgba(255,255,255,0.85)", fontSize: 12, fontWeight: "600", letterSpacing: 0.4 },
  grossValue: { color: "#fff", fontSize: 32, fontWeight: "800", marginTop: 4 },
  grossHint: { color: "rgba(255,255,255,0.75)", fontSize: 11, marginTop: 6, textAlign: "center" },

  section: { color: colors.onSurface, fontSize: type.base, fontWeight: "700", marginTop: 4, marginBottom: 8 },

  grid: {
    flexDirection: "row", flexWrap: "wrap",
    gap: 8, marginBottom: spacing.md,
  },
  stat: {
    width: "48%",
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
    alignItems: "flex-start",
  },
  statIcon: {
    width: 32, height: 32, borderRadius: 16,
    alignItems: "center", justifyContent: "center",
    marginBottom: 6,
  },
  statV: { color: colors.onSurface, fontSize: 18, fontWeight: "800" },
  statL: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2, fontWeight: "600" },

  breakdown: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 },
  rowK: { color: colors.onSurfaceSecondary, fontSize: 13 },
  rowV: { color: colors.onSurface, fontSize: 13, fontWeight: "600" },
  rowVStrong: { color: colors.brandPrimary, fontSize: 16, fontWeight: "800" },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 8 },

  footNote: { color: colors.onSurfaceTertiary, fontSize: 11, textAlign: "center", lineHeight: 16 },
  punchLine: {
    color: colors.brandPrimary, fontSize: 12.5, fontWeight: "700",
    fontStyle: "italic", textAlign: "center", marginTop: 18,
  },
  warnBox: {
    marginTop: spacing.md, flexDirection: "row", gap: 6,
    backgroundColor: "#FFF4E5",
    borderRadius: radius.md, padding: 10,
    alignItems: "center",
  },
  warnTxt: { color: "#B45309", fontSize: 12, fontWeight: "600", flex: 1 },
});
