/**
 * Iter 706 — Admin → Tour Management.
 * Tabs: Requests (approve/reject fallback) · Live Tracking · All Tours ·
 * Settings (tracking interval + OD attendance policy).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform, Alert, Switch, Linking,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors } from "@/src/theme";
import { STATUS_META } from "./my-tours";

const toast = (m: string) => (Platform.OS === "web" ? window.alert(m) : Alert.alert("Tours", m));
const TABS = [["requests", "Requests"], ["live", "Live Tracking"], ["all", "All Tours"],
  ["report", "Report"], ["advances", "Advances"], ["settings", "Settings"]] as const;
const monthShift = (m: string, d: number) => {
  const [y, mm] = m.split("-").map(Number);
  const dt = new Date(y, mm - 1 + d, 1);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`;
};

export default function TourAdmin() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const role = user?.role as string;
  const [companyId, setCompanyId] = useState<string>(
    role === "company_admin" ? (user?.company_id || "") : (selectedCompanyId || ""));
  const [tab, setTab] = useState<string>("requests");
  const [data, setData] = useState<any>(null);
  const [live, setLive] = useState<any[]>([]);
  const [settings, setSettings] = useState<any>(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  // Iter 707 — monthly report + advance payouts.
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [report, setReport] = useState<any>(null);
  const [advances, setAdvances] = useState<any>(null);
  const [advFilter, setAdvFilter] = useState("all");

  useEffect(() => {
    if (role !== "company_admin" && selectedCompanyId) setCompanyId(selectedCompanyId);
  }, [selectedCompanyId, role]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = companyId ? `?company_id=${companyId}` : "";
      const [l, lv, st] = await Promise.all([
        api<any>(`/tours/admin/list${qs}`),
        api<any>(`/tours/admin/live${qs}`),
        companyId ? api<any>(`/tours/admin/settings?company_id=${companyId}`).catch(() => null) : Promise.resolve(null),
      ]);
      setData(l); setLive(lv.active_tours || []); if (st) setSettings(st.settings);
    } catch (e: any) { toast(e?.message || "Failed to load"); }
    finally { setLoading(false); }
  }, [companyId]);
  useEffect(() => { load(); }, [load]);

  // Iter 707 — lazy loads for Report / Advances tabs.
  useEffect(() => {
    if (tab !== "report" || !companyId) return;
    api<any>(`/tours/admin/report?company_id=${companyId}&month=${month}`)
      .then(setReport).catch((e: any) => toast(e?.message || "Report failed"));
  }, [tab, companyId, month]);
  useEffect(() => {
    if (tab !== "advances") return;
    const qs = companyId ? `?company_id=${companyId}` : "";
    api<any>(`/tours/admin/advances${qs}`)
      .then(setAdvances).catch((e: any) => toast(e?.message || "Advances failed"));
  }, [tab, companyId, busy]);

  const payAdvance = async (t: any) => {
    let mode = "bank", reference = "";
    if (Platform.OS === "web") {
      mode = window.prompt("Payment mode (cash / bank / upi):", "bank") || "bank";
      reference = window.prompt("Reference / UTR (optional):") || "";
    }
    setBusy(t.tour_id);
    try {
      await api(`/tours/${t.tour_id}/advance/pay`, { method: "POST", body: { mode, reference } });
      toast(`Advance ₹${t.advance_payout?.amount} marked PAID ✓`);
    } catch (e: any) { toast(e?.message || "Pay failed"); }
    finally { setBusy(""); }
  };
  const settleAdvance = async (t: any) => {
    if (Platform.OS === "web" && !window.confirm(
      `Settle ${t.tour_no}? Approved expenses ₹${t.expenses_approved} vs advance ₹${t.advance_payout?.amount}.`)) return;
    setBusy(t.tour_id);
    try {
      const r = await api<any>(`/tours/${t.tour_id}/advance/settle`, { method: "POST", body: {} });
      toast(`Settled ✓ Balance ${r.balance >= 0 ? `₹${r.balance} payable to employee` : `₹${Math.abs(r.balance)} recoverable`}`);
    } catch (e: any) { toast(e?.message || "Settle failed"); }
    finally { setBusy(""); }
  };
  const downloadReport = async () => {
    const { readAuthToken, getApiBaseUrl } = await import("@/src/api/client");
    const tok = await readAuthToken();
    const url = `${getApiBaseUrl()}/api/tours/admin/report.xlsx?company_id=${companyId}&month=${month}&token=${tok}`;
    if (Platform.OS === "web") window.open(url, "_blank");
    else Linking.openURL(url);
  };

  const decide = async (t: any, action: string) => {
    let remarks: string | undefined;
    if (action !== "approve" && Platform.OS === "web") {
      remarks = window.prompt("Remarks (mandatory):") || "";
      if (!remarks) { toast("Remarks are mandatory."); return; }
    } else if (Platform.OS === "web") {
      if (!window.confirm(`Approve ${t.tour_no}?`)) return;
    }
    setBusy(t.tour_id);
    try {
      await api(`/tours/${t.tour_id}/decide`, { method: "POST", body: { action, remarks } });
      toast(`Tour ${action}d ✓`); await load();
    } catch (e: any) { toast(e?.message || "Action failed"); }
    finally { setBusy(""); }
  };

  const saveSetting = async (patch: any) => {
    try {
      const r = await api<any>("/tours/admin/settings", { method: "POST", body: { company_id: companyId, ...patch } });
      setSettings(r.settings);
    } catch (e: any) { toast(e?.message || "Setting save failed"); }
  };

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) return <Redirect href="/" />;

  const counts = data?.counts || {};
  const pending = (data?.tours || []).filter((t: any) => t.status === "pending_approval");
  const allTours = (data?.tours || []).filter((t: any) => statusFilter === "all" || t.status === statusFilter);

  const TourRow = ({ t, showDecide }: { t: any; showDecide?: boolean }) => {
    const m = STATUS_META[t.status] || STATUS_META.draft;
    return (
      <View style={s.card} testID={`adm-tour-${t.tour_no}`}>
        <Pressable onPress={() => router.push(`/tour-detail?id=${t.tour_id}` as any)}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Text style={[s.tourNo, { flex: 1 }]}>{t.tour_no} · {t.employee?.name}</Text>
            <View style={[s.chip, { backgroundColor: m.bg }]}>
              <Text style={[s.chipT, { color: m.color }]}>{m.label}</Text>
            </View>
          </View>
          <Text style={s.info}>
            {t.tour_type} · {(t.destinations || []).join(", ")} · {t.start_date} → {t.end_date}
            {t.total_estimated ? ` · Est ₹${t.total_estimated}` : ""}
          </Text>
          {t.attendance_summary ? (
            <Text style={[s.info, t.attendance_summary.conflicts ? { color: "#DC2626", fontWeight: "700" } : null]}>
              OD posted: {t.attendance_summary.posted} · conflicts: {t.attendance_summary.conflicts} · skipped: {t.attendance_summary.skipped}
            </Text>
          ) : null}
        </Pressable>
        {showDecide ? (
          t.approval_request_id ? (
            <Pressable style={s.wfLink} onPress={() => router.push("/approval-inbox" as any)}>
              <Ionicons name="git-branch-outline" size={13} color={colors.brandPrimary} />
              <Text style={s.wfLinkT}>Routed via Approval Workflow — open Approval Inbox</Text>
            </Pressable>
          ) : (
            <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
              {[["approve", "#059669"], ["return", "#B45309"], ["reject", "#DC2626"]].map(([a, c]) => (
                <Pressable key={a} disabled={busy === t.tour_id}
                  style={[s.decBtn, { backgroundColor: c as string }]}
                  onPress={() => decide(t, a)} testID={`decide-${a}-${t.tour_no}`}>
                  <Text style={s.decBtnT}>{a.toUpperCase()}</Text>
                </Pressable>
              ))}
            </View>
          )
        ) : null}
      </View>
    );
  };

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.hBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Tour Management</Text>
          <Text style={s.subtitle}>Requests · live tracking · OD attendance · policy</Text>
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

        <View style={s.tabs}>
          {TABS.map(([k, lbl]) => (
            <Pressable key={k} style={[s.tab, tab === k && s.tabOn]} onPress={() => setTab(k)} testID={`ta-tab-${k}`}>
              <Text style={[s.tabT, tab === k && s.tabTOn]}>
                {lbl}{k === "requests" && counts.pending_approval ? ` (${counts.pending_approval})` : ""}
                {k === "live" && live.length ? ` (${live.length})` : ""}
              </Text>
            </Pressable>
          ))}
        </View>

        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} /> : null}

        {!loading && tab === "requests" ? (
          pending.length ? pending.map((t: any) => <TourRow key={t.tour_id} t={t} showDecide />)
            : <Text style={s.empty}>No tour requests pending approval.</Text>
        ) : null}

        {!loading && tab === "live" ? (
          live.length ? live.map((t: any) => (
            <View key={t.tour_id} style={s.card} testID={`live-${t.tour_no}`}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Text style={{ fontSize: 11 }}>🔴</Text>
                <Text style={[s.tourNo, { flex: 1 }]}>{t.tour_no} · {t.employee?.name}</Text>
                <Text style={s.info}>{t.visits} visit(s)</Text>
              </View>
              <Text style={s.info}>{t.tour_type} · {(t.destinations || []).join(", ")} · started {String(t.started_at || "").slice(0, 16).replace("T", " ")}</Text>
              {t.last_location ? (
                <Pressable onPress={() => Linking.openURL(`https://maps.google.com/?q=${t.last_location.lat},${t.last_location.lng}`)}>
                  <Text style={[s.info, { color: colors.brandPrimary, fontWeight: "700" }]}>
                    📍 Last: {t.last_location.lat?.toFixed(5)}, {t.last_location.lng?.toFixed(5)} at {String(t.last_location.captured_at || "").slice(11, 16)} — open map
                  </Text>
                </Pressable>
              ) : <Text style={s.info}>No location synced yet.</Text>}
              <Pressable style={s.wfLink} onPress={() => router.push(`/tour-detail?id=${t.tour_id}` as any)}>
                <Text style={s.wfLinkT}>Open tour — map · timeline · visits · expenses · attendance</Text>
              </Pressable>
            </View>
          )) : <Text style={s.empty}>No active tours right now.</Text>
        ) : null}

        {!loading && tab === "all" ? (
          <>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 10 }}>
              <View style={{ flexDirection: "row", gap: 6 }}>
                {["all", ...Object.keys(STATUS_META)].map((k) => (
                  <Pressable key={k} style={[s.fChip, statusFilter === k && s.fChipOn]}
                    onPress={() => setStatusFilter(k)} testID={`filter-${k}`}>
                    <Text style={[s.fChipT, statusFilter === k && { color: "#fff" }]}>
                      {k === "all" ? `All (${counts.total || 0})` : `${STATUS_META[k].label} (${counts[k] || 0})`}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </ScrollView>
            {allTours.length ? allTours.map((t: any) => <TourRow key={t.tour_id} t={t} />)
              : <Text style={s.empty}>No tours found.</Text>}
          </>
        ) : null}

        {!loading && tab === "report" ? (
          <>
            <View style={s.mRow}>
              <Pressable style={s.mBtn} onPress={() => setMonth(monthShift(month, -1))} testID="rep-prev">
                <Ionicons name="chevron-back" size={16} color={colors.brandPrimary} />
              </Pressable>
              <Text style={s.mTxt}>{month}</Text>
              <Pressable style={s.mBtn} onPress={() => setMonth(monthShift(month, 1))} testID="rep-next">
                <Ionicons name="chevron-forward" size={16} color={colors.brandPrimary} />
              </Pressable>
              <View style={{ flex: 1 }} />
              <Pressable style={s.dlBtn} onPress={downloadReport} testID="rep-download">
                <Ionicons name="download-outline" size={14} color="#fff" />
                <Text style={s.dlBtnT}>Excel</Text>
              </Pressable>
            </View>
            {!companyId ? <Text style={s.empty}>Select a firm to view the report.</Text>
              : !report ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 20 }} />
              : !report.rows?.length ? <Text style={s.empty}>No tours in {month}.</Text>
              : (
                <>
                  {report.rows.map((r: any) => (
                    <View key={r.user_id} style={s.card} testID={`rep-${r.employee_code || r.user_id}`}>
                      <Text style={s.tourNo}>{r.name} {r.employee_code ? `(${r.employee_code})` : ""}{r.department ? ` · ${r.department}` : ""}</Text>
                      <Text style={s.info}>{r.tour_nos.join(", ")}</Text>
                      <View style={s.repGrid}>
                        {[["Tours", r.tours], ["Tour Days", r.tour_days], ["Visits", r.visits],
                          ["OD Posted", r.od_posted], ["Claimed ₹", r.expenses_claimed],
                          ["Approved ₹", r.expenses_approved], ["Advance ₹", r.advance_paid],
                          ["Conflicts", r.od_conflicts]].map(([l, v]) => (
                          <View key={l as string} style={s.repCell}>
                            <Text style={[s.repVal, l === "Conflicts" && Number(v) > 0 && { color: "#DC2626" }]}>{String(v)}</Text>
                            <Text style={s.repLbl}>{l}</Text>
                          </View>
                        ))}
                      </View>
                    </View>
                  ))}
                  <View style={[s.card, { backgroundColor: "rgba(37,99,235,0.06)" }]}>
                    <Text style={s.tourNo}>TOTAL — {month}</Text>
                    <Text style={s.info}>
                      Tours {report.totals.tours} · Days {report.totals.tour_days} · Visits {report.totals.visits} ·
                      OD {report.totals.od_posted} · Claimed ₹{report.totals.expenses_claimed} ·
                      Approved ₹{report.totals.expenses_approved} · Advance ₹{report.totals.advance_paid}
                    </Text>
                  </View>
                </>
              )}
          </>
        ) : null}

        {!loading && tab === "advances" ? (
          <>
            <View style={{ flexDirection: "row", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
              {["all", "pending", "paid", "settled"].map((k) => (
                <Pressable key={k} style={[s.fChip, advFilter === k && s.fChipOn]}
                  onPress={() => setAdvFilter(k)} testID={`adv-filter-${k}`}>
                  <Text style={[s.fChipT, advFilter === k && { color: "#fff" }]}>
                    {k === "all" ? `All (${advances?.counts?.total ?? 0})`
                      : `${k[0].toUpperCase()}${k.slice(1)} (${advances?.counts?.[k] ?? 0})`}
                  </Text>
                </Pressable>
              ))}
            </View>
            {!(advances?.advances || []).filter((t: any) => advFilter === "all" || t.advance_payout?.status === advFilter).length
              ? <Text style={s.empty}>No tour advances {advFilter !== "all" ? `(${advFilter})` : ""} yet — advances appear here when a tour with &quot;Advance Required&quot; is approved.</Text>
              : (advances.advances || [])
                .filter((t: any) => advFilter === "all" || t.advance_payout?.status === advFilter)
                .map((t: any) => {
                  const ap = t.advance_payout || {};
                  return (
                    <View key={t.tour_id} style={s.card} testID={`adv-${t.tour_no}`}>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                        <Text style={[s.tourNo, { flex: 1 }]}>{t.tour_no} · {t.employee?.name}</Text>
                        <View style={[s.chip, {
                          backgroundColor: ap.status === "pending" ? "rgba(217,119,6,0.12)"
                            : ap.status === "paid" ? "rgba(3,105,161,0.12)" : "rgba(5,150,105,0.12)" }]}>
                          <Text style={[s.chipT, {
                            color: ap.status === "pending" ? "#D97706"
                              : ap.status === "paid" ? "#0369A1" : "#059669" }]}>
                            {String(ap.status || "").toUpperCase()}
                          </Text>
                        </View>
                      </View>
                      <Text style={s.info}>
                        Advance ₹{ap.amount} · {t.start_date} → {t.end_date} · Tour {t.status}
                      </Text>
                      <Text style={s.info}>
                        Expenses: claimed ₹{t.expenses_claimed} · approved ₹{t.expenses_approved}
                        {ap.status !== "pending" ? ` · balance ${t.balance >= 0 ? `₹${t.balance} payable` : `₹${Math.abs(t.balance)} recoverable`}` : ""}
                      </Text>
                      {ap.paid_at ? (
                        <Text style={s.info}>Paid {String(ap.paid_at).slice(0, 10)} · {ap.mode}{ap.reference ? ` · ${ap.reference}` : ""} by {ap.paid_by_name}</Text>
                      ) : null}
                      {ap.settled_at ? (
                        <Text style={s.info}>Settled {String(ap.settled_at).slice(0, 10)} by {ap.settled_by_name} · final balance ₹{ap.balance}</Text>
                      ) : null}
                      <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
                        {ap.status === "pending" ? (
                          <Pressable style={[s.decBtn, { backgroundColor: "#0369A1", flex: 0, paddingHorizontal: 16 }]}
                            disabled={busy === t.tour_id} onPress={() => payAdvance(t)} testID={`adv-pay-${t.tour_no}`}>
                            <Text style={s.decBtnT}>MARK PAID</Text>
                          </Pressable>
                        ) : null}
                        {ap.status === "paid" ? (
                          <Pressable style={[s.decBtn, { backgroundColor: "#059669", flex: 0, paddingHorizontal: 16 }]}
                            disabled={busy === t.tour_id} onPress={() => settleAdvance(t)} testID={`adv-settle-${t.tour_no}`}>
                            <Text style={s.decBtnT}>SETTLE</Text>
                          </Pressable>
                        ) : null}
                        <Pressable style={s.wfLink} onPress={() => router.push(`/tour-detail?id=${t.tour_id}` as any)}>
                          <Text style={s.wfLinkT}>Open tour</Text>
                        </Pressable>
                      </View>
                    </View>
                  );
                })}
          </>
        ) : null}

        {!loading && tab === "settings" ? (
          settings ? (
            <View style={s.card}>
              <Text style={s.secT}>Live Tracking</Text>
              <Text style={s.info}>Tracking interval (minutes):</Text>
              <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
                {[1, 5, 10, 15].map((iv) => (
                  <Pressable key={iv} style={[s.fChip, settings.tracking_interval_min === iv && s.fChipOn]}
                    onPress={() => saveSetting({ tracking_interval_min: iv })} testID={`iv-${iv}`}>
                    <Text style={[s.fChipT, settings.tracking_interval_min === iv && { color: "#fff" }]}>{iv} min</Text>
                  </Pressable>
                ))}
              </View>
              <Text style={[s.secT, { marginTop: 16 }]}>OD / Tour Attendance Policy</Text>
              {[["od_counts_present", "OD counts as Present"],
                ["od_counts_paid", "OD counts as Paid Day"],
                ["od_ot_eligible", "OD eligible for OT"]].map(([k, lbl]) => (
                <View key={k} style={s.setRow}>
                  <Text style={[s.info, { flex: 1, marginTop: 0 }]}>{lbl}</Text>
                  <Switch value={!!settings[k]} onValueChange={(v) => saveSetting({ [k]: v })}
                    trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }} testID={`set-${k}`} />
                </View>
              ))}
              {[["holiday_during_tour", "Holiday during tour"],
                ["weekly_off_during_tour", "Weekly-off during tour"]].map(([k, lbl]) => (
                <View key={k} style={s.setRow}>
                  <Text style={[s.info, { flex: 1, marginTop: 0 }]}>{lbl}</Text>
                  {["skip", "od"].map((v) => (
                    <Pressable key={v} style={[s.fChip, settings[k] === v && s.fChipOn]}
                      onPress={() => saveSetting({ [k]: v })} testID={`set-${k}-${v}`}>
                      <Text style={[s.fChipT, settings[k] === v && { color: "#fff" }]}>{v === "skip" ? "Skip" : "Post OD"}</Text>
                    </Pressable>
                  ))}
                </View>
              ))}
              <View style={s.setRow}>
                <Text style={[s.info, { flex: 1, marginTop: 0 }]}>Expense claim grace after tour (days)</Text>
                {[0, 7, 15, 30].map((g) => (
                  <Pressable key={g} style={[s.fChip, settings.expense_claim_grace_days === g && s.fChipOn]}
                    onPress={() => saveSetting({ expense_claim_grace_days: g })} testID={`grace-${g}`}>
                    <Text style={[s.fChipT, settings.expense_claim_grace_days === g && { color: "#fff" }]}>{g}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          ) : <Text style={s.empty}>Select a firm to configure tour settings.</Text>
        ) : null}
        <View style={{ height: 40 }} />
      </ScrollView>
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
  tabs: { flexDirection: "row", gap: 6, marginBottom: 12, flexWrap: "wrap" },
  tab: {
    paddingHorizontal: 12, paddingVertical: 9, borderRadius: 10, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  tabOn: { backgroundColor: "rgba(37,99,235,0.1)", borderColor: colors.brandPrimary },
  tabT: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTOn: { color: colors.brandPrimary },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 14, padding: 12,
    borderWidth: 1, borderColor: colors.border, marginBottom: 10,
  },
  tourNo: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  chip: { borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4 },
  chipT: { fontSize: 10.5, fontWeight: "800" },
  info: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 3 },
  secT: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 4 },
  empty: { fontSize: 12.5, color: colors.onSurfaceTertiary, textAlign: "center", marginTop: 30 },
  decBtn: { flex: 1, height: 38, borderRadius: 9, alignItems: "center", justifyContent: "center" },
  decBtnT: { color: "#fff", fontWeight: "800", fontSize: 12 },
  wfLink: { flexDirection: "row", alignItems: "center", gap: 5, marginTop: 8 },
  wfLinkT: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },
  fChip: {
    paddingHorizontal: 10, paddingVertical: 7, borderRadius: 9, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  fChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  fChipT: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  setRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10, flexWrap: "wrap" },
  // Iter 707 — report + advances.
  mRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 10 },
  mBtn: {
    width: 34, height: 34, borderRadius: 9, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary, alignItems: "center", justifyContent: "center",
  },
  mTxt: { fontSize: 14, fontWeight: "800", color: colors.onSurface, minWidth: 78, textAlign: "center" },
  dlBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: "#059669",
    borderRadius: 9, paddingHorizontal: 12, height: 36,
  },
  dlBtnT: { color: "#fff", fontWeight: "800", fontSize: 12 },
  repGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 },
  repCell: {
    minWidth: 72, flexGrow: 1, backgroundColor: colors.surface, borderRadius: 9,
    borderWidth: 1, borderColor: colors.border, paddingVertical: 7, alignItems: "center",
  },
  repVal: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  repLbl: { fontSize: 9.5, fontWeight: "700", color: colors.onSurfaceTertiary, marginTop: 1 },
});
