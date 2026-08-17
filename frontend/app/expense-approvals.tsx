/**
 * Iter 605 — Expense Claims Phase 3: Approvals & Payments (admin/managers).
 * Stage tabs: Manager → Accounts → Finance → Payments queue.
 * Approve / return / reject with remarks; finance sets approved amount;
 * payment recording (bank/UPI/cash or via payroll head).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  RefreshControl, TextInput, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";
import { openReceipt } from "./my-expenses";

const inr = (v: any) => `₹${Number(v || 0).toLocaleString("en-IN")}`;
const STAGES = [
  { key: "pending_manager", label: "Manager", icon: "person-outline" },
  { key: "pending_accounts", label: "Accounts", icon: "calculator-outline" },
  { key: "pending_finance", label: "Finance", icon: "cash-outline" },
  { key: "approved", label: "Payments", icon: "card-outline" },
] as const;
const PAY_MODES = [
  { key: "bank_transfer", label: "Bank Transfer" },
  { key: "upi", label: "UPI" },
  { key: "cash", label: "Cash" },
  { key: "payroll", label: "Add to Payroll" },
];

export default function ExpenseApprovals() {
  const router = useRouter();
  const { selectedCompanyId } = useSelectedCompany();
  const [stage, setStage] = useState<string>("pending_manager");
  const [lists, setLists] = useState<Record<string, any[]>>({});
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState("");
  // action modal: { claim, kind: approve|reject|return|pay }
  const [act, setAct] = useState<any>(null);
  const [remarks, setRemarks] = useState("");
  const [apprAmt, setApprAmt] = useState("");
  const [payMode, setPayMode] = useState("bank_transfer");
  const [payRef, setPayRef] = useState("");
  const [busy, setBusy] = useState(false);

  const cidQ = selectedCompanyId ? `&company_id=${selectedCompanyId}` : "";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res: Record<string, any[]> = {};
      await Promise.all(STAGES.map(async (st) => {
        const scope = st.key === "approved" ? "all" : "approvals";
        const r = await api(`/expense/claims?scope=${scope}&status=${st.key}${cidQ}`);
        res[st.key] = r.claims || [];
      }));
      setLists(res);
    } catch { /* keep */ }
    finally { setLoading(false); }
  }, [cidQ]);
  useEffect(() => { load(); }, [load]);

  const openAction = (claim: any, kind: string) => {
    setAct({ claim, kind });
    setRemarks(""); setPayRef("");
    setApprAmt(String(claim.approved_amount ?? claim.amount ?? ""));
    setPayMode("bank_transfer");
  };

  const doAction = async () => {
    if (!act) return;
    const { claim, kind } = act;
    setBusy(true); setMsg("");
    try {
      if (kind === "pay") {
        await api(`/expense/claims/${claim.claim_id}/payment`, {
          method: "POST",
          body: {
            payment_mode: payMode, payment_reference: payRef,
            paid_amount: parseFloat(apprAmt) || claim.approved_amount || claim.amount,
          },
        });
        setMsg(`${claim.claim_no} marked PAID ✓`);
      } else {
        const body: any = { action: kind, remarks };
        if (kind === "approve" && claim.status === "pending_finance") {
          body.approved_amount = parseFloat(apprAmt) || claim.amount;
        }
        await api(`/expense/claims/${claim.claim_id}/action`, { method: "POST", body });
        setMsg(`${claim.claim_no}: ${kind} done ✓`);
      }
      setAct(null);
      await load();
    } catch (e: any) { setMsg(String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const rows = lists[stage] || [];
  const isPayTab = stage === "approved";

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={{ padding: 4 }}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Expense Approvals</Text>
          <Text style={s.subtitle}>Manager → Accounts → Finance → Payment</Text>
        </View>
      </View>

      <View style={s.tabs}>
        {STAGES.map((st) => (
          <Pressable key={st.key} style={[s.tab, stage === st.key && s.tabOn]}
            onPress={() => setStage(st.key)} testID={`expappr-tab-${st.key}`}>
            <Ionicons name={st.icon as any} size={15}
              color={stage === st.key ? "#fff" : colors.onSurfaceSecondary} />
            <Text style={[s.tabTxt, stage === st.key && { color: "#fff" }]}>
              {st.label} ({(lists[st.key] || []).length})
            </Text>
          </Pressable>
        ))}
      </View>

      <ScrollView
        contentContainerStyle={s.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.brandPrimary} />}
      >
        {msg ? <Text style={s.msg}>{msg}</Text> : null}
        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} /> : null}
        {!loading && rows.length === 0 ? (
          <View style={s.empty}>
            <Ionicons name="checkmark-done-circle-outline" size={38} color={colors.onSurfaceTertiary} />
            <Text style={s.muted}>{isPayTab ? "No approved claims awaiting payment." : "Nothing pending at this stage."}</Text>
          </View>
        ) : null}

        {rows.map((c) => (
          <View key={c.claim_id} style={s.card} testID={`expappr-claim-${c.claim_no}`}>
            <View style={s.cardTop}>
              <Text style={s.claimNo}>{c.claim_no}</Text>
              <Text style={s.emp} numberOfLines={1}>
                {c.employee?.name || "—"}{c.employee?.employee_code ? ` (${c.employee.employee_code})` : ""}
              </Text>
              <Text style={s.amt}>{inr(c.amount)}</Text>
            </View>
            <Text style={s.metaLine}>
              {c.category_name || "—"} · {c.expense_date || "—"}
              {c.vendor ? ` · ${c.vendor}` : ""}{c.invoice_no ? ` · Inv ${c.invoice_no}` : ""}
            </Text>
            {c.description ? <Text style={s.desc} numberOfLines={2}>{c.description}</Text> : null}
            {c.duplicate_confirmed ? (
              <View style={s.dupWarn}>
                <Ionicons name="warning-outline" size={13} color="#B45309" />
                <Text style={s.dupWarnTxt}>Submitted as confirmed possible duplicate — verify carefully</Text>
              </View>
            ) : null}
            {(c.attachments || []).map((a: any) => (
              <Pressable key={a.doc_id} style={s.attRow} onPress={() => openReceipt(c.claim_id, a.doc_id)}>
                <Ionicons name="document-attach-outline" size={15} color={colors.brandPrimary} />
                <Text style={s.attTxt}>{a.file_name}</Text>
              </Pressable>
            ))}
            {(c.approvals || []).map((a: any, i: number) => (
              <Text key={i} style={s.trail}>
                ✓ {a.stage.replace("pending_", "")} {a.action} by {a.by_name || a.role}
                {a.remarks ? ` — “${a.remarks}”` : ""}
              </Text>
            ))}
            <View style={s.btnRow}>
              {isPayTab ? (
                <Pressable style={[s.aBtn, { backgroundColor: "#047857" }]}
                  onPress={() => openAction(c, "pay")} testID={`expappr-pay-${c.claim_no}`}>
                  <Ionicons name="card-outline" size={15} color="#fff" />
                  <Text style={s.aBtnTxt}>Record Payment {inr(c.approved_amount ?? c.amount)}</Text>
                </Pressable>
              ) : (
                <>
                  <Pressable style={[s.aBtn, { backgroundColor: "#059669" }]}
                    onPress={() => openAction(c, "approve")} testID={`expappr-approve-${c.claim_no}`}>
                    <Text style={s.aBtnTxt}>Approve</Text>
                  </Pressable>
                  <Pressable style={[s.aBtn, s.aBtnLight]} onPress={() => openAction(c, "return")}>
                    <Text style={[s.aBtnTxt, { color: "#B45309" }]}>Return</Text>
                  </Pressable>
                  <Pressable style={[s.aBtn, s.aBtnDanger]} onPress={() => openAction(c, "reject")}>
                    <Text style={[s.aBtnTxt, { color: "#DC2626" }]}>Reject</Text>
                  </Pressable>
                </>
              )}
            </View>
          </View>
        ))}
        <View style={{ height: 40 }} />
      </ScrollView>

      {/* Action modal */}
      <Modal visible={!!act} transparent animationType="fade" onRequestClose={() => setAct(null)}>
        <Pressable style={s.modalBg} onPress={() => setAct(null)}>
          <Pressable style={s.modalCard} onPress={() => {}}>
            <Text style={s.modalTitle}>
              {act?.kind === "pay" ? "Record payment" :
                act?.kind === "approve" ? "Approve claim" :
                  act?.kind === "return" ? "Return to employee" : "Reject claim"}
              {" · "}{act?.claim?.claim_no}
            </Text>
            <Text style={s.modalSub}>
              {act?.claim?.employee?.name} · {inr(act?.claim?.amount)}
            </Text>

            {act?.kind === "approve" && act?.claim?.status === "pending_finance" ? (
              <>
                <Text style={s.lbl}>Approved amount (₹)</Text>
                <TextInput style={s.input} value={apprAmt} keyboardType="decimal-pad"
                  onChangeText={setApprAmt} testID="expappr-amt" />
              </>
            ) : null}

            {act?.kind === "pay" ? (
              <>
                <Text style={s.lbl}>Payment mode</Text>
                <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                  {PAY_MODES.map((m) => (
                    <Pressable key={m.key} onPress={() => setPayMode(m.key)}
                      style={[s.mode, payMode === m.key && s.modeOn]} testID={`expappr-mode-${m.key}`}>
                      <Text style={[s.modeTxt, payMode === m.key && { color: "#fff" }]}>{m.label}</Text>
                    </Pressable>
                  ))}
                </View>
                {payMode === "payroll" ? (
                  <Text style={s.hint}>Will appear as “Expense Reimbursement” head in the employee&apos;s next salary (kept separate from wages).</Text>
                ) : null}
                <Text style={s.lbl}>Paid amount (₹)</Text>
                <TextInput style={s.input} value={apprAmt} keyboardType="decimal-pad" onChangeText={setApprAmt} />
                <Text style={s.lbl}>Reference (UTR / txn id)</Text>
                <TextInput style={s.input} value={payRef} onChangeText={setPayRef}
                  placeholder="Optional" placeholderTextColor={colors.onSurfaceTertiary} />
              </>
            ) : (
              <>
                <Text style={s.lbl}>Remarks {act?.kind !== "approve" ? "(tell the employee why)" : "(optional)"}</Text>
                <TextInput style={[s.input, { minHeight: 60, textAlignVertical: "top" }]} multiline
                  value={remarks} onChangeText={setRemarks} testID="expappr-remarks"
                  placeholder="e.g. Receipt unclear, please re-upload" placeholderTextColor={colors.onSurfaceTertiary} />
              </>
            )}

            <View style={{ flexDirection: "row", gap: 10, marginTop: 16 }}>
              <Pressable style={[s.aBtn, s.aBtnLight, { flex: 1 }]} onPress={() => setAct(null)}>
                <Text style={[s.aBtnTxt, { color: colors.onSurface }]}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[s.aBtn, { flex: 1, backgroundColor: act?.kind === "reject" ? "#DC2626" : act?.kind === "return" ? "#B45309" : "#059669" }]}
                disabled={busy} onPress={doAction} testID="expappr-confirm">
                {busy ? <ActivityIndicator size="small" color="#fff" /> :
                  <Text style={s.aBtnTxt}>Confirm</Text>}
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
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceTertiary },
  tabs: {
    flexDirection: "row", gap: 6, paddingHorizontal: 12, paddingVertical: 10,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
    flexWrap: "wrap",
  },
  tab: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderRadius: 999, paddingHorizontal: 12, paddingVertical: 8, minHeight: 38,
    backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border,
  },
  tabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12, fontWeight: "800", color: colors.onSurfaceSecondary },
  body: { padding: 16 },
  msg: { fontSize: 12.5, color: "#059669", fontWeight: "700", marginBottom: 8 },
  empty: { alignItems: "center", paddingVertical: 40 },
  muted: { color: colors.onSurfaceTertiary, marginTop: 8, fontSize: 13 },
  card: {
    backgroundColor: colors.surface, borderRadius: 14, padding: 14,
    borderWidth: 1, borderColor: colors.border, marginBottom: 10,
  },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  claimNo: { fontSize: 12.5, fontWeight: "800", color: colors.brandPrimary },
  emp: { flex: 1, fontSize: 13.5, fontWeight: "700", color: colors.onSurface },
  amt: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  metaLine: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: 4 },
  desc: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 4 },
  dupWarn: {
    flexDirection: "row", alignItems: "center", gap: 5, marginTop: 6,
    backgroundColor: "#FFFBEB", borderRadius: 8, padding: 7,
  },
  dupWarnTxt: { fontSize: 11.5, color: "#B45309", fontWeight: "700", flex: 1 },
  attRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 4, marginTop: 2 },
  attTxt: { fontSize: 12.5, color: colors.brandPrimary, fontWeight: "700" },
  trail: { fontSize: 11.5, color: "#059669", marginTop: 4 },
  btnRow: { flexDirection: "row", gap: 8, marginTop: 12, flexWrap: "wrap" },
  aBtn: {
    flexDirection: "row", gap: 6, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 10,
    minHeight: 44, alignItems: "center", justifyContent: "center",
  },
  aBtnLight: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  aBtnDanger: { backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FECACA" },
  aBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  modalBg: {
    flex: 1, backgroundColor: "rgba(15,23,42,.5)",
    alignItems: "center", justifyContent: "center", padding: 20,
  },
  modalCard: {
    backgroundColor: colors.surface, borderRadius: 16, padding: 18,
    width: "100%", maxWidth: 440,
  },
  modalTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  modalSub: { fontSize: 12.5, color: colors.onSurfaceTertiary, marginTop: 3 },
  lbl: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 12, marginBottom: 5 },
  input: {
    backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border,
    borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10,
    fontSize: 14, color: colors.onSurface, minHeight: 44,
  },
  mode: {
    borderRadius: 999, paddingHorizontal: 13, paddingVertical: 9,
    backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, minHeight: 40,
  },
  modeOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  modeTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  hint: { fontSize: 11.5, color: "#1E40AF", marginTop: 8, backgroundColor: "#EFF6FF", borderRadius: 8, padding: 8 },
});
