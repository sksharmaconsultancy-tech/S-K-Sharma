/**
 * Iter 527 (user request) — CENTRAL CONTRACTOR WAGE REGISTERS (Form A–D).
 * Compliance → Contractor Registers → Central Wages.
 *   Form A — Employee Register · Form B — Wage Register
 *   Form C — Deductions / Advances / Recoveries · Form D — Muster Roll
 * Common filters, wage period (month or custom range), Excel/PDF export,
 * Draft → Verified → Approved → Locked workflow with audit trail, plus a
 * Setup tab (Principal Employers, Work Orders, Employee mapping).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Platform,
  ScrollView,
  ActivityIndicator,
  TextInput,
  Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { api, apiBinary } from "@/src/api/client";
import MonthPicker from "@/src/components/MonthPicker";
import EmployeeDropdown, { EmpLite } from "@/src/components/EmployeeDropdown";
import RegisterTable from "@/src/components/RegisterTable";
import { colors, radius } from "@/src/theme";

const BASE = "/admin/central-wage-registers";
const FORMS: { key: string; label: string; icon: any }[] = [
  { key: "a", label: "Form A — Employees", icon: "people-outline" },
  { key: "b", label: "Form B — Wages", icon: "cash-outline" },
  { key: "c", label: "Form C — Deductions", icon: "remove-circle-outline" },
  { key: "d", label: "Form D — Muster Roll", icon: "calendar-outline" },
  { key: "setup", label: "Setup", icon: "settings-outline" },
];

type Opt = { id: string; label: string };

function Pick({ label, value, options, onChange, testID }: {
  label: string; value: string; options: Opt[];
  onChange: (v: string) => void; testID?: string;
}) {
  const [open, setOpen] = useState(false);
  const cur = options.find((o) => o.id === value);
  return (
    <View style={{ minWidth: 150, flexGrow: 1, maxWidth: 260 }}>
      <Text style={st.pickLbl}>{label}</Text>
      <Pressable style={st.pickBtn} onPress={() => setOpen(true)} testID={testID}>
        <Text style={[st.pickTxt, !cur && { color: "#94A3B8" }]} numberOfLines={1}>
          {cur ? cur.label : "All"}
        </Text>
        <Ionicons name="chevron-down" size={14} color="#64748B" />
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={st.mBack} onPress={() => setOpen(false)}>
          <View style={st.mCard}>
            <Text style={st.mTitle}>{label}</Text>
            <ScrollView style={{ maxHeight: 360 }}>
              <Pressable style={st.mRow} onPress={() => { onChange(""); setOpen(false); }}>
                <Text style={[st.mRowTxt, !value && st.mRowSel]}>All</Text>
              </Pressable>
              {options.map((o) => (
                <Pressable key={o.id} style={st.mRow}
                  onPress={() => { onChange(o.id); setOpen(false); }}>
                  <Text style={[st.mRowTxt, value === o.id && st.mRowSel]} numberOfLines={1}>
                    {o.label}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}

function Field({ label, value, onChange, placeholder, keyboardType }: any) {
  return (
    <View style={{ minWidth: 140, flexGrow: 1 }}>
      <Text style={st.pickLbl}>{label}</Text>
      <TextInput style={st.input} value={value} onChangeText={onChange}
        placeholder={placeholder || ""} placeholderTextColor="#94A3B8"
        keyboardType={keyboardType} />
    </View>
  );
}

const STATUS_COLORS: Record<string, string> = {
  draft: "#64748B", verified: "#2563EB", approved: "#059669", locked: "#B91C1C",
};

export default function CentralWageRegistersScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const companyId = selectedCompanyId || "";

  const [tab, setTab] = useState("a");
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [custom, setCustom] = useState(false);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [ctr, setCtr] = useState("");
  const [wo, setWo] = useState("");
  const [pe, setPe] = useState("");
  const [site, setSite] = useState("");
  const [dept, setDept] = useState("");
  const [etype, setEtype] = useState("");
  const [selEmps, setSelEmps] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<any>(null);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  // Form C entry modal
  const [cOpen, setCOpen] = useState(false);
  const [cEmp, setCEmp] = useState<string[]>([]);
  const [cDate, setCDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [cType, setCType] = useState("Advance");
  const [cReason, setCReason] = useState("");
  const [cAdv, setCAdv] = useState("");
  const [cRec, setCRec] = useState("");
  const [cFine, setCFine] = useState("");
  const [cOther, setCOther] = useState("");
  const [cRemarks, setCRemarks] = useState("");

  const loadFilters = useCallback(async () => {
    if (!companyId) return;
    try {
      setFilters(await api<any>(`${BASE}/filters?company_id=${companyId}`));
    } catch {}
  }, [companyId]);
  useEffect(() => { void loadFilters(); }, [loadFilters]);

  const qs = useCallback(() => {
    const p = new URLSearchParams();
    p.append("company_id", companyId);
    if (custom && /^\d{4}-\d{2}-\d{2}$/.test(fromDate) && /^\d{4}-\d{2}-\d{2}$/.test(toDate)) {
      p.append("from_date", fromDate);
      p.append("to_date", toDate);
    } else p.append("month", month);
    if (ctr) p.append("contractor_id", ctr);
    if (wo) p.append("work_order_id", wo);
    if (pe) p.append("principal_employer_id", pe);
    if (site) p.append("site", site);
    if (dept) p.append("department", dept);
    if (etype) p.append("employee_type", etype);
    if (selEmps.length) p.append("employee_ids", selEmps.join(","));
    if (search.trim()) p.append("search", search.trim());
    return p.toString();
  }, [companyId, custom, fromDate, toDate, month, ctr, wo, pe, site, dept,
      etype, selEmps, search]);

  const load = useCallback(async () => {
    if (!companyId || tab === "setup") return;
    setLoading(true);
    setErr("");
    try {
      setData(await api<any>(`${BASE}/register/form-${tab}?${qs()}`));
    } catch (e: any) {
      setErr(e?.message || "Failed to load register");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, tab, qs]);
  useEffect(() => { void load(); }, [load]);

  const download = useCallback(async (ext: "pdf" | "xlsx") => {
    setBusy(ext);
    try {
      const res = await apiBinary(`${BASE}/register/form-${tab}.${ext}?${qs()}`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = `Form_${tab.toUpperCase()}_${data?.period || month}.${ext}`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      setErr(e?.message || "Export failed");
    } finally {
      setBusy("");
    }
  }, [tab, qs, data, month]);

  const wfAction = useCallback(async (action: string) => {
    if (!data?.period) return;
    setBusy(action);
    setErr("");
    try {
      await api(`${BASE}/status`, {
        method: "POST",
        body: ({ company_id: companyId, register: tab,
          period: data.period, action }),
      });
      await load();
    } catch (e: any) {
      setErr(e?.message || "Action failed");
    } finally {
      setBusy("");
    }
  }, [companyId, tab, data, load]);

  const saveCEntry = useCallback(async () => {
    if (!cEmp.length) { setErr("Pick an employee for the Form C entry."); return; }
    setBusy("centry");
    setErr("");
    try {
      await api(`${BASE}/form-c-entries`, {
        method: "POST",
        body: ({
          company_id: companyId, user_id: cEmp[0], date: cDate,
          wage_period: cDate.slice(0, 7), dtype: cType, reason: cReason,
          advance_amount: cAdv, recovery_amount: cRec, fine_amount: cFine,
          other_amount: cOther, remarks: cRemarks,
        }),
      });
      setCOpen(false);
      setCReason(""); setCAdv(""); setCRec(""); setCFine(""); setCOther(""); setCRemarks("");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Failed to save entry");
    } finally {
      setBusy("");
    }
  }, [companyId, cEmp, cDate, cType, cReason, cAdv, cRec, cFine, cOther,
      cRemarks, load]);

  const ctrOpts: Opt[] = useMemo(() => (filters?.contractors || []).map(
    (c: any) => ({ id: c.contractor_id, label: c.name })), [filters]);
  const woOpts: Opt[] = useMemo(() => (filters?.work_orders || [])
    .filter((w: any) => !ctr || w.contractor_id === ctr)
    .map((w: any) => ({ id: w.wo_id, label: w.wo_number })), [filters, ctr]);
  const peOpts: Opt[] = useMemo(() => (filters?.principal_employers || []).map(
    (p: any) => ({ id: p.pe_id, label: p.name })), [filters]);
  const siteOpts: Opt[] = useMemo(() => (filters?.sites || []).map(
    (s: string) => ({ id: s, label: s })), [filters]);
  const deptOpts: Opt[] = useMemo(() => (filters?.departments || []).map(
    (s: string) => ({ id: s, label: s })), [filters]);
  const etypeOpts: Opt[] = useMemo(() => (filters?.employee_types || []).map(
    (s: string) => ({ id: s, label: s })), [filters]);
  const emps: EmpLite[] = filters?.employees || [];

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role as string))
    return <Redirect href="/" />;

  const status = data?.status || {};
  const stCol = STATUS_COLORS[status.status || "draft"] || "#64748B";
  const isLocked = ["approved", "locked"].includes(status.status);

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="cwr-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={st.headerTitle}>Contractor Registers — Central Wages</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={st.wrap}>
        <Text style={st.framework}>{filters?.framework ||
          "Contract Labour (R&A) Act, 1970 — Central Rules, 1971"}</Text>

        {/* form tabs */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: 8, paddingVertical: 8 }}>
          {FORMS.map((f) => (
            <Pressable key={f.key} onPress={() => setTab(f.key)}
              style={[st.tab, tab === f.key && st.tabActive]}
              testID={`cwr-tab-${f.key}`}>
              <Ionicons name={f.icon} size={14}
                color={tab === f.key ? "#fff" : colors.brandPrimary} />
              <Text style={[st.tabTxt, tab === f.key && st.tabTxtActive]}>
                {f.label}
              </Text>
            </Pressable>
          ))}
        </ScrollView>

        {tab === "setup" ? (
          <SetupPanel companyId={companyId} filters={filters}
            reload={loadFilters} emps={emps} ctrOpts={ctrOpts}
            peOpts={peOpts} />
        ) : (
          <>
            {/* common filters */}
            <View style={st.card}>
              <View style={st.rowWrap}>
                <View>
                  <Text style={st.pickLbl}>Wage Period</Text>
                  <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
                    {!custom && <MonthPicker value={month} onChange={setMonth} testID="cwr-month" />}
                    <Pressable style={[st.chip, custom && st.chipOn]}
                      onPress={() => setCustom(!custom)} testID="cwr-custom-toggle">
                      <Text style={[st.chipTxt, custom && st.chipTxtOn]}>Custom Period</Text>
                    </Pressable>
                  </View>
                </View>
                {custom && (
                  <>
                    <Field label="From (YYYY-MM-DD)" value={fromDate} onChange={setFromDate} placeholder="2026-08-01" />
                    <Field label="To (YYYY-MM-DD)" value={toDate} onChange={setToDate} placeholder="2026-08-31" />
                  </>
                )}
              </View>
              <View style={st.rowWrap}>
                <Pick label="Principal Employer" value={pe} options={peOpts} onChange={setPe} testID="cwr-pe" />
                <Pick label="Contractor" value={ctr} options={ctrOpts} onChange={(v) => { setCtr(v); setWo(""); }} testID="cwr-ctr" />
                <Pick label="Work Order" value={wo} options={woOpts} onChange={setWo} testID="cwr-wo" />
                <Pick label="Site / Location" value={site} options={siteOpts} onChange={setSite} testID="cwr-site" />
              </View>
              <View style={st.rowWrap}>
                <Pick label="Department" value={dept} options={deptOpts} onChange={setDept} testID="cwr-dept" />
                <Pick label="Employee Type" value={etype} options={etypeOpts} onChange={setEtype} testID="cwr-etype" />
                <Field label="Search" value={search} onChange={setSearch} placeholder="Name / code…" />
              </View>
              <EmployeeDropdown employees={emps} value={selEmps} onChange={setSelEmps}
                multi label={`Employees (${selEmps.length ? `${selEmps.length} selected` : "All"})`}
                placeholder="All Employees — tap to pick specific ones…" testID="cwr-emp-dd" />
            </View>

            {err ? (
              <View style={st.errBox}>
                <Ionicons name="alert-circle" size={15} color="#DC2626" />
                <Text style={st.errTxt}>{err}</Text>
              </View>
            ) : null}

            {/* workflow + export bar */}
            {data ? (
              <View style={st.wfCard}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <View style={[st.stChip, { backgroundColor: stCol }]}>
                    <Text style={st.stChipTxt}>{(status.status || "draft").toUpperCase()}</Text>
                  </View>
                  <Text style={st.wfMeta}>
                    Prepared: {status.prepared_by || "—"}{status.prepared_at ? ` (${String(status.prepared_at).slice(0, 10)})` : ""} ·
                    Verified: {status.verified_by || "—"}{status.verified_at ? ` (${String(status.verified_at).slice(0, 10)})` : ""} ·
                    Approved: {status.approved_by || "—"}{status.approved_at ? ` (${String(status.approved_at).slice(0, 10)})` : ""}
                  </Text>
                </View>
                <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
                  {status.status === "draft" && (
                    <WfBtn label="Mark Prepared" icon="create-outline" onPress={() => wfAction("prepare")} busy={busy === "prepare"} />
                  )}
                  {!isLocked && (
                    <WfBtn label="Verify" icon="checkmark-outline" color="#2563EB" onPress={() => wfAction("verify")} busy={busy === "verify"} />
                  )}
                  {status.status === "verified" && (
                    <WfBtn label="Approve" icon="shield-checkmark-outline" color="#059669" onPress={() => wfAction("approve")} busy={busy === "approve"} />
                  )}
                  {status.status === "approved" && (
                    <WfBtn label="Lock" icon="lock-closed-outline" color="#B91C1C" onPress={() => wfAction("lock")} busy={busy === "lock"} />
                  )}
                  {isLocked && (
                    <WfBtn label="Unlock / Reopen" icon="lock-open-outline" color="#B45309" onPress={() => wfAction("unlock")} busy={busy === "unlock"} />
                  )}
                  <View style={{ flex: 1 }} />
                  {tab === "c" && !isLocked && (
                    <WfBtn label="+ Add Entry" icon="add-circle-outline" color="#7C3AED" onPress={() => setCOpen(true)} busy={false} />
                  )}
                  <WfBtn label="PDF" icon="document-outline" color="#C0392B" onPress={() => download("pdf")} busy={busy === "pdf"} />
                  <WfBtn label="Excel" icon="download-outline" color="#166534" onPress={() => download("xlsx")} busy={busy === "xlsx"} />
                </View>
              </View>
            ) : null}

            {loading && <ActivityIndicator style={{ marginVertical: 24 }} />}
            {!loading && data && (
              <View style={st.card}>
                <Text style={st.cardTitle}>{data.title}</Text>
                <Text style={st.cardSub}>{data.subtitle}</Text>
                {data.rows?.length ? (
                  <RegisterTable columns={data.columns} rows={data.rows} totals={data.totals} />
                ) : (
                  <Text style={st.empty}>
                    No records for this wage period / filter selection.
                  </Text>
                )}
              </View>
            )}
          </>
        )}
      </ScrollView>

      {/* Form C manual entry modal */}
      <Modal visible={cOpen} transparent animationType="fade" onRequestClose={() => setCOpen(false)}>
        <View style={st.mBack}>
          <View style={[st.mCard, { maxWidth: 560 }]}>
            <Text style={st.mTitle}>Form C — Add Deduction / Advance / Recovery</Text>
            <ScrollView style={{ maxHeight: 430 }}>
              <EmployeeDropdown employees={emps} value={cEmp} onChange={setCEmp}
                label="Employee" placeholder="Select employee…" testID="cwr-c-emp" />
              <View style={[st.rowWrap, { marginTop: 8 }]}>
                <Field label="Date (YYYY-MM-DD)" value={cDate} onChange={setCDate} />
                <Pick label="Type of Deduction" value={cType} onChange={setCType}
                  options={(filters?.deduction_categories || ["Advance", "Loan", "Fine", "Other"]).map(
                    (c: string) => ({ id: c, label: c }))} testID="cwr-c-type" />
              </View>
              <Field label="Reason / Particulars" value={cReason} onChange={setCReason} />
              <View style={st.rowWrap}>
                <Field label="Advance / Loan Amt" value={cAdv} onChange={setCAdv} keyboardType="numeric" placeholder="0" />
                <Field label="Recovery Amt" value={cRec} onChange={setCRec} keyboardType="numeric" placeholder="0" />
              </View>
              <View style={st.rowWrap}>
                <Field label="Fine Amt" value={cFine} onChange={setCFine} keyboardType="numeric" placeholder="0" />
                <Field label="Other Deduction" value={cOther} onChange={setCOther} keyboardType="numeric" placeholder="0" />
              </View>
              <Field label="Remarks" value={cRemarks} onChange={setCRemarks} />
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12, justifyContent: "flex-end" }}>
              <Pressable style={st.btnGhost} onPress={() => setCOpen(false)}>
                <Text style={st.btnGhostTxt}>Cancel</Text>
              </Pressable>
              <Pressable style={st.btnPrim} onPress={saveCEntry} disabled={busy === "centry"} testID="cwr-c-save">
                {busy === "centry" ? <ActivityIndicator size="small" color="#fff" /> :
                  <Text style={st.btnPrimTxt}>Save Entry</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function WfBtn({ label, icon, color = colors.brandPrimary, onPress, busy }: any) {
  return (
    <Pressable style={[st.wfBtn, { borderColor: color }]} onPress={onPress} disabled={busy}>
      {busy ? <ActivityIndicator size="small" color={color} /> : (
        <>
          <Ionicons name={icon} size={14} color={color} />
          <Text style={[st.wfBtnTxt, { color }]}>{label}</Text>
        </>
      )}
    </Pressable>
  );
}

/* ---------------- Setup: Principal Employers · Work Orders · Mapping ---- */
function SetupPanel({ companyId, filters, reload, emps, ctrOpts, peOpts }: {
  companyId: string; filters: any; reload: () => Promise<void>;
  emps: EmpLite[]; ctrOpts: Opt[]; peOpts: Opt[];
}) {
  const [pes, setPes] = useState<any[]>([]);
  const [wos, setWos] = useState<any[]>([]);
  const [maps, setMaps] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");
  // PE form
  const [peName, setPeName] = useState("");
  const [peAddr, setPeAddr] = useState("");
  const [peRep, setPeRep] = useState("");
  // WO form
  const [woNum, setWoNum] = useState("");
  const [woDesc, setWoDesc] = useState("");
  const [woCtr, setWoCtr] = useState("");
  const [woPe, setWoPe] = useState("");
  const [woSite, setWoSite] = useState("");
  const [woStart, setWoStart] = useState("");
  const [woEnd, setWoEnd] = useState("");
  // mapping form
  const [mEmps, setMEmps] = useState<string[]>([]);
  const [mCtr, setMCtr] = useState("");
  const [mWo, setMWo] = useState("");
  const [mSite, setMSite] = useState("");

  const loadAll = useCallback(async () => {
    if (!companyId) return;
    try {
      const [p, w, m] = await Promise.all([
        api<any>(`${BASE}/principal-employers?company_id=${companyId}`),
        api<any>(`${BASE}/work-orders?company_id=${companyId}`),
        api<any>(`${BASE}/employee-map?company_id=${companyId}`),
      ]);
      setPes(p.principal_employers || []);
      setWos(w.work_orders || []);
      setMaps(m.mappings || []);
    } catch {}
  }, [companyId]);
  useEffect(() => { void loadAll(); }, [loadAll]);

  const run = async (key: string, fn: () => Promise<any>, ok: string) => {
    setBusy(key);
    setMsg("");
    try {
      await fn();
      setMsg(`✓ ${ok}`);
      await loadAll();
      await reload();
    } catch (e: any) {
      setMsg(e?.message || "Failed");
    } finally {
      setBusy("");
    }
  };

  const empName = (uid: string) => {
    const e = emps.find((x) => x.user_id === uid);
    return e ? `${e.employee_code || ""} ${e.name || ""}`.trim() : uid;
  };
  const woOptsAll: Opt[] = wos
    .filter((w) => !mCtr || w.contractor_id === mCtr)
    .map((w) => ({ id: w.wo_id, label: w.wo_number }));

  return (
    <View>
      {msg ? <Text style={[st.msg, msg.startsWith("✓") && { color: "#059669" }]}>{msg}</Text> : null}

      {/* Principal Employers */}
      <View style={st.card}>
        <Text style={st.cardTitle}>Principal Employers</Text>
        {pes.map((p) => (
          <View key={p.pe_id} style={st.setupRow}>
            <Text style={st.setupTxt} numberOfLines={1}>
              {p.name}{p.representative ? ` · ${p.representative}` : ""}{p.address ? ` · ${p.address}` : ""}
            </Text>
            <Pressable hitSlop={8} onPress={() =>
              run(`delpe${p.pe_id}`, () => api(`${BASE}/principal-employers/${p.pe_id}?company_id=${companyId}`, { method: "DELETE" }), "Deleted")}>
              <Ionicons name="trash-outline" size={16} color="#DC2626" />
            </Pressable>
          </View>
        ))}
        {!pes.length && <Text style={st.empty}>No principal employers yet.</Text>}
        <View style={st.rowWrap}>
          <Field label="Name *" value={peName} onChange={setPeName} placeholder="Principal Employer name" />
          <Field label="Representative" value={peRep} onChange={setPeRep} />
          <Field label="Address" value={peAddr} onChange={setPeAddr} />
        </View>
        <Pressable style={st.btnPrim} disabled={busy === "pe"} testID="cwr-add-pe"
          onPress={() => run("pe", () => api(`${BASE}/principal-employers`, {
            method: "POST",
            body: ({ company_id: companyId, name: peName, address: peAddr, representative: peRep }),
          }).then(() => { setPeName(""); setPeAddr(""); setPeRep(""); }), "Principal Employer saved")}>
          {busy === "pe" ? <ActivityIndicator size="small" color="#fff" /> : <Text style={st.btnPrimTxt}>+ Add Principal Employer</Text>}
        </Pressable>
      </View>

      {/* Work Orders */}
      <View style={st.card}>
        <Text style={st.cardTitle}>Work Orders / Contracts</Text>
        {wos.map((w) => (
          <View key={w.wo_id} style={st.setupRow}>
            <Text style={st.setupTxt} numberOfLines={1}>
              {w.wo_number} · {ctrOpts.find((c) => c.id === w.contractor_id)?.label || "—"} ·
              {" "}{w.site || "no site"} {w.start_date ? `· ${w.start_date} → ${w.end_date || "…"}` : ""}
            </Text>
            <Pressable hitSlop={8} onPress={() =>
              run(`delwo${w.wo_id}`, () => api(`${BASE}/work-orders/${w.wo_id}?company_id=${companyId}`, { method: "DELETE" }), "Deleted")}>
              <Ionicons name="trash-outline" size={16} color="#DC2626" />
            </Pressable>
          </View>
        ))}
        {!wos.length && <Text style={st.empty}>No work orders yet.</Text>}
        <View style={st.rowWrap}>
          <Field label="WO Number *" value={woNum} onChange={setWoNum} placeholder="WO/2026/001" />
          <Pick label="Contractor" value={woCtr} options={ctrOpts} onChange={setWoCtr} />
          <Pick label="Principal Employer" value={woPe} options={peOpts.length ? peOpts : pes.map((p) => ({ id: p.pe_id, label: p.name }))} onChange={setWoPe} />
        </View>
        <View style={st.rowWrap}>
          <Field label="Site / Location" value={woSite} onChange={setWoSite} />
          <Field label="Start (YYYY-MM-DD)" value={woStart} onChange={setWoStart} />
          <Field label="End (YYYY-MM-DD)" value={woEnd} onChange={setWoEnd} />
          <Field label="Description" value={woDesc} onChange={setWoDesc} />
        </View>
        <Pressable style={st.btnPrim} disabled={busy === "wo"} testID="cwr-add-wo"
          onPress={() => run("wo", () => api(`${BASE}/work-orders`, {
            method: "POST",
            body: ({ company_id: companyId, wo_number: woNum, description: woDesc, contractor_id: woCtr, pe_id: woPe, site: woSite, start_date: woStart, end_date: woEnd }),
          }).then(() => { setWoNum(""); setWoDesc(""); setWoSite(""); setWoStart(""); setWoEnd(""); }), "Work Order saved")}>
          {busy === "wo" ? <ActivityIndicator size="small" color="#fff" /> : <Text style={st.btnPrimTxt}>+ Add Work Order</Text>}
        </Pressable>
      </View>

      {/* employee mapping */}
      <View style={st.card}>
        <Text style={st.cardTitle}>Employee ↔ Contractor / Work Order / Site Mapping</Text>
        <Text style={st.cardSub}>
          Employee Master is never duplicated — mapping is stored separately. Same
          contractor at multiple sites = multiple work orders, map employees to each.
        </Text>
        <EmployeeDropdown employees={emps} value={mEmps} onChange={setMEmps} multi
          label={`Employees (${mEmps.length ? `${mEmps.length} selected` : "pick"})`}
          placeholder="Pick employees to map…" testID="cwr-map-emps" />
        <View style={[st.rowWrap, { marginTop: 8 }]}>
          <Pick label="Contractor" value={mCtr} options={ctrOpts} onChange={(v) => { setMCtr(v); setMWo(""); }} />
          <Pick label="Work Order" value={mWo} options={woOptsAll} onChange={setMWo} />
          <Field label="Site (optional override)" value={mSite} onChange={setMSite} />
        </View>
        <Pressable style={st.btnPrim} disabled={busy === "map"} testID="cwr-map-save"
          onPress={() => run("map", () => api(`${BASE}/employee-map`, {
            method: "POST",
            body: ({ company_id: companyId, user_ids: mEmps, contractor_id: mCtr, work_order_id: mWo, site: mSite }),
          }).then(() => setMEmps([])), "Employees mapped")}>
          {busy === "map" ? <ActivityIndicator size="small" color="#fff" /> : <Text style={st.btnPrimTxt}>Assign Mapping</Text>}
        </Pressable>
        {maps.length ? (
          <View style={{ marginTop: 10 }}>
            <Text style={st.pickLbl}>Current mappings ({maps.length})</Text>
            {maps.slice(0, 100).map((m) => (
              <View key={m.user_id} style={st.setupRow}>
                <Text style={st.setupTxt} numberOfLines={1}>
                  {empName(m.user_id)} → {ctrOpts.find((c) => c.id === m.contractor_id)?.label || "—"}
                  {m.work_order_id ? ` · ${wos.find((w) => w.wo_id === m.work_order_id)?.wo_number || ""}` : ""}
                  {m.site ? ` · ${m.site}` : ""}
                </Text>
                <Pressable hitSlop={8} onPress={() =>
                  run(`delmap${m.user_id}`, () => api(`${BASE}/employee-map/${m.user_id}?company_id=${companyId}`, { method: "DELETE" }), "Mapping removed")}>
                  <Ionicons name="trash-outline" size={16} color="#DC2626" />
                </Pressable>
              </View>
            ))}
          </View>
        ) : null}
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 16, paddingVertical: 12, backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  headerTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  wrap: { padding: 14, paddingBottom: 48 },
  framework: { fontSize: 11, color: colors.onSurfaceSecondary, fontWeight: "600" },
  tab: {
    flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 8,
    paddingHorizontal: 12, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.brandPrimary, backgroundColor: colors.surface,
  },
  tabActive: { backgroundColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, fontWeight: "700", color: colors.brandPrimary },
  tabTxtActive: { color: "#fff" },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: 12, marginBottom: 12,
  },
  cardTitle: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface, marginBottom: 4 },
  cardSub: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginBottom: 8 },
  rowWrap: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginBottom: 8 },
  pickLbl: { fontSize: 10.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 3 },
  pickBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 9, backgroundColor: colors.surface, gap: 6,
  },
  pickTxt: { fontSize: 12.5, color: colors.onSurface, flex: 1 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 12.5,
    color: colors.onSurface, backgroundColor: colors.surface,
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
  },
  chip: {
    paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8,
    borderWidth: 1, borderColor: colors.border,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  wfCard: {
    backgroundColor: "#F8FAFC", borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: 10, marginBottom: 12,
  },
  stChip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 20 },
  stChipTxt: { color: "#fff", fontSize: 10.5, fontWeight: "800" },
  wfMeta: { fontSize: 10.5, color: colors.onSurfaceSecondary, flexShrink: 1 },
  wfBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, paddingVertical: 7,
    paddingHorizontal: 10, borderRadius: 8, borderWidth: 1.2,
    backgroundColor: colors.surface,
  },
  wfBtnTxt: { fontSize: 11.5, fontWeight: "800" },
  empty: { textAlign: "center", paddingVertical: 20, color: colors.onSurfaceSecondary, fontSize: 12.5 },
  errBox: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#FEF2F2",
    borderRadius: 8, padding: 10, marginBottom: 10, borderWidth: 1, borderColor: "#FECACA",
  },
  errTxt: { color: "#B91C1C", fontSize: 12, fontWeight: "600", flex: 1 },
  msg: { fontSize: 12, fontWeight: "700", color: "#DC2626", marginBottom: 8 },
  mBack: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.55)", justifyContent: "center",
    alignItems: "center", padding: 16,
  },
  mCard: {
    width: "100%", maxWidth: 420, backgroundColor: colors.surface,
    borderRadius: 14, padding: 16,
  },
  mTitle: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  mRow: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#F1F5F9" },
  mRowTxt: { fontSize: 13, color: colors.onSurface },
  mRowSel: { fontWeight: "800", color: colors.brandPrimary },
  setupRow: {
    flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 7,
    borderBottomWidth: 1, borderBottomColor: "#F1F5F9",
  },
  setupTxt: { flex: 1, fontSize: 12, color: colors.onSurface },
  btnPrim: {
    backgroundColor: colors.brandPrimary, borderRadius: 8, paddingVertical: 10,
    paddingHorizontal: 16, alignItems: "center", alignSelf: "flex-start",
    minWidth: 120,
  },
  btnPrimTxt: { color: "#fff", fontSize: 12.5, fontWeight: "800" },
  btnGhost: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingVertical: 10, paddingHorizontal: 16, alignItems: "center",
  },
  btnGhostTxt: { color: colors.onSurfaceSecondary, fontSize: 12.5, fontWeight: "700" },
});
