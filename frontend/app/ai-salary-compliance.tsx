/**
 * Salary Compliance Process — AI (Iter 367).
 * Senior Payroll & Compliance Expert: loads an employee's data (or manual
 * entry), allowance/deduction heads come DYNAMICALLY from the Firm Master
 * (exact heads, exact order — no re-sorting/re-grouping), output includes
 * Sr. No. in every table. Strictly ADDITIVE — the Import Excel / Freeze
 * Salary process is untouched.
 */
import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
  Platform,
  StyleSheet,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { shared } from "@/src/components/RegisterTable";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";
import EmployeeDropdown from "@/src/components/EmployeeDropdown";

const ATT_FIELDS: [string, string][] = [
  ["working_days", "Working Days"],
  ["present_days", "Present Days"],
  ["paid_leave", "Paid Leave"],
  ["lop", "Loss of Pay (LOP)"],
  ["ot_hours", "Overtime Hours"],
];
const VAR_FIELDS: [string, string][] = [
  ["incentives", "Incentives"],
  ["bonus", "Bonus"],
  ["arrears", "Arrears"],
  ["reimbursements", "Reimbursements"],
  ["loan_recovery", "Loan/Advance Recovery"],
];
const STAT_FIELDS: [string, string][] = [
  ["pf_eligible", "PF Eligibility (Yes/No)"],
  ["esi_eligible", "ESI Eligibility (Yes/No)"],
  ["pt_state", "Professional Tax State"],
  ["tds_amount", "TDS (₹, if known)"],
  ["lwf_applicable", "LWF Applicable (Yes/No)"],
];

