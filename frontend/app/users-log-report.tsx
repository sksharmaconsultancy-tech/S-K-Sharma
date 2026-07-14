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
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";
import { formatDateTime } from "@/src/utils/date";
import DateField from "@/src/components/DateField";

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

  const actors = useMemo(() => {
    const map = new Map<string, { name: string; role: string }>();
    for (const e of events) {
      if (e.actor_id && !map.has(e.actor_id)) {
        map.set(e.actor_id, { name: e.actor_name || "—", role: e.actor_role || "" });
      }
    }
    return Array.from(map.entries()).map(([id, v]) => ({ id, ...v }));
  }, [events]);

  // Performance chart — per-admin action counts grouped by category.
  const perf = useMemo(() => {
    type Row = {
      id: string; name: string; role: string;
      punch: number; salary: number; compliance: number; other: number; total: number;
    };
    const map = new Map<string, Row>();
    for (const e of events) {
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
  }, [events]);

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
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Filters</Text>
          <View style={styles.filterRow}>
            <View style={styles.filterCol}>
              <Text style={styles.label}>Quick period</Text>
              <View style={styles.chipStrip}>
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
                <Text style={styles.label}>Firm</Text>
                <View style={styles.chipStrip}>
                  <Chip
                    label="All firms"
                    active={!firmId}
                    onPress={() => setFirmId("")}
                  />
                  {(companies || []).map((c) => (
                    <Chip
                      key={c.company_id}
                      label={c.name || c.company_id}
                      active={firmId === c.company_id}
                      onPress={() => setFirmId(c.company_id)}
                    />
                  ))}
                </View>
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

          <Pressable
            onPress={fetchLog}
            disabled={loading}
            style={[styles.primaryBtn, loading && { opacity: 0.6 }]}
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

        <View style={styles.card}>
          <Text style={styles.cardTitle}>
            Log entries · {events.length}
          </Text>
          {events.length === 0 && !loading ? (
            <Text style={styles.smallHint}>
              No log entries for the selected filters. Try widening the date
              range or clearing the firm / user filter.
            </Text>
          ) : null}
          {events.map((e, idx) => (
            <View key={idx} style={styles.logRow}>
              <View style={styles.logIcon}>
                <Ionicons
                  name={
                    (e.action || "").startsWith("punch") ? "finger-print-outline"
                    : (e.action || "").startsWith("salary") ? "cash-outline"
                    : (e.action || "").startsWith("compliance") ? "shield-checkmark-outline"
                    : "document-text-outline"
                  }
                  size={16}
                  color={colors.brandPrimary}
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.logAction}>{e.action || "—"}</Text>
                <Text style={styles.logMeta}>
                  {e.actor_name || "—"}
                  {e.actor_role ? ` (${e.actor_role})` : ""}
                  {"  ·  "}
                  {e.company_name || "—"}
                </Text>
                {e.details ? (
                  <Text style={styles.logDetails}>{e.details}</Text>
                ) : null}
              </View>
              <Text style={styles.logAt}>{formatDateTime(e.at)}</Text>
            </View>
          ))}
        </View>
        <View style={{ height: 40 }} />
      </ScrollView>
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
  logIcon: {
    width: 30, height: 30, borderRadius: 15,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
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
