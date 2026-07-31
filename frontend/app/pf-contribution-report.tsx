/**
 * Iter 408 (user spec) — PF Contribution Reports (Higher PF / VPF).
 * One screen, five views: All Types / Higher PF / VPF / Approval Pending /
 * PF Difference. Excel + PDF export. Source = latest Compliance Salary run.
 */
import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { api, apiBinary } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import MonthPicker from "@/src/components/MonthPicker";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, spacing, type } from "@/src/theme";

const VIEWS: [string, string][] = [
  ["all", "All Types"], ["higher", "Higher PF"], ["vpf", "VPF"],
  ["pending", "Approval Pending"], ["diff", "PF Difference"],
];

const HEADERS = [
  "Emp Code", "Name", "UAN", "Type", "Approval", "Declaration", "Gross",
  "PF Wages", "Ceiling?", "Higher Wage", "PF (E)", "VPF", "EPF (ER)",
  "EPS (ER)", "ER Total", "Statutory PF", "Diff",
];
const KEYS = [
  "employee_code", "name", "uan_no", "pf_contribution_type",
  "pf_approval_status", "pf_declaration_available", "gross_paid", "pf_wages",
  "pf_ceiling_applied", "higher_pf_wage", "pf_employee", "vpf_part",
  "pf_employer_epf", "pf_employer_eps", "pf_employer_total", "statutory_pf",
  "pf_diff",
];

function defaultMonth() {
  return new Date().toISOString().slice(0, 7);
}

