/**
 * Employee Advance Management — enterprise module.
 *
 * Tabs: Dashboard (KPIs + trend/dept/type bars) · Ledger (grid + actions)
 * · Reports (9 kinds + Excel export). "New Advance" modal creates
 * Salary/Festival/Loan/Emergency/Medical/Travel advances with Single or
 * EMI recovery synced to Compliance / Actual / Both salary processes.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Modal, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api, readAuthToken, getApiBaseUrl } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import DateField from "@/src/components/DateField";
import MonthPicker from "@/src/components/MonthPicker";
import { confirmYesNo } from "@/src/utils/confirm";
import { colors } from "@/src/theme";

const TYPES = ["Salary Advance", "Festival Advance", "Loan Recovery",
  "Emergency Advance", "Medical Advance", "Travel Advance", "Other"];
const MODES = ["Cash", "Bank", "UPI", "Cheque"];
const SOURCES = [
  { key: "compliance", label: "Compliance Salary" },
  { key: "actual", label: "Actual Salary" },
  { key: "both", label: "Both Processes" },
];
const PRIORITIES = ["high", "normal", "low"];
const REPORTS = [
  { key: "register", label: "Advance Register" },
  { key: "outstanding", label: "Outstanding" },
  { key: "monthly_recovery", label: "Monthly Recovery" },
  { key: "department", label: "Department Wise" },
  { key: "contractor", label: "Contractor Wise" },
  { key: "company", label: "Company Wise" },
  { key: "closed", label: "Closed Advances" },
  { key: "pending", label: "Pending Recovery" },
  { key: "recovery_history", label: "Recovery History" },
];

const STATUS_COLORS: Record<string, string> = {
  active: "#059669", scheduled: "#2563EB", on_hold: "#D97706",
  closed: "#DC2626", waived: "#64748B",
  pending_approval: "#7C3AED", rejected: "#B91C1C",
};

function inr(v: any) {
  const n = Number(v || 0);
  return `₹${n.toLocaleString("en-IN")}`;
}
function toast(msg: string) {
  if (Platform.OS === "web") window.alert(msg); else Alert.alert("Advance", msg);
}
function thisMonth() { return new Date().toISOString().slice(0, 7); }

function StatusPill({ status }: { status: string }) {
  const c = STATUS_COLORS[status] || "#64748B";
  return (
    <View style={[s.pill, { backgroundColor: `${c}18` }]}>
      <Text style={[s.pillTxt, { color: c }]}>{(status || "").replace("_", " ").toUpperCase()}</Text>
    </View>
  );
}

function Kpi({ label, value, icon, tone }: { label: string; value: string | number; icon: any; tone: string }) {
  return (
    <View style={s.kpi}>
      <View style={[s.kpiIcon, { backgroundColor: `${tone}18` }]}>
        <Ionicons name={icon} size={15} color={tone} />
      </View>
      <Text style={s.kpiVal}>{value}</Text>
      <Text style={s.kpiLbl} numberOfLines={1}>{label}</Text>
    </View>
  );
}

function Bars({ title, data }: { title: string; data: { label: string; value: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <View style={s.card}>
      <Text style={s.cardTitle}>{title}</Text>
      {data.length === 0 ? <Text style={s.muted}>No data</Text> : data.map((d) => (
        <View key={d.label} style={{ marginTop: 8 }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
            <Text style={s.barLbl} numberOfLines={1}>{d.label}</Text>
            <Text style={s.barVal}>{inr(d.value)}</Text>
          </View>
          <View style={s.barTrack}>
            <View style={[s.barFill, { width: `${Math.round((d.value / max) * 100)}%` }]} />
          </View>
        </View>
      ))}
    </View>
  );
}

export default function AdvancesScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const role = user?.role as string;

  const [companyId, setCompanyId] = useState<string | "all">(
    role === "company_admin" ? (user?.company_id || "all") : (selectedCompanyId || "all"));
  const [tab, setTab] = useState<"dashboard" | "ledger" | "reports">("ledger");
  const [loading, setLoading] = useState(true);
  const [list, setList] = useState<any>(null);
  const [dash, setDash] = useState<any>(null);
  const [search, setSearch] = useState("");
  const [statusF, setStatusF] = useState("all");

  // create form
  const [showForm, setShowForm] = useState(false);
  const [emps, setEmps] = useState<any[]>([]);
  const [empQuery, setEmpQuery] = useState("");
  const [f, setF] = useState<any>({
    user_id: "", advance_date: new Date().toISOString().slice(0, 10),
    advance_type: "Salary Advance", amount: "", purpose: "", payment_mode: "Bank",
    recovery_type: "emi", emi_amount: "", installments: "",
    start_month: thisMonth(), recovery_source: "both", priority: "normal", remarks: "",
  });
  const [saving, setSaving] = useState(false);

  // detail
  const [detail, setDetail] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  // reports
  const [repKind, setRepKind] = useState("register");
  const [repMonth, setRepMonth] = useState(thisMonth());
  const [rep, setRep] = useState<any>(null);

  const qCompany = companyId && companyId !== "all" ? `company_id=${companyId}` : "";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [l, d] = await Promise.all([
        api(`/admin/advances?${qCompany}`),
        api(`/admin/advances/dashboard?${qCompany}`),
      ]);
      setList(l); setDash(d);
    } catch { setList(null); setDash(null); }
    finally { setLoading(false); }
  }, [qCompany]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!showForm) return;
    (async () => {
      try {
        const r = await api<{ employees: any[] }>(`/admin/employees?${qCompany}`);
        setEmps(r.employees || []);
      } catch { setEmps([]); }
    })();
  }, [showForm, qCompany]);

  const loadReport = useCallback(async () => {
    try {
      const m = repKind === "monthly_recovery" ? `&month=${repMonth}` : "";
      setRep(await api(`/admin/advances/reports?kind=${repKind}&${qCompany}${m}`));
    } catch { setRep(null); }
  }, [repKind, repMonth, qCompany]);
  useEffect(() => { if (tab === "reports") loadReport(); }, [tab, loadReport]);

  const filtered = useMemo(() => {
    let rows = list?.advances || [];
    if (statusF !== "all") rows = rows.filter((a: any) => a.status === statusF);
    const t = search.trim().toLowerCase();
    if (t) rows = rows.filter((a: any) =>
      (a.employee_name || "").toLowerCase().includes(t) ||
      (a.voucher_no || "").toLowerCase().includes(t) ||
      String(a.employee_code || "").toLowerCase().includes(t));
    return rows;
  }, [list, statusF, search]);

  const openDetail = async (id: string) => {
    try { setDetail(await api(`/admin/advances/${id}`)); } catch (e: any) { toast(e?.message || "Failed"); }
  };

  const doAction = async (id: string, action: string, extra: any = {}) => {
    const labels: Record<string, string> = {
      pause: "Pause recovery for this advance?",
      resume: "Resume recovery for this advance?",
      recover_full: "Recover the FULL remaining balance now?",
      waive: "Waive the remaining balance? This closes the advance.",
    };
    if (labels[action] && !(await confirmYesNo(labels[action]))) return;
    let remarks = extra.remarks;
    if ((action === "waive" || action === "skip_month") && !remarks) {
      remarks = Platform.OS === "web" ? window.prompt("Remarks (mandatory):") || "" : "";
      if (!remarks) { toast("Remarks are mandatory."); return; }
    }
    setBusy(true);
    try {
      await api(`/admin/advances/${id}/action`, { method: "POST", body: { action, ...extra, remarks } });
      toast("Done.");
      setDetail(null); await load();
    } catch (e: any) { toast(e?.message || "Action failed"); }
    finally { setBusy(false); }
  };

  const doDelete = async (id: string) => {
    if (!(await confirmYesNo("Delete this advance? Only possible before any recovery."))) return;
    try { await api(`/admin/advances/${id}`, { method: "DELETE" }); toast("Deleted."); setDetail(null); await load(); }
    catch (e: any) { toast(e?.message || "Delete failed"); }
  };

  const submit = async () => {
    if (!f.user_id) return toast("Pick an employee.");
    if (!Number(f.amount)) return toast("Enter the advance amount.");
    if (f.recovery_type === "emi" && !Number(f.emi_amount)) return toast("Enter the EMI amount.");
    setSaving(true);
    try {
      const body: any = { ...f, amount: Number(f.amount) };
      body.emi_amount = f.recovery_type === "emi" ? Number(f.emi_amount) : undefined;
      body.installments = f.installments ? Number(f.installments) : undefined;
      const r = await api("/admin/advances", { method: "POST", body });
      toast(r.pending_approval
        ? `Advance ${r.advance.voucher_no} sent for approval (workflow).`
        : `Advance ${r.advance.voucher_no} created.`);
      setShowForm(false);
      setF({ ...f, user_id: "", amount: "", emi_amount: "", installments: "", purpose: "", remarks: "" });
      await load();
    } catch (e: any) { toast(e?.message || "Create failed"); }
    finally { setSaving(false); }
  };

  const exportXlsx = async () => {
    try {
      const t = await readAuthToken();
      const m = repKind === "monthly_recovery" ? `&month=${repMonth}` : "";
      const url = `${getApiBaseUrl()}/admin/advances/reports?kind=${repKind}&format=xlsx&${qCompany}${m}`;
      if (Platform.OS === "web") {
        const res = await fetch(url, { headers: { Authorization: `Bearer ${t}` } });
        const blob = await res.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `advance_${repKind}.xlsx`;
        a.click();
      } else toast("Excel export is available on the web portal.");
    } catch { toast("Export failed"); }
  };

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) return <Redirect href="/" />;

  const selEmp = emps.find((e) => e.user_id === f.user_id);
  const emiInstallments = f.recovery_type === "emi" && Number(f.amount) && Number(f.emi_amount)
    ? Math.ceil(Number(f.amount) / Number(f.emi_amount)) : null;
  const sum = list?.summary;
  const d = detail?.advance;
  const recoveredPct = d ? Math.round(100 * (d.recovered_total || 0) / (d.amount || 1)) : 0;

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.hBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Employee Advance Management</Text>
          <Text style={s.subtitle}>Advances · EMI recovery · Salary process sync</Text>
        </View>
        <Pressable style={s.newBtn} onPress={() => setShowForm(true)} testID="new-advance">
          <Ionicons name="add" size={16} color="#fff" />
          <Text style={s.newBtnTxt}>New Advance</Text>
        </Pressable>
      </View>

      {/* Tabs */}
      <View style={s.tabs}>
        {(["dashboard", "ledger", "reports"] as const).map((t) => (
          <Pressable key={t} onPress={() => setTab(t)} style={[s.tab, tab === t && s.tabOn]} testID={`tab-${t}`}>
            <Text style={[s.tabTxt, tab === t && s.tabTxtOn]}>{t[0].toUpperCase() + t.slice(1)}</Text>
          </Pressable>
        ))}
      </View>

      <ScrollView contentContainerStyle={s.body}>
        {role !== "company_admin" ? (
          <View style={{ marginBottom: 12 }}>
            <CompanyPicker value={companyId} onChange={(v: any) => setCompanyId(v || "all")} allowAll />
          </View>
        ) : null}

        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} /> : null}

        {/* ---------------- DASHBOARD ---------------- */}
        {!loading && tab === "dashboard" && dash ? (
          <View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              <View style={{ flexDirection: "row", gap: 10 }}>
                <Kpi label="Active Advances" value={dash.kpis.active} icon="wallet-outline" tone="#2563EB" />
                <Kpi label="Outstanding" value={inr(dash.kpis.outstanding)} icon="trending-up-outline" tone="#DC2626" />
                <Kpi label="Recovered This Month" value={inr(dash.kpis.recovered_this_month)} icon="cash-outline" tone="#059669" />
                <Kpi label="On Hold" value={dash.kpis.on_hold} icon="pause-circle-outline" tone="#D97706" />
                <Kpi label="Closed" value={dash.kpis.closed} icon="checkmark-done-outline" tone="#64748B" />
                <Kpi label="Employees" value={dash.kpis.employees} icon="people-outline" tone="#7C3AED" />
                <Kpi label="Recovery Rate" value={`${dash.kpis.recovery_rate}%`} icon="speedometer-outline" tone="#0891B2" />
              </View>
            </ScrollView>
            <View style={{ height: 12 }} />
            <Bars title="Monthly Recovery Trend" data={dash.trend.map((t: any) => ({ label: t.month, value: t.value }))} />
            <Bars title="Outstanding by Department" data={dash.by_department} />
            <Bars title="Outstanding by Contractor" data={dash.by_contractor} />
            <Bars title="Advance Type Distribution" data={dash.by_type} />
          </View>
        ) : null}

        {/* ---------------- LEDGER ---------------- */}
        {!loading && tab === "ledger" ? (
          <View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 10 }}>
              <View style={{ flexDirection: "row", gap: 10 }}>
                <Kpi label="Active" value={sum?.active ?? 0} icon="wallet-outline" tone="#2563EB" />
                <Kpi label="Outstanding" value={inr(sum?.outstanding)} icon="trending-up-outline" tone="#DC2626" />
                <Kpi label="Recovered" value={inr(sum?.recovered)} icon="cash-outline" tone="#059669" />
                <Kpi label="On Hold" value={sum?.on_hold ?? 0} icon="pause-circle-outline" tone="#D97706" />
                <Kpi label="Closed" value={sum?.closed ?? 0} icon="checkmark-done-outline" tone="#64748B" />
              </View>
            </ScrollView>
            <View style={s.searchWrap}>
              <Ionicons name="search" size={16} color={colors.onSurfaceTertiary} />
              <TextInput style={s.searchInput} placeholder="Search employee, code or voucher…"
                placeholderTextColor={colors.onSurfaceTertiary} value={search} onChangeText={setSearch} testID="adv-search" />
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 10 }}>
              <View style={{ flexDirection: "row", gap: 8 }}>
                {["all", "pending_approval", "active", "scheduled", "on_hold", "closed", "waived", "rejected"].map((k) => (
                  <Pressable key={k} onPress={() => setStatusF(k)} style={[s.chip, statusF === k && s.chipOn]} testID={`adv-filter-${k}`}>
                    <Text style={[s.chipTxt, statusF === k && s.chipTxtOn]}>{k === "all" ? "All" : k.replace("_", " ")}</Text>
                  </Pressable>
                ))}
              </View>
            </ScrollView>
            {filtered.length === 0 ? (
              <View style={s.empty}><Ionicons name="wallet-outline" size={34} color={colors.onSurfaceTertiary} />
                <Text style={s.muted}>No advances yet — tap &quot;New Advance&quot; to issue one.</Text></View>
            ) : filtered.map((a: any) => (
              <Pressable key={a.advance_id} style={s.row} onPress={() => openDetail(a.advance_id)} testID={`adv-row-${a.voucher_no}`}>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <View style={s.rowTop}>
                    <Text style={s.voucher}>{a.voucher_no}</Text>
                    <Text style={s.name} numberOfLines={1}>{a.employee_name}</Text>
                    {a.employee_code ? <Text style={s.code}>#{a.employee_code}</Text> : null}
                    <StatusPill status={a.status} />
                  </View>
                  <Text style={s.meta} numberOfLines={1}>
                    {a.advance_type} · {a.advance_date} · {a.recovery_type === "emi" ? `EMI ${inr(a.emi_amount)}` : "Single shot"} · {a.recovery_source}
                    {a.next_recovery_month ? ` · Next: ${a.next_recovery_month}` : ""}
                  </Text>
                  <View style={s.amtRow}>
                    <Text style={s.amt}>{inr(a.amount)}</Text>
                    <Text style={s.amtRec}>Recovered {inr(a.recovered_total)}</Text>
                    <Text style={s.amtOut}>Outstanding {inr(a.remaining_balance)}</Text>
                  </View>
                  <View style={s.progressTrack}>
                    <View style={[s.progressFill, { width: `${Math.min(100, Math.round(100 * (a.recovered_total || 0) / (a.amount || 1)))}%` }]} />
                  </View>
                </View>
                <Ionicons name="chevron-forward" size={17} color={colors.onSurfaceTertiary} />
              </Pressable>
            ))}
          </View>
        ) : null}

        {/* ---------------- REPORTS ---------------- */}
        {!loading && tab === "reports" ? (
          <View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 10 }}>
              <View style={{ flexDirection: "row", gap: 8 }}>
                {REPORTS.map((r) => (
                  <Pressable key={r.key} onPress={() => setRepKind(r.key)} style={[s.chip, repKind === r.key && s.chipOn]} testID={`report-${r.key}`}>
                    <Text style={[s.chipTxt, repKind === r.key && s.chipTxtOn]}>{r.label}</Text>
                  </Pressable>
                ))}
              </View>
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 8, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
              {repKind === "monthly_recovery" ? (
                <MonthPicker value={repMonth} onChange={setRepMonth} />
              ) : null}
              <Pressable style={s.exportBtn} onPress={exportXlsx} testID="export-xlsx">
                <Ionicons name="download-outline" size={14} color={colors.brandPrimary} />
                <Text style={s.exportTxt}>Export Excel</Text>
              </Pressable>
            </View>
            {rep ? (
              <ScrollView horizontal>
                <View style={s.card}>
                  <Text style={s.cardTitle}>{rep.title} ({rep.rows.length})</Text>
                  <View style={s.trHead}>
                    {rep.columns.map((c: string) => <Text key={c} style={s.th}>{c}</Text>)}
                  </View>
                  {rep.rows.map((r: any[], i: number) => (
                    <View key={i} style={[s.tr, i % 2 ? { backgroundColor: colors.surface } : null]}>
                      {r.map((v, j) => <Text key={j} style={s.td} numberOfLines={1}>{v === null || v === undefined ? "—" : String(v)}</Text>)}
                    </View>
                  ))}
                  {rep.rows.length === 0 ? <Text style={[s.muted, { padding: 10 }]}>No rows</Text> : null}
                </View>
              </ScrollView>
            ) : null}
          </View>
        ) : null}
        <View style={{ height: 40 }} />
      </ScrollView>

      {/* ---------------- NEW ADVANCE MODAL ---------------- */}
      <Modal transparent visible={showForm} animationType="fade" onRequestClose={() => setShowForm(false)}>
        <View style={s.modalRoot}>
          <Pressable style={s.backdrop} onPress={() => setShowForm(false)} />
          <View style={s.modalCard}>
            <ScrollView showsVerticalScrollIndicator={false}>
              <View style={s.modalHead}>
                <Text style={s.modalTitle}>New Advance</Text>
                <Pressable onPress={() => setShowForm(false)} hitSlop={10}><Ionicons name="close" size={22} color={colors.onSurfaceSecondary} /></Pressable>
              </View>

              <Text style={s.lbl}>Employee</Text>
              {selEmp ? (
                <View style={s.selEmp}>
                  <Text style={s.selEmpTxt}>{selEmp.name} {selEmp.employee_code ? `· #${selEmp.employee_code}` : ""}</Text>
                  <Pressable onPress={() => setF({ ...f, user_id: "" })}><Ionicons name="close-circle" size={18} color={colors.onSurfaceTertiary} /></Pressable>
                </View>
              ) : (
                <>
                  <TextInput style={s.input} placeholder="Search employee name / code…" placeholderTextColor={colors.onSurfaceTertiary}
                    value={empQuery} onChangeText={setEmpQuery} testID="emp-search" />
                  {empQuery.trim() ? (
                    <View style={s.empList}>
                      {emps.filter((e) => (e.name || "").toLowerCase().includes(empQuery.toLowerCase())
                        || String(e.employee_code || "").toLowerCase().includes(empQuery.toLowerCase())).slice(0, 6).map((e) => (
                        <Pressable key={e.user_id} style={s.empItem} onPress={() => { setF({ ...f, user_id: e.user_id }); setEmpQuery(""); }} testID={`emp-pick-${e.user_id}`}>
                          <Text style={s.empItemTxt}>{e.name} {e.employee_code ? `· #${e.employee_code}` : ""}</Text>
                          <Text style={s.empItemMeta}>{[e.designation, e.department].filter(Boolean).join(" · ")}</Text>
                        </Pressable>
                      ))}
                    </View>
                  ) : null}
                </>
              )}

              <View style={s.twoCol}>
                <View style={{ flex: 1 }}>
                  <Text style={s.lbl}>Advance Date</Text>
                  <DateField value={f.advance_date} onChangeISO={(v) => setF({ ...f, advance_date: v })} testID="adv-date" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={s.lbl}>Amount (₹)</Text>
                  <TextInput style={s.input} keyboardType="numeric" value={String(f.amount)}
                    onChangeText={(v) => setF({ ...f, amount: v.replace(/[^0-9.]/g, "") })} placeholder="e.g. 20000"
                    placeholderTextColor={colors.onSurfaceTertiary} testID="adv-amount" />
                </View>
              </View>

              <Text style={s.lbl}>Advance Type</Text>
              <View style={s.chipsWrap}>{TYPES.map((t) => (
                <Pressable key={t} onPress={() => setF({ ...f, advance_type: t })} style={[s.chip, f.advance_type === t && s.chipOn]}>
                  <Text style={[s.chipTxt, f.advance_type === t && s.chipTxtOn]}>{t.replace(" Advance", "")}</Text>
                </Pressable>))}
              </View>

              <Text style={s.lbl}>Payment Mode</Text>
              <View style={s.chipsWrap}>{MODES.map((m) => (
                <Pressable key={m} onPress={() => setF({ ...f, payment_mode: m })} style={[s.chip, f.payment_mode === m && s.chipOn]}>
                  <Text style={[s.chipTxt, f.payment_mode === m && s.chipTxtOn]}>{m}</Text>
                </Pressable>))}
              </View>

              <Text style={s.lbl}>Recovery Type</Text>
              <View style={s.chipsWrap}>
                {[["single", "Single Recovery"], ["emi", "Monthly EMI"]].map(([k, l]) => (
                  <Pressable key={k} onPress={() => setF({ ...f, recovery_type: k })} style={[s.chip, f.recovery_type === k && s.chipOn]} testID={`rt-${k}`}>
                    <Text style={[s.chipTxt, f.recovery_type === k && s.chipTxtOn]}>{l}</Text>
                  </Pressable>))}
              </View>

              {f.recovery_type === "emi" ? (
                <View style={s.twoCol}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.lbl}>EMI Amount (₹)</Text>
                    <TextInput style={s.input} keyboardType="numeric" value={String(f.emi_amount)}
                      onChangeText={(v) => setF({ ...f, emi_amount: v.replace(/[^0-9.]/g, "") })}
                      placeholder="e.g. 2000" placeholderTextColor={colors.onSurfaceTertiary} testID="adv-emi" />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.lbl}>Installments</Text>
                    <TextInput style={s.input} keyboardType="numeric"
                      value={f.installments ? String(f.installments) : (emiInstallments ? String(emiInstallments) : "")}
                      onChangeText={(v) => setF({ ...f, installments: v.replace(/[^0-9]/g, "") })}
                      placeholder="auto" placeholderTextColor={colors.onSurfaceTertiary} />
                  </View>
                </View>
              ) : null}

              <View style={s.twoCol}>
                <View style={{ flex: 1 }}>
                  <Text style={s.lbl}>Recovery Start Month</Text>
                  <MonthPicker value={f.start_month} onChange={(m: string) => setF({ ...f, start_month: m })} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={s.lbl}>End Month (auto)</Text>
                  <View style={[s.input, { justifyContent: "center" }]}>
                    <Text style={{ color: colors.onSurfaceSecondary }}>
                      {(() => {
                        const n = f.recovery_type === "emi" ? (Number(f.installments) || emiInstallments || 1) : 1;
                        const [y, m] = f.start_month.split("-").map(Number);
                        const idx = y * 12 + (m - 1) + (n - 1);
                        return `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, "0")}`;
                      })()}
                    </Text>
                  </View>
                </View>
              </View>

              <Text style={s.lbl}>Recover From</Text>
              <View style={s.chipsWrap}>{SOURCES.map((so) => (
                <Pressable key={so.key} onPress={() => setF({ ...f, recovery_source: so.key })} style={[s.chip, f.recovery_source === so.key && s.chipOn]} testID={`src-${so.key}`}>
                  <Text style={[s.chipTxt, f.recovery_source === so.key && s.chipTxtOn]}>{so.label}</Text>
                </Pressable>))}
              </View>

              <Text style={s.lbl}>Priority</Text>
              <View style={s.chipsWrap}>{PRIORITIES.map((p) => (
                <Pressable key={p} onPress={() => setF({ ...f, priority: p })} style={[s.chip, f.priority === p && s.chipOn]}>
                  <Text style={[s.chipTxt, f.priority === p && s.chipTxtOn]}>{p[0].toUpperCase() + p.slice(1)}</Text>
                </Pressable>))}
              </View>

              <Text style={s.lbl}>Purpose</Text>
              <TextInput style={s.input} value={f.purpose} onChangeText={(v) => setF({ ...f, purpose: v })}
                placeholder="e.g. Medical emergency" placeholderTextColor={colors.onSurfaceTertiary} />
              <Text style={s.lbl}>Remarks</Text>
              <TextInput style={s.input} value={f.remarks} onChangeText={(v) => setF({ ...f, remarks: v })}
                placeholder="Optional" placeholderTextColor={colors.onSurfaceTertiary} />

              <Pressable style={[s.saveBtn, saving && { opacity: 0.6 }]} disabled={saving} onPress={submit} testID="save-advance">
                {saving ? <ActivityIndicator color="#fff" size="small" /> : (
                  <><Ionicons name="checkmark" size={16} color="#fff" /><Text style={s.saveBtnTxt}>Save Advance</Text></>)}
              </Pressable>
              <View style={{ height: 14 }} />
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* ---------------- DETAIL MODAL ---------------- */}
      <Modal transparent visible={!!detail} animationType="fade" onRequestClose={() => setDetail(null)}>
        <View style={s.modalRoot}>
          <Pressable style={s.backdrop} onPress={() => setDetail(null)} />
          <View style={s.modalCard}>
            {d ? (
              <ScrollView showsVerticalScrollIndicator={false}>
                <View style={s.modalHead}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.modalTitle}>{d.voucher_no} · {d.employee_name}</Text>
                    <Text style={s.muted}>{d.advance_type} · {d.advance_date} · {d.payment_mode} · {d.recovery_source}</Text>
                  </View>
                  <StatusPill status={d.status} />
                  <Pressable onPress={() => setDetail(null)} hitSlop={10}><Ionicons name="close" size={22} color={colors.onSurfaceSecondary} /></Pressable>
                </View>

                <View style={s.sumRow}>
                  <View style={s.sumBox}><Text style={s.sumLbl}>Advance</Text><Text style={s.sumVal}>{inr(d.amount)}</Text></View>
                  <View style={s.sumBox}><Text style={s.sumLbl}>Recovered</Text><Text style={[s.sumVal, { color: "#059669" }]}>{inr(d.recovered_total)}</Text></View>
                  <View style={s.sumBox}><Text style={s.sumLbl}>Outstanding</Text><Text style={[s.sumVal, { color: "#DC2626" }]}>{inr(d.remaining_balance)}</Text></View>
                  <View style={s.sumBox}><Text style={s.sumLbl}>Progress</Text><Text style={s.sumVal}>{recoveredPct}%</Text></View>
                </View>
                <View style={s.progressTrack}>
                  <View style={[s.progressFill, { width: `${Math.min(100, recoveredPct)}%` }]} />
                </View>
                {d.next_recovery_month ? <Text style={[s.muted, { marginTop: 6 }]}>Next recovery: {d.next_recovery_month}{d.emi_amount ? ` · EMI ${inr(d.emi_amount)}` : ""}</Text> : null}

                {/* Actions */}
                {!["closed", "waived"].includes(d.status) ? (
                  <View style={[s.chipsWrap, { marginTop: 12 }]}>
                    {d.status !== "on_hold" ? (
                      <Pressable style={s.actBtn} disabled={busy} onPress={() => doAction(d.advance_id, "pause")} testID="act-pause">
                        <Ionicons name="pause" size={13} color="#D97706" /><Text style={[s.actTxt, { color: "#D97706" }]}>Pause</Text></Pressable>
                    ) : (
                      <Pressable style={s.actBtn} disabled={busy} onPress={() => doAction(d.advance_id, "resume")} testID="act-resume">
                        <Ionicons name="play" size={13} color="#059669" /><Text style={[s.actTxt, { color: "#059669" }]}>Resume</Text></Pressable>
                    )}
                    <Pressable style={s.actBtn} disabled={busy} onPress={() => doAction(d.advance_id, "skip_month", { month: d.next_recovery_month || thisMonth() })} testID="act-skip">
                      <Ionicons name="play-skip-forward" size={13} color="#2563EB" /><Text style={[s.actTxt, { color: "#2563EB" }]}>Skip Next EMI</Text></Pressable>
                    <Pressable style={s.actBtn} disabled={busy} onPress={() => doAction(d.advance_id, "recover_full")} testID="act-full">
                      <Ionicons name="cash" size={13} color="#059669" /><Text style={[s.actTxt, { color: "#059669" }]}>Recover Full</Text></Pressable>
                    <Pressable style={s.actBtn} disabled={busy} onPress={() => doAction(d.advance_id, "recover_full", { mode: "fnf" })}>
                      <Ionicons name="exit-outline" size={13} color="#7C3AED" /><Text style={[s.actTxt, { color: "#7C3AED" }]}>F&amp;F Recovery</Text></Pressable>
                    <Pressable style={s.actBtn} disabled={busy} onPress={() => doAction(d.advance_id, "waive")}>
                      <Ionicons name="hand-left-outline" size={13} color="#DC2626" /><Text style={[s.actTxt, { color: "#DC2626" }]}>Waive</Text></Pressable>
                    {Number(d.recovered_total) === 0 ? (
                      <Pressable style={s.actBtn} disabled={busy} onPress={() => doDelete(d.advance_id)} testID="act-delete">
                        <Ionicons name="trash-outline" size={13} color="#DC2626" /><Text style={[s.actTxt, { color: "#DC2626" }]}>Delete</Text></Pressable>
                    ) : null}
                  </View>
                ) : null}

                {/* Schedule */}
                <Text style={s.cardTitle}>Installment Schedule</Text>
                {(detail.schedule || []).map((r: any, i: number) => (
                  <View key={i} style={s.schedRow}>
                    <Text style={s.schedNo}>{r.no ?? "—"}</Text>
                    <Text style={s.schedMonth}>{r.month}</Text>
                    <Text style={s.schedAmt}>{inr(r.emi)}</Text>
                    <Text style={[s.schedStatus, {
                      color: r.status === "paid" ? "#059669" : r.status === "skipped" ? "#D97706" : colors.onSurfaceTertiary }]}>
                      {r.status.toUpperCase()}</Text>
                  </View>
                ))}

                {/* Transactions */}
                <Text style={s.cardTitle}>Recovery History</Text>
                {(detail.transactions || []).length === 0 ? <Text style={s.muted}>No recoveries yet</Text> :
                  detail.transactions.map((t: any) => (
                    <View key={t.txn_id} style={s.schedRow}>
                      <Text style={s.schedMonth}>{t.salary_month}</Text>
                      <Text style={s.schedAmt}>{inr(t.amount)}</Text>
                      <Text style={s.schedStatus}>{t.process_type}{t.balance_applied ? "" : " (mirror)"}</Text>
                      <Text style={s.schedStatus}>bal {inr(t.remaining_after)}</Text>
                    </View>
                  ))}

                {/* Audit */}
                <Text style={s.cardTitle}>Audit Trail</Text>
                {(d.audit || []).slice().reverse().map((e: any, i: number) => (
                  <View key={i} style={{ marginBottom: 6 }}>
                    <Text style={s.auditLine}>• {e.detail}</Text>
                    <Text style={s.auditMeta}>{(e.at || "").slice(0, 16).replace("T", " ")} · {e.by}</Text>
                  </View>
                ))}
                <View style={{ height: 14 }} />
              </ScrollView>
            ) : <ActivityIndicator color={colors.brandPrimary} style={{ margin: 30 }} />}
          </View>
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
  title: { fontSize: 16.5, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 1 },
  newBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: colors.brandPrimary,
    borderRadius: 12, paddingHorizontal: 13, height: 38,
  },
  newBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  tabs: {
    flexDirection: "row", gap: 6, paddingHorizontal: 16, paddingVertical: 10,
    backgroundColor: colors.surfaceSecondary, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  tab: { paddingHorizontal: 16, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceTertiary },
  tabOn: { backgroundColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtOn: { color: "#fff" },
  body: { padding: 16, width: "100%", maxWidth: 1100, alignSelf: "center" },

  kpi: {
    minWidth: 128, backgroundColor: colors.surfaceSecondary, borderRadius: 16, padding: 12,
    borderWidth: 1, borderColor: colors.border,
  },
  kpiIcon: { width: 26, height: 26, borderRadius: 8, alignItems: "center", justifyContent: "center", marginBottom: 7 },
  kpiVal: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  kpiLbl: { fontSize: 10.5, color: colors.onSurfaceTertiary, fontWeight: "600", marginTop: 2 },

  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 16, padding: 14,
    borderWidth: 1, borderColor: colors.border, marginBottom: 12, minWidth: 320,
  },
  cardTitle: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface, marginTop: 14, marginBottom: 6 },
  muted: { fontSize: 12, color: colors.onSurfaceTertiary },
  barLbl: { fontSize: 11.5, color: colors.onSurfaceSecondary, flex: 1 },
  barVal: { fontSize: 11.5, fontWeight: "700", color: colors.onSurface },
  barTrack: { height: 7, borderRadius: 4, backgroundColor: colors.surfaceTertiary, marginTop: 3 },
  barFill: { height: 7, borderRadius: 4, backgroundColor: colors.brandPrimary },

  searchWrap: {
    flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surfaceSecondary,
    borderRadius: 14, borderWidth: 1, borderColor: colors.border, paddingHorizontal: 12, height: 44, marginBottom: 10,
  },
  searchInput: { flex: 1, fontSize: 14, color: colors.onSurface, ...Platform.select({ web: { outlineStyle: "none" } as any, default: {} }) },
  chip: {
    paddingHorizontal: 12, height: 32, borderRadius: 16, backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center",
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "600", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 4 },

  row: {
    flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surfaceSecondary,
    borderRadius: 16, borderWidth: 1, borderColor: colors.border, padding: 14, marginBottom: 10,
  },
  rowTop: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  voucher: { fontSize: 12, fontWeight: "800", color: colors.brandPrimary },
  name: { fontSize: 14, fontWeight: "700", color: colors.onSurface, maxWidth: 220 },
  code: { fontSize: 11, color: colors.onSurfaceTertiary, fontWeight: "700" },
  meta: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 3 },
  amtRow: { flexDirection: "row", gap: 14, marginTop: 6, flexWrap: "wrap" },
  amt: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  amtRec: { fontSize: 12, fontWeight: "700", color: "#059669" },
  amtOut: { fontSize: 12, fontWeight: "700", color: "#DC2626" },
  progressTrack: { height: 6, borderRadius: 3, backgroundColor: colors.surfaceTertiary, marginTop: 8 },
  progressFill: { height: 6, borderRadius: 3, backgroundColor: "#059669" },
  pill: { borderRadius: 8, paddingHorizontal: 7, paddingVertical: 2 },
  pillTxt: { fontSize: 9.5, fontWeight: "800", letterSpacing: 0.4 },
  empty: { alignItems: "center", paddingVertical: 40, gap: 10 },

  exportBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1, borderColor: "rgba(37,99,235,0.35)",
    borderRadius: 10, paddingHorizontal: 12, height: 34, backgroundColor: "rgba(37,99,235,0.06)",
  },
  exportTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  trHead: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.border, paddingVertical: 6 },
  th: { width: 120, fontSize: 11, fontWeight: "800", color: colors.onSurfaceSecondary },
  tr: { flexDirection: "row", paddingVertical: 6 },
  td: { width: 120, fontSize: 11.5, color: colors.onSurface },

  modalRoot: { flex: 1, alignItems: "center", justifyContent: "center", padding: 16 },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(15,23,42,0.45)" },
  modalCard: {
    width: "100%", maxWidth: 560, maxHeight: "92%", backgroundColor: colors.surfaceSecondary,
    borderRadius: 18, padding: 18,
    ...Platform.select({ web: { boxShadow: "0 20px 50px rgba(15,23,42,0.25)" } as any, default: { elevation: 8 } }),
  },
  modalHead: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 10 },
  modalTitle: { fontSize: 15.5, fontWeight: "800", color: colors.onSurface },
  lbl: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 10, marginBottom: 5 },
  input: {
    height: 44, borderRadius: 12, borderWidth: 1, borderColor: colors.border, paddingHorizontal: 12,
    fontSize: 14, color: colors.onSurface, backgroundColor: colors.surface,
  },
  twoCol: { flexDirection: "row", gap: 10 },
  selEmp: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    borderWidth: 1, borderColor: "rgba(37,99,235,0.4)", backgroundColor: "rgba(37,99,235,0.06)",
    borderRadius: 12, paddingHorizontal: 12, height: 44,
  },
  selEmpTxt: { fontSize: 13.5, fontWeight: "700", color: colors.brandPrimary },
  empList: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, marginTop: 6, overflow: "hidden" },
  empItem: { padding: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  empItemTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  empItemMeta: { fontSize: 11, color: colors.onSurfaceTertiary },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7,
    backgroundColor: colors.brandPrimary, borderRadius: 14, height: 48, marginTop: 16,
  },
  saveBtnTxt: { fontSize: 14, fontWeight: "800", color: "#fff" },

  sumRow: { flexDirection: "row", gap: 8, marginTop: 6, flexWrap: "wrap" },
  sumBox: { flex: 1, minWidth: 100, backgroundColor: colors.surface, borderRadius: 12, padding: 10, borderWidth: 1, borderColor: colors.border },
  sumLbl: { fontSize: 10.5, color: colors.onSurfaceTertiary, fontWeight: "700" },
  sumVal: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface, marginTop: 2 },
  actBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1, borderColor: colors.border,
    borderRadius: 10, paddingHorizontal: 10, height: 32, backgroundColor: colors.surface,
  },
  actTxt: { fontSize: 11.5, fontWeight: "800" },
  schedRow: {
    flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 7,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  schedNo: { width: 26, fontSize: 11.5, color: colors.onSurfaceTertiary, fontWeight: "700" },
  schedMonth: { width: 74, fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  schedAmt: { flex: 1, fontSize: 12.5, color: colors.onSurface },
  schedStatus: { fontSize: 10.5, fontWeight: "800", color: colors.onSurfaceTertiary },
  auditLine: { fontSize: 12, color: colors.onSurface },
  auditMeta: { fontSize: 10.5, color: colors.onSurfaceTertiary },
});
