/**
 * Iter 741 — PROBATION → CONFIRMATION dashboard (firm-wise policy,
 * auto due-dates from DOJ, confirm / extend workflow, immutable history,
 * confirmation & extension letters via existing HR Letters module).
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, apiBinary } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";
import { BmField, BmBtn, BmChip, bm, showWebMsg } from "@/src/components/firmMaster/branchMasterUi";

const ST_LABEL: Record<string, { l: string; c: string }> = {
  on_probation: { l: "On Probation", c: "#2563EB" },
  due_soon: { l: "Due Soon", c: "#B45309" },
  overdue: { l: "OVERDUE", c: "#B91C1C" },
  extended: { l: "Extended", c: "#7C3AED" },
  confirmed: { l: "Confirmed", c: "#15803D" },
};

export default function ProbationScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const cid = user?.role === "company_admin" ? user.company_id : companyId;
  const [data, setData] = useState<any>(null);
  const [fStatus, setFStatus] = useState("");
  const [action, setAction] = useState<{ kind: "init" | "confirm" | "extend"; emp: any } | null>(null);
  const [histOf, setHistOf] = useState<any>(null);
  const [hist, setHist] = useState<any[]>([]);

  const load = useCallback(async () => {
    if (!cid) return;
    try {
      const qs = new URLSearchParams({ company_id: cid });
      if (fStatus) qs.set("status", fStatus);
      setData(await api<any>(`/admin/probation/list?${qs.toString()}`));
    } catch { /* ignore */ }
  }, [cid, fStatus]);
  useEffect(() => { load(); }, [load]);

  const exportXlsx = async () => {
    try {
      const r = await apiBinary(`/admin/probation/export?company_id=${cid}`);
      if (Platform.OS === "web" && r.webBlobUrl) {
        const a = document.createElement("a");
        a.href = r.webBlobUrl; a.download = "Confirmation_Due_Report.xlsx"; a.click();
      }
    } catch (e: any) { showWebMsg(e?.message || "Export failed"); }
  };

  const openHistory = async (emp: any) => {
    setHistOf(emp);
    try {
      const r = await api<any>(`/admin/probation/history/${emp.user_id}`);
      setHist(r.history || []);
    } catch { setHist([]); }
  };

  const counts = data?.counts || {};
  const cards = [
    { k: "", l: "On Probation", v: counts.total_probation },
    { k: "due_soon", l: "Due Soon (30d)", v: counts.due_soon, c: "#B45309" },
    { k: "overdue", l: "Overdue", v: counts.overdue, c: "#B91C1C" },
    { k: "extended", l: "Extended", v: counts.extended, c: "#7C3AED" },
    { k: "confirmed", l: "Confirmed", v: counts.confirmed_this_month, c: "#15803D" },
  ];

  return (
    <SafeAreaView style={s.root}>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        <View style={s.head}>
          <Text style={s.title}>Probation → Confirmation</Text>
          <BmBtn label="Export Report" kind="ghost" icon="download-outline" small onPress={exportXlsx} testID="pb-export" />
        </View>
        {user?.role !== "company_admin" ? (
          <CompanyPicker value={companyId || "all"} onChange={(v: any) => setCompanyId(v === "all" ? null : v)} allowAll={false} />
        ) : null}
        {!cid ? <Text style={s.hint}>Select a firm to begin.</Text> : !data ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 20 }} />
        ) : (
          <>
            <View style={s.cards}>
              {cards.map((c) => (
                <Pressable key={c.l} style={s.card} onPress={() => setFStatus(c.k)}
                           testID={`pb-card-${c.l.replace(/\W+/g, "-")}`}>
                  <Text style={[s.cardV, c.c ? { color: c.c } : null]}>{c.v ?? 0}</Text>
                  <Text style={s.cardL}>{c.l}</Text>
                </Pressable>
              ))}
            </View>
            <View style={[bm.chipsWrap, { marginVertical: 8 }]}>
              {["", "on_probation", "due_soon", "overdue", "extended", "confirmed"].map((k) => (
                <BmChip key={k || "all"} label={k ? ST_LABEL[k].l : "All (probation)"} on={fStatus === k}
                        onPress={() => setFStatus(k)} />
              ))}
            </View>
            {(data.employees || []).map((e: any) => {
              const st = ST_LABEL[e.probation_status] || ST_LABEL.on_probation;
              return (
                <View key={e.user_id} style={s.row} testID={`pb-emp-${e.user_id}`}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.name}>{e.employee_code ? `${e.employee_code} · ` : ""}{e.name}</Text>
                    <Text style={s.meta}>
                      DOJ {e.doj || e.date_of_joining || "—"} · {e.probation_months || "—"} months
                      {e.confirmation_due ? ` · Due ${e.confirmation_due}` : ""}
                      {e.days_remaining != null ? ` (${e.days_remaining}d)` : ""}
                    </Text>
                  </View>
                  <Text style={[s.st, { color: st.c }]}>{st.l}</Text>
                  <BmBtn label="Set" kind="ghost" small onPress={() => setAction({ kind: "init", emp: e })} testID={`pb-set-${e.user_id}`} />
                  {e.probation_status !== "confirmed" ? (
                    <>
                      <BmBtn label="Confirm" small onPress={() => setAction({ kind: "confirm", emp: e })} testID={`pb-confirm-${e.user_id}`} />
                      <BmBtn label="Extend" kind="ghost" small onPress={() => setAction({ kind: "extend", emp: e })} testID={`pb-extend-${e.user_id}`} />
                    </>
                  ) : (
                    <BmBtn label="Letter" kind="ghost" small icon="document-text-outline"
                           onPress={() => router.push(`/hr-letters?letter_type=confirmation&user_id=${e.user_id}` as any)} />
                  )}
                  <BmBtn label="History" kind="ghost" small onPress={() => openHistory(e)} />
                </View>
              );
            })}
            {(data.employees || []).length === 0 ? (
              <Text style={s.hint}>कोई employee probation tracking में नहीं — &quot;Set&quot; से probation assign करें (Employee की DOJ से due date अपने आप निकलेगी). Filter &quot;All (probation)&quot; में सिर्फ probation वाले दिखते हैं.</Text>
            ) : null}
          </>
        )}
        {action ? (
          <ActionPanel cid={cid!} action={action}
                       onDone={() => { setAction(null); load(); }}
                       onCancel={() => setAction(null)} />
        ) : null}
        {histOf ? (
          <View style={s.panel}>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={s.panelT}>History — {histOf.name}</Text>
              <Pressable onPress={() => setHistOf(null)}><Ionicons name="close" size={18} color={colors.onSurfaceSecondary} /></Pressable>
            </View>
            {hist.map((h) => (
              <Text key={h.hist_id} style={s.meta}>
                {String(h.at || "").slice(0, 10)} · {h.action} · by {h.by_name}
                {h.reason ? ` · ${h.reason}` : ""}{h.new?.due ? ` · due→${h.new.due}` : ""}
              </Text>
            ))}
            {hist.length === 0 ? <Text style={s.meta}>No history.</Text> : null}
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function ActionPanel({ cid, action, onDone, onCancel }: {
  cid: string; action: { kind: "init" | "confirm" | "extend"; emp: any };
  onDone: () => void; onCancel: () => void;
}) {
  const { kind, emp } = action;
  const [months, setMonths] = useState(String(emp.probation_months || 6));
  const [cdate, setCdate] = useState(new Date().toISOString().slice(0, 10));
  const [reason, setReason] = useState("");
  const [remarks, setRemarks] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      if (kind === "init") {
        await api("/admin/probation/init", { method: "POST", body: {
          company_id: cid, user_id: emp.user_id, probation_months: parseInt(months, 10) || 6 } });
      } else if (kind === "confirm") {
        await api("/admin/probation/confirm", { method: "POST", body: {
          company_id: cid, user_id: emp.user_id, confirmation_date: cdate, remarks } });
      } else {
        if (!reason.trim()) { showWebMsg("Extension के लिए reason ज़रूरी है"); setBusy(false); return; }
        await api("/admin/probation/extend", { method: "POST", body: {
          company_id: cid, user_id: emp.user_id, extension_months: parseInt(months, 10) || 1,
          reason, remarks } });
      }
      onDone();
    } catch (e: any) { showWebMsg(e?.message || "Failed"); }
    finally { setBusy(false); }
  };
  return (
    <View style={s.panel} testID="pb-action-panel">
      <Text style={s.panelT}>
        {kind === "init" ? "Set Probation" : kind === "confirm" ? "Confirm Employee" : "Extend Probation"} — {emp.name}
      </Text>
      <View style={bm.row}>
        {kind !== "confirm" ? (
          <BmField label={kind === "extend" ? "Extension months" : "Probation months"}
                   value={months} onChangeText={setMonths} keyboardType="number-pad" width={150}
                   testID="pb-months" />
        ) : (
          <BmField label="Confirmation Date (YYYY-MM-DD)" value={cdate} onChangeText={setCdate} width={200} testID="pb-cdate" />
        )}
        {kind === "extend" ? (
          <BmField label="Reason *" value={reason} onChangeText={setReason} testID="pb-reason" />
        ) : null}
        {kind !== "init" ? (
          <BmField label="Remarks" value={remarks} onChangeText={setRemarks} />
        ) : null}
      </View>
      <View style={{ flexDirection: "row", gap: 8, justifyContent: "flex-end" }}>
        <BmBtn label="Cancel" kind="ghost" onPress={onCancel} />
        <BmBtn label={kind === "init" ? "Save" : kind === "confirm" ? "Confirm ✓" : "Extend"}
               onPress={go} busy={busy} testID="pb-go" />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  title: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  hint: { fontSize: 12.5, color: colors.onSurfaceTertiary, marginVertical: 10 },
  cards: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  card: { minWidth: 120, flexGrow: 1, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: 10, backgroundColor: colors.surface },
  cardV: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  cardL: { fontSize: 10.5, fontWeight: "700", color: colors.onSurfaceTertiary },
  row: { flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1,
    borderColor: colors.border, borderRadius: radius.md, padding: 9, marginBottom: 6,
    backgroundColor: colors.surface, flexWrap: "wrap" },
  name: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  meta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  st: { fontSize: 11, fontWeight: "800" },
  panel: { borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    padding: spacing.sm, marginTop: 10, backgroundColor: colors.surface },
  panelT: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
});
