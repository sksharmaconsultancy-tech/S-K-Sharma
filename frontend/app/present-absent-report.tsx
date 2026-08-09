/**
 * Present / Absent Report — Iter 521 (user request).
 *
 * P / HD / A / WO / H status matrix per employee per day, computed by the
 * SAME policy engine as the Attendance Grid (so it matches payroll's
 * policy-based Present Days 1:1). Excel + PDF exports.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text,
  TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Stack } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors } from "@/src/theme";

const currentMonth = () => new Date().toISOString().slice(0, 7);

const ST_UI: Record<string, { bg: string; fg: string }> = {
  P: { bg: "#DCFCE7", fg: "#166534" },
  HD: { bg: "#FEF9C3", fg: "#854D0E" },
  A: { bg: "#FEE2E2", fg: "#991B1B" },
  WO: { bg: "#E0F2FE", fg: "#075985" },
  H: { bg: "#FED7AA", fg: "#9A3412" },
};

export default function PresentAbsentReport() {
  const { user } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [cid, setCid] = useState("");
  const [month, setMonth] = useState(currentMonth());
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("");
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [exporting, setExporting] = useState("");
  // Iter 533 (user request) — NEW format selector. "old" keeps the
  // existing report 100% unchanged; "ot" opens the new 2-row-per-employee
  // "Present / Absent + Daily OT" report (separate endpoints).
  const [fmt, setFmt] = useState<"old" | "ot">("old");

  useEffect(() => {
    if (user?.role === "company_admin") setCid(user.company_id || "");
    else if (selectedCompanyId && selectedCompanyId !== "all") setCid(selectedCompanyId);
  }, [user, selectedCompanyId]);

  const qs = useMemo(() => {
    const p = new URLSearchParams({ month });
    if (cid) p.set("company_id", cid);
    if (q.trim()) p.set("search", q.trim());
    if (dept) p.set("department", dept);
    return p.toString();
  }, [cid, month, q, dept]);

  const load = useCallback(async () => {
    if (!cid || !/^\d{4}-\d{2}$/.test(month)) return;
    setLoading(true);
    setErr("");
    try {
      const r = await api<any>(fmt === "ot"
        ? `/admin/reports/present-absent-ot?${qs}`
        : `/admin/reports/present-absent?${qs}`);
      setData(r);
    } catch (e: any) {
      setErr(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [cid, month, qs, fmt]);

  useEffect(() => { load(); }, [load]);

  const doExport = async (kind: "xlsx" | "pdf") => {
    if (!cid) return;
    setExporting(kind);
    try {
      const r = await apiBinary(fmt === "ot"
        ? `/admin/reports/present-absent-ot.${kind}?${qs}`
        : `/admin/reports/present-absent.${kind}?${qs}`);
      if (Platform.OS === "web" && r.webBlobUrl) {
        if (kind === "pdf") window.open(r.webBlobUrl, "_blank");
        else {
          const a = document.createElement("a");
          a.href = r.webBlobUrl;
          a.download = `present-absent-${month}.${kind}`;
          a.click();
        }
      }
    } catch (e: any) {
      setErr(e?.message || "Export failed");
    } finally {
      setExporting("");
    }
  };

  const emps = data?.employees || [];
  const dayLabels: string[] = data?.day_labels || [];

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <Stack.Screen options={{ title: "Present / Absent Report" }} />
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 12 }}>
        <Text style={s.title}>Present / Absent Report</Text>
        <Text style={s.sub}>As per the Firm Attendance Policy — matches payroll Present Days 1:1</Text>

        {user?.role !== "company_admin" ? (
          <View style={{ marginTop: 8 }}>
            <CompanyPicker
              value={cid || "all"}
              onChange={(v) => setCid(v === "all" ? "" : v)}
              allowAll={false}
              label="Firm"
              testID="par-firm-dd"
            />
          </View>
        ) : null}

        {/* Iter 533 — Report Format selector (old report untouched) */}
        <View style={{ flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
          {([["old", "Existing Present / Absent Report"],
            ["ot", "Present / Absent + Daily OT Report"]] as const).map(([k, lbl]) => (
            <Pressable key={k} onPress={() => setFmt(k)}
              style={[s.chip, fmt === k && s.chipOn]} testID={`par-fmt-${k}`}>
              <Text style={[s.chipTxt, fmt === k && { color: "#fff" }]}>{lbl}</Text>
            </Pressable>
          ))}
        </View>

        <View style={s.filterRow}>
          <TextInput
            value={month} onChangeText={setMonth} placeholder="YYYY-MM"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={[s.input, { maxWidth: 110 }]} testID="par-month" />
          <TextInput
            value={q} onChangeText={setQ} placeholder="Search name / code…"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={[s.input, { flex: 1 }]} testID="par-search" />
          {(["xlsx", "pdf"] as const).map((k) => (
            <Pressable key={k} onPress={() => doExport(k)} style={s.expBtn}
              testID={`par-export-${k}`}>
              {exporting === k ? <ActivityIndicator size="small" color="#fff" /> : (
                <Text style={s.expTxt}>{k === "xlsx" ? "Excel" : "PDF"}</Text>
              )}
            </Pressable>
          ))}
        </View>

        {(data?.departments || []).length > 0 ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
            <View style={{ flexDirection: "row", gap: 6 }}>
              <Pressable onPress={() => setDept("")}
                style={[s.chip, !dept && s.chipOn]}>
                <Text style={[s.chipTxt, !dept && { color: "#fff" }]}>All Departments</Text>
              </Pressable>
              {(data.departments as string[]).map((dp) => (
                <Pressable key={dp} onPress={() => setDept(dp === dept ? "" : dp)}
                  style={[s.chip, dept === dp && s.chipOn]}>
                  <Text style={[s.chipTxt, dept === dp && { color: "#fff" }]}>{dp}</Text>
                </Pressable>
              ))}
            </View>
          </ScrollView>
        ) : null}

        {data?.policy_line ? <Text style={s.policyTxt}>{data.policy_line}</Text> : null}
        {err ? <Text style={s.err}>{err}</Text> : null}
        {loading ? <ActivityIndicator style={{ marginTop: 20 }} color={colors.brandPrimary} /> : null}

        {!loading && data && !emps.length ? (
          <Text style={s.empty}>No employees found for {month}.</Text>
        ) : null}

        {!loading && emps.length ? (
          <ScrollView horizontal showsHorizontalScrollIndicator style={{ marginTop: 10 }}>
            <View>
              {/* header */}
              <View style={s.row}>
                <View style={[s.nameCell, s.hCell]}><Text style={s.hTxt}>Employee</Text></View>
                {dayLabels.map((dl, i) => (
                  <View key={dl} style={[s.dayCell, s.hCell]}>
                    <Text style={s.hTxt}>{parseInt(String(dl).slice(0, 2), 10)}</Text>
                    <Text style={s.wdTxt}>{(data.weekday_labels || [])[i] || ""}</Text>
                  </View>
                ))}
                {["P", "HD", "A", "WO", "H", "Days"].map((t) => (
                  <View key={t} style={[s.totCell, s.hCell]}><Text style={s.hTxt}>{t}</Text></View>
                ))}
              </View>
              {emps.map((e: any) => (
                <View key={e.employee_code || e.name} style={s.row}>
                  <View style={s.nameCell}>
                    <Text style={s.nameTxt} numberOfLines={1}>
                      {e.employee_code ? `${e.employee_code} · ` : ""}{e.name}
                    </Text>
                    {e.department ? <Text style={s.depTxt} numberOfLines={1}>{e.department}</Text> : null}
                  </View>
                  {dayLabels.map((dl) => {
                    const st = e.days?.[dl] || "";
                    const ui = ST_UI[st];
                    return (
                      <View key={dl} style={[s.dayCell, ui && { backgroundColor: ui.bg }]}>
                        <Text style={[s.stTxt, ui && { color: ui.fg }]}>{st}</Text>
                      </View>
                    );
                  })}
                  {["P", "HD", "A", "WO", "H"].map((k) => (
                    <View key={k} style={s.totCell}><Text style={s.totTxt}>{e.totals?.[k] ?? 0}</Text></View>
                  ))}
                  <View style={s.totCell}><Text style={[s.totTxt, { color: "#166534" }]}>{e.present_days}</Text></View>
                </View>
              ))}
              {/* daily present footer */}
              <View style={[s.row, { backgroundColor: "#F1F5F9" }]}>
                <View style={s.nameCell}><Text style={[s.nameTxt, { fontWeight: "800" }]}>Daily Present (P + HD)</Text></View>
                {dayLabels.map((dl) => {
                  const dc = data.day_counts?.[dl] || {};
                  return (
                    <View key={dl} style={s.dayCell}>
                      <Text style={[s.stTxt, { fontWeight: "800", color: "#0F3B5C" }]}>
                        {(dc.P || 0) + (dc.HD || 0)}
                      </Text>
                    </View>
                  );
                })}
                {["P", "HD", "A", "WO", "H"].map((k) => (
                  <View key={k} style={s.totCell}>
                    <Text style={[s.totTxt, { fontWeight: "800" }]}>{data.grand_totals?.[k] ?? 0}</Text>
                  </View>
                ))}
                <View style={s.totCell} />
              </View>
            </View>
          </ScrollView>
        ) : null}

        {!loading && emps.length ? (
          <View style={s.legend}>
            {Object.entries(ST_UI).map(([k, ui]) => (
              <View key={k} style={[s.legItem, { backgroundColor: ui.bg }]}>
                <Text style={[s.legTxt, { color: ui.fg }]}>
                  {k} = {{ P: "Present", HD: "Half Day", A: "Absent", WO: "Weekly Off", H: "Holiday" }[k]}
                </Text>
              </View>
            ))}
          </View>
        ) : null}
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  title: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  filterRow: { flexDirection: "row", gap: 8, marginTop: 10, alignItems: "center" },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  expBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 14, paddingVertical: 9, minWidth: 60, alignItems: "center",
  },
  expTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  chip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 6, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, color: colors.onSurface, fontWeight: "600" },
  policyTxt: {
    color: "#0F3B5C", fontSize: 11.5, fontWeight: "700", marginTop: 10,
    backgroundColor: "#EFF6FF", borderRadius: 8, paddingHorizontal: 10,
    paddingVertical: 6, borderWidth: 1, borderColor: "#BFDBFE",
  },
  err: { color: "#B91C1C", marginTop: 10, fontSize: 12.5 },
  empty: { color: colors.onSurfaceTertiary, marginTop: 20, textAlign: "center" },
  row: { flexDirection: "row" },
  hCell: { backgroundColor: "#0F3B5C" },
  hTxt: { color: "#fff", fontSize: 10, fontWeight: "800", textAlign: "center" },
  wdTxt: { color: "#BFDBFE", fontSize: 8, textAlign: "center" },
  nameCell: {
    width: 190, borderWidth: 0.5, borderColor: "#CBD5E1", paddingHorizontal: 6,
    paddingVertical: 4, justifyContent: "center", backgroundColor: colors.surface,
  },
  nameTxt: { fontSize: 11, color: colors.onSurface, fontWeight: "600" },
  depTxt: { fontSize: 9, color: colors.onSurfaceTertiary },
  dayCell: {
    width: 30, borderWidth: 0.5, borderColor: "#CBD5E1", alignItems: "center",
    justifyContent: "center", paddingVertical: 4, backgroundColor: colors.surface,
  },
  stTxt: { fontSize: 9.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  totCell: {
    width: 42, borderWidth: 0.5, borderColor: "#CBD5E1", alignItems: "center",
    justifyContent: "center", paddingVertical: 4, backgroundColor: colors.surface,
  },
  totTxt: { fontSize: 10.5, fontWeight: "700", color: colors.onSurface },
  legend: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 12 },
  legItem: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 },
  legTxt: { fontSize: 10.5, fontWeight: "700" },
});
