import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Modal,
  TextInput,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";
import { useFocusEffect } from "@react-navigation/native";

import { useOnRefresh } from "@/src/context/RefreshBusContext";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";
import DateField from "@/src/components/DateField";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

type Leave = {
  leave_id: string;
  user_name: string;
  user_email: string;
  leave_type: string;
  from_date: string;
  to_date: string;
  reason: string;
  status: "pending" | "approved" | "rejected";
  admin_comment?: string | null;
};

const TYPES = ["casual", "sick", "earned", "unpaid"] as const;

export default function LeavesScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const params = useLocalSearchParams<{ scope?: string }>();
  const isAdmin = user?.role !== "employee";

  const initialScope: "mine" | "all" =
    isAdmin && (params.scope === "all" || params.scope === "approvals")
      ? "all"
      : "mine";
  const [scope, setScope] = useState<"mine" | "all">(initialScope);
  const [leaves, setLeaves] = useState<Leave[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [type, setType] = useState<(typeof TYPES)[number]>("casual");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Iter 99 — employee's own CL/PL balance (current year).
  const [balance, setBalance] = useState<any>(null);
  useEffect(() => {
    if (!user || user.role !== "employee") return;
    api<any>("/leaves/balance").then(setBalance).catch(() => setBalance(null));
  }, [user]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ leaves: Leave[] }>(`/leaves?scope=${scope}`);
      setLeaves(r.leaves || []);
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => {
    load();
  }, [load]);
  // Iter 72 — Refresh on tab focus + on top-bar Refresh click so the
  // employee (or admin acting-as-employee) sees fresh leave data as
  // soon as they navigate back to the tab.
  useFocusEffect(useCallback(() => { load(); }, [load]));
  useOnRefresh(load);

  const submit = async () => {
    if (!from || !to || !reason) return;
    setSubmitting(true);
    try {
      await api("/leaves", {
        method: "POST",
        body: { leave_type: type, from_date: from, to_date: to, reason },
      });
      setOpen(false);
      setFrom("");
      setTo("");
      setReason("");
      setType("casual");
      await load();
    } catch (e: any) {
      // toast?
    } finally {
      setSubmitting(false);
    }
  };

  const decide = async (id: string, status: "approved" | "rejected") => {
    await api(`/leaves/${id}`, { method: "PATCH", body: { status } });
    await load();
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} testID="back">
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Leaves</Text>
          <View style={{ width: 26 }} />
        </View>
        {isAdmin && (
          <View style={styles.seg}>
            <Pressable
              onPress={() => setScope("mine")}
              style={[styles.segItem, scope === "mine" && styles.segItemActive]}
            >
              <Text style={[styles.segTxt, scope === "mine" && styles.segTxtActive]}>Mine</Text>
            </Pressable>
            <Pressable
              onPress={() => setScope("all")}
              style={[styles.segItem, scope === "all" && styles.segItemActive]}
            >
              <Text style={[styles.segTxt, scope === "all" && styles.segTxtActive]}>All requests</Text>
            </Pressable>
          </View>
        )}
      </SafeAreaView>

      <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll}>
        {/* Iter 99 — CL/PL balance for the logged-in employee */}
        {user?.role === "employee" && balance ? (
          <View style={styles.balCard} testID="leave-balance-card">
            <Text style={styles.balTitle}>My Leave Balance · {balance.year}</Text>
            {balance.cl_pl_applicable ? (
              <View style={styles.balRow}>
                <View style={styles.balBox}>
                  <Text style={styles.balBoxVal}>{balance.cl_balance}</Text>
                  <Text style={styles.balBoxLbl}>CL Balance</Text>
                  <Text style={styles.balBoxSub}>{balance.cl_taken} used of {balance.cl_allowed}</Text>
                </View>
                <View style={styles.balBox}>
                  <Text style={styles.balBoxVal}>{balance.pl_balance}</Text>
                  <Text style={styles.balBoxLbl}>PL Balance</Text>
                  <Text style={styles.balBoxSub}>{balance.pl_taken} used of {balance.pl_allowed}</Text>
                </View>
              </View>
            ) : (
              <Text style={styles.balNa}>CL/PL policy is not enabled for your firm yet.</Text>
            )}
          </View>
        ) : null}
        {loading ? (
          <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
        ) : leaves.length === 0 ? (
          <Text style={styles.empty}>No leave requests.</Text>
        ) : (
          leaves.map((l) => (
            <View key={l.leave_id} style={styles.card} testID={`leave-${l.leave_id}`}>
              <View style={styles.rowBetween}>
                <Text style={styles.leaveType}>{l.leave_type.toUpperCase()}</Text>
                <View style={[styles.statusChip, statusStyle(l.status)]}>
                  <Text style={statusTextStyle(l.status)}>{l.status}</Text>
                </View>
              </View>
              {scope === "all" && <Text style={styles.leaveWho}>{l.user_name} · {l.user_email}</Text>}
              <Text style={styles.leaveDates}>{l.from_date} → {l.to_date}</Text>
              <Text style={styles.leaveReason}>{l.reason}</Text>
              {isAdmin && scope === "all" && l.status === "pending" && (
                <View style={styles.actionsRow}>
                  <Pressable
                    testID={`approve-${l.leave_id}`}
                    style={[styles.actionBtn, { backgroundColor: colors.success }]}
                    onPress={() => decide(l.leave_id, "approved")}
                  >
                    <Text style={styles.actionTxt}>Approve</Text>
                  </Pressable>
                  <Pressable
                    testID={`reject-${l.leave_id}`}
                    style={[styles.actionBtn, { backgroundColor: colors.error }]}
                    onPress={() => decide(l.leave_id, "rejected")}
                  >
                    <Text style={styles.actionTxt}>Reject</Text>
                  </Pressable>
                </View>
              )}
              {l.admin_comment && <Text style={styles.comment}>Admin: {l.admin_comment}</Text>}
            </View>
          ))
        )}
        <View style={{ height: 100 }} />
      </KeyboardAwareScrollView>

      <Pressable testID="new-leave-fab" style={styles.fab} onPress={() => setOpen(true)}>
        <Ionicons name="add" size={24} color="#fff" />
        <Text style={styles.fabTxt}>Request</Text>
      </Pressable>

      <Modal transparent visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          style={styles.modalRoot}
        >
          <Pressable style={styles.backdrop} onPress={() => setOpen(false)} />
          <View style={styles.sheet}>
            <View style={styles.sheetGrip} />
            <Text style={styles.sheetTitle}>New leave request</Text>

            <Text style={styles.label}>Type</Text>
            <View style={styles.typeRow}>
              {TYPES.map((t) => (
                <Pressable
                  key={t}
                  onPress={() => setType(t)}
                  style={[styles.typeChip, type === t && styles.typeChipActive]}
                >
                  <Text style={[styles.typeChipTxt, type === t && styles.typeChipTxtActive]}>{t}</Text>
                </Pressable>
              ))}
            </View>

            <Text style={styles.label}>From date</Text>
            <DateField
              value={from}
              onChangeISO={setFrom}
              testID="from-input"
            />

            <Text style={styles.label}>To date</Text>
            <DateField
              value={to}
              onChangeISO={setTo}
              testID="to-input"
            />

            <Text style={styles.label}>Reason</Text>
            <TextInput
              testID="reason-input"
              value={reason}
              onChangeText={setReason}
              placeholder="Family function"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={[styles.input, { height: 80 }]}
              multiline
            />

            <Pressable
              testID="submit-leave"
              style={styles.submit}
              onPress={submit}
              disabled={submitting}
            >
              {submitting ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.submitTxt}>Submit request</Text>
              )}
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

