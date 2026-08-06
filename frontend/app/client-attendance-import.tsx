/**
 * Iter 501 — Client Attendance Import (Attendance Summary Excel).
 * Upload client sheets (.xlsx/.xls ≤ 20 MB) → auto column detection with
 * manual mapping + saved templates → validation preview (valid / invalid /
 * duplicates / missing employees) → duplicate handling (replace / skip /
 * merge) → import log with error-report download + one-click rollback.
 * Additive: existing biometric sync / punch import / engines untouched.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator, ScrollView,
  TextInput, Modal, Platform, Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as DocumentPicker from "expo-document-picker";

import { api } from "@/src/api/client";
import ReportTable, { ReportCol } from "@/src/components/ReportTable";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing } from "@/src/theme";

const DUP_MODES = [
  { key: "skip", label: "Skip Existing", desc: "Existing employee+date records stay untouched" },
  { key: "replace", label: "Replace Existing", desc: "Previous CLIENT-imported data for those days is replaced (biometric punches never touched)" },
  { key: "merge", label: "Merge Attendance", desc: "Only missing IN/OUT punches are added" },
];

export default function ClientAttendanceImportScreen() {
  const router = useRouter();
  const { selectedCompanyId, companies } = useSelectedCompany();
  const [cid, setCid] = useState<string | null>(selectedCompanyId);
  const [tab, setTab] = useState<"import" | "history">("import");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [showMap, setShowMap] = useState(false);
  const [mapping, setMapping] = useState<Record<string, number>>({});
  const [dupMode, setDupMode] = useState("skip");
  const [syncCompliance, setSyncCompliance] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [templates, setTemplates] = useState<any[]>([]);
  const [tplName, setTplName] = useState("");
  const [logBusy, setLogBusy] = useState<string | null>(null);

  useEffect(() => { if (selectedCompanyId) setCid(selectedCompanyId); }, [selectedCompanyId]);

  const loadHistory = useCallback(async () => {
    if (!cid) return;
    try {
      const [l, t] = await Promise.all([
        api(`/admin/client-attendance/logs?company_id=${cid}`),
        api(`/admin/client-attendance/templates?company_id=${cid}`),
      ]);
      setLogs(l.logs || []); setTemplates(t.templates || []);
    } catch { /* role-gated */ }
  }, [cid]);
  useEffect(() => { loadHistory(); }, [loadHistory]);

  const fileToBase64 = async (uri: string): Promise<string> => {
    const res = await fetch(uri);
    const blob = await res.blob();
    return await new Promise<string>((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => {
        const s = String(fr.result || "");
        resolve(s.includes(",") ? s.split(",")[1] : s);
      };
      fr.onerror = reject;
      fr.readAsDataURL(blob);
    });
  };

  const saveB64File = (name: string, b64: string) => {
    if (Platform.OS !== "web") return;
    const bytes = atob(b64);
    const arr = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([arr]));
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  };

  const downloadTemplate = async () => {
    try {
      const r = await api<any>("/admin/client-attendance/template");
      saveB64File(r.filename, r.file_base64);
    } catch (e: any) { setErr(e?.message || "Template download failed"); }
  };

  const pickFile = async () => {
    if (!cid) { setErr("Select a firm first"); return; }
    const res = await DocumentPicker.getDocumentAsync({
      type: [
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      ],
      copyToCacheDirectory: true,
    });
    if (res.canceled || !res.assets?.length) return;
    const asset = res.assets[0];
    if ((asset.size || 0) > 20 * 1024 * 1024) { setErr("File exceeds the 20 MB limit"); return; }
    setBusy(true); setErr(null); setResult(null); setPreview(null);
    try {
      const b64 = await fileToBase64(asset.uri);
      const p = await api<any>("/admin/client-attendance/preview", {
        method: "POST", body: { company_id: cid, file_base64: b64, filename: asset.name },
      });
      setFileName(asset.name); setPreview(p); setMapping(p.mapping || {});
    } catch (e: any) { setErr(e?.message || "Could not read the Excel file"); }
    setBusy(false);
  };

  const remap = async (m: Record<string, number>) => {
    if (!preview?.staging_id) return;
    setBusy(true); setErr(null);
    try {
      const p = await api<any>("/admin/client-attendance/preview", {
        method: "POST",
        body: { company_id: cid, staging_id: preview.staging_id, mapping: m },
      });
      setPreview(p); setMapping(p.mapping || {});
    } catch (e: any) { setErr(e?.message || "Re-mapping failed"); }
    setBusy(false);
  };

  const applyTemplate = (t: any) => {
    if (!preview) return;
    const hs: string[] = preview.headers || [];
    const m: Record<string, number> = {};
    Object.entries(t.mapping_headers || {}).forEach(([f, hname]) => {
      const i = hs.findIndex((h) => String(h).trim().toLowerCase() === String(hname).trim().toLowerCase());
      if (i >= 0) m[f] = i;
    });
    remap(Object.keys(m).length ? m : t.mapping || {});
  };

  const saveTemplate = async () => {
    if (!tplName.trim() || !preview) return;
    try {
      await api("/admin/client-attendance/templates", {
        method: "POST",
        body: { company_id: cid, name: tplName.trim(), mapping, headers: preview.headers },
      });
      setTplName(""); await loadHistory();
    } catch (e: any) { setErr(e?.message || "Template save failed"); }
  };

  const commit = async () => {
    if (!preview?.staging_id) return;
    setBusy(true); setErr(null);
    try {
      const r = await api<any>("/admin/client-attendance/commit", {
        method: "POST",
        body: { staging_id: preview.staging_id, duplicate_mode: dupMode, sync_compliance: syncCompliance },
      });
      setResult(r.log); setPreview(null); await loadHistory();
    } catch (e: any) { setErr(e?.message || "Import failed"); }
    setBusy(false);
  };

  const downloadErrors = async (l: any) => {
    setLogBusy(l.import_id);
    try {
      const r = await api<any>(`/admin/client-attendance/logs/${l.import_id}/errors`);
      saveB64File(r.filename, r.file_base64);
    } catch (e: any) { setErr(e?.message || "Error report failed"); }
    setLogBusy(null);
  };

  const deleteImport = async (l: any) => {
    if (Platform.OS === "web" && !window.confirm(
      `Roll back import "${l.filename}" (${l.imported} rows + ${l.punches_created} punches)?`)) return;
    setLogBusy(l.import_id);
    try {
      await api(`/admin/client-attendance/logs/${l.import_id}`, { method: "DELETE" });
      await loadHistory();
    } catch (e: any) { setErr(e?.message || "Rollback failed"); }
    setLogBusy(null);
  };

  const INVALID_COLS: ReportCol<any>[] = [
    { key: "row", label: "Excel Row", type: "center", min: 76 },
    { key: "code", label: "Code", type: "center", min: 70 },
    { key: "name", label: "Name", min: 160, max: 260 },
    { key: "date", label: "Date", type: "center", min: 90 },
    { key: "reason", label: "Error", min: 220, max: 420, textStyle: () => ({ color: "#B91C1C" }) },
  ];
  const SAMPLE_COLS: ReportCol<any>[] = [
    { key: "employee_code", label: "Code", type: "center", min: 64, sticky: true },
    { key: "name", label: "Name", min: 160, max: 240, sticky: true },
    { key: "date", label: "Date", type: "center", min: 90 },
    { key: "in_time", label: "In", type: "center", min: 56 },
    { key: "out_time", label: "Out", type: "center", min: 56 },
    {
      key: "missing_punch", label: "Punch", type: "center", min: 88,
      value: (r) => (r.missing_punch ? `Missing ${r.missing_punch.toUpperCase()}` : "OK"),
      textStyle: (r) => ({ color: r.missing_punch ? "#C2410C" : "#15803D", fontWeight: "700" }),
    },
    { key: "status", label: "Status", type: "center", min: 100, value: (r) => (r.status || "").replace(/_/g, " ").toUpperCase() },
    { key: "shift", label: "Shift", type: "center", min: 60 },
    { key: "work_hours", label: "Work Hrs", type: "num", min: 78 },
    { key: "ot_hours", label: "OT Hrs", type: "num", min: 68 },
    { key: "late_hours", label: "Late", type: "num", min: 60 },
    { key: "paid_days", label: "Paid", type: "num", min: 60 },
    {
      key: "duplicate", label: "Duplicate", type: "center", min: 80,
      value: (r) => (r.duplicate ? "YES" : ""),
      textStyle: () => ({ color: "#B45309", fontWeight: "800" }),
    },
  ];
  const LOG_COLS: ReportCol<any>[] = [
    { key: "at", label: "When", type: "date", min: 100, value: (r) => (r.at || "").slice(0, 16).replace("T", " ") },
    { key: "filename", label: "File", min: 170, max: 280, sticky: true },
    { key: "imported_by_name", label: "By", min: 110, max: 180 },
    { key: "date_from", label: "From", type: "date" },
    { key: "date_to", label: "To", type: "date" },
    { key: "total_rows", label: "Total", type: "num", min: 60 },
    { key: "imported", label: "Imported", type: "num", min: 76, textStyle: () => ({ color: "#15803D", fontWeight: "800" }) },
    { key: "skipped", label: "Skipped", type: "num", min: 70 },
    { key: "failed", label: "Failed", type: "num", min: 64, textStyle: (r) => ({ color: r.failed ? "#B91C1C" : colors.onSurface }) },
    { key: "punches_created", label: "Punches", type: "num", min: 72 },
    { key: "duplicate_mode", label: "Dup. Mode", type: "center", min: 84 },
    {
      key: "status", label: "Status", type: "center", min: 84,
      value: (r) => (r.status || "imported").toUpperCase(),
      textStyle: (r) => ({ fontWeight: "800", color: r.status === "deleted" ? "#B91C1C" : "#15803D" }),
    },
    {
      key: "__act", label: "Actions", type: "center", min: 96,
      render: (r) => (
        <View style={{ flexDirection: "row", gap: 10, justifyContent: "center" }}>
          {logBusy === r.import_id ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : (
            <>
              <Pressable onPress={() => downloadErrors(r)} hitSlop={6} testID={`cai-err-${r.import_id}`}>
                <Ionicons name="download-outline" size={16} color={colors.brandPrimary} />
              </Pressable>
              {r.status !== "deleted" ? (
                <Pressable onPress={() => deleteImport(r)} hitSlop={6} testID={`cai-del-${r.import_id}`}>
                  <Ionicons name="trash-outline" size={16} color="#B91C1C" />
                </Pressable>
              ) : null}
            </>
          )}
        </View>
      ),
    },
  ];

  const stat = (label: string, v: any, color?: string) => (
    <View key={label} style={st.statCard}>
      <Text style={[st.statVal, color ? { color } : null]}>{String(v ?? 0)}</Text>
      <Text style={st.statLbl}>{label}</Text>
    </View>
  );

  return (
    <SafeAreaView style={st.root} edges={["top"]}>
      <View style={st.head}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="arrow-back" size={20} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.title}>Client Attendance Import</Text>
          <Text style={st.sub}>Attendance summary Excel from clients · auto column detection · duplicate handling · rollback</Text>
        </View>
        <Pressable onPress={downloadTemplate} style={st.tplBtn} testID="cai-template">
          <Ionicons name="download-outline" size={13} color={colors.brandPrimary} />
          <Text style={st.tplTxt}>Sample</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ flexDirection: "row", gap: 6, paddingBottom: 8 }}>
          {companies.map((c: any) => (
            <Pressable key={c.company_id} onPress={() => { setCid(c.company_id); setPreview(null); setResult(null); }}
              style={[st.chip, cid === c.company_id && st.chipOn]}>
              <Text style={[st.chipTxt, cid === c.company_id && st.chipTxtOn]} numberOfLines={1}>{c.name}</Text>
            </Pressable>
          ))}
        </ScrollView>

        <View style={{ flexDirection: "row", gap: 6, marginBottom: 10 }}>
          {[["import", "Import"], ["history", `Import History (${logs.length})`]].map(([k, l]) => (
            <Pressable key={k} onPress={() => setTab(k as any)} style={[st.chip, tab === k && st.chipOn]}>
              <Text style={[st.chipTxt, tab === k && st.chipTxtOn]}>{l}</Text>
            </Pressable>
          ))}
        </View>

        {err ? <View style={st.errBox}><Text style={st.errTxt}>{err}</Text></View> : null}

        {tab === "history" ? (
          <View style={{ minHeight: 300, maxHeight: 640 }}>
            <ReportTable reportKey="client_att_imports" columns={LOG_COLS} rows={logs}
              maxHeight={600} emptyText="No imports yet."
              pdfTitle="Client Attendance Import Log"
              pdfSubtitle={companies.find((c: any) => c.company_id === cid)?.name || ""} />
          </View>
        ) : result ? (
          <View style={st.card}>
            <Text style={[st.cardTitle, { color: "#15803D" }]}>✅ Import Complete — {result.filename}</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
              {stat("Imported", result.imported, "#15803D")}
              {stat("Skipped (duplicates)", result.skipped, "#B45309")}
              {stat("Failed (invalid)", result.failed, "#B91C1C")}
              {stat("Punches Created", result.punches_created, "#1E3A8A")}
            </View>
            {result.sync_compliance ? (
              <Text style={st.dim2}>Present days synced to Compliance Imported-Sheet for: {(result.synced_months || []).join(", ")}</Text>
            ) : null}
            <Pressable onPress={() => setResult(null)} style={[st.primaryBtn, { marginTop: 10 }]}>
              <Text style={st.primaryTxt}>Import Another File</Text>
            </Pressable>
          </View>
        ) : !preview ? (
          <Pressable onPress={pickFile} disabled={busy} style={st.dropZone} testID="cai-upload">
            {busy ? <ActivityIndicator color={colors.brandPrimary} /> : (
              <>
                <Ionicons name="cloud-upload-outline" size={34} color={colors.brandPrimary} />
                <Text style={st.dropTitle}>Drop the client&apos;s attendance Excel here, or tap to browse</Text>
                <Text style={st.dim2}>.xlsx / .xls · up to 20 MB · columns are auto-detected (Code, Name, Date, Intime, Outtime, Shift, Late, Early, OT, Work Hrs, Present, Absent, Leave, Paid Days, WO, Holiday, CL/SL/PL/OD/CO)</Text>
              </>
            )}
          </Pressable>
        ) : (
          <>
            {/* stats */}
            <View style={st.card}>
              <View style={{ flexDirection: "row", alignItems: "center" }}>
                <Text style={[st.cardTitle, { flex: 1 }]} numberOfLines={1}>📄 {fileName}</Text>
                <Pressable onPress={() => setPreview(null)} hitSlop={8}>
                  <Ionicons name="close" size={17} color={colors.onSurfaceSecondary} />
                </Pressable>
              </View>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                {stat("Total Rows", preview.stats?.total)}
                {stat("Valid", preview.stats?.valid, "#15803D")}
                {stat("Invalid", preview.stats?.invalid, "#B91C1C")}
                {stat("Duplicates", preview.stats?.duplicates, "#B45309")}
                {stat("Missing Employees", preview.stats?.missing_employees, "#B91C1C")}
                {stat("Present", preview.stats?.present, "#15803D")}
                {stat("Absent", preview.stats?.absent, "#B91C1C")}
                {stat("Leave", preview.stats?.leave, "#7C2D12")}
                {stat("Weekly Off", preview.stats?.weekly_off)}
                {stat("Holiday", preview.stats?.holiday)}
              </View>
              <Pressable onPress={() => setShowMap(true)} style={[st.outlineBtn, { marginTop: 10 }]} testID="cai-map">
                <Ionicons name="git-compare-outline" size={13} color={colors.brandPrimary} />
                <Text style={st.outlineTxt}>Column Mapping ({Object.keys(preview.mapping || {}).length} detected)</Text>
              </Pressable>
            </View>

            {/* missing employees */}
            {(preview.missing_employees || []).length ? (
              <View style={st.card}>
                <Text style={[st.cardTitle, { color: "#B91C1C" }]}>Missing Employees (not imported)</Text>
                <Text style={st.dim2}>
                  {preview.missing_employees.slice(0, 30).map((m: any) => `${m.code || m.name} (${m.rows})`).join(" · ")}
                  {preview.missing_employees.length > 30 ? ` · +${preview.missing_employees.length - 30} more` : ""}
                </Text>
              </View>
            ) : null}

            {/* invalid rows */}
            {(preview.invalid_rows || []).length ? (
              <View style={{ minHeight: 120, maxHeight: 300, marginBottom: 10 }}>
                <ReportTable reportKey="client_att_invalid" columns={INVALID_COLS}
                  rows={preview.invalid_rows} maxHeight={280}
                  emptyText="" pdfTitle="Invalid Rows" />
              </View>
            ) : null}

            {/* sample */}
            <Text style={st.secTitle}>Preview (first 15 valid rows)</Text>
            <View style={{ minHeight: 140, maxHeight: 380, marginBottom: 10 }}>
              <ReportTable reportKey="client_att_sample" columns={SAMPLE_COLS}
                rows={preview.sample || []} maxHeight={360} emptyText="No valid rows." />
            </View>

            {/* duplicate mode + commit */}
            <View style={st.card}>
              <Text style={st.cardTitle}>If a record already exists (Employee + Date)</Text>
              {DUP_MODES.map((m) => (
                <Pressable key={m.key} onPress={() => setDupMode(m.key)}
                  style={[st.dupRow, dupMode === m.key && st.dupRowOn]} testID={`cai-dup-${m.key}`}>
                  <Ionicons name={dupMode === m.key ? "radio-button-on" : "radio-button-off"}
                    size={15} color={dupMode === m.key ? colors.brandPrimary : colors.onSurfaceTertiary} />
                  <View style={{ flex: 1 }}>
                    <Text style={st.dupLbl}>{m.label}</Text>
                    <Text style={st.dim2}>{m.desc}</Text>
                  </View>
                </Pressable>
              ))}
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8 }}>
                <Switch value={syncCompliance} onValueChange={setSyncCompliance}
                  trackColor={{ true: colors.brandPrimary }} testID="cai-sync" />
                <Text style={[st.dim2, { flex: 1 }]}>
                  Also sync monthly Present Days into the Compliance Salary &quot;Imported Sheet&quot; entries (optional)
                </Text>
              </View>
              <View style={{ flexDirection: "row", gap: 10, marginTop: 12, justifyContent: "flex-end" }}>
                <Pressable onPress={() => setPreview(null)} style={st.outlineBtn} disabled={busy}>
                  <Text style={st.outlineTxt}>Cancel Import</Text>
                </Pressable>
                <Pressable onPress={commit} style={[st.primaryBtn, !preview.stats?.valid && { opacity: 0.4 }]}
                  disabled={busy || !preview.stats?.valid} testID="cai-commit">
                  {busy ? <ActivityIndicator size="small" color="#fff" />
                    : <Text style={st.primaryTxt}>Import {preview.stats?.valid} Valid Rows</Text>}
                </Pressable>
              </View>
            </View>
          </>
        )}
      </ScrollView>

      {/* column mapping modal */}
      <Modal visible={showMap} transparent animationType="fade" onRequestClose={() => setShowMap(false)}>
        <View style={st.mWrap}>
          <View style={[st.mCard, { maxWidth: 640, width: Platform.OS === "web" ? 620 : "100%" }]}>
            <Text style={st.mTitle}>Column Mapping — Excel → Payroll Field</Text>
            {templates.length ? (
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 5, marginBottom: 8, alignItems: "center" }}>
                <Text style={st.dim2}>Templates:</Text>
                {templates.map((t) => (
                  <Pressable key={t.template_id} onPress={() => applyTemplate(t)} style={st.tinyChip}>
                    <Text style={st.tinyTxt}>{t.name}</Text>
                  </Pressable>
                ))}
              </View>
            ) : null}
            <ScrollView style={{ maxHeight: 400 }}>
              {(preview?.fields || []).map((f: any) => (
                <View key={f.key} style={st.mapRow}>
                  <Text style={st.mapLbl}>{f.label}</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flex: 1 }}>
                    <View style={{ flexDirection: "row", gap: 4 }}>
                      <Pressable onPress={() => setMapping((m) => { const n = { ...m }; delete n[f.key]; return n; })}
                        style={[st.tinyChip, mapping[f.key] === undefined && st.chipOn]}>
                        <Text style={[st.tinyTxt, mapping[f.key] === undefined && st.chipTxtOn]}>—</Text>
                      </Pressable>
                      {(preview?.headers || []).map((h: string, i: number) => (
                        h ? (
                          <Pressable key={i} onPress={() => setMapping((m) => ({ ...m, [f.key]: i }))}
                            style={[st.tinyChip, mapping[f.key] === i && st.chipOn]}>
                            <Text style={[st.tinyTxt, mapping[f.key] === i && st.chipTxtOn]} numberOfLines={1}>{h}</Text>
                          </Pressable>
                        ) : null
                      ))}
                    </View>
                  </ScrollView>
                </View>
              ))}
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 10, alignItems: "center" }}>
              <TextInput style={[st.mInput, { flex: 1 }]} placeholder="Save mapping as template (name)"
                placeholderTextColor={colors.onSurfaceTertiary} value={tplName} onChangeText={setTplName} />
              <Pressable onPress={saveTemplate} style={st.outlineBtn} disabled={!tplName.trim()}>
                <Text style={st.outlineTxt}>Save Template</Text>
              </Pressable>
            </View>
            <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 10, marginTop: 12 }}>
              <Pressable onPress={() => setShowMap(false)} style={st.mCancel}>
                <Text style={{ fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary }}>Close</Text>
              </Pressable>
              <Pressable onPress={() => { setShowMap(false); remap(mapping); }} style={st.primaryBtn} testID="cai-remap">
                <Text style={st.primaryTxt}>Apply Mapping & Re-validate</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  head: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: spacing.md, paddingVertical: 10, backgroundColor: colors.surface },
  title: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 1 },
  tplBtn: { flexDirection: "row", alignItems: "center", gap: 4, borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  tplTxt: { fontSize: 11, fontWeight: "800", color: colors.brandPrimary },
  chip: { borderWidth: 1, borderColor: colors.divider, borderRadius: 999, paddingHorizontal: 11, paddingVertical: 6, backgroundColor: colors.surface, maxWidth: 230 },
  chipOn: { borderColor: colors.brandPrimary, backgroundColor: `${colors.brandPrimary}14` },
  chipTxt: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: colors.brandPrimary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.divider, padding: 12, marginBottom: 10 },
  cardTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  dim2: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  secTitle: { fontSize: 12, fontWeight: "800", color: colors.onSurface, marginBottom: 6 },
  errBox: { backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FECACA", borderRadius: radius.md, padding: 10, marginBottom: 10 },
  errTxt: { fontSize: 12, color: "#B91C1C", fontWeight: "600" },
  dropZone: { borderWidth: 2, borderStyle: "dashed", borderColor: colors.brandPrimary, borderRadius: radius.lg, alignItems: "center", justifyContent: "center", paddingVertical: 44, paddingHorizontal: 20, backgroundColor: `${colors.brandPrimary}08`, gap: 8 },
  dropTitle: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface, textAlign: "center" },
  statCard: { backgroundColor: colors.background, borderRadius: radius.md, borderWidth: 1, borderColor: colors.divider, paddingHorizontal: 12, paddingVertical: 7, minWidth: 92 },
  statVal: { fontSize: 15, fontWeight: "900", color: colors.onSurface },
  statLbl: { fontSize: 9.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 1 },
  primaryBtn: { backgroundColor: colors.brandPrimary, borderRadius: radius.md, paddingHorizontal: 16, paddingVertical: 9, alignItems: "center" },
  primaryTxt: { fontSize: 12.5, fontWeight: "800", color: "#fff" },
  outlineBtn: { flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 8, alignSelf: "flex-start" },
  outlineTxt: { fontSize: 11.5, fontWeight: "800", color: colors.brandPrimary },
  dupRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 7, paddingHorizontal: 8, borderRadius: radius.md, marginTop: 4 },
  dupRowOn: { backgroundColor: `${colors.brandPrimary}10` },
  dupLbl: { fontSize: 12, fontWeight: "800", color: colors.onSurface },
  tinyChip: { borderWidth: 1, borderColor: colors.divider, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3, maxWidth: 160 },
  tinyTxt: { fontSize: 10, fontWeight: "700", color: colors.onSurfaceSecondary },
  mWrap: { flex: 1, backgroundColor: "rgba(15,23,42,0.5)", alignItems: "center", justifyContent: "center", padding: 16 },
  mCard: { width: Platform.OS === "web" ? 620 : "100%", maxWidth: 640, backgroundColor: colors.surface, borderRadius: radius.lg, padding: 16 },
  mTitle: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  mInput: { borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 7, fontSize: 12.5, color: colors.onSurface, backgroundColor: colors.background },
  mCancel: { paddingHorizontal: 14, paddingVertical: 9 },
  mapRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 5, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider },
  mapLbl: { width: 118, fontSize: 11, fontWeight: "800", color: colors.onSurface },
});
