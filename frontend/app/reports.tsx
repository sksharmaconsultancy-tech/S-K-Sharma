/**
 * Reports Hub — Iter 60.
 *
 * Centralized read-only reporting for Super Admins and Sub-Admins. Every
 * report supports the same three filters:
 *   • Firm (Company)
 *   • Month (YYYY-MM)  — optional
 *   • Financial Year (Apr → Mar) — optional; when set with no month, we
 *     fall back to the FY-window query on the backend
 *
 * Three tabs:
 *   1. Salary   — /admin/salary-runs
 *   2. Compliance — /admin/compliance-salary-runs
 *   3. Bonus     — /admin/bonus-runs  (FY-native)
 *
 * Each row exposes the standard download buttons (CSV / PDF / XLSX / ECR)
 * so the operator never has to leave the page.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";
import { useFocusEffect } from "@react-navigation/native";

import { useOnRefresh } from "@/src/context/RefreshBusContext";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import MultiCompanyPicker from "@/src/components/MultiCompanyPicker";
import MonthPicker from "@/src/components/MonthPicker";
import { colors, radius, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };
type Tab = "salary" | "compliance" | "bonus";

type SalaryRun = {
  run_id: string;
  month: string;
  company_id?: string;
  company_name?: string;
  generated_at?: string;
  total_gross?: number;
  total_net?: number;
  row_count?: number;
  finalized?: boolean;
};

type ComplianceRun = SalaryRun & {
  total_pf?: number;
  total_esic?: number;
  total_tds?: number;
};

type BonusRun = {
  run_id: string;
  company_id: string;
  company_name?: string;
  fy_start_year: number;
  fy_label: string;
  group_name?: string | null;
  total_employees: number;
  eligible_count: number;
  total_bonus: number;
  created_at?: string;
};

function inr(n?: number): string {
  if (n === undefined || n === null || !Number.isFinite(n)) return "—";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

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

function showMsg(msg: string, title = "Reports") {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

async function downloadBinary(path: string, filename: string) {
  try {
    const res = await apiBinary(path);
    if (Platform.OS === "web" && res.webBlobUrl) {
      const a = document.createElement("a");
      a.href = res.webBlobUrl;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
    }
  } catch (e: any) {
    showMsg(e?.message || "Download failed");
  }
}

const TABS: { key: Tab; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: "salary", label: "Salary reports", icon: "cash-outline" },
  { key: "compliance", label: "Compliance reports", icon: "shield-checkmark-outline" },
  { key: "bonus", label: "Bonus reports", icon: "gift-outline" },
];

export default function ReportsHubScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ tab?: string }>();
  const { user } = useAuth();
  const isAdminish = user?.role === "super_admin" || user?.role === "sub_admin";

  const [companies, setCompanies] = useState<Company[]>([]);
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  const [companyId, setCompanyId] = useState<string>(globalCid || ""); // "" = all
  // Sync local filter whenever the global picker changes.
  useEffect(() => {
    setCompanyId(globalCid || "");
  }, [globalCid]);

  // Iter 63: cross-firm mode. When ON, we ignore the single companyId
  // filter and fetch runs for every firm in `crossFirmSet` in parallel.
  const [crossFirmMode, setCrossFirmMode] = useState(false);
  const [crossFirmSet, setCrossFirmSet] = useState<Set<string>>(new Set());
  const [bulkDownloading, setBulkDownloading] = useState(false);

  const [month, setMonth] = useState<string>(""); // ""
  const fys = useMemo(() => fyOptions(), []);
  const [fyStart, setFyStart] = useState<string>(""); // "" = any FY

  // Iter 86 — Read tab from URL so sidebar links like
  // "/reports?tab=salary", "/reports?tab=compliance", "/reports?tab=bonus"
  // open the correct tab directly instead of always defaulting to salary.
  const initialTab: Tab = (() => {
    const t = (params.tab || "").toString().toLowerCase();
    if (t === "compliance" || t === "bonus") return t as Tab;
    return "salary";
  })();
  const [tab, setTab] = useState<Tab>(initialTab);
  // Iter 98 — report download sorting + finalized-only filter.
  const [sortBy, setSortBy] = useState<string>("");
  const [finalizedOnly, setFinalizedOnly] = useState(false);
  const sortQ = sortBy ? `?sort_by=${sortBy}` : "";

  // If the query param changes (user clicks a different sidebar link
  // while already on /reports), reflect it in local state.
  useEffect(() => {
    const t = (params.tab || "").toString().toLowerCase();
    if (t === "salary" || t === "compliance" || t === "bonus") {
      setTab(t as Tab);
    }
  }, [params.tab]);
  const [salaryRuns, setSalaryRuns] = useState<SalaryRun[]>([]);
  const [complianceRuns, setComplianceRuns] = useState<ComplianceRun[]>([]);
  // Iter 98 — finalized-only view filter.
  const visSalaryRuns = useMemo(
    () => (finalizedOnly ? salaryRuns.filter((r) => r.finalized) : salaryRuns),
    [salaryRuns, finalizedOnly],
  );
  const visComplianceRuns = useMemo(
    () => (finalizedOnly ? complianceRuns.filter((r) => r.finalized) : complianceRuns),
    [complianceRuns, finalizedOnly],
  );
  const [bonusRuns, setBonusRuns] = useState<BonusRun[]>([]);
  const [loading, setLoading] = useState(false);

  const companyName = useCallback(
    (cid?: string) => companies.find((c) => c.company_id === cid)?.name || "—",
    [companies],
  );

  useEffect(() => {
    if (!isAdminish) return;
    (async () => {
      try {
        const r = await api<{ companies: Company[] }>("/companies");
        setCompanies(r.companies || []);
      } catch (e: any) {
        showMsg(e?.message || "Could not load companies");
      }
    })();
  }, [isAdminish]);

  const load = useCallback(async () => {
    if (!isAdminish) return;
    setLoading(true);
    try {
      const qs: string[] = [];
      // Cross-firm mode wins over single-firm dropdown.
      const cidList = crossFirmMode ? Array.from(crossFirmSet) : [];
      if (crossFirmMode) {
        for (const c of cidList) qs.push(`company_ids=${encodeURIComponent(c)}`);
      } else if (companyId) {
        qs.push(`company_id=${encodeURIComponent(companyId)}`);
      }
      if (month) qs.push(`month=${encodeURIComponent(month)}`);
      if (fyStart) qs.push(`fy_start_year=${fyStart}`);
      const q = qs.length ? `?${qs.join("&")}` : "";

      // Cross-firm with zero selection = nothing to fetch.
      if (crossFirmMode && cidList.length === 0) {
        setSalaryRuns([]);
        setComplianceRuns([]);
        setBonusRuns([]);
        return;
      }

      if (tab === "salary") {
        const r = await api<{ runs: SalaryRun[] }>(`/admin/salary-runs${q}`);
        setSalaryRuns(r.runs || []);
      } else if (tab === "compliance") {
        const r = await api<{ runs: ComplianceRun[] }>(`/admin/compliance-salary-runs${q}`);
        setComplianceRuns(r.runs || []);
      } else {
        const bqs: string[] = [];
        if (crossFirmMode) {
          for (const c of cidList) bqs.push(`company_ids=${encodeURIComponent(c)}`);
        } else if (companyId) {
          bqs.push(`company_id=${encodeURIComponent(companyId)}`);
        }
        if (fyStart) bqs.push(`fy_start_year=${fyStart}`);
        const bq = bqs.length ? `?${bqs.join("&")}` : "";
        const r = await api<{ items: BonusRun[] }>(`/admin/bonus-runs${bq}`);
        setBonusRuns(r.items || []);
      }
    } catch (e: any) {
      showMsg(e?.message || "Could not load reports");
    } finally {
      setLoading(false);
    }
  }, [companyId, month, fyStart, tab, isAdminish, crossFirmMode, crossFirmSet]);

  useEffect(() => {
    void load();
  }, [load]);
  // Iter 72 — Refresh Reports Hub on tab focus + top-bar Refresh.
  useFocusEffect(useCallback(() => { void load(); }, [load]));
  useOnRefresh(load);

  if (!isAdminish) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Only Super/Sub-admins can access reports.</Text>
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
            <Text style={styles.h1}>Reports Hub</Text>
            <Text style={styles.hsub}>
              Salary · Compliance · Bonus — firm-wise · month-wise · financial year
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Annual Report — one-click end-of-FY workbook per firm */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Annual Report (FY)</Text>
          <Text style={styles.cardHint}>
            One workbook per firm covering all 12 months of the selected FY —
            monthly summary, per-employee payroll, attendance and PF/ESIC.
          </Text>
          <View style={[styles.gridRow, { marginTop: 6 }]}>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Firm</Text>
              {Platform.OS === "web" ? (
                <select
                  value={companyId}
                  onChange={(e) => setCompanyId((e.target as HTMLSelectElement).value)}
                  style={styles.selectStyle as any}
                >
                  <option value="">— pick firm —</option>
                  {companies.map((c) => (
                    <option key={c.company_id} value={c.company_id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              ) : null}
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Financial Year</Text>
              {Platform.OS === "web" ? (
                <select
                  value={fyStart}
                  onChange={(e) => setFyStart((e.target as HTMLSelectElement).value)}
                  style={styles.selectStyle as any}
                >
                  <option value="">— pick FY —</option>
                  {fys.map((f) => (
                    <option key={f.start} value={String(f.start)}>
                      {f.label}
                    </option>
                  ))}
                </select>
              ) : null}
            </View>
            <View style={styles.gridCol}>
              <Pressable
                onPress={async () => {
                  if (!companyId) return showMsg("Select a firm first.");
                  if (!fyStart) return showMsg("Select a financial year.");
                  const fy = `${fyStart}-${String(Number(fyStart) + 1).slice(-2)}`;
                  const cName = (companyName(companyId) || "firm").replace(/[^A-Za-z0-9]+/g, "_");
                  await downloadBinary(
                    `/admin/reports/annual.xlsx?fy=${encodeURIComponent(fy)}&company_id=${encodeURIComponent(companyId)}`,
                    `AnnualReport_${cName}_FY${fy}.xlsx`,
                  );
                }}
                style={[styles.bulkBtn, { alignSelf: "flex-end" }]}
                testID="rep-annual-dl"
              >
                <Ionicons name="calendar-outline" size={14} color="#fff" />
                <Text style={styles.bulkBtnTxt}>Download Annual XLSX</Text>
              </Pressable>
            </View>
          </View>
        </View>

        {/* Filters */}
        <View style={styles.card}>
          {/* Cross-firm toggle */}
          <View style={styles.crossToggleRow}>
            <Pressable
              onPress={() => {
                const next = !crossFirmMode;
                setCrossFirmMode(next);
                if (next && crossFirmSet.size === 0 && globalCid) {
                  setCrossFirmSet(new Set([globalCid]));
                }
              }}
              style={styles.crossToggle}
              testID="rep-cross-firm-toggle"
            >
              <Ionicons
                name={crossFirmMode ? "checkbox" : "square-outline"}
                size={16}
                color={crossFirmMode ? colors.brandPrimary : colors.onSurfaceSecondary}
              />
              <Text style={styles.crossToggleTxt}>
                Multi-firm mode (cross-firm export)
              </Text>
            </Pressable>
            {crossFirmMode && crossFirmSet.size > 1 && (tab === "salary" || tab === "compliance") ? (
              <Pressable
                onPress={async () => {
                  const runs: any[] = tab === "salary" ? salaryRuns : complianceRuns;
                  if (runs.length === 0) return;
                  setBulkDownloading(true);
                  try {
                    for (const r of runs) {
                      const cName = (r.company_name || companyName(r.company_id) || "").replace(/[^A-Za-z0-9]+/g, "_");
                      const base =
                        tab === "salary"
                          ? `/admin/salary-runs/${r.run_id}/export.xlsx`
                          : `/admin/compliance-salary-runs/${r.run_id}/export.xlsx`;
                      const name =
                        tab === "salary"
                          ? `SalaryRun_${cName}_${r.month}.xlsx`
                          : `Compliance_${cName}_${r.month}.xlsx`;
                      await downloadBinary(base, name);
                      // Small stagger so browsers don't block multi-download.
                      await new Promise((res) => setTimeout(res, 250));
                    }
                  } finally {
                    setBulkDownloading(false);
                  }
                }}
                style={styles.bulkBtn}
                disabled={bulkDownloading}
                testID="rep-bulk-dl"
              >
                {bulkDownloading ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Ionicons name="cloud-download-outline" size={14} color="#fff" />
                )}
                <Text style={styles.bulkBtnTxt}>
                  {bulkDownloading ? "Downloading…" : `Download all Excel (${(tab === "salary" ? salaryRuns : complianceRuns).length})`}
                </Text>
              </Pressable>
            ) : null}
          </View>

          <View style={styles.gridRow}>
            <View style={styles.gridCol}>
              <Text style={styles.label}>
                {crossFirmMode ? "Firms (multi-select)" : "Company (Firm)"}
              </Text>
              {crossFirmMode ? (
                <MultiCompanyPicker
                  value={crossFirmSet}
                  onChange={setCrossFirmSet}
                  testID="rep-multi-picker"
                />
              ) : Platform.OS === "web" ? (
                <select
                  value={companyId}
                  onChange={(e) => setCompanyId((e.target as HTMLSelectElement).value)}
                  style={styles.selectStyle as any}
                >
                  <option value="">All firms</option>
                  {companies.map((c) => (
                    <option key={c.company_id} value={c.company_id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              ) : null}
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Month</Text>
              <MonthPicker
                value={month}
                onChange={setMonth}
                allowEmpty
                emptyLabel="All months"
                testID="rep-month-picker"
              />
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Financial Year</Text>
              {Platform.OS === "web" ? (
                <select
                  value={fyStart}
                  onChange={(e) => setFyStart((e.target as HTMLSelectElement).value)}
                  style={styles.selectStyle as any}
                >
                  <option value="">Any FY</option>
                  {fys.map((f) => (
                    <option key={f.start} value={String(f.start)}>
                      {f.label}
                    </option>
                  ))}
                </select>
              ) : null}
            </View>
          </View>
        </View>

        {/* Tabs */}
        <View style={styles.tabsRow}>
          {TABS.map((t) => (
            <Pressable
              key={t.key}
              onPress={() => setTab(t.key)}
              style={[styles.tab, tab === t.key && styles.tabActive]}
              testID={`rep-tab-${t.key}`}
            >
              <Ionicons
                name={t.icon}
                size={14}
                color={tab === t.key ? "#fff" : colors.onSurfaceSecondary}
              />
              <Text
                style={[
                  styles.tabTxt,
                  { color: tab === t.key ? "#fff" : colors.onSurfaceSecondary },
                ]}
              >
                {t.label}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Iter 98 — sorting + finalized-only controls */}
        {(tab === "salary" || tab === "compliance") ? (
          <View style={styles.sortRow}>
            <Text style={styles.sortLbl}>Sort report:</Text>
            {[["", "Default"], ["name", "Name"], ["code", "Emp Code"], ["net", "Net ↓"], ["gross", "Gross ↓"]].map(([val, lab]) => (
              <Pressable
                key={val || "default"}
                onPress={() => setSortBy(val)}
                style={[styles.sortChip, sortBy === val && styles.sortChipActive]}
                testID={`rep-sort-${val || "default"}`}
              >
                <Text style={[styles.sortChipTxt, sortBy === val && styles.sortChipTxtActive]}>{lab}</Text>
              </Pressable>
            ))}
            <Pressable
              onPress={() => setFinalizedOnly((v) => !v)}
              style={[styles.sortChip, finalizedOnly && styles.sortChipActive]}
              testID="rep-finalized-only"
            >
              <Ionicons name={finalizedOnly ? "lock-closed" : "lock-open-outline"} size={12} color={finalizedOnly ? "#fff" : colors.onSurfaceSecondary} />
              <Text style={[styles.sortChipTxt, finalizedOnly && styles.sortChipTxtActive]}>Finalized only</Text>
            </Pressable>
          </View>
        ) : null}

        {/* Results */}
        {loading ? (
          <ActivityIndicator style={{ marginTop: 20 }} />
        ) : tab === "salary" ? (
          <View style={styles.card}>
            <Text style={styles.stepTitle}>{visSalaryRuns.length} salary run(s)</Text>
            {visSalaryRuns.length === 0 ? (
              <Text style={styles.smallHint}>No runs match the selected filters.</Text>
            ) : (
              visSalaryRuns.map((r) => (
                <View key={r.run_id} style={styles.row}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowName}>
                      {r.month} · {r.company_name || companyName(r.company_id)}
                    </Text>
                    <Text style={styles.smallHint}>
                      {r.row_count ?? "—"} employees · Gross {inr(r.total_gross)} · Net {inr(r.total_net)}
                    </Text>
                  </View>
                  <Pressable
                    onPress={() =>
                      downloadBinary(
                        `/admin/salary-runs/${r.run_id}/export.xlsx${sortQ}`,
                        `SalaryRun_${r.month}_${r.run_id.slice(-6)}.xlsx`,
                      )
                    }
                    style={styles.linkBtn}
                    testID={`rep-sal-xlsx-${r.run_id}`}
                  >
                    <Ionicons name="download-outline" size={14} color={colors.brandPrimary} />
                    <Text style={styles.linkBtnTxt}>Excel</Text>
                  </Pressable>
                  <Pressable
                    onPress={() =>
                      downloadBinary(
                        `/admin/salary-runs/${r.run_id}/register.pdf`,
                        `SalaryRegister_${r.month}.pdf`,
                      )
                    }
                    style={styles.linkBtn}
                    testID={`rep-sal-pdf-${r.run_id}`}
                  >
                    <Ionicons name="document-outline" size={14} color={colors.brandPrimary} />
                    <Text style={styles.linkBtnTxt}>PDF</Text>
                  </Pressable>
                  <Pressable
                    onPress={() =>
                      downloadBinary(
                        `/admin/salary-runs/${r.run_id}/export.csv${sortQ}`,
                        `SalaryRun_${r.month}_${r.run_id.slice(-6)}.csv`,
                      )
                    }
                    style={styles.linkBtnGhost}
                    testID={`rep-sal-csv-${r.run_id}`}
                  >
                    <Text style={styles.linkBtnGhostTxt}>CSV</Text>
                  </Pressable>
                </View>
              ))
            )}
          </View>
        ) : tab === "compliance" ? (
          <View style={styles.card}>
            <Text style={styles.stepTitle}>{visComplianceRuns.length} compliance run(s)</Text>
            {visComplianceRuns.length === 0 ? (
              <Text style={styles.smallHint}>No runs match the selected filters.</Text>
            ) : (
              visComplianceRuns.map((r) => (
                <View key={r.run_id} style={styles.row}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowName}>
                      {r.month} · {r.company_name || companyName(r.company_id)}
                    </Text>
                    <Text style={styles.smallHint}>
                      PF {inr(r.total_pf)} · ESIC {inr(r.total_esic)} · TDS {inr(r.total_tds)}
                    </Text>
                  </View>
                  <Pressable
                    onPress={() =>
                      downloadBinary(
                        `/admin/compliance-salary-runs/${r.run_id}/export.xlsx${sortQ}`,
                        `Compliance_${r.month}.xlsx`,
                      )
                    }
                    style={styles.linkBtn}
                    testID={`rep-comp-xlsx-${r.run_id}`}
                  >
                    <Ionicons name="download-outline" size={14} color={colors.brandPrimary} />
                    <Text style={styles.linkBtnTxt}>Excel</Text>
                  </Pressable>
                  <Pressable
                    onPress={() =>
                      downloadBinary(
                        `/admin/compliance-salary-runs/${r.run_id}/register.pdf`,
                        `ComplianceRegister_${r.month}.pdf`,
                      )
                    }
                    style={styles.linkBtn}
                  >
                    <Ionicons name="document-outline" size={14} color={colors.brandPrimary} />
                    <Text style={styles.linkBtnTxt}>PDF</Text>
                  </Pressable>
                  <Pressable
                    onPress={() =>
                      downloadBinary(
                        `/admin/compliance-salary-runs/${r.run_id}/ecr.txt`,
                        `ECR_${r.month}.txt`,
                      )
                    }
                    style={styles.linkBtn}
                  >
                    <Ionicons name="document-text-outline" size={14} color={colors.brandPrimary} />
                    <Text style={styles.linkBtnTxt}>ECR</Text>
                  </Pressable>
                  <Pressable
                    onPress={() =>
                      downloadBinary(
                        `/admin/compliance-salary-runs/${r.run_id}/export.csv${sortQ}`,
                        `Compliance_${r.month}.csv`,
                      )
                    }
                    style={styles.linkBtnGhost}
                  >
                    <Text style={styles.linkBtnGhostTxt}>CSV</Text>
                  </Pressable>
                </View>
              ))
            )}
          </View>
        ) : (
          <View style={styles.card}>
            <Text style={styles.stepTitle}>{bonusRuns.length} bonus run(s)</Text>
            {bonusRuns.length === 0 ? (
              <Text style={styles.smallHint}>No runs match the selected filters.</Text>
            ) : (
              bonusRuns.map((r) => (
                <View key={r.run_id} style={styles.row}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowName}>
                      FY {r.fy_label} · {r.company_name || companyName(r.company_id)}
                      {r.group_name ? ` · ${r.group_name}` : ""}
                    </Text>
                    <Text style={styles.smallHint}>
                      {r.eligible_count}/{r.total_employees} eligible · {inr(r.total_bonus)} total
                    </Text>
                  </View>
                  <Pressable
                    onPress={() =>
                      downloadBinary(
                        `/admin/bonus-runs/${r.run_id}/report.xlsx`,
                        `BonusReport_FY${r.fy_label}.xlsx`,
                      )
                    }
                    style={styles.linkBtn}
                  >
                    <Ionicons name="download-outline" size={14} color={colors.brandPrimary} />
                    <Text style={styles.linkBtnTxt}>XLSX</Text>
                  </Pressable>
                </View>
              ))
            )}
          </View>
        )}

        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  // Iter 98 — sort/filter chips row
  sortRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6, marginTop: 10 },
  sortLbl: { color: colors.onSurfaceSecondary, fontSize: 12, fontWeight: "700", marginRight: 2 },
  sortChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  sortChipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  sortChipTxt: { color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "700" },
  sortChipTxtActive: { color: "#fff" },
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
  scroll: { padding: spacing.lg, maxWidth: 1200, alignSelf: "center", width: "100%" },
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
  cardTitle: {
    color: colors.onSurface,
    fontSize: 15,
    fontWeight: "800",
    marginBottom: 2,
  },
  cardHint: {
    color: colors.onSurfaceSecondary,
    fontSize: 12,
    marginBottom: 6,
  },
  label: {
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    fontWeight: "800",
    marginBottom: 4,
    textTransform: "uppercase",
  },
  smallHint: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 4 },
  stepTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800", marginBottom: 8 },
  gridRow: { flexDirection: "row", gap: 12, flexWrap: "wrap" },
  gridCol: { flex: 1, minWidth: 200 },
  selectStyle: {
    padding: 10,
    borderRadius: 8,
    borderColor: colors.borderStrong,
    borderWidth: 1,
    fontSize: 14,
    width: "100%",
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
  tabsRow: { flexDirection: "row", gap: 8, marginBottom: 10, flexWrap: "wrap" },
  tab: {
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 999,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.divider,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  tabActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12, fontWeight: "700" },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
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
  linkBtnGhost: {
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 8,
    backgroundColor: "transparent",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.divider,
  },
  linkBtnGhostTxt: { color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "600" },
  crossToggleRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    marginBottom: 10,
    flexWrap: "wrap",
  },
  crossToggle: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 4,
  },
  crossToggleTxt: {
    color: colors.onSurface,
    fontSize: 12,
    fontWeight: "700",
  },
  bulkBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: colors.brandPrimary,
  },
  bulkBtnTxt: { color: "#fff", fontSize: 12, fontWeight: "800" },
});
