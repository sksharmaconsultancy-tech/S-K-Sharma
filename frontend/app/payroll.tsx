import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing, type } from "@/src/theme";

type Slip = {
  slip_id: string;
  employee_user_id: string;
  employee_name?: string;
  employee_email?: string;
  month: string;
  net: number;
  gross: number;
  status: "pending" | "paid";
};

export default function PayrollScreen() {
  const { user } = useAuth();
  const router = useRouter();

  const [tab, setTab] = useState<"pending" | "paid">("pending");
  const [slips, setSlips] = useState<Slip[]>([]);
  const [loading, setLoading] = useState(true);
  const [marking, setMarking] = useState<string | null>(null);
  const [companyFilter, setCompanyFilter] = useState<string | "all">("all");

  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ status: tab });
      if (isSuper && companyFilter !== "all") {
        params.set("company_id", companyFilter);
      }
      const r = await api<{ payslips: Slip[] }>(
        `/admin/payroll?${params.toString()}`,
      );
      setSlips(r.payslips || []);
    } finally { setLoading(false); }
  }, [tab, companyFilter, isSuper]);

  useEffect(() => { load(); }, [load]);

  const markPaid = async (id: string) => {
    setMarking(id);
    try {
      await api(`/payslips/${id}/mark-paid`, { method: "PATCH" });
      await load();
    } finally { setMarking(null); }
  };

  const isAdmin = user?.role === "company_admin" || user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
          <View style={styles.header}>
            <Pressable onPress={() => router.back()}>
              <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
            </Pressable>
            <Text style={styles.h1}>Payroll</Text>
            <View style={{ width: 26 }} />
          </View>
        </SafeAreaView>
        <View style={styles.forbidden}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbTitle}>Admins only</Text>
        </View>
      </View>
    );
  }

  const totalPending = slips.reduce((s, x) => s + Number(x.net || 0), 0);

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Payroll</Text>
          <View style={{ width: 26 }} />
        </View>
        <View style={styles.seg}>
          <Pressable
            testID="seg-pending"
            onPress={() => setTab("pending")}
            style={[styles.segItem, tab === "pending" && styles.segItemActive]}
          >
            <Text style={[styles.segTxt, tab === "pending" && styles.segTxtActive]}>
              Pending
            </Text>
          </Pressable>
          <Pressable
            testID="seg-paid"
            onPress={() => setTab("paid")}
            style={[styles.segItem, tab === "paid" && styles.segItemActive]}
          >
            <Text style={[styles.segTxt, tab === "paid" && styles.segTxtActive]}>
              Paid
            </Text>
          </Pressable>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {isSuper && (
          <View style={{ marginBottom: spacing.md }}>
            <CompanyPicker
              testID="payroll-company-picker"
              value={companyFilter}
              onChange={setCompanyFilter}
              label=""
              compact={false}
            />
          </View>
        )}
        <View style={styles.summary}>
          <View>
            <Text style={styles.summaryLabel}>
              {tab === "pending" ? "TOTAL PENDING" : "TOTAL PAID"}
            </Text>
            <Text style={styles.summaryValue}>
              ₹{totalPending.toLocaleString()}
            </Text>
          </View>
          <View style={styles.summaryChip}>
            <Text style={styles.summaryCount}>{slips.length}</Text>
            <Text style={styles.summaryCountLbl}>records</Text>
          </View>
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
        ) : slips.length === 0 ? (
          <View style={styles.empty}>
            <View style={styles.emptyIcon}>
              <Ionicons name="cash-outline" size={26} color={colors.onBrandTertiary} />
            </View>
            <Text style={styles.emptyTitle}>
              {tab === "pending" ? "No pending salaries" : "No paid records yet"}
            </Text>
            <Text style={styles.emptyBody}>
              {tab === "pending"
                ? "Salary rows appear automatically for each employee once a month completes."
                : "Once you mark a pending salary as paid it will move here."}
            </Text>
          </View>
        ) : (
          slips.map((s) => (
            <View key={s.slip_id} style={styles.row} testID={`slip-${s.slip_id}`}>
              <View style={styles.rowIcon}>
                <Ionicons name="cash-outline" size={20} color={colors.onBrandTertiary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle}>
                  {s.employee_name || s.employee_email || s.employee_user_id}
                </Text>
                <Text style={styles.rowMeta}>
                  Month {s.month} · ₹{Number(s.net).toLocaleString()}
                </Text>
              </View>
              {s.status === "pending" ? (
                <Pressable
                  testID={`mark-paid-${s.slip_id}`}
                  style={styles.markBtn}
                  onPress={() => markPaid(s.slip_id)}
                  disabled={marking === s.slip_id}
                >
                  {marking === s.slip_id ? (
                    <ActivityIndicator color="#fff" size="small" />
                  ) : (
                    <Text style={styles.markTxt}>Mark paid</Text>
                  )}
                </Pressable>
              ) : (
                <View style={styles.paidPill}>
                  <Ionicons name="checkmark" size={12} color={colors.onSuccess} />
                  <Text style={styles.paidTxt}>Paid</Text>
                </View>
              )}
            </View>
          ))
        )}
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { fontSize: type.xl, color: colors.onSurface, fontWeight: "700" },
  seg: {
    marginHorizontal: spacing.lg, backgroundColor: colors.surfaceTertiary,
    borderRadius: radius.md, padding: 4, flexDirection: "row", marginBottom: spacing.md,
  },
  segItem: { flex: 1, paddingVertical: 8, alignItems: "center", borderRadius: radius.sm },
  segItemActive: { backgroundColor: colors.surfaceSecondary },
  segTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm, fontWeight: "600" },
  segTxtActive: { color: colors.onSurface },
  scroll: { paddingHorizontal: spacing.lg },
  summary: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.lg,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  summaryLabel: {
    color: "rgba(255,255,255,0.7)",
    fontSize: 11,
    letterSpacing: 1.5,
    fontWeight: "600",
  },
  summaryValue: { color: "#fff", fontSize: 28, fontWeight: "700", marginTop: 4 },
  summaryChip: {
    backgroundColor: "rgba(255,255,255,0.14)",
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: radius.md,
    alignItems: "center",
  },
  summaryCount: { color: "#fff", fontSize: 22, fontWeight: "700" },
  summaryCountLbl: { color: "rgba(255,255,255,0.7)", fontSize: 10, letterSpacing: 0.5 },
  row: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, marginBottom: 8,
  },
  rowIcon: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  rowTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "600" },
  rowMeta: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 2 },
  markBtn: {
    backgroundColor: colors.cta,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    borderRadius: radius.pill,
  },
  markTxt: { color: colors.onCta, fontSize: type.sm, fontWeight: "700" },
  paidPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.success,
    paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: radius.pill,
  },
  paidTxt: { color: colors.onSuccess, fontSize: 11, fontWeight: "700", letterSpacing: 0.3 },
  empty: { alignItems: "center", paddingVertical: 60, gap: 12 },
  emptyIcon: {
    width: 56, height: 56, borderRadius: 28,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  emptyTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "600" },
  emptyBody: {
    color: colors.onSurfaceTertiary, fontSize: type.base,
    textAlign: "center", paddingHorizontal: spacing.xl, lineHeight: 20,
  },
  forbidden: { alignItems: "center", paddingVertical: 80, gap: 12 },
  forbTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "600" },
});
