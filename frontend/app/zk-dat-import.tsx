/**
 * ZKTeco Biometric .dat Import (Web Portal) - Iter 77.
 *
 * A super/company/sub admin picks a firm, uploads the IN.dat + OUT.dat
 * (or a combined .dat) files that came off the ZKTeco terminal, and the
 * backend parses + inserts the punches into ``db.attendance``. Idempotent
 * (re-upload is safe).
 */
import React, { useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator, TextInput,
  Platform, ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { readAuthToken, getApiBaseUrl } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing, type, shadow } from "@/src/theme";

/** DD-MM-YYYY -> YYYY-MM-DD; returns "" if invalid. */
function toISO(dmy: string): string {
  const m = /^(\d{2})-(\d{2})-(\d{4})$/.exec((dmy || "").trim());
  if (!m) return "";
  return `${m[3]}-${m[2]}-${m[1]}`;
}

function formatDdmmyyyy(raw: string): string {
  const d = (raw || "").replace(/\D/g, "").slice(0, 8);
  if (d.length <= 2) return d;
  if (d.length <= 4) return `${d.slice(0, 2)}-${d.slice(2)}`;
  return `${d.slice(0, 2)}-${d.slice(2, 4)}-${d.slice(4)}`;
}

type ImportStats = {
  total_lines: number;
  inserted: number;
  duplicate: number;
  unmapped: number;
  out_of_range: number;
  missing_kind: number;
  unmapped_bio_codes?: string[];
  source_tag?: string;
};

