import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  RefreshControl, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Req = {
  request_id: string;
  contact_name: string;
  contact_mobile: string;
  contact_email?: string;
  company_name: string;
  address?: string;
  employee_count?: number;
  services_needed?: string;
  notes?: string;
  status: "pending" | "approved" | "rejected";
  submitted_by_email?: string;
  created_at: string;
};

export default function CompanyRequestsScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<Req[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  // Iter 88 — synchronous double-tap guard. setBusy is asynchronous so
  // two quick taps could both pass the `busy` state check and fire two
  // concurrent PATCHes, which used to bubble a `HTTP 500` from the
  // backend race. A ref updates immediately and blocks reliably.
  const inflightRef = useRef<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ requests: Req[] }>("/company-requests");
      setItems(r.requests || []);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (user?.role !== "super_admin") {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]}>
          <View style={styles.header}>
            <Pressable onPress={() => router.back()}>
              <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
            </Pressable>
            <Text style={styles.h1}>Company requests</Text>
            <View style={{ width: 26 }} />
          </View>
        </SafeAreaView>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbTitle}>Super admin only</Text>
        </View>
      </View>
    );
  }

  const decide = async (id: string, status: "approved" | "rejected") => {
    // Iter 88 — Reject double-taps instantly using a ref-guard. This
    // prevents two concurrent PATCH /company-requests/:id calls from the
    // same admin (Approve → tap again while spinner is up) which caused
    // the backend race that surfaced as "HTTP 500" on the mobile app.
    if (inflightRef.current.has(id)) return;
    inflightRef.current.add(id);
    setBusy(id);
    // Optimistic update — immediately flip the status locally so the row
    // moves out of "Pending" without waiting for the network round-trip.
    setItems((prev) =>
      prev.map((r) =>
        r.request_id === id ? { ...r, status } : r,
      ),
    );
    try {
      const res = await api<{ ok?: boolean; company_id?: string; user_id?: string }>(
        `/company-requests/${id}`,
        { method: "PATCH", body: { status } },
      );
      await load();
      // Iter 83 — surface success feedback so admins know the row moved.
      const msg = status === "approved"
        ? (res?.company_id
          ? `Approved. Company ${res.company_id} created.`
          : "Approved.")
        : "Rejected.";
      if (Platform.OS === "web") {
        window.alert(msg);
      } else {
        Alert.alert("Company request", msg);
      }
    } catch (e: any) {
      // Iter 83-fix — surface real error to the admin. Previously we
      // silently swallowed the error and just re-fetched, which made the
      // UI look like "nothing happened".
      await load();
      const errMsg = (e?.detail || e?.message || "Failed to update request").toString();
      if (Platform.OS === "web") {
        window.alert(errMsg);
      } else {
        Alert.alert("Company request", errMsg);
      }
    } finally {
      setBusy(null);
      inflightRef.current.delete(id);
    }
  };

  const pending = items.filter((x) => x.status === "pending");
  const decided = items.filter((x) => x.status !== "pending");

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Company requests</Text>
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
        {loading ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 40 }} />
        ) : items.length === 0 ? (
          <Text style={styles.empty}>No company requests yet.</Text>
        ) : (
          <>
            {pending.length > 0 && <Text style={styles.section}>Pending ({pending.length})</Text>}
            {pending.map((r) => (
              <Card key={r.request_id} r={r} busy={busy === r.request_id}
                    onApprove={() => decide(r.request_id, "approved")}
                    onReject={() => decide(r.request_id, "rejected")} />
            ))}
            {decided.length > 0 && <Text style={styles.section}>History</Text>}
            {decided.map((r) => (
              <Card key={r.request_id} r={r} readonly />
            ))}
          </>
        )}
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

function Card({
  r, busy, onApprove, onReject, readonly,
}: {
  r: Req; busy?: boolean; onApprove?: () => void; onReject?: () => void; readonly?: boolean;
}) {
  return (
    <View style={styles.card} testID={`req-${r.request_id}`}>
      <View style={styles.rowHead}>
        <Text style={styles.company}>{r.company_name}</Text>
        <View style={[styles.statusChip, statusStyle(r.status)]}>
          <Text style={styles.statusTxt}>{r.status}</Text>
        </View>
      </View>
      <Text style={styles.contact}>
        {r.contact_name} · {r.contact_mobile}
      </Text>
      {r.contact_email ? <Text style={styles.meta}>{r.contact_email}</Text> : null}
      {r.address ? <Text style={styles.meta}>{r.address}</Text> : null}
      <View style={styles.metaRow}>
        {r.employee_count ? <Text style={styles.metaChip}>{r.employee_count} employees</Text> : null}
        {r.services_needed ? <Text style={styles.metaChip}>{r.services_needed}</Text> : null}
      </View>
      {r.notes ? <Text style={styles.notes}>&ldquo;{r.notes}&rdquo;</Text> : null}
      <Text style={styles.date}>
        Submitted {new Date(r.created_at).toLocaleString()} by {r.submitted_by_email || "—"}
      </Text>
      {!readonly && (
        <View style={styles.actionRow}>
          <Pressable
            testID={`approve-${r.request_id}`}
            style={[styles.actBtn, { backgroundColor: colors.success }]}
            onPress={onApprove}
            disabled={busy}
          >
            {busy ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.actTxt}>Approve</Text>}
          </Pressable>
          <Pressable
            testID={`reject-${r.request_id}`}
            style={[styles.actBtn, { backgroundColor: colors.error }]}
            onPress={onReject}
            disabled={busy}
          >
            <Text style={styles.actTxt}>Reject</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

function statusStyle(s: string) {
  if (s === "approved") return { backgroundColor: colors.success };
  if (s === "rejected") return { backgroundColor: colors.error };
  return { backgroundColor: colors.cta };
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { fontSize: type.lg, color: colors.onSurface, fontWeight: "700" },
  scroll: { padding: spacing.lg },
  section: {
    color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: spacing.md,
    marginBottom: spacing.sm, letterSpacing: 0.5, textTransform: "uppercase",
  },
  empty: { color: colors.onSurfaceTertiary, textAlign: "center", marginTop: 40 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  forbTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "600" },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.md,
  },
  rowHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  company: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700", flex: 1 },
  statusChip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  statusTxt: { color: "#fff", fontSize: 10, fontWeight: "700", letterSpacing: 0.5, textTransform: "uppercase" },
  contact: { color: colors.onSurface, fontSize: type.base, marginTop: 6, fontWeight: "600" },
  meta: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 2 },
  metaRow: { flexDirection: "row", gap: 6, marginTop: 6, flexWrap: "wrap" },
  metaChip: {
    backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary,
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill,
    fontSize: 11, fontWeight: "500",
  },
  notes: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 8, fontStyle: "italic" },
  date: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 8 },
  actionRow: { flexDirection: "row", gap: 8, marginTop: spacing.md },
  actBtn: {
    flex: 1, paddingVertical: 10, borderRadius: radius.md,
    alignItems: "center", justifyContent: "center",
  },
  actTxt: { color: "#fff", fontSize: type.base, fontWeight: "600" },
});
