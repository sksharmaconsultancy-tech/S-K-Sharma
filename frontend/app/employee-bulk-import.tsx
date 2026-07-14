/**
 * Employee Bulk Import — Iter 71.
 *
 * Web-only screen (native falls back to a helpful nudge) that lets an
 * operator upload a CSV of employees and register them all in one call
 * against the currently-selected firm.
 *
 * Flow:
 *   1. Operator picks a firm (top-of-page picker, same UX as Add
 *      Employee).
 *   2. Downloads the CSV template (columns match what the backend
 *      accepts).
 *   3. Fills the template, drags/drops it back into the page → we
 *      parse in-browser using PapaParse.
 *   4. Preview shows the first 25 rows so the operator can spot bad
 *      data before submitting.
 *   5. "Import" posts the rows to `POST /admin/employees/bulk-import`.
 *      The server returns per-row created / skipped / error results
 *      which we render as a summary + downloadable log CSV.
 *
 * Notes:
 *   * The endpoint is idempotent per-phone/email, so re-importing the
 *     same file is safe (dupes go into skipped_duplicates).
 *   * Every newly-created employee is auto-approved with a random 6-digit
 *     temp PIN + pin_must_change=true.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Platform,
  ScrollView,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";

type ParsedRow = Record<string, string>;
type ImportResult = {
  ok: boolean;
  created_count: number;
  skipped_count: number;
  error_count: number;
  created: {
    row: number;
    name: string;
    user_id: string;
    employee_code: string | null;
    temp_pin: string;
  }[];
  skipped_duplicates: {
    row: number;
    name: string;
    reason: string;
    existing_user_id: string;
  }[];
  errors: { row: number; reason: string }[];
};

/** Minimal RFC-4180-ish CSV parser (handles quotes + commas in fields). */
function parseCsv(text: string): { headers: string[]; rows: ParsedRow[] } {
  const lines: string[] = [];
  let buf = "";
  let inQ = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"') {
      if (inQ && text[i + 1] === '"') {
        buf += '"';
        i++;
      } else {
        inQ = !inQ;
      }
    } else if ((ch === "\n" || ch === "\r") && !inQ) {
      if (buf.length > 0 || lines.length > 0) lines.push(buf);
      buf = "";
      if (ch === "\r" && text[i + 1] === "\n") i++;
    } else {
      buf += ch;
    }
  }
  if (buf.length) lines.push(buf);
  const cells: string[][] = lines
    .filter((l) => l.trim().length > 0)
    .map((line) => {
      const out: string[] = [];
      let cur = "";
      let q = false;
      for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (ch === '"') {
          if (q && line[i + 1] === '"') {
            cur += '"';
            i++;
          } else {
            q = !q;
          }
        } else if (ch === "," && !q) {
          out.push(cur);
          cur = "";
        } else {
          cur += ch;
        }
      }
      out.push(cur);
      return out;
    });
  if (cells.length === 0) return { headers: [], rows: [] };
  const headers = cells[0].map((h) => h.trim());
  const rows: ParsedRow[] = cells.slice(1).map((r) => {
    const o: ParsedRow = {};
    headers.forEach((h, i) => {
      o[h] = (r[i] || "").trim();
    });
    return o;
  });
  return { headers, rows };
}

