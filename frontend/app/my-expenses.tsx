/**
 * Iter 605 — Expense Claims Phase 2: Employee dashboard.
 * Summary tiles, status filters, claim history with approval timeline,
 * submit (with duplicate confirmation), edit / cancel drafts, receipts.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  RefreshControl, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useFocusEffect } from "@react-navigation/native";

import { api, apiBinary } from "@/src/api/client";
import { colors } from "@/src/theme";
import { confirmYesNo } from "@/src/utils/confirm";

export const STATUS_META: Record<string, { label: string; color: string }> = {
  draft: { label: "DRAFT", color: "#64748B" },
  pending_manager: { label: "WITH MANAGER", color: "#D97706" },
  pending_accounts: { label: "WITH ACCOUNTS", color: "#7C3AED" },
  pending_finance: { label: "WITH FINANCE", color: "#2563EB" },
  returned: { label: "RETURNED", color: "#B45309" },
  rejected: { label: "REJECTED", color: "#DC2626" },
  approved: { label: "APPROVED", color: "#059669" },
  paid: { label: "PAID", color: "#047857" },
  cancelled: { label: "CANCELLED", color: "#94A3B8" },
};
const inr = (v: any) => `₹${Number(v || 0).toLocaleString("en-IN")}`;
const FILTERS = [
  { key: "all", label: "All" },
  { key: "draft", label: "Draft" },
  { key: "pending", label: "In Approval" },
  { key: "approved", label: "Approved" },
  { key: "paid", label: "Paid" },
  { key: "returned", label: "Returned" },
  { key: "rejected", label: "Rejected" },
];

export async function openReceipt(claimId: string, docId: string) {
  try {
    const r = await apiBinary(`/expense/claims/${claimId}/attachments/${docId}`);
    if (Platform.OS === "web" && r.webBlobUrl) {
      (globalThis as any).window?.open(r.webBlobUrl, "_blank");
    }
  } catch {}
}

export default function MyExpenses() {
  const router = useRouter();
  const [dash, setDash] = useState<any>(null);
  const [claims, setClaims] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [d, c] = await Promise.all([
        api("/expense/dashboard"), api("/expense/claims?scope=mine"),
      ]);
      setDash(d); setClaims(c.claims || []);
    } catch { /* keep */ }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const submit = async (claim: any, confirmDup = false) => {
    setBusy(claim.claim_id); setMsg("");
    try {
      await api(`/expense/claims/${claim.claim_id}/submit`, {
        method: "POST", body: confirmDup ? { confirm_duplicate: true } : {},
      });
      setMsg(`Claim ${claim.claim_no} submitted for approval ✓`);
      await load();
    } catch (e: any) {
      const t = String(e?.message || e);
      if (t.toLowerCase().includes("duplicate")) {
        const yes = await confirmYesNo(
          `${t.replace(/^.*detail":"?/, "").replace(/"}$/, "")}\n\nSubmit anyway?`,
          "Possible duplicate claim");
        if (yes) { await submit(claim, true); return; }
      } else setMsg(t);
    } finally { setBusy(null); }
  };

  const cancel = async (claim: any) => {
    const yes = await confirmYesNo(
      `Cancel claim ${claim.claim_no} (${inr(claim.amount)})?`, "Cancel claim");
    if (!yes) return;
    setBusy(claim.claim_id);
    try { await api(`/expense/claims/${claim.claim_id}/cancel`, { method: "POST", body: {} }); await load(); }
    catch (e: any) { setMsg(String(e?.message || e)); }
    finally { setBusy(null); }
  };

  const shown = claims.filter((c) => {
    if (filter === "all") return true;
    if (filter === "pending") return c.status?.startsWith("pending_");
    return c.status === filter;
  });
  const pendingCount = claims.filter((c) => c.status?.startsWith("pending_")).length;

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.back} testID="exp-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Expense Claims</Text>
          <Text style={s.subtitle}>Reimbursements &amp; claim status</Text>
        </View>
        <Pressable style={s.newBtn} onPress={() => router.push("/expense-claim-form")} testID="exp-new">
          <Ionicons name="add" size={18} color="#fff" />
          <Text style={s.newBtnTxt}>New Claim</Text>
        </Pressable>
      </View>

      <ScrollView
        contentContainerStyle={s.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.brandPrimary} />}
      >
        <View style={s.sumRow}>
          <View style={s.sumBox}><Text style={s.sumLbl}>Claimed</Text>
            <Text style={s.sumVal}>{inr(dash?.total_claimed)}</Text></View>
          <View style={s.sumBox}><Text style={s.sumLbl}>Approved</Text>
            <Text style={[s.sumVal, { color: "#059669" }]}>{inr(dash?.total_approved)}</Text></View>
          <View style={s.sumBox}><Text style={s.sumLbl}>Paid</Text>
            <Text style={[s.sumVal, { color: "#047857" }]}>{inr(dash?.total_paid)}</Text></View>
          <View style={s.sumBox}><Text style={s.sumLbl}>In approval</Text>
            <Text style={[s.sumVal, { color: "#D97706" }]}>{pendingCount}</Text></View>
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 12 }}>
          {FILTERS.map((f) => (
            <Pressable key={f.key} onPress={() => setFilter(f.key)}
              style={[s.chip, filter === f.key && s.chipOn]} testID={`exp-filter-${f.key}`}>
              <Text style={[s.chipTxt, filter === f.key && s.chipTxtOn]}>{f.label}</Text>
            </Pressable>
          ))}
        </ScrollView>

        {msg ? <Text style={s.msg}>{msg}</Text> : null}
        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} /> : null}
        {!loading && shown.length === 0 ? (
          <View style={s.empty}>
            <Ionicons name="receipt-outline" size={38} color={colors.onSurfaceTertiary} />
            <Text style={s.muted}>No expense claims yet.</Text>
            <Pressable style={[s.newBtn, { marginTop: 12 }]} onPress={() => router.push("/expense-claim-form")}>
              <Ionicons name="add" size={18} color="#fff" />
              <Text style={s.newBtnTxt}>Create your first claim</Text>
            </Pressable>
          </View>
        ) : null}

        {shown.map((c) => {
          const meta = STATUS_META[c.status] || STATUS_META.draft;
          const expanded = open === c.claim_id;
          const editable = c.status === "draft" || c.status === "returned";
          return (
            <Pressable key={c.claim_id} style={s.card}
              onPress={() => setOpen(expanded ? null : c.claim_id)} testID={`exp-claim-${c.claim_no}`}>
              <View style={s.cardTop}>
                <Text style={s.claimNo}>{c.claim_no}</Text>
                <Text style={s.cat} numberOfLines={1}>{c.category_name || "—"}</Text>
                <View style={[s.pill, { backgroundColor: `${meta.color}18` }]}>
                  <Text style={[s.pillTxt, { color: meta.color }]}>{meta.label}</Text>
                </View>
              </View>
              <View style={s.amtRow}>
                <View><Text style={s.amtLbl}>Date</Text><Text style={s.amtVal}>{c.expense_date || "—"}</Text></View>
                <View><Text style={s.amtLbl}>Amount</Text><Text style={s.amtVal}>{inr(c.amount)}</Text></View>
                {c.approved_amount != null ? (
                  <View><Text style={s.amtLbl}>Approved</Text>
                    <Text style={[s.amtVal, { color: "#059669" }]}>{inr(c.approved_amount)}</Text></View>) : null}
                {c.paid_amount != null ? (
                  <View><Text style={s.amtLbl}>Paid</Text>
                    <Text style={[s.amtVal, { color: "#047857" }]}>{inr(c.paid_amount)}</Text></View>) : null}
              </View>
              {c.vendor ? <Text style={s.metaLine}>Vendor: {c.vendor}{c.invoice_no ? ` · Inv ${c.invoice_no}` : ""}</Text> : null}

              {expanded ? (
                <View style={{ marginTop: 10 }}>
                  {c.description ? <Text style={s.desc}>{c.description}</Text> : null}
                  {(c.attachments || []).length > 0 ? (
                    <View style={{ marginTop: 6 }}>
                      <Text style={s.secTitle}>Receipts</Text>
                      {(c.attachments || []).map((a: any) => (
                        <Pressable key={a.doc_id} style={s.attRow} onPress={() => openReceipt(c.claim_id, a.doc_id)}>
                          <Ionicons name="document-attach-outline" size={16} color={colors.brandPrimary} />
                          <Text style={s.attTxt}>{a.file_name}</Text>
                        </Pressable>
                      ))}
                    </View>
                  ) : null}
                  {(c.approvals || []).length > 0 ? (
                    <View style={{ marginTop: 6 }}>
                      <Text style={s.secTitle}>Approval trail</Text>
                      {(c.approvals || []).map((a: any, i: number) => (
                        <View key={i} style={s.trailRow}>
                          <Ionicons
                            name={a.action === "approve" ? "checkmark-circle" : a.action === "reject" ? "close-circle" : "return-up-back"}
                            size={15}
                            color={a.action === "approve" ? "#059669" : a.action === "reject" ? "#DC2626" : "#B45309"} />
                          <Text style={s.trailTxt}>
                            {a.by_name || a.role} · {a.stage.replace("pending_", "")} · {a.action}
                            {a.remarks ? ` — “${a.remarks}”` : ""}
                          </Text>
                        </View>
                      ))}
                    </View>
                  ) : null}
                  {c.payment_reference || c.payment_date ? (
                    <Text style={s.metaLine}>
                      Payment: {c.payment_mode || "—"} · {c.payment_date || ""}
                      {c.payment_reference ? ` · Ref ${c.payment_reference}` : ""}
                    </Text>
                  ) : null}

                  <View style={s.btnRow}>
                    {editable ? (
                      <>
                        <Pressable style={[s.aBtn, { backgroundColor: colors.brandPrimary }]}
                          disabled={busy === c.claim_id}
                          onPress={() => submit(c)} testID={`exp-submit-${c.claim_no}`}>
                          {busy === c.claim_id ? <ActivityIndicator size="small" color="#fff" /> :
                            <Text style={s.aBtnTxt}>Submit for approval</Text>}
                        </Pressable>
                        <Pressable style={[s.aBtn, s.aBtnLight]}
                          onPress={() => router.push(`/expense-claim-form?claim_id=${c.claim_id}` as any)}>
                          <Text style={[s.aBtnTxt, { color: colors.onSurface }]}>Edit</Text>
                        </Pressable>
                      </>
                    ) : null}
                    {(editable || c.status === "pending_manager") ? (
                      <Pressable style={[s.aBtn, s.aBtnDanger]} onPress={() => cancel(c)}>
                        <Text style={[s.aBtnTxt, { color: "#DC2626" }]}>Cancel</Text>
                      </Pressable>
                    ) : null}
                  </View>
                </View>
              ) : null}
              <Text style={s.expandHint}>{expanded ? "Tap to collapse" : "Tap for details & actions"}</Text>
            </Pressable>
          );
        })}
        <View style={{ height: 40 }} />
      </ScrollView>
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
  back: { padding: 4 },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceTertiary },
  newBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brandPrimary, borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 8, minHeight: 44, justifyContent: "center",
  },
  newBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  body: { padding: 16 },
  sumRow: { flexDirection: "row", gap: 8, marginBottom: 14, flexWrap: "wrap" },
  sumBox: {
    flex: 1, minWidth: 80, backgroundColor: colors.surface, borderRadius: 12,
    padding: 10, borderWidth: 1, borderColor: colors.border,
  },
  sumLbl: { fontSize: 11, color: colors.onSurfaceTertiary, fontWeight: "700" },
  sumVal: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginTop: 2 },
  chip: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, marginRight: 8,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  msg: { fontSize: 12.5, color: "#059669", fontWeight: "700", marginBottom: 8 },
  empty: { alignItems: "center", paddingVertical: 40 },
  muted: { color: colors.onSurfaceTertiary, marginTop: 8, fontSize: 13 },
  card: {
    backgroundColor: colors.surface, borderRadius: 14, padding: 14,
    borderWidth: 1, borderColor: colors.border, marginBottom: 10,
  },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  claimNo: { fontSize: 12.5, fontWeight: "800", color: colors.brandPrimary },
  cat: { flex: 1, fontSize: 13, fontWeight: "700", color: colors.onSurface },
  pill: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  pillTxt: { fontSize: 10, fontWeight: "800" },
  amtRow: { flexDirection: "row", gap: 18, marginTop: 8, flexWrap: "wrap" },
  amtLbl: { fontSize: 10.5, color: colors.onSurfaceTertiary, fontWeight: "700" },
  amtVal: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface, marginTop: 1 },
  metaLine: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 6 },
  desc: { fontSize: 12.5, color: colors.onSurfaceSecondary },
  secTitle: { fontSize: 11.5, fontWeight: "800", color: colors.onSurfaceTertiary, marginBottom: 4, marginTop: 4, textTransform: "uppercase" },
  attRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 5 },
  attTxt: { fontSize: 12.5, color: colors.brandPrimary, fontWeight: "700" },
  trailRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 3 },
  trailTxt: { fontSize: 12, color: colors.onSurfaceSecondary, flex: 1 },
  btnRow: { flexDirection: "row", gap: 8, marginTop: 12, flexWrap: "wrap" },
  aBtn: {
    borderRadius: 10, paddingHorizontal: 14, paddingVertical: 10,
    minHeight: 44, alignItems: "center", justifyContent: "center",
  },
  aBtnLight: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  aBtnDanger: { backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FECACA" },
  aBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  expandHint: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 8, textAlign: "center" },
});
