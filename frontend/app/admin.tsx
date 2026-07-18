import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator,
  Modal, TextInput, KeyboardAvoidingView, Platform, Alert, Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";
import { useFocusEffect } from "@react-navigation/native";

import { useOnRefresh } from "@/src/context/RefreshBusContext";

import { api, apiBinary } from "@/src/api/client";
import { useLiveSync } from "@/src/api/live-sync";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import SalaryUpdateModal from "@/src/components/SalaryUpdateModal";
import { EmployeeStatsBar, EmployeeListSkeleton } from "@/src/components/EmployeeStatsBar";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import DateField from "@/src/components/DateField";
import { formatDate, ddmmyyyyToISO } from "@/src/utils/date";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import * as FileSystemNS from "expo-file-system";
import * as Sharing from "expo-sharing";

const FileSystem: any = FileSystemNS as any;

const ROLES = ["employee", "company_admin", "super_admin"] as const;

type Company = { company_id: string; name: string };

export default function AdminScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const params = useLocalSearchParams<{ section?: string }>();
  const isSuper = user?.role === "super_admin";
  // Iter 133 (user bug) — sub-admins must get the same firm scoping as
  // super admins (their /companies list is already restricted server-side).
  const isScopedAdmin = isSuper || user?.role === "sub_admin";
  // Iter 77 - Session lock. When the operator has already picked a firm
  // during this session, restrict all firm selectors on this page to that
  // single firm; force logout to switch.
  const { selectedCompanyId: lockedCid, isLocked } = useSelectedCompany();
  // Iter 83 — Auto-scroll targets for jumping straight to a section from
  // Home tab shortcuts (e.g. "Employee Master Data" → scroll to
  // "Employees" section).
  const scrollRef = React.useRef<any>(null);
  const employeesSectionRef = React.useRef<any>(null);

  const [companies, setCompaniesRaw] = useState<Company[]>([]);
  const setCompanies = (cs: Company[]) => setCompaniesRaw(cs);
  // Effective firm list respects the session lock.
  const effectiveCompanies = React.useMemo(() => {
    if (isLocked && lockedCid) {
      return companies.filter((c) => c.company_id === lockedCid);
    }
    return companies;
  }, [companies, isLocked, lockedCid]);
  const [companyFilter, setCompanyFilter] = useState<string | "all">(lockedCid || "all");
  // User directive (Iter 132) — Employee Master must show ONLY the selected
  // company's employees. Whenever the global firm selection changes, scope
  // this screen to it automatically.
  useEffect(() => {
    if (lockedCid) setCompanyFilter(lockedCid);
  }, [lockedCid]);
  const [employees, setEmployees] = useState<any[]>([]);
  const [typeFilter, setTypeFilter] = useState<string | "all">("all");
  const [rollFilter, setRollFilter] = useState<"all" | "on" | "off">("all");
  // Iter 166 — employment status filter (user request): Active (default) /
  // Resigned / All employees.
  const [statusFilter, setStatusFilter] = useState<"active" | "resigned" | "all">("active");
  // Iter 169 — shared status helpers (used by the type-count chips AND the
  // list so the counts always match what is displayed).
  const isResigned = (e: any) => {
    if (e.exit_date) return true;
    if (e.resign_date) return true;
    if (e.date_of_leaving || e.leaving_date) return true;
    if (
      typeof e.employment_status === "string" &&
      ["exited", "resigned", "terminated", "inactive", "left"].includes(
        e.employment_status.toLowerCase(),
      )
    ) {
      return true;
    }
    return false;
  };
  const matchesStatus = (e: any) => {
    if (statusFilter === "resigned") return isResigned(e);
    if (statusFilter === "all") return true;
    // active (default) — keep the pre-Iter-166 behaviour
    if (e.is_onroll === false) return false;
    if (e.disabled === true) return false;
    return !isResigned(e);
  };
  const [pending, setPending] = useState<any[]>([]);
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const [selected, setSelected] = useState<any | null>(null);
  // Iter 89 — Salary Update modal (Web only)
  const [salaryModalUser, setSalaryModalUser] = useState<string | null>(null);
  const [role, setRole] = useState<(typeof ROLES)[number]>("employee");
  const [assignedCompany, setAssignedCompany] = useState<string | null>(null);
  const [empCode, setEmpCode] = useState("");
  const [dept, setDept] = useState("");
  const [pos, setPos] = useState("");
  const [exitDate, setExitDate] = useState("");
  const [isLiveIn, setIsLiveIn] = useState<boolean>(false);
  const [saving, setSaving] = useState(false);

  // Iter 77 - Search + Sort for employee list
  const [empQuery, setEmpQuery] = useState<string>("");
  const [sortKey, setSortKey] = useState<"code" | "name" | "doj" | "dept" | "salary">("code");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const companyParam =
        isScopedAdmin && companyFilter !== "all" ? `?company_id=${companyFilter}` : "";
      const [e, s, c, p] = await Promise.all([
        api<{ employees: any[] }>(`/admin/employees${companyParam}`),
        api(`/admin/stats${companyParam}`).catch(() => null),
        isScopedAdmin
          ? api<{ companies: Company[] }>("/companies").catch(() => ({ companies: [] }))
          : Promise.resolve({ companies: [] as Company[] }),
        api<{ pending: any[] }>(`/admin/pending-approvals${companyParam}`).catch(() => ({ pending: [] })),
      ]);
      setEmployees(e.employees || []);
      setStats(s);
      if (isScopedAdmin) setCompanies(c.companies || []);
      setPending(p.pending || []);
    } finally { setLoading(false); }
  }, [companyFilter, isScopedAdmin]);

  useEffect(() => { load(); }, [load]);
  // Iter 72 — Refresh on tab focus + on top-bar Refresh click.
  useFocusEffect(useCallback(() => { load(); }, [load]));
  useOnRefresh(load);

  // Iter 77n — Live-sync: refresh pending approvals + counters when
  // leaves are decided or employees change.
  useLiveSync(lockedCid, (ev) => {
    if (!ev?.type) return;
    if (
      ev.type.startsWith("leave.") ||
      ev.type === "employee.created" ||
      ev.type === "employee.updated" ||
      ev.type === "punch.created"
    ) {
      load();
    }
  });

  const decide = async (u: any, action: "approve" | "reject") => {
    setDecidingId(u.user_id);
    try {
      await api("/admin/approve-employee", {
        method: "PATCH",
        body: { user_id: u.user_id, action },
      });
      await load();
    } finally {
      setDecidingId(null);
    }
  };

  const doDeleteEmp = (e: any) => {
    const proceed = async () => {
      try {
        await api(`/admin/employees/${e.user_id}`, { method: "DELETE" });
        await load();
      } catch (err: any) {
        const msg = err?.message || "Delete failed";
        if (Platform.OS === "web") {
          if (typeof window !== "undefined") window.alert(msg);
        } else {
          Alert.alert("Delete failed", msg);
        }
      }
    };
    const msg = `Delete ${e.name || e.email}? This will also remove their attendance, leaves, tickets and payslips. Cannot be undone.`;
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && window.confirm(msg)) proceed();
    } else {
      Alert.alert("Delete employee", msg, [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: proceed },
      ]);
    }
  };

  const [bulkDl, setBulkDl] = useState(false);
  const bulkExportMasterPdf = async () => {
    if (bulkDl) return;
    setBulkDl(true);
    try {
      const qs =
        isScopedAdmin && companyFilter !== "all"
          ? `?company_id=${companyFilter}`
          : "";
      const res = await apiBinary(`/admin/employees/master-pdf/bulk${qs}`);
      const stamp = new Date().toISOString().replace(/[:T]/g, "-").slice(0, 16);
      const fname = `EmployeeMaster_Bulk_${stamp}.pdf`;
      if (Platform.OS === "web") {
        if (res.webBlobUrl) {
          const a = document.createElement("a");
          a.href = res.webBlobUrl;
          a.download = fname;
          a.click();
          setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
        }
      } else {
        const path = `${FileSystem.cacheDirectory}${fname}`;
        await FileSystem.writeAsStringAsync(path, res.base64, {
          encoding: "base64",
        });
        if (await Sharing.isAvailableAsync()) {
          await Sharing.shareAsync(path, {
            mimeType: "application/pdf",
            dialogTitle: "Save bulk Employee Master PDF",
            UTI: "com.adobe.pdf",
          });
        }
      }
    } catch (err: any) {
      const msg = err?.message || "Bulk export failed";
      if (Platform.OS === "web") window.alert(msg);
      else Alert.alert("Bulk export", msg);
    } finally {
      setBulkDl(false);
    }
  };

  const openEditor = (emp: any) => {
    setSelected(emp);
    setRole(emp.role);
    setAssignedCompany(emp.company_id || null);
    setEmpCode(emp.employee_code || "");
    setDept(emp.department || "");
    setPos(emp.position || "");
    setExitDate(emp.exit_date || "");
    setIsLiveIn(!!emp.is_live_in);
  };

  const save = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      // Convert the DD/MM/YYYY exit date field back to ISO before saving
      const exitISO = exitDate.trim() ? (ddmmyyyyToISO(exitDate.trim()) || exitDate.trim()) : "";
      await api("/admin/user-role", {
        method: "PATCH",
        body: {
          user_id: selected.user_id,
          ...(isSuper ? { role, company_id: assignedCompany } : {}),
          employee_code: empCode,
          department: dept,
          position: pos,
          is_live_in: isLiveIn,
          // send exit_date; empty string clears it on the backend
          exit_date: exitISO,
        },
      });
      setSelected(null);
      await load();
    } finally { setSaving(false); }
  };

  const companyName = (id?: string | null) => {
    if (!id) return "Unassigned";
    return companies.find((c) => c.company_id === id)?.name || id;
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Admin Panel</Text>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll}>
        {isScopedAdmin && (
          <View style={styles.firmHero}>
            <View style={styles.firmHeroLabelRow}>
              <Ionicons name="business" size={16} color={colors.onCta} />
              <Text style={styles.firmHeroLabel}>Active firm</Text>
              {isLocked ? (
                <View style={styles.firmHeroLockPill}>
                  <Ionicons name="lock-closed" size={10} color="#fff" />
                  <Text style={styles.firmHeroLockTxt}>Locked</Text>
                </View>
              ) : null}
            </View>
            <View style={styles.firmHeroPickerWrap}>
              <CompanyPicker
                testID="admin-company-picker"
                value={companyFilter}
                onChange={(v) => setCompanyFilter(v)}
                companies={companies}
                label=""
                compact={false}
                allowAll={!isLocked}
              />
            </View>
            <Text style={styles.firmHeroHint}>
              {companyFilter === "all"
                ? "Showing rollup across all firms. Pick a firm to scope every screen (KPIs, employees, reports, salary run)."
                : `All screens are scoped to: ${companies.find((c) => c.company_id === companyFilter)?.name || companyFilter}. ${isLocked ? "Log out to switch." : "Change any time from here."}`}
            </Text>
          </View>
        )}

        {stats && (
          <View style={styles.statsGrid}>
            {isSuper && (
              <View style={styles.stat}>
                <Text style={styles.statV}>{stats.total_companies ?? companies.length}</Text>
                <Text style={styles.statL}>Companies</Text>
              </View>
            )}
            <View style={styles.stat}>
              <Text style={styles.statV}>{stats.total_employees}</Text>
              <Text style={styles.statL}>Employees</Text>
            </View>
            <View style={styles.stat}>
              <Text style={styles.statV}>{stats.present_today}</Text>
              <Text style={styles.statL}>Present today</Text>
            </View>
            <View style={styles.stat}>
              <Text style={styles.statV}>{stats.pending_leaves}</Text>
              <Text style={styles.statL}>Pending leaves</Text>
            </View>
            <View style={styles.stat}>
              <Text style={styles.statV}>{stats.open_tickets}</Text>
              <Text style={styles.statL}>Open tickets</Text>
            </View>
          </View>
        )}

        <Pressable
          testID="open-add-employee"
          style={styles.actionTile}
          onPress={() => router.push("/employee-add")}
        >
          <View style={styles.actionIcon}>
            <Ionicons name="person-add-outline" size={20} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.actionTitle}>Add employee</Text>
            <Text style={styles.actionSub}>
              New hire — fill the master sheet from the web portal. Code + PIN auto-assigned.
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
        </Pressable>

        {/* Quick actions — Punch approvals first (day-to-day admin task) */}
        <Pressable
          testID="open-punch-approvals"
          style={styles.actionTile}
          onPress={() => router.push("/punch-approvals")}
        >
          <View style={styles.actionIcon}>
            <Ionicons name="checkmark-done-circle-outline" size={20} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.actionTitle}>Punch approvals</Text>
            <Text style={styles.actionSub}>
              Review auto punch-in / punch-out — approve, adjust the time, or reject.
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
        </Pressable>

        {/* ── Company Policies section ────────────────────────────────── */}
        <Text style={styles.sectionHeading}>Company Policies</Text>

        <Pressable
          testID="open-attendance-policy"
          style={styles.actionTile}
          onPress={() => {
            // Only pass company_id when super_admin has narrowed the filter to a
            // specific company. Passing 'all' or an empty string would 404.
            const validScope =
              isSuper && companyFilter && companyFilter !== "all";
            const target = validScope
              ? { pathname: "/attendance-policy", params: { company_id: companyFilter } }
              : "/attendance-policy";
            router.push(target as any);
          }}
        >
          <View style={styles.actionIcon}>
            <Ionicons name="time-outline" size={20} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.actionTitle}>Attendance policy</Text>
            <Text style={styles.actionSub}>
              {isSuper
                ? "Pick a company from the filter above, then tap here to configure shifts, weekly-off & OT rules."
                : "Shifts, weekly-off, OT thresholds — tuned to your business type."}
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
        </Pressable>

        {/* Iter 83 — Moved to LAST position of Company Policies per user request. */}
        <Pressable
          testID="open-biometric-devices"
          style={styles.actionTile}
          onPress={() => router.push("/biometric-devices")}
        >
          <View style={styles.actionIcon}>
            <Ionicons name="finger-print-outline" size={20} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.actionTitle}>Biometric devices (ZKTeco)</Text>
            <Text style={styles.actionSub}>
              Real-time punch sync from your ZKTeco AC Mini Plus entry & exit machines.
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
        </Pressable>

        <Pressable
          testID="admin-salary-run-tile"
          style={styles.actionTile}
          onPress={() => router.push("/salary-run")}
        >
          <View style={styles.actionIcon}>
            <Ionicons name="cash-outline" size={20} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.actionTitle}>Salary process</Text>
            <Text style={styles.actionSub}>
              Month-wise batch salary calc for the whole firm — filter by
              type / on-roll, override month-days, download CSV + PDF
              register, push to payslips. (Web portal recommended.)
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
        </Pressable>

        <Pressable
          testID="admin-ot-salary-tile"
          style={styles.actionTile}
          onPress={() => router.push("/ot-salary-run")}
        >
          <View style={styles.actionIcon}>
            <Ionicons name="time-outline" size={20} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.actionTitle}>OT salary process</Text>
            <Text style={styles.actionSub}>Separate overtime payout — Textile Policy 2 firms</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.onSurface60} />
        </Pressable>

        <Pressable
          testID="admin-compliance-salary-tile"
          style={styles.actionTile}
          onPress={() => router.push("/compliance-salary-run")}
        >
          <View style={styles.actionIcon}>
            <Ionicons name="briefcase-outline" size={20} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.actionTitle}>Compliance salary process</Text>
            <Text style={styles.actionSub}>
              Statutory-side payroll — PF · ESIC · PT · TDS under the new
              labour code. Wage base = max(Basic, 50% of Gross). Web-only.
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
        </Pressable>

        <Pressable
          testID="admin-backdate-tile"
          style={styles.actionTile}
          onPress={() => router.push("/backdate-punches")}
        >
          <View style={styles.actionIcon}>
            <Ionicons name="calendar-clear-outline" size={20} color={colors.brandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.actionTitle}>Back-date punches</Text>
            <Text style={styles.actionSub}>
              {isSuper
                ? "Add, edit or delete an employee's punches for any date. All actions are audited."
                : "Add / edit / delete punches for the last 90 days. Audit log is kept."}
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
        </Pressable>

        <View style={styles.sectionRow}>
          <Text style={styles.section}>
            Pending approvals
            {pending.length > 0 ? (
              <Text style={styles.badge}>  {pending.length}</Text>
            ) : null}
          </Text>
        </View>

        {pending.length === 0 ? (
          <Text style={styles.empty} testID="pending-empty">
            No pending approvals. New employee sign-ups will appear here.
          </Text>
        ) : (
          pending.map((u) => (
            <View
              key={u.user_id}
              style={styles.pendingRow}
              testID={`pending-${u.user_id}`}
            >
              <View style={[styles.avatar, styles.avatarPending]}>
                <Text style={styles.avatarTxt}>{(u.name || "?")[0]}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.empName}>{u.name || u.email}</Text>
                <Text style={styles.empMeta}>{u.email}</Text>
                <View style={styles.metaRow}>
                  {u.company_name ? (
                    <Text style={styles.empMeta}>{u.company_name}</Text>
                  ) : null}
                  {u.employee_code ? (
                    <Text style={styles.empMeta}>· {u.employee_code}</Text>
                  ) : null}
                </View>
                <View style={styles.decideRow}>
                  <Pressable
                    onPress={() => decide(u, "approve")}
                    disabled={decidingId === u.user_id}
                    style={[styles.decideBtn, styles.approveBtn]}
                    testID={`approve-${u.user_id}`}
                  >
                    {decidingId === u.user_id ? (
                      <ActivityIndicator color="#fff" size="small" />
                    ) : (
                      <>
                        <Ionicons name="checkmark" size={14} color="#fff" />
                        <Text style={styles.decideTxt}>Approve</Text>
                      </>
                    )}
                  </Pressable>
                  <Pressable
                    onPress={() => decide(u, "reject")}
                    disabled={decidingId === u.user_id}
                    style={[styles.decideBtn, styles.rejectBtn]}
                    testID={`reject-${u.user_id}`}
                  >
                    <Ionicons name="close" size={14} color="#8A1F1F" />
                    <Text style={[styles.decideTxt, { color: "#8A1F1F" }]}>Reject</Text>
                  </Pressable>
                </View>
              </View>
            </View>
          ))
        )}

        <View style={styles.sectionRow}>
          <Text style={styles.section}>Employees</Text>
          <View style={{ flexDirection: "row", gap: 12, alignItems: "center" }}>
            <Pressable
              onPress={() => router.push("/bulk-employee-correction")}
              hitSlop={6}
              testID="link-bulk-correction"
            >
              <Text style={styles.link}>Bulk Correction →</Text>
            </Pressable>
            <Pressable
              onPress={bulkExportMasterPdf}
              hitSlop={6}
              disabled={bulkDl || employees.length === 0}
              testID="bulk-export-master-pdf"
            >
              <Text
                style={[
                  styles.link,
                  (bulkDl || employees.length === 0) && { opacity: 0.5 },
                ]}
              >
                {bulkDl ? "Exporting…" : "⤓ Bulk Master PDF"}
              </Text>
            </Pressable>
            {isSuper && (
              <Pressable onPress={() => router.push("/companies")} hitSlop={6}>
                <Text style={styles.link}>Manage companies →</Text>
              </Pressable>
            )}
          </View>
        </View>

        {/* Iter 182 — premium stat cards */}
        {!loading && employees.length > 0 ? (
          <EmployeeStatsBar employees={employees} />
        ) : null}

        {/* Iter 77 - Employee search + sort controls */}
        <View style={styles.empToolbar}>
          <View style={styles.empSearchBox}>
            <Ionicons name="search" size={14} color={colors.onSurfaceTertiary} />
            <TextInput
              style={styles.empSearchInput}
              value={empQuery}
              onChangeText={setEmpQuery}
              placeholder="Search name / code / phone / dept"
              placeholderTextColor={colors.onSurfaceTertiary}
            />
            {empQuery ? (
              <Pressable onPress={() => setEmpQuery("")} hitSlop={6}>
                <Ionicons name="close-circle" size={14} color={colors.onSurfaceTertiary} />
              </Pressable>
            ) : null}
          </View>
          <View style={styles.sortRow}>
            <Text style={styles.sortLabel}>Sort:</Text>
            {(["code","name","doj","dept","salary"] as const).map((k) => (
              <Pressable
                key={k}
                onPress={() => {
                  if (sortKey === k) {
                    setSortDir((d) => (d === "asc" ? "desc" : "asc"));
                  } else {
                    setSortKey(k);
                    setSortDir("asc");
                  }
                }}
                style={[styles.sortChip, sortKey === k && styles.sortChipOn]}
                testID={`sort-${k}`}
              >
                <Text
                  style={[styles.sortChipTxt, sortKey === k && styles.sortChipTxtOn]}
                >
                  {({ code:"Code", name:"Name", doj:"DOJ", dept:"Dept", salary:"Salary" } as any)[k]}
                  {sortKey === k ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>

        {/* Iter 166 — Employment status filter chips */}
        <View style={styles.statusChipRow}>
          {([
            ["active", "ACTIVE EMPLOYEE"],
            ["resigned", "RESIGN EMPLOYEE"],
            ["all", "ALL EMPLOYEE"],
          ] as const).map(([key, label]) => (
            <Pressable
              key={key}
              onPress={() => setStatusFilter(key)}
              style={[styles.statusChip, statusFilter === key && styles.statusChipOn]}
              testID={`status-filter-${key}`}
            >
              <Text style={[styles.statusChipTxt, statusFilter === key && styles.statusChipTxtOn]}>
                {label}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Filter chips: Type + On/Off-roll (counts follow the status filter) */}
        <EmployeeFilterChips
          employees={employees.filter(matchesStatus)}
          typeFilter={typeFilter}
          onTypeChange={setTypeFilter}
          rollFilter={rollFilter}
          onRollChange={setRollFilter}
        />

        {loading ? (
          <EmployeeListSkeleton rows={6} />
        ) : employees.length === 0 ? (
          <Text style={styles.empty}>
            No employees yet. New Google sign-ups will appear here.
          </Text>
        ) : (
          (() => {
            // Iter 166/169 — status filter (helpers hoisted to component
            // scope so the count chips share the same logic).
            const visible = employees.filter((e) => {
              if (!matchesStatus(e)) return false;
              if (rollFilter === "on" && e.is_onroll === false) return false;
              if (rollFilter === "off" && e.is_onroll !== false) return false;
              if (typeFilter !== "all") {
                const cur = (e.employee_type || "").trim().toLowerCase();
                if (typeFilter === "__unset__") {
                  if (cur) return false;
                } else if (cur !== typeFilter.toLowerCase()) {
                  return false;
                }
              }
              // Iter 77 - Search filter
              const needle = empQuery.trim().toLowerCase();
              if (needle) {
                const hay = [
                  e.name, e.email, e.phone, e.employee_code,
                  e.department, e.position, e.bio_code,
                ].filter(Boolean).map(String).join(" ").toLowerCase();
                if (!hay.includes(needle)) return false;
              }
              return true;
            });
            // Iter 77 - Sort
            const dirMul = sortDir === "asc" ? 1 : -1;
            visible.sort((a: any, b: any) => {
              const gs = (o: any) => {
                switch (sortKey) {
                  case "name": return (o.name || "").toString().toLowerCase();
                  case "doj": return (o.join_date || o.doj || "").toString();
                  case "dept": return (o.department || "").toString().toLowerCase();
                  case "salary": return Number(o.salary_monthly || 0);
                  case "code":
                  default: return (o.employee_code || "").toString();
                }
              };
              const va = gs(a); const vb = gs(b);
              if (typeof va === "number" && typeof vb === "number") return (va - vb) * dirMul;
              return String(va).localeCompare(String(vb)) * dirMul;
            });
            if (visible.length === 0) {
              return (
                <Text style={styles.empty}>
                  No employees match the current filters.
                </Text>
              );
            }
            return visible.map((e) => (
            <Pressable
              key={e.user_id}
              style={styles.empRow}
              testID={`emp-${e.user_id}`}
              onPress={() => {
                // Iter 77 - Row tap opens the Preview modal (photo, name,
                // code, dept, phone, DOJ, salary + inline edit + link to
                // full Employee Master editor).
                openEditor(e);
              }}
            >
              <View style={styles.avatar}>
                <Text style={styles.avatarTxt}>{(e.name || "?")[0]}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <View style={styles.empHeadRow}>
                  <Text style={styles.empName} numberOfLines={1}>
                    {e.name}
                  </Text>
                  {e.employee_code ? (
                    <View style={styles.codePill}>
                      <Text style={styles.codePillTxt}>#{e.employee_code}</Text>
                    </View>
                  ) : null}
                  {isResigned(e) ? (
                    <View style={styles.resignedPill}>
                      <Text style={styles.resignedPillTxt}>
                        RESIGNED{e.exit_date ? ` · ${String(e.exit_date).slice(0, 10)}` : ""}
                      </Text>
                    </View>
                  ) : null}
                </View>
                <View style={styles.metaRow}>
                  {e.designation ? (
                    <Text style={styles.empMeta} numberOfLines={1}>
                      {e.designation}
                    </Text>
                  ) : null}
                  {e.department ? (
                    <Text style={styles.empMeta} numberOfLines={1}>
                      · {e.department}
                    </Text>
                  ) : null}
                </View>
                {e.salary_monthly ? (
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <Text style={styles.salaryLine}>
                      ₹{Number(e.salary_monthly).toLocaleString()}
                      {e.salary_mode ? ` · ${e.salary_mode}` : ""}
                    </Text>
                    {/* Iter 89 — Update Salary shortcut (Web only per user
                        request). Opens the two-block Actual / Compliance
                        editor without going through the big employee-master
                        screen. Mobile users edit salary via the field on
                        the Employee Master screen instead. */}
                    {Platform.OS === "web" ? (
                      <Pressable
                        onPress={(ev) => {
                          (ev as any)?.stopPropagation?.();
                          setSalaryModalUser(e.user_id);
                        }}
                        style={styles.salaryEditPill}
                        testID={`update-salary-${e.user_id}`}
                      >
                        <Ionicons name="cash-outline" size={12} color={colors.brandPrimary} />
                        <Text style={styles.salaryEditPillTxt}>Update Salary</Text>
                      </Pressable>
                    ) : null}
                  </View>
                ) : Platform.OS === "web" ? (
                  <Pressable
                    onPress={(ev) => {
                      (ev as any)?.stopPropagation?.();
                      setSalaryModalUser(e.user_id);
                    }}
                    style={styles.salaryEditPill}
                    testID={`add-salary-${e.user_id}`}
                  >
                    <Ionicons name="cash-outline" size={12} color={colors.brandPrimary} />
                    <Text style={styles.salaryEditPillTxt}>+ Set Salary</Text>
                  </Pressable>
                ) : null}
                {e.bio_code !== null && e.bio_code !== undefined && e.bio_code !== "" ? (
                  <Text style={styles.bioLine}>
                    Bio Code: {String(e.bio_code)}
                  </Text>
                ) : null}
              </View>
              <Ionicons
                name="chevron-forward"
                size={18}
                color={colors.onSurfaceTertiary}
              />
            </Pressable>
          ));
          })()
        )}
        <View style={{ height: 40 }} />
      </KeyboardAwareScrollView>

      <Modal
        transparent
        visible={!!selected}
        animationType="slide"
        onRequestClose={() => setSelected(null)}
      >
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          style={styles.modalRoot}
        >
          <Pressable style={styles.backdrop} onPress={() => setSelected(null)} />
          <View style={styles.sheet}>
            <KeyboardAwareScrollView bottomOffset={62} showsVerticalScrollIndicator={false}>
              <View style={styles.sheetGrip} />
              <View style={styles.previewRow}>
                <View style={styles.previewAvatar}>
                  {selected?.avatar_url ? (
                    <Image
                      source={{ uri: selected.avatar_url }}
                      style={{ width: 64, height: 64, borderRadius: 32 }}
                    />
                  ) : (
                    <Text style={styles.previewAvatarTxt}>
                      {(selected?.name || "?").slice(0, 1)}
                    </Text>
                  )}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.sheetTitle}>{selected?.name}</Text>
                  <Text style={styles.email}>{selected?.email}</Text>
                  <View style={styles.previewMetaRow}>
                    {selected?.employee_code ? (
                      <Text style={styles.previewMeta}>#{selected.employee_code}</Text>
                    ) : null}
                    {selected?.phone ? (
                      <Text style={styles.previewMeta}>· {selected.phone}</Text>
                    ) : null}
                    {(selected?.designation || selected?.department) ? (
                      <Text style={styles.previewMeta}>
                        · {selected?.designation || selected?.department}
                      </Text>
                    ) : null}
                  </View>
                  <View style={styles.previewMetaRow}>
                    {selected?.doj ? (
                      <Text style={styles.previewMeta}>DOJ: {formatDate(selected.doj)}</Text>
                    ) : null}
                    {selected?.salary_monthly ? (
                      <Text style={styles.previewMeta}>
                        · ₹{Number(selected.salary_monthly).toLocaleString()}
                      </Text>
                    ) : null}
                    {selected?.bio_code ? (
                      <Text style={styles.previewMeta}>· Bio {selected.bio_code}</Text>
                    ) : null}
                  </View>
                </View>
              </View>

              {/* Iter 96m — single edit entry point (Full Employee Master).
                  It contains the same one-page edit form as Add PLUS all
                  employee tools, so the duplicate "Edit Details" button was
                  removed per user request. */}
              <Pressable
                style={styles.editAllBtn}
                testID="open-employee-master"
                onPress={() => {
                  const uid = selected?.user_id;
                  setSelected(null);
                  if (uid) {
                    router.push({
                      pathname: "/employee-master",
                      params: { user_id: uid },
                    });
                  }
                }}
              >
                <Ionicons name="create-outline" size={16} color="#fff" />
                <Text style={styles.editAllBtnTxt}>
                  Edit / Manage Employee (all details)
                </Text>
                <Ionicons name="chevron-forward" size={16} color="#fff" />
              </Pressable>
              <Pressable
                style={styles.masterLinkBtn}
                testID="open-emp-attendance-policy"
                onPress={() => {
                  const uid = selected?.user_id;
                  setSelected(null);
                  if (uid) {
                    router.push({
                      pathname: "/employee-attendance-policy",
                      params: { user_id: uid },
                    });
                  }
                }}
              >
                <Ionicons name="time-outline" size={16} color={colors.brand} />
                <Text style={styles.masterLinkTxt}>
                  Set Attendance Policy override
                </Text>
                <Ionicons
                  name="chevron-forward"
                  size={16}
                  color={colors.brand}
                />
              </Pressable>

              {isSuper && (
                <>
                  <Text style={styles.label}>Role</Text>
                  <View style={styles.typeRow}>
                    {ROLES.map((r) => (
                      <Pressable
                        key={r}
                        onPress={() => setRole(r)}
                        style={[styles.typeChip, role === r && styles.typeChipActive]}
                      >
                        <Text
                          style={[styles.typeChipTxt, role === r && styles.typeChipTxtActive]}
                        >
                          {r.replace("_", " ")}
                        </Text>
                      </Pressable>
                    ))}
                  </View>

                  <Text style={styles.label}>Company</Text>
                  <View style={styles.typeRow}>
                    {isLocked ? null : (
                      <Pressable
                        onPress={() => setAssignedCompany(null)}
                        style={[
                          styles.typeChip,
                          assignedCompany === null && styles.typeChipActive,
                        ]}
                      >
                        <Text
                          style={[
                            styles.typeChipTxt,
                            assignedCompany === null && styles.typeChipTxtActive,
                          ]}
                        >
                          Unassigned
                        </Text>
                      </Pressable>
                    )}
                    {effectiveCompanies.map((c) => (
                      <Pressable
                        key={c.company_id}
                        onPress={() => setAssignedCompany(c.company_id)}
                        style={[
                          styles.typeChip,
                          assignedCompany === c.company_id && styles.typeChipActive,
                        ]}
                      >
                        <Text
                          style={[
                            styles.typeChipTxt,
                            assignedCompany === c.company_id && styles.typeChipTxtActive,
                          ]}
                        >
                          {c.name}
                        </Text>
                      </Pressable>
                    ))}
                    {isLocked && (
                      <View style={styles.lockPill}>
                        <Ionicons name="lock-closed" size={11} color="#fff" />
                        <Text style={styles.lockPillTxt}>Locked - logout to switch</Text>
                      </View>
                    )}
                  </View>
                  {companies.length === 0 && (
                    <Text style={styles.hint}>
                      No companies yet.{" "}
                      <Text
                        style={styles.linkInline}
                        onPress={() => {
                          setSelected(null);
                          router.push("/companies");
                        }}
                      >
                        Add one first
                      </Text>
                      .
                    </Text>
                  )}
                </>
              )}

              {/* Iter 94 — Employee code / Department / Position inputs
                  removed: those fields now live in the one-page form above
                  so Add & Update share the exact same format. This sheet
                  keeps only admin-only controls (exit date, live-in, role). */}
              <Text style={styles.label}>Exit / Left date</Text>
              <View style={styles.exitRow}>
                <View style={{ flex: 1 }}>
                  <DateField
                    value={exitDate}
                    onChangeISO={setExitDate}
                    testID="exit-date-input"
                  />
                </View>
                {exitDate ? (
                  <Pressable
                    onPress={() => setExitDate("")}
                    style={styles.clearBtn}
                    testID="exit-date-clear"
                  >
                    <Ionicons name="close-circle" size={22} color={colors.onSurfaceTertiary} />
                  </Pressable>
                ) : null}
              </View>
              <Text style={styles.hint}>
                Setting a past or today&apos;s date will immediately block this
                employee from accessing the app.
              </Text>

              <Pressable
                testID="live-in-toggle"
                style={[styles.liveInRow, isLiveIn && styles.liveInRowOn]}
                onPress={() => setIsLiveIn((v) => !v)}
              >
                <View style={styles.liveInIcon}>
                  <Ionicons
                    name="home-outline"
                    size={16}
                    color={colors.brandPrimary}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.liveInTitle}>Live-in employee</Text>
                  <Text style={styles.liveInSub}>
                    Skips geofence for OUT punches and disables auto-punch.
                    Use for resort staff who sleep on-site.
                  </Text>
                </View>
                <View
                  style={[
                    styles.liveInBadge,
                    isLiveIn && styles.liveInBadgeOn,
                  ]}
                >
                  {isLiveIn ? (
                    <Ionicons name="checkmark" size={14} color="#fff" />
                  ) : null}
                </View>
              </Pressable>

              <Pressable style={styles.submit} onPress={save} disabled={saving}>
                {saving ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={styles.submitTxt}>Save</Text>
                )}
              </Pressable>
              <View style={{ height: 40 }} />
            </KeyboardAwareScrollView>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Iter 89 — Salary Update modal (Web only) */}
      {Platform.OS === "web" ? (
        <SalaryUpdateModal
          visible={!!salaryModalUser}
          userId={salaryModalUser}
          onClose={() => setSalaryModalUser(null)}
          onSaved={() => load()}
        />
      ) : null}
    </View>
  );
}

