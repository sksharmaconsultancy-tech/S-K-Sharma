/**
 * Bonus Calculation — Iter 59.
 *
 * Statutory Bonus (Payment of Bonus Act, 1965) processing:
 *   • Pick a Firm + Financial Year (Apr–Mar) + optional Employee Group
 *   • Preview computed bonus per employee (rate %, wage ceiling, months
 *     worked, eligibility)
 *   • Save the run (persist to `bonus_runs`)
 *   • Download the Bonus Report as .xlsx
 *   • Rules are configurable per-firm on this same screen —
 *     rate %, wage ceiling, eligibility cap can be updated anytime.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
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
import { colors, radius, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };
type GroupOption = { master_id: string; name: string };
type BonusPolicy = {
  rate_percent: number;
  wage_ceiling: number;
  eligibility_cap: number;
  basic_percent_of_gross: number;
  min_months_worked: number;
  notes?: string;
};
type BonusRow = {
  user_id: string;
  employee_code: string;
  name: string;
  doj: string;
  exit_date: string;
  gross_monthly: number;
  basic_monthly: number;
  months_worked: number;
  eligible: boolean;
  wage_base_used: number;
  rate_percent: number;
  bonus_amount: number;
};
type BonusResult = {
  run_id?: string;
  company_id: string;
  company_name?: string;
  fy_start_year: number;
  fy_label: string;
  date_from: string;
  date_to: string;
  group_id?: string | null;
  group_name?: string | null;
  policy_used: BonusPolicy;
  rows: BonusRow[];
  total_employees: number;
  eligible_count: number;
  total_bonus: number;
};
type BonusRunListItem = Omit<BonusResult, "rows"> & { created_at: string };

function fyOptions(): { start: number; label: string }[] {
  const now = new Date();
  const y = now.getFullYear();
  const currentStart = now.getMonth() >= 3 ? y : y - 1;
  const out: { start: number; label: string }[] = [];
  for (let i = -1; i <= 3; i++) {
    const s = currentStart - i;
    out.push({ start: s, label: `FY ${s}-${String(s + 1).slice(-2)}` });
  }
  return out;
}

function inr(n: number): string {
  if (!Number.isFinite(n)) return "₹0";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function showMsg(msg: string, title = "Bonus") {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

export default function BonusRunScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin" || user?.role === "sub_admin";

  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState<string>("");
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  useEffect(() => {
    if (globalCid) setCompanyId(globalCid);
  }, [globalCid]);
  const [groups, setGroups] = useState<GroupOption[]>([]);
  const [groupId, setGroupId] = useState<string>("");
  const fys = useMemo(() => fyOptions(), []);
  const [fyStart, setFyStart] = useState<number>(fys[1]?.start ?? new Date().getFullYear() - 1);

  const [policy, setPolicy] = useState<BonusPolicy | null>(null);
  const [savingPolicy, setSavingPolicy] = useState(false);

  const [preview, setPreview] = useState<BonusResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [savingRun, setSavingRun] = useState(false);

  const [pastRuns, setPastRuns] = useState<BonusRunListItem[]>([]);

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

  // Load groups + policy + past runs when company changes
  useEffect(() => {
    if (!companyId) return;
    (async () => {
      try {
        const g = await api<{ items: GroupOption[] }>(
          `/admin/masters?type=group&company_id=${encodeURIComponent(companyId)}`,
        );
        setGroups(g.items || []);
        setGroupId("");
      } catch {
        setGroups([]);
      }
      try {
        const p = await api<{ policy: BonusPolicy }>(
          `/admin/companies/${companyId}/bonus-policy`,
        );
        setPolicy(p.policy);
      } catch {
        setPolicy(null);
      }
      try {
        const runs = await api<{ items: BonusRunListItem[] }>(
          `/admin/bonus-runs?company_id=${encodeURIComponent(companyId)}`,
        );
        setPastRuns(runs.items || []);
      } catch {
        setPastRuns([]);
      }
      setPreview(null);
    })();
  }, [companyId]);

  const setPolicyNum = (k: keyof BonusPolicy, v: string) => {
    const cleaned = v.trim();
    const n = Number(cleaned);
    setPolicy((p) => ({
      ...(p || ({} as BonusPolicy)),
      [k]: Number.isFinite(n) ? n : (p as any)?.[k],
    }));
  };

  const savePolicy = async () => {
    if (!companyId || !policy) return;
    setSavingPolicy(true);
    try {
      const r = await api<{ policy: BonusPolicy }>(
        `/admin/companies/${companyId}/bonus-policy`,
        {
          method: "PUT",
          body: {
            rate_percent: policy.rate_percent,
            wage_ceiling: policy.wage_ceiling,
            eligibility_cap: policy.eligibility_cap,
            basic_percent_of_gross: policy.basic_percent_of_gross,
            min_months_worked: policy.min_months_worked,
          },
        },
      );
      setPolicy(r.policy);
      showMsg("Bonus rules saved.");
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally {
      setSavingPolicy(false);
    }
  };

  const runPreview = async () => {
    if (!companyId) return showMsg("Pick a company");
    setPreviewing(true);
    try {
      const r = await api<BonusResult>("/admin/bonus-runs/preview", {
        method: "POST",
        body: {
          company_id: companyId,
          fy_start_year: fyStart,
          group_id: groupId || null,
        },
      });
      setPreview(r);
    } catch (e: any) {
      showMsg(e?.message || "Preview failed");
    } finally {
      setPreviewing(false);
    }
  };

  const saveRun = async () => {
    if (!preview) return;
    setSavingRun(true);
    try {
      const r = await api<BonusResult>("/admin/bonus-runs", {
        method: "POST",
        body: {
          company_id: companyId,
          fy_start_year: fyStart,
          group_id: groupId || null,
        },
      });
      setPreview(r);
      const runs = await api<{ items: BonusRunListItem[] }>(
        `/admin/bonus-runs?company_id=${encodeURIComponent(companyId)}`,
      );
      setPastRuns(runs.items || []);
      showMsg("Bonus run saved.");
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally {
      setSavingRun(false);
    }
  };

  const downloadReport = useCallback(async (runId: string) => {
    try {
      const res = await apiBinary(`/admin/bonus-runs/${runId}/report.xlsx`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = `BonusReport_${runId}.xlsx`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      showMsg(e?.message || "Download failed");
    }
  }, []);

  if (!isSuper) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Only Super/Sub-admins can process Bonus.</Text>
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
            <Text style={styles.h1}>Bonus Calculation — Financial Year</Text>
            <Text style={styles.hsub}>
              Payment of Bonus Act, 1965 · rules configurable per firm · group-wise supported
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.card}>
          <View style={styles.gridRow}>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Company (Firm)</Text>
              {Platform.OS === "web" ? (
                <select
                  data-testid="bn-company"
                  value={companyId}
                  onChange={(e) => setCompanyId((e.target as HTMLSelectElement).value)}
                  style={styles.selectStyle as any}
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
            <View style={styles.gridCol}>
              <Text style={styles.label}>Financial Year</Text>
              {Platform.OS === "web" ? (
                <select
                  data-testid="bn-fy"
                  value={String(fyStart)}
                  onChange={(e) => setFyStart(Number((e.target as HTMLSelectElement).value))}
                  style={styles.selectStyle as any}
                >
                  {fys.map((f) => (
                    <option key={f.start} value={f.start}>
                      {f.label}
                    </option>
                  ))}
                </select>
              ) : (
                <Text style={styles.smallHint}>Web only.</Text>
              )}
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Employee Group (optional)</Text>
              {Platform.OS === "web" ? (
                <select
                  data-testid="bn-group"
                  value={groupId}
                  onChange={(e) => setGroupId((e.target as HTMLSelectElement).value)}
                  style={styles.selectStyle as any}
                >
                  <option value="">All groups</option>
                  {groups.map((g) => (
                    <option key={g.master_id} value={g.master_id}>
                      {g.name}
                    </option>
                  ))}
                </select>
              ) : (
                <Text style={styles.smallHint}>Web only.</Text>
              )}
            </View>
          </View>
        </View>

        {/* Rules editor */}
        {policy ? (
          <View style={styles.card}>
            <Text style={styles.stepTitle}>Bonus Rules (editable per firm)</Text>
            <Text style={styles.smallHint}>
              Statutory range: 8.33 % – 20 %. Wage ceiling default ₹7,000. Eligibility cap ₹21,000.
            </Text>
            <View style={styles.gridRow}>
              {(
                [
                  ["rate_percent", "Rate %", "8.33 – 20"],
                  ["wage_ceiling", "Wage Ceiling (₹)", "e.g. 7000"],
                  ["eligibility_cap", "Eligibility Cap (₹)", "e.g. 21000"],
                  ["basic_percent_of_gross", "Basic % of Gross (fallback)", "e.g. 50"],
                  ["min_months_worked", "Min Months Worked", "e.g. 1"],
                ] as [keyof BonusPolicy, string, string][]
              ).map(([k, lbl, hint]) => (
                <View key={k as string} style={styles.gridCol}>
                  <Text style={styles.label}>{lbl}</Text>
                  <TextInput
                    testID={`bn-${k as string}`}
                    value={String((policy as any)[k] ?? "")}
                    onChangeText={(v) => setPolicyNum(k, v)}
                    placeholder={hint}
                    placeholderTextColor={colors.onSurfaceTertiary}
                    keyboardType="decimal-pad"
                    style={styles.input}
                  />
                </View>
              ))}
            </View>
            <Pressable
              onPress={savePolicy}
              disabled={savingPolicy}
              style={[styles.secondaryBtn, savingPolicy && { opacity: 0.5 }]}
              testID="bn-save-rules"
            >
              {savingPolicy ? (
                <ActivityIndicator color={colors.brandPrimary} />
              ) : (
                <>
                  <Ionicons name="save-outline" size={14} color={colors.brandPrimary} />
                  <Text style={styles.secondaryBtnTxt}>Save rules for this firm</Text>
                </>
              )}
            </Pressable>
          </View>
        ) : null}

        <Pressable
          onPress={runPreview}
          disabled={previewing || !companyId}
          style={[styles.primaryBtn, (previewing || !companyId) && { opacity: 0.5 }]}
          testID="bn-preview"
        >
          {previewing ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <Ionicons name="calculator-outline" size={16} color="#fff" />
              <Text style={styles.primaryBtnTxt}>Preview bonus</Text>
            </>
          )}
        </Pressable>

        {preview ? (
          <View style={styles.card}>
            <Text style={styles.stepTitle}>
              {preview.fy_label} — {preview.company_name}
              {preview.group_name ? ` — ${preview.group_name}` : ""}
            </Text>
            <View style={styles.summaryRow}>
              <View style={styles.summaryBox}>
                <Text style={styles.summaryLbl}>Employees</Text>
                <Text style={styles.summaryVal}>{preview.total_employees}</Text>
              </View>
              <View style={styles.summaryBox}>
                <Text style={styles.summaryLbl}>Eligible</Text>
                <Text style={styles.summaryVal}>{preview.eligible_count}</Text>
              </View>
              <View style={styles.summaryBox}>
                <Text style={styles.summaryLbl}>Total Bonus</Text>
                <Text style={styles.summaryVal}>{inr(preview.total_bonus)}</Text>
              </View>
            </View>

            {/* Table */}
            <ScrollView horizontal style={{ marginTop: 8 }}>
              <View>
                <View style={[styles.tblRow, styles.tblHead]}>
                  <Text style={[styles.tblCell, styles.tblCellHead, { width: 90 }]}>Code</Text>
                  <Text style={[styles.tblCell, styles.tblCellHead, { width: 180 }]}>Name</Text>
                  <Text style={[styles.tblCell, styles.tblCellHead, { width: 90, textAlign: "right" }]}>Basic</Text>
                  <Text style={[styles.tblCell, styles.tblCellHead, { width: 60, textAlign: "right" }]}>Mo.</Text>
                  <Text style={[styles.tblCell, styles.tblCellHead, { width: 70, textAlign: "center" }]}>Elig</Text>
                  <Text style={[styles.tblCell, styles.tblCellHead, { width: 100, textAlign: "right" }]}>Bonus</Text>
                </View>
                {preview.rows.map((r) => (
                  <View key={r.user_id} style={styles.tblRow}>
                    <Text style={[styles.tblCell, { width: 90 }]}>{r.employee_code || "—"}</Text>
                    <Text style={[styles.tblCell, { width: 180 }]} numberOfLines={1}>
                      {r.name}
                    </Text>
                    <Text style={[styles.tblCell, { width: 90, textAlign: "right" }]}>{inr(r.basic_monthly)}</Text>
                    <Text style={[styles.tblCell, { width: 60, textAlign: "right" }]}>{r.months_worked}</Text>
                    <Text style={[styles.tblCell, { width: 70, textAlign: "center" }]}>
                      {r.eligible ? "Yes" : "No"}
                    </Text>
                    <Text
                      style={[
                        styles.tblCell,
                        { width: 100, textAlign: "right", fontWeight: "700" },
                      ]}
                    >
                      {inr(r.bonus_amount)}
                    </Text>
                  </View>
                ))}
              </View>
            </ScrollView>

            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <Pressable
                onPress={saveRun}
                disabled={savingRun}
                style={[styles.primaryBtn, { flex: 1 }, savingRun && { opacity: 0.5 }]}
                testID="bn-save-run"
              >
                {savingRun ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons name="save-outline" size={16} color="#fff" />
                    <Text style={styles.primaryBtnTxt}>Save run</Text>
                  </>
                )}
              </Pressable>
              {preview.run_id ? (
                <Pressable
                  onPress={() => downloadReport(preview.run_id!)}
                  style={[styles.secondaryBtn, { flex: 1 }]}
                  testID="bn-download"
                >
                  <Ionicons name="download-outline" size={14} color={colors.brandPrimary} />
                  <Text style={styles.secondaryBtnTxt}>Download .xlsx</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        ) : null}

        {pastRuns.length > 0 ? (
          <View style={styles.card}>
            <Text style={styles.stepTitle}>Past bonus runs</Text>
            {pastRuns.map((r) => (
              <View key={r.run_id!} style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowName}>
                    {r.fy_label}
                    {r.group_name ? ` — ${r.group_name}` : ""}
                  </Text>
                  <Text style={styles.smallHint}>
                    {r.eligible_count}/{r.total_employees} eligible · {inr(r.total_bonus)}
                  </Text>
                </View>
                <Pressable
                  onPress={() => downloadReport(r.run_id!)}
                  style={styles.linkBtn}
                  testID={`bn-past-dl-${r.run_id}`}
                >
                  <Ionicons name="download-outline" size={14} color={colors.brandPrimary} />
                  <Text style={styles.linkBtnTxt}>Report</Text>
                </Pressable>
              </View>
            ))}
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
  scroll: { padding: spacing.lg, maxWidth: 1080, alignSelf: "center", width: "100%" },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: { marginTop: 8, color: colors.onSurfaceSecondary, textAlign: "center" },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  label: {
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    fontWeight: "800",
    marginBottom: 4,
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
  selectStyle: {
    padding: 10,
    borderRadius: 8,
    borderColor: colors.borderStrong,
    borderWidth: 1,
    fontSize: 14,
    width: "100%",
  },
  stepTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800", marginBottom: 8 },
  smallHint: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 2, marginBottom: 6 },
  gridRow: { flexDirection: "row", gap: 12, flexWrap: "wrap" },
  gridCol: { flex: 1, minWidth: 200, marginBottom: 8 },
  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    marginTop: 4,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800" },
  secondaryBtn: {
    borderRadius: radius.md,
    paddingVertical: 12,
    marginTop: 8,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  secondaryBtnTxt: { color: colors.brandPrimary, fontWeight: "800" },
  summaryRow: { flexDirection: "row", gap: 8, marginTop: 4 },
  summaryBox: {
    flex: 1,
    backgroundColor: colors.brandTertiary,
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
  },
  summaryLbl: { fontSize: 10, color: colors.brandPrimary, fontWeight: "800", textTransform: "uppercase" },
  summaryVal: { fontSize: 18, color: colors.onSurface, fontWeight: "800", marginTop: 2 },
  tblRow: {
    flexDirection: "row",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  tblHead: { backgroundColor: colors.background },
  tblCell: {
    paddingHorizontal: 8,
    paddingVertical: 8,
    fontSize: 12,
    color: colors.onSurface,
  },
  tblCellHead: { fontWeight: "800", color: colors.onSurfaceSecondary, fontSize: 11 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  rowName: { color: colors.onSurface, fontSize: 14, fontWeight: "700" },
  linkBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    backgroundColor: colors.brandTertiary,
  },
  linkBtnTxt: { color: colors.brandPrimary, fontSize: 12, fontWeight: "700" },
});
