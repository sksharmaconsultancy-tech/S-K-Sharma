/**
 * Iter 161 — PF Reports / ESIC Reports (replaces the old contribution
 * sheet nav entries; formats per the user's uploaded EPFO/ESIC samples).
 *  • Manual period selection: From month/year → To month/year.
 *  • PF:   Challan Report (PDF + Excel) and ECR (PDF + Excel).
 *  • ESIC: Contribution Sheet (PDF + Excel) and Monthly Challan (PDF + Excel).
 * Open as /pf-reports?kind=pf or ?kind=esic.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  ActivityIndicator, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter, useLocalSearchParams } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import MonthPicker from "@/src/components/MonthPicker";
import { colors, radius, spacing, type } from "@/src/theme";

function thisMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function PfReportsScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ kind?: string }>();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId, selectedCompany } = useSelectedCompany();

  const [kind, setKind] = useState<"pf" | "esic">(
    (params.kind || "pf").toString().toLowerCase() === "esic" ? "esic" : "pf",
  );
  useEffect(() => {
    const k = (params.kind || "").toString().toLowerCase();
    if (k === "pf" || k === "esic") setKind(k);
  }, [params.kind]);

  const [from, setFrom] = useState<string>(thisMonth());
  const [to, setTo] = useState<string>(thisMonth());
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string>("");

  const companyId = user?.role === "company_admin" ? user.company_id : selectedCompanyId;
  const qs = `company_id=${companyId}&month_from=${from}&month_to=${to}`;

  const load = useCallback(async () => {
    if (!companyId || !from || !to) return;
    setLoading(true);
    try {
      const path = kind === "pf" ? "/admin/pf-reports/summary" : "/admin/pf-reports/esic-summary";
      setSummary(await api<any>(`${path}?${qs}`));
    } catch { setSummary(null); }
    finally { setLoading(false); }
  }, [companyId, from, to, kind, qs]);
  useEffect(() => { void load(); }, [load]);

  const download = async (path: string, filename: string) => {
    setBusy(path);
    try {
      const res = await apiBinary(`${path}?${qs}`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = filename;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      if (Platform.OS === "web") globalThis.alert(e?.message || "Download failed");
    } finally { setBusy(""); }
  };

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role)) {
    return <Redirect href="/" />;
  }
  const firmName = user.role === "company_admin" ? "" : (selectedCompany?.name || "");
  const label = kind === "pf" ? "PF Reports" : "ESIC Reports";
  const period = `${from}_${to}`;

  const DlBtn = ({ title, icon, path, fn }: any) => (
    <Pressable
      onPress={() => download(path, fn)}
      disabled={!!busy || !companyId}
      style={[styles.dlBtn, busy === path && { opacity: 0.6 }]}
      testID={`dl-${path.split("/").pop()}`}
    >
      {busy === path ? <ActivityIndicator size="small" color="#fff" /> : (
        <Ionicons name={icon} size={15} color="#fff" />
      )}
      <Text style={styles.dlTxt}>{title}</Text>
    </Pressable>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="pfr-back">
          <Ionicons name="arrow-back" size={20} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>{label}{firmName ? ` — ${firmName}` : ""}</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 60 }}>
        {/* kind switch */}
        <View style={{ flexDirection: "row", gap: 8, marginBottom: 12 }}>
          {(["pf", "esic"] as const).map((k) => (
            <Pressable key={k} onPress={() => setKind(k)}
              style={[styles.tab, kind === k && styles.tabActive]} testID={`pfr-kind-${k}`}>
              <Text style={[styles.tabTxt, kind === k && { color: "#fff" }]}>
                {k === "pf" ? "PF Reports" : "ESIC Reports"}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* period pickers — month & year selection in user's hand */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Select Period (Month & Year)</Text>
          <View style={{ flexDirection: "row", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
            <View>
              <Text style={styles.lbl}>From month</Text>
              <MonthPicker value={from} onChange={setFrom} allowEmpty={false} testID="pfr-from" />
            </View>
            <View>
              <Text style={styles.lbl}>To month</Text>
              <MonthPicker value={to} onChange={setTo} allowEmpty={false} testID="pfr-to" />
            </View>
          </View>
        </View>

        {/* downloads */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>
            {kind === "pf" ? "Downloads — as per EPFO formats" : "Downloads — as per ESIC formats"}
          </Text>
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            {kind === "pf" ? (
              <>
                <DlBtn title="PF Challan (PDF)" icon="document-outline"
                  path="/admin/pf-reports/challan.pdf" fn={`PF_Challan_${period}.pdf`} />
                <DlBtn title="PF Challan (Excel)" icon="grid-outline"
                  path="/admin/pf-reports/challan.xlsx" fn={`PF_Challan_${period}.xlsx`} />
                <DlBtn title="PF ECR (PDF)" icon="document-text-outline"
                  path="/admin/pf-reports/ecr.pdf" fn={`PF_ECR_${period}.pdf`} />
                <DlBtn title="PF ECR (Excel)" icon="grid-outline"
                  path="/admin/pf-reports/ecr.xlsx" fn={`PF_ECR_${period}.xlsx`} />
              </>
            ) : (
              <>
                <DlBtn title="Contribution Sheet (PDF)" icon="document-text-outline"
                  path="/admin/pf-reports/esic-sheet.pdf" fn={`ESIC_Contribution_${period}.pdf`} />
                <DlBtn title="Contribution Sheet (Excel)" icon="grid-outline"
                  path="/admin/pf-reports/esic-sheet.xlsx" fn={`ESIC_Contribution_${period}.xlsx`} />
                <DlBtn title="ESIC Challan (PDF)" icon="document-outline"
                  path="/admin/pf-reports/esic-challan.pdf" fn={`ESIC_Challan_${period}.pdf`} />
                <DlBtn title="ESIC Challan (Excel)" icon="grid-outline"
                  path="/admin/pf-reports/esic-challan.xlsx" fn={`ESIC_Challan_${period}.xlsx`} />
              </>
            )}
          </View>
          <Pressable
            onPress={() => router.push(`/contribution-sheets?kind=${kind === "pf" ? "pf" : "esi"}` as any)}
            style={{ marginTop: 10 }}
            testID="pfr-old-sheet"
          >
            <Text style={{ color: colors.brandPrimary, fontSize: 12, fontWeight: "600" }}>
              Open old {kind === "pf" ? "P.F." : "E.S.I."} Contribution Sheet →
            </Text>
          </Pressable>
        </View>

        {/* preview */}
        {loading ? <ActivityIndicator style={{ marginTop: 30 }} color={colors.brandPrimary} /> : summary ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Period Preview</Text>
            <View style={styles.row}>
              {(kind === "pf"
                ? ["Month", "Members", "EE (A/c 1)", "ER EPF", "EPS (A/c 10)", "A/c 2", "A/c 21", "A/c 22", "Total"]
                : ["Month", "Employees", "Wages", "EE Contri.", "ER Contri.", "Total"]
              ).map((h) => <Text key={h} style={[styles.cell, styles.hcell]}>{h}</Text>)}
            </View>
            {(summary.months || []).map((m: any) => (
              <View key={m.month} style={styles.row}>
                {(kind === "pf"
                  ? [m.label, m.subscribers, m.ee, m.er_epf, m.eps, m.ac2, m.ac21, m.ac22, m.total]
                  : [m.label, m.employees, m.wages, m.ee, m.er, m.total]
                ).map((v: any, i: number) => <Text key={i} style={styles.cell}>{String(v)}</Text>)}
              </View>
            ))}
            {summary.missing_months?.length ? (
              <Text style={styles.warn}>
                No compliance salary run for: {summary.missing_months.join(", ")} — process salary first.
              </Text>
            ) : null}
            {summary.totals ? (
              <Text style={styles.totTxt}>
                Period Total: ₹{Number(summary.totals.total || 0).toLocaleString("en-IN")}
              </Text>
            ) : null}
          </View>
        ) : null}
        {!companyId ? (
          <Text style={styles.warn}>Select a firm from the top bar first.</Text>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.lg, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  backBtn: { padding: 4 },
  title: { fontSize: type.h3, fontWeight: "700", color: colors.onSurface },
  tab: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  tabActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginBottom: 12,
  },
  cardTitle: { fontSize: 13, fontWeight: "700", color: colors.onSurface, marginBottom: 10 },
  lbl: { fontSize: 11, fontWeight: "600", color: colors.onSurfaceSecondary, marginBottom: 4 },
  dlBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, paddingHorizontal: 12,
    paddingVertical: 10, borderRadius: radius.sm,
  },
  dlTxt: { color: "#fff", fontSize: 12, fontWeight: "700" },
  row: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.border, paddingVertical: 6 },
  cell: { flex: 1, fontSize: 11, color: colors.onSurface },
  hcell: { fontWeight: "700", color: colors.onSurfaceSecondary },
  warn: { color: "#B45309", fontSize: 12, marginTop: 8, fontWeight: "600" },
  totTxt: { marginTop: 8, fontSize: 13, fontWeight: "800", color: colors.brandPrimary },
});
