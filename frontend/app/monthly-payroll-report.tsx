/**
 * Iter 529 (user request) — MONTHLY PAYROLL ATTENDANCE & SALARY REPORT.
 * One wide landscape report: Employee Details → Attendance 1–31 →
 * Summary → Compliance/Actual Gross → Final Salary → Deductions →
 * Net Payable → Bank Details. Frozen identity columns + sticky header,
 * footer totals, Excel / PDF / Print. Reporting layer only — all values
 * come from the existing attendance + payroll engines.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, Modal, Platform, Pressable, ScrollView, StyleSheet,
  Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Stack, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { GridScroller, stickyCol, stickyHeader } from "@/src/components/GridFreeze";
import { colors } from "@/src/theme";

const CODE_UI: Record<string, { bg: string; fg: string }> = {
  "-": { bg: "#FEE2E2", fg: "#991B1B" },
  WO: { bg: "#E0F2FE", fg: "#075985" },
  HO: { bg: "#FED7AA", fg: "#9A3412" },
  CL: { bg: "#EDE9FE", fg: "#5B21B6" },
  PL: { bg: "#EDE9FE", fg: "#5B21B6" },
  EL: { bg: "#EDE9FE", fg: "#5B21B6" },
  SL: { bg: "#FCE7F3", fg: "#9D174D" },
  ESIC: { bg: "#FCE7F3", fg: "#9D174D" },
};
// hour cells ("8", "12.5", "8+4") get the "present" green tint
const HRS_UI = { bg: "#DCFCE7", fg: "#166534" };

// column widths (px) — identity block is FROZEN while day columns scroll
const W: Record<string, number> = {
  sr: 36, employee_code: 52, name: 150, father_name: 110, designation: 100,
  department: 90, doj: 74, uan: 92, esic_ip: 82,
  present: 56, leave: 46, wo: 42, holiday: 54, absent: 52,
  payable_days: 62, ot_hours: 52,
  comp_gross: 96, act_gross: 90, final_salary: 110,
  pf: 62, esic: 62, pt: 50, lwf: 48, tds: 56, advance: 62, other_ded: 66,
  total_ded: 72, net: 90,
  acct_name: 120, acct_no: 104, ifsc: 88, bank_name: 100, bank_branch: 90,
  payment_mode: 52,
};
const DAY_W = 40;
const FROZEN = ["sr", "employee_code", "name"]; // stay pinned on the left

function colW(key: string): number {
  return /^d\d+$/.test(key) ? DAY_W : W[key] || 60;
}

function fmt(v: any): string {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "number")
    return v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return String(v);
}

type Opt = string;
function Pick({ label, value, options, onChange }: {
  label: string; value: string; options: Opt[]; onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <View>
      <Pressable style={s.pickBtn} onPress={() => setOpen(true)}
        testID={`mpr-pick-${label}`}>
        <Text style={[s.pickTxt, !value && { color: "#94A3B8" }]} numberOfLines={1}>
          {value || label}
        </Text>
        <Ionicons name="chevron-down" size={12} color="#64748B" />
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={s.mBack} onPress={() => setOpen(false)}>
          <View style={s.mCard}>
            <Text style={s.mTitle}>{label}</Text>
            <ScrollView style={{ maxHeight: 380 }}>
              <Pressable style={s.mRow} onPress={() => { onChange(""); setOpen(false); }}>
                <Text style={[s.mRowTxt, !value && s.mRowSel]}>All</Text>
              </Pressable>
              {options.map((o) => (
                <Pressable key={o} style={s.mRow}
                  onPress={() => { onChange(o); setOpen(false); }}>
                  <Text style={[s.mRowTxt, value === o && s.mRowSel]} numberOfLines={1}>{o}</Text>
                </Pressable>
              ))}
            </ScrollView>
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}

export default function MonthlyPayrollReport() {
  const { user } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const params = useLocalSearchParams<{ month?: string }>();
  const [cid, setCid] = useState("");
  // Iter 535 (user request) — default month = LAST salary-finalized
  // month (resolved by the backend), never the current month.
  const [month, setMonth] = useState(
    typeof params.month === "string" && /^\d{4}-\d{2}$/.test(params.month)
      ? params.month
      : "",
  );
  const [branch, setBranch] = useState("");
  const [dept, setDept] = useState("");
  const [desig, setDesig] = useState("");
  const [etype, setEtype] = useState("");
  const [ctr, setCtr] = useState("");
  const [salaryType, setSalaryType] = useState<"compliance" | "actual" | "both">("both");
  const [basis, setBasis] = useState<"compliance" | "actual">("compliance");
  const [q, setQ] = useState("");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [exporting, setExporting] = useState("");
  const loadSeq = React.useRef(0);

  useEffect(() => {
    if (user?.role === "company_admin") setCid(user.company_id || "");
    else if (selectedCompanyId && selectedCompanyId !== "all") setCid(selectedCompanyId);
  }, [user, selectedCompanyId]);

  const qs = useMemo(() => {
    const p = new URLSearchParams({ salary_type: salaryType, basis });
    if (month) p.set("month", month);
    if (cid) p.set("company_id", cid);
    if (branch) p.set("branch", branch);
    if (dept) p.set("department", dept);
    if (desig) p.set("designation", desig);
    if (etype) p.set("employee_type", etype);
    if (ctr) p.set("contractor", ctr);
    if (q.trim()) p.set("search", q.trim());
    return p.toString();
  }, [cid, month, branch, dept, desig, etype, ctr, salaryType, basis, q]);

  const load = useCallback(async (query: string) => {
    setLoading(true);
    setErr("");
    const seq = ++loadSeq.current;
    try {
      const d = await api<any>(`/admin/reports/monthly-payroll?${query}`);
      if (seq === loadSeq.current) setData(d); // ignore stale responses
    } catch (e: any) {
      if (seq === loadSeq.current) setErr(e?.message || "Failed to load");
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, []);
  // Iter 534 (perf fix) — DEBOUNCE: typing in search/month fired one heavy
  // report computation per keystroke, hanging the server & the grid.
  useEffect(() => {
    if (!cid) return;
    if (month && !/^\d{4}-\d{2}$/.test(month)) return; // typing in progress
    const t = setTimeout(() => { void load(qs); }, 600);
    return () => clearTimeout(t);
  }, [cid, month, qs, load]);
  // adopt the backend-resolved default month into the input
  useEffect(() => {
    if (!month && data?.month) setMonth(data.month);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  // ‹ › stepper — jump between months that HAVE a salary run
  const stepMonth = (dir: -1 | 1) => {
    const list: string[] = data?.run_months || [];
    const cur = month || data?.month || "";
    if (list.length) {
      const c = dir === -1 ? list.filter((x) => x < cur) : list.filter((x) => x > cur);
      const next = dir === -1 ? c[c.length - 1] : c[0];
      if (next) setMonth(next);
      return;
    }
    if (/^\d{4}-\d{2}$/.test(cur)) { // no runs yet → plain calendar step
      const [y, m] = cur.split("-").map(Number);
      const d = new Date(y, m - 1 + dir, 1);
      setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
    }
  };

  const doExport = async (kind: "xlsx" | "pdf") => {
    if (!cid) return;
    setExporting(kind);
    try {
      const r = await apiBinary(`/admin/reports/monthly-payroll.${kind}?${qs}`);
      if (Platform.OS === "web" && r.webBlobUrl) {
        if (kind === "pdf") window.open(r.webBlobUrl, "_blank");
        else {
          const a = document.createElement("a");
          a.href = r.webBlobUrl;
          a.download = `monthly-payroll-${month}.${kind}`;
          a.click();
        }
      }
    } catch (e: any) {
      setErr(e?.message || "Export failed");
    } finally {
      setExporting("");
    }
  };

  const cols: { key: string; label: string }[] = data?.columns || [];
  const rows: any[] = data?.rows || [];
  const meta = data?.meta || {};

  // frozen offsets for the pinned identity columns
  const offsets = useMemo(() => {
    const out: Record<string, number> = {};
    let x = 0;
    for (const k of FROZEN) { out[k] = x; x += colW(k); }
    return out;
  }, []);

  const cell = (c: { key: string }, r: any, ri: number) => {
    const k = c.key;
    const v = r[k];
    const day = /^d\d+$/.test(k);
    const hrs = day && typeof v === "string" && /^\d/.test(v);
    const ui = day ? (hrs ? HRS_UI : CODE_UI[v]) : undefined;
    const frozen = FROZEN.includes(k);
    const noteCell = k === "final_salary" && r.status_note;
    return (
      <View key={k}
        style={[s.td, { width: colW(k) },
          day && ui && { backgroundColor: ui.bg },
          frozen && stickyCol(offsets[k], ri % 2 ? "#F8FAFC" : "#fff"),
          noteCell && { backgroundColor: "#FEF3C7" }]}>
        <Text numberOfLines={2}
          style={[s.tdTxt,
            day && { fontSize: 8, fontWeight: "700" },
            day && ui && { color: ui.fg },
            k === "net" && { fontWeight: "800", color: "#166534" },
            noteCell && { color: "#92400E", fontWeight: "700", fontSize: 8.5 }]}>
          {noteCell ? r.status_note : fmt(v)}
        </Text>
      </View>
    );
  };

  // Iter 534 (perf fix) — the grid (~130 rows × 60 cols ≈ 8,000 cells) was
  // re-rendered on EVERY keystroke in the filter inputs, freezing the page.
  // Memoise it so it only re-renders when the report data changes.
  const grid = useMemo(() => {
    if (!rows.length) return null;
    return (
      <GridScroller maxHeight={620}>
        <View>
          <View style={[s.tr, stickyHeader("#0F3B5C")]}>
            {cols.map((c) => (
              <View key={c.key}
                style={[s.td, s.th, { width: colW(c.key) },
                  FROZEN.includes(c.key) && stickyCol(offsets[c.key], "#0F3B5C"),
                  FROZEN.includes(c.key) && { zIndex: 11 }]}>
                <Text style={s.thTxt} numberOfLines={2}>{c.label}</Text>
              </View>
            ))}
          </View>
          {rows.map((r, ri) => (
            <View key={r.employee_code || ri}
              style={[s.tr, ri % 2 ? { backgroundColor: "#F8FAFC" } : null]}>
              {cols.map((c) => cell(c, r, ri))}
            </View>
          ))}
          {/* footer totals */}
          <View style={[s.tr, { backgroundColor: "#FFF7E0" }]}>
            {cols.map((c) => (
              <View key={c.key}
                style={[s.td, { width: colW(c.key) },
                  FROZEN.includes(c.key) && stickyCol(offsets[c.key], "#FFF7E0")]}>
                <Text style={[s.tdTxt, { fontWeight: "800" }]}>
                  {c.key === "name" ? "TOTAL" : fmt(data.totals?.[c.key])}
                </Text>
              </View>
            ))}
          </View>
        </View>
      </GridScroller>
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, offsets]);

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <Stack.Screen options={{ title: "Monthly Payroll Report" }} />
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 12 }}>
        <Text style={s.title}>Monthly Payroll Attendance &amp; Salary Report</Text>
        <Text style={s.sub}>
          Employee → Attendance 1–31 → Payable Days → Salary → Deductions → Net
          Payable → Bank. Uses the finalized attendance &amp; payroll engines.
        </Text>

        {user?.role !== "company_admin" ? (
          <View style={{ marginTop: 8 }}>
            <CompanyPicker value={cid || "all"}
              onChange={(v) => setCid(v === "all" ? "" : v)}
              allowAll={false} label="Firm" testID="mpr-firm-dd" />
          </View>
        ) : null}

        <View style={s.filterRow}>
          <Pressable style={s.stepBtn} onPress={() => stepMonth(-1)}
            testID="mpr-month-prev">
            <Ionicons name="chevron-back" size={16} color="#0F3B5C" />
          </Pressable>
          <TextInput value={month} onChangeText={setMonth} placeholder="YYYY-MM"
            placeholderTextColor="#94A3B8" style={[s.input, { maxWidth: 100 }]}
            testID="mpr-month" />
          <Pressable style={s.stepBtn} onPress={() => stepMonth(1)}
            testID="mpr-month-next">
            <Ionicons name="chevron-forward" size={16} color="#0F3B5C" />
          </Pressable>
          <Pick label="Branch / Unit" value={branch} options={meta.branches || []} onChange={setBranch} />
          <Pick label="Department" value={dept} options={meta.departments || []} onChange={setDept} />
          <Pick label="Designation" value={desig} options={meta.designations || []} onChange={setDesig} />
          <Pick label="Employee Type" value={etype} options={meta.employee_types || []} onChange={setEtype} />
          <Pick label="Contractor" value={ctr} options={meta.contractors || []} onChange={setCtr} />
          <TextInput value={q} onChangeText={setQ} placeholder="Search name / code…"
            placeholderTextColor="#94A3B8" style={[s.input, { flex: 1, minWidth: 140 }]}
            testID="mpr-search" />
        </View>

        <View style={s.filterRow}>
          <Text style={s.selLbl}>Salary Type:</Text>
          {(["compliance", "actual", "both"] as const).map((k) => (
            <Pressable key={k} onPress={() => setSalaryType(k)}
              style={[s.chip, salaryType === k && s.chipOn]} testID={`mpr-stype-${k}`}>
              <Text style={[s.chipTxt, salaryType === k && { color: "#fff" }]}>
                {k === "both" ? "Both" : k === "compliance" ? "Compliance" : "Actual"}
              </Text>
            </Pressable>
          ))}
          <Text style={s.selLbl}>Salary Basis:</Text>
          {(["compliance", "actual"] as const).map((k) => (
            <Pressable key={k} onPress={() => setBasis(k)}
              style={[s.chip, basis === k && s.chipOn]} testID={`mpr-basis-${k}`}>
              <Text style={[s.chipTxt, basis === k && { color: "#fff" }]}>
                {k === "compliance" ? "Compliance" : "Actual"}
              </Text>
            </Pressable>
          ))}
          <View style={{ flex: 1 }} />
          {(["xlsx", "pdf"] as const).map((k) => (
            <Pressable key={k} onPress={() => doExport(k)} style={s.expBtn}
              testID={`mpr-export-${k}`}>
              {exporting === k ? <ActivityIndicator size="small" color="#fff" /> : (
                <Text style={s.expTxt}>{k === "xlsx" ? "Excel" : "PDF"}</Text>
              )}
            </Pressable>
          ))}
          <Pressable onPress={() => doExport("pdf")} style={[s.expBtn, { backgroundColor: "#475569" }]}
            testID="mpr-print">
            <Text style={s.expTxt}>Print</Text>
          </Pressable>
        </View>

        {data ? (
          <Text style={s.runNote}>
            Compliance run: {data.compliance_run
              ? (data.compliance_finalized ? "✓ Finalized" : "Draft") : "— not processed"} ·
            {" "}Actual run: {data.actual_run ? "✓ Available" : "— not processed"} ·
            {" "}Employees: {rows.length}
          </Text>
        ) : null}
        {err ? <Text style={s.err}>{err}</Text> : null}
        {loading ? <ActivityIndicator style={{ marginTop: 20 }} color={colors.brandPrimary} /> : null}

        {!loading && data && !rows.length ? (
          <Text style={s.empty}>No employees found for {month}.</Text>
        ) : null}

        {!loading && rows.length ? grid : null}

        {!loading && rows.length ? (
          <View style={s.legend}>
            <View style={[s.legItem, { backgroundColor: HRS_UI.bg }]}>
              <Text style={[s.legTxt, { color: HRS_UI.fg }]}>
                {data?.att_mode === "HRS+OT"
                  ? "8+4 = Duty HRS + OT HRS (attendance policy)"
                  : "8 = Duty HRS (attendance policy)"}
              </Text>
            </View>
            {Object.entries({
              "-": "Absent / No Punch", WO: "Weekly Off", HO: "Holiday",
              CL: "Casual Leave", PL: "Paid Leave", EL: "Earned Leave",
              SL: "Sick Leave", ESIC: "ESIC Leave",
            }).map(([k, lbl]) => {
              const ui = CODE_UI[k] || { bg: "#F1F5F9", fg: "#334155" };
              return (
                <View key={k} style={[s.legItem, { backgroundColor: ui.bg }]}>
                  <Text style={[s.legTxt, { color: ui.fg }]}>{k} = {lbl}</Text>
                </View>
              );
            })}
          </View>
        ) : null}
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  title: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  filterRow: {
    flexDirection: "row", gap: 8, marginTop: 10, alignItems: "center",
    flexWrap: "wrap",
  },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13,
    color: colors.onSurface, backgroundColor: colors.surface,
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
  },
  stepBtn: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 8, justifyContent: "center", alignItems: "center",
    backgroundColor: colors.surface, minHeight: 36,
  },
  pickBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1,
    borderColor: colors.border, borderRadius: 8, paddingHorizontal: 10,
    paddingVertical: 8, backgroundColor: colors.surface, maxWidth: 170,
  },
  pickTxt: { fontSize: 12, color: colors.onSurface },
  selLbl: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  chip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 6, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, color: colors.onSurface, fontWeight: "600" },
  expBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 14, paddingVertical: 9, minWidth: 58, alignItems: "center",
  },
  expTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  runNote: {
    color: "#0F3B5C", fontSize: 11.5, fontWeight: "700", marginTop: 10,
    backgroundColor: "#EFF6FF", borderRadius: 8, paddingHorizontal: 10,
    paddingVertical: 6, borderWidth: 1, borderColor: "#BFDBFE",
  },
  err: { color: "#B91C1C", marginTop: 10, fontSize: 12.5 },
  empty: { color: colors.onSurfaceTertiary, marginTop: 20, textAlign: "center" },
  tr: { flexDirection: "row", backgroundColor: "#fff" },
  td: {
    borderWidth: 0.5, borderColor: "#CBD5E1", paddingHorizontal: 3,
    paddingVertical: 4, justifyContent: "center", alignItems: "center",
  },
  tdTxt: { fontSize: 10, color: colors.onSurface, textAlign: "center" },
  th: { backgroundColor: "#0F3B5C" },
  thTxt: { color: "#fff", fontSize: 9, fontWeight: "800", textAlign: "center" },
  legend: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 12 },
  legItem: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 },
  legTxt: { fontSize: 10.5, fontWeight: "700" },
  mBack: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.55)", justifyContent: "center",
    alignItems: "center", padding: 16,
  },
  mCard: {
    width: "100%", maxWidth: 400, backgroundColor: colors.surface,
    borderRadius: 14, padding: 16,
  },
  mTitle: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  mRow: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#F1F5F9" },
  mRowTxt: { fontSize: 13, color: colors.onSurface },
  mRowSel: { fontWeight: "800", color: colors.brandPrimary },
});