/** Small filter chip strip for Employee GROUP + On-roll / Off-roll.
 * Rendered above the employees list. Groups come from the employees'
 * assigned General Master Group (employee_type field). */
function EmployeeFilterChips({
  employees,
  typeFilter,
  onTypeChange,
  rollFilter,
  onRollChange,
}: {
  employees: any[];
  typeFilter: string | "all";
  onTypeChange: (v: string | "all") => void;
  rollFilter: "all" | "on" | "off";
  onRollChange: (v: "all" | "on" | "off") => void;
}) {
  const types = React.useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of employees) {
      const t = (e.employee_type || "").trim();
      if (t) counts[t] = (counts[t] || 0) + 1;
    }
    const arr = Object.entries(counts)
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
    return { arr };
  }, [employees]);

  if (employees.length === 0) return null;

  return (
    <View style={filterStyles.wrap} testID="employee-filters">
      <View style={filterStyles.row}>
        <Text style={filterStyles.label}>Group</Text>
        <View style={filterStyles.chipStrip}>
          <FilterChip
            label="All"
            active={typeFilter === "all"}
            onPress={() => onTypeChange("all")}
            testID="type-chip-all"
          />
          {types.arr.map((t) => (
            <FilterChip
              key={t.name}
              label={t.name}
              count={t.count}
              active={typeFilter.toLowerCase() === t.name.toLowerCase()}
              onPress={() => onTypeChange(t.name)}
              testID={`type-chip-${t.name.replace(/\W+/g, "_")}`}
            />
          ))}
        </View>
      </View>
      <View style={filterStyles.row}>
        <Text style={filterStyles.label}>Roll</Text>
        <View style={filterStyles.chipStrip}>
          {(["all", "on", "off"] as const).map((v) => (
            <FilterChip
              key={v}
              label={v === "all" ? "All" : v === "on" ? "On-roll" : "Off-roll"}
              active={rollFilter === v}
              onPress={() => onRollChange(v)}
              testID={`roll-chip-${v}`}
            />
          ))}
        </View>
      </View>
    </View>
  );
}