export default function AiSalaryComplianceScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { companies } = useSelectedCompany();
  const [companyId, setCompanyId] = useState("");
  const [empCode, setEmpCode] = useState("");
  // Iter 520 (user request) — employee NAME dropdown with search.
  const [emps, setEmps] = useState<any[]>([]);
  const [selEmpIds, setSelEmpIds] = useState<string[]>([]);
  const [month, setMonth] = useState("");
  const [form, setForm] = useState<Record<string, string>>({});
  const [allow, setAllow] = useState<{ head: string; amount: string }[]>([]);
  const [ded, setDed] = useState<{ head: string; amount: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [calc, setCalc] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState("");

  const isCompanyAdmin = user?.role === "company_admin";
  const set = (k: string, v: string) =>
    setForm((p) => ({ ...p, [k]: v }));

  // Iter 520 — load the firm's employees for the name dropdown.
  useEffect(() => {
    const cid = isCompanyAdmin ? user?.company_id : companyId;
    if (!cid) { setEmps([]); setSelEmpIds([]); setEmpCode(""); return; }
    (async () => {
      try {
        const r = await api<any>(`/admin/employees?company_id=${cid}`);
        setEmps(r.employees || []);
      } catch { setEmps([]); }
    })();
    setSelEmpIds([]);
    setEmpCode("");
  }, [companyId, isCompanyAdmin, user?.company_id]);

  const loadEmployee = async () => {
    const cid = isCompanyAdmin ? user?.company_id : companyId;
    if (!cid || !empCode || !month) {
      setErr("Select company, employee and month first");
      return;
    }
    setLoading(true);
    setErr("");
    try {
      const r = await api<any>(
        `/admin/ai-salary-compliance/employee-inputs?company_id=${cid}`
        + `&employee_code=${encodeURIComponent(empCode)}&month=${month}`);
      const i = r.inputs || {};
      const f: Record<string, string> = {};
      Object.entries(i).forEach(([k, v]) => {
        if (k !== "allowances" && k !== "deductions")
          f[k] = String(v ?? "");
      });
      setForm(f);
      setAllow((i.allowances || []).map((a: any) => ({
        head: a.head, amount: String(a.amount ?? 0) })));
      setDed((i.deductions || []).map((d: any) => ({
        head: d.head, amount: String(d.amount ?? 0) })));
      setResult("");
    } catch (e: any) {
      setErr(e?.message || "Employee not found");
    } finally {
      setLoading(false);
    }
  };

  const runCalc = async () => {
    if (!form.basic) {
      setErr("Basic Salary is required");
      return;
    }
    setCalc(true);
    setErr("");
    setResult("");
    try {
      const cid = isCompanyAdmin ? user?.company_id : companyId;
      const r = await api<any>("/admin/ai-salary-compliance/calculate", {
        method: "POST",
        body: {
          // When an employee is loaded, the backend computes with the
          // SAME Compliance Salary engine + firm policy (exact
          // deductions & net); manual entries fall back to AI-only.
          company_id: cid || undefined,
          employee_code: empCode || undefined,
          month: month || form.payroll_month || undefined,
          inputs: {
            ...form,
            allowances: allow
              .filter((a) => a.head)
              .map((a, ix) => ({ sr: ix + 1, head: a.head,
                amount: Number(a.amount) || 0 })),
            deductions: ded
              .filter((d) => d.head)
              .map((d, ix) => ({ sr: ix + 1, head: d.head,
                amount: Number(d.amount) || 0 })),
          },
        },
      });
      setResult(r.result || "");
    } catch (e: any) {
      setErr(e?.message || "AI calculation failed");
    } finally {
      setCalc(false);
    }
  };

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"]
    .includes(user.role)) return <Redirect href="/" />;

  const dynRows = (
    rows: { head: string; amount: string }[],
    setRows: React.Dispatch<React.SetStateAction<
      { head: string; amount: string }[]>>,
    testPrefix: string,
  ) => (
    <>
      {rows.map((r, ix) => (
        <View key={ix} style={st.dynRow}>
          <Text style={st.srNo}>{ix + 1}.</Text>
          <TextInput
            style={[shared.input, { flex: 2 }]}
            value={r.head}
            onChangeText={(t) => setRows((p) => p.map(
              (x, j) => (j === ix ? { ...x, head: t } : x)))}
            placeholder="Head"
            testID={`${testPrefix}-head-${ix}`}
          />
          <TextInput
            style={[shared.input, { flex: 1 }]}
            value={r.amount}
            onChangeText={(t) => setRows((p) => p.map(
              (x, j) => (j === ix ? { ...x, amount: t } : x)))}
            placeholder="₹"
            keyboardType="numeric"
            testID={`${testPrefix}-amt-${ix}`}
          />
          <Pressable
            onPress={() => setRows((p) => p.filter((_x, j) => j !== ix))}
            hitSlop={8}
          >
            <Ionicons name="close-circle-outline" size={18}
              color="#B91C1C" />
          </Pressable>
        </View>
      ))}
      <Pressable
        onPress={() => setRows((p) => [...p, { head: "", amount: "" }])}
        style={st.addRow}
        testID={`${testPrefix}-add`}
      >
        <Ionicons name="add-circle-outline" size={15}
          color={colors.brandPrimary} />
        <Text style={st.addTxt}>Add head</Text>
      </Pressable>
    </>
  );

  return (
    <SafeAreaView style={shared.safe} edges={["top"]}>
      <View style={shared.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}
          testID="sc-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={shared.headerTitle}>
          Salary Compliance Process (AI)
        </Text>
        <View style={{ width: 40 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: 12 }}>
        <View style={shared.card}>
          <Text style={shared.cardTitle}>
            👨‍💼 Load Employee (auto-fill from portal — read-only)
          </Text>
          <View style={[shared.row, { flexWrap: "wrap", gap: 8 }]}>
            {!isCompanyAdmin && Platform.OS === "web" && (
              <select
                data-testid="sc-company"
                value={companyId}
                onChange={(e) =>
                  setCompanyId((e.target as HTMLSelectElement).value)}
                style={{ padding: 8, borderRadius: 8,
                  border: "1px solid #CBD5E1", fontSize: 13,
                  maxWidth: 260 } as any}
              >
                <option value="">— Select Company —</option>
                {(companies || []).map((c: any) => (
                  <option key={c.company_id} value={c.company_id}>
                    {c.name}
                  </option>
                ))}
              </select>
            )}
            <View style={{ minWidth: 260, flexGrow: 1, maxWidth: 380 }}>
              <EmployeeDropdown
                employees={emps}
                value={selEmpIds}
                onChange={(ids) => {
                  setSelEmpIds(ids);
                  const e = emps.find((x) => x.user_id === ids[0]);
                  setEmpCode(e?.employee_code ? String(e.employee_code) : "");
                }}
                placeholder="Select employee (search by name)…"
                testID="sc-emp-dd"
              />
            </View>
            {Platform.OS === "web" && (
              <input
                data-testid="sc-month"
                type="month"
                value={month}
                onChange={(e) =>
                  setMonth((e.target as HTMLInputElement).value)}
                style={{ padding: 8, borderRadius: 8,
                  border: "1px solid #CBD5E1", fontSize: 13 } as any}
              />
            )}
            <Pressable onPress={loadEmployee} disabled={loading}
              style={st.loadBtn} testID="sc-load">
              {loading ? <ActivityIndicator size="small" color="#fff" />
                : <Text style={st.loadTxt}>Load Data</Text>}
            </Pressable>
          </View>
          <Text style={shared.meta}>
            Or fill the fields manually below. Allowance & deduction heads
            come from the Firm Master exactly as configured — same order,
            no re-grouping.
          </Text>
        </View>

        <View style={shared.card}>
          <Text style={shared.cardTitle}>Employee & Salary Structure</Text>
          <View style={st.grid}>
            {([["employee_name", "Employee Name"],
              ["payroll_month", "Payroll Month (YYYY-MM)"],
              ["basic", "Basic Salary (₹) *"],
              ["rate_basis", "Rate Basis (monthly / daily)"]] as const)
              .map(([k, lb]) => (
              <View key={k} style={st.field}>
                <Text style={st.lbl}>{lb}</Text>
                <TextInput style={shared.input} value={form[k] || ""}
                  onChangeText={(t) => set(k, t)} placeholder={lb}
                  testID={`sc-f-${k}`} />
              </View>
            ))}
          </View>
          <Text style={st.groupH}>
            Allowances (firm-wise, Sr. No. order preserved)
          </Text>
          {dynRows(allow, setAllow, "sc-allow")}
          <Text style={st.groupH}>
            Deductions (firm-wise, Sr. No. order preserved)
          </Text>
          {dynRows(ded, setDed, "sc-ded")}
        </View>

        {([["Attendance", ATT_FIELDS],
          ["Variable Pay", VAR_FIELDS],
          ["Statutory Details", STAT_FIELDS]] as const).map(([ttl, fs]) => (
          <View key={ttl} style={shared.card}>
            <Text style={shared.cardTitle}>{ttl}</Text>
            <View style={st.grid}>
              {fs.map(([k, lb]) => (
                <View key={k} style={st.field}>
                  <Text style={st.lbl}>{lb}</Text>
                  <TextInput style={shared.input} value={form[k] || ""}
                    onChangeText={(t) => set(k, t)} placeholder={lb}
                    testID={`sc-f-${k}`} />
                </View>
              ))}
            </View>
          </View>
        ))}

        <Pressable onPress={runCalc} disabled={calc} style={st.calcBtn}
          testID="sc-calculate">
          {calc ? <ActivityIndicator size="small" color="#fff" /> : (
            <>
              <Ionicons name="sparkles" size={16} color="#fff" />
              <Text style={st.calcTxt}>
                Calculate Salary with AI Expert
              </Text>
            </>
          )}
        </Pressable>
        {calc && (
          <Text style={[shared.meta, { textAlign: "center", marginTop: 6 }]}>
            The AI expert is working through PF/ESI/PT/TDS/LWF rules —
            this can take 30-60 seconds…
          </Text>
        )}
        {!!err && <Text style={st.errTxt} testID="sc-err">{err}</Text>}

        {!!result && (
          <View style={[shared.card, { marginTop: 12 }]}>
            <Text style={shared.cardTitle}>
              📋 Salary Compliance Report
            </Text>
            <Text style={st.result} selectable testID="sc-result">
              {result}
            </Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  loadBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 9,
    justifyContent: "center",
  },
  loadTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  field: { minWidth: 180, flexGrow: 1, maxWidth: 300 },
  lbl: {
    fontSize: 11.5,
    color: colors.onSurfaceSecondary,
    marginBottom: 3,
  },
  groupH: {
    fontSize: 12,
    fontWeight: "800",
    color: colors.onSurface,
    marginTop: 12,
    marginBottom: 5,
  },
  dynRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 6,
    maxWidth: 520,
  },
  srNo: {
    fontSize: 12,
    fontWeight: "800",
    color: colors.onSurfaceSecondary,
    width: 22,
  },
  addRow: {
    flexDirection: "row",
    gap: 5,
    alignItems: "center",
    paddingVertical: 4,
  },
  addTxt: {
    fontSize: 12,
    color: colors.brandPrimary,
    fontWeight: "700",
  },
  calcBtn: {
    flexDirection: "row",
    gap: 8,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.brandPrimary,
    borderRadius: 10,
    paddingVertical: 13,
    marginTop: 4,
  },
  calcTxt: { color: "#fff", fontWeight: "800", fontSize: 14 },
  errTxt: {
    color: "#B91C1C",
    fontSize: 12.5,
    fontWeight: "700",
    marginTop: 8,
  },
  result: {
    fontFamily: Platform.OS === "web" ? "monospace" : undefined,
    fontSize: 12,
    color: "#0F172A",
    lineHeight: 18,
    backgroundColor: "#F8FAFC",
    borderRadius: 8,
    padding: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
});
