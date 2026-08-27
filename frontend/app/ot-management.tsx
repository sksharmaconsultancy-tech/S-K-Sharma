/**
 * Iter 746 — OT MANAGEMENT (user PRD Phase 2).
 * Tabs: Policy config | Entries & Approvals | Reports.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Redirect } from "expo-router";
import { api, apiBinary } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

const ym = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const LEVELS = [["primary_manager", "Reporting Manager"], ["secondary_manager", "Functional Manager"], ["dept_head", "Dept Head"], ["hr_manager", "HR/Payroll"], ["final_approver", "Final Approver"], ["admin", "Admin"]];
const ROUND = [["none", "None"], ["down_15", "Down 15m"], ["down_30", "Down 30m"], ["nearest_15", "Nearest 15m"], ["nearest_30", "Nearest 30m"]];
const STATUSES = ["", "pending", "approved", "rejected", "cancelled", "payroll_processed"];

export default function OtManagementScreen() {
  const { user, loading: authLoading } = useAuth();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [tab, setTab] = useState<"policy" | "approvals" | "reports">("policy");
  const [pol, setPol] = useState<any>(null);
  const [month, setMonth] = useState(ym());
  const [entries, setEntries] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [statusF, setStatusF] = useState("");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const cid = user?.role === "company_admin" ? user.company_id : companyId;

  const loadPolicy = useCallback(async () => {
    if (!cid) return;
    try { const r = await api<any>(`/ot/policy?company_id=${cid}`); setPol(r.policy); } catch { setPol(null); }
  }, [cid]);
  useEffect(() => { loadPolicy(); }, [loadPolicy]);

  const loadEntries = useCallback(async () => {
    if (!cid) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api<any>(`/ot/entries?company_id=${cid}&month=${month}${statusF ? `&status=${statusF}` : ""}`);
      setEntries(r.entries || []); setSummary(r.summary || null); setSel(new Set());
      if (!(r.entries || []).length) setMsg("Koi OT entry nahi — pehle 'OT Generate' karein");
    } catch (e: any) { setMsg(e?.message || "Load failed"); }
    finally { setBusy(false); }
  }, [cid, month, statusF]);
  useEffect(() => { if (tab === "approvals") loadEntries(); }, [tab, loadEntries]);

  if (authLoading) return <View style={st.center}><ActivityIndicator /></View>;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role)) return <Redirect href="/" />;

  const setP = (patch: any) => setPol({ ...(pol || {}), ...patch });
  const savePolicy = async () => {
    if (!cid || !pol) return;
    setBusy(true); setMsg(null);
    try {
      await api("/ot/policy", { method: "POST", body: { ...pol, company_id: cid, branch_id: null } });
      setMsg("✅ OT Policy saved"); loadPolicy();
    } catch (e: any) { setMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };
  const generate = async () => {
    if (!cid) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api<any>("/ot/generate", { method: "POST", body: { company_id: cid, month } });
      setMsg(`✅ Generated: ${r.created} new, ${r.updated} updated, ${r.kept_finalised} finalised kept`);
      loadEntries();
    } catch (e: any) { setMsg(e?.message || "Generate failed"); }
    finally { setBusy(false); }
  };
  const act = async (action: string) => {
    if (!cid || !sel.size) { setMsg("Pehle entries select karein"); return; }
    const remarks = action === "reject" ? "Rejected by admin" : "";
    setBusy(true);
    try {
      const path = action === "resubmit" ? "/ot/resubmit" : "/ot/action";
      await api(path, { method: "POST", body: { company_id: cid, entry_ids: Array.from(sel), action, remarks } });
      setMsg(`✅ ${action} done (${sel.size})`); loadEntries();
    } catch (e: any) { setMsg(e?.message || "Action failed"); }
    finally { setBusy(false); }
  };
  const dl = async (kind: string, fmt: string) => {
    try {
      const r = await apiBinary(`/ot/report?kind=${kind}&fmt=${fmt}&company_id=${cid}&month=${month}`);
      if (Platform.OS === "web" && (r as any).webBlobUrl) {
        const a = document.createElement("a");
        a.href = (r as any).webBlobUrl; a.download = `ot_${kind}_${month}.${fmt}`; a.click();
      }
    } catch (e: any) { setMsg(e?.message || "Download failed"); }
  };
  const toggleSel = (id: string) => {
    const n = new Set(sel);
    if (n.has(id)) n.delete(id); else n.add(id);
    setSel(n);
  };
  const num = (l: string, k: string, step = 1) => (
    <View style={st.numRow} key={k}>
      <Text style={st.lbl}>{l}</Text>
      <View style={st.row}>
        <Pressable style={st.stepBtn} onPress={() => setP({ [k]: Math.max(0, Number(pol?.[k] || 0) - step) })}><Text style={st.stepTxt}>−</Text></Pressable>
        <Text style={st.numVal}>{String(pol?.[k] ?? 0)}</Text>
        <Pressable style={st.stepBtn} onPress={() => setP({ [k]: Number(pol?.[k] || 0) + step })}><Text style={st.stepTxt}>+</Text></Pressable>
      </View>
    </View>
  );
  const tog = (l: string, k: string, hint?: string) => (
    <Pressable key={k} style={st.togRow} onPress={() => setP({ [k]: !pol?.[k] })} testID={`otp-${k}`}>
      <View style={{ flex: 1 }}>
        <Text style={st.lbl}>{l}</Text>
        {hint ? <Text style={st.hint}>{hint}</Text> : null}
      </View>
      <View style={[st.tg, pol?.[k] && st.tgOn]}><View style={[st.knob, pol?.[k] && st.knobOn]} /></View>
    </Pressable>
  );

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={st.body}>
        <Text style={st.h1}>⏱️ OT Management</Text>
        {user.role !== "company_admin" && <CompanyPicker value={companyId} onChange={setCompanyId} />}
        <View style={st.tabs}>
          {([["policy", "OT Policy"], ["approvals", "Entries & Approval"], ["reports", "Reports"]] as [any, string][]).map(([t, l]) => (
            <Pressable key={t} style={[st.tab, tab === t && st.tabOn]} onPress={() => setTab(t)} testID={`ot-tab-${t}`}>
              <Text style={[st.tabTxt, tab === t && st.tabTxtOn]}>{l}</Text>
            </Pressable>
          ))}
        </View>
        {msg ? <Text style={st.msg}>{msg}</Text> : null}

        {tab === "policy" && pol ? (
          <View style={st.card}>
            {tog("Enable OT Policy", "enabled", "OFF = purana system (grid OT seedha payroll) waisa hi chalega")}
            {pol.enabled ? (<>
              {tog("Approval Required", "approval_required", "ON hone par payroll me sirf APPROVED OT jayega — unapproved/excess kabhi silently nahi")}
              {num("Minimum OT (minutes) — isse kam = not eligible", "min_ot_minutes", 5)}
              {num("Monthly OT Cap (hours) — default 48", "max_ot_hours_month", 1)}
              {num("Weekly OT Limit (hours, 0 = none)", "weekly_limit_hours", 1)}
              {num("Normal Working Hours / day", "normal_working_hours", 0.5)}
              {num("OT Rate Multiplier (1 = single, 2 = double)", "ot_rate_multiplier", 0.5)}
              <Text style={st.lbl}>OT Rounding</Text>
              <View style={st.chips}>
                {ROUND.map(([v, l]) => (
                  <Pressable key={v} style={[st.chip, pol.rounding === v && st.chipOn]} onPress={() => setP({ rounding: v })}>
                    <Text style={[st.chipTxt, pol.rounding === v && st.chipTxtOn]}>{l}</Text>
                  </Pressable>
                ))}
              </View>
              {tog("Holiday OT allowed", "holiday_ot")}
              {tog("Weekly-Off OT allowed", "weekly_off_ot")}
              {tog("Admin Override allowed", "allow_override", "Policy cap ke upar admin reason ke saath override kar sakta hai")}
              <Text style={st.lbl}>Approval Levels (sequence — tap to add/remove)</Text>
              <View style={st.chips}>
                {LEVELS.map(([v, l]) => {
                  const on = (pol.approval_levels || []).includes(v);
                  const idx = (pol.approval_levels || []).indexOf(v);
                  return (
                    <Pressable key={v} style={[st.chip, on && st.chipOn]} testID={`otp-lvl-${v}`}
                      onPress={() => setP({ approval_levels: on ? pol.approval_levels.filter((x: string) => x !== v) : [...(pol.approval_levels || []), v] })}>
                      <Text style={[st.chipTxt, on && st.chipTxtOn]}>{on ? `${idx + 1}. ` : ""}{l}</Text>
                    </Pressable>
                  );
                })}
              </View>
              <Text style={st.hint}>Har company ke liye levels alag set kar sakte ho — sab levels force nahi. Chain Employee Master ke Reporting Structure se auto-derive hoti hai.</Text>
              <View style={st.inRow}>
                <Text style={st.lbl}>Applicable Departments (comma, blank = all)</Text>
                <TextInput style={st.input} value={(pol.departments || []).join(", ")}
                  onChangeText={(t) => setP({ departments: t.split(",").map((x) => x.trim()).filter(Boolean) })}
                  placeholder="e.g. PRODUCTION, PACKING" placeholderTextColor={colors.onSurfaceTertiary} />
              </View>
              <View style={st.inRow}>
                <Text style={st.lbl}>Applicable Employee Types (comma, blank = all)</Text>
                <TextInput style={st.input} value={(pol.employee_types || []).join(", ")}
                  onChangeText={(t) => setP({ employee_types: t.split(",").map((x) => x.trim()).filter(Boolean) })}
                  placeholder="e.g. LABOUR" placeholderTextColor={colors.onSurfaceTertiary} />
              </View>
              <View style={st.inRow}>
                <Text style={st.lbl}>Custom Rules Note</Text>
                <TextInput style={st.input} value={pol.custom_note || ""} onChangeText={(t) => setP({ custom_note: t })}
                  placeholder="koi special rule likhein" placeholderTextColor={colors.onSurfaceTertiary} />
              </View>
            </>) : null}
            <Pressable style={st.btn} onPress={savePolicy} testID="otp-save">
              {busy ? <ActivityIndicator color="#fff" size="small" /> : <Text style={st.btnTxt}>Save OT Policy</Text>}
            </Pressable>
          </View>
        ) : null}

        {tab === "approvals" ? (
          <View style={st.card}>
            <View style={st.row}>
              <TextInput style={[st.input, { width: 100 }]} value={month} onChangeText={setMonth} placeholder="YYYY-MM" placeholderTextColor={colors.onSurfaceTertiary} />
              <Pressable style={st.btnSm} onPress={generate} testID="ot-generate"><Text style={st.btnTxt}>OT Generate</Text></Pressable>
              <Pressable style={[st.btnSm, { backgroundColor: colors.surfaceElevated }]} onPress={loadEntries}><Text style={[st.btnTxt, { color: colors.onSurface }]}>Refresh</Text></Pressable>
            </View>
            <View style={st.chips}>
              {STATUSES.map((s) => (
                <Pressable key={s || "all"} style={[st.chip, statusF === s && st.chipOn]} onPress={() => setStatusF(s)}>
                  <Text style={[st.chipTxt, statusF === s && st.chipTxtOn]}>{s || "all"}</Text>
                </Pressable>
              ))}
            </View>
            {summary ? (
              <Text style={st.sum}>
                Att OT {summary.attendance_ot}h · Eligible {summary.eligible_ot}h · Excess {summary.excess_ot}h · Approved {summary.approved_ot}h · Pending {summary.pending_ot}h · Rejected {summary.rejected_ot}h · Payroll {summary.payroll_ot}h · Cost ₹{summary.ot_cost} · Cap violations {summary.cap_violations}
              </Text>
            ) : null}
            <View style={st.row}>
              <Pressable style={[st.btnSm, { backgroundColor: "#2e7d32" }]} onPress={() => act("approve")} testID="ot-approve"><Text style={st.btnTxt}>Approve ({sel.size})</Text></Pressable>
              <Pressable style={[st.btnSm, { backgroundColor: "#b3261e" }]} onPress={() => act("reject")} testID="ot-reject"><Text style={st.btnTxt}>Reject</Text></Pressable>
              <Pressable style={[st.btnSm, { backgroundColor: "#6a5acd" }]} onPress={() => act("resubmit")}><Text style={st.btnTxt}>Re-submit</Text></Pressable>
              <Pressable style={[st.btnSm, { backgroundColor: "#555" }]} onPress={() => act("cancel")}><Text style={st.btnTxt}>Cancel</Text></Pressable>
            </View>
            {busy ? <ActivityIndicator style={{ marginTop: 12 }} /> : null}
            <ScrollView horizontal>
              <View>
                <View style={[st.tr, st.th]}>
                  {["✔", "Code", "Name", "Date", "In", "Out", "Att OT", "Eligible", "Excess", "Type", "Rate", "Amount", "Level", "Status", "Reason"].map((h, i) => (
                    <Text key={h} style={[st.td, st.thTxt, { width: [34, 52, 130, 84, 48, 48, 56, 60, 56, 66, 50, 64, 46, 100, 120][i] }]}>{h}</Text>
                  ))}
                </View>
                {entries.map((e) => (
                  <Pressable key={e.entry_id} style={[st.tr, sel.has(e.entry_id) && { backgroundColor: "#26324a" }]} onPress={() => toggleSel(e.entry_id)}>
                    <Text style={[st.td, { width: 34 }]}>{sel.has(e.entry_id) ? "☑" : "☐"}</Text>
                    <Text style={[st.td, { width: 52 }]}>{e.employee_code}</Text>
                    <Text style={[st.td, { width: 130 }]} numberOfLines={1}>{e.name}</Text>
                    <Text style={[st.td, { width: 84 }]}>{e.date}</Text>
                    <Text style={[st.td, { width: 48 }]}>{e.in_time || "-"}</Text>
                    <Text style={[st.td, { width: 48 }]}>{e.out_time || "-"}</Text>
                    <Text style={[st.td, { width: 56 }]}>{e.attendance_ot_hours}</Text>
                    <Text style={[st.td, { width: 60, color: "#7dc97d" }]}>{e.eligible_ot_hours}</Text>
                    <Text style={[st.td, { width: 56, color: e.excess_ot_hours > 0 ? "#ff8a80" : st.td.color }]}>{e.excess_ot_hours}</Text>
                    <Text style={[st.td, { width: 66 }]}>{e.ot_type}</Text>
                    <Text style={[st.td, { width: 50 }]}>{e.ot_rate}</Text>
                    <Text style={[st.td, { width: 64 }]}>{e.ot_amount}</Text>
                    <Text style={[st.td, { width: 46 }]}>{e.approval_level || "-"}</Text>
                    <Text style={[st.td, { width: 100 }]}>{e.status}</Text>
                    <Text style={[st.td, { width: 120 }]} numberOfLines={1}>{e.ot_reason || e.rejection_reason || ""}</Text>
                  </Pressable>
                ))}
              </View>
            </ScrollView>
          </View>
        ) : null}

        {tab === "reports" ? (
          <View style={st.card}>
            <View style={st.row}>
              <TextInput style={[st.input, { width: 100 }]} value={month} onChangeText={setMonth} placeholder="YYYY-MM" placeholderTextColor={colors.onSurfaceTertiary} />
            </View>
            {[["register", "OT Register"], ["employee", "Employee-wise OT"], ["department", "Department-wise OT"], ["branch", "Branch-wise OT"], ["approved", "Approved OT"], ["pending", "Pending OT"], ["rejected", "Rejected OT"], ["excess", "Excess / Cap Violation"], ["cost", "OT Cost"], ["history", "Approval History"]].map(([k, l]) => (
              <View key={k} style={st.repRow}>
                <Text style={[st.lbl, { flex: 1 }]}>{l}</Text>
                <Pressable style={st.btnXs} onPress={() => dl(k, "xlsx")}><Text style={st.btnTxt}>Excel</Text></Pressable>
                <Pressable style={[st.btnXs, { backgroundColor: "#b3261e" }]} onPress={() => dl(k, "pdf")}><Text style={st.btnTxt}>PDF</Text></Pressable>
              </View>
            ))}
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background },
  body: { padding: spacing.lg, paddingBottom: 80 },
  h1: { fontSize: 20, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  tabs: { flexDirection: "row", gap: 8, marginVertical: 10, flexWrap: "wrap" },
  tab: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md, backgroundColor: colors.surfaceElevated },
  tabOn: { backgroundColor: colors.cta },
  tabTxt: { color: colors.onSurfaceSecondary, fontWeight: "700", fontSize: 13 },
  tabTxtOn: { color: "#fff" },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, marginTop: 8 },
  row: { flexDirection: "row", gap: 8, alignItems: "center", marginVertical: 6, flexWrap: "wrap" },
  lbl: { color: colors.onSurface, fontSize: 13, fontWeight: "600" },
  hint: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },
  msg: { color: "#ffd54f", marginVertical: 6, fontSize: 13 },
  sum: { color: colors.onSurfaceSecondary, fontSize: 12, marginVertical: 8, lineHeight: 18 },
  numRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginVertical: 6 },
  stepBtn: { width: 32, height: 32, borderRadius: 8, backgroundColor: colors.surfaceElevated, alignItems: "center", justifyContent: "center" },
  stepTxt: { color: colors.onSurface, fontSize: 18, fontWeight: "800" },
  numVal: { color: colors.onSurface, fontWeight: "800", minWidth: 44, textAlign: "center" },
  togRow: { flexDirection: "row", alignItems: "center", marginVertical: 8, gap: 8 },
  tg: { width: 44, height: 24, borderRadius: 12, backgroundColor: "#444", padding: 2 },
  tgOn: { backgroundColor: colors.cta },
  knob: { width: 20, height: 20, borderRadius: 10, backgroundColor: "#999" },
  knobOn: { backgroundColor: "#fff", alignSelf: "flex-end" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginVertical: 8 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 14, backgroundColor: colors.surfaceElevated },
  chipOn: { backgroundColor: colors.cta },
  chipTxt: { color: colors.onSurfaceSecondary, fontSize: 12 },
  chipTxtOn: { color: "#fff", fontWeight: "700" },
  inRow: { marginVertical: 6 },
  input: { backgroundColor: colors.surfaceElevated, color: colors.onSurface, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 8, marginTop: 4, fontSize: 13 },
  btn: { backgroundColor: colors.cta, borderRadius: radius.md, paddingVertical: 12, alignItems: "center", marginTop: 14 },
  btnSm: { backgroundColor: colors.cta, borderRadius: radius.md, paddingVertical: 9, paddingHorizontal: 12, alignItems: "center" },
  btnXs: { backgroundColor: "#2e7d32", borderRadius: radius.sm, paddingVertical: 6, paddingHorizontal: 10 },
  btnTxt: { color: "#fff", fontWeight: "700", fontSize: 12 },
  repRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 7, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: "#333" },
  tr: { flexDirection: "row", borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: "#333", paddingVertical: 5 },
  th: { backgroundColor: colors.surfaceElevated },
  thTxt: { fontWeight: "800" },
  td: { color: colors.onSurfaceSecondary, fontSize: 11, paddingHorizontal: 3 },
});