export default function PfContributionReport() {
  const { selectedCompanyId, setSelectedCompanyId } = useSelectedCompany();
  const companyId = selectedCompanyId;
  const setCompanyId = setSelectedCompanyId;
  const [month, setMonth] = useState(defaultMonth());
  const [view, setView] = useState("all");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState("");
  const [err, setErr] = useState("");

  const qs = useMemo(() => {
    const p = new URLSearchParams();
    p.set("company_id", companyId || "");
    p.set("month", month);
    p.set("view", view);
    return p.toString();
  }, [companyId, month, view]);

  const load = useCallback(async () => {
    if (!companyId || companyId === "all") { setData(null); return; }
    setLoading(true);
    setErr("");
    try {
      setData(await api<any>(`/admin/reports/pf-contribution?${qs}`));
    } catch (e: any) {
      setErr(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [companyId, qs]);

  useEffect(() => { load(); }, [load]);

  const doExport = async (kind: "xlsx" | "pdf") => {
    if (!companyId) return;
    setExporting(kind);
    try {
      const r = await apiBinary(`/admin/reports/pf-contribution.${kind}?${qs}`);
      if (Platform.OS === "web" && r.webBlobUrl) {
        if (kind === "pdf") window.open(r.webBlobUrl, "_blank");
        else {
          const a = document.createElement("a");
          a.href = r.webBlobUrl;
          a.download = `pf-contribution-${view}-${month}.xlsx`;
          a.click();
        }
      }
    } catch (e: any) {
      setErr(e?.message || "Export failed");
    } finally {
      setExporting("");
    }
  };

  const s = data?.summary;
  return (
    <SafeAreaView style={st.root} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="pfc-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={st.title}>PF Contribution Reports</Text>
        <View style={{ width: 22 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 48 }}>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, zIndex: 30 }}>
          <View style={{ minWidth: 260, flex: 1 }}>
            <CompanyPicker value={companyId || "all"} onChange={setCompanyId}
              allowAll={false} label="Firm" testID="pfc-firm" />
          </View>
          <View style={{ minWidth: 170 }}>
            <MonthPicker value={month} onChange={setMonth} testID="pfc-month" />
          </View>
        </View>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
          {VIEWS.map(([k, l]) => (
            <Pressable key={k} onPress={() => setView(k)}
              style={[st.chip, view === k && st.chipOn]} testID={`pfc-view-${k}`}>
              <Text style={[st.chipTxt, view === k && st.chipTxtOn]}>{l}</Text>
            </Pressable>
          ))}
        </View>
        <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
          {(["xlsx", "pdf"] as const).map((k) => (
            <Pressable key={k} onPress={() => doExport(k)} style={st.expBtn}
              disabled={!!exporting} testID={`pfc-export-${k}`}>
              {exporting === k ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : (
                <Ionicons name={k === "pdf" ? "document-text-outline" : "download-outline"}
                  size={15} color={colors.brandPrimary} />
              )}
              <Text style={st.expTxt}>{k.toUpperCase()}</Text>
            </Pressable>
          ))}
        </View>
        {err ? <Text style={{ color: "#B91C1C", marginTop: 10 }}>{err}</Text> : null}
        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 24 }} /> : null}
        {!loading && data ? (
          <>
            <View style={st.sumCard} testID="pfc-summary">
              <Text style={st.sumTxt}>
                Employees {s.employees} · Statutory {s.statutory} · Higher {s.higher} · VPF {s.vpf} ·
                Pending Approval {s.pending_approval}
              </Text>
              <Text style={st.sumTxt}>
                PF (E) ₹{Number(s.total_pf_employee).toLocaleString("en-IN")} (incl. VPF ₹
                {Number(s.total_vpf).toLocaleString("en-IN")}) · Employer ₹
                {Number(s.total_employer).toLocaleString("en-IN")} · Diff vs Statutory ₹
                {Number(s.total_diff).toLocaleString("en-IN")}
                {data.run_locked ? "  ·  🔒 Run Locked" : ""}
              </Text>
              <Text style={[st.sumTxt, { color: colors.onSurfaceSecondary }]}>
                Company policy: Higher PF {data.policy?.allow_higher_pf ? "ALLOWED" : "not allowed"} ·
                VPF {data.policy?.allow_vpf ? "ALLOWED" : "not allowed"}
                {Number(data.policy?.vpf_max_percent) > 0 ? ` (max ${data.policy.vpf_max_percent}%)` : ""}
              </Text>
            </View>
            {!data.rows?.length ? (
              <Text style={{ marginTop: 16, color: colors.onSurfaceSecondary }}>
                {data.run_id ? "No employees match this view." :
                  "No Compliance Salary run found for this month — run Salary Process first."}
              </Text>
            ) : (
              <ScrollView horizontal showsHorizontalScrollIndicator style={{ marginTop: 12 }}>
                <View>
                  <View style={st.tr}>
                    {HEADERS.map((h, j) => (
                      <Text key={h} style={[st.cell, st.th, j === 1 && { width: 160 }]}>{h}</Text>
                    ))}
                  </View>
                  {data.rows.map((r: any) => (
                    <View key={r.user_id} style={st.tr}>
                      {KEYS.map((k, j) => (
                        <Text key={k}
                          style={[st.cell, j === 1 && { width: 160, textAlign: "left" },
                            k === "pf_diff" && Math.abs(Number(r[k])) >= 0.5 && { color: "#B45309", fontWeight: "700" },
                            k === "pf_approval_status" && String(r[k]).toLowerCase() !== "approved" && { color: "#B91C1C", fontWeight: "700" }]}
                          numberOfLines={1}>
                          {typeof r[k] === "number" ? Number(r[k]).toLocaleString("en-IN") : String(r[k] ?? "-")}
                        </Text>
                      ))}
                    </View>
                  ))}
                </View>
              </ScrollView>
            )}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.md, paddingVertical: 12,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderColor: colors.border,
  },
  title: { fontSize: type.lg, fontWeight: "800", color: colors.onSurface },
  chip: {
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999,
    borderWidth: 1.2, borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  chipTxtOn: { color: "#fff" },
  expBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 14,
    paddingVertical: 8, borderRadius: 10, borderWidth: 1.2,
    borderColor: colors.brandPrimary, backgroundColor: colors.surface,
  },
  expTxt: { fontSize: 12, fontWeight: "800", color: colors.brandPrimary },
  sumCard: {
    marginTop: 14, padding: 12, borderRadius: 12, backgroundColor: "#EFF6FF",
    borderWidth: 1, borderColor: "#BFDBFE", gap: 4,
  },
  sumTxt: { fontSize: 12.5, color: colors.onSurface, fontWeight: "600" },
  tr: { flexDirection: "row" },
  th: { backgroundColor: "#DDEBF7", fontWeight: "800" },
  cell: {
    width: 104, paddingHorizontal: 6, paddingVertical: 6, fontSize: 11,
    borderWidth: 0.5, borderColor: "#CBD5E1", color: colors.onSurface,
    textAlign: "center", backgroundColor: colors.surface,
  },
});
