/**
 * Iter 104 — Shift Change Approvals (admins, Hospital firms).
 * Approving REQUIRES allotting the vacated shift to a replacement
 * employee who has not punched yet (mandatory per policy).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, TextInput,
  ActivityIndicator, Platform, Alert, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

function showMsg(m: string) {
  if (Platform.OS === "web") globalThis.alert(m); else Alert.alert("Shift approvals", m);
}

export default function ShiftApprovalsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  const isSuper = user?.role === "super_admin" || user?.role === "sub_admin";
  const [reqs, setReqs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<any>(null); // request being approved
  const [cands, setCands] = useState<any[]>([]);
  const [candLoading, setCandLoading] = useState(false);
  const [replacement, setReplacement] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = isSuper && globalCid ? `&company_id=${encodeURIComponent(globalCid)}` : "";
      const r = await api<{ requests: any[] }>(`/shift-change-requests?x=1${q}`);
      setReqs(r.requests || []);
    } catch { setReqs([]); }
    finally { setLoading(false); }
  }, [globalCid, isSuper]);
  useEffect(() => { load(); }, [load]);

  const openApprove = async (req: any) => {
    setModal(req); setReplacement(null); setNote(""); setCandLoading(true);
    try {
      const r = await api<{ candidates: any[] }>(`/admin/shift-change-requests/${req.request_id}/replacement-candidates`);
      setCands(r.candidates || []);
    } catch (e: any) { showMsg(e?.message || "Failed to load candidates"); setModal(null); }
    finally { setCandLoading(false); }
  };

  const decide = async (req: any, action: "approve" | "reject") => {
    if (action === "approve" && !replacement) {
      showMsg("Replacement employee is mandatory — select who will cover the vacated shift.");
      return;
    }
    setBusy(true);
    try {
      const r = await api<any>(`/admin/shift-change-requests/${req.request_id}/decide`, {
        method: "POST",
        body: { action, replacement_user_id: replacement, note: note.trim() },
      });
      showMsg(action === "approve"
        ? `Approved — ${r.replacement?.name} covers the ${r.replacement?.shift} shift. Both employees notified.`
        : "Request rejected.");
      setModal(null);
      await load();
    } catch (e: any) { showMsg(e?.message || "Action failed"); }
    finally { setBusy(false); }
  };

  const pending = reqs.filter((r) => r.status === "pending");
  const past = reqs.filter((r) => r.status !== "pending");

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 60 }}>
        <View style={styles.headRow}>
          <Pressable onPress={() => router.back()} style={styles.backBtn} testID="sa-back">
            <Ionicons name="chevron-back" size={20} color={colors.onSurface} />
          </Pressable>
          <View>
            <Text style={styles.title}>Shift Change Approvals</Text>
            <Text style={styles.subtitle}>Hospital shift swaps — replacement allotment is mandatory</Text>
          </View>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Pending ({pending.length})</Text>
          {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 16 }} />
            : pending.length === 0 ? <Text style={styles.hint}>No pending requests.</Text>
              : pending.map((r) => (
                <View key={r.request_id} style={styles.reqRow}>
                  <Ionicons name="swap-horizontal" size={17} color="#D97706" />
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontWeight: "800", color: colors.onSurface, fontSize: 13 }}>
                      {r.employee_name} ({r.employee_code || "—"})
                    </Text>
                    <Text style={styles.hint}>
                      {r.date}: {r.current_shift || "—"} → {r.requested_shift}
                      {r.reason ? ` · "${r.reason}"` : ""}
                    </Text>
                  </View>
                  <Pressable onPress={() => openApprove(r)} style={styles.approveBtn} testID={`sa-approve-${r.request_id}`}>
                    <Text style={{ color: "#fff", fontWeight: "800", fontSize: 12 }}>Approve…</Text>
                  </Pressable>
                  <Pressable onPress={() => decide(r, "reject")} style={styles.rejectBtn} testID={`sa-reject-${r.request_id}`}>
                    <Text style={{ color: "#DC2626", fontWeight: "800", fontSize: 12 }}>Reject</Text>
                  </Pressable>
                </View>
              ))}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>History</Text>
          {past.length === 0 ? <Text style={styles.hint}>Nothing decided yet.</Text> : past.slice(0, 30).map((r) => (
            <View key={r.request_id} style={styles.reqRow}>
              <Ionicons name={r.status === "approved" ? "checkmark-circle" : "close-circle"}
                size={16} color={r.status === "approved" ? "#16A34A" : "#DC2626"} />
              <View style={{ flex: 1 }}>
                <Text style={{ fontWeight: "700", color: colors.onSurface, fontSize: 12.5 }}>
                  {r.employee_name}: {r.date} · {r.current_shift || "—"} → {r.requested_shift}
                </Text>
                <Text style={styles.hint}>
                  {r.status.toUpperCase()}{r.replacement_name ? ` · covered by ${r.replacement_name}` : ""}
                </Text>
              </View>
            </View>
          ))}
        </View>
      </ScrollView>

      {/* Approve modal — mandatory replacement */}
      <Modal visible={!!modal} transparent animationType="fade" onRequestClose={() => setModal(null)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 8 }}>
              <Text style={[styles.cardTitle, { flex: 1 }]}>
                Allot the vacated {modal?.current_shift || "—"} shift
              </Text>
              <Pressable onPress={() => setModal(null)}><Ionicons name="close" size={20} color={colors.onSurfaceTertiary} /></Pressable>
            </View>
            <Text style={styles.hint}>
              {modal?.employee_name} moves to {modal?.requested_shift} on {modal?.date}.
              You MUST pick a replacement who can join the {modal?.current_shift || "vacated"} shift on time.
            </Text>
            {candLoading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 16 }} /> : (
              <ScrollView style={{ maxHeight: 260, marginTop: 8 }}>
                {cands.length === 0 ? (
                  <Text style={[styles.hint, { color: "#B45309" }]}>
                    No available employees (everyone has already punched for {modal?.date}).
                  </Text>
                ) : cands.map((c) => (
                  <Pressable key={c.user_id} onPress={() => setReplacement(c.user_id)}
                    style={styles.candRow} testID={`sa-cand-${c.user_id}`}>
                    <Ionicons name={replacement === c.user_id ? "radio-button-on" : "radio-button-off"}
                      size={17} color={replacement === c.user_id ? colors.brandPrimary : colors.onSurfaceTertiary} />
                    <Text style={{ fontSize: 12.5, color: colors.onSurface, flex: 1 }}>
                      {c.employee_code ? `${c.employee_code} · ` : ""}{c.name}
                    </Text>
                    <Text style={styles.hint}>{c.shift_name || "no shift"}</Text>
                  </Pressable>
                ))}
              </ScrollView>
            )}
            <TextInput style={styles.input} value={note} onChangeText={setNote}
              placeholder="Note (optional)" testID="sa-note" />
            <Pressable
              onPress={() => decide(modal, "approve")}
              disabled={busy || !replacement}
              style={[styles.primaryBtn, (busy || !replacement) && { opacity: 0.55 }]}
              testID="sa-confirm-approve"
            >
              {busy ? <ActivityIndicator color="#fff" /> : (
                <><Ionicons name="checkmark-done" size={16} color="#fff" />
                  <Text style={{ color: "#fff", fontWeight: "800", fontSize: 13.5 }}>
                    Approve & Allot Shift
                  </Text></>
              )}
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  headRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: spacing.md },
  backBtn: {
    width: 36, height: 36, borderRadius: 10, backgroundColor: colors.surface,
    alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.divider,
  },
  title: { ...type.h2, color: colors.onSurface, fontWeight: "800" },
  subtitle: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 2 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.divider, marginBottom: spacing.md, maxWidth: 760,
  },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  hint: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 3 },
  reqRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 10, borderBottomWidth: 1, borderColor: colors.divider,
  },
  approveBtn: {
    backgroundColor: "#16A34A", paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md,
  },
  rejectBtn: {
    borderWidth: 1, borderColor: "#FCA5A5", paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: radius.md, marginLeft: 6,
  },
  modalBg: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.45)",
    alignItems: "center", justifyContent: "center", padding: 20,
  },
  modalCard: {
    backgroundColor: colors.surface, borderRadius: 14, padding: 16,
    width: "100%", maxWidth: 520,
  },
  candRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 8, borderBottomWidth: 1, borderColor: colors.divider,
  },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 9, fontSize: 13,
    color: colors.onSurface, backgroundColor: colors.background, marginTop: 10,
  },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brandPrimary, paddingVertical: 12, borderRadius: radius.md, marginTop: 12,
  },
});
