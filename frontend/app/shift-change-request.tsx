/**
 * Employee — Shift Change Request (Iter 204).
 *
 * Policy-gated: firms enable it in Attendance Policy → Employee Shift
 * Change. Employees submit a request (date, requested shift, reason);
 * the new shift applies only after approval. Includes My Requests with
 * status timeline + cancel.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  TextInput,
  RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { colors } from "@/src/theme";

const STATUS_COLORS: Record<string, { bg: string; fg: string }> = {
  pending: { bg: "#FEF3C7", fg: "#92400E" },
  pending_final: { bg: "#FEF3C7", fg: "#92400E" },
  approved: { bg: "#D1FAE5", fg: "#065F46" },
  rejected: { bg: "#FEE2E2", fg: "#991B1B" },
  sent_back: { bg: "#E0E7FF", fg: "#3730A3" },
  cancelled: { bg: "#F1F5F9", fg: "#475569" },
};

export default function ShiftChangeRequestScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ date?: string; instant?: string }>();
  const [cfg, setCfg] = useState<any>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [date, setDate] = useState(params.date || new Date().toISOString().slice(0, 10));
  const [shiftId, setShiftId] = useState("");
  const [reason, setReason] = useState("");
  const [remarks, setRemarks] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [c, r] = await Promise.all([
        api<any>("/shift-change/config"),
        api<{ rows: any[] }>("/shift-change/requests-v2/my"),
      ]);
      setCfg(c);
      setRows(r.rows || []);
    } catch (e: any) {
      setMsg({ kind: "err", text: e?.message || "Failed to load" });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    setMsg(null);
    setBusy(true);
    try {
      await api("/shift-change/requests-v2", {
        method: "POST",
        body: {
          date,
          requested_shift_id: shiftId,
          reason,
          remarks,
          instant_exception: params.instant === "1",
        },
      });
      setReason("");
      setRemarks("");
      setShiftId("");
      setMsg({ kind: "ok", text: "Request submitted — you'll be notified after approval." });
      await load();
    } catch (e: any) {
      setMsg({ kind: "err", text: e?.message || "Submit failed" });
    } finally {
      setBusy(false);
    }
  };

  const cancel = async (id: string) => {
    try {
      await api(`/shift-change/requests-v2/${id}/cancel`, { method: "POST" });
      await load();
    } catch (e: any) {
      setMsg({ kind: "err", text: e?.message || "Cancel failed" });
    }
  };

  if (!cfg) {
    return (
      <SafeAreaView style={st.safe}>
        <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
      </SafeAreaView>
    );
  }

  const enabled = cfg.config?.enabled;
  const filtered = statusFilter ? rows.filter((r) => r.status === statusFilter) : rows;

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={st.wrap}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => {
          setRefreshing(true); await load(); setRefreshing(false);
        }} />}
      >
        <View style={st.headRow}>
          <Pressable onPress={() => router.back()} style={st.backBtn} testID="scr-back">
            <Ionicons name="arrow-back" size={20} color="#0F172A" />
          </Pressable>
          <Text style={st.title}>Shift Change Request</Text>
        </View>

        {params.instant === "1" ? (
          <View style={st.instantBanner}>
            <Ionicons name="alert-circle" size={17} color="#B45309" />
            <Text style={st.instantTxt}>
              Your punch does not match your assigned shift. Submit a request so
              attendance is calculated on the correct shift once approved.
            </Text>
          </View>
        ) : null}

        {!enabled ? (
          <View style={st.card}>
            <Text style={st.hint}>
              Shift change requests are not enabled for your firm. Contact HR/Admin.
            </Text>
          </View>
        ) : (
          <View style={st.card}>
            <Text style={st.lbl}>Current shift</Text>
            <Text style={st.curShift}>
              {cfg.current_shift?.name
                ? `${cfg.current_shift.name} (${cfg.current_shift.start}–${cfg.current_shift.end})`
                : "Not assigned"}
            </Text>
            <Text style={st.lbl}>Date</Text>
            <TextInput style={st.input} value={date} onChangeText={setDate}
                       placeholder="YYYY-MM-DD" placeholderTextColor="#94A3B8" testID="scr-date" />
            <Text style={st.lbl}>Requested shift</Text>
            <View style={st.chipsWrap}>
              {(cfg.shifts || []).map((s: any) => (
                <Pressable key={s.shift_id}
                           style={[st.chip, shiftId === s.shift_id && st.chipOn]}
                           onPress={() => setShiftId(s.shift_id)}>
                  <Text style={[st.chipTxt, shiftId === s.shift_id && st.chipTxtOn]}>
                    {s.name} ({s.start}–{s.end})
                  </Text>
                </Pressable>
              ))}
            </View>
            <Text style={st.lbl}>
              Reason{cfg.config?.reason_mandatory ? " *" : " (optional)"}
            </Text>
            <TextInput style={st.input} value={reason} onChangeText={setReason}
                       placeholder="Production requirement / OT / emergency…"
                       placeholderTextColor="#94A3B8" testID="scr-reason" />
            <Text style={st.lbl}>Remarks (optional)</Text>
            <TextInput style={[st.input, { minHeight: 60 }]} value={remarks}
                       onChangeText={setRemarks} multiline
                       placeholder="Anything the approver should know"
                       placeholderTextColor="#94A3B8" />
            {msg ? (
              <Text style={[st.msg, { color: msg.kind === "ok" ? "#065F46" : "#B91C1C" }]}>
                {msg.text}
              </Text>
            ) : null}
            <Pressable style={st.submitBtn} onPress={submit} disabled={busy} testID="scr-submit">
              {busy ? <ActivityIndicator color="#fff" size="small" /> : (
                <Text style={st.submitTxt}>Submit Request</Text>
              )}
            </Pressable>
          </View>
        )}

        <Text style={st.section}>My Requests</Text>
        <View style={st.chipsWrap}>
          {["", "pending", "approved", "rejected", "cancelled"].map((s) => (
            <Pressable key={s || "all"}
                       style={[st.chip, statusFilter === s && st.chipOn]}
                       onPress={() => setStatusFilter(s)}>
              <Text style={[st.chipTxt, statusFilter === s && st.chipTxtOn]}>
                {s ? s[0].toUpperCase() + s.slice(1) : "All"}
              </Text>
            </Pressable>
          ))}
        </View>
        {filtered.length === 0 ? (
          <Text style={st.hint}>No requests yet.</Text>
        ) : filtered.map((r) => {
          const sc = STATUS_COLORS[r.status] || STATUS_COLORS.pending;
          return (
            <View key={r.request_id} style={st.card}>
              <View style={st.reqHead}>
                <Text style={st.reqNo}>{r.request_no}</Text>
                <View style={[st.badge, { backgroundColor: sc.bg }]}>
                  <Text style={[st.badgeTxt, { color: sc.fg }]}>
                    {String(r.status).replace("_", " ").toUpperCase()}
                  </Text>
                </View>
              </View>
              <Text style={st.reqLine}>
                {r.date} · {(r.old_shift?.name || "—")} → {(r.requested_shift?.name || "—")}
                {" "}({r.requested_shift?.start}–{r.requested_shift?.end})
              </Text>
              {r.reason ? <Text style={st.hint}>Reason: {r.reason}</Text> : null}
              {r.approval_remarks ? <Text style={st.hint}>Approver: {r.approval_remarks}</Text> : null}
              {(r.history || []).slice(-3).map((h: any, i: number) => (
                <Text key={i} style={st.timeline}>
                  • {h.action.replace("_", " ")} — {h.by_name || h.by} · {String(h.at || "").slice(0, 16).replace("T", " ")}
                </Text>
              ))}
              {["pending", "pending_final", "sent_back"].includes(r.status) ? (
                <Pressable style={st.cancelBtn} onPress={() => cancel(r.request_id)}>
                  <Text style={st.cancelTxt}>Cancel request</Text>
                </Pressable>
              ) : null}
            </View>
          );
        })}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F6F8FA" },
  wrap: { padding: 16, paddingBottom: 48, maxWidth: 640, width: "100%", alignSelf: "center" },
  headRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 10 },
  backBtn: { width: 40, height: 40, borderRadius: 10, backgroundColor: "#fff",
             alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: "#E2E8F0" },
  title: { fontSize: 20, fontWeight: "800", color: "#0F172A" },
  instantBanner: { flexDirection: "row", gap: 8, padding: 12, borderRadius: 10,
                   backgroundColor: "#FEF3C7", borderWidth: 1, borderColor: "#FDE68A", marginBottom: 12 },
  instantTxt: { flex: 1, fontSize: 12.5, color: "#92400E" },
  card: { backgroundColor: "#fff", borderRadius: 12, padding: 14, marginBottom: 12,
          borderWidth: 1, borderColor: "#E2E8F0" },
  lbl: { fontSize: 12.5, fontWeight: "700", color: "#334155", marginTop: 10, marginBottom: 4 },
  curShift: { fontSize: 14, fontWeight: "700", color: colors.brandPrimary },
  input: { borderWidth: 1, borderColor: "#E2E8F0", borderRadius: 8, paddingHorizontal: 10,
           paddingVertical: 9, fontSize: 13.5, color: "#0F172A", backgroundColor: "#fff" },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginVertical: 6 },
  chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999,
          backgroundColor: "#F1F5F9", borderWidth: 1, borderColor: "#E2E8F0", minHeight: 36 },
  chipOn: { backgroundColor: "#EFF6FF", borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12.5, color: "#475569", fontWeight: "600" },
  chipTxtOn: { color: colors.brandPrimary },
  msg: { fontSize: 13, marginTop: 8 },
  submitBtn: { backgroundColor: colors.brandPrimary, borderRadius: 10, paddingVertical: 12,
               alignItems: "center", marginTop: 14, minHeight: 46, justifyContent: "center" },
  submitTxt: { color: "#fff", fontWeight: "800", fontSize: 14.5 },
  section: { fontSize: 16, fontWeight: "800", color: "#0F172A", marginTop: 8, marginBottom: 6 },
  hint: { fontSize: 12.5, color: "#64748B", marginVertical: 2 },
  reqHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  reqNo: { fontSize: 13.5, fontWeight: "800", color: "#0F172A" },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  badgeTxt: { fontSize: 10.5, fontWeight: "800" },
  reqLine: { fontSize: 13, color: "#334155", marginTop: 6 },
  timeline: { fontSize: 11.5, color: "#94A3B8", marginTop: 3 },
  cancelBtn: { alignSelf: "flex-start", marginTop: 8, paddingHorizontal: 12, paddingVertical: 7,
               borderRadius: 8, borderWidth: 1, borderColor: "#FCA5A5" },
  cancelTxt: { color: "#B91C1C", fontSize: 12.5, fontWeight: "700" },
});
