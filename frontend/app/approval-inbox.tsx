/**
 * Approval Inbox — RBAC Phase 3.
 * Pending requests routed to the caller (level approver), with
 * Approve / Reject / Hold / Return actions + full approval timeline.
 * Maker-checker: creators can never action their own request.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform, Alert, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { confirmYesNo } from "@/src/utils/confirm";
import { colors } from "@/src/theme";

const toast = (m: string) => (Platform.OS === "web" ? window.alert(m) : Alert.alert("Approvals", m));
const ST_COLORS: Record<string, string> = {
  pending: "#D97706", on_hold: "#7C3AED", approved: "#059669",
  rejected: "#DC2626", returned: "#64748B",
};
const inr = (v: any) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

export default function ApprovalInbox() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const role = user?.role as string;

  const [companyId, setCompanyId] = useState<string>(
    role === "company_admin" ? (user?.company_id || "") : (selectedCompanyId || ""));
  const [status, setStatus] = useState("pending");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [timeline, setTimeline] = useState<any>(null);

  // Follow the global active-firm picker.
  useEffect(() => {
    if (role !== "company_admin" && selectedCompanyId) setCompanyId(selectedCompanyId);
  }, [selectedCompanyId, role]);
  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    try {
      setData(await api(`/admin/approval-inbox?company_id=${companyId}&status=${status}`));
    } catch { setData(null); }
    finally { setLoading(false); }
  }, [companyId, status]);
  useEffect(() => { load(); }, [load]);

  const act = async (r: any, action: string) => {
    const confirmMsg: Record<string, string> = {
      approve: `Approve "${r.title}"?`, reject: `Reject "${r.title}"?`,
      hold: `Put "${r.title}" on hold?`, return: `Return "${r.title}" to the requester?`,
    };
    if (!(await confirmYesNo(confirmMsg[action]))) return;
    let remarks: string | undefined;
    if (action === "reject" || action === "return") {
      remarks = Platform.OS === "web" ? window.prompt("Remarks (mandatory):") || "" : "";
      if (!remarks) { toast("Remarks are mandatory."); return; }
    } else if (Platform.OS === "web") {
      remarks = window.prompt("Remarks (optional):") || undefined;
    }
    setBusy(true);
    try {
      await api(`/admin/approval-requests/${r.request_id}/action`, { method: "POST", body: { action, remarks } });
      toast("Done.");
      await load();
    } catch (e: any) { toast(e?.message || "Action failed"); }
    finally { setBusy(false); }
  };

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) return <Redirect href="/" />;

  const counts = data?.counts || {};
  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.hBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Approval Inbox</Text>
          <Text style={s.subtitle}>Multi-level approvals · maker-checker enforced</Text>
        </View>
        <Pressable onPress={load} hitSlop={10} style={s.hBtn}>
          <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={s.body}>
        {role !== "company_admin" ? (
          <View style={{ marginBottom: 12 }}>
            <CompanyPicker value={companyId} onChange={(v: any) => setCompanyId(v || "")} />
          </View>
        ) : null}
        {!companyId ? <Text style={s.muted}>Select a firm to see its approval inbox.</Text> : null}

        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 12 }}>
          <View style={{ flexDirection: "row", gap: 8 }}>
            {["pending", "on_hold", "approved", "rejected", "returned", "all"].map((k) => (
              <Pressable key={k} onPress={() => setStatus(k)} style={[s.chip, status === k && s.chipOn]} testID={`inbox-${k}`}>
                <Text style={[s.chipTxt, status === k && s.chipTxtOn]}>
                  {k === "all" ? "All" : k.replace("_", " ")}{counts[k] !== undefined ? ` (${counts[k]})` : ""}
                </Text>
              </Pressable>
            ))}
          </View>
        </ScrollView>

        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} /> : null}
        {!loading && companyId && (data?.requests || []).length === 0 ? (
          <View style={s.empty}>
            <Ionicons name="checkmark-done-circle-outline" size={38} color={colors.onSurfaceTertiary} />
            <Text style={s.muted}>Nothing waiting here.</Text>
          </View>
        ) : null}

        {(data?.requests || []).map((r: any) => {
          const c = ST_COLORS[r.status] || "#64748B";
          return (
            <View key={r.request_id} style={s.card} testID={`req-${r.request_id}`}>
              <View style={s.cardTop}>
                <View style={[s.modPill]}><Text style={s.modPillTxt}>{r.module.replace("_", " ").toUpperCase()}</Text></View>
                <Text style={s.reqTitle} numberOfLines={1}>{r.title}</Text>
                <View style={[s.stPill, { backgroundColor: `${c}18` }]}>
                  <Text style={[s.stPillTxt, { color: c }]}>{r.status.replace("_", " ").toUpperCase()}</Text>
                </View>
              </View>
              <Text style={s.meta}>
                By {r.requested_by_name} · {(r.created_at || "").slice(0, 16).replace("T", " ")}
                {r.pending_with ? ` · Level ${r.current_level}/${(r.levels || []).length} — pending with ${r.pending_with}` : ""}
              </Text>
              {r.summary?.amount ? (
                <Text style={s.sumLine}>
                  {r.summary.advance_type} · {inr(r.summary.amount)}
                  {r.summary.emi_amount ? ` · EMI ${inr(r.summary.emi_amount)}` : ""} · from {r.summary.start_month}
                </Text>
              ) : null}
              <View style={s.actions}>
                {r.can_action ? (
                  <>
                    <Pressable style={[s.actBtn, { backgroundColor: "#059669" }]} disabled={busy} onPress={() => act(r, "approve")} testID={`approve-${r.request_id}`}>
                      <Ionicons name="checkmark" size={13} color="#fff" /><Text style={s.actTxtW}>Approve</Text></Pressable>
                    <Pressable style={[s.actBtn, { backgroundColor: "#DC2626" }]} disabled={busy} onPress={() => act(r, "reject")} testID={`reject-${r.request_id}`}>
                      <Ionicons name="close" size={13} color="#fff" /><Text style={s.actTxtW}>Reject</Text></Pressable>
                    <Pressable style={[s.actBtnO]} disabled={busy} onPress={() => act(r, "hold")}>
                      <Text style={s.actTxtO}>Hold</Text></Pressable>
                    <Pressable style={[s.actBtnO]} disabled={busy} onPress={() => act(r, "return")}>
                      <Text style={s.actTxtO}>Return</Text></Pressable>
                  </>
                ) : r.status === "pending" || r.status === "on_hold" ? (
                  <Text style={s.muted}>
                    {r.requested_by === user?.user_id ? "You raised this — another approver must act (maker-checker)." : `Waiting for ${r.pending_with}.`}
                  </Text>
                ) : null}
                <Pressable style={s.actBtnO} onPress={() => setTimeline(r)} testID={`history-${r.request_id}`}>
                  <Text style={s.actTxtO}>View History</Text></Pressable>
              </View>
            </View>
          );
        })}
        <View style={{ height: 40 }} />
      </ScrollView>

      {/* Timeline modal */}
      <Modal transparent visible={!!timeline} animationType="fade" onRequestClose={() => setTimeline(null)}>
        <View style={s.modalRoot}>
          <Pressable style={s.backdrop} onPress={() => setTimeline(null)} />
          {timeline ? (
            <View style={s.modalCard}>
              <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 10 }}>
                <Text style={[s.reqTitle, { flex: 1 }]}>{timeline.title}</Text>
                <Pressable onPress={() => setTimeline(null)} hitSlop={10}>
                  <Ionicons name="close" size={22} color={colors.onSurfaceSecondary} /></Pressable>
              </View>
              <ScrollView>
                {(timeline.history || []).map((h: any, i: number) => (
                  <View key={i} style={s.tl}>
                    <View style={s.tlDot} />
                    <View style={{ flex: 1 }}>
                      <Text style={s.tlAction}>
                        {h.level ? `Level ${h.level} — ` : ""}{h.action.toUpperCase()} · {h.by_name}
                      </Text>
                      <Text style={s.tlMeta}>{(h.at || "").slice(0, 16).replace("T", " ")}{h.remarks ? ` · “${h.remarks}”` : ""}</Text>
                    </View>
                  </View>
                ))}
              </ScrollView>
            </View>
          ) : null}
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surfaceSecondary, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  hBtn: { width: 38, height: 38, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceTertiary },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 1 },
  body: { padding: 16, width: "100%", maxWidth: 900, alignSelf: "center" },
  muted: { fontSize: 12, color: colors.onSurfaceTertiary },
  chip: {
    paddingHorizontal: 12, height: 32, borderRadius: 16, backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center",
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "600", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  empty: { alignItems: "center", paddingVertical: 40, gap: 10 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 16, borderWidth: 1, borderColor: colors.border,
    padding: 14, marginBottom: 10,
  },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  modPill: { backgroundColor: "rgba(37,99,235,0.1)", borderRadius: 8, paddingHorizontal: 7, paddingVertical: 2 },
  modPillTxt: { fontSize: 9.5, fontWeight: "800", color: colors.brandPrimary },
  reqTitle: { flex: 1, fontSize: 13.5, fontWeight: "700", color: colors.onSurface, minWidth: 160 },
  stPill: { borderRadius: 8, paddingHorizontal: 7, paddingVertical: 2 },
  stPillTxt: { fontSize: 9.5, fontWeight: "800", letterSpacing: 0.4 },
  meta: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 4 },
  sumLine: { fontSize: 12, color: colors.onSurface, marginTop: 4, fontWeight: "600" },
  actions: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10, flexWrap: "wrap" },
  actBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, borderRadius: 10, paddingHorizontal: 12, height: 32,
  },
  actTxtW: { fontSize: 12, fontWeight: "800", color: "#fff" },
  actBtnO: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, height: 32,
    alignItems: "center", justifyContent: "center", backgroundColor: colors.surface,
  },
  actTxtO: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  modalRoot: { flex: 1, alignItems: "center", justifyContent: "center", padding: 16 },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(15,23,42,0.45)" },
  modalCard: {
    width: "100%", maxWidth: 480, maxHeight: "80%", backgroundColor: colors.surfaceSecondary,
    borderRadius: 18, padding: 18,
    ...Platform.select({ web: { boxShadow: "0 20px 50px rgba(15,23,42,0.25)" } as any, default: { elevation: 8 } }),
  },
  tl: { flexDirection: "row", gap: 10, marginBottom: 12 },
  tlDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.brandPrimary, marginTop: 4 },
  tlAction: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  tlMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
});
