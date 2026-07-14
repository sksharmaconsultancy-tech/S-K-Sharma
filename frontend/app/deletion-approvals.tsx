/**
 * Deletion Approvals (user directive).
 * Sub-admin firm force-deletes and salary-run deletions land here as
 * pending requests. The Super Admin approves (deletion executes) or
 * rejects (nothing is deleted — data keeps showing the same).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Req = {
  request_id: string;
  kind: "firm" | "salary_run" | "compliance_run";
  target_label: string;
  company_id?: string;
  force?: boolean;
  requested_by_name?: string;
  requested_by_role?: string;
  requested_at?: string;
  status: "pending" | "approved" | "rejected";
  decided_by_name?: string;
  decided_at?: string;
  reject_reason?: string;
};

const KIND_LABEL: Record<string, string> = {
  firm: "🏢 Firm (force delete)",
  salary_run: "💰 Actual Salary Run",
  compliance_run: "🛡 Compliance Salary Run",
};

export default function DeletionApprovalsScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [reqs, setReqs] = useState<Req[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ requests: Req[] }>("/admin/deletion-requests");
      setReqs(r.requests || []);
    } catch { setReqs([]); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const decide = async (r: Req, action: "approve" | "reject") => {
    const msg = action === "approve"
      ? `APPROVE deletion of "${r.target_label}"? The data will be permanently deleted.`
      : `REJECT this request? Nothing will be deleted — the data stays the same.`;
    if (Platform.OS === "web" && !window.confirm(msg)) return;
    setBusyId(r.request_id);
    try {
      await api(`/admin/deletion-requests/${r.request_id}/${action}`, { method: "POST", body: {} });
      await load();
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Action failed");
    } finally { setBusyId(null); }
  };

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role)) {
    return <Redirect href="/" />;
  }
  const isSuper = user.role === "super_admin";
  const pending = reqs.filter((r) => r.status === "pending");
  const decided = reqs.filter((r) => r.status !== "pending");

  const Card = ({ r }: { r: Req }) => (
    <View style={styles.reqCard}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Text style={styles.kind}>{KIND_LABEL[r.kind] || r.kind}</Text>
        <View style={[styles.badge, r.status === "pending" ? styles.badgeAmber
          : r.status === "approved" ? styles.badgeRed : styles.badgeGreen]}>
          <Text style={styles.badgeTxt}>
            {r.status === "pending" ? "Awaiting Super Admin" : r.status === "approved" ? "Approved · Deleted" : "Rejected · Data kept"}
          </Text>
        </View>
      </View>
      <Text style={styles.target}>{r.target_label}</Text>
      <Text style={styles.meta}>
        Requested by {r.requested_by_name || "—"} ({r.requested_by_role || "—"}) · {(r.requested_at || "").slice(0, 16).replace("T", " ")}
      </Text>
      {r.status !== "pending" ? (
        <Text style={styles.meta}>
          Decided by {r.decided_by_name || "—"} · {(r.decided_at || "").slice(0, 16).replace("T", " ")}
        </Text>
      ) : null}
      {isSuper && r.status === "pending" ? (
        <View style={{ flexDirection: "row", gap: 10, marginTop: 8 }}>
          <Pressable onPress={() => decide(r, "approve")} disabled={busyId === r.request_id}
            style={[styles.btn, { backgroundColor: "#B0002B" }]} testID={`da-approve-${r.request_id}`}>
            <Text style={styles.btnTxt}>Approve & Delete</Text>
          </Pressable>
          <Pressable onPress={() => decide(r, "reject")} disabled={busyId === r.request_id}
            style={[styles.btn, { backgroundColor: "#166534" }]} testID={`da-reject-${r.request_id}`}>
            <Text style={styles.btnTxt}>Reject (keep data)</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="da-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Deletion Approvals</Text>
        <Pressable onPress={() => void load()} hitSlop={10} testID="da-refresh">
          <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        {loading ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 30 }} />
        ) : (
          <>
            <Text style={styles.section}>Pending ({pending.length})</Text>
            {pending.length === 0 ? (
              <Text style={styles.dim}>No pending deletion requests.</Text>
            ) : pending.map((r) => <Card key={r.request_id} r={r} />)}
            {decided.length > 0 ? (
              <>
                <Text style={[styles.section, { marginTop: 18 }]}>History</Text>
                {decided.map((r) => <Card key={r.request_id} r={r} />)}
              </>
            ) : null}
          </>
        )}
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surfaceSecondary },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  headerTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800" },
  section: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  dim: { fontSize: 12, color: colors.onSurfaceTertiary, marginBottom: 10 },
  reqCard: {
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, padding: spacing.md, marginBottom: 10, gap: 3,
  },
  kind: { fontSize: 12.5, fontWeight: "800", color: colors.brandPrimary },
  target: { fontSize: 14, fontWeight: "800", color: colors.onSurface, marginTop: 2 },
  meta: { fontSize: 11, color: colors.onSurfaceTertiary },
  badge: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  badgeAmber: { backgroundColor: "#FEF3C7" },
  badgeRed: { backgroundColor: "#FEE2E2" },
  badgeGreen: { backgroundColor: "#DCFCE7" },
  badgeTxt: { fontSize: 10.5, fontWeight: "800", color: "#374151" },
  btn: { borderRadius: 8, paddingHorizontal: 14, paddingVertical: 9 },
  btnTxt: { color: "#FFF", fontWeight: "800", fontSize: 12 },
});