export default function EmployeeBulkImportScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const {
    selectedCompany,
    selectedCompanyId,
    setSelectedCompanyId,
    companies,
    companiesLoading,
    reloadCompanies,
  } = useSelectedCompany();

  // Self-heal: if the firm list is empty (initial fetch raced auth or
  // failed once), re-fetch on mount so the picker always shows firm names.
  useEffect(() => {
    if (companies.length === 0 && !companiesLoading) void reloadCompanies();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isAdmin =
    user?.role === "super_admin" ||
    user?.role === "sub_admin" ||
    user?.role === "company_admin";
  const canSwitchFirm = user?.role === "super_admin" || user?.role === "sub_admin";

  const [rows, setRows] = useState<ParsedRow[]>([]);
  const [headers, setHeaders] = useState<string[]>([]);
  const [fileName, setFileName] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const canImport = !!selectedCompanyId && rows.length > 0 && !importing;

  const numeric = useMemo(() => ["salary_monthly", "compliance_gross"], []);
  const cleanRows = useMemo(
    () =>
      rows.map((r) => {
        const o: Record<string, any> = { ...r };
        for (const k of numeric) {
          if (o[k]) o[k] = Number(String(o[k]).replace(/[^\d.]/g, "")) || undefined;
        }
        return o;
      }),
    [rows, numeric],
  );

  const downloadTemplate = async () => {
    const res = await apiBinary("/admin/employees/bulk-import-template.csv");
    if (Platform.OS === "web" && res.webBlobUrl) {
      const a = document.createElement("a");
      a.href = res.webBlobUrl;
      a.download = "employee_bulk_import_template.csv";
      a.click();
      setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
    }
  };

  const onPickFile = (file: File) => {
    setParseError(null);
    setResult(null);
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const text = String(reader.result || "");
        const { headers: h, rows: r } = parseCsv(text);
        if (h.length === 0 || r.length === 0) {
          setParseError("Empty CSV — no rows detected.");
          setHeaders([]);
          setRows([]);
          return;
        }
        if (
          !h.some((x) => {
            const n = x.trim().toLowerCase().replace(/\s+/g, " ");
            return n === "name" || n === "employee name";
          })
        ) {
          setParseError('Missing "EMPLOYEE NAME" (or "name") column in the CSV header.');
          return;
        }
        setHeaders(h);
        setRows(r);
        setFileName(file.name);
      } catch (e: any) {
        setParseError(e?.message || "Failed to parse the CSV.");
      }
    };
    reader.readAsText(file);
  };

  const runImport = async () => {
    if (!selectedCompanyId || rows.length === 0) return;
    setImporting(true);
    setResult(null);
    try {
      const r = await api<ImportResult>("/admin/employees/bulk-import", {
        method: "POST",
        body: {
          company_id: selectedCompanyId,
          rows: cleanRows,
        },
      });
      setResult(r);
    } catch (e: any) {
      setParseError(e?.message || "Import failed.");
    } finally {
      setImporting(false);
    }
  };

  const downloadLog = () => {
    if (!result) return;
    const lines = ["row,status,name,employee_code,temp_pin,reason"];
    for (const c of result.created) {
      lines.push(`${c.row},created,"${c.name}",${c.employee_code || ""},${c.temp_pin},`);
    }
    for (const s of result.skipped_duplicates) {
      lines.push(`${s.row},skipped,"${s.name}",,,${s.reason}`);
    }
    for (const e of result.errors) {
      lines.push(`${e.row},error,,,,${e.reason}`);
    }
    if (Platform.OS === "web") {
      const blob = new Blob([lines.join("\n")], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bulk_import_log_${Date.now()}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }
  };

  if (!isAdmin) {
    return (
      <View style={styles.forbid}>
        <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
        <Text style={styles.forbidT}>Admins only</Text>
      </View>
    );
  }
  if (Platform.OS !== "web") {
    return (
      <View style={styles.forbid}>
        <Ionicons name="cloud-upload-outline" size={40} color={colors.onSurfaceTertiary} />
        <Text style={styles.forbidT}>Web-only feature</Text>
        <Text style={styles.forbidHint}>
          Open the web portal on a laptop to bulk-import employees from a
          CSV. Adding one-by-one is available on mobile.
        </Text>
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
            <Text style={styles.h1}>Bulk import employees</Text>
            <Text style={styles.hsub}>Upload a CSV — one row per new hire</Text>
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>
        {/* Firm picker */}
        <View style={styles.firmCard}>
          <Ionicons name="business" size={20} color={colors.brandPrimary} />
          <View style={{ flex: 1 }}>
            <Text style={styles.firmLabel}>Import under firm</Text>
            {canSwitchFirm ? (
              <select
                value={selectedCompanyId || ""}
                onChange={(e) =>
                  setSelectedCompanyId((e.target as HTMLSelectElement).value || null)
                }
                style={styles.firmSelect as any}
              >
                <option value="">
                  {companiesLoading && companies.length === 0
                    ? "Loading firms…"
                    : "— pick a firm —"}
                </option>
                {companies.map((c) => (
                  <option key={c.company_id} value={c.company_id}>
                    {c.name}
                    {c.company_code ? ` · ${c.company_code}` : ""}
                  </option>
                ))}
              </select>
            ) : (
              <Text style={styles.firmName}>{selectedCompany?.name || "—"}</Text>
            )}
          </View>
        </View>

        {/* Step 1 — template */}
        <View style={styles.card}>
          <Text style={styles.section}>1 · Download the template</Text>
          <Text style={styles.hint}>
            The CSV has 26 columns — <Text style={{ fontWeight: "700" }}>name</Text> is
            mandatory, plus either <Text style={{ fontWeight: "700" }}>phone</Text> or{" "}
            <Text style={{ fontWeight: "700" }}>email</Text>.
          </Text>
          <Text style={styles.hint}>
            <Text style={{ fontWeight: "700" }}>Allowances / deductions</Text> use
            pipe-separated <Text style={{ fontStyle: "italic" }}>Head:Amount</Text> pairs, e.g.{" "}
            <Text style={{ fontFamily: Platform.OS === "web" ? "monospace" : undefined, fontWeight: "600" }}>
              HRA:2000|Convey:500|SpecialAllow:1000
            </Text>{" "}
            — one column each for Actual & Compliance payroll.
          </Text>
          <Pressable onPress={downloadTemplate} style={styles.secondaryBtn}>
            <Ionicons name="download-outline" size={16} color={colors.brandPrimary} />
            <Text style={styles.secondaryBtnTxt}>Download template CSV</Text>
          </Pressable>
        </View>

        {/* Step 2 — upload */}
        <View style={styles.card}>
          <Text style={styles.section}>2 · Upload your filled CSV</Text>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => {
              const f = (e.target as HTMLInputElement).files?.[0];
              if (f) onPickFile(f);
            }}
            style={{
              padding: 8,
              borderRadius: 6,
              border: `1px solid ${colors.divider}`,
              width: "100%",
              backgroundColor: colors.surface,
            } as any}
          />
          {fileName ? (
            <Text style={styles.hint}>
              Loaded <Text style={{ fontWeight: "700" }}>{fileName}</Text> —{" "}
              {rows.length} row{rows.length === 1 ? "" : "s"} detected.
            </Text>
          ) : null}
          {parseError ? (
            <View style={styles.errBox}>
              <Ionicons name="alert-circle" size={16} color="#B0002B" />
              <Text style={styles.errTxt}>{parseError}</Text>
            </View>
          ) : null}
        </View>

        {/* Step 3 — preview */}
        {rows.length > 0 ? (
          <View style={styles.card}>
            <Text style={styles.section}>3 · Preview (first 25 rows)</Text>
            <View style={styles.tableWrap}>
              <View style={styles.trHead}>
                {headers.map((h) => (
                  <Text key={h} style={styles.th}>{h}</Text>
                ))}
              </View>
              {rows.slice(0, 25).map((r, i) => (
                <View
                  key={i}
                  style={[styles.tr, i % 2 === 0 && styles.trAlt]}
                >
                  {headers.map((h) => (
                    <Text key={h} style={styles.td} numberOfLines={1}>
                      {r[h] || ""}
                    </Text>
                  ))}
                </View>
              ))}
            </View>
            {rows.length > 25 ? (
              <Text style={styles.hint}>
                + {rows.length - 25} more row{rows.length - 25 === 1 ? "" : "s"} not
                shown in preview.
              </Text>
            ) : null}
          </View>
        ) : null}

        {/* Step 4 — import */}
        <View style={styles.card}>
          <Text style={styles.section}>4 · Import</Text>
          <Pressable
            onPress={runImport}
            disabled={!canImport}
            style={[styles.primaryBtn, !canImport && styles.btnDisabled]}
          >
            {importing ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="cloud-upload-outline" size={18} color="#fff" />
                <Text style={styles.primaryBtnTxt}>
                  Import {rows.length} employees
                </Text>
              </>
            )}
          </Pressable>
        </View>

        {/* Result */}
        {result ? (
          <View style={[styles.card, styles.successCard]}>
            <Text style={styles.successTitle}>
              <Ionicons name="checkmark-circle" size={16} color="#0F7B4F" />{" "}
              Import complete
            </Text>
            <Text style={styles.successRow}>
              Created: <Text style={styles.bold}>{result.created_count}</Text> ·
              Skipped: <Text style={styles.bold}>{result.skipped_count}</Text> ·
              Errors: <Text style={styles.bold}>{result.error_count}</Text>
            </Text>
            {result.created_count > 0 ? (
              <Text style={styles.successHint}>
                Each new employee has a temp 6-digit PIN — download the log
                below to share with them.
              </Text>
            ) : null}
            <Pressable onPress={downloadLog} style={styles.secondaryBtn}>
              <Ionicons name="download-outline" size={16} color={colors.brandPrimary} />
              <Text style={styles.secondaryBtnTxt}>Download log CSV</Text>
            </Pressable>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
  },
  h1: { ...type.h2, color: colors.onSurface },
  hsub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: 8,
    ...shadow.card,
  },
  section: { ...type.body, fontWeight: "800", color: colors.onSurface },
  hint: { ...type.caption, color: colors.onSurfaceSecondary },
  firmCard: {
    flexDirection: "row",
    gap: spacing.sm,
    alignItems: "flex-start",
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  firmLabel: {
    ...type.caption,
    fontWeight: "700",
    color: colors.onSurfaceSecondary,
    marginBottom: 4,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  firmSelect: {
    padding: 10,
    borderRadius: 8,
    borderColor: colors.divider,
    borderWidth: 1,
    fontSize: 14,
    width: "100%",
    backgroundColor: colors.surface,
    color: colors.onSurface,
  },
  firmName: { ...type.body, fontWeight: "700", color: colors.onSurface },
  primaryBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: radius.md,
    backgroundColor: colors.brandPrimary,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "700", fontSize: 14 },
  secondaryBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.surface,
    alignSelf: "flex-start",
  },
  secondaryBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 13 },
  btnDisabled: { opacity: 0.5 },
  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FFE9EE",
    borderColor: "#F1B6C2",
    borderWidth: 1,
    borderRadius: radius.sm,
    padding: 8,
  },
  errTxt: { color: "#B0002B", fontSize: 12, flex: 1 },
  successCard: {
    backgroundColor: "#E7F5EE",
    borderColor: "#B7DEC7",
    borderWidth: 1,
  },
  successTitle: { ...type.body, fontWeight: "700", color: "#0F7B4F" },
  successRow: { ...type.body, color: "#0F7B4F" },
  successHint: {
    ...type.caption,
    color: "#0F7B4F",
    marginTop: 4,
  },
  bold: { fontWeight: "800" },
  tableWrap: {
    borderWidth: 1,
    borderColor: colors.divider,
    borderRadius: radius.sm,
    overflow: "hidden",
    marginTop: 6,
  },
  trHead: {
    flexDirection: "row",
    backgroundColor: colors.surfaceSecondary,
    paddingHorizontal: 6,
    paddingVertical: 4,
  },
  tr: {
    flexDirection: "row",
    paddingHorizontal: 6,
    paddingVertical: 4,
  },
  trAlt: { backgroundColor: "#F7F9F9" },
  th: {
    ...type.caption,
    color: colors.onSurfaceSecondary,
    fontWeight: "800",
    textTransform: "uppercase",
    letterSpacing: 0.3,
    flex: 1,
    minWidth: 90,
    fontSize: 10,
  },
  td: {
    ...type.caption,
    color: colors.onSurface,
    flex: 1,
    minWidth: 90,
    fontSize: 11,
  },
  forbid: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    gap: spacing.md,
  },
  forbidT: { ...type.h3, color: colors.onSurfaceSecondary },
  forbidHint: {
    ...type.caption,
    color: colors.onSurfaceTertiary,
    textAlign: "center",
    paddingHorizontal: spacing.xl,
  },
});