function statusStyle(s: string) {
  if (s === "approved") return { backgroundColor: colors.success };
  if (s === "rejected") return { backgroundColor: colors.error };
  return { backgroundColor: colors.warning };
}
function statusTextStyle(s: string) {
  return { color: "#fff", fontSize: 11, fontWeight: "500" as const, letterSpacing: 0.5 };
}

const styles = StyleSheet.create({
  // Iter 99 — leave balance card
  balCard: {
    backgroundColor: colors.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 14,
    marginBottom: 12,
  },
  balTitle: { color: colors.onSurface, fontSize: 14, fontWeight: "800", marginBottom: 10 },
  balRow: { flexDirection: "row", gap: 10 },
  balBox: {
    flex: 1,
    backgroundColor: colors.brandTertiary,
    borderRadius: 12,
    alignItems: "center",
    paddingVertical: 12,
  },
  balBoxVal: { color: colors.brandPrimary, fontSize: 24, fontWeight: "900" },
  balBoxLbl: { color: colors.onSurface, fontSize: 12, fontWeight: "700", marginTop: 2 },
  balBoxSub: { color: colors.onSurfaceTertiary, fontSize: 10.5, marginTop: 2 },
  balNa: { color: colors.onSurfaceTertiary, fontSize: 12 },
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { fontSize: type.xl, color: colors.onSurface, fontWeight: "500" },
  seg: {
    marginHorizontal: spacing.xl, backgroundColor: colors.surfaceTertiary,
    borderRadius: radius.md, padding: 4, flexDirection: "row",
  },
  segItem: { flex: 1, paddingVertical: 8, alignItems: "center", borderRadius: radius.sm },
  segItemActive: { backgroundColor: colors.surfaceSecondary },
  segTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm, fontWeight: "500" },
  segTxtActive: { color: colors.onSurface },
  scroll: { padding: spacing.xl },
  empty: { color: colors.onSurfaceTertiary, textAlign: "center", marginTop: 60 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md,
  },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  leaveType: { color: colors.onSurface, fontSize: type.sm, fontWeight: "500", letterSpacing: 1 },
  statusChip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  leaveWho: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 4 },
  leaveDates: { color: colors.onSurface, fontSize: type.lg, fontWeight: "500", marginTop: 4 },
  leaveReason: { color: colors.onSurfaceSecondary, fontSize: type.base, marginTop: 4 },
  comment: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 8, fontStyle: "italic" },
  actionsRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  actionBtn: {
    flex: 1, paddingVertical: 10, borderRadius: radius.md,
    alignItems: "center", justifyContent: "center",
  },
  actionTxt: { color: "#fff", fontSize: type.base, fontWeight: "500" },
  fab: {
    position: "absolute", bottom: 24, right: 24,
    backgroundColor: colors.brandPrimary, borderRadius: radius.pill,
    paddingHorizontal: 18, paddingVertical: 14,
    flexDirection: "row", alignItems: "center", gap: 6,
    shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 10, shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  fabTxt: { color: "#fff", fontSize: type.base, fontWeight: "500" },
  modalRoot: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.35)" },
  sheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24,
    padding: spacing.xl, gap: 8,
  },
  sheetGrip: { alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: colors.borderStrong, marginBottom: spacing.md },
  sheetTitle: { fontSize: type.xl, color: colors.onSurface, fontWeight: "500", marginBottom: spacing.md },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: spacing.sm },
  typeRow: { flexDirection: "row", gap: 8, marginTop: 6 },
  typeChip: {
    paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.pill,
    backgroundColor: colors.surfaceTertiary,
  },
  typeChipActive: { backgroundColor: colors.brandPrimary },
  typeChipTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm, textTransform: "capitalize" },
  typeChipTxtActive: { color: "#fff" },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, color: colors.onSurface, fontSize: type.base, marginTop: 6,
    backgroundColor: colors.surfaceSecondary,
  },
  submit: {
    marginTop: spacing.lg, backgroundColor: colors.cta,
    paddingVertical: 14, borderRadius: radius.pill, alignItems: "center",
  },
  submitTxt: { color: "#fff", fontSize: type.lg, fontWeight: "500" },
});
