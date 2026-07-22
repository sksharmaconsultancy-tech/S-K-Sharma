/**
 * Bulk UAN / ESIC-IP Import — Iter 242 (user request).
 *
 * Upload one Excel/CSV with Employee Code + UAN + ESIC IP columns and the
 * matching employees get their UAN / ESIC numbers filled in one shot, so
 * the PF ECR .txt and ESIC upload files can then be generated. Only these
 * two identifier fields are touched — nothing else in the Employee Master.
 */
import React, { useState } from "react";
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { getApiBaseUrl, readAuthToken } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing } from "@/src/theme";

type Result = {
  dry_run: boolean;
  rows_read: number;
  rows_with_identifier: number;
  employees_updated: number;
  uan_filled: number;
  esic_ip_filled: number;
  not_found_count: number;
  not_found: string[];
  invalid: string[];
};

const MATCH_OPTS = [
  { key: "employee_code", label: "Employee Code" },
  { key: "bio_code", label: "Bio Code" },
  { key: "name", label: "Name" },
];

export default function UanEsicImportScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";
  const { selectedCompanyId } = useSelectedCompany() as any;
  const companyId = isSuper ? selectedCompanyId : user?.company_id;

  const [file, setFile] = useState<File | null>(null);
  const [matchBy, setMatchBy] = useState("employee_code");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [err, setErr] = useState("");

  const send = async (dryRun: boolean) => {
    if (!companyId) { setErr("Select a firm first."); return; }
    if (!file) { setErr("Choose an Excel/CSV file first."); return; }
    setBusy(true); setErr(""); setResult(null);
    try {
      const form = new FormData();
      form.append("company_id", companyId);
      form.append("match_by", matchBy);
      form.append("dry_run", dryRun ? "true" : "false");
      form.append("file", file);
      const token = (await readAuthToken()) || "";
      const res = await fetch(`${getApiBaseUrl()}/admin/uan-esic-import`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail || `HTTP ${res.status}`);
      setResult(body as Result);
    } catch (e: any) {
      setErr(e?.message || "Import failed");
    } finally {
      setBusy(false);
    }
  };

  const downloadTemplate = async () => {
    if (!companyId) { setErr("Select a firm first."); return; }
    try {
      const form = new FormData();
      form.append("company_id", companyId);
      const token = (await readAuthToken()) || "";
      const res = await fetch(`${getApiBaseUrl()}/admin/uan-esic-import/template.xlsx`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      if (!res.ok) throw new Error("Template download failed");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "UAN_ESIC_Template.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e: any) {
      setErr(e?.message || "Template download failed");
    }
  };

  return (
    <SafeAreaView style={st.root} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={8} style={st.iconBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.title}>Import UAN / ESIC Numbers</Text>
          <Text style={st.subtitle}>Fill employee UAN &amp; ESIC IP in one upload</Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
        {!companyId && (
          <Text style={st.warn}>Select a firm from the top selector to continue.</Text>
        )}

        <View style={st.card}>
          <Text style={st.step}>1. Download the template (pre-filled with your employees)</Text>
          <Pressable style={st.templateBtn} onPress={downloadTemplate} disabled={!companyId}>
            <Ionicons name="download-outline" size={16} color={colors.primary} />
            <Text style={st.templateTxt}>Download Template (.xlsx)</Text>
          </Pressable>
          <Text style={st.hint}>
            Fill the UAN (12 digits) and ESIC IP No columns, then upload it below.
            You can also use your own Excel/CSV — columns named UAN, ESIC IP No and
            Employee Code are auto-detected.
          </Text>
        </View>

        <View style={st.card}>
          <Text style={st.step}>2. Match employees by</Text>
          <View style={st.chipRow}>
            {MATCH_OPTS.map((o) => (
              <Pressable
                key={o.key}
                onPress={() => setMatchBy(o.key)}
                style={[st.chip, matchBy === o.key && st.chipOn]}
              >
                <Text style={[st.chipTxt, matchBy === o.key && st.chipTxtOn]}>{o.label}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={[st.step, { marginTop: spacing.md }]}>3. Upload the file</Text>
          {/* @ts-ignore web file input */}
          <input
            type="file"
            accept=".xlsx,.xls,.csv,text/csv"
            onChange={(e: any) => { setFile(e.target.files?.[0] || null); setResult(null); }}
            style={{
              padding: 8, border: `1px solid ${colors.border}`, borderRadius: 6,
              fontSize: 13, background: colors.surface, width: "100%",
            } as any}
          />
          {file ? <Text style={st.hint}>Selected: {file.name}</Text> : null}

          {err ? <Text style={st.err}>{err}</Text> : null}

          <View style={st.actions}>
            <Pressable style={[st.previewBtn, busy && { opacity: 0.6 }]} onPress={() => send(true)} disabled={busy}>
              {busy ? <ActivityIndicator size="small" color={colors.primary} /> : <Text style={st.previewTxt}>Preview (no changes)</Text>}
            </Pressable>
            <Pressable style={[st.applyBtn, busy && { opacity: 0.6 }]} onPress={() => send(false)} disabled={busy}>
              {busy ? <ActivityIndicator size="small" color="#fff" /> : (
                <>
                  <Ionicons name="checkmark" size={16} color="#fff" />
                  <Text style={st.applyTxt}>Apply Import</Text>
                </>
              )}
            </Pressable>
          </View>
        </View>

        {result && (
          <View style={st.card}>
            <Text style={st.resultTitle}>
              {result.dry_run ? "Preview result" : "✅ Import applied"}
            </Text>
            <Text style={st.rLine}>Rows read: {result.rows_read}</Text>
            <Text style={st.rLine}>Employees matched &amp; updated: {result.employees_updated}</Text>
            <Text style={st.rLine}>UAN filled: {result.uan_filled}</Text>
            <Text style={st.rLine}>ESIC IP filled: {result.esic_ip_filled}</Text>
            {result.not_found_count > 0 && (
              <Text style={[st.rLine, { color: "#DC2626" }]}>
                Not matched ({result.not_found_count}): {result.not_found.join(", ")}
              </Text>
            )}
            {result.invalid?.length > 0 && (
              <Text style={[st.rLine, { color: "#D97706" }]}>
                Skipped invalid: {result.invalid.join("; ")}
              </Text>
            )}
            {result.dry_run && result.employees_updated > 0 && (
              <Text style={st.hint}>Looks good? Press “Apply Import” to save.</Text>
            )}
            {!result.dry_run && (
              <Text style={st.hint}>
                Done. You can now generate the PF ECR .txt and ESIC upload files.
              </Text>
            )}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  iconBtn: { padding: 4 },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceSecondary },
  warn: { fontSize: 13, color: "#B45309", fontWeight: "700", marginBottom: spacing.md },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
    marginBottom: spacing.lg, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border,
  },
  step: { fontSize: 14, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.sm },
  templateBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    borderWidth: 1, borderColor: colors.primary, borderRadius: radius.md,
    paddingHorizontal: 14, paddingVertical: 9,
  },
  templateTxt: { fontSize: 13, fontWeight: "800", color: colors.primary },
  hint: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 8, lineHeight: 17 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
  },
  chipOn: { backgroundColor: "#FBECD6", borderColor: "#8B5E34" },
  chipTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#7A4A18" },
  err: { color: "#DC2626", fontSize: 13, fontWeight: "700", marginTop: spacing.md },
  actions: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  previewBtn: {
    flex: 1, borderWidth: 1.5, borderColor: colors.primary, borderRadius: radius.md,
    paddingVertical: 11, alignItems: "center", justifyContent: "center",
  },
  previewTxt: { fontSize: 14, fontWeight: "800", color: colors.primary },
  applyBtn: {
    flex: 1, flexDirection: "row", gap: 6, backgroundColor: "#15803D",
    borderRadius: radius.md, paddingVertical: 11, alignItems: "center", justifyContent: "center",
  },
  applyTxt: { fontSize: 14, fontWeight: "800", color: "#fff" },
  resultTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  rLine: { fontSize: 13, color: colors.onSurfaceSecondary, marginBottom: 4 },
});
