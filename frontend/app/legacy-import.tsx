/**
 * Iter 300 — Legacy Import Wizard.
 *
 * 1) Map old firms → portal firms (tick which to import)
 * 2) Head-wise selection (employee field groups + online/offline salary)
 * 3) Preview counts → Start Import → live progress → summary
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

const FIELD_GROUPS: { key: string; label: string }[] = [
  { key: "personal", label: "Personal (Name, F/H Name, DOB, DOJ, Type, Desig.)" },
  { key: "contact", label: "Contact (Mobile, Email, Address)" },
  { key: "ids", label: "IDs (PAN, Aadhaar, UAN, PF No, ESIC No)" },
  { key: "bank", label: "Bank (A/c, IFSC, Bank name)" },
  { key: "salary", label: "Salary heads (Basic, PF Basic, Gross, Allowances)" },
  { key: "status", label: "Status (Resign / Left date)" },
];

// Iter 300e (user) — every portal field an old head can be re-pointed to.
const PORTAL_FIELDS: { key: string; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "father_name", label: "Father / Husband Name" },
  { key: "gender", label: "Gender" },
  { key: "dob", label: "Date of Birth" },
  { key: "doj", label: "Date of Joining" },
  { key: "marital_status", label: "Marital Status" },
  { key: "designation", label: "Designation" },
  { key: "department", label: "Department" },
  { key: "employee_type", label: "Employee Type / Group" },
  { key: "salary_mode", label: "Salary Mode (Daily/Monthly)" },
  { key: "phone", label: "Mobile Number" },
  { key: "email", label: "Email" },
  { key: "present_address", label: "Present Address" },
  { key: "permanent_address", label: "Permanent Address" },
  { key: "pincode", label: "Pincode" },
  { key: "pan_no", label: "PAN Number" },
  { key: "aadhaar_no", label: "Aadhaar Number" },
  { key: "uan_no", label: "UAN Number" },
  { key: "pf_no", label: "PF Number" },
  { key: "esi_ip_no", label: "ESIC IP Number" },
  { key: "bank_name", label: "Bank Name" },
  { key: "bank_account", label: "Bank Account No" },
  { key: "bank_ifsc", label: "IFSC Code" },
  { key: "account_holder", label: "Account Holder Name" },
  { key: "basic_salary", label: "Basic Salary (Online)" },
  { key: "compliance_basic", label: "Compliance Basic" },
  { key: "pf_basic", label: "PF Basic" },
  { key: "compliance_gross", label: "Compliance Gross" },
  { key: "salary_monthly", label: "Actual / Offline Salary" },
  { key: "resign_date", label: "Resign Date" },
  { key: "exit_date", label: "Exit Date" },
];
const HEAD_MAP: { legacy: string; field: string; group: string }[] = [
  { legacy: "EmpName", field: "name", group: "personal" },
  { legacy: "EmpFatherName", field: "father_name", group: "personal" },
  { legacy: "Gender", field: "gender", group: "personal" },
  { legacy: "DOB", field: "dob", group: "personal" },
  { legacy: "DOJ / NewDOJ", field: "doj", group: "personal" },
  { legacy: "MaritalStatus", field: "marital_status", group: "personal" },
  { legacy: "Designation", field: "designation", group: "personal" },
  { legacy: "Department", field: "department", group: "personal" },
  { legacy: "EmpType", field: "employee_type", group: "personal" },
  { legacy: "PayBasis (Daily/Monthly)", field: "salary_mode", group: "personal" },
  { legacy: "PersMobileNo / PermMobileNo", field: "phone", group: "contact" },
  { legacy: "Email", field: "email", group: "contact" },
  { legacy: "PresentAdd", field: "present_address", group: "contact" },
  { legacy: "PermanentAdd", field: "permanent_address", group: "contact" },
  { legacy: "PinCode", field: "pincode", group: "contact" },
  { legacy: "PANNo", field: "pan_no", group: "ids" },
  { legacy: "AadharCardNo", field: "aadhaar_no", group: "ids" },
  { legacy: "UANNo", field: "uan_no", group: "ids" },
  { legacy: "PFNumber", field: "pf_no", group: "ids" },
  { legacy: "ESINo", field: "esi_ip_no", group: "ids" },
  { legacy: "BankName", field: "bank_name", group: "bank" },
  { legacy: "AccountNo", field: "bank_account", group: "bank" },
  { legacy: "IFSCCode", field: "bank_ifsc", group: "bank" },
  { legacy: "NameOnBankAc", field: "account_holder", group: "bank" },
  { legacy: "BasicSalary", field: "basic_salary", group: "salary" },
  { legacy: "PFBasicSalary", field: "pf_basic", group: "salary" },
  { legacy: "GrossPay", field: "compliance_gross", group: "salary" },
  { legacy: "Salary (rate)", field: "salary_monthly", group: "salary" },
  { legacy: "IsResign + ResignDate", field: "resign_date", group: "status" },
];

// Iter 301b (user) — salary-history heads (archive fields) can also be
// remapped among themselves or skipped entirely.
const ONLINE_HIST_FIELDS: { key: string; label: string }[] = [
  { key: "month_days", label: "Month Days" },
  { key: "present_days", label: "Present Days" },
  { key: "basic", label: "Basic (TBasicSalary)" },
  { key: "earn_heads", label: "All Earning heads (Earn1–25)" },
  { key: "deduct_heads", label: "All Deduction heads (Deduct1–20)" },
  { key: "gross", label: "Gross Salary" },
  { key: "pf_basic", label: "PF Basic" },
  { key: "ee_pf", label: "Employee EPF" },
  { key: "er_pf", label: "Employer EPF + FPF" },
  { key: "er_esi", label: "Employer ESI" },
  { key: "less_adv", label: "Less Advance" },
  { key: "less_other", label: "Less Other" },
  { key: "less_loan", label: "Less Loan" },
  { key: "less_total", label: "Less Total" },
  { key: "ot_hours", label: "OT Hours" },
  { key: "net", label: "Net Salary" },
];
const OFFLINE_HIST_FIELDS: { key: string; label: string }[] = [
  { key: "month_days", label: "Month Days" },
  { key: "present_days", label: "Present Days" },
  { key: "rate", label: "Salary Rate" },
  { key: "basic", label: "Basic" },
  { key: "w_basic", label: "W. Basic" },
  { key: "others", label: "Others (TOther)" },
  { key: "gross", label: "Gross Salary" },
  { key: "tds", label: "TDS" },
  { key: "work_hours", label: "Work Hours" },
  { key: "less_epf", label: "Less EPF" },
  { key: "less_esi", label: "Less ESI" },
  { key: "less_adv", label: "Less Advance" },
  { key: "less_other", label: "Less Other" },
  { key: "less_loan", label: "Less Loan" },
  { key: "less_total", label: "Less Total" },
  { key: "net", label: "Net Salary" },
];

type Scope = "emp" | "on" | "off";
const scopeFields = (s: Scope) =>
  s === "emp" ? PORTAL_FIELDS : s === "on" ? ONLINE_HIST_FIELDS : OFFLINE_HIST_FIELDS;
const scopeLabel = (s: Scope, k: string) =>
  k === "skip" ? "⛔ SKIP — do not import" : (scopeFields(s).find((f) => f.key === k)?.label || k);

export default function LegacyImportScreen() {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [firms, setFirms] = useState<any[]>([]);
  const [portalFirms, setPortalFirms] = useState<any[]>([]);
  const [sel, setSel] = useState<Record<number, string>>({});   // firm_no -> company_id
  const [pickFor, setPickFor] = useState<number | null>(null);  // modal
  const [groups, setGroups] = useState<string[]>(FIELD_GROUPS.map((g) => g.key));
  const [impEmp, setImpEmp] = useState(true);
  const [impOn, setImpOn] = useState(true);
  const [impOff, setImpOff] = useState(true);
  const [preview, setPreview] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<any>(null);
  const [showMap, setShowMap] = useState(false); // mapping chart
  // Iter 300e (user) — manual head overrides + 2-step confirmation.
  const [overrides, setOverrides] = useState<Record<string, string>>({}); // src field -> dst field | 'skip'
  const [ovOn, setOvOn] = useState<Record<string, string>>({});   // online salary-history overrides
  const [ovOff, setOvOff] = useState<Record<string, string>>({}); // offline salary-history overrides
  const [editHead, setEditHead] = useState<{ scope: Scope; field: string } | null>(null);
  const [confirmStep, setConfirmStep] = useState(0);                      // 0 hidden, 1, 2

  const ovFor = (s: Scope) => (s === "emp" ? overrides : s === "on" ? ovOn : ovOff);
  const setOvFor = (s: Scope, v: Record<string, string>) =>
    (s === "emp" ? setOverrides(v) : s === "on" ? setOvOn(v) : setOvOff(v));
  const totalChanges =
    Object.keys(overrides).length + Object.keys(ovOn).length + Object.keys(ovOff).length;
  const allChanges: string[] = [
    ...Object.entries(overrides).map(([s, d]) =>
      `${HEAD_MAP.find((h) => h.field === s)?.legacy || s} → ${scopeLabel("emp", d)}`),
    ...Object.entries(ovOn).map(([s, d]) =>
      `Online salary: ${scopeLabel("on", s)} → ${scopeLabel("on", d)}`),
    ...Object.entries(ovOff).map(([s, d]) =>
      `Offline salary: ${scopeLabel("off", s)} → ${scopeLabel("off", d)}`),
  ];

  useEffect(() => {
    (async () => {
      try {
        const r = await api<any>("/admin/legacy-import/firms");
        setFirms(r.firms || []);
        setPortalFirms(r.portal_firms || []);
      } catch (e: any) {
        setErr(e?.message || "Legacy server not reachable — run the setup first.");
      } finally { setLoading(false); }
    })();
  }, []);

  const body = () => ({
    mappings: Object.entries(sel).map(([fn, cid]) =>
      cid === "__create__"
        ? { firm_no: Number(fn), company_id: null, create_new: true }
        : { firm_no: Number(fn), company_id: cid }),
    import_employees: impEmp,
    employee_fields: groups,
    salary_online: impOn,
    salary_offline: impOff,
    field_overrides: overrides,
    salary_online_overrides: ovOn,
    salary_offline_overrides: ovOff,
    ...(replApplied ? { replace_names: replApplied } : {}),
  });

  const runPreview = async () => {
    setBusy(true); setErr(""); setPreview(null);
    try {
      const r = await api<any>("/admin/legacy-import/preview", { method: "POST", body: body() });
      setPreview(r.firms || []);
    } catch (e: any) { setErr(e?.message || "Preview failed"); }
    finally { setBusy(false); }
  };

  const startImport = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api<any>("/admin/legacy-import/run", { method: "POST", body: body() });
      pollJob(r.job_id);
    } catch (e: any) { setErr(e?.message || "Import failed to start"); setBusy(false); }
  };

  const pollJob = async (id: string) => {
    try {
      const j = await api<any>(`/admin/legacy-import/jobs/${id}`);
      setJob(j);
      if (j.status === "done" || j.status === "failed") { setBusy(false); return; }
    } catch { /* keep polling */ }
    setTimeout(() => pollJob(id), 2500);
  };

  // Iter 305 (user) — Comparison Record: matched names, Replace-or-Not.
  const [cmp, setCmp] = useState<any>(null);          // employee-compare response
  const [cmpOpen, setCmpOpen] = useState(false);
  const [cmpBusy, setCmpBusy] = useState(false);
  const [replSel, setReplSel] = useState<Record<string, boolean>>({}); // "firmNo|nameLower" -> replace?
  const [replApplied, setReplApplied] = useState<Record<string, string[]> | null>(null);

  const openCompare = async () => {
    setCmpBusy(true);
    try {
      const r = await api<any>("/admin/legacy-import/employee-compare", {
        method: "POST", body: body(),
      });
      setCmp(r);
      const init: Record<string, boolean> = {};
      (r.firms || []).forEach((f: any) =>
        (f.matched || []).forEach((mt: any) => { init[`${f.firm_no}|${mt.name.toLowerCase()}`] = true; }));
      setReplSel(init);
      setCmpOpen(true);
    } catch (e: any) { setErr(e?.message || "Compare failed"); }
    finally { setCmpBusy(false); }
  };

  const applyReplaceChoices = () => {
    const out: Record<string, string[]> = {};
    (cmp?.firms || []).forEach((f: any) => {
      out[String(f.firm_no)] = (f.matched || [])
        .filter((mt: any) => replSel[`${f.firm_no}|${mt.name.toLowerCase()}`])
        .map((mt: any) => mt.name);
    });
    setReplApplied(out);
    setCmpOpen(false);
  };

  const mappedCount = Object.keys(sel).length;

  // Iter 303 (user, A-ONE MOTOR'S) — undo a wrong import & re-import.
  const [undoFor, setUndoFor] = useState<any>(null);   // firm object
  const [undoBusy, setUndoBusy] = useState(false);
  const [undoMsg, setUndoMsg] = useState("");

  // Iter 303b (user) — preview the new firm BEFORE confirming creation.
  const [createPrev, setCreatePrev] = useState<any>(null);   // parsed firm settings
  const [createPrevFor, setCreatePrevFor] = useState<number | null>(null);
  const [createPrevBusy, setCreatePrevBusy] = useState(false);

  const openCreatePreview = async (firmNo: number) => {
    setPickFor(null); setCreatePrevBusy(true); setCreatePrevFor(firmNo); setCreatePrev(null);
    try {
      const r = await api<any>(`/admin/legacy-import/firm-preview/${firmNo}`);
      setCreatePrev(r);
    } catch (e: any) {
      setErr(e?.message || "Could not read legacy Firm Master");
      setCreatePrevFor(null);
    } finally { setCreatePrevBusy(false); }
  };

  const doUndo = async () => {
    if (!undoFor) return;
    setUndoBusy(true); setUndoMsg("");
    try {
      const r = await api<any>("/admin/legacy-import/undo", {
        method: "POST",
        body: { firm_no: undoFor.firm_no, company_id: undoFor.imported_company_id },
      });
      setUndoMsg(
        `↩️ ${undoFor.firm_name}: ${r.employees_deleted} imported employees, ` +
        `${r.salary_rows_deleted} salary rows and ${r.published_runs_deleted} published ` +
        `runs removed — firm unlocked for re-import.`);
      setUndoFor(null);
      const fr = await api<any>("/admin/legacy-import/firms");
      setFirms(fr.firms || []);
      setPortalFirms(fr.portal_firms || []);
    } catch (e: any) { setErr(e?.message || "Undo failed"); }
    finally { setUndoBusy(false); }
  };

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <Stack.Screen options={{ title: "Legacy Import Wizard" }} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 80 }}>
        <Text style={st.h1}>Legacy Import Wizard</Text>
        <Text style={st.sub}>
          Choose the firms, tick the heads you want, preview, then import.
          Nothing is written until you press Start Import.
        </Text>
        {loading ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} /> : (
          <>
            {/* STEP 1 — firm mapping */}
            <View style={st.card}>
              <Text style={st.cardTitle}>1️⃣  Select old firms &amp; map to portal firms ({mappedCount} selected)</Text>
              {undoMsg ? (
                <Text style={[st.firmMeta, { color: "#16a34a", fontWeight: "700", marginBottom: 6 }]}>{undoMsg}</Text>
              ) : null}
              {firms.map((f) => {
                const cid = sel[f.firm_no];
                const pname = portalFirms.find((p) => p.company_id === cid)?.name;
                if (f.already_imported) {
                  return (
                    <View key={f.firm_no} style={[st.firmRow, { opacity: 0.9 }]}>
                      <Ionicons name="checkmark-circle" size={20} color="#16a34a" />
                      <View style={{ flex: 1, minWidth: 0 }}>
                        <Text style={st.firmName} numberOfLines={1}>{f.firm_name}</Text>
                        <Text style={[st.firmMeta, { color: "#16a34a", fontWeight: "700" }]} numberOfLines={1}>
                          ✓ ALREADY IMPORTED{f.imported_into ? ` → ${f.imported_into}` : ""}
                          {f.imported_at ? ` · ${String(f.imported_at).slice(0, 10)}` : ""}
                        </Text>
                      </View>
                      {f.imported_company_id ? (
                        <Pressable style={st.undoBtn} onPress={() => setUndoFor(f)} disabled={undoBusy}>
                          <Ionicons name="arrow-undo-outline" size={12} color="#DC2626" />
                          <Text style={st.undoBtnTxt}>Undo</Text>
                        </Pressable>
                      ) : null}
                    </View>
                  );
                }
                return (
                  <View key={f.firm_no} style={st.firmRow}>
                    <Pressable
                      onPress={() => {
                        const c = { ...sel };
                        if (cid) delete c[f.firm_no];
                        else c[f.firm_no] = f.suggested_company_id || "";
                        if (c[f.firm_no] === "") { setPickFor(f.firm_no); }
                        setSel(c);
                      }}
                      hitSlop={8}
                    >
                      <Ionicons
                        name={cid !== undefined ? "checkbox" : "square-outline"}
                        size={20}
                        color={cid !== undefined ? colors.brandPrimary : colors.onSurfaceTertiary}
                      />
                    </Pressable>
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <Text style={st.firmName} numberOfLines={1}>{f.firm_name}</Text>
                      <Text style={st.firmMeta} numberOfLines={1}>
                        {f.employees} emp (✅ {f.employees_active ?? "?"} active · 🔻 {f.employees_resigned ?? "?"} resigned) · online {f.online_months} mo · offline {f.offline_months} mo
                      </Text>
                    </View>
                    {cid !== undefined ? (
                      <Pressable style={st.mapBtn} onPress={() => setPickFor(f.firm_no)}>
                        <Text
                          style={[st.mapBtnTxt, cid === "__create__" && { color: "#16a34a" }]}
                          numberOfLines={1}
                        >
                          {cid === "__create__" ? "➕ NEW FIRM (will be created)" : (pname || "→ choose portal firm")}
                        </Text>
                        <Ionicons name="chevron-down" size={12} color={colors.brandPrimary} />
                      </Pressable>
                    ) : null}
                  </View>
                );
              })}
            </View>

            {/* STEP 2 — head-wise selection */}
            <View style={st.card}>
              <Text style={st.cardTitle}>2️⃣  What to import (tick the heads)</Text>
              <Pressable style={st.tickRow} onPress={() => setImpEmp(!impEmp)}>
                <Ionicons name={impEmp ? "checkbox" : "square-outline"} size={19} color={colors.brandPrimary} />
                <Text style={st.tickMain}>Employee Master</Text>
              </Pressable>
              {impEmp ? FIELD_GROUPS.map((g) => (
                <Pressable
                  key={g.key}
                  style={[st.tickRow, { paddingLeft: 28 }]}
                  onPress={() => setGroups(groups.includes(g.key)
                    ? groups.filter((x) => x !== g.key) : [...groups, g.key])}
                >
                  <Ionicons
                    name={groups.includes(g.key) ? "checkbox" : "square-outline"}
                    size={17} color={groups.includes(g.key) ? colors.brandPrimary : colors.onSurfaceTertiary}
                  />
                  <Text style={st.tickTxt}>{g.label}</Text>
                </Pressable>
              )) : null}
              <Pressable style={st.tickRow} onPress={() => setImpOn(!impOn)}>
                <Ionicons name={impOn ? "checkbox" : "square-outline"} size={19} color={colors.brandPrimary} />
                <Text style={st.tickMain}>Salary History — ONLINE (PF/ESIC salary, head-wise)</Text>
              </Pressable>
              <Pressable style={st.tickRow} onPress={() => setImpOff(!impOff)}>
                <Ionicons name={impOff ? "checkbox" : "square-outline"} size={19} color={colors.brandPrimary} />
                <Text style={st.tickMain}>Salary History — OFFLINE (actual salary)</Text>
              </Pressable>

              {/* Iter 300e (user) — editable head mapping + override */}
              <Pressable style={[st.tickRow, { marginTop: 6 }]} onPress={() => setShowMap(!showMap)}>
                <Ionicons name={showMap ? "chevron-down" : "chevron-forward"} size={16} color={colors.brandPrimary} />
                <Text style={[st.tickMain, { color: colors.brandPrimary }]}>
                  📖 Head Mapping — verify &amp; change where each old head settles
                </Text>
              </Pressable>
              {showMap ? (
                <View style={st.mapBox}>
                  <Text style={st.mapHint}>
                    Tap any row to change its target head, or set SKIP to not import it.
                  </Text>
                  {["personal", "contact", "ids", "bank", "salary", "status"]
                    .filter((g) => groups.includes(g))
                    .map((g) => (
                      <View key={g}>
                        <Text style={st.mapHead}>
                          {FIELD_GROUPS.find((x) => x.key === g)?.label || g}
                        </Text>
                        {HEAD_MAP.filter((h) => h.group === g).map((h) => {
                          const target = overrides[h.field] ?? h.field;
                          const changed = overrides[h.field] !== undefined && overrides[h.field] !== h.field;
                          return (
                            <Pressable key={h.field} style={st.mapRow} onPress={() => setEditHead({ scope: "emp", field: h.field })}>
                              <Text style={st.mapOld} numberOfLines={2}>{h.legacy}</Text>
                              <Ionicons name="arrow-forward" size={11} color={colors.onSurfaceTertiary} />
                              <View style={{ flex: 1.2, flexDirection: "row", alignItems: "center", gap: 4 }}>
                                <Text
                                  style={[
                                    st.mapNew,
                                    changed && (target === "skip" ? { color: "#DC2626" } : { color: "#B45309" }),
                                  ]}
                                  numberOfLines={2}
                                >
                                  {scopeLabel("emp", target)}
                                </Text>
                                {changed ? (
                                  <View style={[st.chgBadge, target === "skip" && { backgroundColor: "#FEE2E2" }]}>
                                    <Text style={[st.chgBadgeTxt, target === "skip" && { color: "#DC2626" }]}>
                                      {target === "skip" ? "SKIPPED" : "CHANGED"}
                                    </Text>
                                  </View>
                                ) : null}
                                <Ionicons name="create-outline" size={13} color={colors.brandPrimary} />
                              </View>
                            </Pressable>
                          );
                        })}
                      </View>
                    ))}
                  <Text style={st.mapHead}>SALARY HISTORY → &apos;Legacy Salary Records&apos; screen (archive — live payroll untouched)</Text>
                  {([
                    ["on", "Salary History — ONLINE (SalaryTrans)", impOn, ONLINE_HIST_FIELDS, ovOn],
                    ["off", "Salary History — OFFLINE (SalaryTransoff)", impOff, OFFLINE_HIST_FIELDS, ovOff],
                  ] as [Scope, string, boolean, { key: string; label: string }[], Record<string, string>][])
                    .filter(([, , on]) => on)
                    .map(([sc, title, , flds, ov]) => (
                      <View key={sc}>
                        <Text style={st.mapHead}>{title}</Text>
                        {flds.map((f) => {
                          const target = ov[f.key] ?? f.key;
                          const changed = ov[f.key] !== undefined && ov[f.key] !== f.key;
                          return (
                            <Pressable key={f.key} style={st.mapRow} onPress={() => setEditHead({ scope: sc, field: f.key })}>
                              <Text style={st.mapOld} numberOfLines={2}>{f.label}</Text>
                              <Ionicons name="arrow-forward" size={11} color={colors.onSurfaceTertiary} />
                              <View style={{ flex: 1.2, flexDirection: "row", alignItems: "center", gap: 4 }}>
                                <Text
                                  style={[
                                    st.mapNew,
                                    changed && (target === "skip" ? { color: "#DC2626" } : { color: "#B45309" }),
                                  ]}
                                  numberOfLines={2}
                                >
                                  {scopeLabel(sc, target)}
                                </Text>
                                {changed ? (
                                  <View style={[st.chgBadge, target === "skip" && { backgroundColor: "#FEE2E2" }]}>
                                    <Text style={[st.chgBadgeTxt, target === "skip" && { color: "#DC2626" }]}>
                                      {target === "skip" ? "SKIPPED" : "CHANGED"}
                                    </Text>
                                  </View>
                                ) : null}
                                <Ionicons name="create-outline" size={13} color={colors.brandPrimary} />
                              </View>
                            </Pressable>
                          );
                        })}
                      </View>
                    ))}
                  {totalChanges ? (
                    <Pressable style={st.resetBtn} onPress={() => { setOverrides({}); setOvOn({}); setOvOff({}); }}>
                      <Ionicons name="refresh" size={13} color="#DC2626" />
                      <Text style={{ color: "#DC2626", fontSize: 11.5, fontWeight: "700" }}>
                        Reset all {totalChanges} change(s) to default
                      </Text>
                    </Pressable>
                  ) : null}
                </View>
              ) : null}
            </View>

            {/* STEP 3 — preview & run */}
            <View style={st.card}>
              <Text style={st.cardTitle}>3️⃣  Preview &amp; Import</Text>
              <Pressable
                style={[st.actBtn, { backgroundColor: colors.brandPrimary, opacity: mappedCount && !busy ? 1 : 0.5 }]}
                disabled={!mappedCount || busy}
                onPress={runPreview}
              >
                <Ionicons name="eye-outline" size={16} color="#fff" />
                <Text style={st.actTxt}>Preview (nothing is saved)</Text>
              </Pressable>
              {preview ? preview.map((p) => (
                <View key={p.firm_no} style={st.prevRow}>
                  <Text style={st.firmName}>→ {p.company_name}</Text>
                  <Text style={st.firmMeta}>
                    {impEmp ? `Employees: ${p.employees_new ?? 0} new + ${p.employees_existing ?? 0} update · ` : ""}
                    {impOn ? `Online: ${p.online_rows ?? 0} rows / ${p.online_months ?? 0} months · ` : ""}
                    {impOff ? `Offline: ${p.offline_rows ?? 0} rows / ${p.offline_months ?? 0} months` : ""}
                  </Text>
                  {/* Iter 331 (user) — allowance heads found in the old DB:
                      matching Firm Master labels are ENABLED, missing ones
                      are CREATED as custom heads. */}
                  {(p.allowance_heads || []).length ? (
                    <View style={{ marginTop: 4 }}>
                      <Text style={[st.firmMeta, { fontWeight: "800", color: "#5B21B6" }]}>
                        Allowances (auto-set on Firm Master):
                      </Text>
                      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 3 }}>
                        {p.allowance_heads.map((h: any) => (
                          <View
                            key={h.head}
                            style={{
                              flexDirection: "row", alignItems: "center", gap: 3,
                              paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999,
                              backgroundColor: h.action === "create" ? "#FEF3C7" : "#EDE9FE",
                            }}
                          >
                            <Ionicons
                              name={h.action === "create" ? "add-circle-outline" : "checkmark-circle-outline"}
                              size={11}
                              color={h.action === "create" ? "#92400E" : "#5B21B6"}
                            />
                            <Text style={{ fontSize: 10, fontWeight: "700", color: h.action === "create" ? "#92400E" : "#5B21B6" }}>
                              {h.head}{h.action === "create" ? " (new)" : ""}
                            </Text>
                          </View>
                        ))}
                      </View>
                    </View>
                  ) : null}
                </View>
              )) : null}
              {preview && impEmp ? (
                <Pressable
                  style={[st.actBtn, { backgroundColor: "#0E7490", opacity: cmpBusy ? 0.5 : 1 }]}
                  disabled={cmpBusy}
                  onPress={openCompare}
                >
                  <Ionicons name="git-compare-outline" size={16} color="#fff" />
                  <Text style={st.actTxt}>
                    {cmpBusy ? "Comparing…" : "Compare Records — matched names, Replace or Not"}
                  </Text>
                </Pressable>
              ) : null}
              {replApplied ? (
                <Text style={[st.firmMeta, { color: "#0E7490", fontWeight: "700" }]}>
                  ✔ Replace choices applied: {Object.values(replApplied).reduce((a, l) => a + l.length, 0)} matched
                  name(s) will be REPLACED; other matched names stay untouched. New employees import regardless.
                </Text>
              ) : null}
              {preview ? (
                <Pressable
                  style={[st.actBtn, { backgroundColor: "#B45309", opacity: busy ? 0.5 : 1 }]}
                  disabled={busy}
                  onPress={() => setConfirmStep(1)}
                >
                  <Ionicons name="download-outline" size={16} color="#fff" />
                  <Text style={st.actTxt}>Start Import</Text>
                </Pressable>
              ) : null}
              {job ? (
                <View style={st.prevRow}>
                  <Text style={st.firmName}>
                    {job.status === "done" ? "✅ Import complete" :
                      job.status === "failed" ? "❌ Import failed" : "⏳ Importing…"}
                  </Text>
                  <Text style={st.firmMeta}>
                    Employees: {job.totals?.employees_created || 0} created, {job.totals?.employees_updated || 0} updated{job.totals?.employees_kept ? `, ${job.totals.employees_kept} kept (not replaced)` : ""} ·
                    Online rows: {job.totals?.online_rows || 0} · Offline rows: {job.totals?.offline_rows || 0}
                    {job.totals?.firms_created ? ` · Firms created: ${job.totals.firms_created}` : ""}
                    {job.totals?.allowance_labels_enabled ? ` · Allowances enabled on Firm Master: ${job.totals.allowance_labels_enabled}` : ""}
                    {job.totals?.allowance_heads_created ? ` · New allowance heads created: ${job.totals.allowance_heads_created}` : ""}
                  </Text>
                  {(job.errors || []).slice(0, 5).map((e: string, i: number) => (
                    <Text key={i} style={st.errTxt}>{e}</Text>
                  ))}
                  {job.status === "done" ? (
                    <Text style={st.firmMeta}>
                      View imported salary: Import / Export → Legacy Salary Records
                    </Text>
                  ) : null}
                </View>
              ) : null}
            </View>
          </>
        )}
        {err ? <Text style={st.errTxt}>{err}</Text> : null}
      </ScrollView>

      {/* Iter 305 (user) — Comparison Record modal, grouped firm-wise */}
      <Modal transparent visible={cmpOpen} animationType="fade" onRequestClose={() => setCmpOpen(false)}>
        <Pressable style={st.backdrop} onPress={() => setCmpOpen(false)} />
        <View style={st.pickSheet}>
          <Text style={st.confTitle}>🔍 Comparison Record — confirm Replace or Not</Text>
          <Text style={st.confTxt}>
            Matched names already exist in the mapped firm. Tick = REPLACE with legacy data;
            untick = keep the portal record untouched. New employees import regardless.
          </Text>
          <ScrollView style={{ maxHeight: 420, marginTop: 6 }}>
            {(cmp?.firms || []).map((f: any) => {
              const allOn = (f.matched || []).every((mt: any) => replSel[`${f.firm_no}|${mt.name.toLowerCase()}`]);
              return (
                <View key={f.firm_no} style={{ marginBottom: 14 }}>
                  <Text style={[st.firmName, { color: colors.brandPrimary }]}>
                    {firms.find((x) => x.firm_no === f.firm_no)?.firm_name || `Firm ${f.firm_no}`} → {f.company_name}
                  </Text>
                  <Text style={st.firmMeta}>
                    Old DB: {f.total} total (✅ {f.active} active · 🔻 {f.resigned} resigned) ·{" "}
                    {f.new_count} NEW will import · {f.matched_count} matched
                  </Text>
                  {(f.matched || []).length ? (
                    <>
                      <Pressable
                        style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 6 }}
                        onPress={() => {
                          const c = { ...replSel };
                          (f.matched || []).forEach((mt: any) => { c[`${f.firm_no}|${mt.name.toLowerCase()}`] = !allOn; });
                          setReplSel(c);
                        }}
                      >
                        <Ionicons name={allOn ? "checkbox" : "square-outline"} size={18} color={colors.brandPrimary} />
                        <Text style={[st.tickTxt, { fontWeight: "800" }]}>Replace ALL matched ({f.matched_count})</Text>
                      </Pressable>
                      {(f.matched || []).map((mt: any) => {
                        const k = `${f.firm_no}|${mt.name.toLowerCase()}`;
                        return (
                          <Pressable
                            key={k}
                            style={{ flexDirection: "row", alignItems: "flex-start", gap: 6, paddingVertical: 4, paddingLeft: 10 }}
                            onPress={() => setReplSel({ ...replSel, [k]: !replSel[k] })}
                          >
                            <Ionicons
                              name={replSel[k] ? "checkbox" : "square-outline"}
                              size={17}
                              color={replSel[k] ? "#B45309" : colors.onSurfaceTertiary}
                            />
                            <View style={{ flex: 1, minWidth: 0 }}>
                              <Text style={st.tickTxt}>
                                {mt.name}{mt.employee_code ? `  (#${mt.employee_code})` : ""}
                                {"  "}
                                <Text style={{ color: mt.change_count ? "#B45309" : "#16a34a", fontSize: 11 }}>
                                  {mt.change_count ? `${mt.change_count} field(s) differ` : "no difference"}
                                </Text>
                              </Text>
                              {(mt.changes || []).slice(0, 4).map((c: any) => (
                                <Text key={c.field} style={st.firmMeta} numberOfLines={1}>
                                  • {c.field}: {String(c.old ?? "—")} → {String(c.new)}
                                </Text>
                              ))}
                            </View>
                          </Pressable>
                        );
                      })}
                    </>
                  ) : (
                    <Text style={[st.firmMeta, { color: "#16a34a" }]}>No matched names — all employees are NEW.</Text>
                  )}
                  {f.new_count ? (
                    <Text style={st.firmMeta} numberOfLines={3}>
                      NEW ({f.new_count}): {(f.new_names || []).slice(0, 12).join(", ")}{f.new_count > 12 ? "…" : ""}
                    </Text>
                  ) : null}
                </View>
              );
            })}
          </ScrollView>
          <Pressable style={[st.actBtn, { backgroundColor: colors.brandPrimary }]} onPress={applyReplaceChoices}>
            <Ionicons name="checkmark" size={16} color="#fff" />
            <Text style={st.actTxt}>Apply choices</Text>
          </Pressable>
          <Pressable style={st.cancelBtn} onPress={() => setCmpOpen(false)}>
            <Text style={st.cancelTxt}>Cancel</Text>
          </Pressable>
        </View>
      </Modal>

      {/* Iter 303b (user) — preview the new firm BEFORE confirming */}
      <Modal
        transparent
        visible={createPrevFor !== null}
        animationType="fade"
        onRequestClose={() => { setCreatePrevFor(null); setCreatePrev(null); }}
      >
        <Pressable style={st.backdrop} onPress={() => { setCreatePrevFor(null); setCreatePrev(null); }} />
        <View style={st.pickSheet}>
          <Text style={st.confTitle}>🏢 New firm — this is what will be created</Text>
          {createPrevBusy ? <ActivityIndicator style={{ marginVertical: 30 }} color={colors.brandPrimary} /> : createPrev ? (
            <>
              <ScrollView style={{ maxHeight: 380 }}>
                {createPrev.duplicate_company ? (
                  <Text style={[st.confTxt, { color: "#DC2626", fontWeight: "800" }]}>
                    ⚠️ A firm named &quot;{createPrev.duplicate_company.name}&quot; already exists — the
                    import will use that existing firm instead of creating a duplicate.
                  </Text>
                ) : null}
                {([
                  ["Firm Name", createPrev.name],
                  ["Address", createPrev.full_address],
                  ["Email", [createPrev.email_1, createPrev.email_2].filter(Boolean).join(", ")],
                  ["Start Date", createPrev.start_date],
                  ["Business Nature", createPrev.business_nature],
                  ["EPF No (applicable)", createPrev.pf_no],
                  ["EPF Portal Login", [createPrev.pf_user_id, createPrev.pf_password].filter(Boolean).join(" / ")],
                  ["ESI No (applicable)", createPrev.esi_no],
                  ["ESI Portal Login", [createPrev.esi_user_id, createPrev.esi_password].filter(Boolean).join(" / ")],
                  ["Bank", [createPrev.bank?.bank_name, createPrev.bank?.account_no, createPrev.bank?.ifsc].filter(Boolean).join(" · ")],
                  ["PAN", createPrev.docs?.PAN],
                  ["TAN", createPrev.docs?.TAN],
                  ["GST", createPrev.docs?.GST],
                  ["Contact / Owner", [createPrev.owner, createPrev.phone].filter(Boolean).join(" · ")],
                ] as [string, any][]).map(([k, v]) => (
                  <View key={k} style={{ flexDirection: "row", paddingVertical: 5, borderBottomWidth: 1, borderBottomColor: colors.border }}>
                    <Text style={[st.confTxt, { width: 150, fontWeight: "800", marginTop: 0 }]}>{k}</Text>
                    <Text style={[st.confTxt, { flex: 1, marginTop: 0, color: v ? colors.onSurface : colors.onSurfaceTertiary }]}>
                      {v || "— not found in legacy —"}
                    </Text>
                  </View>
                ))}
                <Text style={st.confTxt}>
                  These settings go into the new firm&apos;s Firm Master. You can edit anything
                  there after creation. The firm is created only when you Start Import.
                </Text>
              </ScrollView>
              <Pressable
                style={[st.actBtn, { backgroundColor: "#16a34a" }]}
                onPress={() => {
                  if (createPrevFor !== null) setSel({ ...sel, [createPrevFor]: "__create__" });
                  setCreatePrevFor(null); setCreatePrev(null);
                }}
              >
                <Ionicons name="checkmark" size={16} color="#fff" />
                <Text style={st.actTxt}>OK — create this firm on import</Text>
              </Pressable>
              <Pressable style={st.cancelBtn} onPress={() => { setCreatePrevFor(null); setCreatePrev(null); }}>
                <Text style={st.cancelTxt}>Cancel</Text>
              </Pressable>
            </>
          ) : null}
        </View>
      </Modal>

      {/* Iter 303 (user) — undo import confirmation */}
      <Modal transparent visible={undoFor !== null} animationType="fade" onRequestClose={() => setUndoFor(null)}>
        <Pressable style={st.backdrop} onPress={() => setUndoFor(null)} />
        <View style={st.pickSheet}>
          <Text style={st.confTitle}>↩️ Undo import of &quot;{undoFor?.firm_name}&quot;?</Text>
          <Text style={st.confTxt}>
            This removes from {undoFor?.imported_into || "the mapped firm"}:
            {"\n"}• employees CREATED by this import (pre-existing employees are kept)
            {"\n"}• the imported legacy salary history of this firm
            {"\n"}• legacy months published into the Compliance Salary Process
            {"\n"}The old firm is then unlocked so you can re-import it — e.g. into a newly created firm.
          </Text>
          <Pressable
            style={[st.actBtn, { backgroundColor: "#DC2626", opacity: undoBusy ? 0.5 : 1 }]}
            disabled={undoBusy}
            onPress={doUndo}
          >
            <Ionicons name="arrow-undo" size={16} color="#fff" />
            <Text style={st.actTxt}>YES — Undo this import</Text>
          </Pressable>
          <Pressable style={st.cancelBtn} onPress={() => setUndoFor(null)}>
            <Text style={st.cancelTxt}>Cancel</Text>
          </Pressable>
        </View>
      </Modal>

      {/* portal firm picker */}
      <Modal transparent visible={pickFor !== null} animationType="fade" onRequestClose={() => setPickFor(null)}>
        <Pressable style={st.backdrop} onPress={() => setPickFor(null)} />
        <View style={st.pickSheet}>
          <Text style={st.cardTitle}>Import into which portal firm?</Text>
          <ScrollView style={{ maxHeight: 400 }}>
            {/* Iter 303 (user) — no match? create the firm with its legacy settings */}
            <Pressable
              style={st.pickRow}
              onPress={() => { if (pickFor !== null) openCreatePreview(pickFor); }}
            >
              <Ionicons name="add-circle" size={16} color="#16a34a" />
              <Text style={[st.tickTxt, { color: "#16a34a", fontWeight: "800" }]}>
                ➕ Create NEW firm in Firm Master (name, address, PF/ESI &amp; settings from legacy)
              </Text>
            </Pressable>
            {portalFirms.map((p) => (
              <Pressable
                key={p.company_id}
                style={st.pickRow}
                onPress={() => {
                  if (pickFor !== null) setSel({ ...sel, [pickFor]: p.company_id });
                  setPickFor(null);
                }}
              >
                <Ionicons name="business-outline" size={15} color={colors.brandPrimary} />
                <Text style={st.tickTxt}>{p.name}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      </Modal>
      {/* Iter 300e (user) — head remap picker (employee + salary-history) */}
      <Modal transparent visible={editHead !== null} animationType="fade" onRequestClose={() => setEditHead(null)}>
        <Pressable style={st.backdrop} onPress={() => setEditHead(null)} />
        <View style={st.pickSheet}>
          <Text style={st.cardTitle}>
            Where should &quot;{editHead
              ? (editHead.scope === "emp"
                ? (HEAD_MAP.find((h) => h.field === editHead.field)?.legacy || editHead.field)
                : scopeLabel(editHead.scope, editHead.field))
              : ""}&quot; go?
          </Text>
          <ScrollView style={{ maxHeight: 420 }}>
            <Pressable
              style={st.pickRow}
              onPress={() => {
                if (editHead) {
                  const c = { ...ovFor(editHead.scope) };
                  delete c[editHead.field];
                  setOvFor(editHead.scope, c);
                }
                setEditHead(null);
              }}
            >
              <Ionicons name="refresh-outline" size={15} color={colors.brandPrimary} />
              <Text style={[st.tickTxt, { fontWeight: "700" }]}>
                Default — {editHead ? scopeLabel(editHead.scope, editHead.field) : ""}
              </Text>
            </Pressable>
            <Pressable
              style={st.pickRow}
              onPress={() => {
                if (editHead) setOvFor(editHead.scope, { ...ovFor(editHead.scope), [editHead.field]: "skip" });
                setEditHead(null);
              }}
            >
              <Ionicons name="close-circle-outline" size={15} color="#DC2626" />
              <Text style={[st.tickTxt, { color: "#DC2626", fontWeight: "700" }]}>
                SKIP — do not import this head
              </Text>
            </Pressable>
            {scopeFields(editHead?.scope || "emp").filter((p) => p.key !== editHead?.field).map((p) => (
              <Pressable
                key={p.key}
                style={st.pickRow}
                onPress={() => {
                  if (editHead) setOvFor(editHead.scope, { ...ovFor(editHead.scope), [editHead.field]: p.key });
                  setEditHead(null);
                }}
              >
                <Ionicons
                  name={editHead && ovFor(editHead.scope)[editHead.field] === p.key ? "radio-button-on" : "radio-button-off"}
                  size={15}
                  color={editHead && ovFor(editHead.scope)[editHead.field] === p.key ? colors.brandPrimary : colors.onSurfaceTertiary}
                />
                <Text style={st.tickTxt}>{p.label}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      </Modal>

      {/* Iter 300e (user) — 2-step confirmation before writing anything */}
      <Modal transparent visible={confirmStep > 0} animationType="fade" onRequestClose={() => setConfirmStep(0)}>
        <Pressable style={st.backdrop} onPress={() => setConfirmStep(0)} />
        <View style={st.pickSheet}>
          {confirmStep === 1 ? (
            <>
              <Text style={st.confTitle}>⚠️ Confirmation 1 of 2 — Verify Head Mapping</Text>
              <Text style={st.confTxt}>
                {mappedCount} firm(s) selected.
                {impEmp ? ` Employee Master (${groups.length} head groups).` : ""}
                {impOn ? " Online salary history." : ""}
                {impOff ? " Offline salary history." : ""}
              </Text>
              {allChanges.length ? (
                <View style={st.confBox}>
                  <Text style={[st.confTxt, { fontWeight: "800", color: "#B45309" }]}>
                    You changed {allChanges.length} head(s):
                  </Text>
                  {allChanges.map((c) => (
                    <Text key={c} style={st.confTxt}>• {c}</Text>
                  ))}
                </View>
              ) : (
                <Text style={[st.confTxt, { color: "#16a34a", fontWeight: "700" }]}>
                  All heads are on the DEFAULT mapping (see Head Mapping chart above).
                </Text>
              )}
              <Text style={st.confTxt}>
                If any head would settle in the wrong place, press Cancel and change it in the
                Head Mapping chart first.
              </Text>
              <Pressable style={[st.actBtn, { backgroundColor: colors.brandPrimary }]} onPress={() => setConfirmStep(2)}>
                <Ionicons name="checkmark" size={16} color="#fff" />
                <Text style={st.actTxt}>Mapping is correct — Continue (1/2)</Text>
              </Pressable>
              <Pressable style={st.cancelBtn} onPress={() => setConfirmStep(0)}>
                <Text style={st.cancelTxt}>Cancel — let me check the mapping</Text>
              </Pressable>
            </>
          ) : (
            <>
              <Text style={st.confTitle}>🔴 Final Confirmation 2 of 2</Text>
              <Text style={st.confTxt}>
                Data will now be WRITTEN into the live portal database for {mappedCount} firm(s).
                Imported firms are locked and cannot be imported again.
              </Text>
              <Text style={[st.confTxt, { fontWeight: "800" }]}>Are you sure you want to start the import?</Text>
              <Pressable
                style={[st.actBtn, { backgroundColor: "#B45309" }]}
                onPress={() => { setConfirmStep(0); startImport(); }}
              >
                <Ionicons name="download-outline" size={16} color="#fff" />
                <Text style={st.actTxt}>YES — Start Import Now (2/2)</Text>
              </Pressable>
              <Pressable style={st.cancelBtn} onPress={() => setConfirmStep(1)}>
                <Text style={st.cancelTxt}>← Back</Text>
              </Pressable>
            </>
          )}
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  h1: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 4 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
    marginTop: spacing.md, borderWidth: 1, borderColor: colors.border,
  },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface, marginBottom: 6 },
  firmRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  firmName: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  firmMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  mapBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, maxWidth: 220,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 5,
  },
  mapBtnTxt: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },
  tickRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 7 },
  tickMain: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  tickTxt: { fontSize: 12.5, color: colors.onSurface, flex: 1 },
  actBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    borderRadius: radius.md, paddingVertical: 12, marginTop: 10,
  },
  actTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  prevRow: { paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  errTxt: { color: "#DC2626", fontSize: 12, marginTop: 8 },
  mapBox: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 10, marginTop: 4, backgroundColor: colors.surfaceSecondary,
  },
  mapHead: { fontSize: 11.5, fontWeight: "800", color: colors.brandPrimary, marginTop: 8, marginBottom: 2 },
  mapHint: { fontSize: 11, color: colors.onSurfaceTertiary, fontStyle: "italic" },
  chgBadge: {
    backgroundColor: "#FEF3C7", borderRadius: 4, paddingHorizontal: 4, paddingVertical: 1,
  },
  chgBadgeTxt: { fontSize: 8.5, fontWeight: "800", color: "#B45309" },
  resetBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, marginTop: 10,
    alignSelf: "flex-start", paddingVertical: 4,
  },
  confTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  confTxt: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 4, lineHeight: 18 },
  confBox: {
    borderWidth: 1, borderColor: "#FCD34D", backgroundColor: "#FFFBEB",
    borderRadius: radius.md, padding: 10, marginTop: 8,
  },
  cancelBtn: { alignItems: "center", paddingVertical: 12, marginTop: 4 },
  cancelTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  undoBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderWidth: 1, borderColor: "#DC2626", borderRadius: 999,
    paddingHorizontal: 9, paddingVertical: 4,
  },
  undoBtnTxt: { fontSize: 10.5, fontWeight: "800", color: "#DC2626" },
  mapRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 3 },
  mapOld: { flex: 1, fontSize: 11, color: colors.onSurfaceSecondary },
  mapNew: { flex: 1.2, fontSize: 11, fontWeight: "700", color: colors.onSurface },
  backdrop: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.45)" },
  pickSheet: {
    position: "absolute", left: 20, right: 20, top: "15%",
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
  },
  pickRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
});
