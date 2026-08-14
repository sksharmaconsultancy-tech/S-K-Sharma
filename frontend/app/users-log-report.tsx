/**
 * Iter 85 — Users Log Report.
 *
 * A unified activity feed for Super/Sub/Company admins. Aggregates
 * events from company_audit_log, attendance_audit_log, salary_runs
 * (generated + finalized), and compliance_salary_runs.
 *
 * Filters:
 *   • Date range (from / to)
 *   • Firm (super/sub admin only — company_admin is auto-scoped)
 *   • User (dropdown of admins in the visible firms)
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  ScrollView,
  Platform,
  TextInput,
  Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";
import { formatDateTime } from "@/src/utils/date";
import DateField from "@/src/components/DateField";
import CompanyPicker from "@/src/components/CompanyPicker";

type FieldChange = { field: string; old: string; new: string };

type LogEvent = {
  at?: string;
  actor_id?: string;
  actor_name?: string;
  actor_role?: string;
  company_id?: string;
  company_name?: string;
  action?: string;
  details?: string;
  source?: string;
  // Iter 568 — Detailed Audit Trail
  module?: string;
  action_type?: string;
  success?: boolean;
  status_code?: number;
  ip?: string;
  device?: string;
  method?: string;
  path?: string;
  record_id?: string;
  record_label?: string;
  description?: string;
  changes?: FieldChange[];
  old_values?: Record<string, string> | null;
  new_values?: Record<string, string> | null;
};

const TYPE_COLORS: Record<string, string> = {
  CREATE: "#16a34a",
  UPDATE: "#2563eb",
  DELETE: "#dc2626",
  LOGIN: "#7c3aed",
  DOWNLOAD: "#d97706",
  OTHER: "#64748b",
};

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

export default function UsersLogReportScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { companies, selectedCompanyId } = useSelectedCompany();
  const isAdmin = user?.role === "super_admin" || user?.role === "sub_admin" || user?.role === "company_admin";

  const [fromDate, setFromDate] = useState<string>(daysAgoIso(7));
  const [toDate, setToDate] = useState<string>(todayIso());
  const [firmId, setFirmId] = useState<string>(selectedCompanyId || "");
  const [actorId, setActorId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [events, setEvents] = useState<LogEvent[]>([]);
  // Iter 568 — Detailed Audit Trail: quick filters + search + details modal.
  const [searchTxt, setSearchTxt] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [moduleFilter, setModuleFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>(""); // "" | "success" | "failed"
  const [detailEvent, setDetailEvent] = useState<LogEvent | null>(null);

  const showMsg = (msg: string) => {
    if (Platform.OS === "web") globalThis.alert(msg);
  };

  const fetchLog = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (fromDate) params.set("from_date", fromDate);
      if (toDate)   params.set("to_date", toDate);
      if (firmId)   params.set("company_id", firmId);
      if (actorId)  params.set("user_id", actorId);
      const r = await api<{ events: LogEvent[] }>(`/admin/users-log?${params.toString()}`);
      setEvents(r.events || []);
    } catch (e: any) {
      showMsg(e?.message || "Failed to load user log");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchLog(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // Iter 247 — full Excel report (same filters).
  const [exporting, setExporting] = useState(false);
  const exportXlsx = async () => {
    setExporting(true);
    try {
      const params = new URLSearchParams();
      if (fromDate) params.set("from_date", fromDate);
      if (toDate)   params.set("to_date", toDate);
      if (firmId)   params.set("company_id", firmId);
      if (actorId)  params.set("user_id", actorId);
      if (moduleFilter)  params.set("module", moduleFilter);
      if (typeFilter)    params.set("action_type", typeFilter);
      if (statusFilter)  params.set("status", statusFilter);
      if (searchTxt.trim()) params.set("search", searchTxt.trim());
      const res = await apiBinary(`/admin/users-log.xlsx?${params.toString()}`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = `users-log-${fromDate}-to-${toDate}.xlsx`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      showMsg(e?.message || "Export failed");
    } finally {
      setExporting(false);
    }
  };

  const actors = useMemo(() => {
    const map = new Map<string, { name: string; role: string }>();
    for (const e of events) {
      if (e.actor_id && !map.has(e.actor_id)) {
        map.set(e.actor_id, { name: e.actor_name || "—", role: e.actor_role || "" });
      }
    }
    return Array.from(map.entries()).map(([id, v]) => ({ id, ...v }));
  }, [events]);

  // Iter 568 — client-side quick filters (instant, applied on loaded events).
  const filtered = useMemo(() => {
    let out = events;
    if (moduleFilter) out = out.filter((e) => (e.module || "Other") === moduleFilter);
    if (typeFilter) out = out.filter((e) => (e.action_type || "OTHER") === typeFilter);
    if (statusFilter === "failed") out = out.filter((e) => e.success === false);
    else if (statusFilter === "success") out = out.filter((e) => e.success !== false);
    const s = searchTxt.trim().toLowerCase();
    if (s) {
      out = out.filter((e) =>
        [e.action, e.details, e.actor_name, e.record_label, e.path, e.module, e.company_name, e.ip]
          .join(" ").toLowerCase().includes(s));
    }
    return out;
  }, [events, moduleFilter, typeFilter, statusFilter, searchTxt]);

  // Iter 568 — summary cards for the visible (filtered) events.
  const summary = useMemo(() => {
    const s = { total: filtered.length, creates: 0, updates: 0, deletes: 0, logins: 0, downloads: 0, failed: 0 };
    for (const e of filtered) {
      const t = e.action_type || "OTHER";
      if (t === "CREATE") s.creates += 1;
      else if (t === "UPDATE") s.updates += 1;
      else if (t === "DELETE") s.deletes += 1;
      else if (t === "LOGIN") s.logins += 1;
      else if (t === "DOWNLOAD") s.downloads += 1;
      if (e.success === false) s.failed += 1;
    }
    return s;
  }, [filtered]);

  const modules = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of events) {
      const k = e.module || "Other";
      m.set(k, (m.get(k) || 0) + 1);
    }
    return Array.from(m.entries()).sort((a, b) => b[1] - a[1]);
  }, [events]);

  // Iter 580 — Sub-User activity rollup (per user, from the filtered view).
  const byUser = useMemo(() => {
    type R = { name: string; firm: string; total: number; emp: number; att: number; pay: number; rep: number; failed: number };
    const m = new Map<string, R>();
    for (const e of filtered) {
      const k = e.actor_id || e.actor_name || "system";
      const r = m.get(k) || { name: e.actor_name || "System", firm: e.company_name || "—", total: 0, emp: 0, att: 0, pay: 0, rep: 0, failed: 0 };
      r.total += 1;
      if (e.module === "Employee") r.emp += 1;
      else if (e.module === "Attendance") r.att += 1;
      else if (e.module === "Payroll" || e.module === "Compliance") r.pay += 1;
      if (e.action_type === "DOWNLOAD" || e.module === "Reports") r.rep += 1;
      if (e.success === false) r.failed += 1;
      m.set(k, r);
    }
    return Array.from(m.values()).sort((a, b) => b.total - a.total).slice(0, 20);
  }, [filtered]);

  // Performance chart — per-admin action counts grouped by category.
  const perf = useMemo(() => {
    type Row = {
      id: string; name: string; role: string;
      punch: number; salary: number; compliance: number; other: number; total: number;
    };
    const map = new Map<string, Row>();
    for (const e of filtered) {
      const id = e.actor_id || "unknown";
      let row = map.get(id);
      if (!row) {
        row = {
          id,
          name: (e.actor_name && e.actor_name !== "—") ? e.actor_name
            : (id === "unknown" ? "System / Device" : e.actor_name || "System / Device"),
          role: e.actor_role || "",
          punch: 0, salary: 0, compliance: 0, other: 0, total: 0,
        };
        map.set(id, row);
      }
      const a = e.action || "";
      if (a.startsWith("punch")) row.punch += 1;
      else if (a.startsWith("salary")) row.salary += 1;
      else if (a.startsWith("compliance")) row.compliance += 1;
      else row.other += 1;
      row.total += 1;
    }
    const rows = Array.from(map.values()).sort((a, b) => b.total - a.total);
    const max = rows.length ? rows[0].total : 0;
    return { rows, max };
  }, [filtered]);

  const setQuickRange = (days: number) => {
    setFromDate(daysAgoIso(days));
    setToDate(todayIso());
  };
  const isRange = (days: number) => fromDate === daysAgoIso(days) && toDate === todayIso();

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
            <Text style={styles.h1}>Users Log Report</Text>
            <Text style={styles.hsub}>Audit trail across firms & admins</Text>
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* ── Iter 568 — Summary cards ─────────────────────────────── */}
        <View style={styles.sumRow}>
          <SummaryCard label="Total" value={summary.total} color={colors.brandPrimary} icon="list-outline" />
          <SummaryCard label="Created" value={summary.creates} color="#16a34a" icon="add-circle-outline" />
          <SummaryCard label="Updated" value={summary.updates} color="#2563eb" icon="create-outline" />
          <SummaryCard label="Deleted" value={summary.deletes} color="#dc2626" icon="trash-outline" />
          <SummaryCard label="Logins" value={summary.logins} color="#7c3aed" icon="log-in-outline" />
          <SummaryCard label="Failed" value={summary.failed} color="#b91c1c" icon="warning-outline" />
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Filters</Text>
          <View style={styles.filterRow}>
            <View style={styles.filterCol}>
              <Text style={styles.label}>Quick period</Text>
              <View style={styles.chipStrip}>
                <Chip label="Today" active={isRange(0)} onPress={() => setQuickRange(0)} />
                <Chip label="Yesterday" active={fromDate === daysAgoIso(1) && toDate === daysAgoIso(1)}
                  onPress={() => { setFromDate(daysAgoIso(1)); setToDate(daysAgoIso(1)); }} />
                <Chip label="Last 7 days" active={isRange(7)} onPress={() => setQuickRange(7)} />
                <Chip label="Last 30 days" active={isRange(30)} onPress={() => setQuickRange(30)} />
                <Chip label="Last 90 days" active={isRange(90)} onPress={() => setQuickRange(90)} />
              </View>
            </View>
          </View>
          <View style={styles.filterRow}>
            <View style={styles.filterCol}>
              <Text style={styles.label}>From date</Text>
              <DateField
                value={fromDate}
                onChangeISO={setFromDate}
                testID="ulr-from-date"
              />
            </View>
            <View style={styles.filterCol}>
              <Text style={styles.label}>To date</Text>
              <DateField
                value={toDate}
                onChangeISO={setToDate}
                testID="ulr-to-date"
              />
            </View>
          </View>

          {user?.role !== "company_admin" ? (
            <View style={styles.filterRow}>
              <View style={styles.filterCol}>
                {/* Iter 520 (user request) — firm as OPTIONAL dropdown:
                    "All firms" shows Super/Sub-admin activity too. */}
                <Text style={styles.label}>Firm (optional — All shows Super/Sub-admin logs)</Text>
                <CompanyPicker
                  value={firmId || "all"}
                  onChange={(v) => setFirmId(v === "all" ? "" : v)}
                  companies={companies}
                  allowAll
                  label="Firm"
                  testID="ulr-firm-dd"
                />
              </View>
            </View>
          ) : null}

          {actors.length > 0 ? (
            <View style={styles.filterRow}>
              <View style={styles.filterCol}>
                <Text style={styles.label}>Filter by admin</Text>
                <View style={styles.chipStrip}>
                  <Chip
                    label="All users"
                    active={!actorId}
                    onPress={() => setActorId("")}
                  />
                  {actors.map((a) => (
                    <Chip
                      key={a.id}
                      label={`${a.name} · ${a.role}`}
                      active={actorId === a.id}
                      onPress={() => setActorId(a.id)}
                    />
                  ))}
                </View>
              </View>
            </View>
          ) : null}

          <View style={{ flexDirection: "row", gap: 10 }}>
            <Pressable
              onPress={fetchLog}
              disabled={loading}
              style={[styles.primaryBtn, { flex: 1 }, loading && { opacity: 0.6 }]}
              testID="ulr-show"
            >
              {loading ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="eye-outline" size={14} color="#fff" />
                  <Text style={styles.primaryBtnTxt}>Show</Text>
                </>
              )}
            </Pressable>
            <Pressable
              onPress={exportXlsx}
              disabled={exporting}
              style={[styles.primaryBtn, { flex: 1, backgroundColor: "#16a34a" }, exporting && { opacity: 0.6 }]}
              testID="ulr-export-xlsx"
            >
              {exporting ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="download-outline" size={14} color="#fff" />
                  <Text style={styles.primaryBtnTxt}>Excel Report</Text>
                </>
              )}
            </Pressable>
          </View>
        </View>

        {/* ── Iter 568 — Audit quick filters + search ──────────────── */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Audit Filters</Text>
          <Text style={styles.label}>Search (user, action, record, IP...)</Text>
          <TextInput
            style={styles.input}
            value={searchTxt}
            onChangeText={setSearchTxt}
            placeholder="Type to search the log..."
            placeholderTextColor={colors.onSurfaceTertiary}
            testID="ulr-search"
          />
          <Text style={styles.label}>Action type</Text>
          <View style={styles.chipStrip}>
            <Chip label="All" active={!typeFilter} onPress={() => setTypeFilter("")} />
            {["CREATE", "UPDATE", "DELETE", "LOGIN", "DOWNLOAD"].map((t) => (
              <Chip key={t} label={t} active={typeFilter === t} onPress={() => setTypeFilter(typeFilter === t ? "" : t)} />
            ))}
          </View>
          <Text style={styles.label}>Status</Text>
          <View style={styles.chipStrip}>
            <Chip label="All" active={!statusFilter} onPress={() => setStatusFilter("")} />
            <Chip label="Success" active={statusFilter === "success"} onPress={() => setStatusFilter(statusFilter === "success" ? "" : "success")} />
            <Chip label="Failed" active={statusFilter === "failed"} onPress={() => setStatusFilter(statusFilter === "failed" ? "" : "failed")} />
          </View>
          {modules.length > 0 ? (
            <>
              <Text style={styles.label}>Module</Text>
              <View style={styles.chipStrip}>
                <Chip label="All" active={!moduleFilter} onPress={() => setModuleFilter("")} />
                {modules.slice(0, 10).map(([m, n]) => (
                  <Chip key={m} label={`${m} (${n})`} active={moduleFilter === m} onPress={() => setModuleFilter(moduleFilter === m ? "" : m)} />
                ))}
              </View>
            </>
          ) : null}
        </View>

        {/* ── Sub Admin Performance Chart ─────────────────────────── */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Sub Admin Performance</Text>
          <Text style={styles.smallHint}>
            Action counts per admin for the selected period ({fromDate} → {toDate}).
          </Text>
          <View style={styles.legendRow}>
            <LegendDot color="#2563eb" label="Punch" />
            <LegendDot color="#16a34a" label="Salary" />
            <LegendDot color="#d97706" label="Compliance" />
            <LegendDot color="#94a3b8" label="Other" />
          </View>
          {perf.rows.length === 0 && !loading ? (
            <Text style={styles.smallHint}>No activity found for the selected period.</Text>
          ) : null}
          {perf.rows.map((r) => (
            <View key={r.id} style={styles.perfRow} testID={`ulr-perf-${r.id}`}>
              <View style={styles.perfHead}>
                <Text style={styles.perfName} numberOfLines={1}>
                  {r.name}
                  <Text style={styles.perfRole}>{r.role ? `  ·  ${r.role}` : ""}</Text>
                </Text>
                <Text style={styles.perfTotal}>{r.total} actions</Text>
              </View>
              <View style={styles.perfBarTrack}>
                {r.punch > 0 ? (
                  <View style={[styles.perfSeg, { flex: r.punch, backgroundColor: "#2563eb" }]} />
                ) : null}
                {r.salary > 0 ? (
                  <View style={[styles.perfSeg, { flex: r.salary, backgroundColor: "#16a34a" }]} />
                ) : null}
                {r.compliance > 0 ? (
                  <View style={[styles.perfSeg, { flex: r.compliance, backgroundColor: "#d97706" }]} />
                ) : null}
                {r.other > 0 ? (
                  <View style={[styles.perfSeg, { flex: r.other, backgroundColor: "#94a3b8" }]} />
                ) : null}
                {/* filler keeps bar length proportional to the busiest admin */}
                {perf.max > r.total ? <View style={{ flex: perf.max - r.total }} /> : null}
              </View>
              <Text style={styles.perfBreakdown}>
                Punch {r.punch} · Salary {r.salary} · Compliance {r.compliance} · Other {r.other}
              </Text>
            </View>
          ))}
        </View>

        {/* Iter 580 — Sub-User activity rollup */}
        {byUser.length > 0 ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Activity by User</Text>
            <View style={styles.buHead}>
              {["User", "Total", "Emp", "Att", "Pay", "Rep", "Fail"].map((h, i) => (
                <Text key={h} style={[styles.buCell, styles.buHeadTxt, i === 0 ? { flex: 2.2 } : { flex: 0.8, textAlign: "center" }]}>{h}</Text>
              ))}
            </View>
            {byUser.map((r, i) => (
              <View key={i} style={[styles.buRow, i % 2 === 1 && { backgroundColor: colors.surface }]}>
                <View style={{ flex: 2.2, padding: 6 }}>
                  <Text style={styles.buName}>{r.name}</Text>
                  <Text style={styles.buFirm}>{r.firm}</Text>
                </View>
                {[r.total, r.emp, r.att, r.pay, r.rep].map((v, j) => (
                  <Text key={j} style={[styles.buCell, { flex: 0.8, textAlign: "center" }]}>{v}</Text>
                ))}
                <Text style={[styles.buCell, { flex: 0.8, textAlign: "center", color: r.failed ? "#dc2626" : colors.onSurfaceTertiary, fontWeight: "700" }]}>{r.failed}</Text>
              </View>
            ))}
          </View>
        ) : null}

        <View style={styles.card}>
          <Text style={styles.cardTitle}>
            Log entries · {filtered.length}
          </Text>
          {filtered.length === 0 && !loading ? (
            <Text style={styles.smallHint}>
              No log entries for the selected filters. Try widening the date
              range or clearing the firm / user filter.
            </Text>
          ) : null}
          {filtered.map((e, idx) => {
            const t = e.action_type || "OTHER";
            const failed = e.success === false;
            const nChanges = (e.changes || []).length;
            return (
              <Pressable
                key={idx}
                style={[styles.logRow, failed && styles.logRowFailed]}
                onPress={() => setDetailEvent(e)}
                testID={`ulr-row-${idx}`}
              >
                <View style={[styles.typeBadge, { backgroundColor: TYPE_COLORS[t] || TYPE_COLORS.OTHER }]}>
                  <Text style={styles.typeBadgeTxt}>{t.slice(0, 3)}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.logAction} numberOfLines={3}>
                    {e.description || e.action || "—"}
                    {failed ? <Text style={{ color: "#dc2626" }}>  ✗ FAILED</Text> : null}
                  </Text>
                  <Text style={styles.logMeta}>
                    {e.actor_name || "—"}
                    {e.actor_role ? ` (${e.actor_role})` : ""}
                    {"  ·  "}
                    {e.company_name || "—"}
                    {e.module ? `  ·  ${e.module}` : ""}
                  </Text>
                  {e.record_label ? (
                    <Text style={styles.logMeta}>Record: {e.record_label}</Text>
                  ) : null}
                  {nChanges > 0 ? (
                    <Text style={styles.logChanges}>
                      ✎ {nChanges} field{nChanges > 1 ? "s" : ""} changed — tap to view old → new
                    </Text>
                  ) : e.details ? (
                    <Text style={styles.logDetails} numberOfLines={2}>{e.details}</Text>
                  ) : null}
                </View>
                <View style={{ alignItems: "flex-end", gap: 4 }}>
                  <Text style={styles.logAt}>{formatDateTime(e.at)}</Text>
                  <Ionicons name="chevron-forward" size={14} color={colors.onSurfaceTertiary} />
                </View>
              </Pressable>
            );
          })}
        </View>
        <View style={{ height: 40 }} />
      </ScrollView>

      {/* ── Iter 568 — View Details modal (field-level old → new) ──── */}
      <Modal
        visible={!!detailEvent}
        transparent
        animationType="fade"
        onRequestClose={() => setDetailEvent(null)}
      >
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>Audit Entry Details</Text>
              <Pressable onPress={() => setDetailEvent(null)} hitSlop={10} testID="ulr-detail-close">
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            <ScrollView style={{ maxHeight: 480 }}>
              {detailEvent ? (
                <>
                  <MetaRow label="Date & Time" value={formatDateTime(detailEvent.at)} />
                  {detailEvent.description ? (
                    <MetaRow label="What Happened" value={detailEvent.description} />
                  ) : null}
                  <MetaRow label="User" value={`${detailEvent.actor_name || "—"}${detailEvent.actor_role ? ` (${detailEvent.actor_role})` : ""}`} />
                  <MetaRow label="Firm" value={detailEvent.company_name || "—"} />
                  <MetaRow label="Module" value={detailEvent.module || "—"} />
                  <MetaRow label="Action" value={detailEvent.action || "—"} />
                  {detailEvent.record_label || detailEvent.record_id ? (
                    <MetaRow label="Record" value={`${detailEvent.record_label || ""}${detailEvent.record_id ? ` [${detailEvent.record_id}]` : ""}`} />
                  ) : null}
                  <MetaRow
                    label="Status"
                    value={detailEvent.success === false
                      ? `FAILED${detailEvent.status_code ? ` (HTTP ${detailEvent.status_code})` : ""}`
                      : "Success"}
                    valueColor={detailEvent.success === false ? "#dc2626" : "#16a34a"}
                  />
                  {detailEvent.ip ? <MetaRow label="IP Address" value={detailEvent.ip} /> : null}
                  {detailEvent.device ? <MetaRow label="Device" value={detailEvent.device} small /> : null}
                  {detailEvent.method && detailEvent.path ? (
                    <MetaRow label="Endpoint" value={`${detailEvent.method} ${detailEvent.path}`} small />
                  ) : null}
                  {detailEvent.details ? <MetaRow label="Details" value={detailEvent.details} small /> : null}

                  {(detailEvent.changes || []).length > 0 ? (
                    <>
                      <Text style={styles.diffTitle}>Field Changes (Old → New)</Text>
                      <View style={styles.diffHead}>
                        <Text style={[styles.diffCell, styles.diffHeadTxt, { flex: 1 }]}>Field</Text>
                        <Text style={[styles.diffCell, styles.diffHeadTxt, { flex: 1.3 }]}>Old Value</Text>
                        <Text style={[styles.diffCell, styles.diffHeadTxt, { flex: 1.3 }]}>New Value</Text>
                      </View>
                      {(detailEvent.changes || []).map((c, i) => (
                        <View key={i} style={[styles.diffRow, i % 2 === 1 && { backgroundColor: colors.surface }]}>
                          <Text style={[styles.diffCell, styles.diffField, { flex: 1 }]}>{c.field}</Text>
                          <Text style={[styles.diffCell, styles.diffOld, { flex: 1.3 }]}>{c.old || "—"}</Text>
                          <Text style={[styles.diffCell, styles.diffNew, { flex: 1.3 }]}>{c.new || "—"}</Text>
                        </View>
                      ))}
                    </>
                  ) : null}

                  {detailEvent.old_values && Object.keys(detailEvent.old_values).length > 0 ? (
                    <>
                      <Text style={styles.diffTitle}>Deleted Record Snapshot</Text>
                      {Object.entries(detailEvent.old_values).map(([k, v], i) => (
                        <View key={i} style={styles.diffRow}>
                          <Text style={[styles.diffCell, styles.diffField, { flex: 1 }]}>{k}</Text>
                          <Text style={[styles.diffCell, styles.diffOld, { flex: 2.6 }]}>{String(v)}</Text>
                        </View>
                      ))}
                    </>
                  ) : null}

                  {detailEvent.new_values && Object.keys(detailEvent.new_values).length > 0 ? (
                    <>
                      <Text style={styles.diffTitle}>Created Record Values</Text>
                      {Object.entries(detailEvent.new_values).map(([k, v], i) => (
                        <View key={i} style={styles.diffRow}>
                          <Text style={[styles.diffCell, styles.diffField, { flex: 1 }]}>{k}</Text>
                          <Text style={[styles.diffCell, styles.diffNew, { flex: 2.6 }]}>{String(v)}</Text>
                        </View>
                      ))}
                    </>
                  ) : null}
                </>
              ) : null}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function SummaryCard({ label, value, color, icon }: {
  label: string; value: number; color: string; icon: any;
}) {
  return (
    <View style={[styles.sumCard, { borderColor: color + "44" }]}>
      <Ionicons name={icon} size={16} color={color} />
      <Text style={[styles.sumValue, { color }]}>{value}</Text>
      <Text style={styles.sumLabel}>{label}</Text>
    </View>
  );
}