export default function ZkDatImportScreen() {
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const router = useRouter();

  const [companyId, setCompanyId] = useState<string>(selectedCompanyId || "");
  const [inFile, setInFile] = useState<File | null>(null);
  const [outFile, setOutFile] = useState<File | null>(null);
  const [combinedFile, setCombinedFile] = useState<File | null>(null);
  // Iter 106 — Excel imports (IN sheet separate, OUT sheet separate)
  const [inExcel, setInExcel] = useState<File | null>(null);
  const [outExcel, setOutExcel] = useState<File | null>(null);
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportStats | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const canRun =
    !!companyId && (inFile || outFile || combinedFile || inExcel || outExcel) && !busy;

  const upload = async () => {
    if (!canRun) return;
    setBusy(true);
    setResult(null);
    setErr(null);
    try {
      const form = new FormData();
      form.append("company_id", companyId);
      const fISO = toISO(fromDate);
      const tISO = toISO(toDate);
      if (fISO) form.append("from_date", fISO);
      if (tISO) form.append("to_date", tISO);
      if (inFile) form.append("in_file", inFile);
      if (outFile) form.append("out_file", outFile);
      if (combinedFile) form.append("combined_file", combinedFile);
      if (inExcel) form.append("in_excel", inExcel);
      if (outExcel) form.append("out_excel", outExcel);

      // Iter 86 — Use the shared readAuthToken() helper so this upload
      // reads the CURRENT session token from the same place the rest of
      // the app reads it (web localStorage under "llc_session_token"
      // on web, expo-secure-store on native). Previously we manually
      // read the wrong localStorage key which produced 401 "Missing
      // bearer token" for every upload.
      const token = (await readAuthToken()) || "";
      if (!token) {
        throw new Error("You are not signed in. Please log in and retry.");
      }
      // Also use the full absolute BASE URL so this works on native.
      const url = `${getApiBaseUrl()}/admin/attendance/zk-dat-import`;
      const res = await fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
      setResult(body as ImportStats);
    } catch (e: any) {
      setErr(e?.message || "Import failed");
    } finally {
      setBusy(false);
    }
  };

  if (Platform.OS !== "web") {
    return (
      <SafeAreaView style={styles.center}>
        <Ionicons name="desktop-outline" size={40} color={colors.brand} />
        <Text style={styles.centerTitle}>Desktop / Web only</Text>
        <Text style={styles.centerBody}>
          Use the web portal on a computer to upload ZKTeco .dat files.
        </Text>
      </SafeAreaView>
    );
  }

  const canEdit =
    user?.role === "super_admin" ||
    user?.role === "company_admin" ||
    user?.role === "sub_admin";
  if (authLoading) {
    return (
      <SafeAreaView style={styles.center}>
        <ActivityIndicator color={colors.brand} size="large" />
      </SafeAreaView>
    );
  }
  if (!canEdit) {
    return (
      <SafeAreaView style={styles.center}>
        <Ionicons name="lock-closed-outline" size={40} color={colors.error} />
        <Text style={styles.centerTitle}>Admins only</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top", "left", "right"]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.toolbar}>
          <Pressable onPress={() => router.back()} hitSlop={8} style={styles.iconBtn}>
            <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Import ZKTeco Biometric .dat</Text>
            <Text style={styles.subtitle}>
              Upload IN.dat + OUT.dat (or a single combined file) exported from
              the biometric terminal. Device attendance-record exports are also
              supported: tab-separated .TXT (No / TMNo / EnNo / Name / Mode /
              INOUT / DateTime) and binary .DAT backups. Idempotent - safe to
              re-upload.
            </Text>
          </View>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>1. Firm</Text>
          <CompanyPicker
            value={companyId || "all"}
            onChange={(v) => setCompanyId(v === "all" ? "" : v)}
            label=""
            compact
            testID="zk-dat-firm"
          />

          <Text style={[styles.sectionTitle, { marginTop: spacing.md }]}>
            2. Optional date filter
          </Text>
          <View style={styles.row}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>From (DD-MM-YYYY)</Text>
              <TextInput
                style={styles.input}
                value={fromDate}
                onChangeText={(t) => setFromDate(formatDdmmyyyy(t))}
                placeholder="01-06-2026"
                placeholderTextColor={colors.onSurfaceTertiary}
                keyboardType="number-pad"
                maxLength={10}
              />
            </View>
            <View style={{ width: 12 }} />
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>To (DD-MM-YYYY)</Text>
              <TextInput
                style={styles.input}
                value={toDate}
                onChangeText={(t) => setToDate(formatDdmmyyyy(t))}
                placeholder="30-06-2026"
                placeholderTextColor={colors.onSurfaceTertiary}
                keyboardType="number-pad"
                maxLength={10}
              />
            </View>
          </View>
          <Text style={styles.hint}>
            Punches outside this window are skipped. Leave blank to import all.
          </Text>

          <Text style={[styles.sectionTitle, { marginTop: spacing.md }]}>
            3. Upload device file(s) — .dat / .TXT / binary .DAT backup
          </Text>
          <FilePickerRow
            label="IN.dat (entry punches)"
            file={inFile}
            onPick={setInFile}
            testID="zk-in-file"
          />
          <FilePickerRow
            label="OUT.dat (exit punches)"
            file={outFile}
            onPick={setOutFile}
            testID="zk-out-file"
          />
          <FilePickerRow
            label="Combined file (auto-detect from status column)"
            file={combinedFile}
            onPick={setCombinedFile}
            testID="zk-combined-file"
          />

          <Text style={[styles.sectionTitle, { marginTop: spacing.md }]}>
            4. Or import from Excel (IN data separate · OUT data separate)
          </Text>
          <Text style={styles.hint}>
            Columns: CODE | DATE | TIME (header row optional). CODE is the
            biometric code of the employee.{" "}
            <Text
              style={{ color: colors.brand, fontWeight: "800" }}
              onPress={async () => {
                const token = (await readAuthToken()) || "";
                const res = await fetch(
                  `${getApiBaseUrl()}/admin/attendance/import-sample`,
                  { headers: { Authorization: `Bearer ${token}` } },
                );
                const blob = await res.blob();
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = "attendance_import_sample.xlsx";
                a.click();
                URL.revokeObjectURL(a.href);
              }}
              testID="zk-sample-download"
            >
              ⬇ Download Sample Format
            </Text>
          </Text>
          <FilePickerRow
            label="IN punches Excel (.xlsx / .xls)"
            file={inExcel}
            onPick={setInExcel}
            testID="zk-in-excel"
          />
          <FilePickerRow
            label="OUT punches Excel (.xlsx / .xls)"
            file={outExcel}
            onPick={setOutExcel}
            testID="zk-out-excel"
          />

          <Pressable
            onPress={upload}
            disabled={!canRun}
            style={[styles.submitBtn, !canRun && { opacity: 0.5 }]}
            testID="zk-dat-submit"
          >
            {busy ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="cloud-upload-outline" size={16} color="#fff" />
                <Text style={styles.submitTxt}>Import punches</Text>
              </>
            )}
          </Pressable>

          {err ? (
            <View style={styles.errBox}>
              <Ionicons name="alert-circle" size={14} color={colors.error} />
              <Text style={styles.errTxt}>{err}</Text>
            </View>
          ) : null}

          {result ? (
            <View style={styles.resultBox}>
              <Text style={styles.resultTitle}>Import complete</Text>
              <StatRow label="Total lines parsed" value={result.total_lines} />
              <StatRow label="Inserted (new)" value={result.inserted} good />
              <StatRow label="Duplicates skipped" value={result.duplicate} />
              <StatRow label="Unmapped bio codes" value={result.unmapped} warn={result.unmapped > 0} />
              <StatRow label="Out of date range" value={result.out_of_range} />
              <StatRow label="Missing IN/OUT kind" value={result.missing_kind} warn={result.missing_kind > 0} />
              {result.unmapped_bio_codes && result.unmapped_bio_codes.length > 0 ? (
                <View style={{ marginTop: 8 }}>
                  <Text style={styles.label}>Unmapped bio codes (first 50):</Text>
                  <Text style={styles.mono}>
                    {result.unmapped_bio_codes.join(", ")}
                  </Text>
                </View>
              ) : null}
              {result.source_tag ? (
                <Text style={styles.hint}>Batch tag: {result.source_tag}</Text>
              ) : null}
            </View>
          ) : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function FilePickerRow({
  label, file, onPick, testID,
}: {
  label: string;
  file: File | null;
  onPick: (f: File | null) => void;
  testID?: string;
}) {
  return (
    <View style={fileStyles.row}>
      <Text style={styles.label}>{label}</Text>
      <View style={fileStyles.inputRow}>
        <input
          type="file"
          accept=".dat,.txt,text/plain"
          onChange={(e) => onPick(e.target.files?.[0] || null)}
          data-testid={testID}
          style={{
            flex: 1,
            padding: 8,
            border: `1px solid ${colors.border}`,
            borderRadius: 6,
            fontSize: 13,
            background: colors.surface,
          } as any}
        />
        {file ? (
          <Pressable onPress={() => onPick(null)} style={fileStyles.clearBtn}>
            <Ionicons name="close-circle" size={16} color={colors.onSurfaceSecondary} />
          </Pressable>
        ) : null}
      </View>
      {file ? (
        <Text style={styles.hint}>
          Selected: {file.name} ({Math.round(file.size / 1024)} KB)
        </Text>
      ) : null}
    </View>
  );
}

function StatRow({
  label, value, good, warn,
}: {
  label: string;
  value: number;
  good?: boolean;
  warn?: boolean;
}) {
  return (
    <View style={styles.statRow}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text
        style={[
          styles.statValue,
          good && { color: "#10B981" },
          warn && { color: colors.error },
        ]}
      >
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  center: {
    flex: 1, alignItems: "center", justifyContent: "center",
    padding: spacing.lg, gap: spacing.sm,
  },
  centerTitle: { fontSize: type.lg, fontWeight: "800", color: colors.onSurface },
  centerBody: {
    color: colors.onSurfaceSecondary, textAlign: "center", fontSize: type.sm,
    paddingHorizontal: spacing.lg,
  },
  scroll: { padding: spacing.md, gap: spacing.md },
  toolbar: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  iconBtn: {
    width: 34, height: 34, alignItems: "center", justifyContent: "center",
  },
  title: { fontSize: type.h2, fontWeight: "800", color: colors.onSurface },
  subtitle: {
    color: colors.onSurfaceSecondary, marginTop: 2, fontSize: type.sm,
    lineHeight: 18,
  },
  card: {
    padding: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
    ...shadow.card,
  },
  sectionTitle: {
    color: colors.onSurface, fontWeight: "800", fontSize: type.md,
  },
  row: { flexDirection: "row" },
  label: {
    color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "600",
    marginBottom: 4,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 8,
    paddingHorizontal: 12,
    color: colors.onSurface,
    backgroundColor: colors.surface,
    fontSize: type.sm,
    ...Platform.select({ web: { outlineWidth: 0 as any } }),
  },
  hint: {
    color: colors.onSurfaceTertiary, fontSize: 11, fontStyle: "italic",
    marginTop: 4,
  },
  mono: {
    fontFamily: Platform.OS === "web" ? ("monospace" as any) : "Menlo",
    color: colors.onSurface, fontSize: 11, marginTop: 4,
  },
  submitBtn: {
    marginTop: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderRadius: radius.md,
    backgroundColor: colors.brand,
  },
  submitTxt: { color: "#fff", fontWeight: "800", fontSize: type.md },
  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: spacing.sm,
    padding: 8,
    borderRadius: radius.md,
    backgroundColor: "rgba(220, 38, 38, 0.08)",
  },
  errTxt: { color: colors.error, flex: 1, fontSize: type.sm },
  resultBox: {
    marginTop: spacing.md,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 4,
  },
  resultTitle: {
    color: colors.onSurface, fontWeight: "800", fontSize: type.md,
    marginBottom: 4,
  },
  statRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 4,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  statLabel: { color: colors.onSurfaceSecondary, fontSize: type.sm },
  statValue: {
    color: colors.onSurface, fontWeight: "700", fontSize: type.sm,
  },
});

const fileStyles = StyleSheet.create({
  row: { marginBottom: spacing.sm },
  inputRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  clearBtn: { padding: 4 },
});
