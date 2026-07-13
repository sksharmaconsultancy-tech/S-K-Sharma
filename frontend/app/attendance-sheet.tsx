/**
 * Attendance Sheet Automation — Super Admin only (web-focused).
 *
 * The single-screen workflow that automates S.K. Sharma & Co.'s monthly
 * process end-to-end:
 *   1. Generate the pre-populated Excel for a company + month (optionally
 *      filtered by Employee Group)
 *   2. Upload the client's returned sheet (our template OR their random
 *      format) — the server returns an MIS report of fuzzy column matches
 *   3. Review + confirm the column mapping
 *   4. Apply the mapping — imports Gross / Advance / TDS onto employees
 *   5. Trigger a Compliance Salary Run (already existing feature) and
 *      download the ECR / ESIC challans from the compliance-salary-run page
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  TextInput,
  ActivityIndicator,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import MonthPicker from "@/src/components/MonthPicker";
import { colors, radius, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };
type GroupOption = { master_id: string; name: string };
type Match = {
  canonical: string;
  canonical_label: string;
  matched_header: string | null;
  matched_index: number | null;
  confidence: number;
  required: boolean;
};
type MisReport = {
  matches: Match[];
  unmatched_required: string[];
  unrecognised_headers: { index: number; header: string }[];
};
type UploadResponse = {
  ok: boolean;
  row_count: number;
  headers: string[];
  body: any[][];
  body_preview: any[][];
  mis_report: MisReport;
};
type ImportResponse = {
  ok: boolean;
  imported: number;
  unmatched_count: number;
  unmatched: { code: string; name: string }[];
  next: string;
};

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function showMsg(msg: string, title = "Attendance Sheet") {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

export default function AttendanceSheetScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";

  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState<string>("");
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  useEffect(() => {
    if (globalCid) setCompanyId(globalCid);
  }, [globalCid]);
  const [groups, setGroups] = useState<GroupOption[]>([]);
  const [groupId, setGroupId] = useState<string>(""); // "" = All groups
  const [month, setMonth] = useState<string>(currentMonth());
  const [downloading, setDownloading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  // canonical field → column index (or -1 for "unset")
  const [mapping, setMapping] = useState<Record<string, number>>({});
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<ImportResponse | null>(null);

  useEffect(() => {
    if (!isSuper) return;
    (async () => {
      try {
        const r = await api<{ companies: Company[] }>("/companies");
        setCompanies(r.companies || []);
        if (r.companies?.length && !companyId) setCompanyId(r.companies[0].company_id);
      } catch (e: any) {
        showMsg(e?.message || "Could not load companies");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSuper]);

  // Load groups whenever the selected company changes.
  // Iter 77 - Merge legacy masters/group AND the newer Employee Group
  // Policies so the dropdown shows every group actually usable on the
  // backend endpoint.
  useEffect(() => {
    if (!isSuper || !companyId) {
      setGroups([]);
      setGroupId("");
      return;
    }
    (async () => {
      try {
        const [masters, egp] = await Promise.all([
          api<{ items: GroupOption[] }>(
            `/admin/masters?type=group&company_id=${encodeURIComponent(companyId)}`,
          ).catch(() => ({ items: [] })),
          api<{ groups: { group_id: string; name: string }[] }>(
            `/admin/employee-groups?company_id=${encodeURIComponent(companyId)}`,
          ).catch(() => ({ groups: [] })),
        ]);
        const combined: GroupOption[] = [
          ...(masters.items || []),
          ...(egp.groups || []).map((g) => ({
            master_id: g.group_id,
            name: g.name,
            type: "group" as any,
          })),
        ];
        // De-dupe by name (case-insensitive) keeping the first (legacy) source.
        const seen = new Set<string>();
        const unique = combined.filter((g) => {
          const key = (g.name || "").toLowerCase();
          if (!key || seen.has(key)) return false;
          seen.add(key);
          return true;
        });
        setGroups(unique);
        setGroupId("");
      } catch {
        setGroups([]);
      }
    })();
  }, [companyId, isSuper]);

  const generateTemplate = async () => {
    if (!companyId) return showMsg("Pick a company first.");
    if (downloading) return;
    setDownloading(true);
    try {
      const qs = groupId ? `?group_id=${encodeURIComponent(groupId)}` : "";
      const res = await apiBinary(
        `/admin/attendance-sheet/${companyId}/${month}.xlsx${qs}`,
      );
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        const grpLabel = groupId
          ? "_" + (groups.find((g) => g.master_id === groupId)?.name || "group").replace(/\s+/g, "-")
          : "";
        a.download = `AttendanceSheet_${month}${grpLabel}.xlsx`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      showMsg(e?.message || "Template download failed");
    } finally {
      setDownloading(false);
    }
  };

  // Iter 68 — Monthly Attendance Reports (per-day working hours or IN/OUT + hrs)
  const downloadMonthlyReport = useCallback(
    async (variant: "hours" | "inout") => {
      if (!companyId) return showMsg("Pick a company first.");
      if (downloading) return;
      setDownloading(true);
      try {
        const qs = groupId ? `?group_id=${encodeURIComponent(groupId)}` : "";
        const path =
          variant === "hours"
            ? `/admin/attendance/monthly-hours/${companyId}/${month}.xlsx${qs}`
            : `/admin/attendance/monthly-inout/${companyId}/${month}.xlsx${qs}`;
        const res = await apiBinary(path);
        if (Platform.OS === "web" && res.webBlobUrl) {
          const a = document.createElement("a");
          a.href = res.webBlobUrl;
          const grpLabel = groupId
            ? "_" + (groups.find((g) => g.master_id === groupId)?.name || "group").replace(/\s+/g, "-")
            : "";
          const kind = variant === "hours" ? "WorkingHours" : "InOut";
          a.download = `MonthlyAttendance_${kind}_${month}${grpLabel}.xlsx`;
          a.click();
          setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
        }
      } catch (e: any) {
        showMsg(e?.message || "Report download failed");
      } finally {
        setDownloading(false);
      }
    },
    [companyId, month, groupId, downloading, groups],
  );

  const pickAndUpload = useCallback(async () => {
    if (Platform.OS !== "web") {
      showMsg("Please use the web portal for uploading Excel sheets.");
      return;
    }
    const input = document.createElement("input");
    input.type = "file";
    input.accept =
      ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      setUploading(true);
      try {
        const fd = new FormData();
        fd.append("file", file);
        const url = `/api/admin/attendance-sheet/upload`; // web-only flow → same-origin (avoids Cloudflare cross-origin challenges)
        const token =
          typeof globalThis !== "undefined" &&
          (globalThis as any).localStorage?.getItem("llc_session_token");
        const res = await fetch(url, {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: fd,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || `Upload failed (${res.status})`);
        }
        const json = (await res.json()) as UploadResponse;
        setUpload(json);
        // Pre-fill mapping with confident matches
        const initial: Record<string, number> = {};
        for (const m of json.mis_report.matches) {
          initial[m.canonical] = m.matched_index ?? -1;
        }
        setMapping(initial);
        setImportResult(null);
      } catch (e: any) {
        showMsg(e?.message || "Upload failed");
      } finally {
        setUploading(false);
      }
    };
    input.click();
  }, []);

  const applyMapping = async () => {
    if (!upload || !companyId) return;
    setImporting(true);
    setImportResult(null);
    try {
      // Filter out unset (-1) mappings
      const finalMap: Record<string, number> = {};
      for (const [k, v] of Object.entries(mapping)) {
        if (v !== undefined && v >= 0) finalMap[k] = v;
      }
      const r = await api<ImportResponse>(
        "/admin/attendance-sheet/apply-mapping",
        {
          method: "POST",
          body: {
            company_id: companyId,
            month,
            headers: upload.headers,
            body: upload.body,
            mapping: finalMap,
          },
        },
      );
      setImportResult(r);
    } catch (e: any) {
      showMsg(e?.message || "Import failed");
    } finally {
      setImporting(false);
    }
  };

  const bulkImportEmployees = async (dryRun: boolean) => {
    if (!upload || !companyId) return;
    setImporting(true);
    try {
      const finalMap: Record<string, number> = {};
      for (const [k, v] of Object.entries(mapping)) {
        if (v !== undefined && v >= 0) finalMap[k] = v;
      }
      const r = await api<{
        ok: boolean;
        created: any[];
        updated: any[];
        skipped: any[];
        new_masters: any[];
        dry_run: boolean;
      }>("/admin/attendance-sheet/bulk-import-employees", {
        method: "POST",
        body: {
          company_id: companyId,
          month,
          headers: upload.headers,
          body: upload.body,
          mapping: finalMap,
          default_group_id: groupId || null,
          dry_run: dryRun,
        },
      });
      const summary =
        `${dryRun ? "Preview" : "Applied"}:\n` +
        `  Created:  ${r.created.length}\n` +
        `  Updated:  ${r.updated.length}\n` +
        `  Skipped:  ${r.skipped.length}\n` +
        `  New masters auto-created: ${r.new_masters.length}`;
      showMsg(summary);
    } catch (e: any) {
      showMsg(e?.message || "Bulk import failed");
    } finally {
      setImporting(false);
    }
  };

  const jumpToComplianceRun = () => router.push("/compliance-salary-run");

  if (!isSuper) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Only the Super Admin can access the Attendance Sheet automation.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.h1}>Attendance Sheet Automation</Text>
            <Text style={styles.hsub}>
              Generate · Upload · Match columns · Import · Process compliance
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Step 1 — generate + upload */}
        <View style={styles.card}>
          <View style={styles.stepHead}>
            <View style={styles.stepBadge}><Text style={styles.stepBadgeTxt}>1</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.stepTitle}>Generate & email attendance sheet to client</Text>
              <Text style={styles.smallHint}>
                Pick a company + month → download the pre-populated Excel to
                send. Optional: filter by Employee Group to export a
                group-wise sheet. Auto-email cron runs on the last day of
                each month.
              </Text>
            </View>
          </View>
          <View style={styles.gridRow}>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Company</Text>
              <View style={styles.pickerWrap}>
                {Platform.OS === "web" ? (
                  <select
                    testID="ms-company"
                    value={companyId}
                    onChange={(e) => setCompanyId((e.target as HTMLSelectElement).value)}
                    style={{
                      padding: 10,
                      borderRadius: 8,
                      borderColor: colors.borderStrong,
                      borderWidth: 1,
                      fontSize: 14,
                      width: "100%",
                    } as any}
                  >
                    <option value="">— select —</option>
                    {companies.map((c) => (
                      <option key={c.company_id} value={c.company_id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Text style={styles.smallHint}>Best used on desktop web.</Text>
                )}
              </View>
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Month</Text>
              <MonthPicker
                value={month}
                onChange={setMonth}
                allowEmpty={false}
                testID="ms-month"
              />
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Employee Group (optional)</Text>
              <View style={styles.pickerWrap}>
                {Platform.OS === "web" ? (
                  <select
                    testID="ms-group"
                    value={groupId}
                    onChange={(e) => setGroupId((e.target as HTMLSelectElement).value)}
                    style={{
                      padding: 10,
                      borderRadius: 8,
                      borderColor: colors.borderStrong,
                      borderWidth: 1,
                      fontSize: 14,
                      width: "100%",
                    } as any}
                  >
                    <option value="">All groups</option>
                    {groups.map((g) => (
                      <option key={g.master_id} value={g.master_id}>
                        {g.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Text style={styles.smallHint}>Best used on desktop web.</Text>
                )}
              </View>
            </View>
          </View>
          <Pressable
            onPress={generateTemplate}
            disabled={downloading || !companyId}
            style={[styles.primaryBtn, (!companyId || downloading) && { opacity: 0.6 }]}
            testID="ms-download-template"
          >
            {downloading ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="download-outline" size={16} color="#fff" />
                <Text style={styles.primaryBtnTxt}>
                  Download attendance sheet{groupId ? " (group-wise)" : ""}
                </Text>
              </>
            )}
          </Pressable>
        </View>

        {/* Iter 68 — Monthly attendance reports */}
        <View style={styles.card}>
          <View style={styles.stepHead}>
            <View style={[styles.stepBadge, { backgroundColor: "#E0F2FE" }]}>
              <Ionicons name="stats-chart-outline" size={14} color="#0369A1" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.stepTitle}>Monthly attendance reports</Text>
              <Text style={styles.smallHint}>
                Ready-made per-day reports for the selected company + month{groupId ? " + group" : ""}.
              </Text>
            </View>
          </View>
          <View style={{ flexDirection: "row", gap: 10, flexWrap: "wrap" }}>
            {/* Iter 76 — Live in-portal grid view. Opens the same
                per-employee × per-day matrix but rendered on-screen so
                admins don't need to open an Excel file first. */}
            <Pressable
              onPress={() => {
                const q = new URLSearchParams();
                if (month) q.set("month", month);
                if (companyId) q.set("company_id", companyId);
                const qs = q.toString();
                router.push(("/attendance-grid" + (qs ? "?" + qs : "")) as any);
              }}
              disabled={!companyId}
              style={[
                styles.reportBtn,
                { backgroundColor: "#ECFDF5", borderColor: "#A7F3D0" },
                !companyId && { opacity: 0.6 },
              ]}
              testID="ms-open-grid-view"
            >
              <Ionicons name="apps-outline" size={16} color="#047857" />
              <View style={{ flex: 1 }}>
                <Text style={[styles.reportBtnTitle, { color: "#047857" }]}>
                  Grid View (on-screen)
                </Text>
                <Text style={styles.reportBtnSub}>
                  Live per-employee × per-day IN / OUT + hours matrix. Switch
                  between IN/OUT and Hours-only, search &amp; export inline.
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={16} color="#047857" />
            </Pressable>
            <Pressable
              onPress={() => downloadMonthlyReport("hours")}
              disabled={downloading || !companyId}
              style={[styles.reportBtn, (!companyId || downloading) && { opacity: 0.6 }]}
              testID="ms-download-monthly-hours"
            >
              <Ionicons name="grid-outline" size={16} color="#0369A1" />
              <View style={{ flex: 1 }}>
                <Text style={styles.reportBtnTitle}>Monthly working hours</Text>
                <Text style={styles.reportBtnSub}>
                  One cell per day showing total worked hours (matches the reference format).
                </Text>
              </View>
              <Ionicons name="download-outline" size={16} color="#0369A1" />
            </Pressable>
            <Pressable
              onPress={() => downloadMonthlyReport("inout")}
              disabled={downloading || !companyId}
              style={[styles.reportBtn, (!companyId || downloading) && { opacity: 0.6 }]}
              testID="ms-download-monthly-inout"
            >
              <Ionicons name="swap-vertical-outline" size={16} color="#0369A1" />
              <View style={{ flex: 1 }}>
                <Text style={styles.reportBtnTitle}>Monthly IN / OUT + hours</Text>
                <Text style={styles.reportBtnSub}>
                  Each day cell shows IN time, OUT time and total working hours.
                </Text>
              </View>
              <Ionicons name="download-outline" size={16} color="#0369A1" />
            </Pressable>
          </View>
        </View>

        {/* Step 2 — upload completed sheet */}
        <View style={styles.card}>
          <View style={styles.stepHead}>
            <View style={styles.stepBadge}><Text style={styles.stepBadgeTxt}>2</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.stepTitle}>Upload the completed sheet</Text>
              <Text style={styles.smallHint}>
                Client can return in our template OR any other Excel — our MIS
                matcher will fuzzy-map their columns to ours.
              </Text>
            </View>
          </View>
          <Pressable
            onPress={pickAndUpload}
            disabled={uploading || !companyId}
            style={[styles.secondaryBtn, (uploading || !companyId) && { opacity: 0.6 }]}
            testID="ms-upload"
          >
            {uploading ? (
              <ActivityIndicator color={colors.brandPrimary} />
            ) : (
              <>
                <Ionicons name="cloud-upload-outline" size={16} color={colors.brandPrimary} />
                <Text style={styles.secondaryBtnTxt}>Pick .xlsx file to upload</Text>
              </>
            )}
          </Pressable>
        </View>

        {/* Step 3 — MIS report + confirm mapping */}
        {upload ? (
          <View style={styles.card}>
            <View style={styles.stepHead}>
              <View style={styles.stepBadge}><Text style={styles.stepBadgeTxt}>3</Text></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.stepTitle}>
                  MIS report — column matches ({upload.row_count} rows detected)
                </Text>
                <Text style={styles.smallHint}>
                  Confirm which uploaded column feeds each of our canonical
                  fields. Confident matches (≥ 65 %) are pre-selected.
                </Text>
              </View>
            </View>
            {upload.mis_report.unmatched_required.length > 0 ? (
              <View style={styles.warnBox}>
                <Ionicons name="warning-outline" size={16} color="#7A1B00" />
                <Text style={styles.warnTxt}>
                  Missing required fields — please map them below:{" "}
                  <Text style={{ fontWeight: "800" }}>
                    {upload.mis_report.unmatched_required.join(", ")}
                  </Text>
                </Text>
              </View>
            ) : null}

            {upload.mis_report.matches.map((m) => (
              <View key={m.canonical} style={styles.matchRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.matchLabel}>
                    {m.canonical_label}
                    {m.required ? <Text style={{ color: "#8A1F1F" }}> *</Text> : null}
                  </Text>
                  {m.matched_header ? (
                    <Text style={styles.matchSub}>
                      Suggested → “{m.matched_header}” · {m.confidence}% match
                    </Text>
                  ) : (
                    <Text style={styles.matchSubMuted}>No confident match — please pick manually.</Text>
                  )}
                </View>
                {Platform.OS === "web" ? (
                  <select
                    testID={`ms-map-${m.canonical}`}
                    value={String(mapping[m.canonical] ?? -1)}
                    onChange={(e) =>
                      setMapping({
                        ...mapping,
                        [m.canonical]: Number((e.target as HTMLSelectElement).value),
                      })
                    }
                    style={{
                      padding: 8,
                      borderRadius: 6,
                      borderColor: colors.borderStrong,
                      borderWidth: 1,
                      minWidth: 220,
                    } as any}
                  >
                    <option value="-1">— unset —</option>
                    {upload.headers.map((h, i) => (
                      <option key={i} value={i}>
                        {h || `Column ${i + 1}`}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Text style={styles.smallHint}>Web-only.</Text>
                )}
              </View>
            ))}

            <Pressable
              onPress={applyMapping}
              disabled={importing}
              style={[styles.primaryBtn, importing && { opacity: 0.6 }]}
              testID="ms-apply"
            >
              {importing ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="checkmark-done-outline" size={16} color="#fff" />
                  <Text style={styles.primaryBtnTxt}>Confirm mapping & import</Text>
                </>
              )}
            </Pressable>

            {/* Bulk import — creates missing employees + auto-tags Group/Dept/Designation */}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
              <Pressable
                onPress={() => bulkImportEmployees(true)}
                disabled={importing}
                style={[styles.secondaryBtn, { flex: 1 }, importing && { opacity: 0.5 }]}
                testID="ms-bulk-preview"
              >
                <Ionicons name="eye-outline" size={14} color={colors.brandPrimary} />
                <Text style={styles.secondaryBtnTxt}>Bulk-import preview</Text>
              </Pressable>
              <Pressable
                onPress={() => bulkImportEmployees(false)}
                disabled={importing}
                style={[styles.secondaryBtn, { flex: 1 }, importing && { opacity: 0.5 }]}
                testID="ms-bulk-apply"
              >
                <Ionicons name="person-add-outline" size={14} color={colors.brandPrimary} />
                <Text style={styles.secondaryBtnTxt}>Bulk-import employees</Text>
              </Pressable>
            </View>
            <Text style={styles.smallHint}>
              Bulk-import auto-creates missing employees (approval required) and
              new Group / Department / Designation masters detected in the sheet.
            </Text>
          </View>
        ) : null}

        {/* Step 4 — Import result + next step */}
        {importResult ? (
          <View style={styles.card}>
            <View style={styles.stepHead}>
              <View style={[styles.stepBadge, { backgroundColor: colors.success }]}>
                <Ionicons name="checkmark" size={12} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.stepTitle}>Imported</Text>
                <Text style={styles.smallHint}>
                  {importResult.imported} employee
                  {importResult.imported === 1 ? "" : "s"} updated · {importResult.unmatched_count}{" "}
                  row{importResult.unmatched_count === 1 ? "" : "s"} could not be matched.
                </Text>
              </View>
            </View>
            {importResult.unmatched.length > 0 ? (
              <View style={styles.warnBox}>
                <Ionicons name="alert-circle-outline" size={16} color="#7A1B00" />
                <View style={{ flex: 1 }}>
                  <Text style={styles.warnTxt}>
                    These rows in the uploaded sheet had no matching employee:
                  </Text>
                  {importResult.unmatched.slice(0, 10).map((u, i) => (
                    <Text key={i} style={styles.unmatchedItem}>
                      · {u.code || "no code"} {u.name ? `— ${u.name}` : ""}
                    </Text>
                  ))}
                  {importResult.unmatched.length > 10 ? (
                    <Text style={styles.unmatchedItem}>
                      … +{importResult.unmatched.length - 10} more
                    </Text>
                  ) : null}
                </View>
              </View>
            ) : null}

            <Pressable
              onPress={jumpToComplianceRun}
              style={styles.primaryBtn}
              testID="ms-goto-compliance"
            >
              <Ionicons name="briefcase-outline" size={16} color="#fff" />
              <Text style={styles.primaryBtnTxt}>
                Continue → Run Compliance Salary Process
              </Text>
            </Pressable>
          </View>
        ) : null}
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  h1: { color: colors.onSurface, fontSize: type.xl, fontWeight: "800" },
  hsub: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },
  scroll: { padding: spacing.lg, maxWidth: 960, alignSelf: "center", width: "100%" },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: {
    marginTop: 8,
    color: colors.onSurfaceSecondary,
    fontSize: type.body,
    textAlign: "center",
  },

  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  stepHead: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 10 },
  stepBadge: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  stepBadgeTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  stepTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800" },
  smallHint: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 2 },

  gridRow: { flexDirection: "row", gap: 10, flexWrap: "wrap", marginBottom: 6 },
  gridCol: { flex: 1, minWidth: 220 },
  label: {
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    fontWeight: "800",
    marginBottom: 4,
    marginTop: 4,
    textTransform: "uppercase",
  },
  input: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  pickerWrap: { paddingVertical: 2 },

  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    marginTop: 8,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800" },
  secondaryBtn: {
    borderRadius: radius.md,
    paddingVertical: 12,
    marginTop: 4,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  secondaryBtnTxt: { color: colors.brandPrimary, fontWeight: "800" },

  // Iter 68 — Monthly report buttons
  reportBtn: {
    flex: 1,
    minWidth: 260,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    borderWidth: 1,
    borderColor: "#BAE6FD",
    backgroundColor: "#F0F9FF",
    borderRadius: radius.md,
  },
  reportBtnTitle: { color: "#0F172A", fontSize: 14, fontWeight: "800" },
  reportBtnSub: {
    color: "#475569",
    fontSize: 11,
    lineHeight: 15,
    marginTop: 2,
  },

  warnBox: {
    flexDirection: "row",
    gap: 8,
    padding: 10,
    backgroundColor: "#FDECE2",
    borderRadius: 8,
    marginBottom: 10,
    alignItems: "flex-start",
  },
  warnTxt: { flex: 1, color: "#7A1B00", fontSize: 12, lineHeight: 18 },
  unmatchedItem: { color: "#7A1B00", fontSize: 11, marginTop: 2 },

  matchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
    flexWrap: "wrap",
  },
  matchLabel: { color: colors.onSurface, fontSize: 13, fontWeight: "700" },
  matchSub: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 2 },
  matchSubMuted: { color: "#8A1F1F", fontSize: 11, marginTop: 2 },
});
