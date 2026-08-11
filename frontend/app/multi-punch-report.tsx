/**
 * Iter 545 (user spec) — MULTIPLE PUNCH REPORT.
 *
 * Two tabs:
 *   • Punch Register — per employee-day: every counted punch, IN→OUT
 *     pairs, Duty / Break / OT hours and "Punches n / max" against the
 *     firm's Attendance Punch Policy.
 *   • Exceptions — the Punch Exception Log (max limit exceeded, invalid
 *     sequence, duplicate IN/OUT …) with full policy context.
 * Read-only — attendance/payroll are never modified from this screen.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius } from "@/src/theme";

type PunchRow = {
  user_id: string;
  employee_code?: string;
  name?: string;
  date: string;
  punches: { time: string; kind: "in" | "out"; source?: string; status?: string }[];
  pairs: { in: string; out: string; minutes: number }[];
  unpaired: number;
  duty_hhmm: string;
  break_hhmm: string;
  ot_hhmm: string;
  punch_count: number;
  max_allowed?: number | null;
  limit_reached: boolean;
  exception_count: number;
};

type ExcRow = {
  exception_id: string;
  employee_code?: string;
  name?: string;
  date: string;
  at: string;
  kind: string;
  exception_type: string;
  reason: string;
  max_punches_allowed?: number;
  existing_punch_count?: number;
  source?: string;
  created_at?: string;
};

const EXC_LABEL: Record<string, string> = {
  max_punch_limit: "Max Punch Limit Exceeded",
  multiple_punch_not_allowed: "Multiple Punch Not Allowed",
  duplicate_in: "Duplicate IN Punch",
  duplicate_out: "Duplicate OUT Punch",
  missing_in: "OUT Without IN (Invalid Sequence)",
};

const dmy = (iso: string) => (iso || "").split("-").reverse().join("-");

export default function MultiPunchReportScreen() {
  const router = useRouter();
  const { selectedCompanyId, companies } = useSelectedCompany() as any;
  const [firmId, setFirmId] = useState<string>(selectedCompanyId || "");
  const [month, setMonth] = useState<string>(() => new Date().toISOString().slice(0, 7));
  const [tab, setTab] = useState<"punches" | "exceptions">("punches");
  const [onlyMultiple, setOnlyMultiple] = useState(true);
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<PunchRow[]>([]);
  const [excRows, setExcRows] = useState<ExcRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!firmId && selectedCompanyId) setFirmId(selectedCompanyId);
  }, [selectedCompanyId, firmId]);

  const load = useCallback(async () => {
    if (!firmId || !/^\d{4}-\d{2}$/.test(month)) return;
    setLoading(true);
    setErr("");
    try {
      const [r, e] = await Promise.all([
        api<{ rows: PunchRow[] }>(
          `/admin/multi-punch/report?company_id=${firmId}&month=${month}&only_multiple=${onlyMultiple}`,
        ),
        api<{ rows: ExcRow[] }>(
          `/admin/multi-punch/exceptions?company_id=${firmId}&month=${month}`,
        ),
      ]);
      setRows(r.rows || []);
      setExcRows(e.rows || []);
    } catch (x: any) {
      setErr(x?.message || "Failed to load report");
    } finally {
      setLoading(false);
    }
  }, [firmId, month, onlyMultiple]);

  useEffect(() => {
    load();
  }, [load]);

  const q = query.trim().toLowerCase();
  const vRows = q
    ? rows.filter((r) =>
        (r.name || "").toLowerCase().includes(q) ||
        String(r.employee_code || "").toLowerCase().includes(q))
    : rows;
  const vExc = q
    ? excRows.filter((r) =>
        (r.name || "").toLowerCase().includes(q) ||
        String(r.employee_code || "").toLowerCase().includes(q))
    : excRows;

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={8}>
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={st.h1}>Multiple Punch Report</Text>
        <View style={{ width: 24 }} />
      </View>

      {/* Filters */}
      <View style={st.filters}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ maxHeight: 38 }}>
          {(companies || []).map((c: any) => (
            <Pressable
              key={c.company_id}
              onPress={() => setFirmId(c.company_id)}
              style={[st.firmChip, firmId === c.company_id && st.firmChipOn]}
              testID={`mpr-firm-${c.company_id}`}
            >
              <Text style={[st.firmChipTxt, firmId === c.company_id && { color: "#fff" }]} numberOfLines={1}>
                {c.name}
              </Text>
            </Pressable>
          ))}
        </ScrollView>
        <View style={st.filterRow}>
          <TextInput
            style={st.monthInput}
            value={month}
            onChangeText={setMonth}
            placeholder="YYYY-MM"
            placeholderTextColor={colors.onSurfaceTertiary}
            maxLength={7}
            testID="mpr-month"
          />
          <TextInput
            style={[st.monthInput, { flex: 1 }]}
            value={query}
            onChangeText={setQuery}
            placeholder="Search employee / code"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID="mpr-search"
          />
          <Pressable onPress={load} style={st.goBtn} disabled={loading} testID="mpr-load">
            <Ionicons name="refresh" size={16} color="#fff" />
          </Pressable>
        </View>
        <View style={st.tabRow}>
          <Pressable
            onPress={() => setTab("punches")}
            style={[st.tabBtn, tab === "punches" && st.tabBtnOn]}
            testID="mpr-tab-punches"
          >
            <Text style={[st.tabTxt, tab === "punches" && { color: "#fff" }]}>
              Punch Register ({vRows.length})
            </Text>
          </Pressable>
          <Pressable
            onPress={() => setTab("exceptions")}
            style={[st.tabBtn, tab === "exceptions" && st.tabBtnOn]}
            testID="mpr-tab-exceptions"
          >
            <Text style={[st.tabTxt, tab === "exceptions" && { color: "#fff" }]}>
              Exceptions ({vExc.length})
            </Text>
          </Pressable>
          {tab === "punches" && (
            <Pressable
              onPress={() => setOnlyMultiple((v) => !v)}
              style={[st.togglePill, !onlyMultiple && st.togglePillOn]}
              testID="mpr-only-multiple"
            >
              <Ionicons
                name={onlyMultiple ? "filter" : "filter-outline"}
                size={12}
                color={onlyMultiple ? colors.brandPrimary : "#fff"}
              />
              <Text style={[st.toggleTxt, !onlyMultiple && { color: "#fff" }]}>
                {onlyMultiple ? "Multi-punch days only" : "All punched days"}
              </Text>
            </Pressable>
          )}
        </View>
      </View>

      {err ? <Text style={st.errTxt}>{err}</Text> : null}

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 10, paddingBottom: 40 }}>
        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
        ) : tab === "punches" ? (
          vRows.length === 0 ? (
            <Text style={st.emptyTxt}>
              No {onlyMultiple ? "multi-punch " : "punched "}days found for {month}.
            </Text>
          ) : (
            vRows.map((r) => (
              <View key={`${r.user_id}_${r.date}`} style={st.card} testID={`mpr-row-${r.user_id}-${r.date}`}>
                <View style={st.cardHead}>
                  <Text style={st.empName} numberOfLines={1}>
                    {r.name} {r.employee_code ? `· ${r.employee_code}` : ""}
                  </Text>
                  <Text style={st.dateTxt}>{dmy(r.date)}</Text>
                </View>
                <View style={st.punchChips}>
                  {r.punches.map((p, i) => (
                    <View key={i} style={[st.pChip, p.kind === "in" ? st.pChipIn : st.pChipOut]}>
                      <Text style={st.pChipTxt}>
                        {p.kind.toUpperCase()} {p.time}
                      </Text>
                    </View>
                  ))}
                </View>
                <View style={st.statRow}>
                  <Text style={st.statTxt}>Duty {r.duty_hhmm}</Text>
                  <Text style={st.statTxt}>Break {r.break_hhmm}</Text>
                  <Text style={[st.statTxt, r.ot_hhmm !== "00:00" && { color: "#B45309" }]}>
                    OT {r.ot_hhmm}
                  </Text>
                  <View style={[st.countPill, r.limit_reached && st.countPillMax]}>
                    <Text style={[st.countPillTxt, r.limit_reached && { color: "#fff" }]}>
                      Punches: {r.punch_count} / {r.max_allowed || "∞"}
                    </Text>
                  </View>
                  {r.unpaired > 0 && (
                    <Text style={st.warnTxt}>⚠ {r.unpaired} unpaired</Text>
                  )}
                  {r.exception_count > 0 && (
                    <Text style={st.excBadge}>⛔ {r.exception_count} exception{r.exception_count > 1 ? "s" : ""}</Text>
                  )}
                </View>
              </View>
            ))
          )
        ) : vExc.length === 0 ? (
          <Text style={st.emptyTxt}>No punch exceptions recorded for {month}. 🎉</Text>
        ) : (
          vExc.map((e) => (
            <View key={e.exception_id} style={st.card} testID={`mpr-exc-${e.exception_id}`}>
              <View style={st.cardHead}>
                <Text style={st.empName} numberOfLines={1}>
                  {e.name} {e.employee_code ? `· ${e.employee_code}` : ""}
                </Text>
                <Text style={st.dateTxt}>{dmy(e.date)} {String(e.at || "").slice(11, 16)}</Text>
              </View>
              <View style={st.excTypeRow}>
                <View style={st.excTypePill}>
                  <Text style={st.excTypeTxt}>
                    {EXC_LABEL[e.exception_type] || e.exception_type}
                  </Text>
                </View>
                <View style={[st.pChip, e.kind === "in" ? st.pChipIn : st.pChipOut]}>
                  <Text style={st.pChipTxt}>{String(e.kind || "").toUpperCase()}</Text>
                </View>
              </View>
              <Text style={st.reasonTxt}>{e.reason}</Text>
              <Text style={st.metaTxt}>
                {e.max_punches_allowed ? `Max allowed: ${e.max_punches_allowed} · ` : ""}
                {e.existing_punch_count != null ? `Existing punches: ${e.existing_punch_count} · ` : ""}
                Source: {e.source || "app"}
              </Text>
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 12, paddingVertical: 10,
  },
  h1: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  filters: { paddingHorizontal: 10, gap: 8 },
  firmChip: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 7, marginRight: 6,
    backgroundColor: colors.surface, maxWidth: 220,
  },
  firmChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  firmChipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  filterRow: { flexDirection: "row", gap: 8, alignItems: "center" },
  monthInput: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: Platform.OS === "web" ? 8 : 6,
    fontSize: 13, color: colors.onSurface, backgroundColor: colors.surface,
    minWidth: 90,
  },
  goBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    padding: 9, alignItems: "center", justifyContent: "center",
  },
  tabRow: { flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" },
  tabBtn: {
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 14, paddingVertical: 7,
  },
  tabBtnOn: { backgroundColor: colors.brandPrimary },
  tabTxt: { fontSize: 12, fontWeight: "800", color: colors.brandPrimary },
  togglePill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 6,
  },
  togglePillOn: { backgroundColor: colors.brandPrimary },
  toggleTxt: { fontSize: 11, fontWeight: "700", color: colors.brandPrimary },
  errTxt: { color: "#DC2626", fontSize: 12, paddingHorizontal: 12, paddingTop: 6 },
  emptyTxt: {
    textAlign: "center", marginTop: 40, fontSize: 13,
    color: colors.onSurfaceTertiary,
  },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.divider,
    padding: 10, marginBottom: 8,
  },
  cardHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  empName: { fontSize: 13, fontWeight: "800", color: colors.onSurface, flex: 1 },
  dateTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  punchChips: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 },
  pChip: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 },
  pChipIn: { backgroundColor: "#DCFCE7" },
  pChipOut: { backgroundColor: "#FEE2E2" },
  pChipTxt: { fontSize: 11, fontWeight: "800", color: "#374151" },
  statRow: {
    flexDirection: "row", flexWrap: "wrap", gap: 10,
    marginTop: 8, alignItems: "center",
  },
  statTxt: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  countPill: {
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 8, paddingVertical: 3,
  },
  countPillMax: { backgroundColor: "#DC2626", borderColor: "#DC2626" },
  countPillTxt: { fontSize: 10.5, fontWeight: "800", color: colors.brandPrimary },
  warnTxt: { fontSize: 11, fontWeight: "700", color: "#B45309" },
  excBadge: { fontSize: 11, fontWeight: "800", color: "#DC2626" },
  excTypeRow: { flexDirection: "row", gap: 6, marginTop: 8, alignItems: "center" },
  excTypePill: {
    backgroundColor: "#FEF3C7", borderRadius: 6,
    paddingHorizontal: 8, paddingVertical: 4,
  },
  excTypeTxt: { fontSize: 11, fontWeight: "800", color: "#92400E" },
  reasonTxt: { fontSize: 12, color: colors.onSurface, marginTop: 6, lineHeight: 17 },
  metaTxt: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 4 },
});