function MetaRow({ label, value, valueColor, small }: {
  label: string; value: string; valueColor?: string; small?: boolean;
}) {
  return (
    <View style={styles.metaRow}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={[styles.metaValue, small && { fontSize: 11 }, valueColor ? { color: valueColor, fontWeight: "700" } : null]}>
        {value}
      </Text>
    </View>
  );
}

function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      style={[styles.chip, active && styles.chipActive]}
    >
      <Text style={[styles.chipTxt, active && styles.chipTxtActive]}>{label}</Text>
    </Pressable>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <View style={styles.legendItem}>
      <View style={[styles.legendDot, { backgroundColor: color }]} />
      <Text style={styles.legendTxt}>{label}</Text>
    </View>
  );
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
  cardTitle: {
    ...type.h6, color: colors.onSurface, fontWeight: "700", marginBottom: 6,
  },
  smallHint: { ...type.caption, color: colors.onSurfaceSecondary },
  filterRow: { flexDirection: "row", gap: 10, flexWrap: "wrap", marginBottom: 6 },
  filterCol: { flex: 1, minWidth: 220 },
  label: {
    ...type.tiny, color: colors.onSurfaceSecondary,
    fontWeight: "700", marginBottom: 4, marginTop: 4,
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

  primaryBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingVertical: 12, marginTop: 8,
    flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "700" },

  logRow: {
    flexDirection: "row", alignItems: "flex-start", gap: 10,
    paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  logRowFailed: { backgroundColor: "#FEF2F2", borderRadius: 8, paddingHorizontal: 6 },
  logChanges: { fontSize: 11, color: "#7c3aed", marginTop: 2, fontWeight: "600" },

  // Iter 568 — summary cards
  sumRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: spacing.md },
  sumCard: {
    flexGrow: 1, minWidth: 100, alignItems: "center",
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    borderWidth: 1, paddingVertical: 10, paddingHorizontal: 8, gap: 2,
  },
  sumValue: { fontSize: 18, fontWeight: "800" },
  sumLabel: { fontSize: 10, fontWeight: "700", color: colors.onSurfaceSecondary, textTransform: "uppercase" },

  // Iter 568 — action-type badge
  typeBadge: {
    width: 38, paddingVertical: 4, borderRadius: 6,
    alignItems: "center", justifyContent: "center", marginTop: 2,
  },
  typeBadgeTxt: { color: "#fff", fontSize: 9, fontWeight: "800" },

  // Iter 568 — details modal
  modalBg: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.5)",
    alignItems: "center", justifyContent: "center", padding: 16,
  },
  modalCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.md, width: "100%", maxWidth: 640,
  },
  modalHead: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginBottom: 10, paddingBottom: 8,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  modalTitle: { ...type.h6, color: colors.onSurface, fontWeight: "800" },
  metaRow: { flexDirection: "row", paddingVertical: 5, gap: 10 },
  metaLabel: {
    width: 100, fontSize: 11, fontWeight: "700",
    color: colors.onSurfaceSecondary, textTransform: "uppercase",
  },
  metaValue: { flex: 1, fontSize: 13, color: colors.onSurface },
  diffTitle: {
    fontSize: 13, fontWeight: "800", color: colors.onSurface,
    marginTop: 14, marginBottom: 6,
  },
  diffHead: {
    flexDirection: "row", backgroundColor: colors.surfaceSecondary,
    borderTopLeftRadius: 8, borderTopRightRadius: 8,
  },
  diffHeadTxt: { fontWeight: "800", fontSize: 10, textTransform: "uppercase", color: colors.onSurfaceSecondary },
  diffRow: {
    flexDirection: "row",
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  diffCell: { padding: 7, fontSize: 12 },
  diffField: { fontWeight: "700", color: colors.onSurface },
  diffOld: { color: "#b91c1c", textDecorationLine: "line-through" },
  diffNew: { color: "#15803d", fontWeight: "600" },

  // Iter 580 — by-user rollup
  buHead: { flexDirection: "row", backgroundColor: colors.surfaceSecondary, borderTopLeftRadius: 8, borderTopRightRadius: 8 },
  buHeadTxt: { fontWeight: "800", fontSize: 10, textTransform: "uppercase", color: colors.onSurfaceSecondary },
  buRow: { flexDirection: "row", alignItems: "center", borderBottomWidth: 1, borderBottomColor: colors.divider },
  buCell: { padding: 6, fontSize: 12, color: colors.onSurface },
  buName: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  buFirm: { fontSize: 10, color: colors.onSurfaceTertiary },
  logAction: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  logMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  logDetails: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2, fontStyle: "italic" },
  logAt: { fontSize: 10, color: colors.onSurfaceTertiary, minWidth: 110, textAlign: "right" },

  // Performance chart
  legendRow: { flexDirection: "row", flexWrap: "wrap", gap: 12, marginTop: 6, marginBottom: 10 },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 5 },
  legendDot: { width: 10, height: 10, borderRadius: 5 },
  legendTxt: { fontSize: 11, color: colors.onSurfaceSecondary, fontWeight: "600" },
  perfRow: { marginBottom: 14 },
  perfHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 4 },
  perfName: { fontSize: 13, fontWeight: "700", color: colors.onSurface, flex: 1, marginRight: 8 },
  perfRole: { fontSize: 11, fontWeight: "500", color: colors.onSurfaceTertiary },
  perfTotal: { fontSize: 12, fontWeight: "800", color: colors.brandPrimary },
  perfBarTrack: {
    flexDirection: "row", height: 14, borderRadius: 7, overflow: "hidden",
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.divider,
  },
  perfSeg: { height: "100%" },
  perfBreakdown: { fontSize: 10, color: colors.onSurfaceTertiary, marginTop: 3 },
});
