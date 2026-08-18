/**
 * Iter 610 — ESS Requests admin queue (HR/Manager approvals).
 * Attendance corrections, profile/bank changes, advances, device changes…
 * Approve applies the change (originals never deleted) + notifies employee
 * in-app and via SMS (MSG91, when enabled).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Modal, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";

const ST: Record<string, string> = {
  submitted: "#2563EB", under_review: "#D97706", approved: "#059669",
  rejected: "#DC2626", completed: "#047857",
};

export default function EssRequestsAdmin() {
  const router = useRouter();
  const { selectedCompanyId } = useSelectedCompany();
  const [filter, setFilter] = useState<"open" | "all">("open");
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [act, setAct] = useState<any>(null);
  const [remarks, setRemarks] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const cid = selectedCompanyId ? `&company_id=${selectedCompanyId}` : "";
      const r = await api(`/ess/requests?scope=admin${cid}`);
      setRows(r.requests || []);
    } catch (e: any) { setMsg(String(e?.message || e)); }
    finally { setLoading(false); }
  }, [selectedCompanyId]);
  useEffect(() => { load(); }, [load]);

  const decide = async (action: string) => {
    if (!act) return;
    setBusy(true);
    try {
      await api(`/ess/requests/${act.request_id}/decide`, {
        method: "POST", body: { action, remarks },
      });
      setMsg(`${act.request_no}: ${action} ✓ (employee notified)`);
      setAct(null); setRemarks("");
      await load();
    } catch (e: any) { setMsg(String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const shown = rows.filter((r) =>
    filter === "all" || ["submitted", "under_review"].includes(r.status));

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="arrow-back" size={22} color={colors.onSurface} /></Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Employee Requests (ESS)</Text>
          <Text style={s.sub}>Corrections · profile/bank changes · advances · devices</Text>
        </View>
        <Pressable style={[s.chip, filter === "open" && s.chipOn]} onPress={() => setFilter("open")}>
          <Text style={[s.chipTxt, filter === "open" && { color: "#fff" }]}>Open</Text>
        </Pressable>
        <Pressable style={[s.chip, filter === "all" && s.chipOn]} onPress={() => setFilter("all")}>
          <Text style={[s.chipTxt, filter === "all" && { color: "#fff" }]}>All</Text>
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={s.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.brandPrimary} />}>
        {msg ? <Text style={s.msg}>{msg}</Text> : null}
        {!loading && shown.length === 0 ? <Text style={s.muted}>No {filter === "open" ? "open " : ""}requests.</Text> : null}
        {shown.map((r) => (
          <View key={r.request_id} style={s.card} testID={`essadm-${r.request_no}`}>
            <View style={s.cardTop}>
              <Text style={s.reqNo}>{r.request_no}</Text>
              <Text style={s.emp}>{r.employee?.name}{r.employee?.employee_code ? ` (${r.employee.employee_code})` : ""}</Text>
              <View style={[s.pill, { backgroundColor: `${ST[r.status] || "#64748B"}18` }]}>
                <Text style={[s.pillTxt, { color: ST[r.status] || "#64748B" }]}>{r.status.replace("_", " ").toUpperCase()}</Text>
              </View>
            </View>
            <Text style={s.type}>{r.type.replace(/_/g, " ").toUpperCase()}</Text>
            {r.reason ? <Text style={s.reason}>“{r.reason}”</Text> : null}
            {r.type === "attendance_correction" && r.payload ? (
              <Text style={s.detail}>
                Date {r.payload.date} · Requested IN {r.payload.requested_in ? r.payload.requested_in.slice(11, 16) : "—"} ·
                OUT {r.payload.requested_out ? r.payload.requested_out.slice(11, 16) : "—"}
              </Text>
            ) : null}
            {(r.type === "profile_correction" || r.type === "bank_change") && r.payload?.fields ? (
              <Text style={s.detail}>Fields: {Object.entries(r.payload.fields).map(([k, v]) => `${k} → ${v}`).join(" · ")}</Text>
            ) : null}
            {r.payload?.detail ? <Text style={s.detail}>{r.payload.detail}</Text> : null}
            {["submitted", "under_review"].includes(r.status) ? (
              <View style={s.btnRow}>
                <Pressable style={[s.aBtn, { backgroundColor: "#059669" }]} onPress={() => { setAct({ ...r, _a: "approve" }); setRemarks(""); }}
                  testID={`essadm-approve-${r.request_no}`}>
                  <Text style={s.aBtnTxt}>Approve</Text>
                </Pressable>
                <Pressable style={[s.aBtn, s.aBtnDanger]} onPress={() => { setAct({ ...r, _a: "reject" }); setRemarks(""); }}>
                  <Text style={[s.aBtnTxt, { color: "#DC2626" }]}>Reject</Text>
                </Pressable>
                {r.status === "submitted" ? (
                  <Pressable style={[s.aBtn, s.aBtnLight]} onPress={() => { setAct({ ...r, _a: "under_review" }); setRemarks(""); }}>
                    <Text style={[s.aBtnTxt, { color: "#D97706" }]}>Mark Reviewing</Text>
                  </Pressable>
                ) : null}
              </View>
            ) : null}
          </View>
        ))}
        <View style={{ height: 40 }} />
      </ScrollView>

      <Modal visible={!!act} transparent animationType="fade" onRequestClose={() => setAct(null)}>
        <Pressable style={s.modalBg} onPress={() => setAct(null)}>
          <Pressable style={s.modalCard} onPress={() => {}}>
            <Text style={s.modalTitle}>{act?._a?.replace("_", " ")} · {act?.request_no}</Text>
            <Text style={s.sub}>{act?.employee?.name} · {act?.type?.replace(/_/g, " ")}</Text>
            {act?._a === "approve" && act?.type === "attendance_correction" ? (
              <Text style={s.detail}>Approving will ADD corrected punch record(s) with source “Manual Correction” — the original punches stay untouched.</Text>
            ) : null}
            <Text style={s.lbl}>Remarks {act?._a === "reject" ? "(tell the employee why) *" : "(optional)"}</Text>
            <TextInput style={s.input} value={remarks} onChangeText={setRemarks}
              placeholder="Remarks…" placeholderTextColor={colors.onSurfaceTertiary} testID="essadm-remarks" />
            <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
              <Pressable style={[s.aBtn, s.aBtnLight, { flex: 1 }]} onPress={() => setAct(null)}>
                <Text style={[s.aBtnTxt, { color: colors.onSurface }]}>Cancel</Text>
              </Pressable>
              <Pressable style={[s.aBtn, { flex: 1, backgroundColor: act?._a === "reject" ? "#DC2626" : "#059669" }]}
                disabled={busy} onPress={() => decide(act._a)} testID="essadm-confirm">
                {busy ? <ActivityIndicator size="small" color="#fff" /> : <Text style={s.aBtnTxt}>Confirm</Text>}
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
  header: { flexDirection: "row", alignItems: "center", gap: 8, padding: 14, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 2 },
  chip: { borderRadius: 999, paddingHorizontal: 13, paddingVertical: 8, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, minHeight: 36 },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "800", color: colors.onSurfaceSecondary },
  body: { padding: 16 },
  msg: { color: "#059669", fontWeight: "700", fontSize: 12.5, marginBottom: 8 },
  muted: { color: colors.onSurfaceTertiary, fontSize: 13, textAlign: "center", marginTop: 24 },
  card: { backgroundColor: colors.surface, borderRadius: 14, padding: 13, borderWidth: 1, borderColor: colors.border, marginBottom: 10 },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  reqNo: { fontSize: 12, fontWeight: "800", color: colors.brandPrimary },
  emp: { flex: 1, fontSize: 13, fontWeight: "800", color: colors.onSurface },
  pill: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  pillTxt: { fontSize: 9.5, fontWeight: "800" },
  type: { fontSize: 11.5, fontWeight: "800", color: colors.onSurfaceTertiary, marginTop: 4 },
  reason: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 4, fontStyle: "italic" },
  detail: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 4, lineHeight: 17 },
  btnRow: { flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" },
  aBtn: { borderRadius: 10, paddingHorizontal: 14, paddingVertical: 10, minHeight: 42, alignItems: "center", justifyContent: "center" },
  aBtnLight: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  aBtnDanger: { backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FECACA" },
  aBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  lbl: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 12, marginBottom: 4 },
  input: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 9, fontSize: 13.5, color: colors.onSurface, minHeight: 42 },
  modalBg: { flex: 1, backgroundColor: "rgba(15,23,42,.5)", alignItems: "center", justifyContent: "center", padding: 20 },
  modalCard: { backgroundColor: colors.surface, borderRadius: 16, padding: 16, width: "100%", maxWidth: 430 },
  modalTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, textTransform: "capitalize" },
});
