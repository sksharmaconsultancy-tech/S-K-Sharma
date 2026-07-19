/**
 * Admin — Shift Change Requests (Iter 204).
 *
 * Pending queue with bulk approve / reject / send-back, status filters,
 * approval timeline, Shift Change Register (Excel) and Daily Shift
 * Assignment report download.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  TextInput,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import MonthPicker from "@/src/components/MonthPicker";
import { colors } from "@/src/theme";

const STATUS_COLORS: Record<string, { bg: string; fg: string }> = {
  pending: { bg: "#FEF3C7", fg: "#92400E" },
  pending_final: { bg: "#FDE68A", fg: "#92400E" },
  approved: { bg: "#D1FAE5", fg: "#065F46" },
  rejected: { bg: "#FEE2E2", fg: "#991B1B" },
  sent_back: { bg: "#E0E7FF", fg: "#3730A3" },
  cancelled: { bg: "#F1F5F9", fg: "#475569" },
};

export default function ShiftChangeAdminScreen() {
  const { user, loading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [rows, setRows] = useState<any[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [statusFilter, setStatusFilter] = useState("pending");
  const [month, setMonth] = useState<string>(() => new Date().toISOString().slice(0, 7));
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [remarks, setRemarks] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const params = [
        selectedCompanyId ? `company_id=${encodeURIComponent(selectedCompanyId)}` : "",
        statusFilter ? `status=${statusFilter}` : "",
      ].filter(Boolean).join("&");
      const r = await api<any>(`/admin/shift-change/requests-v2${params ? `?${params}` : ""}`);
      setRows(r.rows || []);
      setCounts(r.counts || {});
      setSelected(new Set());
    } catch (e: any) {
      setMsg(e?.message || "Failed to load");
    }
  }, [selectedCompanyId, statusFilter]);

  useEffect(() => { load(); }, [load]);

  const decide = async (action: "approve" | "reject" | "send_back", ids?: string[]) => {
    const targetIds = ids || Array.from(selected);
    if (targetIds.length === 0) {
      setMsg("Select at least one request.");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<any>("/admin/shift-change/requests-v2/decide", {
        method: "POST",
        body: { request_ids: targetIds, action, remarks },
      });
      setMsg(`${r.processed} request(s) processed. Attendance recalculates automatically on the approved shift.`);
      setRemarks("");
      await load();
    } catch (e: any) {
      setMsg(e?.message || "Action failed");
    } finally {
      setBusy(false);
    }
  };

  const download = async (kind: "register" | "assignments") => {
    if (!selectedCompanyId) {
      setMsg("Select a firm from the top bar first.");
      return;
    }
    try {
      const path = kind === "register"
        ? `/admin/shift-change/register?company_id=${selectedCompanyId}&month=${month}&fmt=xlsx${statusFilter ? `&status=${statusFilter}` : ""}`
        : `/admin/shift-change/daily-assignments?company_id=${selectedCompanyId}&month=${month}&fmt=xlsx`;
      const { webBlobUrl } = await apiBinary(path);
      if (Platform.OS === "web" && webBlobUrl) {
        const a = document.createElement("a");
        a.href = webBlobUrl;
        a.download = kind === "register"
          ? `ShiftChangeRegister_${month}.xlsx`
          : `DailyShiftAssignments_${month}.xlsx`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(webBlobUrl), 30000);
      }
    } catch (e: any) {
      setMsg(e?.message || "Download failed");
    }
  };

  const pendingSelectable = useMemo(
    () => rows.filter((r) => ["pending", "pending_final", "sent_back"].includes(r.status)),
    [rows],
  );

  if (loading) return null;
  const role = user?.role as string;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={st.wrap}>
        <Text style={st.title}>Shift Change Requests</Text>
        <Text style={st.subtitle}>
          Approve / reject employee shift change requests. Approved shifts apply
          to that day automatically — attendance, OT and payroll views recalculate.
        </Text>

        <View style={st.filterRow}>
          {["pending", "pending_final", "approved", "rejected", "sent_back", "cancelled", ""].map((s) => (
            <Pressable key={s || "all"}
                       style={[st.chip, statusFilter === s && st.chipOn]}
                       onPress={() => setStatusFilter(s)}
                       testID={`sca-filter-${s || "all"}`}>
              <Text style={[st.chipTxt, statusFilter === s && st.chipTxtOn]}>
                {(s ? s.replace("_", " ") : "all").toUpperCase()}
                {s && counts[s] ? ` (${counts[s]})` : ""}
              </Text>
            </Pressable>
          ))}
          <MonthPicker value={month} onChange={setMonth} />
          <Pressable style={st.dlBtn} onPress={() => download("register")}>
            <Ionicons name="download-outline" size={14} color={colors.brandPrimary} />
            <Text style={st.dlTxt}>Register (Excel)</Text>
          </Pressable>
          <Pressable style={st.dlBtn} onPress={() => download("assignments")}>
            <Ionicons name="calendar-outline" size={14} color={colors.brandPrimary} />
            <Text style={st.dlTxt}>Daily Assignments</Text>
          </Pressable>
        </View>

        {msg ? <Text style={st.msg}>{msg}</Text> : null}

        {pendingSelectable.length > 0 ? (
          <View style={st.bulkBar}>
            <Pressable style={st.smallBtn}
                       onPress={() => setSelected(new Set(pendingSelectable.map((r) => r.request_id)))}>
              <Text style={st.smallBtnTxt}>Select all pending ({pendingSelectable.length})</Text>
            </Pressable>
            <TextInput style={st.remarksInput} placeholder="Approval / rejection remarks…"
                       placeholderTextColor="#94A3B8" value={remarks} onChangeText={setRemarks} />
            <Pressable style={[st.actBtn, { backgroundColor: "#059669" }]}
                       onPress={() => decide("approve")} disabled={busy} testID="sca-bulk-approve">
              <Text style={st.actTxt}>Approve ({selected.size})</Text>
            </Pressable>
            <Pressable style={[st.actBtn, { backgroundColor: "#DC2626" }]}
                       onPress={() => decide("reject")} disabled={busy}>
              <Text style={st.actTxt}>Reject</Text>
            </Pressable>
            <Pressable style={[st.actBtn, { backgroundColor: "#4F46E5" }]}
                       onPress={() => decide("send_back")} disabled={busy}>
              <Text style={st.actTxt}>Send Back</Text>
            </Pressable>
          </View>
        ) : null}

        {busy ? <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 10 }} /> : null}

        {rows.length === 0 ? (
          <Text style={st.hint}>No requests for this filter.</Text>
        ) : rows.map((r) => {
          const sc = STATUS_COLORS[r.status] || STATUS_COLORS.pending;
          const selectable = ["pending", "pending_final", "sent_back"].includes(r.status);
          const on = selected.has(r.request_id);
          return (
            <Pressable key={r.request_id}
                       style={[st.card, on && st.cardOn]}
                       onPress={() => {
                         if (!selectable) return;
                         setSelected((prev) => {
                           const n = new Set(prev);
                           if (n.has(r.request_id)) n.delete(r.request_id);
                           else n.add(r.request_id);
                           return n;
                         });
                       }}>
              <View style={st.cardHead}>
                {selectable ? (
                  <Ionicons name={on ? "checkbox" : "square-outline"} size={18}
                            color={on ? colors.brandPrimary : "#94A3B8"} />
                ) : null}
                <Text style={st.reqNo}>{r.request_no}</Text>
                <Text style={st.empName}>{r.employee_name} ({r.employee_code})</Text>
                {r.post_punch ? (
                  <View style={[st.badge, { backgroundColor: "#FEF3C7" }]}>
                    <Text style={[st.badgeTxt, { color: "#92400E" }]}>POST-PUNCH</Text>
                  </View>
                ) : null}
                <View style={[st.badge, { backgroundColor: sc.bg }]}>
                  <Text style={[st.badgeTxt, { color: sc.fg }]}>
                    {String(r.status).replace("_", " ").toUpperCase()}
                  </Text>
                </View>
              </View>
              <Text style={st.reqLine}>
                {r.date} · {(r.old_shift?.name || "no shift")} → {(r.requested_shift?.name || "—")}
                {" "}({r.requested_shift?.start}–{r.requested_shift?.end}) · {r.company_name}
              </Text>
              {r.reason ? <Text style={st.hint}>Reason: {r.reason}</Text> : null}
              {(r.history || []).map((h: any, i: number) => (
                <Text key={i} style={st.timeline}>
                  • {h.action.replace("_", " ")} — {h.by_name || h.by} · {String(h.at || "").slice(0, 16).replace("T", " ")}
                  {h.remarks ? ` — ${h.remarks}` : ""}
                </Text>
              ))}
              {selectable ? (
                <View style={st.rowActions}>
                  <Pressable style={[st.miniBtn, { borderColor: "#A7F3D0" }]}
                             onPress={() => decide("approve", [r.request_id])}
                             testID={`sca-approve-${r.request_no}`}>
                    <Text style={[st.miniTxt, { color: "#059669" }]}>Approve</Text>
                  </Pressable>
                  <Pressable style={[st.miniBtn, { borderColor: "#FECACA" }]}
                             onPress={() => decide("reject", [r.request_id])}>
                    <Text style={[st.miniTxt, { color: "#DC2626" }]}>Reject</Text>
                  </Pressable>
                  <Pressable style={[st.miniBtn, { borderColor: "#C7D2FE" }]}
                             onPress={() => decide("send_back", [r.request_id])}>
                    <Text style={[st.miniTxt, { color: "#4F46E5" }]}>Send Back</Text>
                  </Pressable>
                </View>
              ) : null}
            </Pressable>
          );
        })}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F6F8FA" },
  wrap: { padding: 16, paddingBottom: 48, maxWidth: 1000, width: "100%", alignSelf: "center" },
  title: { fontSize: 22, fontWeight: "800", color: "#0F172A" },
  subtitle: { fontSize: 13, color: "#64748B", marginTop: 4, marginBottom: 12 },
  filterRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 10 },
  chip: { paddingHorizontal: 11, paddingVertical: 7, borderRadius: 999,
          backgroundColor: "#F1F5F9", borderWidth: 1, borderColor: "#E2E8F0" },
  chipOn: { backgroundColor: "#EFF6FF", borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11.5, color: "#475569", fontWeight: "700" },
  chipTxtOn: { color: colors.brandPrimary },
  dlBtn: { flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1,
           borderColor: colors.brandPrimary, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 7 },
  dlTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  msg: { fontSize: 13, color: "#334155", marginBottom: 8 },
  bulkBar: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center",
             backgroundColor: "#fff", borderRadius: 10, padding: 10, borderWidth: 1,
             borderColor: "#E2E8F0", marginBottom: 12 },
  smallBtn: { paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8, backgroundColor: "#F1F5F9" },
  smallBtnTxt: { fontSize: 12, color: "#334155", fontWeight: "600" },
  remarksInput: { flex: 1, minWidth: 180, borderWidth: 1, borderColor: "#E2E8F0",
                  borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 12.5, color: "#0F172A" },
  actBtn: { borderRadius: 8, paddingHorizontal: 14, paddingVertical: 9, minHeight: 38, justifyContent: "center" },
  actTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  card: { backgroundColor: "#fff", borderRadius: 12, padding: 13, marginBottom: 10,
          borderWidth: 1, borderColor: "#E2E8F0" },
  cardOn: { borderColor: colors.brandPrimary, backgroundColor: "#F8FBFF" },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  reqNo: { fontSize: 13, fontWeight: "800", color: "#0F172A" },
  empName: { fontSize: 13, color: "#334155", flex: 1 },
  badge: { paddingHorizontal: 9, paddingVertical: 3, borderRadius: 999 },
  badgeTxt: { fontSize: 10, fontWeight: "800" },
  reqLine: { fontSize: 12.5, color: "#334155", marginTop: 6 },
  hint: { fontSize: 12, color: "#64748B", marginTop: 3 },
  timeline: { fontSize: 11.5, color: "#94A3B8", marginTop: 3 },
  rowActions: { flexDirection: "row", gap: 8, marginTop: 8 },
  miniBtn: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 6 },
  miniTxt: { fontSize: 12, fontWeight: "700" },
});
