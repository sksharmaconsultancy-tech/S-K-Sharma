/**
 * Bulk Employee Correction — Iter 60.
 *
 * One-click bulk edit for active employees of a firm. Super Admins and
 * Sub-Admins (with write perms) can update Designation, Salary, UAN,
 * ESI IP No., PF No., group membership and other master data across
 * multiple employees in a single POST.
 *
 * The screen renders a horizontal, spreadsheet-style grid. Only cells
 * the user actually edited are sent to the backend. Group changes are
 * cascaded to the ``masters.member_user_ids`` collection server-side.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  TextInput,
  ActivityIndicator,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useOnRefresh } from "@/src/context/RefreshBusContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };
type FieldDef = { key: string; label: string; type: string };
type GroupOption = { master_id: string; name: string; member_user_ids?: string[] };
type EmployeeRow = {
  user_id: string;
  employee_code?: string;
  name?: string;
  father_name?: string;
  phone?: string;
  email?: string;
  doj?: string;
  department?: string;
  designation?: string;
  salary_monthly?: number;
  basic_salary?: number;
  compliance_basic?: number | null;
  pf_basic?: number;
  compliance_salary_allowances?: { head?: string; amount?: number }[];
  hra?: number;
  conveyance?: number;
  over_time?: number;
  other?: number;
  uan_no?: string;
  esi_ip_no?: string;
  pf_no?: string;
  aadhaar_no?: string;
  name_as_per_aadhar?: string;
  pan_no?: string;
  name_as_per_pan?: string;
  bank_account?: string;
  bank_ifsc?: string;
  active?: boolean;
  resign_date?: string;
  employee_group_id?: string;
  company_id?: string;
  company_name?: string;
  // Iter 141 — Actual Salary correction mode
  bio_code?: string;
  pay_basis?: string;
  salary_structure_actual?: { head?: string; amount?: number; rate_type?: string; working_days?: number }[];
  attendance_policy_override?: { shift_id?: string } | null;
};

// Fields we want visible in the grid header order.
const COL_WIDTHS: Record<string, number> = {
  company_name: 160,
  employee_code: 100,
  name: 180,
  father_name: 160,
  phone: 130,
  email: 180,
  doj: 110,
  department: 130,
  designation: 150,
  employee_group_id: 160,
  compliance_basic: 140,
  pf_basic: 120,
  uan_no: 130,
  esi_ip_no: 130,
  pf_no: 130,
  aadhaar_no: 130,
  name_as_per_aadhar: 160,
  pan_no: 110,
  name_as_per_pan: 160,
  bank_account: 140,
  bank_ifsc: 110,
  bio_code: 100,
  actual_basic: 140,
  pay_basis: 120,
  shift_id: 150,
  salary_1: 110,
  day_1: 90,
  salary_2: 110,
  day_2: 90,
  salary_3: 110,
  day_3: 90,
};

// Iter 134 (user spec) — Only identity columns are locked. Statutory IDs,
// bank details, salary heads, department/designation/group are editable.
const LOCKED_FIELDS: Set<string> = new Set([
  "employee_code",
  "name",
  "father_name",
  "dob",
  "doj",
  "phone",
  "email",
]);

const normHead = (h: any): string =>
  String(h || "").toLowerCase().replace(/[^a-z0-9]/g, "");

/** Base (saved) value for an allowance column — reads the employee's
 *  compliance allowance lines first, then the flat XLSX-imported fields. */
function allowanceBase(row: EmployeeRow, head: string): string {
  const nh = normHead(head);
  const lines = row.compliance_salary_allowances || [];
  const hit = lines.find((l) => {
    const n = normHead(l?.head);
    return (
      n === nh ||
      (nh === "conv" && n.startsWith("conv")) ||
      (nh.startsWith("conv") && n === "conv")
    );
  });
  if (hit && hit.amount != null) return String(hit.amount);
  if (nh === "hra" && row.hra != null) return String(row.hra);
  if (nh.startsWith("conv") && row.conveyance != null) return String(row.conveyance);
  if ((nh === "overtime" || nh === "ot") && row.over_time != null) return String(row.over_time);
  if ((nh === "other" || nh === "others") && row.other != null) return String(row.other);
  return "";
}

