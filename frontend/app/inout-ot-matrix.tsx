/**
 * Iter 292 (user request) — Monthly Employee In/Out & Overtime Matrix Report.
 *
 * A NEW report (existing reports untouched): one employee per matrix —
 * rows D-In / D-Out / OT-In / OT-Out / Total Hrs / OT Hrs, columns = days.
 * Colour-coded (OT blue, Late yellow, Missing red, Holiday grey, Weekly-off
 * green, Leave orange), hover tooltip + click-for-punch-history, filters,
 * pagination and Excel / PDF / CSV / Print exports (A4 landscape, one
 * employee per page).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
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
import CompanyPicker from "@/src/components/CompanyPicker";
import MonthPicker from "@/src/components/MonthPicker";
import { colors } from "@/src/theme";

const ROW_LABELS: [string, string][] = [
  ["d_in", "D-In"], ["d_out", "D-Out"], ["ot_in", "OT-In"],
  ["ot_out", "OT-Out"], ["total", "Total Hrs"], ["ot", "OT Hrs"],
];

const FLAG_BG: Record<string, string> = {
  ot: "#DBEAFE", late: "#FEF08A", missing: "#FECACA",
  holiday: "#E2E8F0", weekly_off: "#DCFCE7", leave: "#FED7AA",
};

const LEGEND: [string, string][] = [
  ["OT", "#DBEAFE"], ["Late", "#FEF08A"], ["Missing punch", "#FECACA"],
  ["Holiday", "#E2E8F0"], ["Weekly off", "#DCFCE7"], ["Leave", "#FED7AA"],
];

const currentMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

export default function InOutOtMatrixScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [cid, setCid] = useState<string>("");
  const [month, setMonth] = useState(currentMonth());
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("");
  const [desig, setDesig] = useState("");
  const [cat, setCat] = useState("");
  const [contr, setContr] = useState("");
  const [shift, setShift] = useState("");
  const [status, setStatus] = useState<"all" | "active" | "resigned">("all");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [exporting, setExporting] = useState("");
  const [detail, setDetail] = useState<any | null>(null); // {emp, day, cell}
  const [punches, setPunches] = useState<any[] | null>(null);

  useEffect(() => {
    if (user?.role === "company_admin") setCid(user.company_id || "");
    else if (selectedCompanyId && selectedCompanyId !== "all") setCid(selectedCompanyId);
  }, [user, selectedCompanyId]);

  const qs = useMemo(() => {
    const p = new URLSearchParams({ month, page: String(page), page_size: "10" });
    if (cid) p.set("company_id", cid);
    if (q.trim()) p.set("q", q.trim());
    if (dept) p.set("department", dept);
    if (desig) p.set("designation", desig);
    if (cat) p.set("employee_type", cat);
    if (contr) p.set("contractor", contr);
    if (shift) p.set("shift", shift);
    if (status !== "all") p.set("status", status);
    return p.toString();
  }, [cid, month, q, dept, desig, cat, contr, shift, status, page]);

  const load = useCallback(async () => {
    if (!cid) return;
    setLoading(true);
    setErr("");
    try {
      const r = await api<any>(`/admin/reports/inout-ot-matrix?${qs}`);
      setData(r);
    } catch (e: any) {
      setErr(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [cid, qs]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [cid, month, q, dept, desig, cat, contr, shift, status]);

  const doExport = async (kind: "xlsx" | "pdf" | "csv" | "print") => {
    if (!cid) return;
    setExporting(kind);
    try {
      const path = `/admin/reports/inout-ot-matrix.${kind === "print" ? "pdf" : kind}?${qs}`;
      const r = await apiBinary(path);
      if (Platform.OS === "web" && r.webBlobUrl) {
        if (kind === "print" || kind === "pdf") {
          window.open(r.webBlobUrl, "_blank");
        } else {
          const a = document.createElement("a");
          a.href = r.webBlobUrl;
          a.download = `inout-ot-matrix-${month}.${kind}`;
          a.click();
        }
      }
    } catch (e: any) {
      setErr(e?.message || "Export failed");
    } finally {
      setExporting("");
    }
  };

  const openDetail = async (emp: any, dayLabel: string, cell: any) => {
    setDetail({ emp, dayLabel, cell });
    setPunches(null);
    const iso = cell?.detail?.date;
    if (!iso) return;
    try {
      const r = await api<{ records: any[] }>(
        `/admin/attendance/history?user_id=${emp.user_id}&date_from=${iso}&date_to=${iso}&limit=100`);
      setPunches((r.records || []).filter(
        (p) => !["rejected", "auto_ignored"].includes(String(p.status || ""))));
    } catch {
      setPunches([]);
    }
  };

  const fo = data?.filter_options || {};

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.head}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={s.title}>In/Out & OT Matrix</Text>
        <View style={{ flex: 1 }} />
        {(["xlsx", "pdf", "csv", "print"] as const).map((k) => (
          <Pressable key={k} style={s.expBtn} onPress={() => doExport(k)}
            disabled={!!exporting} testID={`iom-export-${k}`}>
            {exporting === k ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : (
              <>
                <Ionicons
                  name={k === "print" ? "print-outline" : k === "pdf" ? "document-outline" : k === "csv" ? "list-outline" : "grid-outline"}
                  size={14} color={colors.brandPrimary} />
                <Text style={s.expTxt}>{k === "print" ? "Print" : k.toUpperCase()}</Text>
              </>
            )}
          </Pressable>
        ))}
      </View>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 12, paddingBottom: 60 }}>
        {/* Filters */}
        <View style={s.filterCard}>
          <View style={s.filterRow}>
            {user?.role !== "company_admin" ? (
              <View style={{ minWidth: 220 }}>
                <CompanyPicker value={cid} onChange={(v: any) => setCid(!v || v === "all" ? "" : v)} />
              </View>
            ) : null}
            <MonthPicker value={month} onChange={setMonth} />
            <TextInput
              style={s.search} value={q} onChangeText={setQ}
              placeholder="Search employee / code…" placeholderTextColor="#94A3B8"
              testID="iom-search" />
          </View>
          <View style={s.filterRow}>
            <FilterSelect label="Department" value={dept} onChange={setDept} options={fo.departments || []} />
            <FilterSelect label="Designation" value={desig} onChange={setDesig} options={fo.designations || []} />
            <FilterSelect label="Category" value={cat} onChange={setCat} options={fo.categories || []} />
            <FilterSelect label="Contractor" value={contr} onChange={setContr} options={fo.contractors || []} />
            <FilterSelect label="Shift" value={shift} onChange={setShift} options={fo.shifts || []} />
            <View style={s.statusChips}>
              {(["all", "active", "resigned"] as const).map((k) => (
                <Pressable key={k} style={[s.chip, status === k && s.chipOn]} onPress={() => setStatus(k)}>
                  <Text style={[s.chipTxt, status === k && s.chipTxtOn]}>
                    {k === "all" ? "All" : k === "active" ? "Active" : "Resigned"}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
          {/* Legend */}
          <View style={s.legendRow}>
            {LEGEND.map(([lab, bg]) => (
              <View key={lab} style={s.legendItem}>
                <View style={[s.legendSwatch, { backgroundColor: bg }]} />
                <Text style={s.legendTxt}>{lab}</Text>
              </View>
            ))}
          </View>
        </View>

        {err ? <Text style={s.err}>{err}</Text> : null}
        {!cid ? <Text style={s.muted}>Select a firm to begin.</Text> : null}
        {loading ? <ActivityIndicator style={{ marginTop: 30 }} color={colors.brandPrimary} /> : null}

        {!loading && data ? (
          <>
            <Text style={s.metaTxt}>
              {data.total_employees} employee(s) · page {data.page}/{data.total_pages} · {data.payroll_period}
            </Text>
            {(data.employees || []).map((emp: any) => (
              <EmployeeMatrix key={emp.user_id} data={data} emp={emp} onCell={openDetail} />
            ))}
            {/* Pagination */}
            {data.total_pages > 1 ? (
              <View style={s.pageRow}>
                <Pressable style={[s.pageBtn, page <= 1 && { opacity: 0.4 }]} disabled={page <= 1}
                  onPress={() => setPage((p) => p - 1)}>
                  <Ionicons name="chevron-back" size={16} color={colors.brandPrimary} />
                  <Text style={s.pageTxt}>Prev</Text>
                </Pressable>
                <Text style={s.metaTxt}>Page {data.page} / {data.total_pages}</Text>
                <Pressable style={[s.pageBtn, page >= data.total_pages && { opacity: 0.4 }]}
                  disabled={page >= data.total_pages} onPress={() => setPage((p) => p + 1)}>
                  <Text style={s.pageTxt}>Next</Text>
                  <Ionicons name="chevron-forward" size={16} color={colors.brandPrimary} />
                </Pressable>
              </View>
            ) : null}
          </>
        ) : null}
      </ScrollView>

      {/* Day detail modal — punches, hours, machine, source, approval */}
      <Modal visible={!!detail} transparent animationType="fade" onRequestClose={() => setDetail(null)}>
        <View style={s.modalWrap}>
          <View style={s.modalCard}>
            <View style={s.modalHead}>
              <Text style={s.modalTitle}>
                {detail?.emp?.name} — {detail?.cell?.detail?.date} ({detail?.cell?.detail?.weekday})
              </Text>
              <Pressable onPress={() => setDetail(null)} hitSlop={10}>
                <Ionicons name="close" size={22} color={colors.onSurfaceSecondary} />
              </Pressable>
            </View>
            <ScrollView style={{ maxHeight: 420 }}>
              <View style={s.kvGrid}>
                {[
                  ["Working Hours", detail?.cell?.detail?.working_hours],
                  ["Break Time", detail?.cell?.detail?.break_time],
                  ["Late Minutes", String(detail?.cell?.detail?.late_min ?? 0)],
                  ["Early Out (min)", String(detail?.cell?.detail?.early_min ?? 0)],
                  ["OT Hours", detail?.cell?.detail?.ot_hours],
                  ["Punch Sources", (detail?.cell?.detail?.sources || []).join(", ") || "—"],
                ].map(([k, v]) => (
                  <View key={String(k)} style={s.kvItem}>
                    <Text style={s.kvKey}>{k}</Text>
                    <Text style={s.kvVal}>{v || "—"}</Text>
                  </View>
                ))}
              </View>
              <Text style={[s.kvKey, { marginTop: 10, marginBottom: 4 }]}>All Punches</Text>
              {punches === null ? <ActivityIndicator color={colors.brandPrimary} /> : null}
              {punches?.length === 0 ? <Text style={s.muted}>No punches on this day.</Text> : null}
              {(punches || []).map((p: any, i: number) => (
                <View key={i} style={s.punchRow}>
                  <View style={[s.punchKind, { backgroundColor: p.kind === "in" ? "#D1FAE5" : "#FEE2E2" }]}>
                    <Text style={[s.punchKindTxt, { color: p.kind === "in" ? "#065F46" : "#991B1B" }]}>
                      {String(p.kind || "").toUpperCase()}
                    </Text>
                  </View>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text style={s.punchTime}>{(p.at || "").slice(11, 19)}</Text>
                    <Text style={s.punchMeta} numberOfLines={2}>
                      {[p.source && `Source: ${p.source}`,
                        (p.device_name || p.device_serial) && `Machine: ${p.device_name || p.device_serial}`,
                        p.lat && p.lng && `GPS: ${Number(p.lat).toFixed(5)}, ${Number(p.lng).toFixed(5)}`,
                        p.status && `Status: ${p.status}`]
                        .filter(Boolean).join(" · ")}
                    </Text>
                  </View>
                </View>
              ))}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

/** Simple inline dropdown filter (web-friendly). */
function FilterSelect({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: string[];
}) {
  const [open, setOpen] = useState(false);
  if (!options.length) return null;
  return (
    <View style={{ position: "relative", zIndex: open ? 50 : 1 }}>
      <Pressable style={s.selBtn} onPress={() => setOpen((o) => !o)} testID={`iom-filter-${label}`}>
        <Text style={s.selTxt} numberOfLines={1}>{value || label}</Text>
        <Ionicons name={open ? "chevron-up" : "chevron-down"} size={13} color="#64748B" />
      </Pressable>
      {open ? (
        <View style={s.selMenu}>
          <ScrollView style={{ maxHeight: 200 }} nestedScrollEnabled>
            <Pressable style={s.selItem} onPress={() => { onChange(""); setOpen(false); }}>
              <Text style={[s.selTxt, { color: "#94A3B8" }]}>All {label}s</Text>
            </Pressable>
            {options.map((o) => (
              <Pressable key={o} style={s.selItem} onPress={() => { onChange(o); setOpen(false); }}>
                <Text style={s.selTxt}>{o}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      ) : null}
    </View>
  );
}

function EmployeeMatrix({ data, emp, onCell }: {
  data: any; emp: any; onCell: (emp: any, dayLabel: string, cell: any) => void;
}) {
  const dayLabels: string[] = data.day_labels || [];
  return (
    <View style={s.empCard} testID={`iom-emp-${emp.employee_code}`}>
      {/* Employee header */}
      <View style={s.empHead}>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={s.empName}>{emp.employee_code} — {emp.name}</Text>
          <Text style={s.empMeta} numberOfLines={2}>
            {[emp.department && `Dept: ${emp.department}`,
              emp.designation && `Desig: ${emp.designation}`,
              emp.category && `Category: ${emp.category}`,
              emp.contractor_name && `Contractor: ${emp.contractor_name}`,
              emp.shift_name && `Shift: ${emp.shift_name}`]
              .filter(Boolean).join("   ·   ")}
          </Text>
          <Text style={s.empMeta}>
            Month: {data.month_number}/{data.year} · Payroll: {data.payroll_period} ·
            {" "}Working {emp.month_total} · OT {emp.month_ot} · Present {emp.present_days}
          </Text>
        </View>
        <View style={[s.statusPill, { backgroundColor: emp.status === "ACTIVE" ? "#D1FAE5" : "#FEE2E2" }]}>
          <Text style={[s.statusTxt, { color: emp.status === "ACTIVE" ? "#065F46" : "#991B1B" }]}>
            {emp.status}
          </Text>
        </View>
      </View>
      {/* Matrix */}
      <ScrollView horizontal showsHorizontalScrollIndicator>
        <View>
          {/* header row */}
          <View style={s.mRow}>
            <View style={[s.mCellLabel, s.mHeadBg]}>
              <Text style={s.mHeadTxt}>Attendance</Text>
            </View>
            {dayLabels.map((d, i) => (
              <View key={d} style={[s.mCell, s.mHeadBg]}>
                <Text style={s.mHeadTxt}>{String(d).slice(0, 2)}</Text>
                <Text style={s.mHeadSub}>{(data.weekday_labels || [])[i] || ""}</Text>
              </View>
            ))}
          </View>
          {ROW_LABELS.map(([key, label]) => (
            <View key={key} style={s.mRow}>
              <View style={s.mCellLabel}>
                <Text style={s.mLabelTxt}>{label}</Text>
              </View>
              {dayLabels.map((d) => {
                const cell = (emp.days || {})[d] || {};
                const bg = FLAG_BG[cell.flag] || "#FFFFFF";
                const det = cell.detail || {};
                const hover = Platform.OS === "web" ? {
                  title:
                    `${det.date} (${det.weekday})\n` +
                    `Working: ${det.working_hours} · Break: ${det.break_time}\n` +
                    `Late: ${det.late_min}m · Early: ${det.early_min}m · OT: ${det.ot_hours}\n` +
                    `Punches: ${det.punch_count} · Source: ${(det.sources || []).join(",") || "—"}\n` +
                    `Click for full punch history`,
                } : {};
                return (
                  <Pressable key={d} style={[s.mCell, { backgroundColor: bg }]}
                    onPress={() => onCell(emp, d, cell)} {...(hover as any)}>
                    <Text style={s.mCellTxt}>{(cell as any)[key] || "-"}</Text>
                  </Pressable>
                );
              })}
            </View>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  head: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 14, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  expBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10,
    paddingVertical: 6, borderRadius: 8, borderWidth: 1,
    borderColor: "rgba(37,99,235,0.35)", backgroundColor: "rgba(37,99,235,0.05)",
  },
  expTxt: { fontSize: 11, fontWeight: "700", color: colors.brandPrimary },
  filterCard: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 12, padding: 12,
    borderWidth: 1, borderColor: colors.border, gap: 10, zIndex: 20,
  },
  filterRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center", zIndex: 10 },
  search: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8, height: 38,
    paddingHorizontal: 10, minWidth: 200, color: colors.onSurface,
    backgroundColor: colors.surface, fontSize: 13,
  },
  selBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1,
    borderColor: colors.border, borderRadius: 8, height: 34,
    paddingHorizontal: 10, backgroundColor: colors.surface, maxWidth: 180,
  },
  selTxt: { fontSize: 12, color: colors.onSurface },
  selMenu: {
    position: "absolute", top: 38, left: 0, minWidth: 180, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border, borderRadius: 8, elevation: 6,
    shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 8, zIndex: 100,
  },
  selItem: { paddingHorizontal: 10, paddingVertical: 8 },
  statusChips: { flexDirection: "row", gap: 6 },
  chip: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11.5, fontWeight: "600", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  legendRow: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  legendSwatch: { width: 14, height: 14, borderRadius: 3, borderWidth: 1, borderColor: "#CBD5E1" },
  legendTxt: { fontSize: 11, color: colors.onSurfaceSecondary },
  err: { color: "#DC2626", marginTop: 10, fontSize: 13 },
  muted: { color: colors.onSurfaceTertiary, marginTop: 10, fontSize: 13 },
  metaTxt: { color: colors.onSurfaceSecondary, fontSize: 12, marginVertical: 8 },
  empCard: {
    backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1,
    borderColor: colors.border, marginBottom: 16, overflow: "hidden",
  },
  empHead: {
    flexDirection: "row", alignItems: "center", gap: 10, padding: 12,
    backgroundColor: colors.surfaceSecondary,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  empName: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface },
  empMeta: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 2 },
  statusPill: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 3 },
  statusTxt: { fontSize: 10.5, fontWeight: "800" },
  mRow: { flexDirection: "row" },
  mCellLabel: {
    width: 84, paddingVertical: 6, paddingHorizontal: 8, justifyContent: "center",
    borderWidth: StyleSheet.hairlineWidth, borderColor: "#CBD5E1",
    backgroundColor: colors.surfaceSecondary,
    ...(Platform.OS === "web" ? ({ position: "sticky", left: 0, zIndex: 2 } as any) : null),
  },
  mCell: {
    width: 52, paddingVertical: 6, alignItems: "center", justifyContent: "center",
    borderWidth: StyleSheet.hairlineWidth, borderColor: "#CBD5E1",
  },
  mHeadBg: { backgroundColor: "#1E3A8A" },
  mHeadTxt: { fontSize: 10.5, fontWeight: "800", color: "#fff" },
  mHeadSub: { fontSize: 8, color: "#BFDBFE" },
  mLabelTxt: { fontSize: 10.5, fontWeight: "800", color: colors.onSurface },
  mCellTxt: { fontSize: 10, color: colors.onSurface },
  pageRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 16, marginTop: 6,
  },
  pageBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 12,
    paddingVertical: 7, borderRadius: 8, borderWidth: 1,
    borderColor: "rgba(37,99,235,0.35)", backgroundColor: "rgba(37,99,235,0.05)",
  },
  pageTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  modalWrap: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.5)", alignItems: "center",
    justifyContent: "center", padding: 16,
  },
  modalCard: {
    backgroundColor: colors.surface, borderRadius: 14, padding: 16,
    width: "100%", maxWidth: 480,
  },
  modalHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  modalTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface, flex: 1 },
  kvGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  kvItem: {
    minWidth: 130, flexGrow: 1, backgroundColor: colors.surfaceSecondary,
    borderRadius: 8, padding: 8,
  },
  kvKey: { fontSize: 10.5, color: colors.onSurfaceTertiary, fontWeight: "700" },
  kvVal: { fontSize: 13, color: colors.onSurface, fontWeight: "700", marginTop: 2 },
  punchRow: {
    flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  punchKind: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3 },
  punchKindTxt: { fontSize: 10, fontWeight: "800" },
  punchTime: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  punchMeta: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 1 },
});
