/**
 * Employee Full Report — consolidated per-employee reporting.
 *
 * Pick a firm → pick an employee → pick a period → see EVERYTHING about
 * that employee in one view: Profile, Attendance, Leaves, Actual Salary,
 * Compliance Salary, Documents and Tickets. Export as XLSX or PDF.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ActivityIndicator,
  ScrollView,
  Platform,
  Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";
import DateField from "@/src/components/DateField";

type Employee = {
  user_id: string;
  name?: string;
  employee_code?: string;
  designation?: string;
  company_id?: string;
};

type ReportData = {
  employee: Record<string, any>;
  period: { from_date: string; to_date: string };
  attendance: {
    days: {
      date: string; first_in?: string; last_out?: string;
      hours?: number; punch_count: number; sources?: string[]; statuses?: string[];
    }[];
    summary: { present_days: number; total_punches: number; total_hours: number; avg_hours: number };
  };
  leaves: Record<string, any>[];
  salary_rows: Record<string, any>[];
  compliance_rows: Record<string, any>[];
  documents: Record<string, any>[];
  tickets: Record<string, any>[];
};

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function monthStart(offset = 0): string {
  const d = new Date();
  d.setMonth(d.getMonth() + offset, 1);
  return iso(d);
}

function monthEnd(offset = 0): string {
  const d = new Date();
  d.setMonth(d.getMonth() + offset + 1, 0);
  return iso(d);
}

function fyStart(): string {
  const now = new Date();
  const y = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  return `${y}-04-01`;
}

function inr(n?: number): string {
  if (n === undefined || n === null || !Number.isFinite(n)) return "—";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function hhmm(at?: string): string {
  if (!at) return "—";
  const t = at.slice(11, 16);
  return t || "—";
}

function showMsg(msg: string) {
  if (Platform.OS === "web") globalThis.alert(msg);
}

async function downloadBinary(path: string, filename: string) {
  try {
    const res = await apiBinary(path);
    if (Platform.OS === "web" && res.webBlobUrl) {
      const a = document.createElement("a");
      a.href = res.webBlobUrl;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
    }
  } catch (e: any) {
    showMsg(e?.message || "Download failed");
  }
}

export default function EmployeeReportScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { companies, selectedCompanyId } = useSelectedCompany();
  const isAdmin =
    user?.role === "super_admin" || user?.role === "sub_admin" || user?.role === "company_admin";

  const [firmId, setFirmId] = useState<string>(selectedCompanyId || "");
  // Iter 230 (user request) — firm dropdown + payslip section state.
  const [firmDdOpen, setFirmDdOpen] = useState(false);
  const [firmQuery, setFirmQuery] = useState("");
  const [slipMonth, setSlipMonth] = useState<string>(() => {
    const d = new Date();
    d.setMonth(d.getMonth() - 1, 1);
    return d.toISOString().slice(0, 7);
  });
  const [slipBusy, setSlipBusy] = useState<string | null>(null);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [empLoading, setEmpLoading] = useState(false);
  const [empSearch, setEmpSearch] = useState("");
  const [empId, setEmpId] = useState<string>("");

  const [fromDate, setFromDate] = useState<string>(monthStart());
  const [toDate, setToDate] = useState<string>(iso(new Date()));

  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState<"" | "xlsx" | "pdf">("");
  const [data, setData] = useState<ReportData | null>(null);

  // Load employees whenever the firm changes.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setEmpLoading(true);
      setEmpId("");
      setData(null);
      try {
        const q = firmId ? `?company_id=${encodeURIComponent(firmId)}` : "";
        const r = await api<{ employees: Employee[] }>(`/admin/employees${q}`);
        if (!cancelled) setEmployees(r.employees || []);
      } catch {
        if (!cancelled) setEmployees([]);
      } finally {
        if (!cancelled) setEmpLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [firmId]);

  const filteredEmployees = useMemo(() => {
    const s = empSearch.trim().toLowerCase();
    if (!s) return employees;
    return employees.filter(
      (e) =>
        (e.name || "").toLowerCase().includes(s) ||
        (e.employee_code || "").toLowerCase().includes(s),
    );
  }, [employees, empSearch]);

  const selectedEmp = useMemo(
    () => employees.find((e) => e.user_id === empId),
    [employees, empId],
  );

  const canGenerate = !!empId && !!fromDate && !!toDate;

  // Iter 230 (user request) — payslip download / mail actions.
  const payslipAction = async (kind: "dl-one" | "dl-all" | "mail-one" | "mail-all") => {
    const m = slipMonth.trim();
    if (!/^\d{4}-\d{2}$/.test(m)) {
      showMsg("Enter the salary month as YYYY-MM (e.g. 2026-06).");
      return;
    }
    setSlipBusy(kind);
    try {
      if (kind === "dl-one") {
        await downloadBinary(
          `/admin/employee-payslip.pdf?company_id=${firmId}&user_id=${empId}&month=${m}`,
          `Payslip_${m}.pdf`,
        );
      } else if (kind === "dl-all") {
        await downloadBinary(
          `/admin/payslips-month.zip?company_id=${firmId}&month=${m}`,
          `Payslips_${m}.zip`,
        );
      } else {
        const r = await api<{ sent: number; no_email: string[]; failed: string[] }>(
          "/admin/payslips/email",
          {
            method: "POST",
            body: {
              company_id: firmId,
              month: m,
              ...(kind === "mail-one" ? { user_id: empId } : {}),
            },
          },
        );
        let msg = `Payslips e-mailed: ${r.sent}`;
        if (r.no_email?.length) msg += `\nNo e-mail in master (skipped): ${r.no_email.slice(0, 10).join(", ")}${r.no_email.length > 10 ? "…" : ""}`;
        if (r.failed?.length) msg += `\nFailed: ${r.failed.slice(0, 10).join(", ")}`;
        showMsg(msg);
      }
    } catch (e: any) {
      showMsg(e?.message || "Payslip action failed");
    } finally {
      setSlipBusy(null);
    }
  };

  const generate = async () => {
    if (!canGenerate) {
      showMsg("Select an employee and a date range first");
      return;
    }
    setLoading(true);
    try {
      const params = new URLSearchParams({
        user_id: empId,
        from_date: fromDate,
        to_date: toDate,
      });
      const r = await api<ReportData>(`/admin/employee-report?${params.toString()}`);
      setData(r);
    } catch (e: any) {
      showMsg(e?.message || "Failed to load employee report");
    } finally {
      setLoading(false);
    }
  };

  const doExport = async (fmt: "xlsx" | "pdf") => {
    if (!canGenerate) return;
    setExporting(fmt);
    try {
      const params = new URLSearchParams({
        user_id: empId,
        from_date: fromDate,
        to_date: toDate,
      });
      const code = selectedEmp?.employee_code || empId;
      await downloadBinary(
        `/admin/employee-report/export.${fmt}?${params.toString()}`,
        `employee-report-${code}-${fromDate}-to-${toDate}.${fmt}`,
      );
    } finally {
      setExporting("");
    }
  };

  const setRange = (f: string, t: string) => {
    setFromDate(f);
    setToDate(t);
  };

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Admins only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>Employee Full Report</Text>
            <Text style={styles.hsub}>All reports for one employee, one place</Text>
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* ----- Filters ----- */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>1 · Select employee</Text>

          {user?.role !== "company_admin" ? (
            <>
              <Text style={styles.label}>Firm</Text>
              {/* Iter 230 (user request) — firm selection as a dropdown. */}
              <Pressable
                onPress={() => setFirmDdOpen(true)}
                style={styles.ddTrigger}
                testID="er-firm-dropdown"
              >
                <Ionicons name="business-outline" size={15} color={colors.brandPrimary} />
                <Text style={styles.ddTriggerTxt} numberOfLines={1}>
                  {(companies || []).find((c) => c.company_id === firmId)?.name || "Select a firm…"}
                </Text>
                <Ionicons name="chevron-down" size={15} color={colors.onSurfaceSecondary} />
              </Pressable>
              <Modal visible={firmDdOpen} transparent animationType="fade" onRequestClose={() => setFirmDdOpen(false)}>
                <Pressable style={styles.ddBackdrop} onPress={() => setFirmDdOpen(false)}>
                  <Pressable style={styles.ddSheet} onPress={() => {}}>
                    <Text style={styles.ddTitle}>Select firm</Text>
                    <View style={styles.ddSearchRow}>
                      <Ionicons name="search" size={14} color={colors.onSurfaceSecondary} />
                      <TextInput
                        style={styles.ddSearchInput}
                        placeholder="Search firm by name…"
                        placeholderTextColor={colors.onSurfaceTertiary}
                        value={firmQuery}
                        onChangeText={setFirmQuery}
                        autoFocus
                        testID="er-firm-search"
                      />
                    </View>
                    <ScrollView style={{ maxHeight: 380 }} keyboardShouldPersistTaps="handled">
                      {(companies || [])
                        .filter((c) => !firmQuery.trim()
                          || String(c.name || "").toLowerCase().includes(firmQuery.trim().toLowerCase()))
                        .map((c) => (
                          <Pressable
                            key={c.company_id}
                            onPress={() => {
                              setFirmId(c.company_id);
                              setFirmDdOpen(false);
                              setFirmQuery("");
                            }}
                            style={[styles.ddItem, firmId === c.company_id && styles.ddItemActive]}
                            testID={`er-firm-${c.company_id}`}
                          >
                            <Ionicons
                              name={firmId === c.company_id ? "radio-button-on" : "radio-button-off"}
                              size={16}
                              color={firmId === c.company_id ? colors.brandPrimary : colors.onSurfaceTertiary}
                            />
                            <Text style={styles.ddItemTxt} numberOfLines={1}>{c.name || c.company_id}</Text>
                          </Pressable>
                        ))}
                    </ScrollView>
                  </Pressable>
                </Pressable>
              </Modal>
            </>
          ) : null}

          <Text style={styles.label}>Employee</Text>
          <TextInput
            style={styles.input}
            placeholder="Search by name or code…"
            placeholderTextColor={colors.onSurfaceTertiary}
            value={empSearch}
            onChangeText={setEmpSearch}
            testID="er-emp-search"
          />
          {empLoading ? (
            <ActivityIndicator style={{ marginVertical: 10 }} color={colors.brandPrimary} />
          ) : (
            <ScrollView style={styles.empList} nestedScrollEnabled>
              {filteredEmployees.slice(0, 200).map((e) => (
                <Pressable
                  key={e.user_id}
                  onPress={() => setEmpId(e.user_id)}
                  style={[styles.empRow, empId === e.user_id && styles.empRowActive]}
                  testID={`er-emp-${e.employee_code || e.user_id}`}
                >
                  <Ionicons
                    name={empId === e.user_id ? "radio-button-on" : "radio-button-off"}
                    size={16}
                    color={empId === e.user_id ? colors.brandPrimary : colors.onSurfaceTertiary}
                  />
                  <Text style={[styles.empName, empId === e.user_id && { color: colors.brandPrimary }]}>
                    {e.name || "—"}
                  </Text>
                  <Text style={styles.empCode}>
                    {e.employee_code || ""}{e.designation ? ` · ${e.designation}` : ""}
                  </Text>
                </Pressable>
              ))}
              {filteredEmployees.length === 0 ? (
                <Text style={styles.smallHint}>No employees found for this firm / search.</Text>
              ) : null}
            </ScrollView>
          )}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>2 · Period</Text>
          <View style={styles.chipStrip}>
            <Chip label="This month" active={fromDate === monthStart() && toDate === iso(new Date())}
              onPress={() => setRange(monthStart(), iso(new Date()))} />
            <Chip label="Last month" active={fromDate === monthStart(-1) && toDate === monthEnd(-1)}
              onPress={() => setRange(monthStart(-1), monthEnd(-1))} />
            <Chip label="Last 3 months" active={fromDate === monthStart(-2) && toDate === iso(new Date())}
              onPress={() => setRange(monthStart(-2), iso(new Date()))} />
            <Chip label="This FY" active={fromDate === fyStart() && toDate === iso(new Date())}
              onPress={() => setRange(fyStart(), iso(new Date()))} />
          </View>
          <View style={styles.filterRow}>
            <View style={styles.filterCol}>
              <Text style={styles.label}>From date</Text>
              <DateField value={fromDate} onChangeISO={setFromDate} testID="er-from-date" />
            </View>
            <View style={styles.filterCol}>
              <Text style={styles.label}>To date</Text>
              <DateField value={toDate} onChangeISO={setToDate} testID="er-to-date" />
            </View>
          </View>

          <Pressable
            onPress={generate}
            disabled={loading || !canGenerate}
            style={[styles.primaryBtn, (loading || !canGenerate) && { opacity: 0.5 }]}
            testID="er-generate"
          >
            {loading ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="analytics-outline" size={15} color="#fff" />
                <Text style={styles.primaryBtnTxt}>Generate Full Report</Text>
              </>
            )}
          </Pressable>

          {data ? (
            <View style={[styles.filterRow, { marginTop: 10 }]}>
              <Pressable
                onPress={() => doExport("xlsx")}
                disabled={!!exporting}
                style={[styles.exportBtn, exporting === "xlsx" && { opacity: 0.5 }]}
                testID="er-export-xlsx"
              >
                <Ionicons name="grid-outline" size={14} color={colors.brandPrimary} />
                <Text style={styles.exportBtnTxt}>{exporting === "xlsx" ? "Exporting…" : "Export Excel"}</Text>
              </Pressable>
              <Pressable
                onPress={() => doExport("pdf")}
                disabled={!!exporting}
                style={[styles.exportBtn, exporting === "pdf" && { opacity: 0.5 }]}
                testID="er-export-pdf"
              >
                <Ionicons name="document-outline" size={14} color={colors.brandPrimary} />
                <Text style={styles.exportBtnTxt}>{exporting === "pdf" ? "Exporting…" : "Export PDF"}</Text>
              </Pressable>
            </View>
          ) : null}
        </View>

        {/* ----- Iter 230 (user request) — Payslips: download / e-mail,
                employee-wise or ALL employees of the firm. ----- */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>3 · Payslips</Text>
          <Text style={styles.smallHint}>
            Uses the latest processed salary run (Compliance first, else Actual)
            for the chosen month. Mail goes to the employee&apos;s e-mail from the
            Employee Master.
          </Text>
          <Text style={styles.label}>Salary month (YYYY-MM)</Text>
          <TextInput
            style={[styles.input, { maxWidth: 160 }]}
            value={slipMonth}
            onChangeText={setSlipMonth}
            placeholder="2026-06"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID="er-slip-month"
          />
          <View style={[styles.chipStrip, { marginTop: 10 }]}>
            <Pressable
              onPress={() => payslipAction("dl-one")}
              disabled={!empId || !!slipBusy}
              style={[styles.slipBtn, (!empId || !!slipBusy) && { opacity: 0.5 }]}
              testID="er-slip-dl-one"
            >
              {slipBusy === "dl-one" ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : <Ionicons name="download-outline" size={14} color={colors.brandPrimary} />}
              <Text style={styles.slipBtnTxt}>Download Payslip (Selected)</Text>
            </Pressable>
            <Pressable
              onPress={() => payslipAction("dl-all")}
              disabled={!firmId || !!slipBusy}
              style={[styles.slipBtn, (!firmId || !!slipBusy) && { opacity: 0.5 }]}
              testID="er-slip-dl-all"
            >
              {slipBusy === "dl-all" ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : <Ionicons name="albums-outline" size={14} color={colors.brandPrimary} />}
              <Text style={styles.slipBtnTxt}>Download ALL (ZIP)</Text>
            </Pressable>
            <Pressable
              onPress={() => payslipAction("mail-one")}
              disabled={!empId || !!slipBusy}
              style={[styles.slipBtn, (!empId || !!slipBusy) && { opacity: 0.5 }]}
              testID="er-slip-mail-one"
            >
              {slipBusy === "mail-one" ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : <Ionicons name="mail-outline" size={14} color={colors.brandPrimary} />}
              <Text style={styles.slipBtnTxt}>Mail Payslip (Selected)</Text>
            </Pressable>
            <Pressable
              onPress={() => payslipAction("mail-all")}
              disabled={!firmId || !!slipBusy}
              style={[styles.slipBtn, (!firmId || !!slipBusy) && { opacity: 0.5 }]}
              testID="er-slip-mail-all"
            >
              {slipBusy === "mail-all" ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : <Ionicons name="send-outline" size={14} color={colors.brandPrimary} />}
              <Text style={styles.slipBtnTxt}>Mail ALL Employees</Text>
            </Pressable>
          </View>
        </View>

        {/* ----- Report ----- */}
        {data ? (
          <>
            {/* Profile */}
            <View style={styles.card}>
              <SectionTitle icon="person-outline" title="Profile" />
              <View style={styles.profileGrid}>
                <KV k="Name" v={data.employee.name} />
                <KV k="Emp Code" v={data.employee.employee_code} />
                <KV k="Father Name" v={data.employee.father_name} />
                <KV k="Designation" v={data.employee.designation} />
                <KV k="Department" v={data.employee.department} />
                <KV k="Type" v={data.employee.employee_type} />
                <KV k="Firm" v={data.employee.company_name} />
                <KV k="Phone" v={data.employee.phone} />
                <KV k="DOJ" v={data.employee.doj} />
                <KV k="UAN" v={data.employee.uan} />
                <KV k="ESIC No" v={data.employee.esic_no} />
                <KV k="PAN" v={data.employee.pan} />
              </View>
            </View>

            {/* Attendance */}
            <View style={styles.card}>
              <SectionTitle icon="finger-print-outline" title="Attendance" />
              <View style={styles.statRow}>
                <Stat label="Present days" value={String(data.attendance.summary.present_days)} />
                <Stat label="Punches" value={String(data.attendance.summary.total_punches)} />
                <Stat label="Total hours" value={String(data.attendance.summary.total_hours)} />
                <Stat label="Avg hrs/day" value={String(data.attendance.summary.avg_hours)} />
              </View>
              {data.attendance.days.length > 0 ? (
                <>
                  <View style={[styles.tRow, styles.tHead]}>
                    <Text style={[styles.tCell, styles.tHeadTxt, { flex: 1.2 }]}>Date</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>In</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>Out</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>Hrs</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>Punches</Text>
                  </View>
                  {data.attendance.days.map((d) => (
                    <View key={d.date} style={styles.tRow}>
                      <Text style={[styles.tCell, { flex: 1.2 }]}>{d.date}</Text>
                      <Text style={styles.tCell}>{hhmm(d.first_in)}</Text>
                      <Text style={styles.tCell}>{hhmm(d.last_out)}</Text>
                      <Text style={styles.tCell}>{d.hours ?? "—"}</Text>
                      <Text style={styles.tCell}>{d.punch_count}</Text>
                    </View>
                  ))}
                </>
              ) : (
                <Text style={styles.smallHint}>No attendance records in this period.</Text>
              )}
            </View>

            {/* Leaves */}
            <View style={styles.card}>
              <SectionTitle icon="calendar-number-outline" title={`Leaves · ${data.leaves.length}`} />
              {data.leaves.length === 0 ? (
                <Text style={styles.smallHint}>No leaves in this period.</Text>
              ) : (
                data.leaves.map((l, i) => (
                  <View key={i} style={styles.tRow}>
                    <Text style={[styles.tCell, { flex: 1 }]}>
                      {(l.leave_type || "—").toString().toUpperCase()}
                    </Text>
                    <Text style={[styles.tCell, { flex: 1.6 }]}>{l.from_date} → {l.to_date}</Text>
                    <Text style={[styles.tCell, statusColor(l.status)]}>{l.status || "—"}</Text>
                  </View>
                ))
              )}
            </View>

            {/* Salary */}
            <View style={styles.card}>
              <SectionTitle icon="cash-outline" title={`Actual Salary · ${data.salary_rows.length} month(s)`} />
              {data.salary_rows.length === 0 ? (
                <Text style={styles.smallHint}>No salary runs found for this period.</Text>
              ) : (
                <>
                  <View style={[styles.tRow, styles.tHead]}>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>Month</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>P Days</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>Gross</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>EPF</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>ESI</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>Net Pay</Text>
                  </View>
                  {data.salary_rows.map((r, i) => (
                    <View key={i} style={styles.tRow}>
                      <Text style={styles.tCell}>{r.month}</Text>
                      <Text style={styles.tCell}>{r.p_days ?? "—"}</Text>
                      <Text style={styles.tCell}>{inr(r.total_gross)}</Text>
                      <Text style={styles.tCell}>{inr(r.epf)}</Text>
                      <Text style={styles.tCell}>{inr(r.esi)}</Text>
                      <Text style={[styles.tCell, { fontWeight: "700" }]}>{inr(r.net_pay)}</Text>
                    </View>
                  ))}
                </>
              )}
            </View>

            {/* Compliance */}
            <View style={styles.card}>
              <SectionTitle icon="shield-checkmark-outline" title={`Compliance Salary · ${data.compliance_rows.length} month(s)`} />
              {data.compliance_rows.length === 0 ? (
                <Text style={styles.smallHint}>No compliance runs found for this period.</Text>
              ) : (
                <>
                  <View style={[styles.tRow, styles.tHead]}>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>Month</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>P Days</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>Basic</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>Gross Paid</Text>
                    <Text style={[styles.tCell, styles.tHeadTxt]}>Net Pay</Text>
                  </View>
                  {data.compliance_rows.map((r, i) => (
                    <View key={i} style={styles.tRow}>
                      <Text style={styles.tCell}>{r.month}</Text>
                      <Text style={styles.tCell}>{r.present_days ?? "—"}</Text>
                      <Text style={styles.tCell}>{inr(r.basic)}</Text>
                      <Text style={styles.tCell}>{inr(r.gross_paid)}</Text>
                      <Text style={[styles.tCell, { fontWeight: "700" }]}>{inr(r.net_pay)}</Text>
                    </View>
                  ))}
                </>
              )}
            </View>

            {/* Documents */}
            <View style={styles.card}>
              <SectionTitle icon="folder-open-outline" title={`Documents · ${data.documents.length}`} />
              {data.documents.length === 0 ? (
                <Text style={styles.smallHint}>No documents uploaded.</Text>
              ) : (
                data.documents.map((d, i) => (
                  <View key={i} style={styles.tRow}>
                    <Text style={[styles.tCell, { flex: 1 }]}>{d.category || "—"}</Text>
                    <Text style={[styles.tCell, { flex: 1.6 }]}>{d.name || d.filename || "—"}</Text>
                    <Text style={styles.tCell}>{(d.uploaded_at || "").slice(0, 10)}</Text>
                  </View>
                ))
              )}
            </View>

            {/* Tickets */}
            <View style={styles.card}>
              <SectionTitle icon="ticket-outline" title={`Tickets · ${data.tickets.length}`} />
              {data.tickets.length === 0 ? (
                <Text style={styles.smallHint}>No tickets raised in this period.</Text>
              ) : (
                data.tickets.map((t, i) => (
                  <View key={i} style={styles.tRow}>
                    <Text style={[styles.tCell, { flex: 2 }]}>{t.subject || t.title || "—"}</Text>
                    <Text style={[styles.tCell, statusColor(t.status)]}>{t.status || "—"}</Text>
                    <Text style={styles.tCell}>{(t.created_at || "").slice(0, 10)}</Text>
                  </View>
                ))
              )}
            </View>
          </>
        ) : null}
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[styles.chip, active && styles.chipActive]}>
      <Text style={[styles.chipTxt, active && styles.chipTxtActive]}>{label}</Text>
    </Pressable>
  );
}

