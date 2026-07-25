/**
 * Bulk Operations — Iter 202.
 *
 * Super/Sub Admin tools that act on MANY employees at once:
 *   • Attendance Upload  — Excel template (status grid P/A/HD or In-Out
 *     times) → preview → apply (creates approved punches).
 *   • Salary Revision    — select employees + % / flat amount, or Excel
 *     upload with new amounts (Actual and/or Compliance).
 *   • Transfer           — move employees to another firm.
 *   • Resignation        — set exit date for many employees.
 *   • Shift Assignment   — assign a Shift Master to many employees.
 *   • History            — audit log of every bulk action.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  TextInput,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import MonthPicker from "@/src/components/MonthPicker";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius } from "@/src/theme";

type Tab = "attendance" | "salary" | "transfer" | "resign" | "shift" | "history";

type Emp = {
  user_id: string;
  employee_code?: string;
  name?: string;
  designation?: string;
  contractor_name?: string;
  exit_date?: string | null;
  shift_name?: string | null;
  actual_basic?: number;
  compliance_gross?: number;
};

const TABS: { key: Tab; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: "attendance", label: "Attendance Upload", icon: "cloud-upload-outline" },
  { key: "salary", label: "Salary Revision", icon: "trending-up-outline" },
  { key: "transfer", label: "Transfer", icon: "swap-horizontal-outline" },
  { key: "resign", label: "Resignation", icon: "exit-outline" },
  { key: "shift", label: "Shift Assign", icon: "time-outline" },
  { key: "history", label: "History", icon: "list-outline" },
];

function b64Download(filename: string, b64: string) {
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  const blob = new Blob([arr], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

function fileToB64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const bytes = new Uint8Array(reader.result as ArrayBuffer);
      let bin = "";
      const CHUNK = 0x8000;
      for (let i = 0; i < bytes.length; i += CHUNK) {
        bin += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
      }
      resolve(btoa(bin));
    };
    reader.onerror = reject;
    reader.readAsArrayBuffer(file);
  });
}

// ---------------------------------------------------------------------------
// Shared employee multi-select list
// ---------------------------------------------------------------------------
function EmployeePicker({
  emps,
  selected,
  onToggle,
  onSetAll,
}: {
  emps: Emp[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onSetAll: (ids: string[]) => void;
}) {
  const [q, setQ] = useState("");
  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return emps;
    return emps.filter(
      (e) =>
        (e.name || "").toLowerCase().includes(s) ||
        String(e.employee_code || "").toLowerCase().includes(s) ||
        (e.contractor_name || "").toLowerCase().includes(s),
    );
  }, [emps, q]);
  return (
    <View style={st.pickerWrap}>
      <View style={st.pickerHead}>
        <TextInput
          style={st.search}
          placeholder="Search name / code / contractor…"
          placeholderTextColor="#94A3B8"
          value={q}
          onChangeText={setQ}
        />
        <Pressable
          style={st.smallBtn}
          onPress={() => onSetAll(filtered.map((e) => e.user_id))}
        >
          <Text style={st.smallBtnTxt}>Select all ({filtered.length})</Text>
        </Pressable>
        <Pressable style={st.smallBtn} onPress={() => onSetAll([])}>
          <Text style={st.smallBtnTxt}>Clear</Text>
        </Pressable>
      </View>
      <ScrollView style={st.pickerList} nestedScrollEnabled>
        {filtered.map((e) => {
          const on = selected.has(e.user_id);
          return (
            <Pressable
              key={e.user_id}
              style={[st.empRow, on && st.empRowOn]}
              onPress={() => onToggle(e.user_id)}
            >
              <Ionicons
                name={on ? "checkbox" : "square-outline"}
                size={18}
                color={on ? colors.brandPrimary : "#94A3B8"}
              />
              <Text style={st.empCode}>{e.employee_code || "—"}</Text>
              <Text style={st.empName} numberOfLines={1}>
                {e.name}
                {e.exit_date ? "  (exited)" : ""}
              </Text>
              <Text style={st.empMeta} numberOfLines={1}>
                {e.designation || ""}
              </Text>
              <Text style={st.empSal}>
                ₹{(e.actual_basic || 0).toLocaleString("en-IN")}
              </Text>
            </Pressable>
          );
        })}
        {filtered.length === 0 ? (
          <Text style={st.hint}>No employees match.</Text>
        ) : null}
      </ScrollView>
      <Text style={st.hint}>
        {selected.size} selected of {emps.length}
      </Text>
    </View>
  );
}

function Chip({
  label,
  on,
  onPress,
}: {
  label: string;
  on: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable style={[st.chip, on && st.chipOn]} onPress={onPress}>
      <Text style={[st.chipTxt, on && st.chipTxtOn]}>{label}</Text>
    </Pressable>
  );
}

export default function BulkOperationsScreen() {
  const { user, loading } = useAuth();
  const { selectedCompanyId, companies } = useSelectedCompany();
  const [tab, setTab] = useState<Tab>("attendance");
  const [emps, setEmps] = useState<Emp[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // --- attendance tab state
  const [attKind, setAttKind] = useState<"status" | "inout">("status");
  const [attMonth, setAttMonth] = useState<string>(() =>
    new Date().toISOString().slice(0, 7),
  );
  const [attPreview, setAttPreview] = useState<any>(null);
  const [attOverwrite, setAttOverwrite] = useState(false);

  // --- salary tab state
  const [salMode, setSalMode] = useState<"select" | "excel">("select");
  const [salTarget, setSalTarget] = useState<"actual" | "compliance" | "both">("actual");
  const [salKind, setSalKind] = useState<"percent" | "flat">("percent");
  const [salValue, setSalValue] = useState("");
  const [salMonth, setSalMonth] = useState("");
  const [salNote, setSalNote] = useState("");
  const [salPreview, setSalPreview] = useState<any>(null);

  // --- transfer / resign / shift state
  const [destCompany, setDestCompany] = useState("");
  const [transferDate, setTransferDate] = useState("");
  const [transferNote, setTransferNote] = useState("");
  // Iter 291 (user request) — Transfer redesign: pick OLD firm → employee
  // list (Active/Resigned filter) → NEW firm; only RESIGNED employees can
  // move; plus a GLOBAL search by Aadhaar / PAN / Mobile / ESI / UAN.
  const [trMode, setTrMode] = useState<"firm" | "search">("firm");
  const [srcCompany, setSrcCompany] = useState("");
  const [srcEmps, setSrcEmps] = useState<any[]>([]);
  const [srcFilter, setSrcFilter] = useState<"all" | "active" | "resigned">("all");
  const [trSel, setTrSel] = useState<Set<string>>(new Set());
  const [trSearchQ, setTrSearchQ] = useState("");
  const [trResults, setTrResults] = useState<any[]>([]);
  const [trPicked, setTrPicked] = useState<any | null>(null);
  const [exitDate, setExitDate] = useState("");
  const [exitReason, setExitReason] = useState("");
  const [shifts, setShifts] = useState<any[]>([]);
  const [shiftId, setShiftId] = useState("");

  // --- history
  const [history, setHistory] = useState<any[]>([]);

  const cid = selectedCompanyId || "";

  const loadEmps = useCallback(async () => {
    if (!cid) return;
    try {
      const r = await api<{ rows: Emp[] }>(
        `/admin/bulk-ops/employees?company_id=${encodeURIComponent(cid)}`,
      );
      setEmps(r.rows || []);
    } catch (e: any) {
      setMsg({ kind: "err", text: e?.message || "Failed to load employees" });
    }
  }, [cid]);

  useEffect(() => {
    setSelected(new Set());
    setAttPreview(null);
    setSalPreview(null);
    loadEmps();
  }, [cid, loadEmps]);

  useEffect(() => {
    if (tab === "shift" && cid) {
      // Iter 279 — offer ONLY the shifts assigned to this firm from the
      // Shift Master (company-wise selection); fallback: full master list.
      (async () => {
        try {
          const r = await api<{ shifts: any[] }>(`/companies/${cid}/assigned-shifts`);
          if ((r.shifts || []).length) {
            setShifts(r.shifts);
            setShiftId("");
            return;
          }
        } catch { /* fall through to full master list */ }
        try {
          const r = await api<any>("/shift-masters");
          setShifts(Array.isArray(r) ? r : r.shifts || r.rows || []);
          setShiftId("");
        } catch { /* ignore */ }
      })();
    }
    if (tab === "history") {
      api<{ rows: any[] }>(
        `/admin/bulk-ops/history${cid ? `?company_id=${encodeURIComponent(cid)}` : ""}`,
      )
        .then((r) => setHistory(r.rows || []))
        .catch(() => {});
    }
  }, [tab, cid]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const setAll = (ids: string[]) => setSelected(new Set(ids));

  const guardFirm = (): boolean => {
    if (!cid) {
      setMsg({ kind: "err", text: "Select a firm from the top bar first." });
      return false;
    }
    return true;
  };

  const run = async (fn: () => Promise<void>) => {
    setMsg(null);
    setBusy(true);
    try {
      await fn();
    } catch (e: any) {
      setMsg({ kind: "err", text: e?.message || "Operation failed" });
    } finally {
      setBusy(false);
    }
  };

  // ------------------------- attendance handlers -------------------------
  const downloadAttTemplate = () =>
    run(async () => {
      if (!guardFirm()) return;
      const r = await api<any>(
        `/admin/bulk-ops/attendance-template?company_id=${cid}&month=${attMonth}&kind=${attKind}`,
      );
      b64Download(r.filename, r.file_base64);
    });

  const onAttFile = (f: File) =>
    run(async () => {
      if (!guardFirm()) return;
      const b64 = await fileToB64(f);
      const r = await api<any>("/admin/bulk-ops/attendance-preview", {
        method: "POST",
        body: { company_id: cid, month: attMonth, kind: attKind, file_base64: b64 },
      });
      setAttPreview(r);
    });

  const applyAttendance = () =>
    run(async () => {
      if (!attPreview) return;
      const rows = (attPreview.rows || []).filter((r: any) => r.status === "matched");
      const r = await api<any>("/admin/bulk-ops/attendance-apply", {
        method: "POST",
        body: {
          company_id: cid,
          month: attMonth,
          kind: attKind,
          overwrite: attOverwrite,
          rows,
        },
      });
      setAttPreview(null);
      setMsg({
        kind: "ok",
        text: `Applied — ${r.created} punches created, ${r.skipped} skipped (already had punches).`,
      });
    });

  // ------------------------- salary handlers -------------------------
  const applySalarySelect = () =>
    run(async () => {
      if (!guardFirm()) return;
      if (selected.size === 0) {
        setMsg({ kind: "err", text: "Select at least one employee." });
        return;
      }
      const v = parseFloat(salValue);
      if (!v) {
        setMsg({ kind: "err", text: "Enter a non-zero revision value." });
        return;
      }
      const r = await api<any>("/admin/bulk-ops/salary-revision", {
        method: "POST",
        body: {
          company_id: cid,
          user_ids: Array.from(selected),
          mode: salKind,
          target: salTarget,
          value: v,
          effective_month: salMonth,
          note: salNote,
        },
      });
      setSelected(new Set());
      loadEmps();
      setMsg({ kind: "ok", text: `Salary revised for ${r.changed} employees.` });
    });

  const downloadSalTemplate = () =>
    run(async () => {
      if (!guardFirm()) return;
      const r = await api<any>(`/admin/bulk-ops/salary-template?company_id=${cid}`);
      b64Download(r.filename, r.file_base64);
    });

  const onSalFile = (f: File) =>
    run(async () => {
      if (!guardFirm()) return;
      const b64 = await fileToB64(f);
      const r = await api<any>("/admin/bulk-ops/salary-preview", {
        method: "POST",
        body: { company_id: cid, file_base64: b64 },
      });
      setSalPreview(r);
    });

  const applySalaryExcel = () =>
    run(async () => {
      if (!salPreview) return;
      const rows = (salPreview.rows || []).filter((r: any) => r.status === "matched");
      const r = await api<any>("/admin/bulk-ops/salary-apply-excel", {
        method: "POST",
        body: { company_id: cid, rows, effective_month: salMonth, note: salNote },
      });
      setSalPreview(null);
      loadEmps();
      setMsg({ kind: "ok", text: `Salary updated for ${r.changed} employees.` });
    });

  // ------------------------- transfer / resign / shift -------------------------
  // Iter 291 — load the OLD firm's employees for the transfer picker.
  useEffect(() => {
    if (!srcCompany) { setSrcEmps([]); setTrSel(new Set()); return; }
    (async () => {
      try {
        const r = await api<{ rows: any[] }>(
          `/admin/bulk-ops/employees?company_id=${encodeURIComponent(srcCompany)}`);
        setSrcEmps(r.rows || []);
        setTrSel(new Set());
      } catch (e: any) {
        setMsg({ kind: "err", text: e?.message || "Failed to load employees" });
      }
    })();
  }, [srcCompany]);

  const toggleTransferEmp = (e: any) => {
    if (!e.is_resigned) {
      setMsg({
        kind: "err",
        text: `${e.name} is ACTIVE — only RESIGNED employees can be transferred. Set their exit date first (Resignation tab).`,
      });
      return;
    }
    setMsg(null);
    setTrSel((prev) => {
      const n = new Set(prev);
      if (n.has(e.user_id)) n.delete(e.user_id); else n.add(e.user_id);
      return n;
    });
  };

  const searchEmployees = () =>
    run(async () => {
      if (trSearchQ.trim().length < 3) {
        setMsg({ kind: "err", text: "Type at least 3 characters (Aadhaar / PAN / Mobile / ESI / UAN / name)." });
        return;
      }
      setTrPicked(null);
      const r = await api<{ rows: any[] }>(
        `/admin/bulk-ops/employee-search?q=${encodeURIComponent(trSearchQ.trim())}`);
      setTrResults(r.rows || []);
      if ((r.rows || []).length === 0) setMsg({ kind: "err", text: "No employee matched." });
    });

  const applyTransfer = () =>
    run(async () => {
      const fromCid = trMode === "firm" ? srcCompany : trPicked?.company_id;
      const ids = trMode === "firm" ? Array.from(trSel) : trPicked ? [trPicked.user_id] : [];
      if (!fromCid || ids.length === 0 || !destCompany) {
        setMsg({ kind: "err", text: "Pick the old firm, employee(s) and the new firm." });
        return;
      }
      if (destCompany === fromCid) {
        setMsg({ kind: "err", text: "New firm must be different from the old firm." });
        return;
      }
      const r = await api<any>("/admin/bulk-ops/transfer", {
        method: "POST",
        body: {
          company_id: fromCid,
          to_company_id: destCompany,
          user_ids: ids,
          effective_date: transferDate,
          note: transferNote,
        },
      });
      setTrSel(new Set());
      setTrPicked(null);
      setTrResults([]);
      if (srcCompany) {
        const rr = await api<{ rows: any[] }>(
          `/admin/bulk-ops/employees?company_id=${encodeURIComponent(srcCompany)}`).catch(() => null);
        if (rr) setSrcEmps(rr.rows || []);
      }
      const codes = (r.transfers || [])
        .map((t: any) => `${t.name}: #${t.old_code} → #${t.new_code}`).join(", ");
      const blockedTxt = (r.blocked || []).length
        ? ` Blocked (active): ${r.blocked.join(", ")}.` : "";
      setMsg({
        kind: "ok",
        text: `${r.moved} employee(s) joined ${r.to_company_name} with new code(s) — ${codes}.${blockedTxt}`,
      });
    });

  const applyResign = () =>
    run(async () => {
      if (!guardFirm()) return;
      if (selected.size === 0 || !/^\d{4}-\d{2}-\d{2}$/.test(exitDate)) {
        setMsg({ kind: "err", text: "Select employees and enter exit date as YYYY-MM-DD." });
        return;
      }
      const r = await api<any>("/admin/bulk-ops/resignation", {
        method: "POST",
        body: {
          company_id: cid,
          user_ids: Array.from(selected),
          exit_date: exitDate,
          reason: exitReason,
        },
      });
      setSelected(new Set());
      loadEmps();
      setMsg({ kind: "ok", text: `Exit date set for ${r.updated} employees.` });
    });

  const applyShift = () =>
    run(async () => {
      if (!guardFirm()) return;
      if (selected.size === 0 || !shiftId) {
        setMsg({ kind: "err", text: "Select employees and a shift." });
        return;
      }
      const r = await api<any>("/admin/bulk-ops/shift-assign", {
        method: "POST",
        body: { company_id: cid, user_ids: Array.from(selected), shift_id: shiftId },
      });
      setSelected(new Set());
      loadEmps();
      setMsg({ kind: "ok", text: `Shift '${r.shift_name}' assigned to ${r.updated} employees.` });
    });

  if (loading) return null;
  const role = user?.role as string;
  if (!user || !["super_admin", "sub_admin"].includes(role)) {
    return <Redirect href="/" />;
  }

  const needsPicker = ["salary", "resign", "shift"].includes(tab)
    && !(tab === "salary" && salMode === "excel");

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={st.wrap}>
        <Text style={st.title}>Bulk Operations</Text>
        <Text style={st.subtitle}>
          Attendance upload, salary revision, transfers, resignations & shift
          assignment for many employees at once. Firm:{" "}
          <Text style={{ fontWeight: "700" }}>
            {companies.find((c: any) => c.company_id === cid)?.name || "— select from top bar —"}
          </Text>
        </Text>

        <View style={st.tabs}>
          {TABS.map((t) => (
            <Pressable
              key={t.key}
              style={[st.tabBtn, tab === t.key && st.tabBtnOn]}
              onPress={() => {
                setTab(t.key);
                setMsg(null);
              }}
            >
              <Ionicons
                name={t.icon}
                size={15}
                color={tab === t.key ? "#fff" : colors.brandPrimary}
              />
              <Text style={[st.tabTxt, tab === t.key && st.tabTxtOn]}>{t.label}</Text>
            </Pressable>
          ))}
        </View>

        {msg ? (
          <View style={[st.banner, msg.kind === "ok" ? st.bannerOk : st.bannerErr]}>
            <Ionicons
              name={msg.kind === "ok" ? "checkmark-circle" : "alert-circle"}
              size={16}
              color={msg.kind === "ok" ? "#059669" : "#DC2626"}
            />
            <Text style={[st.bannerTxt, { color: msg.kind === "ok" ? "#065F46" : "#991B1B" }]}>
              {msg.text}
            </Text>
          </View>
        ) : null}

        {/* ------------------- ATTENDANCE ------------------- */}
        {tab === "attendance" ? (
          <View style={st.card}>
            <Text style={st.section}>1 · Choose format & month</Text>
            <View style={st.rowWrap}>
              <Chip label="Status Grid (P / HD / A)" on={attKind === "status"} onPress={() => setAttKind("status")} />
              <Chip label="In / Out Times" on={attKind === "inout"} onPress={() => setAttKind("inout")} />
              <MonthPicker value={attMonth} onChange={setAttMonth} />
            </View>
            <Text style={st.hint}>
              Status codes: P (Present) &amp; HD (Half Day) create punches from the
              employee&apos;s shift timing; A / WO / H / L are skipped (policy handles them).
            </Text>
            <Pressable style={st.secondaryBtn} onPress={downloadAttTemplate} disabled={busy}>
              <Ionicons name="download-outline" size={16} color={colors.brandPrimary} />
              <Text style={st.secondaryBtnTxt}>Download template (Excel)</Text>
            </Pressable>

            <Text style={st.section}>2 · Upload the filled file</Text>
            {Platform.OS === "web" ? (
              <input
                type="file"
                accept=".xlsx,.xls"
                onChange={(e) => {
                  const f = (e.target as HTMLInputElement).files?.[0];
                  if (f) onAttFile(f);
                  (e.target as HTMLInputElement).value = "";
                }}
                style={{ padding: 8, borderRadius: 6, border: "1px solid #E2E8F0", width: "100%" } as any}
              />
            ) : (
              <Text style={st.hint}>Use the web portal to upload Excel files.</Text>
            )}

            {attPreview ? (
              <>
                <Text style={st.section}>3 · Preview & apply</Text>
                <Text style={st.hint}>
                  {attPreview.summary.matched} matched · {attPreview.summary.errors} errors ·{" "}
                  {attPreview.summary.punch_days} day-entries will create punches.
                </Text>
                {(attPreview.rows || [])
                  .filter((r: any) => r.status === "error")
                  .slice(0, 8)
                  .map((r: any, i: number) => (
                    <Text key={i} style={st.errLine}>
                      ✗ {r.employee_code || r.name}: {r.error}
                    </Text>
                  ))}
                <Pressable style={st.rowWrap} onPress={() => setAttOverwrite((v) => !v)}>
                  <Ionicons
                    name={attOverwrite ? "checkbox" : "square-outline"}
                    size={18}
                    color={attOverwrite ? colors.brandPrimary : "#94A3B8"}
                  />
                  <Text style={st.hint}>
                    Overwrite — delete existing punches on uploaded days before inserting
                  </Text>
                </Pressable>
                <Pressable style={st.primaryBtn} onPress={applyAttendance} disabled={busy}>
                  {busy ? <ActivityIndicator color="#fff" size="small" /> : (
                    <Text style={st.primaryBtnTxt}>
                      Apply to {attPreview.summary.matched} employees
                    </Text>
                  )}
                </Pressable>
              </>
            ) : null}
          </View>
        ) : null}

        {/* ------------------- SALARY ------------------- */}
        {tab === "salary" ? (
          <View style={st.card}>
            <View style={st.rowWrap}>
              <Chip label="Select & Apply" on={salMode === "select"} onPress={() => setSalMode("select")} />
              <Chip label="Excel Upload" on={salMode === "excel"} onPress={() => setSalMode("excel")} />
            </View>
            {salMode === "select" ? (
              <>
                <Text style={st.section}>Revision</Text>
                <View style={st.rowWrap}>
                  <Chip label="% Increase" on={salKind === "percent"} onPress={() => setSalKind("percent")} />
                  <Chip label="Flat Amount (₹)" on={salKind === "flat"} onPress={() => setSalKind("flat")} />
                  <TextInput
                    style={st.input}
                    placeholder={salKind === "percent" ? "e.g. 10 (%)" : "e.g. 1500 (₹)"}
                    placeholderTextColor="#94A3B8"
                    keyboardType="numeric"
                    value={salValue}
                    onChangeText={setSalValue}
                  />
                </View>
                <View style={st.rowWrap}>
                  <Chip label="Actual Salary" on={salTarget === "actual"} onPress={() => setSalTarget("actual")} />
                  <Chip label="Compliance Salary" on={salTarget === "compliance"} onPress={() => setSalTarget("compliance")} />
                  <Chip label="Both" on={salTarget === "both"} onPress={() => setSalTarget("both")} />
                </View>
                <View style={st.rowWrap}>
                  <Text style={st.lbl}>Effective month</Text>
                  <MonthPicker value={salMonth} onChange={setSalMonth} allowEmpty emptyLabel="Pick month" />
                  <TextInput
                    style={[st.input, { flex: 1 }]}
                    placeholder="Note (optional)"
                    placeholderTextColor="#94A3B8"
                    value={salNote}
                    onChangeText={setSalNote}
                  />
                </View>
                <Text style={st.hint}>
                  % increase scales ALL actual salary heads proportionally; flat
                  amount adds to the Basic head. Compliance revises the monthly gross.
                </Text>
                <Pressable style={st.primaryBtn} onPress={applySalarySelect} disabled={busy}>
                  {busy ? <ActivityIndicator color="#fff" size="small" /> : (
                    <Text style={st.primaryBtnTxt}>Revise {selected.size} employees</Text>
                  )}
                </Pressable>
              </>
            ) : (
              <>
                <Pressable style={st.secondaryBtn} onPress={downloadSalTemplate} disabled={busy}>
                  <Ionicons name="download-outline" size={16} color={colors.brandPrimary} />
                  <Text style={st.secondaryBtnTxt}>Download template with current salaries</Text>
                </Pressable>
                {Platform.OS === "web" ? (
                  <input
                    type="file"
                    accept=".xlsx,.xls"
                    onChange={(e) => {
                      const f = (e.target as HTMLInputElement).files?.[0];
                      if (f) onSalFile(f);
                      (e.target as HTMLInputElement).value = "";
                    }}
                    style={{ padding: 8, borderRadius: 6, border: "1px solid #E2E8F0", width: "100%", marginTop: 8 } as any}
                  />
                ) : null}
                {salPreview ? (
                  <>
                    <Text style={st.hint}>
                      {salPreview.summary.matched} matched · {salPreview.summary.errors} errors/skipped
                    </Text>
                    {(salPreview.rows || [])
                      .filter((r: any) => r.status === "matched")
                      .slice(0, 10)
                      .map((r: any, i: number) => (
                        <Text key={i} style={st.okLine}>
                          {r.employee_code} {r.name}:{" "}
                          {r.new_actual != null ? `Actual ${r.current_actual} → ${r.new_actual}  ` : ""}
                          {r.new_compliance != null ? `Compliance ${r.current_compliance} → ${r.new_compliance}` : ""}
                        </Text>
                      ))}
                    <Pressable style={st.primaryBtn} onPress={applySalaryExcel} disabled={busy}>
                      {busy ? <ActivityIndicator color="#fff" size="small" /> : (
                        <Text style={st.primaryBtnTxt}>
                          Apply {salPreview.summary.matched} revisions
                        </Text>
                      )}
                    </Pressable>
                  </>
                ) : null}
              </>
            )}
          </View>
        ) : null}

        {/* ------------------- TRANSFER ------------------- */}
        {tab === "transfer" ? (
          <>
            <View style={st.card}>
              <View style={st.rowWrap}>
                <Chip label="From Firm (list)" on={trMode === "firm"} onPress={() => { setTrMode("firm"); setMsg(null); }} />
                <Chip label="Search Employee (Aadhaar / PAN / Mobile / ESI / UAN)" on={trMode === "search"} onPress={() => { setTrMode("search"); setMsg(null); }} />
              </View>

              {trMode === "firm" ? (
                <>
                  <Text style={st.section}>1 · Old Company (transfer FROM)</Text>
                  <CompanyPicker value={srcCompany} onChange={(v: any) => setSrcCompany(!v || v === "all" ? "" : v)} />
                  {srcCompany ? (
                    <>
                      <View style={[st.rowWrap, { marginTop: 10 }]}>
                        <Chip label={`All (${srcEmps.length})`} on={srcFilter === "all"} onPress={() => setSrcFilter("all")} />
                        <Chip label={`Active (${srcEmps.filter((e) => !e.is_resigned).length})`} on={srcFilter === "active"} onPress={() => setSrcFilter("active")} />
                        <Chip label={`Resigned (${srcEmps.filter((e) => e.is_resigned).length})`} on={srcFilter === "resigned"} onPress={() => setSrcFilter("resigned")} />
                      </View>
                      <Text style={st.hint}>
                        Only RESIGNED employees can be transferred — tapping an active
                        employee shows an error. Set exit dates in the Resignation tab first.
                      </Text>
                      <View style={st.pickerList}>
                        <ScrollView nestedScrollEnabled style={{ maxHeight: 320 }}>
                          {srcEmps
                            .filter((e) => srcFilter === "all" ? true : srcFilter === "resigned" ? e.is_resigned : !e.is_resigned)
                            .map((e) => {
                              const on = trSel.has(e.user_id);
                              return (
                                <Pressable key={e.user_id} style={[st.empRow, on && st.empRowOn]}
                                  onPress={() => toggleTransferEmp(e)} testID={`tr-emp-${e.employee_code}`}>
                                  <Ionicons
                                    name={on ? "checkbox" : e.is_resigned ? "square-outline" : "close-circle-outline"}
                                    size={18}
                                    color={on ? colors.brandPrimary : e.is_resigned ? "#94A3B8" : "#DC2626"}
                                  />
                                  <Text style={st.empCode}>{e.employee_code || "—"}</Text>
                                  <Text style={st.empName} numberOfLines={1}>{e.name}</Text>
                                  <Text style={st.empMeta} numberOfLines={1}>{e.designation || e.department || ""}</Text>
                                  <View style={[st.statusPill, e.is_resigned ? st.pillResigned : st.pillActive]}>
                                    <Text style={[st.statusPillTxt, { color: e.is_resigned ? "#991B1B" : "#065F46" }]}>
                                      {e.is_resigned ? `RESIGNED${e.exit_date ? ` ${e.exit_date}` : ""}` : "ACTIVE"}
                                    </Text>
                                  </View>
                                </Pressable>
                              );
                            })}
                          {srcEmps.length === 0 ? <Text style={[st.hint, { padding: 10 }]}>No employees in this firm.</Text> : null}
                        </ScrollView>
                      </View>
                    </>
                  ) : null}
                </>
              ) : (
                <>
                  <Text style={st.section}>1 · Search the old employee record</Text>
                  <View style={st.rowWrap}>
                    <TextInput
                      style={[st.input, { flex: 1 }]}
                      placeholder="Aadhaar / PAN / Mobile / ESI No. / UAN / name…"
                      placeholderTextColor="#94A3B8"
                      value={trSearchQ}
                      onChangeText={setTrSearchQ}
                      autoCapitalize="none"
                      testID="tr-search-input"
                    />
                    <Pressable style={[st.primaryBtn, { marginTop: 0, paddingHorizontal: 16 }]} onPress={searchEmployees} disabled={busy} testID="tr-search-btn">
                      {busy ? <ActivityIndicator color="#fff" size="small" /> : <Text style={st.primaryBtnTxt}>Search</Text>}
                    </Pressable>
                  </View>
                  {trResults.map((e) => {
                    const picked = trPicked?.user_id === e.user_id;
                    return (
                      <Pressable key={e.user_id}
                        style={[st.searchCard, picked && st.searchCardOn]}
                        onPress={() => {
                          if (!e.is_resigned) {
                            setMsg({ kind: "err", text: `${e.name} is ACTIVE in ${e.company_name} — only RESIGNED employees can be transferred.` });
                            return;
                          }
                          setMsg(null);
                          setTrPicked(picked ? null : e);
                        }}
                        testID={`tr-result-${e.employee_code}`}>
                        <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <Text style={[st.empName, { flex: 0, fontWeight: "700" }]}>{e.name} · #{e.employee_code}</Text>
                          <View style={[st.statusPill, e.is_resigned ? st.pillResigned : st.pillActive]}>
                            <Text style={[st.statusPillTxt, { color: e.is_resigned ? "#991B1B" : "#065F46" }]}>
                              {e.is_resigned ? "RESIGNED" : "ACTIVE"}
                            </Text>
                          </View>
                          {picked ? <Ionicons name="checkmark-circle" size={18} color={colors.brandPrimary} /> : null}
                        </View>
                        <Text style={st.hint}>
                          Current firm: {e.company_name} · DOJ {e.doj || "—"}{e.exit_date ? ` · Exit ${e.exit_date}` : ""}
                        </Text>
                        <Text style={st.hint}>
                          {[e.aadhaar_no && `Aadhaar ${e.aadhaar_no}`, e.pan_no && `PAN ${e.pan_no}`,
                            e.uan_no && `UAN ${e.uan_no}`, e.esi_ip_no && `ESI ${e.esi_ip_no}`,
                            e.phone && `Mob ${e.phone}`].filter(Boolean).join(" · ") || "No ID numbers on file"}
                        </Text>
                        {(e.service_history || []).length > 0 ? (
                          <View style={st.histBox}>
                            <Text style={[st.hint, { fontWeight: "700", color: "#334155" }]}>Service record (old companies):</Text>
                            {e.service_history.map((h: any, i: number) => (
                              <Text key={i} style={st.hint}>
                                • {h.company_name} — code #{h.employee_code || "—"} · {h.doj || "?"} → {h.exit_date || "?"}
                              </Text>
                            ))}
                          </View>
                        ) : null}
                      </Pressable>
                    );
                  })}
                </>
              )}
            </View>

            <View style={st.card}>
              <Text style={st.section}>2 · New Company (transfer TO)</Text>
              <CompanyPicker value={destCompany} onChange={(v: any) => setDestCompany(!v || v === "all" ? "" : v)} />
              <View style={[st.rowWrap, { marginTop: 10 }]}>
                <TextInput
                  style={st.input}
                  placeholder="Joining date YYYY-MM-DD (optional)"
                  placeholderTextColor="#94A3B8"
                  value={transferDate}
                  onChangeText={setTransferDate}
                />
                <TextInput
                  style={[st.input, { flex: 1 }]}
                  placeholder="Note (optional)"
                  placeholderTextColor="#94A3B8"
                  value={transferNote}
                  onChangeText={setTransferNote}
                />
              </View>
              <Text style={st.hint}>
                The employee JOINS the new company with the NEXT FREE employee code —
                their whole master data moves, and the old employment stays in their
                service record.
              </Text>
              <Pressable
                style={[st.primaryBtn,
                  ((trMode === "firm" ? trSel.size === 0 : !trPicked) || !destCompany) && { opacity: 0.5 }]}
                onPress={applyTransfer}
                disabled={busy || (trMode === "firm" ? trSel.size === 0 : !trPicked) || !destCompany}
                testID="tr-apply">
                {busy ? <ActivityIndicator color="#fff" size="small" /> : (
                  <Text style={st.primaryBtnTxt}>
                    Transfer {trMode === "firm" ? trSel.size : trPicked ? 1 : 0} employee(s)
                  </Text>
                )}
              </Pressable>
            </View>
          </>
        ) : null}

        {/* ------------------- RESIGNATION ------------------- */}
        {tab === "resign" ? (
          <View style={st.card}>
            <View style={st.rowWrap}>
              <TextInput
                style={st.input}
                placeholder="Exit date YYYY-MM-DD"
                placeholderTextColor="#94A3B8"
                value={exitDate}
                onChangeText={setExitDate}
              />
              <TextInput
                style={[st.input, { flex: 1 }]}
                placeholder="Reason (optional)"
                placeholderTextColor="#94A3B8"
                value={exitReason}
                onChangeText={setExitReason}
              />
            </View>
            <Text style={st.hint}>
              Sets the exit date & marks the employees as resigned. They stop
              appearing in active lists after the exit date passes.
            </Text>
            <Pressable style={[st.primaryBtn, { backgroundColor: "#DC2626" }]} onPress={applyResign} disabled={busy}>
              {busy ? <ActivityIndicator color="#fff" size="small" /> : (
                <Text style={st.primaryBtnTxt}>Set exit date for {selected.size} employees</Text>
              )}
            </Pressable>
          </View>
        ) : null}

        {/* ------------------- SHIFT ------------------- */}
        {tab === "shift" ? (
          <View style={st.card}>
            <Text style={st.section}>Shift (from Shift Master)</Text>
            <View style={st.rowWrap}>
              {shifts.map((s: any) => (
                <Chip
                  key={s.shift_id}
                  label={`${s.name} (${s.start}–${s.end})`}
                  on={shiftId === s.shift_id}
                  onPress={() => setShiftId(s.shift_id)}
                />
              ))}
              {shifts.length === 0 ? (
                <Text style={st.hint}>No shifts defined — add them in Masters → Shifts.</Text>
              ) : null}
            </View>
            <Pressable style={st.primaryBtn} onPress={applyShift} disabled={busy}>
              {busy ? <ActivityIndicator color="#fff" size="small" /> : (
                <Text style={st.primaryBtnTxt}>Assign shift to {selected.size} employees</Text>
              )}
            </Pressable>
          </View>
        ) : null}

        {/* ------------------- HISTORY ------------------- */}
        {tab === "history" ? (
          <View style={st.card}>
            {history.length === 0 ? (
              <Text style={st.hint}>No bulk operations yet.</Text>
            ) : (
              history.map((h: any) => (
                <View key={h.log_id} style={st.histRow}>
                  <Ionicons
                    name={
                      h.op === "attendance_upload" ? "cloud-upload-outline"
                        : h.op === "salary_revision" ? "trending-up-outline"
                          : h.op === "transfer" ? "swap-horizontal-outline"
                            : h.op === "resignation" ? "exit-outline"
                              : "time-outline"
                    }
                    size={17}
                    color={colors.brandPrimary}
                  />
                  <View style={{ flex: 1 }}>
                    <Text style={st.histDetail}>{h.detail}</Text>
                    <Text style={st.histMeta}>
                      {h.company_name || ""} · {String(h.at || "").slice(0, 16).replace("T", " ")} · by {h.by_name || h.by}
                    </Text>
                  </View>
                </View>
              ))
            )}
          </View>
        ) : null}

        {needsPicker ? (
          <View style={st.card}>
            <Text style={st.section}>Select employees</Text>
            <EmployeePicker emps={emps} selected={selected} onToggle={toggle} onSetAll={setAll} />
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F6F8FA" },
  wrap: { padding: 16, paddingBottom: 48, maxWidth: 1100, width: "100%", alignSelf: "center" },
  title: { fontSize: 22, fontWeight: "800", color: "#0F172A" },
  subtitle: { fontSize: 13, color: "#64748B", marginTop: 4, marginBottom: 12 },
  tabs: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  tabBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius?.md ?? 8,
    backgroundColor: "#fff", borderWidth: 1, borderColor: "#E2E8F0",
  },
  tabBtnOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 13, fontWeight: "600", color: colors.brandPrimary },
  tabTxtOn: { color: "#fff" },
  banner: {
    flexDirection: "row", alignItems: "center", gap: 8, padding: 10,
    borderRadius: 8, marginBottom: 12,
  },
  bannerOk: { backgroundColor: "#ECFDF5", borderWidth: 1, borderColor: "#A7F3D0" },
  bannerErr: { backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FECACA" },
  bannerTxt: { fontSize: 13, flex: 1 },
  card: {
    backgroundColor: "#fff", borderRadius: 12, padding: 16, marginBottom: 14,
    borderWidth: 1, borderColor: "#E2E8F0",
  },
  section: { fontSize: 14, fontWeight: "700", color: "#0F172A", marginBottom: 8, marginTop: 4 },
  rowWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 8 },
  hint: { fontSize: 12, color: "#64748B", marginVertical: 4 },
  lbl: { fontSize: 13, color: "#334155", fontWeight: "600" },
  chip: {
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999,
    backgroundColor: "#F1F5F9", borderWidth: 1, borderColor: "#E2E8F0",
  },
  chipOn: { backgroundColor: "#EFF6FF", borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12.5, color: "#475569", fontWeight: "600" },
  chipTxtOn: { color: colors.brandPrimary },
  input: {
    borderWidth: 1, borderColor: "#E2E8F0", borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, minWidth: 180,
    backgroundColor: "#fff", color: "#0F172A",
  },
  primaryBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: 8, paddingVertical: 11,
    alignItems: "center", marginTop: 10, minHeight: 44, justifyContent: "center",
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "700", fontSize: 14 },
  secondaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 8, marginVertical: 8,
  },
  secondaryBtnTxt: { color: colors.brandPrimary, fontWeight: "600", fontSize: 13 },
  errLine: { fontSize: 12, color: "#DC2626", marginVertical: 1 },
  okLine: { fontSize: 12, color: "#065F46", marginVertical: 1 },
  pickerWrap: { marginTop: 4 },
  pickerHead: { flexDirection: "row", gap: 8, alignItems: "center", marginBottom: 8 },
  search: {
    flex: 1, borderWidth: 1, borderColor: "#E2E8F0", borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, color: "#0F172A",
  },
  smallBtn: {
    paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8,
    backgroundColor: "#F1F5F9",
  },
  smallBtnTxt: { fontSize: 12, color: "#334155", fontWeight: "600" },
  pickerList: { maxHeight: 340, borderWidth: 1, borderColor: "#F1F5F9", borderRadius: 8 },
  empRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 10, paddingVertical: 9,
    borderBottomWidth: 1, borderBottomColor: "#F1F5F9",
  },
  empRowOn: { backgroundColor: "#F0F7FF" },
  empCode: { width: 46, fontSize: 12.5, fontWeight: "700", color: "#334155" },
  empName: { flex: 1.4, fontSize: 13, color: "#0F172A" },
  empMeta: { flex: 1, fontSize: 12, color: "#64748B" },
  empSal: { width: 90, fontSize: 12.5, color: "#334155", textAlign: "right" },
  histRow: {
    flexDirection: "row", gap: 10, alignItems: "flex-start",
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#F1F5F9",
  },
  histDetail: { fontSize: 13, color: "#0F172A" },
  histMeta: { fontSize: 11.5, color: "#94A3B8", marginTop: 2 },
  // Iter 291 — transfer redesign.
  statusPill: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  pillActive: { backgroundColor: "#D1FAE5" },
  pillResigned: { backgroundColor: "#FEE2E2" },
  statusPillTxt: { fontSize: 10, fontWeight: "800" },
  searchCard: {
    borderWidth: 1, borderColor: "#E2E8F0", borderRadius: 10,
    padding: 12, marginTop: 10, backgroundColor: "#fff",
  },
  searchCardOn: { borderColor: colors.brandPrimary, backgroundColor: "#F0F7FF" },
  histBox: {
    marginTop: 6, borderTopWidth: 1, borderTopColor: "#F1F5F9", paddingTop: 6,
  },
});
