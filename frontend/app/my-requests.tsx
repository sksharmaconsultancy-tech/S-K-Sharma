/**
 * Iter 610 — ESS: My Requests (unified) + Notification Center.
 * Requests tab: full history w/ status timeline + create (9 types).
 * Notifications tab: personal feed with unread count + mark-all-read.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Modal, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";
import { api } from "@/src/api/client";
import { colors } from "@/src/theme";

const TYPES: [string, string, string][] = [
  ["attendance_correction", "Attendance Correction", "time-outline"],
  ["profile_correction", "Profile Correction", "person-outline"],
  ["bank_change", "Bank Change", "card-outline"],
  ["advance_request", "Advance Request", "wallet-outline"],
  ["reimbursement_request", "Reimbursement Request", "cash-outline"],
  ["document_request", "Document Request", "document-text-outline"],
  ["device_change", "Device Change", "phone-portrait-outline"],
  ["shift_change", "Shift Change", "swap-horizontal-outline"],
  ["other", "Other HR Request", "help-circle-outline"],
];
const ST: Record<string, { l: string; c: string }> = {
  submitted: { l: "SUBMITTED", c: "#2563EB" }, under_review: { l: "UNDER REVIEW", c: "#D97706" },
  approved: { l: "APPROVED", c: "#059669" }, rejected: { l: "REJECTED", c: "#DC2626" },
  completed: { l: "COMPLETED", c: "#047857" },
};

export default function MyRequests() {
  const router = useRouter();
  const params = useLocalSearchParams<{ tab?: string }>();
  const [tab, setTab] = useState<"requests" | "notifications">(
    params.tab === "notifications" ? "notifications" : "requests");
  const [reqs, setReqs] = useState<any[]>([]);
  const [notifs, setNotifs] = useState<any[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const [create, setCreate] = useState(false);
  const [nType, setNType] = useState("");
  const [reason, setReason] = useState("");
  const [detail, setDetail] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, n] = await Promise.all([api("/ess/requests"), api("/ess/notifications")]);
      setReqs(r.requests || []); setNotifs(n.notifications || []); setUnread(n.unread || 0);
    } catch { }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    if (!nType) { setMsg("Choose a request type"); return; }
    if (nType === "attendance_correction") { setCreate(false); router.push("/my-attendance" as any); return; }
    if (nType === "profile_correction" || nType === "bank_change") { setCreate(false); router.push("/my-profile" as any); return; }
    if (!reason.trim()) { setMsg("Please describe your request"); return; }
    setBusy(true);
    try {
      const r = await api("/ess/requests", {
        method: "POST", body: { type: nType, reason, payload: { detail } },
      });
      setMsg(`Request ${r.request?.request_no} submitted ✓`);
      setCreate(false); setNType(""); setReason(""); setDetail("");
      await load();
    } catch (e: any) { setMsg(String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const markRead = async () => {
    try { await api("/ess/notifications/read", { method: "POST", body: {} }); await load(); } catch { }
  };

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="arrow-back" size={22} color={colors.onSurface} /></Pressable>
        <Text style={s.title}>My Requests & Alerts</Text>
        <Pressable style={s.newBtn} onPress={() => { setCreate(true); setMsg(""); }} testID="req-new">
          <Ionicons name="add" size={16} color="#fff" /><Text style={s.newTxt}>New</Text>
        </Pressable>
      </View>
      <View style={s.tabs}>
        <Pressable style={[s.tab, tab === "requests" && s.tabOn]} onPress={() => setTab("requests")} testID="req-tab-requests">
          <Text style={[s.tabTxt, tab === "requests" && { color: "#fff" }]}>Requests ({reqs.length})</Text>
        </Pressable>
        <Pressable style={[s.tab, tab === "notifications" && s.tabOn]} onPress={() => setTab("notifications")} testID="req-tab-notifications">
          <Text style={[s.tabTxt, tab === "notifications" && { color: "#fff" }]}>Notifications{unread ? ` (${unread} new)` : ""}</Text>
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={s.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.brandPrimary} />}>
        {msg ? <Text style={s.msg}>{msg}</Text> : null}

        {tab === "requests" ? (
          <>
            {!loading && reqs.length === 0 ? <Text style={s.muted}>No requests yet — tap “New” to create one.</Text> : null}
            {reqs.map((r) => {
              const st = ST[r.status] || ST.submitted;
              return (
                <View key={r.request_id} style={s.card} testID={`req-${r.request_no}`}>
                  <View style={s.cardTop}>
                    <Text style={s.reqNo}>{r.request_no}</Text>
                    <Text style={s.type}>{(TYPES.find((t) => t[0] === r.type)?.[1]) || r.type}</Text>
                    <View style={[s.pill, { backgroundColor: `${st.c}18` }]}><Text style={[s.pillTxt, { color: st.c }]}>{st.l}</Text></View>
                  </View>
                  {r.reason ? <Text style={s.sub}>{r.reason}</Text> : null}
                  {r.remarks ? <Text style={[s.sub, { color: st.c }]}>HR: {r.remarks}</Text> : null}
                  <View style={s.timeline}>
                    {(r.history || []).map((h: any, i: number) => (
                      <Text key={i} style={s.tl}>• {h.action.replace("_", " ")} · {(h.at || "").slice(0, 16).replace("T", " ")}</Text>
                    ))}
                  </View>
                </View>
              );
            })}
          </>
        ) : (
          <>
            {unread > 0 ? (
              <Pressable style={s.markBtn} onPress={markRead} testID="notif-mark-read">
                <Text style={s.markTxt}>Mark all as read ({unread})</Text>
              </Pressable>
            ) : null}
            {!loading && notifs.length === 0 ? <Text style={s.muted}>No notifications yet.</Text> : null}
            {notifs.map((n) => (
              <View key={n.notification_id} style={[s.card, !n.read && { borderColor: colors.brandPrimary }]}>
                <View style={s.cardTop}>
                  {!n.read ? <View style={s.dot} /> : null}
                  <Text style={[s.type, { flex: 1 }]}>{n.title}</Text>
                  <Text style={s.at}>{(n.created_at || "").slice(0, 16).replace("T", " ")}</Text>
                </View>
                <Text style={s.sub}>{n.body}</Text>
              </View>
            ))}
          </>
        )}
        <View style={{ height: 40 }} />
      </ScrollView>

      <Modal visible={create} transparent animationType="fade" onRequestClose={() => setCreate(false)}>
        <Pressable style={s.modalBg} onPress={() => setCreate(false)}>
          <Pressable style={s.modalCard} onPress={() => {}}>
            <Text style={s.modalTitle}>New Request</Text>
            <ScrollView style={{ maxHeight: 300 }}>
              {TYPES.map(([k, l, ic]) => (
                <Pressable key={k} style={[s.typeRow, nType === k && { borderColor: colors.brandPrimary, backgroundColor: "#EFF6FF" }]}
                  onPress={() => setNType(k)} testID={`req-type-${k}`}>
                  <Ionicons name={ic as any} size={17} color={colors.brandPrimary} />
                  <Text style={s.typeTxt}>{l}</Text>
                  {nType === k ? <Ionicons name="checkmark" size={16} color={colors.brandPrimary} /> : null}
                </Pressable>
              ))}
            </ScrollView>
            {nType && !["attendance_correction", "profile_correction", "bank_change"].includes(nType) ? (
              <>
                <Text style={s.lbl}>Describe your request *</Text>
                <TextInput style={[s.input, { minHeight: 60 }]} multiline value={reason} onChangeText={setReason}
                  placeholder="e.g. Need advance of ₹5,000 for medical emergency" placeholderTextColor={colors.onSurfaceTertiary} testID="req-reason" />
                <Text style={s.lbl}>Extra details (optional)</Text>
                <TextInput style={s.input} value={detail} onChangeText={setDetail} placeholder="Amount / dates / document name…"
                  placeholderTextColor={colors.onSurfaceTertiary} />
              </>
            ) : null}
            {["attendance_correction", "profile_correction", "bank_change"].includes(nType) ? (
              <Text style={s.sub}>This request has its own guided form — tap Continue.</Text>
            ) : null}
            <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
              <Pressable style={[s.mBtn, s.mBtnLight]} onPress={() => setCreate(false)}>
                <Text style={[s.mBtnTxt, { color: colors.onSurface }]}>Cancel</Text>
              </Pressable>
              <Pressable style={[s.mBtn, { backgroundColor: colors.brandPrimary }]} disabled={busy} onPress={submit} testID="req-submit">
                {busy ? <ActivityIndicator size="small" color="#fff" /> :
                  <Text style={s.mBtnTxt}>{["attendance_correction", "profile_correction", "bank_change"].includes(nType) ? "Continue" : "Submit"}</Text>}
              </Pressable>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { flex: 1, fontSize: 17, fontWeight: "800", color: colors.onSurface },
  newBtn: { flexDirection: "row", alignItems: "center", gap: 3, backgroundColor: colors.brandPrimary, borderRadius: 10, paddingHorizontal: 12, minHeight: 40, justifyContent: "center" },
  newTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  tabs: { flexDirection: "row", gap: 8, padding: 12, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  tab: { flex: 1, borderRadius: 999, paddingVertical: 9, alignItems: "center", backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, minHeight: 40 },
  tabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, fontWeight: "800", color: colors.onSurfaceSecondary },
  body: { padding: 16 },
  msg: { color: "#059669", fontWeight: "700", fontSize: 12.5, marginBottom: 8 },
  muted: { color: colors.onSurfaceTertiary, fontSize: 13, textAlign: "center", marginTop: 24 },
  card: { backgroundColor: colors.surface, borderRadius: 14, padding: 13, borderWidth: 1, borderColor: colors.border, marginBottom: 10 },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  reqNo: { fontSize: 12, fontWeight: "800", color: colors.brandPrimary },
  type: { flex: 1, fontSize: 13, fontWeight: "800", color: colors.onSurface },
  pill: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  pillTxt: { fontSize: 9.5, fontWeight: "800" },
  sub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 5, lineHeight: 17 },
  timeline: { marginTop: 6 },
  tl: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2, textTransform: "capitalize" },
  at: { fontSize: 10.5, color: colors.onSurfaceTertiary },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brandPrimary },
  markBtn: { alignSelf: "center", backgroundColor: "#EFF6FF", borderRadius: 999, paddingHorizontal: 16, paddingVertical: 9, marginBottom: 10, minHeight: 38 },
  markTxt: { color: colors.brandPrimary, fontWeight: "800", fontSize: 12.5 },
  typeRow: { flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1, borderColor: colors.border, borderRadius: 10, padding: 11, marginBottom: 6, minHeight: 44 },
  typeTxt: { flex: 1, fontSize: 13, fontWeight: "700", color: colors.onSurface },
  lbl: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 10, marginBottom: 4 },
  input: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 9, fontSize: 13.5, color: colors.onSurface, minHeight: 42, textAlignVertical: "top" },
  modalBg: { flex: 1, backgroundColor: "rgba(15,23,42,.5)", alignItems: "center", justifyContent: "center", padding: 20 },
  modalCard: { backgroundColor: colors.surface, borderRadius: 16, padding: 16, width: "100%", maxWidth: 430 },
  modalTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  mBtn: { flex: 1, borderRadius: 10, minHeight: 44, alignItems: "center", justifyContent: "center" },
  mBtnLight: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  mBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
});