function SectionTitle({ icon, title }: { icon: keyof typeof Ionicons.glyphMap; title: string }) {
  return (
    <View style={styles.secTitle}>
      <Ionicons name={icon} size={16} color={colors.brandPrimary} />
      <Text style={styles.secTitleTxt}>{title}</Text>
    </View>
  );
}

function KV({ k, v }: { k: string; v?: string | null }) {
  return (
    <View style={styles.kv}>
      <Text style={styles.kvK}>{k}</Text>
      <Text style={styles.kvV}>{v || "—"}</Text>
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statVal}>{value}</Text>
      <Text style={styles.statLbl}>{label}</Text>
    </View>
  );
}

function statusColor(status?: string) {
  const s = (status || "").toLowerCase();
  if (s === "approved" || s === "resolved" || s === "closed") return { color: "#16a34a", fontWeight: "700" as const };
  if (s === "rejected") return { color: "#dc2626", fontWeight: "700" as const };
  if (s === "pending" || s === "open") return { color: "#d97706", fontWeight: "700" as const };
  return {};
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    paddingHorizontal: spacing.md,
    height: 52,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
  },
  h1: { ...type.h5, color: colors.onSurface, fontWeight: "700" },
  hsub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },
  scroll: { padding: spacing.md, paddingBottom: 40 },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: { marginTop: 8, color: colors.onSurfaceTertiary, ...type.body },

  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cardTitle: { ...type.h6, color: colors.onSurface, fontWeight: "700", marginBottom: 6 },
  smallHint: { ...type.caption, color: colors.onSurfaceSecondary, paddingVertical: 6 },
  filterRow: { flexDirection: "row", gap: 10, flexWrap: "wrap", marginBottom: 6 },
  filterCol: { flex: 1, minWidth: 180 },
  label: {
    ...type.tiny, color: colors.onSurfaceSecondary,
    fontWeight: "700", marginBottom: 4, marginTop: 8,
    textTransform: "uppercase",
  },
  input: {
    borderWidth: 1, borderColor: colors.borderStrong,
    borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 10,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  chipStrip: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 4 },
  chip: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 14,
    borderWidth: 1, borderColor: colors.borderStrong, backgroundColor: colors.surface,
  },
  chipActive: { borderColor: colors.brandPrimary, backgroundColor: colors.brandPrimary },
  chipTxt: { color: colors.onSurfaceSecondary, fontWeight: "600", fontSize: 12 },
  chipTxtActive: { color: "#fff" },

  empList: { maxHeight: 240, marginTop: 8 },
  empRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 9, paddingHorizontal: 8,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  empRowActive: { backgroundColor: colors.brandTertiary, borderRadius: radius.md },
  empName: { fontSize: 13, fontWeight: "600", color: colors.onSurface },
  empCode: { fontSize: 11, color: colors.onSurfaceTertiary, marginLeft: "auto" },

  primaryBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingVertical: 12, marginTop: 10,
    flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "700" },
  exportBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    paddingVertical: 10, paddingHorizontal: 16, backgroundColor: colors.surface,
  },
  exportBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 13 },
  // Iter 230 — payslip buttons + firm dropdown.
  slipBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    paddingVertical: 9, paddingHorizontal: 12, backgroundColor: colors.surface,
  },
  slipBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  ddTrigger: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingVertical: 10, paddingHorizontal: 12, backgroundColor: colors.surface,
    marginBottom: 6,
  },
  ddTriggerTxt: { flex: 1, fontSize: 13, fontWeight: "700", color: colors.onSurface },
  ddBackdrop: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.45)",
    justifyContent: "center", alignItems: "center", padding: 20,
  },
  ddSheet: {
    width: "100%", maxWidth: 440, backgroundColor: colors.surface,
    borderRadius: radius.lg, padding: 14, borderWidth: 1, borderColor: colors.border,
  },
  ddTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  ddSearchRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, marginBottom: 8, backgroundColor: colors.background,
  },
  ddSearchInput: { flex: 1, paddingVertical: 9, fontSize: 13, color: colors.onSurface },
  ddItem: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 11, paddingHorizontal: 8,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  ddItemActive: { backgroundColor: colors.brandTertiary, borderRadius: radius.sm },
  ddItemTxt: { flex: 1, fontSize: 13, fontWeight: "600", color: colors.onSurface },

  secTitle: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  secTitleTxt: { ...type.h6, color: colors.onSurface, fontWeight: "700" },

  profileGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  kv: { minWidth: 140, flexGrow: 1, flexBasis: "28%" },
  kvK: { fontSize: 10, color: colors.onSurfaceTertiary, textTransform: "uppercase", fontWeight: "700" },
  kvV: { fontSize: 13, color: colors.onSurface, marginTop: 2, fontWeight: "600" },

  statRow: { flexDirection: "row", gap: 10, flexWrap: "wrap", marginBottom: 10 },
  stat: {
    flex: 1, minWidth: 90, backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    paddingVertical: 10, alignItems: "center",
  },
  statVal: { fontSize: 18, fontWeight: "800", color: colors.brandPrimary },
  statLbl: { fontSize: 10, color: colors.onSurfaceSecondary, marginTop: 2 },

  tRow: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  tHead: { borderBottomWidth: 2, borderBottomColor: colors.borderStrong, paddingVertical: 6 },
  tHeadTxt: { fontWeight: "800", fontSize: 10, textTransform: "uppercase", color: colors.onSurfaceSecondary },
  tCell: { flex: 1, fontSize: 12, color: colors.onSurface },
});
