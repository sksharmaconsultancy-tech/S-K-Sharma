/**
 * Salary Register — Iter 305 (Enterprise reporting module).
 *
 * Payroll → Salary Process → Salary Register. One dynamic register over
 * BOTH engines (Compliance & Actual). Columns come from the backend
 * (dynamic salary heads — never hardcoded here), grouped into banded
 * headers (Employee / Attendance / Earnings / Deductions / Employer /
 * Net) in a Microsoft-365 / SAP-Fiori visual style:
 *   • KPI strip (employees, gross, deductions, net)
 *   • Sticky banded header + frozen Sr/Code/Name columns
 *   • Server-side pagination + column sorting
 *   • Filters: firm, FY-wise month, run, group, branch, dept, contractor, search
 *   • Exports: PDF / Excel / CSV
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator,
  ScrollView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import MonthPicker from "@/src/components/MonthPicker";
import { GridScroller, stickyCol, stickyHeader } from "@/src/components/GridFreeze";
import { colors, radius, shadow, spacing } from "@/src/theme";

type Col = { key: string; label: string; group: string; type: "text" | "num" | "int" };
type Grp = { key: string; label: string };
type RunMeta = {
  run_id?: string; generated_at?: string; employees_count?: number;
  month?: string; month_days?: number;
};
type Filters = {
  months: string[];
  runs: { run_id?: string; generated_at?: string; employees_count?: number; employee_type_filter?: string }[];
  branches: string[]; departments: string[]; employee_types: string[]; contractors: string[];
  firm_email?: string | null;
};

const GROUP_COLORS: Record<string, string> = {
  info: "#44546A", attendance: "#7F7F7F", earnings: "#2E7D32",
  deductions: "#B71C1C", employer: "#6A1B9A", net: "#1F4E79",
};

const PAGE_SIZES = [25, 50, 100, 200];

const fmtNum = (v: any) => {
  const n = Number(v || 0);
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};
const fmtMoney = (v: any) => `₹${fmtNum(v)}`;

function colWidth(c: Col): number {
  if (c.key === "name") return 170;
  if (c.key === "father_name" || c.key === "designation" || c.key === "contractor_name") return 130;
  if (c.type === "text") return 100;
  return 92;
}

export default function SalaryRegisterScreen() {
  const { user } = useAuth();
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  const [source, setSource] = useState<"compliance" | "actual">("compliance");
  const [companyId, setCompanyId] = useState<string | "all">(
    globalCid && globalCid !== "all" ? globalCid : "all",
  );
  const [month, setMonth] = useState("");
  const [runId, setRunId] = useState("");
  const [empType, setEmpType] = useState("");
  const [branch, setBranch] = useState("");
  const [department, setDepartment] = useState("");
  const [contractor, setContractor] = useState("");
  const [search, setSearch] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [sortBy, setSortBy] = useState("");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const [filters, setFilters] = useState<Filters | null>(null);
  const [columns, setColumns] = useState<Col[]>([]);
  const [groups, setGroups] = useState<Grp[]>([]);
  const [rows, setRows] = useState<any[]>([]);
  const [totals, setTotals] = useState<Record<string, number>>({});
  const [totalRows, setTotalRows] = useState(0);
  const [runMeta, setRunMeta] = useState<RunMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [err, setErr] = useState("");
  // Iter 307 — Email register to firm.
  const [emailOpen, setEmailOpen] = useState(false);
  const [emailTo, setEmailTo] = useState("");
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailMsg, setEmailMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const cid = isSuper ? (companyId === "all" ? "" : companyId) : (user?.company_id || "");
  const searchTimer = useRef<any>(null);

  // Follow the globally selected firm (header badge) when it changes.
  useEffect(() => {
    if (globalCid && globalCid !== "all") setCompanyId(globalCid);
  }, [globalCid]);

  // ---- filters (months + facets) -----------------------------------------
  const loadFilters = useCallback(async () => {
    if (!cid) { setFilters(null); return; }
    try {
      const params = new URLSearchParams({ source, company_id: cid });
      if (month) params.set("month", month);
      const r = await api<Filters>(`/admin/salary-register/filters?${params}`);
      setFilters(r);
      // auto-pick the latest month with a run when none chosen / invalid
      if (r.months.length && (!month || !r.months.includes(month))) {
        setMonth(r.months[0]);
      }
    } catch (e: any) {
      setErr(e?.message || "Failed to load filters");
    }
  }, [cid, source, month]);

  useEffect(() => { loadFilters(); }, [loadFilters]);

  // reset dependent filters when the scope changes
  useEffect(() => {
    setRunId(""); setEmpType(""); setBranch(""); setDepartment("");
    setContractor(""); setPage(1); setSortBy("");
  }, [source, cid, month]);

  const buildParams = useCallback(() => {
    const p = new URLSearchParams({ source, month });
    if (cid) p.set("company_id", cid);
    if (runId) p.set("run_id", runId);
    if (empType) p.set("employee_type", empType);
    if (branch) p.set("branch", branch);
    if (department) p.set("department", department);
    if (contractor) p.set("contractor", contractor);
    if (search) p.set("search", search);
    if (sortBy) { p.set("sort_by", sortBy); p.set("sort_dir", sortDir); }
    return p;
  }, [source, month, cid, runId, empType, branch, department, contractor, search, sortBy, sortDir]);

  // ---- main data ----------------------------------------------------------
  const loadData = useCallback(async () => {
    if (!cid || !month) { setRows([]); setColumns([]); setRunMeta(null); return; }
    setLoading(true); setErr("");
    try {
      const p = buildParams();
      p.set("page", String(page));
      p.set("page_size", String(pageSize));
      const r = await api<any>(`/admin/salary-register?${p}`);
      setColumns(r.columns || []);
      setGroups(r.groups || []);
      setRows(r.rows || []);
      setTotals(r.totals || {});
      setTotalRows(r.total_rows || 0);
      setRunMeta(r.run_meta || null);
    } catch (e: any) {
      setErr(e?.message || "Failed to load register");
    } finally { setLoading(false); }
  }, [cid, month, page, pageSize, buildParams]);

  useEffect(() => { loadData(); }, [loadData]);

  // debounce search box
  const onSearchChange = (t: string) => {
    setSearchDraft(t);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => { setSearch(t); setPage(1); }, 400);
  };

  const onSort = (key: string) => {
    if (sortBy === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(key); setSortDir("asc");
    }
    setPage(1);
  };

  const doExport = async (kind: "pdf" | "xlsx" | "csv") => {
    if (!cid || !month) return;
    setExporting(kind);
    try {
      const p = buildParams();
      const res = await apiBinary(`/admin/salary-register/export.${kind}?${p}`);
      const fname = `salary_register_${source}_${month}.${kind}`;
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = fname;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      setErr(e?.message || "Export failed");
    } finally { setExporting(null); }
  };

  const sendEmail = async () => {
    if (!cid || !month) return;
    setEmailBusy(true); setEmailMsg(null);
    try {
      const r = await api<{ ok: boolean; to: string }>("/admin/salary-register/email", {
        method: "POST",
        body: {
          source, company_id: cid, month, run_id: runId || undefined,
          employee_type: empType || undefined, branch: branch || undefined,
          department: department || undefined, contractor: contractor || undefined,
          search: search || undefined,
          to: emailTo.trim() || undefined,
        },
      });
      setEmailMsg({ ok: true, text: `Register emailed to ${r.to} (PDF + Excel)` });
    } catch (e: any) {
      setEmailMsg({ ok: false, text: e?.message || "Email failed" });
    } finally { setEmailBusy(false); }
  };

  // ---- grid geometry ------------------------------------------------------
  const SR_W = 44, CODE_W = 72, NAME_W = 170;
  const nameCol = columns.find((c) => c.key === "name");
  const codeCol = columns.find((c) => c.key === "employee_code");
  const scrollCols = useMemo(
    () => columns.filter((c) => c.key !== "name" && c.key !== "employee_code"),
    [columns],
  );

  // banded header segments for the scrollable columns
  const bands = useMemo(() => {
    const out: { group: string; label: string; width: number }[] = [];
    for (const c of scrollCols) {
      const last = out[out.length - 1];
      if (last && last.group === c.group) last.width += colWidth(c);
      else {
        out.push({
          group: c.group,
          label: groups.find((g) => g.key === c.group)?.label || c.group,
          width: colWidth(c),
        });
      }
    }
    return out;
  }, [scrollCols, groups]);

  const pages = Math.max(1, Math.ceil(totalRows / pageSize));

  const chipRow = (
    label: string, values: string[], sel: string, onSel: (v: string) => void,
  ) => {
    if (!values.length) return null;
    return (
      <View style={styles.chipRowWrap}>
        <Text style={styles.chipRowLabel}>{label}</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View style={{ flexDirection: "row", gap: 6 }}>
            <Pressable
              onPress={() => { onSel(""); setPage(1); }}
              style={[styles.chip, !sel && styles.chipOn]}
            >
              <Text style={[styles.chipTxt, !sel && styles.chipTxtOn]}>All</Text>
            </Pressable>
            {values.map((v) => (
              <Pressable
                key={v}
                onPress={() => { onSel(sel === v ? "" : v); setPage(1); }}
                style={[styles.chip, sel === v && styles.chipOn]}
              >
                <Text style={[styles.chipTxt, sel === v && styles.chipTxtOn]}>{v}</Text>
              </Pressable>
            ))}
          </View>
        </ScrollView>
      </View>
    );
  };

  const kpi = (icon: any, label: string, value: string, color: string) => (
    <View style={[styles.kpiCard, { borderLeftColor: color }]}>
      <View style={[styles.kpiIcon, { backgroundColor: `${color}18` }]}>
        <Ionicons name={icon} size={17} color={color} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.kpiLabel}>{label}</Text>
        <Text style={styles.kpiValue} numberOfLines={1}>{value}</Text>
      </View>
    </View>
  );

  const grossKey = source === "compliance" ? "gross_paid" : "total_gross";
  const dedKey = source === "compliance" ? "total_deduction" : "";
  const netKey = source === "compliance" ? "net" : "net_pay";
  const dedTotal = dedKey
    ? totals[dedKey] || 0
    : (totals["epf"] || 0) + (totals["esi"] || 0) + (totals["adv"] || 0) + (totals["tds"] || 0);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.container}>
        {/* ---- header ---- */}
        <View style={styles.headerRow}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 10, flex: 1 }}>
            <View style={styles.headerIcon}>
              <Ionicons name="grid-outline" size={20} color={colors.onBrandPrimary} />
            </View>
            <View>
              <Text style={styles.title}>Salary Register</Text>
              <Text style={styles.subtitle}>
                Dynamic register with live heads, filters & exports
              </Text>
            </View>
          </View>
          {/* source toggle */}
          <View style={styles.segment}>
            {(["compliance", "actual"] as const).map((s) => (
              <Pressable
                key={s}
                testID={`source-${s}`}
                onPress={() => setSource(s)}
                style={[styles.segBtn, source === s && styles.segBtnOn]}
              >
                <Ionicons
                  name={s === "compliance" ? "shield-checkmark-outline" : "cash-outline"}
                  size={14}
                  color={source === s ? colors.onBrandPrimary : colors.onSurfaceSecondary}
                />
                <Text style={[styles.segTxt, source === s && styles.segTxtOn]}>
                  {s === "compliance" ? "Compliance" : "Actual"}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>

        {/* ---- filter card ---- */}
        <View style={styles.card}>
          <View style={styles.filterTop}>
            {isSuper && (
              <View style={{ minWidth: 220, flex: 1 }}>
                <Text style={styles.fieldLabel}>Firm / Company</Text>
                <CompanyPicker value={companyId} onChange={setCompanyId} allowAll={false} />
              </View>
            )}
            <View style={{ minWidth: 200 }}>
              <Text style={styles.fieldLabel}>Month (FY-wise)</Text>
              <MonthPicker value={month} onChange={setMonth} allowEmpty={false} fyMode yearsBack={12} />
            </View>
            <View style={{ minWidth: 220, flex: 1 }}>
              <Text style={styles.fieldLabel}>Search employee</Text>
              <View style={styles.searchBox}>
                <Ionicons name="search-outline" size={15} color={colors.onSurfaceSecondary} />
                <TextInput
                  style={styles.searchInput}
                  placeholder="Name, code, father, designation…"
                  placeholderTextColor={colors.onSurfaceSecondary}
                  value={searchDraft}
                  onChangeText={onSearchChange}
                  testID="register-search"
                />
                {!!searchDraft && (
                  <Pressable onPress={() => { setSearchDraft(""); setSearch(""); setPage(1); }}>
                    <Ionicons name="close-circle" size={16} color={colors.onSurfaceSecondary} />
                  </Pressable>
                )}
              </View>
            </View>
          </View>

          {/* run selector when multiple runs exist for the month */}
          {!!filters?.runs && filters.runs.length > 1 && (
            <View style={styles.chipRowWrap}>
              <Text style={styles.chipRowLabel}>Run</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                <View style={{ flexDirection: "row", gap: 6 }}>
                  {filters.runs.map((r, i) => {
                    const on = runId ? runId === r.run_id : i === 0;
                    const when = (r.generated_at || "").slice(0, 16).replace("T", " ");
                    return (
                      <Pressable
                        key={r.run_id || i}
                        onPress={() => { setRunId(r.run_id || ""); setPage(1); }}
                        style={[styles.chip, on && styles.chipOn]}
                      >
                        <Text style={[styles.chipTxt, on && styles.chipTxtOn]}>
                          {when || `Run ${i + 1}`}
                          {r.employee_type_filter ? ` · ${r.employee_type_filter}` : ""}
                          {` · ${r.employees_count ?? "?"} emp`}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </ScrollView>
            </View>
          )}

          {chipRow("Group", filters?.employee_types || [], empType, setEmpType)}
          {chipRow("Branch", filters?.branches || [], branch, setBranch)}
          {chipRow("Department", filters?.departments || [], department, setDepartment)}
          {chipRow("Contractor", filters?.contractors || [], contractor, setContractor)}
        </View>

        {!cid ? (
          <View style={styles.emptyBox}>
            <Ionicons name="business-outline" size={30} color={colors.onSurfaceSecondary} />
            <Text style={styles.emptyTxt}>Select a firm to open the register</Text>
          </View>
        ) : loading ? (
          <View style={styles.emptyBox}>
            <ActivityIndicator color={colors.brandPrimary} />
            <Text style={styles.emptyTxt}>Building register…</Text>
          </View>
        ) : !runMeta ? (
          <View style={styles.emptyBox}>
            <Ionicons name="file-tray-outline" size={30} color={colors.onSurfaceSecondary} />
            <Text style={styles.emptyTxt}>
              No {source} salary run found{month ? ` for ${month}` : ""}. Process the month first.
            </Text>
          </View>
        ) : (
          <>
            {/* ---- KPI strip ---- */}
            <View style={styles.kpiRow}>
              {kpi("people-outline", "Employees", String(totalRows), "#1F4E79")}
              {kpi("trending-up-outline", "Gross", fmtMoney(totals[grossKey]), "#2E7D32")}
              {kpi("trending-down-outline", "Deductions", fmtMoney(dedTotal), "#B71C1C")}
              {kpi("wallet-outline", "Net Payable", fmtMoney(totals[netKey]), "#6A1B9A")}
            </View>

            {/* ---- toolbar: run meta + exports ---- */}
            <View style={styles.toolbar}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flex: 1, flexWrap: "wrap" }}>
                <Ionicons name="time-outline" size={13} color={colors.onSurfaceSecondary} />
                <Text style={styles.metaTxt}>
                  Run {String(runMeta.run_id || "").slice(-6) || "—"} · generated{" "}
                  {(runMeta.generated_at || "").slice(0, 16).replace("T", " ") || "—"} ·{" "}
                  {runMeta.month_days || "-"} days
                </Text>
              </View>
              <View style={{ flexDirection: "row", gap: 8 }}>
                {([
                  ["pdf", "document-text-outline", "#B71C1C", "PDF"],
                  ["xlsx", "grid-outline", "#2E7D32", "Excel"],
                  ["csv", "list-outline", "#1F4E79", "CSV"],
                ] as const).map(([k, icon, c, lbl]) => (
                  <Pressable
                    key={k}
                    testID={`export-${k}`}
                    onPress={() => doExport(k)}
                    disabled={!!exporting}
                    style={[styles.expBtn, { borderColor: c }]}
                  >
                    {exporting === k
                      ? <ActivityIndicator size="small" color={c} />
                      : <Ionicons name={icon} size={14} color={c} />}
                    <Text style={[styles.expTxt, { color: c }]}>{lbl}</Text>
                  </Pressable>
                ))}
                {/* Iter 307 — Email register to firm. */}
                <Pressable
                  testID="email-register"
                  onPress={() => {
                    setEmailTo(filters?.firm_email || "");
                    setEmailMsg(null);
                    setEmailOpen((o) => !o);
                  }}
                  style={[styles.expBtn, { borderColor: colors.brandPrimary, backgroundColor: emailOpen ? colors.brandPrimary : colors.surface }]}
                >
                  <Ionicons name="mail-outline" size={14} color={emailOpen ? colors.onBrandPrimary : colors.brandPrimary} />
                  <Text style={[styles.expTxt, { color: emailOpen ? colors.onBrandPrimary : colors.brandPrimary }]}>Email</Text>
                </Pressable>
              </View>
            </View>

            {/* Iter 307 — email panel */}
            {emailOpen && (
              <View style={styles.emailPanel}>
                <Ionicons name="mail-outline" size={16} color={colors.brandPrimary} />
                <TextInput
                  style={styles.emailInput}
                  placeholder="firm@email.com"
                  placeholderTextColor={colors.onSurfaceSecondary}
                  value={emailTo}
                  onChangeText={setEmailTo}
                  autoCapitalize="none"
                  keyboardType="email-address"
                  testID="email-to-input"
                />
                <Pressable
                  onPress={sendEmail}
                  disabled={emailBusy}
                  style={styles.emailSendBtn}
                  testID="email-send"
                >
                  {emailBusy
                    ? <ActivityIndicator size="small" color={colors.onBrandPrimary} />
                    : <Ionicons name="send-outline" size={13} color={colors.onBrandPrimary} />}
                  <Text style={styles.emailSendTxt}>Send PDF + Excel</Text>
                </Pressable>
                {emailMsg && (
                  <Text style={{ fontSize: 12, fontWeight: "600", color: emailMsg.ok ? "#2E7D32" : colors.error }}>
                    {emailMsg.text}
                  </Text>
                )}
              </View>
            )}

            {!!err && <Text style={styles.errTxt}>{err}</Text>}

            {/* ---- grid ---- */}
            <View style={styles.gridCard}>
              <GridScroller maxHeight={620}>
                {/* banded group header */}
                <View style={[{ flexDirection: "row" }, stickyHeader(colors.surface)]}>
                  <View style={{ flexDirection: "row" }}>
                    <View style={[styles.bandCell, { width: SR_W, backgroundColor: "#44546A" },
                      stickyCol(0, "#44546A")]} />
                    <View style={[styles.bandCell, { width: CODE_W + NAME_W, backgroundColor: "#44546A" },
                      stickyCol(SR_W, "#44546A")]}>
                      <Text style={styles.bandTxt}>Employee</Text>
                    </View>
                    {bands.map((b, i) => (
                      <View
                        key={`${b.group}-${i}`}
                        style={[styles.bandCell, {
                          width: b.width,
                          backgroundColor: GROUP_COLORS[b.group] || "#1F4E79",
                        }]}
                      >
                        <Text style={styles.bandTxt}>{b.label}</Text>
                      </View>
                    ))}
                  </View>
                </View>
                {/* column header */}
                <View style={[{ flexDirection: "row" }, Platform.OS === "web"
                  ? ({ position: "sticky", top: 26, zIndex: 9 } as any) : null]}>
                  <View style={[styles.headCell, { width: SR_W }, stickyCol(0, "#1F4E79")]}>
                    <Text style={styles.headTxt}>Sr</Text>
                  </View>
                  <Pressable
                    onPress={() => onSort("employee_code")}
                    style={[styles.headCell, { width: CODE_W }, stickyCol(SR_W, "#1F4E79")]}
                  >
                    <Text style={styles.headTxt}>
                      {codeCol?.label || "Code"}{sortBy === "employee_code" ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                    </Text>
                  </Pressable>
                  <Pressable
                    onPress={() => onSort("name")}
                    style={[styles.headCell, { width: NAME_W, alignItems: "flex-start" },
                      stickyCol(SR_W + CODE_W, "#1F4E79")]}
                  >
                    <Text style={styles.headTxt}>
                      {nameCol?.label || "Name"}{sortBy === "name" ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                    </Text>
                  </Pressable>
                  {scrollCols.map((c) => (
                    <Pressable
                      key={c.key}
                      testID={`col-${c.key}`}
                      onPress={() => onSort(c.key)}
                      style={[styles.headCell, {
                        width: colWidth(c),
                        alignItems: c.type === "text" ? "flex-start" : "flex-end",
                      }]}
                    >
                      <Text style={styles.headTxt} numberOfLines={2}>
                        {c.label}{sortBy === c.key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                      </Text>
                    </Pressable>
                  ))}
                </View>
                {/* data rows */}
                {rows.map((r, i) => {
                  const zebra = i % 2 === 1;
                  const rowBg = zebra ? colors.surfaceSecondary : colors.surface;
                  return (
                    <View key={`${r.employee_code}-${i}`} style={[styles.dataRow, { backgroundColor: rowBg }]}>
                      <View style={[styles.cell, { width: SR_W }, stickyCol(0, rowBg)]}>
                        <Text style={styles.cellTxtMuted}>{(page - 1) * pageSize + i + 1}</Text>
                      </View>
                      <View style={[styles.cell, { width: CODE_W }, stickyCol(SR_W, rowBg)]}>
                        <Text style={styles.cellTxt}>{r.employee_code ?? ""}</Text>
                      </View>
                      <View style={[styles.cell, { width: NAME_W, alignItems: "flex-start" },
                        stickyCol(SR_W + CODE_W, rowBg)]}>
                        <Text style={[styles.cellTxt, { fontWeight: "600" }]} numberOfLines={1}>
                          {r.name ?? ""}
                        </Text>
                      </View>
                      {scrollCols.map((c) => (
                        <View
                          key={c.key}
                          style={[styles.cell, {
                            width: colWidth(c),
                            alignItems: c.type === "text" ? "flex-start" : "flex-end",
                          }]}
                        >
                          <Text
                            style={[
                              styles.cellTxt,
                              c.type !== "text" && styles.numTxt,
                              c.group === "net" && styles.netTxt,
                            ]}
                            numberOfLines={1}
                          >
                            {c.type === "num" ? fmtNum(r[c.key])
                              : c.type === "int" ? String(Math.round(Number(r[c.key] || 0)))
                              : String(r[c.key] ?? "")}
                          </Text>
                        </View>
                      ))}
                    </View>
                  );
                })}
                {/* totals row */}
                <View style={[styles.dataRow, styles.totalRow]}>
                  <View style={[styles.cell, { width: SR_W }, stickyCol(0, "#FFF3CD")]} />
                  <View style={[styles.cell, { width: CODE_W }, stickyCol(SR_W, "#FFF3CD")]} />
                  <View style={[styles.cell, { width: NAME_W, alignItems: "flex-start" },
                    stickyCol(SR_W + CODE_W, "#FFF3CD")]}>
                    <Text style={styles.totalTxt}>TOTAL ({totalRows} emp)</Text>
                  </View>
                  {scrollCols.map((c) => (
                    <View
                      key={c.key}
                      style={[styles.cell, {
                        width: colWidth(c),
                        alignItems: c.type === "text" ? "flex-start" : "flex-end",
                      }]}
                    >
                      <Text style={styles.totalTxt} numberOfLines={1}>
                        {c.type === "text" ? "" : fmtNum(totals[c.key])}
                      </Text>
                    </View>
                  ))}
                </View>
              </GridScroller>

              {/* ---- pagination footer ---- */}
              <View style={styles.pagerRow}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Text style={styles.metaTxt}>Rows:</Text>
                  {PAGE_SIZES.map((s) => (
                    <Pressable
                      key={s}
                      onPress={() => { setPageSize(s); setPage(1); }}
                      style={[styles.pageSizeBtn, pageSize === s && styles.pageSizeOn]}
                    >
                      <Text style={[styles.pageSizeTxt, pageSize === s && styles.pageSizeTxtOn]}>{s}</Text>
                    </Pressable>
                  ))}
                </View>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                  <Text style={styles.metaTxt}>
                    {totalRows === 0 ? "0" :
                      `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, totalRows)}`} of {totalRows}
                  </Text>
                  <Pressable
                    onPress={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    style={[styles.pagerBtn, page <= 1 && { opacity: 0.35 }]}
                    testID="pager-prev"
                  >
                    <Ionicons name="chevron-back" size={16} color={colors.onSurface} />
                  </Pressable>
                  <Text style={[styles.metaTxt, { fontWeight: "700" }]}>{page} / {pages}</Text>
                  <Pressable
                    onPress={() => setPage((p) => Math.min(pages, p + 1))}
                    disabled={page >= pages}
                    style={[styles.pagerBtn, page >= pages && { opacity: 0.35 }]}
                    testID="pager-next"
                  >
                    <Ionicons name="chevron-forward" size={16} color={colors.onSurface} />
                  </Pressable>
                </View>
              </View>
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surfaceSecondary },
  container: { padding: spacing.lg, paddingBottom: 60 },
  headerRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    flexWrap: "wrap", gap: 12, marginBottom: 14,
  },
  headerIcon: {
    width: 40, height: 40, borderRadius: 10, backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  title: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 1 },
  segment: {
    flexDirection: "row", backgroundColor: colors.surface, borderRadius: 10,
    borderWidth: 1, borderColor: colors.border, padding: 3, gap: 3,
  },
  segBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8,
  },
  segBtnOn: { backgroundColor: colors.brandPrimary },
  segTxt: { fontSize: 13, fontWeight: "600", color: colors.onSurfaceSecondary },
  segTxtOn: { color: colors.onBrandPrimary },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: 14,
    borderWidth: 1, borderColor: colors.border, marginBottom: 14, ...shadow.card,
  },
  filterTop: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  fieldLabel: {
    fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary,
    textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 5,
  },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: 6, height: 44,
    borderWidth: 1, borderColor: colors.border, borderRadius: 10,
    paddingHorizontal: 10, backgroundColor: colors.surface,
  },
  searchInput: { flex: 1, fontSize: 13, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" } as any : null) },
  chipRowWrap: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10 },
  chipRowLabel: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary, width: 84 },
  chip: {
    paddingHorizontal: 11, paddingVertical: 6, borderRadius: 16,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, color: colors.onSurfaceSecondary, fontWeight: "600" },
  chipTxtOn: { color: colors.onBrandPrimary },
  emptyBox: {
    alignItems: "center", justifyContent: "center", padding: 44, gap: 10,
    backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
  },
  emptyTxt: { fontSize: 13, color: colors.onSurfaceSecondary, textAlign: "center" },
  kpiRow: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginBottom: 12 },
  kpiCard: {
    flexDirection: "row", alignItems: "center", gap: 10, flexGrow: 1, flexBasis: 180,
    backgroundColor: colors.surface, borderRadius: radius.md, padding: 12,
    borderWidth: 1, borderColor: colors.border, borderLeftWidth: 4,
  },
  kpiIcon: { width: 34, height: 34, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  kpiLabel: { fontSize: 11, color: colors.onSurfaceSecondary, fontWeight: "600" },
  kpiValue: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  toolbar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    flexWrap: "wrap", gap: 10, marginBottom: 10,
  },
  metaTxt: { fontSize: 12, color: colors.onSurfaceSecondary },
  expBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12,
    paddingVertical: 8, borderRadius: 8, borderWidth: 1.2, backgroundColor: colors.surface,
  },
  expTxt: { fontSize: 12, fontWeight: "700" },
  emailPanel: {
    flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 10,
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, padding: 10, marginBottom: 10,
  },
  emailInput: {
    flexGrow: 1, minWidth: 220, height: 40, borderWidth: 1, borderColor: colors.border,
    borderRadius: 8, paddingHorizontal: 10, fontSize: 13, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" } as any : null),
  },
  emailSendBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.brandPrimary,
    paddingHorizontal: 14, paddingVertical: 10, borderRadius: 8,
  },
  emailSendTxt: { color: colors.onBrandPrimary, fontSize: 12, fontWeight: "700" },
  errTxt: { color: colors.error, fontSize: 12, marginBottom: 8 },
  gridCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, overflow: "hidden",
  },
  bandCell: {
    height: 26, alignItems: "center", justifyContent: "center",
    borderRightWidth: 1, borderRightColor: "rgba(255,255,255,0.25)",
  },
  bandTxt: { fontSize: 10.5, fontWeight: "800", color: "#fff", letterSpacing: 0.5 },
  headCell: {
    height: 40, justifyContent: "center", alignItems: "flex-end",
    paddingHorizontal: 8, backgroundColor: "#1F4E79",
    borderRightWidth: 1, borderRightColor: "rgba(255,255,255,0.16)",
  },
  headTxt: { fontSize: 10.5, fontWeight: "700", color: "#fff" },
  dataRow: { flexDirection: "row" },
  cell: {
    height: 34, justifyContent: "center", alignItems: "flex-end",
    paddingHorizontal: 8, borderBottomWidth: 1, borderBottomColor: colors.divider,
    borderRightWidth: 1, borderRightColor: colors.divider,
  },
  cellTxt: { fontSize: 12, color: colors.onSurface },
  cellTxtMuted: { fontSize: 11, color: colors.onSurfaceSecondary },
  numTxt: { fontVariant: ["tabular-nums"] as any },
  netTxt: { fontWeight: "800", color: "#1F4E79" },
  totalRow: { backgroundColor: "#FFF3CD" },
  totalTxt: { fontSize: 11.5, fontWeight: "800", color: "#6b5518" },
  pagerRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    flexWrap: "wrap", gap: 10, padding: 10, borderTopWidth: 1, borderTopColor: colors.border,
  },
  pageSizeBtn: {
    paddingHorizontal: 9, paddingVertical: 5, borderRadius: 6,
    borderWidth: 1, borderColor: colors.border,
  },
  pageSizeOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  pageSizeTxt: { fontSize: 11.5, color: colors.onSurfaceSecondary, fontWeight: "600" },
  pageSizeTxtOn: { color: colors.onBrandPrimary },
  pagerBtn: {
    width: 32, height: 32, borderRadius: 8, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center", backgroundColor: colors.surface,
  },
});