function FilterChip({
  label,
  count,
  active,
  onPress,
  testID,
}: {
  label: string;
  count?: number;
  active: boolean;
  onPress: () => void;
  testID?: string;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={[filterStyles.chip, active && filterStyles.chipActive]}
      testID={testID}
    >
      <Text style={[filterStyles.chipTxt, active && filterStyles.chipTxtActive]}>
        {label}
      </Text>
      {typeof count === "number" ? (
        <Text
          style={[
            filterStyles.chipCount,
            active && { color: "rgba(255,255,255,0.85)" },
          ]}
        >
          {count}
        </Text>
      ) : null}
    </Pressable>
  );
}

const filterStyles = StyleSheet.create({
  wrap: {
    marginTop: spacing.sm,
    marginBottom: spacing.sm,
    gap: 6,
  },
  row: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 6,
  },
  label: {
    fontSize: 10,
    color: colors.onSurfaceTertiary,
    fontWeight: "700",
    textTransform: "uppercase",
    marginTop: 6,
    width: 36,
    letterSpacing: 0.4,
  },
  chipStrip: {
    flex: 1,
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
  chipActive: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandPrimary,
  },
  chipTxt: {
    color: colors.onSurfaceSecondary,
    fontWeight: "600",
    fontSize: 12,
  },
  chipTxtActive: { color: "#fff" },
  chipCount: {
    fontSize: 10,
    color: colors.brandPrimary,
    fontWeight: "700",
    marginLeft: 2,
  },
});

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { fontSize: type.xl, color: colors.onSurface, fontWeight: "500" },
  scroll: { padding: spacing.xl },
  filterLabel: {
    color: colors.onSurfaceTertiary, fontSize: type.sm,
    marginBottom: spacing.sm, letterSpacing: 0.5,
  },
  // Iter 77 - Prominent active-firm hero card at top of Admin Panel
  firmHero: {
    marginBottom: spacing.md,
    padding: spacing.md,
    borderRadius: radius.lg,
    backgroundColor: colors.brand,
    borderWidth: 2,
    borderColor: colors.brand,
    gap: 8,
    ...shadow.cta,
  },
  firmHeroLabelRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  firmHeroLabel: {
    color: colors.onCta,
    fontWeight: "800",
    fontSize: type.sm,
    letterSpacing: 0.5,
    textTransform: "uppercase",
    flex: 1,
  },
  firmHeroLockPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    backgroundColor: "rgba(0,0,0,0.28)",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.pill,
  },
  firmHeroLockTxt: { color: "#fff", fontSize: 10, fontWeight: "700" },
  firmHeroPickerWrap: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: 4,
  },
  firmHeroHint: { color: colors.onCta, fontSize: 11, lineHeight: 16, opacity: 0.85 },
  filterRow: { flexDirection: "row", gap: 8, paddingRight: spacing.xl, marginBottom: spacing.lg },
  chip: {
    height: 36,
    paddingHorizontal: spacing.md,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceTertiary,
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  chipActive: { backgroundColor: colors.brandPrimary },
  chipTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm, fontWeight: "500" },
  chipTxtActive: { color: "#fff" },
  statsGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginBottom: spacing.lg },
  stat: {
    width: "47%", backgroundColor: colors.brandTertiary,
    borderRadius: radius.md, padding: spacing.lg,
  },
  statV: { color: colors.onBrandTertiary, fontSize: 28, fontWeight: "500" },
  statL: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 4 },
  actionTile: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.lg,
  },
  actionIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  actionTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  // Iter 83 — Section heading between quick-action groups
  sectionHeading: {
    fontSize: type.base,
    fontWeight: "800",
    color: colors.brand,
    marginTop: 8,
    marginBottom: 4,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  actionSub: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 2, lineHeight: 16 },
  sectionRow: {
    flexDirection: "row", alignItems: "center",
    justifyContent: "space-between", marginBottom: spacing.md,
  },
  section: { fontSize: type.lg, color: colors.onSurface, fontWeight: "500" },
  badge: {
    color: colors.cta,
    fontWeight: "800",
    fontSize: type.base,
  },
  pendingRow: {
    flexDirection: "row", alignItems: "flex-start", gap: spacing.md,
    backgroundColor: "#FFF9EC", borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: "#F1D9A0",
    marginBottom: spacing.sm,
  },
  avatarPending: { backgroundColor: colors.cta },
  decideRow: { flexDirection: "row", gap: 8, marginTop: 8 },
  decideBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.pill,
    minWidth: 92,
  },
  approveBtn: { backgroundColor: "#218739" },
  rejectBtn: {
    backgroundColor: "#FDECEC",
    borderWidth: 1,
    borderColor: "#F5C0C0",
  },
  decideTxt: { color: "#fff", fontSize: type.sm, fontWeight: "700" },
  link: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "500" },
  empty: { color: colors.onSurfaceTertiary, textAlign: "center", paddingVertical: spacing.xl },
  empRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surfaceSecondary, borderRadius: 16,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm,
    ...shadow.card,
  },
  avatar: {
    width: 42, height: 42, borderRadius: 21,
    backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  avatarTxt: { color: "#FFFFFF", fontSize: type.lg, fontWeight: "700" },
  empName: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  trashBtn: {
    padding: 8,
    borderRadius: 8,
    backgroundColor: "#FDECEC",
    marginRight: 6,
  },
  policyBtn: {
    padding: 8,
    borderRadius: 8,
    backgroundColor: colors.brandTertiary,
    marginRight: 6,
  },
  masterBtn: {
    padding: 8,
    borderRadius: 8,
    backgroundColor: colors.brandTertiary,
    marginRight: 6,
  },
  empMeta: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 2 },
  metaRow: {
    flexDirection: "row", alignItems: "center", gap: 8, marginTop: 6, flexWrap: "wrap",
  },
  roleChip: {
    backgroundColor: colors.brandTertiary, paddingHorizontal: 8, paddingVertical: 2,
    borderRadius: radius.pill,
  },
  roleTxt: {
    color: colors.onBrandTertiary, fontSize: 10, fontWeight: "500",
    textTransform: "capitalize", letterSpacing: 0.5,
  },
  salaryLine: { color: colors.accent, fontSize: type.sm, marginTop: 4, fontWeight: "600" },
  // Iter 89 — small pill button next to salary line (web only)
  salaryEditPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 999,
    backgroundColor: "#EEF2FF",
    borderWidth: 1, borderColor: "#C7D2FE",
  },
  salaryEditPillTxt: { color: colors.brandPrimary, fontSize: 10, fontWeight: "800" },
  bioLine: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    marginTop: 2,
    fontWeight: "500",
    letterSpacing: 0.3,
  },
  empHeadRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
  },
  codePill: {
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
  },
  // Iter 166 — employment status filter + resigned badge
  statusChipRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: 10,
    flexWrap: "wrap",
  },
  statusChip: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  statusChipOn: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  statusChipTxt: {
    fontSize: 11,
    fontWeight: "800",
    color: colors.onSurfaceSecondary,
    letterSpacing: 0.4,
  },
  statusChipTxtOn: { color: "#fff" },
  resignedPill: {
    backgroundColor: "#FEE2E2",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
  },
  resignedPillTxt: {
    fontSize: 10,
    fontWeight: "800",
    color: "#B91C1C",
  },
  codePillTxt: {
    color: colors.onBrandTertiary,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.4,
  },
  exitPill: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 4,
    backgroundColor: "#FDECEC",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.pill,
    marginTop: 6,
  },
  exitPillTxt: { color: "#8A1F1F", fontSize: 10, fontWeight: "700", letterSpacing: 0.3 },
  exitRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 6 },
  clearBtn: { padding: 4 },
  modalRoot: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.35)" },
  sheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24,
    padding: spacing.xl, maxHeight: "88%",
  },
  sheetGrip: {
    alignSelf: "center", width: 40, height: 4,
    borderRadius: 2, backgroundColor: colors.borderStrong, marginBottom: spacing.md,
  },
  sheetTitle: { fontSize: type.xl, color: colors.onSurface, fontWeight: "500" },
  // Iter 77 - Preview modal header
  previewRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  previewAvatar: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  previewAvatarTxt: { color: "#fff", fontWeight: "800", fontSize: 24 },
  previewMetaRow: { flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 2 },
  previewMeta: { color: colors.onSurfaceSecondary, fontSize: type.sm },
  // Iter 94 — primary "Edit All Details" button (same form as Add)
  editAllBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: radius.md,
    marginBottom: spacing.sm,
    backgroundColor: colors.brandPrimary,
  },
  editAllBtnTxt: {
    color: "#fff",
    fontWeight: "800",
    fontSize: type.sm,
    flex: 1,
  },
  masterLinkBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brand,
    marginBottom: spacing.md,
    backgroundColor: "rgba(31, 82, 84, 0.06)",
  },
  masterLinkTxt: {
    color: colors.brand,
    fontWeight: "700",
    fontSize: type.sm,
    flex: 1,
  },
  // Iter 77 - Employee search + sort toolbar
  empToolbar: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: spacing.sm,
    flexWrap: "wrap",
  },
  empSearchBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 999,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    backgroundColor: colors.surfaceSecondary,
    flex: 1,
    minWidth: 200,
    ...shadow.card,
  },
  empSearchInput: {
    flex: 1,
    color: colors.onSurface,
    fontSize: type.sm,
    ...Platform.select({ web: { outlineWidth: 0 as any } }),
  },
  sortRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  sortLabel: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginRight: 4 },
  sortChip: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  sortChipOn: {
    backgroundColor: colors.brand,
    borderColor: colors.brand,
  },
  sortChipTxt: { color: colors.onSurface, fontSize: 12, fontWeight: "600" },
  sortChipTxtOn: { color: colors.onBrandPrimary },
  // Iter 77 - Session-lock pill inside Company chip row
  lockPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.brand,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.pill,
    marginLeft: 4,
  },
  lockPillTxt: { color: "#fff", fontSize: 10, fontWeight: "700" },
  email: { fontSize: type.sm, color: colors.onSurfaceTertiary, marginTop: 2 },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: spacing.md },
  typeRow: { flexDirection: "row", gap: 8, marginTop: 6, flexWrap: "wrap" },
  typeChip: {
    paddingHorizontal: spacing.md, paddingVertical: 8,
    borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary,
  },
  typeChipActive: { backgroundColor: colors.brandPrimary },
  typeChipTxt: {
    color: colors.onSurfaceTertiary, fontSize: type.sm, textTransform: "capitalize",
  },
  typeChipTxtActive: { color: "#fff" },
  hint: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 6 },
  linkInline: { color: colors.brandPrimary, fontWeight: "500" },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, color: colors.onSurface, fontSize: type.base,
    marginTop: 6, backgroundColor: colors.surfaceSecondary,
  },
  submit: {
    marginTop: spacing.lg, backgroundColor: colors.cta,
    paddingVertical: 14, borderRadius: radius.pill, alignItems: "center",
  },
  submitTxt: { color: "#fff", fontSize: type.lg, fontWeight: "500" },
});
