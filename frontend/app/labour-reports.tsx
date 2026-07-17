// Iter 177 — Labour Law Compliance Reports Hub (Phase A+B).
// 22 statutory attendance reports over a common filter set, with
// on-screen preview and PDF / Excel / CSV / Print export. Every export
// carries logo, company details, generated date/by, page numbers and a
// QR verification code.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  ScrollView,
  TextInput,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

type CatItem = { key: string; label: string; group: string };
type Preview = {
  label: string;
  columns: string[];
  rows: any[][];
  total_rows: number;
  from_date: string;
  to_date: string;
  generated_at: string;
  generated_by: string;
  verify_id: string;
};

const FILTER_FIELDS: { key: string; label: string; placeholder: string }[] = [
  { key: "department", label: "Department", placeholder: "e.g. Production" },
  { key: "designation", label: "Designation", placeholder: "e.g. Operator" },
  { key: "employee_category", label: "Employee Category", placeholder: "e.g. Staff / Labour" },
  { key: "gender", label: "Gender", placeholder: "Male / Female" },
  { key: "contractor", label: "Contractor", placeholder: "Contractor name" },
];

function monthNow() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function LabourReportsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const canView =
    user?.role === "super_admin" || user?.role === "company_admin" || user?.role === "sub_admin";

  const [cat, setCat] = useState<CatItem[]>([]);
  const [reportKey, setReportKey] = useState<string>("daily_attendance");
  const [month, setMonth] = useState<string>(monthNow());
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [showFilters, setShowFilters] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ reports: CatItem[] }>("/admin/labour-reports/catalogue")
      .then((r) => setCat(r.reports || []))
      .catch(() => {});
  }, []);

  const groups = useMemo(() => {
    const g: Record<string, CatItem[]> = {};
    for (const c of cat) (g[c.group] = g[c.group] || []).push(c);
    return g;
  }, [cat]);

  const buildBody = (format: string) => ({
    company_id: selectedCompanyId,
    report_key: reportKey,
    format,
    filters: {
      ...(fromDate && toDate ? { from_date: fromDate, to_date: toDate } : { month }),
      ...Object.fromEntries(Object.entries(filters).filter(([, v]) => (v || "").trim())),
    },
  });

  const generate = useCallback(async () => {
    if (!selectedCompanyId) { setError("Select a firm first (top of screen)."); return; }
    setBusy("json");
    setError(null);
    try {
      const r = await api<Preview>("/admin/labour-reports/generate", {
        method: "POST", body: buildBody("json"),
      });
      setPreview(r);
    } catch (e: any) {
      setError(e?.message || "Failed to generate");
      setPreview(null);
    } finally { setBusy(null); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCompanyId, reportKey, month, fromDate, toDate, filters]);

  const download = async (format: "pdf" | "excel" | "csv") => {
    if (!selectedCompanyId) return;
    setBusy(format);
    setError(null);
    try {
      const r = await api<{ filename: string; file_base64: string }>(
        "/admin/labour-reports/generate", { method: "POST", body: buildBody(format) });
      if (Platform.OS === "web") {
        const bytes = atob(r.file_base64);
        const arr = new Uint8Array(bytes.length);
        for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
        const mime = format === "pdf" ? "application/pdf"
          : format === "csv" ? "text/csv"
          : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
        const blob = new Blob([arr], { type: mime });
        const url = URL.createObjectURL(blob);
        if (format === "pdf") {
          window.open(url, "_blank"); // print-friendly preview
        } else {
          const a = document.createElement("a");
          a.href = url;
          a.download = r.filename;
          a.click();
        }
        setTimeout(() => URL.revokeObjectURL(url), 30000);
      }
    } catch (e: any) {
      setError(e?.message || "Export failed");
    } finally { setBusy(null); }
  };

  if (!canView) {
    return <View style={st.center}><Text style={st.dim}>Admins only.</Text></View>;
  }

  const currentLabel = cat.find((c) => c.key === reportKey)?.label || "";

  return (
    <View style={st.root} testID="labour-reports-screen">
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={st.head}>
          <Pressable onPress={() => router.back()} hitSlop={10}>
            <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={st.title}>Labour Law Reports</Text>
            <Text style={st.sub}>22 statutory attendance registers & reports · PDF / Excel / CSV / Print · QR verified</Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}>
        {/* Report catalogue */}
        {Object.entries(groups).map(([g, items]) => (
          <View key={g} style={{ marginBottom: 10 }}>
            <Text style={st.groupLbl}>{g}</Text>
            <View style={st.chipsWrap}>
              {items.map((c) => (
                <Pressable key={c.key} onPress={() => { setReportKey(c.key); setPreview(null); }}
                  style={[st.chip, reportKey === c.key && st.chipOn]} testID={`lr-report-${c.key}`}>
                  <Text style={[st.chipTxt, reportKey === c.key && { color: "#fff" }]}>{c.label}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        ))}

        {/* Period + filters */}
        <View style={st.card}>
          <Text style={st.cardTitle}>{currentLabel}</Text>
          <View style={st.rowWrap}>
            <View style={st.field}>
              <Text style={st.fieldLbl}>Month (YYYY-MM)</Text>
              <TextInput value={month} onChangeText={setMonth} style={st.input}
                placeholder="2026-06" placeholderTextColor={colors.onSurfaceTertiary} testID="lr-month" />
            </View>
            <View style={st.field}>
              <Text style={st.fieldLbl}>From (optional)</Text>
              <TextInput value={fromDate} onChangeText={setFromDate} style={st.input}
                placeholder="YYYY-MM-DD" placeholderTextColor={colors.onSurfaceTertiary} testID="lr-from" />
            </View>
            <View style={st.field}>
              <Text style={st.fieldLbl}>To (optional)</Text>
              <TextInput value={toDate} onChangeText={setToDate} style={st.input}
                placeholder="YYYY-MM-DD" placeholderTextColor={colors.onSurfaceTertiary} testID="lr-to" />
            </View>
          </View>

          <Pressable onPress={() => setShowFilters((v) => !v)} style={st.filterToggle} testID="lr-filters-toggle">
            <Ionicons name="funnel-outline" size={13} color={colors.brandPrimary} />
            <Text style={st.filterToggleTxt}>
              Filters (Department · Designation · Category · Gender · Contractor)
            </Text>
            <Ionicons name={showFilters ? "chevron-up" : "chevron-down"} size={13} color={colors.brandPrimary} />
          </Pressable>
          {showFilters ? (
            <View style={st.rowWrap}>
              {FILTER_FIELDS.map((f) => (
                <View key={f.key} style={st.field}>
                  <Text style={st.fieldLbl}>{f.label}</Text>
                  <TextInput
                    value={filters[f.key] || ""}
                    onChangeText={(v) => setFilters((p) => ({ ...p, [f.key]: v }))}
                    style={st.input} placeholder={f.placeholder}
                    placeholderTextColor={colors.onSurfaceTertiary}
                    testID={`lr-filter-${f.key}`}
                  />
                </View>
              ))}
            </View>
          ) : null}

          <View style={{ flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
            <Pressable onPress={generate} disabled={!!busy}
              style={[st.primaryBtn, busy === "json" && { opacity: 0.6 }]} testID="lr-generate">
              {busy === "json" ? <ActivityIndicator size="small" color="#fff" /> : (
                <><Ionicons name="play-outline" size={14} color="#fff" />
                  <Text style={st.primaryBtnTxt}>Generate Preview</Text></>
              )}
            </Pressable>
            {(["pdf", "excel", "csv"] as const).map((f) => (
              <Pressable key={f} onPress={() => download(f)} disabled={!!busy}
                style={[st.exportBtn, busy === f && { opacity: 0.6 }]} testID={`lr-export-${f}`}>
                {busy === f ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : (
                  <>
                    <Ionicons
                      name={f === "pdf" ? "document-outline" : f === "excel" ? "grid-outline" : "list-outline"}
                      size={13} color={colors.brandPrimary} />
                    <Text style={st.exportBtnTxt}>{f === "pdf" ? "PDF / Print" : f.toUpperCase()}</Text>
                  </>
                )}
              </Pressable>
            ))}
          </View>
          {error ? <Text style={st.errTxt}>{error}</Text> : null}
        </View>

        {/* Preview */}
        {preview ? (
          <View style={st.card} testID="lr-preview">
            <Text style={st.cardTitle}>{preview.label}</Text>
            <Text style={st.metaTxt}>
              {preview.from_date} → {preview.to_date} · {preview.total_rows} rows ·
              Generated {preview.generated_at} by {preview.generated_by} · Verify: {preview.verify_id}
            </Text>
            <ScrollView horizontal style={{ marginTop: 8 }}>
              <View>
                <View style={st.tRow}>
                  {preview.columns.map((c, i) => (
                    <Text key={i} style={[st.tCell, st.tHead]} numberOfLines={2}>{c}</Text>
                  ))}
                </View>
                {preview.rows.slice(0, 100).map((r, ri) => (
                  <View key={ri} style={[st.tRow, ri % 2 === 1 && { backgroundColor: colors.background }]}>
                    {r.map((v, ci) => (
                      <Text key={ci} style={st.tCell} numberOfLines={1}>{String(v ?? "")}</Text>
                    ))}
                  </View>
                ))}
              </View>
            </ScrollView>
            {preview.total_rows > 100 ? (
              <Text style={st.metaTxt}>Showing first 100 of {preview.total_rows} rows — use Excel/PDF for the full report.</Text>
            ) : null}
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  dim: { fontSize: 12.5, color: colors.onSurfaceSecondary },
  head: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: spacing.md, paddingVertical: 10 },
  title: { ...type.h3, color: colors.onSurface },
  sub: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  groupLbl: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceTertiary, marginBottom: 5, textTransform: "uppercase" },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: {
    borderWidth: 1, borderColor: colors.divider, backgroundColor: colors.surface,
    borderRadius: 999, paddingHorizontal: 11, paddingVertical: 7,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11.5, fontWeight: "600", color: colors.onSurface },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.divider, padding: 12, marginTop: 10,
  },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface, marginBottom: 6 },
  rowWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  field: { minWidth: 140, flexGrow: 1, flexBasis: "28%" },
  fieldLbl: { fontSize: 10.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 3 },
  input: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 12.5, color: colors.onSurface,
    backgroundColor: colors.background,
  },
  filterToggle: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10 },
  filterToggleTxt: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.brandPrimary,
    borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 9,
  },
  primaryBtnTxt: { color: "#fff", fontSize: 12.5, fontWeight: "800" },
  exportBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1,
    borderColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 9,
  },
  exportBtnTxt: { fontSize: 12, fontWeight: "800", color: colors.brandPrimary },
  errTxt: { fontSize: 12, color: colors.error, marginTop: 8 },
  metaTxt: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 2 },
  tRow: { flexDirection: "row", borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider },
  tCell: { width: 108, fontSize: 10.5, color: colors.onSurface, paddingVertical: 5, paddingHorizontal: 4 },
  tHead: { fontWeight: "800", color: colors.onSurfaceSecondary, backgroundColor: colors.background },
});