function showMsg(msg: string, title = "Bulk Correction") {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

/** Iter 141 — saved (base) value for the Actual Salary derived columns,
 *  read from `salary_structure_actual` rows / the shift override. */
function actualBase(row: EmployeeRow, key: string): string {
  const srow = (head: string) =>
    (row.salary_structure_actual || []).find(
      (r) => String(r?.head || "").trim().toLowerCase() === head.toLowerCase(),
    );
  switch (key) {
    case "actual_basic": {
      const b = srow("Basic Salary");
      return b?.amount != null ? String(b.amount) : "";
    }
    case "pay_basis": {
      const b = srow("Basic Salary");
      return String(b?.rate_type || row.pay_basis || "");
    }
    case "shift_id":
      return String(row.attendance_policy_override?.shift_id || "");
    case "salary_1": case "salary_2": case "salary_3": {
      const t = srow(`Salary ${key.slice(-1)}`);
      return t?.amount != null ? String(t.amount) : "";
    }
    case "day_1": case "day_2": case "day_3": {
      const t = srow(`Salary ${key.slice(-1)}`);
      return t?.working_days != null ? String(t.working_days) : "";
    }
    default:
      return "";
  }
}

const ACTUAL_DERIVED_KEYS = new Set([
  "actual_basic", "pay_basis", "shift_id",
  "salary_1", "day_1", "salary_2", "day_2", "salary_3", "day_3",
]);

export default function BulkEmployeeCorrectionScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin" || user?.role === "sub_admin";

  const [companies, setCompanies] = useState<Company[]>([]);
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  const [companyId, setCompanyId] = useState<string>(globalCid || "");
  useEffect(() => {
    if (globalCid) setCompanyId(globalCid);
  }, [globalCid]);

  // Iter 63: cross-firm mode toggle. When enabled, employees are loaded
  // from every firm in `crossFirmSet` and edits can span multiple firms
  // in one Apply.
  // Iter 68 — Multi-firm mode disabled per user request.  These states
  // remain declared but are constants: single-firm workflow only.
  const crossFirmMode = false;
  const crossFirmSet = useMemo(() => new Set<string>(), []);

  const [fields, setFields] = useState<FieldDef[]>([]);
  // Iter 141 (user spec) — Compliance vs Actual Salary correction mode.
  const [mode, setMode] = useState<"compliance" | "actual">("compliance");
  const [actualEnabled, setActualEnabled] = useState(false);
  const [shiftOptions, setShiftOptions] = useState<{ shift_id: string; name: string }[]>([]);
  // Cross-firm groups: keyed by company_id -> options
  const [groupsByCid, setGroupsByCid] = useState<Record<string, GroupOption[]>>({});
  // Iter 68 — Same master-driven UX for Departments + Designations.
  const [deptsByCid, setDeptsByCid] = useState<Record<string, GroupOption[]>>({});
  const [designationsByCid, setDesignationsByCid] = useState<Record<string, GroupOption[]>>({});
  const [allRows, setAllRows] = useState<EmployeeRow[]>([]);
  // Iter 134 (user spec) — top filter: Active/Present vs Resigned.
  const [empFilter, setEmpFilter] = useState<"active" | "resigned">("active");
  // Iter 138 (user request) — filter the grid by Employee Group.
  const [groupFilter, setGroupFilter] = useState<string>("");
  const [dirty, setDirty] = useState<Record<string, Record<string, any>>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  // Iter 204 (user request) — search filter + sorting for the data table.
  const [searchQ, setSearchQ] = useState("");
  const [sortKey, setSortKey] = useState<string>("employee_code");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  useEffect(() => { setGroupFilter(""); setMode("compliance"); }, [companyId]);

  const isResigned = (e: EmployeeRow) =>
    e.active === false || !!(e.resign_date && String(e.resign_date).trim());
  const rows = useMemo(() => {
    const q = searchQ.trim().toLowerCase();
    const base = allRows
      .filter((e) => (empFilter === "resigned" ? isResigned(e) : !isResigned(e)))
      .filter((e) => {
        if (!groupFilter) return true;
        if (groupFilter === "__none__") return !e.employee_group_id;
        return e.employee_group_id === groupFilter;
      })
      .filter((e) => {
        if (!q) return true;
        return [
          e.name, (e as any).father_name, e.employee_code, (e as any).bio_code,
          (e as any).designation, (e as any).department, (e as any).company_name,
          (e as any).employee_group, (e as any).uan_no, (e as any).esic_no,
        ].some((v) => String(v ?? "").toLowerCase().includes(q));
      });
    const dir = sortDir === "asc" ? 1 : -1;
    const val = (e: any) => e?.[sortKey];
    return base.slice().sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      const na = parseFloat(String(va));
      const nb = parseFloat(String(vb));
      if (!Number.isNaN(na) && !Number.isNaN(nb)) return (na - nb) * dir;
      return String(va ?? "").localeCompare(String(vb ?? ""), "en", { sensitivity: "base" }) * dir;
    });
  }, [allRows, empFilter, groupFilter, searchQ, sortKey, sortDir]);
  const filterCounts = useMemo(() => {
    let a = 0, r = 0;
    for (const e of allRows) {
      if (isResigned(e)) r++;
      else a++;
    }
    return { active: a, resigned: r };
  }, [allRows]);

  // Legacy field kept for the single-firm group picker.
  const groups: GroupOption[] = useMemo(() => {
    if (crossFirmMode) return [];
    return groupsByCid[companyId] || [];
  }, [crossFirmMode, groupsByCid, companyId]);
  const depts: GroupOption[] = useMemo(
    () => (crossFirmMode ? [] : deptsByCid[companyId] || []),
    [crossFirmMode, deptsByCid, companyId],
  );
  const designations: GroupOption[] = useMemo(
    () => (crossFirmMode ? [] : designationsByCid[companyId] || []),
    [crossFirmMode, designationsByCid, companyId],
  );

  useEffect(() => {
    if (!isSuper) return;
    (async () => {
      try {
        const cs = await api<{ companies: Company[] }>("/companies");
        // Iter 68 — Alphabetical sorting for company + master lists.
        const cmp = (a: { name: string }, b: { name: string }) =>
          (a.name || "").localeCompare(b.name || "", "en", { sensitivity: "base" });
        setCompanies((cs.companies || []).slice().sort(cmp));
        if (cs.companies?.length && !companyId) setCompanyId(cs.companies[0].company_id);
      } catch (e: any) {
        showMsg(e?.message || "Could not load initial data");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSuper]);

  // Iter 134 — the column set depends on the firm (its enabled allowance
  // heads become editable columns), so refetch fields per firm.
  // Iter 141 — and per correction mode (compliance vs actual salary).
  useEffect(() => {
    if (!isSuper || !companyId) {
      setFields([]);
      return;
    }
    (async () => {
      try {
        const fs = await api<{ fields: FieldDef[]; actual_salary_enabled?: boolean }>(
          `/admin/employees/bulk-correction-fields?company_id=${encodeURIComponent(companyId)}&mode=${mode}`,
        );
        setFields(fs.fields || []);
        setActualEnabled(!!fs.actual_salary_enabled);
      } catch (e: any) {
        showMsg(e?.message || "Could not load field list");
      }
    })();
  }, [isSuper, companyId, mode]);

  // Iter 141 — Shift Master catalogue for the Shift dropdown (actual mode).
  useEffect(() => {
    if (!isSuper || mode !== "actual") return;
    (async () => {
      try {
        const r = await api<{ shifts: { shift_id: string; name: string }[] }>("/shift-masters");
        setShiftOptions(r.shifts || []);
      } catch {
        setShiftOptions([]);
      }
    })();
  }, [isSuper, mode]);

  const loadEmployees = useCallback(async () => {
    // Determine target firms.
    const targetCids: string[] = crossFirmMode
      ? Array.from(crossFirmSet)
      : companyId
        ? [companyId]
        : [];
    if (targetCids.length === 0) {
      setAllRows([]);
      setGroupsByCid({});
      return;
    }
    setLoading(true);
    setDirty({});
    try {
      // Fetch employees for every selected firm in parallel.
      const empQs = crossFirmMode
        ? "?" + targetCids.map((c) => `company_ids=${encodeURIComponent(c)}`).join("&")
        : `?company_id=${encodeURIComponent(companyId)}`;
      const emps = await api<{ employees: EmployeeRow[] }>(
        `/admin/employees${empQs}`,
      );
      // Load groups + departments + designations for every firm in parallel.
      const masterKinds: ("group" | "department" | "designation")[] = [
        "group",
        "department",
        "designation",
      ];
      const masterResults = await Promise.all(
        targetCids.flatMap((cid) =>
          masterKinds.map(async (kind) => {
            try {
              // Iter 139 (user report) — GROUPS are used across the WHOLE
              // master, so fetch them WITHOUT a firm filter (all firms +
              // globals) and dedupe by name preferring: this firm's own >
              // global > any other firm. Departments / Designations stay
              // firm-scoped.
              const qs =
                kind === "group"
                  ? `?type=${kind}`
                  : `?type=${kind}&company_id=${encodeURIComponent(cid)}`;
              const r = await api<{ items: (GroupOption & { company_id?: string })[] }>(
                `/admin/masters${qs}`,
              );
              let items = r.items || [];
              if (kind === "group") {
                const byName: Record<string, GroupOption & { company_id?: string }> = {};
                const rank = (g: { company_id?: string }) =>
                  g.company_id === cid ? 0 : g.company_id === "__global__" || !g.company_id ? 1 : 2;
                for (const g of items) {
                  const key = String(g.name || "").trim().toUpperCase();
                  if (!key) continue;
                  if (!(key in byName) || rank(g) < rank(byName[key])) byName[key] = g;
                }
                items = Object.values(byName);
              }
              return [cid, kind, items] as const;
            } catch {
              return [cid, kind, [] as GroupOption[]] as const;
            }
          }),
        ),
      );
      const gm: Record<string, GroupOption[]> = {};
      const dm: Record<string, GroupOption[]> = {};
      const desm: Record<string, GroupOption[]> = {};
      const abc = (arr: GroupOption[]) =>
        arr.slice().sort((a, b) =>
          (a.name || "").localeCompare(b.name || "", "en", { sensitivity: "base" }),
        );
      for (const [cid, kind, items] of masterResults) {
        if (kind === "group") gm[cid] = abc(items);
        else if (kind === "department") dm[cid] = abc(items);
        else if (kind === "designation") desm[cid] = abc(items);
      }
      setGroupsByCid(gm);
      setDeptsByCid(dm);
      setDesignationsByCid(desm);

      // Attach company_name to each row for display in cross-firm view.
      const cName = (cid?: string) =>
        companies.find((c) => c.company_id === cid)?.name || "—";
      // Iter 134 — derive each employee's CURRENT group from the group
      // masters' member lists (user: "please show who already exists"),
      // and fall back to the imported flat Basic when Compliance Basic
      // hasn't been set yet.
      const gidByUser: Record<string, string> = {};
      const gidByName: Record<string, Record<string, string>> = {};
      Object.entries(gm).forEach(([cid, list]) => {
        gidByName[cid] = gidByName[cid] || {};
        (list || []).forEach((g) => {
          gidByName[cid][String(g.name || "").trim().toUpperCase()] = g.master_id;
          (g.member_user_ids || []).forEach((uid) => {
            gidByUser[uid] = g.master_id;
          });
        });
      });
      const mapped = (emps.employees || []).map((e) => {
        const names = gidByName[e.company_id || companyId] || {};
        const byName =
          names[String((e as any).employee_group || (e as any).employee_type || "").trim().toUpperCase()] || "";
        return {
          ...e,
          company_name: cName(e.company_id),
          employee_group_id: e.employee_group_id || gidByUser[e.user_id] || byName,
          compliance_basic: e.compliance_basic ?? e.basic_salary ?? null,
        };
      });
      setAllRows(mapped);
    } catch (e: any) {
      showMsg(e?.message || "Could not load employees");
    } finally {
      setLoading(false);
    }
  }, [companyId, crossFirmMode, crossFirmSet, companies]);

  useEffect(() => {
    void loadEmployees();
  }, [loadEmployees]);
  useOnRefresh(loadEmployees);

  // Iter 68 — Refetch employees + groups whenever the user returns to the
  // screen (e.g. after adding a new Group in Masters), so the Group
  // dropdown always reflects the latest master data.
  useFocusEffect(
    useCallback(() => {
      void loadEmployees();
    }, [loadEmployees]),
  );

  // Fields shown in the grid. When in cross-firm mode we prepend a virtual
  // read-only "Firm" column so operators can tell rows apart.
  const displayFields: FieldDef[] = useMemo(() => {
    if (!crossFirmMode) return fields;
    return [
      { key: "company_name", label: "Firm", type: "text" },
      ...fields,
    ];
  }, [crossFirmMode, fields]);

  const setCell = (uid: string, key: string, value: any) => {
    setDirty((prev) => ({
      ...prev,
      [uid]: { ...(prev[uid] || {}), [key]: value },
    }));
  };

  const clearCell = (uid: string, key: string) => {
    setDirty((prev) => {
      if (!prev[uid]) return prev;
      const next = { ...prev[uid] };
      delete next[key];
      const nextAll = { ...prev, [uid]: next };
      if (Object.keys(next).length === 0) delete nextAll[uid];
      return nextAll;
    });
  };

  const dirtyCount = useMemo(() => {
    let total = 0;
    for (const uid of Object.keys(dirty)) total += Object.keys(dirty[uid]).length;
    return total;
  }, [dirty]);

  const displayValue = (row: EmployeeRow, key: string): string => {
    if (dirty[row.user_id] && key in dirty[row.user_id]) {
      return String(dirty[row.user_id][key] ?? "");
    }
    if (ACTUAL_DERIVED_KEYS.has(key)) return actualBase(row, key);
    const raw = (row as any)[key];
    if (raw === null || raw === undefined) return "";
    return String(raw);
  };

  /** Saved value used for "did the user actually change it?" checks. */
  const baseValue = (row: EmployeeRow, key: string): string => {
    if (ACTUAL_DERIVED_KEYS.has(key)) return actualBase(row, key);
    const raw = (row as any)[key];
    return raw === null || raw === undefined ? "" : String(raw);
  };

  const submit = async (dryRun: boolean) => {
    // Iter 134 — fold "allow:<HEAD>" cell edits into an `allowances`
    // {head: amount} map for the backend.
    const corrections = Object.entries(dirty).map(([uid, patch]) => {
      const out: any = { user_id: uid };
      const allowances: Record<string, number> = {};
      for (const [k, v] of Object.entries(patch)) {
        if (k.startsWith("allow:")) {
          const n = Number(v);
          if (Number.isFinite(n)) allowances[k.slice(6)] = n;
        } else {
          out[k] = v;
        }
      }
      if (Object.keys(allowances).length) out.allowances = allowances;
      return out;
    });
    if (corrections.length === 0) return showMsg("Nothing to save.");
    setSaving(true);
    try {
      const body: any = { corrections, dry_run: dryRun };
      if (crossFirmMode) {
        body.company_ids = Array.from(crossFirmSet);
      } else {
        body.company_id = companyId;
      }
      const r = await api<{
        applied_count: number;
        skipped_count: number;
        skipped: any[];
      }>("/admin/employees/bulk-correction", {
        method: "POST",
        body,
      });
      if (dryRun) {
        showMsg(
          `Preview: ${r.applied_count} would be updated, ${r.skipped_count} skipped.`,
        );
      } else {
        showMsg(
          `Applied ${r.applied_count} update${r.applied_count === 1 ? "" : "s"}. Skipped ${r.skipped_count}.`,
        );
        setDirty({});
        await loadEmployees();
      }
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!isSuper) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Only Super/Sub-admins can bulk correct employees.</Text>
        </View>
      </SafeAreaView>
    );
  }

  // Iter 138 (user request) — freeze Emp Code + Name on the left while
  // scrolling horizontally (web position:sticky).
  const FROZEN_LEFT: Record<string, number> = {
    employee_code: 0,
    name: COL_WIDTHS.employee_code || 100,
  };
  const frozenStyle = (key: string): any =>
    Platform.OS === "web" && key in FROZEN_LEFT
      ? ({ position: "sticky", left: FROZEN_LEFT[key], zIndex: 3 } as any)
      : null;

  const renderCell = (row: EmployeeRow, f: FieldDef) => {
    const w = COL_WIDTHS[f.key] || (f.type === "allowance" ? 110 : 120);
    const val = displayValue(row, f.key);
    const isDirty = dirty[row.user_id] ? f.key in dirty[row.user_id] : false;

    // Iter 85 — Bulk Employee Correction is intentionally limited to
    // Salary Data + Designation edits. Identity fields (Employee Code,
    // Name, Father Name, DOB, DOJ, Phone, Email, UAN, PF number, ESI IP
    // etc.) must be corrected on the Employee Master screen where the
    // audit trail lives — NOT via bulk edit.
    // Iter 141 — In ACTUAL mode Name / Father Name ARE editable (user
    // spec); only the Emp Code stays locked.
    // Iter 204 (user request) — Emp Code / Name / Father Name are locked in
    // BOTH Actual and Compliance modes (no editing/typing box).
    const lockedNow = LOCKED_FIELDS.has(f.key);
    if (lockedNow) {
      const raw = (row as any)[f.key];
      const display = raw === null || raw === undefined || raw === "" ? "—" : String(raw);
      return (
        <View style={[styles.cellWrap, { width: w }, styles.cellLocked, frozenStyle(f.key)]}>
          <Text style={styles.cellReadOnly} numberOfLines={1}>
            {display}
          </Text>
        </View>
      );
    }

    // Iter 63 — read-only company name column shown in cross-firm mode.
    if (f.key === "company_name") {
      return (
        <View style={[styles.cellWrap, { width: w }]}>
          <Text style={styles.cellReadOnly} numberOfLines={1}>
            {row.company_name || "—"}
          </Text>
        </View>
      );
    }

    if (f.type === "master:group") {
      // Iter 134 (user spec) — Employee Group is EDITABLE again: a real
      // dropdown listing the groups that already exist for the firm; the
      // employee's current group is pre-selected.
      const scopedGroups = crossFirmMode
        ? groupsByCid[row.company_id || ""] || []
        : groups;
      const currentGid =
        (dirty[row.user_id]?.employee_group_id as string | undefined) ??
        (row.employee_group_id as string | undefined) ??
        "";
      return (
        <View style={[styles.cellWrap, { width: w }, isDirty && styles.cellDirty]}>
          {Platform.OS === "web" ? (
            <select
              value={currentGid}
              onChange={(e) => {
                const v = (e.target as HTMLSelectElement).value;
                if (v === (row.employee_group_id || "")) clearCell(row.user_id, "employee_group_id");
                else setCell(row.user_id, "employee_group_id", v);
              }}
              style={styles.cellSelect as any}
            >
              <option value="">— (no group)</option>
              {scopedGroups.map((g) => (
                <option key={g.master_id} value={g.master_id}>
                  {g.name}
                </option>
              ))}
            </select>
          ) : (
            <Text style={styles.cellReadOnly} numberOfLines={1}>
              {scopedGroups.find((g) => g.master_id === currentGid)?.name || "— (no group)"}
            </Text>
          )}
        </View>
      );
    }

    // Iter 134 — per-head compliance allowance amount cells (HRA / Conv. /
    // Other / Overtime + every head enabled in the Firm Master).
    if (f.type === "allowance") {
      const head = f.key.slice(6);
      const base = allowanceBase(row, head);
      const cur =
        dirty[row.user_id] && f.key in dirty[row.user_id]
          ? String(dirty[row.user_id][f.key] ?? "")
          : base;
      return (
        <View style={[styles.cellWrap, { width: w }, isDirty && styles.cellDirty]}>
          <TextInput
            value={cur}
            onChangeText={(v) => {
              if (v === base) clearCell(row.user_id, f.key);
              else {
                const n = Number(v);
                setCell(row.user_id, f.key, Number.isFinite(n) ? n : v);
              }
            }}
            keyboardType="decimal-pad"
            style={styles.cellInput}
            placeholder="0"
            placeholderTextColor={colors.onSurfaceTertiary}
          />
        </View>
      );
    }

    // Iter 141 — Pay Basis (daily / monthly) + Shift dropdowns.
    if (f.type === "select:paybasis" || f.type === "select:shift") {
      const base = baseValue(row, f.key);
      const cur =
        dirty[row.user_id] && f.key in dirty[row.user_id]
          ? String(dirty[row.user_id][f.key] ?? "")
          : base;
      return (
        <View style={[styles.cellWrap, { width: w }, isDirty && styles.cellDirty]}>
          {Platform.OS === "web" ? (
            <select
              value={cur}
              onChange={(e) => {
                const v = (e.target as HTMLSelectElement).value;
                if (v === base) clearCell(row.user_id, f.key);
                else setCell(row.user_id, f.key, v);
              }}
              style={styles.cellSelect as any}
            >
              {f.type === "select:paybasis" ? (
                <>
                  <option value="">—</option>
                  <option value="daily">Daily</option>
                  <option value="monthly">Monthly</option>
                </>
              ) : (
                <>
                  <option value="">— (no shift)</option>
                  {shiftOptions.map((s) => (
                    <option key={s.shift_id} value={s.shift_id}>
                      {s.name}
                    </option>
                  ))}
                </>
              )}
            </select>
          ) : (
            <Text style={styles.cellReadOnly}>Web only</Text>
          )}
        </View>
      );
    }

    // Iter 68 — Departments + Designations sourced from Masters.  Value
    // stored on the employee is the *name* (backward compatible with
    // legacy free-text values), not the master_id.  A blank "—" entry
    // clears the assignment.  Uses <input list=…> for type-ahead filter.
    if (f.type === "master:department" || f.type === "master:designation") {
      const scopedOpts = f.type === "master:department"
        ? (crossFirmMode ? deptsByCid[row.company_id || ""] || [] : depts)
        : (crossFirmMode ? designationsByCid[row.company_id || ""] || [] : designations);
      const current =
        (dirty[row.user_id]?.[f.key] as string | undefined) ??
        ((row as any)[f.key] as string | undefined) ??
        "";
      const dlId = `dl-${f.key}-${row.user_id}`;
      return (
        <View style={[styles.cellWrap, { width: w }, isDirty && styles.cellDirty]}>
          {Platform.OS === "web" ? (
            <>
              <input
                list={dlId}
                value={current}
                placeholder="—"
                onChange={(e) => {
                  const v = (e.target as HTMLInputElement).value;
                  if (v === ((row as any)[f.key] ?? "")) clearCell(row.user_id, f.key);
                  else setCell(row.user_id, f.key, v);
                }}
                style={styles.cellSelect as any}
              />
              <datalist id={dlId}>
                {scopedOpts.map((g) => (
                  <option key={g.master_id} value={g.name} />
                ))}
              </datalist>
            </>
          ) : (
            <Text style={styles.cellReadOnly}>Web only</Text>
          )}
        </View>
      );
    }

    return (
      <View style={[styles.cellWrap, { width: w }, isDirty && styles.cellDirty]}>
        <TextInput
          value={val}
          onChangeText={(v) => {
            const orig = baseValue(row, f.key);
            if (v === orig) clearCell(row.user_id, f.key);
            else if (f.type === "number") {
              const n = Number(v);
              setCell(row.user_id, f.key, Number.isFinite(n) ? n : v);
            } else setCell(row.user_id, f.key, v);
          }}
          keyboardType={f.type === "number" ? "decimal-pad" : "default"}
          style={styles.cellInput}
          placeholder=""
          placeholderTextColor={colors.onSurfaceTertiary}
        />
      </View>
    );
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.h1}>Bulk Employee Correction</Text>
            <Text style={styles.hsub}>
              Edit multiple employees at once · Designation, Salary, UAN, ESI IP, PF, Group, more
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.card}>
          {/* Iter 68 — Single-firm mode only.  Multi-firm toggle removed
              per user request; firm name is highlighted at the top of the
              list instead. */}

          <Text style={styles.label}>Company (Firm)</Text>
          {Platform.OS === "web" ? (
            <select
              data-testid="bc-company"
              value={companyId}
              onChange={(e) => setCompanyId((e.target as HTMLSelectElement).value)}
              style={styles.selectStyle as any}
            >
              <option value="">— select —</option>
              {companies.map((c) => (
                <option key={c.company_id} value={c.company_id}>
                  {c.name}
                </option>
              ))}
            </select>
          ) : (
            <Text style={styles.smallHint}>Best used on desktop web.</Text>
          )}
        </View>

        {/* Highlighted firm-name banner */}
        {companyId ? (
          <View style={styles.firmBanner} testID="bc-firm-banner">
            <Pressable
              onPress={() => void loadEmployees()}
              style={styles.firmBannerRefresh}
              disabled={loading}
              testID="bc-firm-banner-refresh"
              hitSlop={8}
            >
              <Ionicons
                name="refresh"
                size={16}
                color="#ffffff"
              />
            </Pressable>
            <Text style={styles.firmBannerTitle}>
              {companies.find((c) => c.company_id === companyId)?.name || "Selected firm"}
            </Text>
            <Text style={styles.firmBannerSub}>
              Employee master · {rows.length}{" "}
              {empFilter === "resigned" ? "resigned" : "active"} employee{rows.length === 1 ? "" : "s"}
            </Text>
          </View>
        ) : null}

        {/* Iter 141 (user spec) — Compliance vs Actual Salary correction
            mode toggle. Actual mode only for offline-salary firms. */}
        {companyId && actualEnabled ? (
          <View style={styles.filterRow}>
            {([
              ["compliance", "Compliance Salary Correction"],
              ["actual", "Actual Salary Correction"],
            ] as const).map(([k, lbl]) => (
              <Pressable
                key={k}
                onPress={() => {
                  if (mode === k) return;
                  if (dirtyCount > 0) {
                    const ok =
                      Platform.OS === "web"
                        ? globalThis.confirm(
                            `Switch mode? ${dirtyCount} unsaved change${dirtyCount === 1 ? "" : "s"} will be discarded.`,
                          )
                        : true;
                    if (!ok) return;
                  }
                  setDirty({});
                  setMode(k);
                }}
                style={[styles.filterChip, mode === k && styles.filterChipOn]}
                testID={`bc-mode-${k}`}
              >
                <Ionicons
                  name={k === "compliance" ? "shield-checkmark-outline" : "cash-outline"}
                  size={13}
                  color={mode === k ? "#fff" : colors.onSurfaceSecondary}
                />
                <Text style={[styles.filterChipTxt, mode === k && styles.filterChipTxtOn]}>
                  {lbl}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}

        {/* Iter 134 (user spec) — Active/Present vs Resigned filter */}
        <View style={styles.filterRow}>
          {([
            ["active", `Active / Present (${filterCounts.active})`],
            ["resigned", `Resigned (${filterCounts.resigned})`],
          ] as const).map(([k, lbl]) => (
            <Pressable
              key={k}
              onPress={() => setEmpFilter(k)}
              style={[styles.filterChip, empFilter === k && styles.filterChipOn]}
              testID={`bc-filter-${k}`}
            >
              <Ionicons
                name={k === "active" ? "person-outline" : "exit-outline"}
                size={13}
                color={empFilter === k ? "#fff" : colors.onSurfaceSecondary}
              />
              <Text style={[styles.filterChipTxt, empFilter === k && styles.filterChipTxtOn]}>
                {lbl}
              </Text>
            </Pressable>
          ))}
          {/* Iter 138 (user request) — Employee Group filter */}
          {Platform.OS === "web" && groups.length > 0 ? (
            <select
              value={groupFilter}
              onChange={(e) => setGroupFilter((e.target as HTMLSelectElement).value)}
              style={{
                padding: "8px 12px",
                borderRadius: 999,
                border: `1px solid ${colors.borderStrong}`,
                background: colors.surface,
                color: colors.onSurface,
                fontSize: 12,
                fontWeight: 700,
              } as any}
              data-testid="bc-filter-group"
            >
              <option value="">All groups</option>
              <option value="__none__">— No group</option>
              {groups.map((g) => (
                <option key={g.master_id} value={g.master_id}>
                  {g.name}
                </option>
              ))}
            </select>
          ) : null}
          {/* Iter 204 (user request) — search + sorting */}
          <TextInput
            style={styles.searchInput}
            placeholder="Search name / code / designation…"
            placeholderTextColor="#94A3B8"
            value={searchQ}
            onChangeText={setSearchQ}
            testID="bc-search"
          />
          {Platform.OS === "web" ? (
            <select
              value={sortKey}
              onChange={(e) => setSortKey((e.target as HTMLSelectElement).value)}
              style={{
                padding: "8px 12px",
                borderRadius: 999,
                border: `1px solid ${colors.borderStrong}`,
                background: colors.surface,
                color: colors.onSurface,
                fontSize: 12,
                fontWeight: 700,
              } as any}
              data-testid="bc-sort-key"
            >
              <option value="employee_code">Sort: Emp Code</option>
              <option value="name">Sort: Name</option>
              <option value="designation">Sort: Designation</option>
              <option value="department">Sort: Department</option>
              <option value="company_name">Sort: Firm</option>
              <option value="compliance_basic">Sort: Basic Salary</option>
              <option value="doj">Sort: DOJ</option>
            </select>
          ) : null}
          <Pressable
            onPress={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}
            style={[styles.filterChip, styles.filterChipOn]}
            testID="bc-sort-dir"
          >
            <Ionicons
              name={sortDir === "asc" ? "arrow-up-outline" : "arrow-down-outline"}
              size={13}
              color="#fff"
            />
            <Text style={[styles.filterChipTxt, styles.filterChipTxtOn]}>
              {sortDir === "asc" ? "A→Z" : "Z→A"}
            </Text>
          </Pressable>
        </View>

        <View style={styles.actionsBar}>
          <View style={{ flex: 1 }}>
            <Text style={styles.stepTitle}>
              {loading
                ? "Loading…"
                : `${rows.length} ${empFilter === "resigned" ? "resigned" : "active"} employees`}
            </Text>
            <Text style={styles.smallHint}>
              {dirtyCount === 0
                ? "Edit cells directly. Modified cells will be highlighted."
                : `${dirtyCount} pending change${dirtyCount === 1 ? "" : "s"}`}
            </Text>
          </View>
          <Pressable
            onPress={() => submit(true)}
            disabled={saving || dirtyCount === 0}
            style={[styles.secondaryBtn, (saving || dirtyCount === 0) && { opacity: 0.5 }]}
            testID="bc-preview"
          >
            <Ionicons name="eye-outline" size={14} color={colors.brandPrimary} />
            <Text style={styles.secondaryBtnTxt}>Preview</Text>
          </Pressable>
          {/* Iter 85 — Reset button.  Discards every pending change in the
              grid without saving so admins can undo mis-edits with a
              single click. */}
          <Pressable
            onPress={() => {
              if (dirtyCount === 0) return;
              const ok =
                Platform.OS === "web"
                  ? globalThis.confirm(
                      `Reset ${dirtyCount} pending change${dirtyCount === 1 ? "" : "s"}? This cannot be undone.`,
                    )
                  : true;
              if (ok) setDirty({});
            }}
            disabled={saving || dirtyCount === 0}
            style={[styles.secondaryBtn, (saving || dirtyCount === 0) && { opacity: 0.5 }]}
            testID="bc-reset"
          >
            <Ionicons name="refresh-outline" size={14} color={colors.brandPrimary} />
            <Text style={styles.secondaryBtnTxt}>Reset</Text>
          </Pressable>
          <Pressable
            onPress={() => submit(false)}
            disabled={saving || dirtyCount === 0}
            style={[styles.primaryBtn, (saving || dirtyCount === 0) && { opacity: 0.5 }]}
            testID="bc-apply"
          >
            {saving ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="save-outline" size={16} color="#fff" />
                <Text style={styles.primaryBtnTxt}>
                  Save {dirtyCount > 0 ? `(${dirtyCount})` : ""}
                </Text>
              </>
            )}
          </Pressable>
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: 20 }} />
        ) : rows.length === 0 ? (
          <View style={styles.card}>
            <Text style={styles.smallHint}>
              No {empFilter === "resigned" ? "resigned" : "active"} employees found for this firm.
            </Text>
          </View>
        ) : (
          <View style={styles.card}>
            {/* Iter 138 (user request) — ONE both-axis scroll container on
                web so the header can freeze on top (sticky top) AND the
                Emp Code / Name columns freeze on the left (sticky left). */}
            {Platform.OS === "web" ? (
              <View style={{ overflow: "auto", maxHeight: 620 } as any}>
                <View style={{ minWidth: "max-content" } as any}>
                  <View
                    style={[
                      styles.gridHead,
                      { position: "sticky", top: 0, zIndex: 10 } as any,
                    ]}
                  >
                    {displayFields.map((f) => (
                      <View
                        key={f.key}
                        style={[
                          styles.headCell,
                          { width: COL_WIDTHS[f.key] || 120, backgroundColor: colors.surfaceTertiary },
                          frozenStyle(f.key),
                        ]}
                      >
                        <Text style={styles.headTxt} numberOfLines={1}>
                          {f.label}
                        </Text>
                      </View>
                    ))}
                  </View>
                  {rows.map((r) => (
                    <View key={r.user_id} style={styles.gridRow}>
                      {displayFields.map((f) => (
                        <React.Fragment key={f.key}>
                          {renderCell(r, f)}
                        </React.Fragment>
                      ))}
                    </View>
                  ))}
                </View>
              </View>
            ) : (
              <ScrollView horizontal>
                <View>
                  <View style={styles.gridHead}>
                    {displayFields.map((f) => (
                      <View
                        key={f.key}
                        style={[styles.headCell, { width: COL_WIDTHS[f.key] || 120 }]}
                      >
                        <Text style={styles.headTxt} numberOfLines={1}>
                          {f.label}
                        </Text>
                      </View>
                    ))}
                  </View>
                  {rows.map((r) => (
                    <View key={r.user_id} style={styles.gridRow}>
                      {displayFields.map((f) => (
                        <React.Fragment key={f.key}>
                          {renderCell(r, f)}
                        </React.Fragment>
                      ))}
                    </View>
                  ))}
                </View>
              </ScrollView>
            )}
          </View>
        )}

        {/* Iter 134 (user request) — bottom Save bar so admins can save
            right after finishing corrections without scrolling back up. */}
        {!loading && rows.length > 0 ? (
          <View style={styles.actionsBar}>
            <View style={{ flex: 1 }}>
              <Text style={styles.stepTitle}>
                {dirtyCount === 0
                  ? "No pending changes"
                  : `${dirtyCount} pending change${dirtyCount === 1 ? "" : "s"}`}
              </Text>
              <Text style={styles.smallHint}>Save your corrections when done.</Text>
            </View>
            <Pressable
              onPress={() => submit(true)}
              disabled={saving || dirtyCount === 0}
              style={[styles.secondaryBtn, (saving || dirtyCount === 0) && { opacity: 0.5 }]}
              testID="bc-preview-bottom"
            >
              <Ionicons name="eye-outline" size={14} color={colors.brandPrimary} />
              <Text style={styles.secondaryBtnTxt}>Preview</Text>
            </Pressable>
            <Pressable
              onPress={() => submit(false)}
              disabled={saving || dirtyCount === 0}
              style={[styles.primaryBtn, (saving || dirtyCount === 0) && { opacity: 0.5 }]}
              testID="bc-save-bottom"
            >
              {saving ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="save-outline" size={16} color="#fff" />
                  <Text style={styles.primaryBtnTxt}>
                    Save {dirtyCount > 0 ? `(${dirtyCount})` : ""}
                  </Text>
                </>
              )}
            </Pressable>
          </View>
        ) : null}

        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  header: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  h1: { color: colors.onSurface, fontSize: type.xl, fontWeight: "800" },
  hsub: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },
  scroll: { padding: spacing.lg, maxWidth: 1400, alignSelf: "center", width: "100%" },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: { marginTop: 8, color: colors.onSurfaceSecondary, textAlign: "center" },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  label: {
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    fontWeight: "800",
    marginBottom: 6,
    textTransform: "uppercase",
  },
  smallHint: { color: colors.onSurfaceSecondary, fontSize: 11 },
  stepTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800" },
  selectStyle: {
    padding: 10,
    borderRadius: 8,
    borderColor: colors.borderStrong,
    borderWidth: 1,
    fontSize: 14,
    width: "100%",
  },
  actionsBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: spacing.md,
    marginBottom: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 10,
    paddingHorizontal: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800" },
  secondaryBtn: {
    borderRadius: radius.md,
    paddingVertical: 10,
    paddingHorizontal: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  secondaryBtnTxt: { color: colors.brandPrimary, fontWeight: "800" },
  gridHead: {
    flexDirection: "row",
    backgroundColor: colors.surfaceTertiary,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderStrong,
  },
  headCell: {
    paddingHorizontal: 6,
    paddingVertical: 8,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.divider,
  },
  headTxt: { fontSize: 10, fontWeight: "800", color: colors.onSurfaceSecondary, textTransform: "uppercase" },
  gridRow: {
    flexDirection: "row",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  cellWrap: {
    paddingHorizontal: 4,
    paddingVertical: 3,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.divider,
    justifyContent: "center",
  },
  cellDirty: { backgroundColor: "#FFF7E0" },
  // Iter 85 — Locked cells (identity fields) get a subtle grey wash so
  // admins immediately see they're read-only in bulk correction mode.
  cellLocked: { backgroundColor: colors.surfaceTertiary },
  cellInput: {
    fontSize: 12,
    color: colors.onSurface,
    paddingHorizontal: 4,
    paddingVertical: 4,
  },
  cellSelect: {
    padding: 4,
    borderWidth: 0,
    backgroundColor: "transparent",
    fontSize: 12,
  },
  cellReadOnly: { fontSize: 12, color: colors.onSurfaceSecondary },
  // Iter 134 — Active/Resigned filter chips.
  filterRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: spacing.md,
  },
  filterChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
  filterChipOn: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  filterChipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  filterChipTxtOn: { color: "#fff" },
  searchInput: {
    borderWidth: 1, borderColor: colors.borderStrong, borderRadius: 999,
    paddingHorizontal: 14, paddingVertical: 8, fontSize: 12.5,
    color: colors.onSurface, backgroundColor: colors.surface, minWidth: 220,
  },
  crossToggleRow: {
    flexDirection: "row",
    marginBottom: 8,
    flexWrap: "wrap",
    alignItems: "center",
  },
  crossToggle: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 4,
  },
  crossToggleTxt: {
    color: colors.onSurface,
    fontSize: 12,
    fontWeight: "700",
  },

  // Iter 68 — Centered, highlighted firm-name banner shown above the
  // employee grid (replaces the redundant "Firm" column).
  firmBanner: {
    backgroundColor: "#0EA5E9",
    borderRadius: radius.md,
    paddingVertical: 20,
    paddingHorizontal: 24,
    marginBottom: 12,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#0EA5E9",
    shadowOpacity: 0.28,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    position: "relative",
  },
  firmBannerRefresh: {
    position: "absolute",
    top: 12,
    right: 12,
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: "rgba(255,255,255,0.18)",
    alignItems: "center",
    justifyContent: "center",
  },
  firmBannerTitle: {
    color: "#ffffff",
    fontSize: 24,
    fontWeight: "800",
    letterSpacing: -0.4,
    textAlign: "center",
  },
  firmBannerSub: {
    color: "rgba(255,255,255,0.85)",
    fontSize: 13,
    fontWeight: "600",
    marginTop: 4,
    textAlign: "center",
    letterSpacing: 0.3,
  },
});
