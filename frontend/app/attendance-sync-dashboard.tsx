/**
 * Iter 392 (user spec) — ATTENDANCE SYNCHRONIZATION DASHBOARD.
 *
 * Single-page reconciliation of Employee Master ⇄ Biometric Machines ⇄
 * Attendance: KPI cards, New Joining, Machine-only, Master-only,
 * Attendance-Missing, Continuous Absence, Machine Sync health, trends and
 * rule-based Smart Analysis remarks. Excel/PDF/CSV exports per section.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";

const PRESETS = [
  { k: "today", l: "Today" }, { k: "yesterday", l: "Yesterday" },
  { k: "week", l: "This Week" }, { k: "month", l: "This Month" },
] as const;
const MISS_OPTS = [1, 2, 3, 5, 7, 15, 30];

const C = { green: "#16A34A", orange: "#D97706", red: "#DC2626" };
const BG = { green: "#F0FDF4", orange: "#FFFBEB", red: "#FEF2F2" };

function Bar({ pct, tone }: { pct: number; tone?: string }) {
  const t = tone || (pct >= 90 ? C.green : pct >= 70 ? C.orange : C.red);
  return (
    <View style={styles.barTrack}>
      <View style={[styles.barFill, { width: `${Math.min(100, pct)}%`, backgroundColor: t }]} />
    </View>
  );
}

export default function AttendanceSyncDashboard() {
  const { selectedCompanyId } = useSelectedCompany();
  const [preset, setPreset] = useState<string>("month");
  const [missDays, setMissDays] = useState(3);
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({ s4: true });
  const [busyExp, setBusyExp] = useState<string | null>(null);
  // Iter 514 — one-tap "Create Master from machine PIN".
  const [busyCreate, setBusyCreate] = useState<string | null>(null);
  const createMaster = (r: any) => {
    const key = `${r.machine}:${r.machine_id}`;
    const go = async () => {
      setBusyCreate(key);
      try {
        const res = await api<any>("/biometric/create-master-from-pin", {
          method: "POST",
          body: { device_serial: r.machine, device_user_id: String(r.machine_id) },
        });
        const msg = `${res.created ? "Employee created" : "Employee already existed"}: ${res.name}`
          + ` (code ${res.employee_code || "—"}, bio ${res.bio_code}).`
          + ` ${res.remapped} old punch(es) pulled into attendance.`
          + ` Complete phone / salary / DOJ in Employee Master.`;
        if (Platform.OS === "web") window.alert(msg); else Alert.alert("Done ✅", msg);
        load();
      } catch (e: any) {
        const m = e?.message || "Failed to create the employee.";
        if (Platform.OS === "web") window.alert(m); else Alert.alert("Failed", m);
      } finally {
        setBusyCreate(null);
      }
    };
    const q = `Create Employee Master for machine PIN ${r.machine_id} (${r.machine_name || r.machine}) and pull their old punches into attendance?`;
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && window.confirm(q)) go();
    } else {
      Alert.alert("Create Master", q, [
        { text: "Cancel", style: "cancel" },
        { text: "Create", onPress: go },
      ]);
    }
  };

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const p = new URLSearchParams({ preset, missing_days: String(missDays) });
      if (selectedCompanyId) p.set("company_id", selectedCompanyId);
      const r = await api<any>(`/admin/attendance-sync-dashboard?${p.toString()}`);
      setData(r);
    } catch (e: any) { setErr(e?.message || "Failed to load dashboard"); }
    finally { setLoading(false); }
  }, [preset, missDays, selectedCompanyId]);
  useEffect(() => { load(); }, [load]);

  const doExport = async (section: string, format: string) => {
    if (busyExp) return;
    setBusyExp(`${section}-${format}`);
    try {
      const p = new URLSearchParams({ section, format, preset, missing_days: String(missDays) });
      if (selectedCompanyId) p.set("company_id", selectedCompanyId);
      const r = await apiBinary(`/admin/attendance-sync-dashboard/export?${p.toString()}`);
      if (Platform.OS === "web" && r.webBlobUrl) window.open(r.webBlobUrl, "_blank");
    } catch (e: any) { setErr(e?.message || "Export failed"); }
    finally { setBusyExp(null); }
  };

  const k = data?.kpis || {};
  const filt = useCallback((rows: any[]) => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      String(r.name || "").toLowerCase().includes(q)
      || String(r.employee_code || r.machine_id || "").toLowerCase().includes(q));
  }, [query]);

  const kpiCards = useMemo(() => [
    { l: "Total Employees", v: k.total_employees, s: null },
    { l: "Machine Registered", v: k.machine_registered, s: null },
    { l: "Active Employees", v: k.active_employees, s: null },
    { l: "New Joining", v: k.new_joining, s: "s1", tone: C.green },
    { l: "Master Pending", v: k.master_pending, s: "s2", tone: C.red },
    { l: "Machine Pending", v: k.machine_pending, s: "s3", tone: C.orange },
    { l: "Attendance Missing", v: k.attendance_missing, s: "s4", tone: C.red },
    { l: "Never Punched", v: k.never_punched, s: "s4", tone: C.orange },
    { l: "Attendance %", v: `${k.attendance_pct ?? 0}%`, s: "s6" },
    { l: "Machine Sync %", v: `${k.machine_sync_pct ?? 0}%`, s: "s6m" },
    { l: "Master Sync %", v: `${k.master_sync_pct ?? 0}%`, s: "s6" },
    { l: "Overall Health", v: `${k.overall_health ?? 0}%`, s: "s6",
      tone: (k.overall_health ?? 0) >= 90 ? C.green : C.orange },
  ], [k]);

  const Section = ({ id, title, count, children, exportKey }: any) => (
    <View style={styles.card}>
      <Pressable style={styles.secHead} onPress={() => setOpen((p) => ({ ...p, [id]: !p[id] }))} testID={`asd-sec-${id}`}>
        <Ionicons name={open[id] ? "chevron-down" : "chevron-forward"} size={16} color={colors.onSurfaceSecondary} />
        <Text style={styles.secTitle}>{title}</Text>
        <View style={styles.countPill}><Text style={styles.countTxt}>{count}</Text></View>
        <View style={{ flex: 1 }} />
        {exportKey && open[id] ? ["xlsx", "pdf", "csv"].map((f) => (
          <Pressable key={f} onPress={() => doExport(exportKey, f)} style={styles.expBtn}
            testID={`asd-exp-${exportKey}-${f}`}>
            {busyExp === `${exportKey}-${f}`
              ? <ActivityIndicator size="small" color={colors.brandPrimary} />
              : <Text style={styles.expTxt}>{f.toUpperCase()}</Text>}
          </Pressable>
        )) : null}
      </Pressable>
      {open[id] ? children : null}
    </View>
  );

  const Row = ({ r, sub, right, color, onPress }: any) => (
    <Pressable onPress={onPress} style={[styles.row, color && { backgroundColor: BG[color as keyof typeof BG] }]}>
      <View style={[styles.dot, { backgroundColor: C[(color as keyof typeof C)] || colors.border }]} />
      <View style={{ flex: 1 }}>
        <Text style={styles.rowTitle} numberOfLines={1}>{r}</Text>
        {sub ? <Text style={styles.rowSub} numberOfLines={2}>{sub}</Text> : null}
      </View>
      {right ? <Text style={styles.rowRight}>{right}</Text> : null}
      {onPress ? <Ionicons name="chevron-forward" size={14} color={colors.onSurfaceTertiary} /> : null}
    </Pressable>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="arrow-back" size={20} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Attendance Synchronization Dashboard</Text>
          <Text style={styles.sub}>
            Master ⇄ Machine ⇄ Attendance reconciliation
            {data ? ` · ${data.range.from} → ${data.range.to}` : ""}
          </Text>
        </View>
        <Pressable onPress={() => doExport("full", "xlsx")} style={[styles.refresh, { flexDirection: "row", gap: 4, alignItems: "center" }]} testID="asd-full-xlsx">
          {busyExp === "full-xlsx" ? <ActivityIndicator size="small" color="#16A34A" /> : (
            <Ionicons name="document-outline" size={15} color="#16A34A" />
          )}
          <Text style={{ fontSize: 10, fontWeight: "800", color: "#16A34A" }}>EXCEL</Text>
        </Pressable>
        <Pressable onPress={() => doExport("full", "pdf")} style={[styles.refresh, { flexDirection: "row", gap: 4, alignItems: "center" }]} testID="asd-full-pdf">
          {busyExp === "full-pdf" ? <ActivityIndicator size="small" color="#DC2626" /> : (
            <Ionicons name="document-text-outline" size={15} color="#DC2626" />
          )}
          <Text style={{ fontSize: 10, fontWeight: "800", color: "#DC2626" }}>PDF</Text>
        </Pressable>
        <Pressable onPress={load} style={styles.refresh} testID="asd-refresh">
          <Ionicons name="refresh" size={16} color={colors.brandPrimary} />
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 90 }}>
        {/* Filters */}
        <View style={styles.filters}>
          {PRESETS.map((p) => (
            <Pressable key={p.k} onPress={() => setPreset(p.k)}
              style={[styles.chip, preset === p.k && styles.chipOn]} testID={`asd-preset-${p.k}`}>
              <Text style={[styles.chipTxt, preset === p.k && styles.chipTxtOn]}>{p.l}</Text>
            </Pressable>
          ))}
          <View style={{ width: 12 }} />
          <Text style={styles.filterLbl}>Missing ≥</Text>
          {MISS_OPTS.map((n) => (
            <Pressable key={n} onPress={() => setMissDays(n)}
              style={[styles.chip, missDays === n && styles.chipOn]} testID={`asd-miss-${n}`}>
              <Text style={[styles.chipTxt, missDays === n && styles.chipTxtOn]}>{n}d</Text>
            </Pressable>
          ))}
          <TextInput
            style={styles.search} placeholder="Search name / code…" value={query}
            onChangeText={setQuery} placeholderTextColor={colors.onSurfaceTertiary}
            testID="asd-search"
          />
        </View>

        {err ? <View style={styles.errBox}><Text style={{ color: C.red, fontSize: 12 }}>{err}</Text></View> : null}
        {loading && !data ? <ActivityIndicator style={{ marginTop: 50 }} color={colors.brandPrimary} /> : null}

        {data ? (
          <>
            {/* KPI cards */}
            <View style={styles.kpiWrap}>
              {kpiCards.map((c2) => (
                <Pressable key={c2.l} style={styles.kpi}
                  onPress={() => c2.s && setOpen((p) => ({ ...p, [c2.s === "s6m" ? "s6" : c2.s]: true }))}>
                  <Text style={[styles.kpiVal, c2.tone ? { color: c2.tone } : null]}>{c2.v ?? 0}</Text>
                  <Text style={styles.kpiLbl}>{c2.l}</Text>
                </Pressable>
              ))}
            </View>
            <Text style={styles.lastSync}>
              Last machine sync: {k.last_sync_at ? String(k.last_sync_at).replace("T", " ").slice(0, 16) : "—"}
              {"  ·  "}{k.machines_online}/{k.machines_total} machines online
            </Text>

            {/* Section 1 — New Joining */}
            <Section id="s1" title="1 · New Joining Report" count={data.new_joining.length} exportKey="new_joining">
              {filt(data.new_joining).slice(0, 60).map((r: any) => (
                <Row key={r.user_id}
                  r={`${r.employee_code || "—"} · ${r.name}`}
                  sub={`DOJ ${r.doj} · ${r.department || "—"} · ${r.company || ""}\n${r.remark}`}
                  right={r.status} color={r.color}
                  onPress={() => router.push(`/employee-detail-slip?user_id=${r.user_id}` as any)}
                />
              ))}
              {data.new_joining.length === 0 ? <Text style={styles.empty}>No joinings in this range.</Text> : null}
            </Section>

            {/* Section 2 — Machine only */}
            <Section id="s2" title="2 · Registered in Machine, NOT in Master" count={data.machine_only.length} exportKey="machine_only">
              {filt(data.machine_only).slice(0, 60).map((r: any, i: number) => (
                <View key={i}>
                  <Row
                    r={`Machine ID ${r.machine_id} · ${r.machine_name || r.machine}`}
                    sub={`Punches ${r.punch_count} · First ${r.first_punch} · Last ${r.last_punch}\n${r.remark}`}
                    right={r.suggested_match ? `≈ ${r.suggested_match}` : ""}
                    color="red"
                    onPress={() => router.push("/employee-add" as any)}
                  />
                  <Pressable
                    onPress={() => createMaster(r)}
                    disabled={!!busyCreate}
                    style={[styles.createBtn, busyCreate === `${r.machine}:${r.machine_id}` && { opacity: 0.6 }]}
                    testID={`asd-create-${r.machine}-${r.machine_id}`}
                  >
                    {busyCreate === `${r.machine}:${r.machine_id}` ? (
                      <ActivityIndicator size="small" color="#fff" />
                    ) : (
                      <>
                        <Ionicons name="person-add-outline" size={13} color="#fff" />
                        <Text style={styles.createTxt}>Create Master from PIN {r.machine_id}</Text>
                      </>
                    )}
                  </Pressable>
                </View>
              ))}
              {data.machine_only.length === 0 ? <Text style={styles.empty}>No unmapped machine users. ✓</Text> : null}
            </Section>

            {/* Section 3 — Master only */}
            <Section id="s3" title="3 · Registered in Master, NOT in Machine" count={data.master_only.length} exportKey="master_only">
              {filt(data.master_only).slice(0, 60).map((r: any) => (
                <Row key={r.user_id}
                  r={`${r.employee_code || "—"} · ${r.name}`}
                  sub={`${r.department || "—"} · DOJ ${r.doj || "—"} · ${r.days_since_joining} days since joining\n${r.remark}`}
                  right={r.machine_status} color="orange"
                  onPress={() => router.push("/biometric-devices" as any)}
                />
              ))}
              {data.master_only.length === 0 ? <Text style={styles.empty}>Everyone is machine-registered. ✓</Text> : null}
            </Section>

            {/* Section 4 — Attendance Missing */}
            <Section id="s4" title={`4 · In Both, Attendance Missing ≥ ${missDays} day(s)`}
              count={data.attendance_missing.length} exportKey="attendance_missing">
              {filt(data.attendance_missing).slice(0, 80).map((r: any) => (
                <Row key={r.user_id}
                  r={`${r.employee_code || "—"} · ${r.name}`}
                  sub={`${r.department || "—"} · Last punch ${r.last_punch || "NEVER"}${r.leave_status ? ` · On ${r.leave_status}` : ""}\n${r.remark}`}
                  right={r.never_punched ? "Never Punched" : `${r.days_missing}d missing`}
                  color={r.color}
                  onPress={() => router.push(`/employee-detail-slip?user_id=${r.user_id}` as any)}
                />
              ))}
              {data.attendance_missing.length === 0 ? <Text style={styles.empty}>No attendance gaps. ✓</Text> : null}
            </Section>

            {/* Section 5 — Continuous absence */}
            <Section id="s5" title="5 · Continuous Absence" count={Object.values(data.continuous_absence as Record<string, number>).reduce((a, b) => Math.max(a, b), 0)}>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, padding: 10 }}>
                {Object.entries(data.continuous_absence as Record<string, number>).map(([d, n]) => (
                  <View key={d} style={[styles.kpi, { minWidth: 100 }]}>
                    <Text style={[styles.kpiVal, { color: n > 0 ? C.red : C.green }]}>{n}</Text>
                    <Text style={styles.kpiLbl}>{d}+ days</Text>
                  </View>
                ))}
              </View>
              <Text style={[styles.empty, { paddingTop: 0 }]}>
                Approved leave, holidays and exited employees are flagged in Section 4 remarks.
              </Text>
            </Section>

            {/* Section 6 — Health */}
            <Section id="s6" title="6 · Attendance Health" count={`${k.overall_health}%`}>
              {[
                ["Attendance %", k.attendance_pct],
                ["Machine Registration %", k.master_sync_pct],
                ["Machine Sync %", k.machine_sync_pct],
                ["Attendance Compliance %", k.compliance_pct],
                ["Overall Health Score", k.overall_health],
              ].map(([l, v]: any) => (
                <View key={l} style={{ paddingHorizontal: 12, paddingVertical: 6 }}>
                  <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                    <Text style={styles.rowSub}>{l}</Text>
                    <Text style={[styles.rowTitle, { fontSize: 12 }]}>{v}%</Text>
                  </View>
                  <Bar pct={Number(v || 0)} />
                </View>
              ))}
              {/* Machines */}
              <Text style={[styles.secTitle, { paddingHorizontal: 12, paddingTop: 10, fontSize: 12 }]}>Machine Synchronization</Text>
              {(data.machines || []).map((m: any) => (
                <Row key={m.serial_number}
                  r={`${m.name || m.serial_number} (${m.serial_number})${m.connection_mode === "sdk" ? " · SDK PULL" : ""}`}
                  sub={m.connection_mode === "sdk"
                    ? (m.remark || `${m.sdk_vendor || "SDK"} · last pull ${String(m.sdk_last_pull_at || "never").replace("T", " ").slice(0, 16)}${m.auto_pull_minutes ? ` · auto every ${m.auto_pull_minutes} min` : " · manual"}`)
                    : (m.remark || `Last seen ${String(m.last_seen_at || "never").replace("T", " ").slice(0, 16)}`)}
                  right={m.connection_mode === "sdk" ? (m.online ? "PULL OK" : "CHECK") : (m.online ? "ONLINE" : "OFFLINE")}
                  color={m.online ? "green" : "red"}
                  onPress={() => router.push("/biometric-devices" as any)}
                />
              ))}
            </Section>

            {/* Section 7 — Trend */}
            <Section id="s7" title="7 · Monthly Trend" count={"14d"}>
              <Text style={[styles.rowSub, { paddingHorizontal: 12 }]}>Daily punch % (last 14 days)</Text>
              <View style={styles.trendRow}>
                {(data.trend?.daily_punch_pct || []).map((d: any) => (
                  <View key={d.date} style={{ alignItems: "center", flex: 1 }}>
                    <View style={[styles.trendBar, {
                      height: Math.max(3, d.pct * 0.7),
                      backgroundColor: d.pct >= 70 ? C.green : d.pct >= 40 ? C.orange : C.red,
                    }]} />
                    <Text style={styles.trendLbl}>{d.date.slice(8)}</Text>
                  </View>
                ))}
              </View>
              <Text style={[styles.rowSub, { paddingHorizontal: 12, paddingTop: 8 }]}>Weekly joinings (last 8 weeks)</Text>
              <View style={styles.trendRow}>
                {(data.trend?.weekly_joins || []).map((w: any) => (
                  <View key={w.week} style={{ alignItems: "center", flex: 1 }}>
                    <View style={[styles.trendBar, {
                      height: Math.max(3, Math.min(70, w.joins * 10)),
                      backgroundColor: colors.brandPrimary,
                    }]} />
                    <Text style={styles.trendLbl}>{w.week.slice(5)}</Text>
                  </View>
                ))}
              </View>
            </Section>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  // Iter 514 — one-tap Create Master button under machine-only rows.
  createBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: "#DC2626", borderRadius: 8, paddingVertical: 8,
    marginHorizontal: 12, marginBottom: 8, minHeight: 34,
  },
  createTxt: { color: "#fff", fontSize: 12, fontWeight: "800" },
  safe: { flex: 1, backgroundColor: "#F4F7FB" },
  header: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingHorizontal: spacing.lg, paddingVertical: 12,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 1 },
  refresh: { padding: 8, borderRadius: 8, borderWidth: 1, borderColor: colors.border },
  filters: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap", marginBottom: 12 },
  filterLbl: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  chip: {
    paddingHorizontal: 11, paddingVertical: 6, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  search: {
    flexGrow: 1, minWidth: 150, borderWidth: 1, borderColor: colors.border,
    borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, fontSize: 12,
    backgroundColor: colors.surface, color: colors.onSurface,
  },
  errBox: { backgroundColor: "#FEE2E2", borderRadius: radius.md, padding: 10, marginBottom: 10 },
  kpiWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  kpi: {
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, paddingVertical: 10, paddingHorizontal: 12,
    minWidth: 118, flexGrow: 1, alignItems: "center",
  },
  kpiVal: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  kpiLbl: { fontSize: 10, color: colors.onSurfaceSecondary, marginTop: 2, textAlign: "center" },
  lastSync: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 8, marginBottom: 4 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, marginTop: 12, overflow: "hidden",
  },
  secHead: { flexDirection: "row", alignItems: "center", gap: 8, padding: 12 },
  secTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  countPill: {
    backgroundColor: "#EFF6FF", borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2,
  },
  countTxt: { fontSize: 11, fontWeight: "800", color: "#1D4ED8" },
  expBtn: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 6,
    paddingHorizontal: 8, paddingVertical: 4, marginLeft: 4,
  },
  expTxt: { fontSize: 9.5, fontWeight: "800", color: colors.brandPrimary },
  row: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 12, paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border,
  },
  dot: { width: 8, height: 8, borderRadius: 4 },
  rowTitle: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  rowSub: { fontSize: 10.5, color: colors.onSurfaceSecondary, marginTop: 1 },
  rowRight: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceSecondary },
  empty: { fontSize: 11.5, color: colors.onSurfaceTertiary, padding: 12 },
  barTrack: { height: 8, borderRadius: 4, backgroundColor: "#E2E8F0", marginTop: 4 },
  barFill: { height: 8, borderRadius: 4 },
  trendRow: {
    flexDirection: "row", alignItems: "flex-end", gap: 3,
    paddingHorizontal: 12, paddingVertical: 8, height: 100,
  },
  trendBar: { width: "70%", borderRadius: 3 },
  trendLbl: { fontSize: 8, color: colors.onSurfaceTertiary, marginTop: 2 },
});
