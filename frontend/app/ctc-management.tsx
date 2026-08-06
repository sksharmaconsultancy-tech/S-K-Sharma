/**
 * Iter 500 — CTC Management (Phase 1).
 * Firm salary mode (Gross / CTC / Mixed) · CTC Structure Master with 3
 * auto-seeded templates + custom builder (formula engine) · live breakup
 * preview · employee salary-mode assignment with revision history.
 * Existing Gross payroll is untouched.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator, ScrollView,
  TextInput, Modal, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import ReportTable, { ReportCol } from "@/src/components/ReportTable";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing } from "@/src/theme";

const fmt = (v: any) => Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 });

const COMP_TYPES = [
  { key: "earning", label: "Earning" },
  { key: "employer", label: "Employer Contribution" },
  { key: "deduction", label: "Employee Deduction" },
];
const CALCS = [
  { key: "percent", label: "% of base" },
  { key: "fixed", label: "Fixed ₹" },
  { key: "balance", label: "Balance" },
];
const BASES = ["gross", "basic", "ctc"];

export default function CtcManagementScreen() {
  const router = useRouter();
  const { selectedCompanyId, companies } = useSelectedCompany();
  const [cid, setCid] = useState<string | null>(selectedCompanyId);
  const [mode, setMode] = useState("gross");
  const [tab, setTab] = useState<"structures" | "employees" | "revisions" | "projection">("structures");
  const [structures, setStructures] = useState<any[]>([]);
  const [rows, setRows] = useState<any[]>([]);
  const [revs, setRevs] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  // yearly projection (appraisal report)
  const curFy = new Date().getMonth() + 1 >= 4 ? new Date().getFullYear() : new Date().getFullYear() - 1;
  const [fy, setFy] = useState(curFy);
  const [proj, setProj] = useState<any>(null);
  const [projLoading, setProjLoading] = useState(false);
  // builder
  const [bOpen, setBOpen] = useState(false);
  const [bForm, setBForm] = useState<any>(null);
  const [preview, setPreview] = useState<any>(null);
  const [prevCtc, setPrevCtc] = useState("25000");
  const [saving, setSaving] = useState(false);
  // assignment
  const [aOpen, setAOpen] = useState(false);
  const [aForm, setAForm] = useState<any>(null);

  useEffect(() => { if (selectedCompanyId) setCid(selectedCompanyId); }, [selectedCompanyId]);

  const load = useCallback(async () => {
    if (!cid) return;
    setLoading(true);
    try {
      const [m, s, e, r, sm] = await Promise.all([
        api(`/admin/ctc/firm-mode/${cid}`),
        api(`/admin/ctc/structures?company_id=${cid}`),
        api(`/admin/ctc/employees?company_id=${cid}`),
        api(`/admin/ctc/revisions?company_id=${cid}`),
        api(`/admin/ctc/summary?company_id=${cid}`),
      ]);
      setMode(m.mode); setStructures(s.structures || []);
      setRows(e.rows || []); setRevs(r.revisions || []);
      setSummary(sm);
    } catch { /* role-gated */ }
    setLoading(false);
  }, [cid]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (tab !== "projection" || !cid) return;
    setProjLoading(true);
    api(`/admin/ctc/yearly-projection?company_id=${cid}&fy_start=${fy}`)
      .then((r: any) => setProj(r))
      .catch(() => setProj(null))
      .finally(() => setProjLoading(false));
  }, [tab, fy, cid]);

  const setFirmMode = async (m: string) => {
    if (!cid) return;
    try { await api(`/admin/ctc/firm-mode/${cid}`, { method: "PUT", body: { mode: m } }); setMode(m); }
    catch (e: any) { alert(e?.message || "Failed (Super/Sub Admin only)"); }
  };

  const runPreview = async (comps: any[]) => {
    try {
      const r = await api(`/admin/ctc/preview`, {
        method: "POST",
        body: { monthly_ctc: Number(prevCtc) || 0, components: comps },
      });
      setPreview(r.breakup);
    } catch (e: any) { alert(e?.message || "Preview failed"); }
  };

  const openBuilder = (s?: any) => {
    setPreview(null);
    setBForm(s ? JSON.parse(JSON.stringify(s)) : {
      company_id: cid, name: "", description: "", components: [], includes: {},
    });
    setBOpen(true);
  };

  const saveStructure = async () => {
    if (!bForm?.name?.trim()) { alert("Structure name required"); return; }
    setSaving(true);
    try {
      if (bForm.structure_id) {
        await api(`/admin/ctc/structures/${bForm.structure_id}`, { method: "PUT", body: bForm });
      } else {
        await api(`/admin/ctc/structures`, { method: "POST", body: { ...bForm, company_id: cid } });
      }
      setBOpen(false); await load();
    } catch (e: any) { alert(e?.message || "Save failed"); }
    setSaving(false);
  };

  const delStructure = async (s: any) => {
    if (Platform.OS === "web" && !window.confirm(`Delete structure "${s.name}"?`)) return;
    try { await api(`/admin/ctc/structures/${s.structure_id}`, { method: "DELETE" }); await load(); }
    catch (e: any) { alert(e?.message || "Delete failed"); }
  };

  const updComp = (i: number, patch: any) => setBForm((f: any) => {
    const cs = [...f.components]; cs[i] = { ...cs[i], ...patch };
    return { ...f, components: cs };
  });
  const moveComp = (i: number, d: number) => setBForm((f: any) => {
    const cs = [...f.components]; const j = i + d;
    if (j < 0 || j >= cs.length) return f;
    [cs[i], cs[j]] = [cs[j], cs[i]];
    cs.forEach((c: any, k: number) => (c.seq = k + 1));
    return { ...f, components: cs };
  });

  const saveAssign = async () => {
    setSaving(true);
    try {
      await api(`/admin/ctc/assign`, { method: "POST", body: aForm });
      setAOpen(false); await load();
    } catch (e: any) { alert(e?.message || "Save failed"); }
    setSaving(false);
  };

  const [letterBusy, setLetterBusy] = useState<string | null>(null);
  const downloadLetter = async (r: any) => {
    setLetterBusy(r.rev_id);
    try {
      const res = await apiBinary(`/admin/ctc/increment-letter/${r.rev_id}.pdf`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = `Increment_Letter_${(r.employee_name || "emp").replace(/ /g, "_")}_${(r.effective_date || "").slice(0, 10)}.pdf`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) { alert(e?.message || "Letter download failed"); }
    setLetterBusy(null);
  };

  const EMP_COLS: ReportCol<any>[] = [
    { key: "employee_code", label: "Code", type: "center", min: 64, sticky: true },
    { key: "name", label: "Name", min: 200, max: 300, sticky: true },
    { key: "department", label: "Department", min: 110, max: 200 },
    { key: "designation", label: "Designation", min: 110, max: 200 },
    {
      key: "salary_mode", label: "Mode", type: "center", min: 76,
      value: (r) => (r.salary_mode === "ctc" ? "CTC" : "GROSS"),
      textStyle: (r) => ({ fontWeight: "800", color: r.salary_mode === "ctc" ? "#7C2D12" : "#1E3A8A" }),
    },
    { key: "gross_salary", label: "Gross ₹", type: "num", min: 100, value: (r) => fmt(r.gross_salary) },
    { key: "monthly_ctc", label: "Monthly CTC ₹", type: "num", min: 118, value: (r) => fmt(r.monthly_ctc) },
    { key: "annual_ctc", label: "Annual CTC ₹", type: "num", min: 118, value: (r) => fmt(r.annual_ctc) },
    { key: "structure", label: "CTC Structure", min: 150, max: 240 },
    { key: "effective_date", label: "Effective", type: "date" },
    {
      key: "__act", label: "Assign", type: "center", min: 70,
      render: (r) => (
        <Pressable
          onPress={() => {
            setAForm({
              user_id: r.user_id, name: r.name,
              salary_mode: r.salary_mode || "gross",
              monthly_ctc: String(r.monthly_ctc || ""),
              structure_id: r.structure_id || structures.find((s) => s.is_default)?.structure_id || "",
              effective_date: new Date().toISOString().slice(0, 10),
              reason: "",
            });
            setAOpen(true);
          }}
          style={{ alignSelf: "center" }} testID={`ctc-assign-${r.employee_code}`}>
          <Ionicons name="create-outline" size={16} color={colors.brandPrimary} />
        </Pressable>
      ),
    },
  ];

  const REV_COLS: ReportCol<any>[] = [
    { key: "created_at", label: "When", type: "date", min: 110, value: (r) => (r.created_at || "").slice(0, 10) },
    { key: "employee_name", label: "Employee", min: 180, max: 280, sticky: true },
    { key: "old_mode", label: "Old Mode", type: "center", min: 80, value: (r) => (r.old_mode || "").toUpperCase() },
    { key: "new_mode", label: "New Mode", type: "center", min: 84, value: (r) => (r.new_mode || "").toUpperCase() },
    { key: "old_ctc", label: "Old CTC ₹", type: "num", min: 100, value: (r) => fmt(r.old_ctc) },
    { key: "new_ctc", label: "New CTC ₹", type: "num", min: 100, value: (r) => fmt(r.new_ctc) },
    {
      key: "__diff", label: "Difference ₹", type: "num", min: 104,
      value: (r) => fmt((r.new_ctc || 0) - (r.old_ctc || 0)),
      textStyle: (r) => ({ fontWeight: "800", color: (r.new_ctc || 0) >= (r.old_ctc || 0) ? "#15803D" : "#B91C1C" }),
    },
    { key: "new_structure", label: "Structure", min: 140, max: 240 },
    { key: "effective_date", label: "Effective", type: "date" },
    { key: "reason", label: "Reason", min: 140, max: 260 },
    { key: "approved_by", label: "Approved By", min: 120, max: 200 },
    {
      key: "__letter", label: "Letter", type: "center", min: 64,
      render: (r) => (
        <Pressable onPress={() => downloadLetter(r)} disabled={letterBusy === r.rev_id}
          style={{ alignSelf: "center" }} testID={`ctc-letter-${r.rev_id}`}>
          {letterBusy === r.rev_id
            ? <ActivityIndicator size="small" color={colors.brandPrimary} />
            : <Ionicons name="document-text-outline" size={16} color={colors.brandPrimary} />}
        </Pressable>
      ),
    },
  ];

  const PROJ_COLS: ReportCol<any>[] = [
    { key: "employee_code", label: "Code", type: "center", min: 64, sticky: true },
    { key: "name", label: "Name", min: 190, max: 290, sticky: true },
    { key: "department", label: "Department", min: 100, max: 180 },
    {
      key: "salary_mode", label: "Mode", type: "center", min: 70,
      value: (r) => (r.salary_mode === "ctc" ? "CTC" : "GROSS"),
      textStyle: (r) => ({ fontWeight: "800", color: r.salary_mode === "ctc" ? "#7C2D12" : "#1E3A8A" }),
    },
    { key: "monthly_cost", label: "Monthly ₹", type: "num", min: 96, value: (r) => fmt(r.monthly_cost) },
    { key: "projected_annual", label: "Annual Projection ₹", type: "num", min: 130, value: (r) => fmt(r.projected_annual) },
    { key: "months_paid", label: "Months Paid", type: "center", min: 88 },
    { key: "gross_paid_ytd", label: "Gross Paid YTD ₹", type: "num", min: 122, value: (r) => fmt(r.gross_paid_ytd) },
    { key: "employer_ytd", label: "Employer Cost YTD ₹", type: "num", min: 138, value: (r) => fmt(r.employer_ytd) },
    { key: "total_cost_ytd", label: "Total Cost YTD ₹", type: "num", min: 122, value: (r) => fmt(r.total_cost_ytd) },
    { key: "projected_ytd", label: "Projected YTD ₹", type: "num", min: 118, value: (r) => fmt(r.projected_ytd) },
    {
      key: "variance_ytd", label: "Variance ₹", type: "num", min: 100,
      value: (r) => fmt(r.variance_ytd),
      textStyle: (r) => ({ fontWeight: "800", color: (r.variance_ytd || 0) >= 0 ? "#15803D" : "#B91C1C" }),
    },
    {
      key: "utilization_pct", label: "% of Annual Used", type: "num", min: 118,
      value: (r) => `${fmt(r.utilization_pct)}%`,
    },
  ];

  return (
    <SafeAreaView style={st.root} edges={["top"]}>
      <View style={st.head}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="arrow-back" size={20} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.title}>CTC Management</Text>
          <Text style={st.sub}>Structures · templates · employee salary mode · revision history</Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ flexDirection: "row", gap: 6, paddingBottom: 8 }}>
          {companies.map((c: any) => (
            <Pressable key={c.company_id} onPress={() => setCid(c.company_id)}
              style={[st.chip, cid === c.company_id && st.chipOn]}>
              <Text style={[st.chipTxt, cid === c.company_id && st.chipTxtOn]} numberOfLines={1}>{c.name}</Text>
            </Pressable>
          ))}
        </ScrollView>

        {/* Phase 3 — CTC dashboard summary */}
        {summary ? (
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
            {[
              ["CTC Employees", `${summary.ctc_employees} / ${summary.total_employees}`, "#7C2D12"],
              ["Total Monthly CTC", `\u20B9${fmt(summary.total_monthly_ctc)}`, "#1E3A8A"],
              ["Annual CTC", `\u20B9${fmt(summary.total_annual_ctc)}`, "#1E3A8A"],
              ["Employer Cost / Month", `\u20B9${fmt(summary.total_employer_cost)}`, "#C2410C"],
              ["Net Payout / Month", `\u20B9${fmt(summary.total_net_payout)}`, "#15803D"],
              ["Avg Monthly CTC", `\u20B9${fmt(summary.avg_monthly_ctc)}`, "#0F766E"],
            ].map(([l, v, c]) => (
              <View key={l as string} style={st.sumCard}>
                <Text style={[st.sumVal, { color: c as string }]} numberOfLines={1}>{v}</Text>
                <Text style={st.sumLbl} numberOfLines={1}>{l}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {/* firm mode */}
        <View style={st.card}>
          <Text style={st.cardTitle}>Company Salary Mode</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
            {[["gross", "Gross Salary Only"], ["ctc", "CTC Salary Only"], ["mixed", "Gross + CTC (Mixed)"]].map(([k, l]) => (
              <Pressable key={k} onPress={() => setFirmMode(k)}
                style={[st.chip, mode === k && st.chipSrcOn]} testID={`ctc-mode-${k}`}>
                <Text style={[st.chipTxt, mode === k && { color: "#7C2D12", fontWeight: "800" }]}>{l}</Text>
              </Pressable>
            ))}
          </View>
        </View>

        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
          {[["structures", `CTC Structures (${structures.length})`], ["employees", `Employee Register (${rows.length})`], ["revisions", `Revision History (${revs.length})`], ["projection", "Yearly Projection"]].map(([k, l]) => (
            <Pressable key={k} onPress={() => setTab(k as any)} style={[st.chip, tab === k && st.chipOn]}>
              <Text style={[st.chipTxt, tab === k && st.chipTxtOn]}>{l}</Text>
            </Pressable>
          ))}
        </View>

        {loading ? <ActivityIndicator style={{ marginTop: 30 }} color={colors.brandPrimary} /> : tab === "structures" ? (
          <>
            <Pressable onPress={() => openBuilder()} style={st.newBtn} testID="ctc-new-structure">
              <Ionicons name="add" size={15} color="#fff" />
              <Text style={{ color: "#fff", fontWeight: "800", fontSize: 12.5 }}>New CTC Structure</Text>
            </Pressable>
            {structures.map((s) => (
              <View key={s.structure_id} style={st.card}>
                <View style={{ flexDirection: "row", alignItems: "center" }}>
                  <View style={{ flex: 1 }}>
                    <Text style={st.cardTitle}>
                      {s.name} {s.is_default ? "⭐" : ""} {s.is_template ? "· System Template" : ""}
                    </Text>
                    <Text style={st.dim2}>{s.description || "—"}</Text>
                    <Text style={st.dim2}>
                      {(s.components || []).filter((c: any) => !c.hidden).length} components · effective {s.effective_from} · {s.status}
                    </Text>
                  </View>
                  <Pressable onPress={() => openBuilder(s)} hitSlop={8} style={{ padding: 6 }} testID={`ctc-edit-${s.structure_id}`}>
                    <Ionicons name="create-outline" size={17} color={colors.brandPrimary} />
                  </Pressable>
                  <Pressable onPress={() => delStructure(s)} hitSlop={8} style={{ padding: 6 }}>
                    <Ionicons name="trash-outline" size={16} color="#B91C1C" />
                  </Pressable>
                </View>
              </View>
            ))}
          </>
        ) : tab === "employees" ? (
          <View style={{ minHeight: 300, maxHeight: 640 }}>
            <ReportTable reportKey="ctc_register" columns={EMP_COLS} rows={rows}
              maxHeight={600} emptyText="No employees."
              pdfTitle="Employee CTC Register" pdfSubtitle={companies.find((c: any) => c.company_id === cid)?.name || ""} />
          </View>
        ) : tab === "projection" ? (
          <View>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 8, alignItems: "center" }}>
              <Text style={[st.chipTxt, { marginRight: 2 }]}>Financial Year:</Text>
              {[curFy - 2, curFy - 1, curFy].map((y) => (
                <Pressable key={y} onPress={() => setFy(y)}
                  style={[st.chip, fy === y && st.chipOn]} testID={`ctc-fy-${y}`}>
                  <Text style={[st.chipTxt, fy === y && st.chipTxtOn]}>{`FY ${y}-${String(y + 1).slice(2)}`}</Text>
                </Pressable>
              ))}
            </View>
            <Text style={[st.dim2, { marginBottom: 8 }]}>
              Projected annual cost (CTC / Gross × 12) vs actual paid + employer statutory cost, from the Compliance Salary runs of Apr {fy} – Mar {fy + 1}. CTC-mode variance compares against Total Cost; Gross-mode against Gross Paid.
            </Text>
            {projLoading ? <ActivityIndicator style={{ marginTop: 30 }} color={colors.brandPrimary} /> : (
              <View style={{ minHeight: 300, maxHeight: 640 }}>
                <ReportTable reportKey="ctc_yearly_projection" columns={PROJ_COLS} rows={proj?.rows || []}
                  maxHeight={600} emptyText="No employees / processed months in this financial year."
                  footer={proj?.totals ? {
                    label: "TOTAL",
                    values: {
                      monthly_cost: fmt(proj.totals.monthly_cost),
                      projected_annual: fmt(proj.totals.projected_annual),
                      gross_paid_ytd: fmt(proj.totals.gross_paid_ytd),
                      employer_ytd: fmt(proj.totals.employer_ytd),
                      total_cost_ytd: fmt(proj.totals.total_cost_ytd),
                      projected_ytd: fmt(proj.totals.projected_ytd),
                      variance_ytd: fmt(proj.totals.variance_ytd),
                    },
                  } : undefined}
                  pdfTitle={`Yearly CTC Projection — FY ${fy}-${String(fy + 1).slice(2)}`}
                  pdfSubtitle={companies.find((c: any) => c.company_id === cid)?.name || ""} />
              </View>
            )}
          </View>
        ) : (
          <View style={{ minHeight: 300, maxHeight: 640 }}>
            <ReportTable reportKey="ctc_revisions" columns={REV_COLS} rows={revs}
              maxHeight={600} emptyText="No salary revisions recorded yet."
              pdfTitle="CTC Revision History" pdfSubtitle={companies.find((c: any) => c.company_id === cid)?.name || ""} />
          </View>
        )}
      </ScrollView>

      {/* structure builder */}
      <Modal visible={bOpen} transparent animationType="fade" onRequestClose={() => setBOpen(false)}>
        <View style={st.mWrap}>
          <View style={[st.mCard, { maxWidth: 760, width: Platform.OS === "web" ? 740 : "100%" }]}>
            <Text style={st.mTitle}>{bForm?.structure_id ? "Edit" : "New"} CTC Structure</Text>
            <ScrollView style={{ maxHeight: 470 }}>
              <TextInput style={st.mInput} placeholder="Structure name" placeholderTextColor={colors.onSurfaceTertiary}
                value={bForm?.name || ""} onChangeText={(v) => setBForm((f: any) => ({ ...f, name: v }))} testID="ctc-b-name" />
              <TextInput style={[st.mInput, { marginTop: 6 }]} placeholder="Description" placeholderTextColor={colors.onSurfaceTertiary}
                value={bForm?.description || ""} onChangeText={(v) => setBForm((f: any) => ({ ...f, description: v }))} />
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 10 }}>
                <Text style={st.cardTitle}>Components</Text>
                <Pressable onPress={() => setBForm((f: any) => ({
                  ...f,
                  components: [...(f.components || []), {
                    key: `c${(f.components || []).length + 1}_${Date.now() % 1000}`,
                    label: "New Component", type: "earning", calc: "percent",
                    value: 0, base: "gross", seq: (f.components || []).length + 1,
                  }],
                }))} style={st.smallBtn} testID="ctc-add-comp">
                  <Text style={st.smallBtnTxt}>+ Add Component</Text>
                </Pressable>
              </View>
              {(bForm?.components || []).map((c: any, i: number) => (
                <View key={i} style={[st.compRow, c.hidden && { opacity: 0.45 }]}>
                  <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
                    <TextInput style={[st.mInput, { flex: 1.4 }]} value={c.label}
                      onChangeText={(v) => updComp(i, { label: v })} />
                    <TextInput style={[st.mInput, { width: 74, textAlign: "right" }]} keyboardType="decimal-pad"
                      value={String(c.value ?? "")} onChangeText={(v) => updComp(i, { value: Number(v) || 0 })} />
                  </View>
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 4, alignItems: "center" }}>
                    {COMP_TYPES.map((t) => (
                      <Pressable key={t.key} onPress={() => updComp(i, { type: t.key })}
                        style={[st.tinyChip, c.type === t.key && st.chipOn]}>
                        <Text style={[st.tinyTxt, c.type === t.key && st.chipTxtOn]}>{t.label}</Text>
                      </Pressable>
                    ))}
                    <Text style={st.tinyTxt}>|</Text>
                    {CALCS.map((t) => (
                      <Pressable key={t.key} onPress={() => updComp(i, { calc: t.key })}
                        style={[st.tinyChip, c.calc === t.key && st.chipOn]}>
                        <Text style={[st.tinyTxt, c.calc === t.key && st.chipTxtOn]}>{t.label}</Text>
                      </Pressable>
                    ))}
                    {c.calc === "percent" ? BASES.map((b) => (
                      <Pressable key={b} onPress={() => updComp(i, { base: b })}
                        style={[st.tinyChip, c.base === b && st.chipSrcOn]}>
                        <Text style={st.tinyTxt}>of {b}</Text>
                      </Pressable>
                    )) : null}
                    <View style={{ flex: 1 }} />
                    <Pressable onPress={() => moveComp(i, -1)} hitSlop={6}><Ionicons name="arrow-up" size={14} color={colors.onSurfaceSecondary} /></Pressable>
                    <Pressable onPress={() => moveComp(i, 1)} hitSlop={6}><Ionicons name="arrow-down" size={14} color={colors.onSurfaceSecondary} /></Pressable>
                    <Pressable onPress={() => updComp(i, { hidden: !c.hidden })} hitSlop={6}>
                      <Ionicons name={c.hidden ? "eye-off-outline" : "eye-outline"} size={14} color={colors.onSurfaceSecondary} />
                    </Pressable>
                    <Pressable onPress={() => setBForm((f: any) => ({ ...f, components: f.components.filter((_: any, k: number) => k !== i) }))} hitSlop={6}>
                      <Ionicons name="trash-outline" size={14} color="#B91C1C" />
                    </Pressable>
                  </View>
                </View>
              ))}
              {/* preview */}
              <View style={{ flexDirection: "row", gap: 8, alignItems: "center", marginTop: 10 }}>
                <TextInput style={[st.mInput, { width: 120 }]} keyboardType="number-pad" value={prevCtc}
                  onChangeText={setPrevCtc} placeholder="Monthly CTC" placeholderTextColor={colors.onSurfaceTertiary} testID="ctc-prev-amt" />
                <Pressable onPress={() => runPreview(bForm?.components || [])} style={st.smallBtn} testID="ctc-prev-btn">
                  <Text style={st.smallBtnTxt}>Preview Breakup</Text>
                </Pressable>
              </View>
              {preview ? (
                <View style={[st.card, { marginTop: 8 }]}>
                  {preview.earnings.map((e: any) => (
                    <View key={e.key} style={st.pRow}><Text style={st.pL}>{e.label}</Text><Text style={st.pV}>{fmt(e.amount)}</Text></View>
                  ))}
                  <View style={st.pRow}><Text style={[st.pL, { fontWeight: "800" }]}>Gross Earnings</Text><Text style={[st.pV, { fontWeight: "800" }]}>{fmt(preview.gross)}</Text></View>
                  {preview.employer_contributions.map((e: any) => (
                    <View key={e.key} style={st.pRow}><Text style={[st.pL, { color: "#C2410C" }]}>{e.label}</Text><Text style={[st.pV, { color: "#C2410C" }]}>{fmt(e.amount)}</Text></View>
                  ))}
                  <View style={st.pRow}><Text style={[st.pL, { fontWeight: "800", color: "#C2410C" }]}>Employer Cost</Text><Text style={[st.pV, { fontWeight: "800", color: "#C2410C" }]}>{fmt(preview.employer_total)}</Text></View>
                  {preview.deductions.map((e: any) => (
                    <View key={e.key} style={st.pRow}><Text style={[st.pL, { color: "#B91C1C" }]}>{e.label}</Text><Text style={[st.pV, { color: "#B91C1C" }]}>−{fmt(e.amount)}</Text></View>
                  ))}
                  <View style={st.pRow}><Text style={[st.pL, { fontWeight: "900" }]}>Net Salary</Text><Text style={[st.pV, { fontWeight: "900", color: "#15803D" }]}>{fmt(preview.net_salary)}</Text></View>
                  <View style={st.pRow}><Text style={st.pL}>Verify (Gross + Employer = CTC)</Text><Text style={st.pV}>{fmt(preview.verify_ctc)}</Text></View>
                </View>
              ) : null}
            </ScrollView>
            <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 10, marginTop: 12 }}>
              <Pressable onPress={() => setBOpen(false)} style={st.mCancel} disabled={saving}>
                <Text style={{ fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary }}>Cancel</Text>
              </Pressable>
              <Pressable onPress={saveStructure} style={st.mSave} disabled={saving} testID="ctc-b-save">
                {saving ? <ActivityIndicator size="small" color="#fff" /> : <Text style={{ fontSize: 12.5, fontWeight: "800", color: "#fff" }}>Save Structure</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* assignment */}
      <Modal visible={aOpen} transparent animationType="fade" onRequestClose={() => setAOpen(false)}>
        <View style={st.mWrap}>
          <View style={st.mCard}>
            <Text style={st.mTitle}>Salary Mode — {aForm?.name}</Text>
            <View style={{ flexDirection: "row", gap: 6, marginBottom: 10 }}>
              {[["gross", "Gross Salary"], ["ctc", "CTC Salary"]].map(([k, l]) => (
                <Pressable key={k} onPress={() => setAForm((f: any) => ({ ...f, salary_mode: k }))}
                  style={[st.chip, aForm?.salary_mode === k && st.chipOn]} testID={`ctc-a-mode-${k}`}>
                  <Text style={[st.chipTxt, aForm?.salary_mode === k && st.chipTxtOn]}>{l}</Text>
                </Pressable>
              ))}
            </View>
            {aForm?.salary_mode === "ctc" ? (
              <>
                <Text style={st.mLbl}>Monthly CTC (₹) — Annual: {fmt((Number(aForm?.monthly_ctc) || 0) * 12)}</Text>
                <TextInput style={st.mInput} keyboardType="number-pad" value={aForm?.monthly_ctc || ""}
                  onChangeText={(v) => setAForm((f: any) => ({ ...f, monthly_ctc: v.replace(/[^\d.]/g, "") }))} testID="ctc-a-amount" />
                <Text style={[st.mLbl, { marginTop: 8 }]}>CTC Structure</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 5 }}>
                  {structures.map((s) => (
                    <Pressable key={s.structure_id} onPress={() => setAForm((f: any) => ({ ...f, structure_id: s.structure_id }))}
                      style={[st.tinyChip, aForm?.structure_id === s.structure_id && st.chipOn]}>
                      <Text style={[st.tinyTxt, aForm?.structure_id === s.structure_id && st.chipTxtOn]}>{s.name}</Text>
                    </Pressable>
                  ))}
                </View>
                <Text style={[st.mLbl, { marginTop: 8 }]}>Effective Date (YYYY-MM-DD)</Text>
                <TextInput style={st.mInput} value={aForm?.effective_date || ""}
                  onChangeText={(v) => setAForm((f: any) => ({ ...f, effective_date: v }))} />
              </>
            ) : null}
            <Text style={[st.mLbl, { marginTop: 8 }]}>Reason (revision history)</Text>
            <TextInput style={st.mInput} value={aForm?.reason || ""}
              onChangeText={(v) => setAForm((f: any) => ({ ...f, reason: v }))} testID="ctc-a-reason" />
            <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 10, marginTop: 12 }}>
              <Pressable onPress={() => setAOpen(false)} style={st.mCancel} disabled={saving}>
                <Text style={{ fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary }}>Cancel</Text>
              </Pressable>
              <Pressable onPress={saveAssign} style={st.mSave} disabled={saving} testID="ctc-a-save">
                {saving ? <ActivityIndicator size="small" color="#fff" /> : <Text style={{ fontSize: 12.5, fontWeight: "800", color: "#fff" }}>Save</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  head: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: spacing.md, paddingVertical: 10, backgroundColor: colors.surface },
  title: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 1 },
  chip: { borderWidth: 1, borderColor: colors.divider, borderRadius: 999, paddingHorizontal: 11, paddingVertical: 6, backgroundColor: colors.surface, maxWidth: 230 },
  chipOn: { borderColor: colors.brandPrimary, backgroundColor: `${colors.brandPrimary}14` },
  chipSrcOn: { borderColor: "#C2410C", backgroundColor: "#FFF7ED" },
  chipTxt: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: colors.brandPrimary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.divider, padding: 12, marginBottom: 10 },
  sumCard: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.divider, paddingHorizontal: 12, paddingVertical: 8, minWidth: 128, flexGrow: 1 },
  sumVal: { fontSize: 15, fontWeight: "900" },
  sumLbl: { fontSize: 10, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 2 },
  cardTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  dim2: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  newBtn: { flexDirection: "row", alignItems: "center", gap: 5, alignSelf: "flex-start", backgroundColor: colors.brandPrimary, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8, marginBottom: 10 },
  smallBtn: { borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  smallBtnTxt: { fontSize: 11, fontWeight: "800", color: colors.brandPrimary },
  compRow: { borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md, padding: 8, marginTop: 6 },
  tinyChip: { borderWidth: 1, borderColor: colors.divider, borderRadius: 999, paddingHorizontal: 7, paddingVertical: 3 },
  tinyTxt: { fontSize: 10, fontWeight: "700", color: colors.onSurfaceSecondary },
  pRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 3, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider },
  pL: { fontSize: 11.5, color: colors.onSurface },
  pV: { fontSize: 11.5, color: colors.onSurface },
  mWrap: { flex: 1, backgroundColor: "rgba(15,23,42,0.5)", alignItems: "center", justifyContent: "center", padding: 16 },
  mCard: { width: Platform.OS === "web" ? 480 : "100%", maxWidth: 520, backgroundColor: colors.surface, borderRadius: radius.lg, padding: 16 },
  mTitle: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  mLbl: { fontSize: 10.5, fontWeight: "800", color: colors.onSurfaceSecondary, marginBottom: 3 },
  mInput: { borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 7, fontSize: 12.5, color: colors.onSurface, backgroundColor: colors.background },
  mCancel: { paddingHorizontal: 14, paddingVertical: 9 },
  mSave: { backgroundColor: colors.brandPrimary, borderRadius: radius.md, paddingHorizontal: 18, paddingVertical: 9 },
});
