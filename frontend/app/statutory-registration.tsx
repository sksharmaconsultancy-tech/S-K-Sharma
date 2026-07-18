/**
 * Statutory Registration — EPF UAN + ESIC IP registration module.
 *
 * SAP Fiori / Workday-style module: KPI cards, status filter chips,
 * registration queue with HR approval workflow, eligible-employee list
 * with bulk registration, duplicate detection & link-existing-number,
 * validation checklist, family particulars (ESIC), Form-1 / Form-11
 * PDF generation and a full per-registration audit timeline.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, Pressable, ActivityIndicator,
  TextInput, Modal, ScrollView, Platform, Alert, Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius } from "@/src/theme";

type Portal = "esic" | "uan";

type Kpis = {
  total_employees: number; registered: number; coverage_pct: number;
  eligible_missing: number; in_progress: number; pending_approval: number;
  action_required: number; failed: number; generated: number; draft: number;
};

type Reg = {
  reg_id: string; portal: Portal; company_id?: string;
  employee_user_id: string; employee_name?: string; employee_code?: string;
  status: string; value?: string | null; last_error?: string | null;
  validation?: { ok: boolean; issues: string[]; warnings: string[]; eligible: boolean; eligibility_note?: string } | null;
  duplicate?: { note?: string; value?: string } | null;
  dispensary?: string; source?: string; updated_at?: string; created_at?: string;
  family_members?: FamilyMember[]; nominee?: Record<string, string>;
  snapshot?: Record<string, any>;
  history?: { at: string; by_name?: string; action: string; note?: string }[];
  rpa_job_id?: string | null;
};

type FamilyMember = { name: string; relation: string; dob?: string; residing?: boolean };

type EligibleEmp = {
  user_id: string; name: string; employee_code?: string;
  company_id?: string; company_name?: string; department?: string;
  designation?: string; aadhaar_ok: boolean; wage: number; eligible: boolean;
  eligibility_note?: string; ready: boolean; issues: string[]; warnings: string[];
  duplicate?: { note?: string; value?: string } | null;
  open_registration?: { reg_id: string; status: string } | null;
};

type Settings = {
  esic_wage_ceiling: number; pf_wage_ceiling: number;
  pf_cover_all: boolean; require_approval: boolean;
};

const STATUS_META: Record<string, { label: string; color: string; icon: keyof typeof Ionicons.glyphMap }> = {
  draft: { label: "Draft", color: "#64748B", icon: "create-outline" },
  pending_approval: { label: "Pending Approval", color: "#D97706", icon: "hourglass-outline" },
  queued: { label: "Queued", color: "#2563EB", icon: "time-outline" },
  submitted: { label: "Submitted", color: "#7C3AED", icon: "cloud-upload-outline" },
  generated: { label: "Generated", color: "#059669", icon: "checkmark-circle-outline" },
  linked_existing: { label: "Linked Existing", color: "#0891B2", icon: "link-outline" },
  action_required: { label: "Action Required", color: "#EA580C", icon: "alert-circle-outline" },
  existing_found: { label: "Existing Found", color: "#CA8A04", icon: "copy-outline" },
  failed: { label: "Failed", color: "#DC2626", icon: "close-circle-outline" },
  rejected: { label: "Rejected", color: "#9F1239", icon: "remove-circle-outline" },
};

const QUEUE_FILTERS = [
  "all", "draft", "pending_approval", "queued", "submitted",
  "generated", "linked_existing", "action_required", "existing_found", "failed",
];

function toast(msg: string) {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert("Statutory Registration", msg);
}

function fmtWhen(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-IN")} ${d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`;
}

function StatusChip({ status }: { status: string }) {
  const m = STATUS_META[status] || { label: status, color: "#64748B", icon: "ellipse-outline" as const };
  return (
    <View style={[s.chip, { backgroundColor: `${m.color}15` }]}>
      <Ionicons name={m.icon} size={12} color={m.color} />
      <Text style={[s.chipTxt, { color: m.color }]}>{m.label}</Text>
    </View>
  );
}

function KpiCard({ label, value, tone, icon, sub }: {
  label: string; value: string | number; tone: string;
  icon: keyof typeof Ionicons.glyphMap; sub?: string;
}) {
  return (
    <View style={s.kpiCard} testID={`kpi-${label.replace(/\W+/g, "-").toLowerCase()}`}>
      <View style={[s.kpiIcon, { backgroundColor: `${tone}18` }]}>
        <Ionicons name={icon} size={16} color={tone} />
      </View>
      <Text style={s.kpiValue}>{value}</Text>
      <Text style={s.kpiLabel} numberOfLines={1}>{label}</Text>
      {sub ? <Text style={[s.kpiSub, { color: tone }]} numberOfLines={1}>{sub}</Text> : null}
    </View>
  );
}

export default function StatutoryRegistration() {
  const params = useLocalSearchParams<{ portal?: string }>();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const role = user?.role as string;

  const [portal, setPortal] = useState<Portal>(
    (params.portal === "uan" ? "uan" : "esic") as Portal);
  useEffect(() => {
    if (params.portal === "uan" || params.portal === "esic") setPortal(params.portal);
  }, [params.portal]);

  const [companyId, setCompanyId] = useState<string | "all">(
    role === "company_admin" ? (user?.company_id || "all") : (selectedCompanyId || "all"),
  );
  const [tab, setTab] = useState<"queue" | "eligible">("queue");
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [regs, setRegs] = useState<Reg[]>([]);
  const [eligible, setEligible] = useState<EligibleEmp[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  // detail modal
  const [detail, setDetail] = useState<Reg | null>(null);
  const [detailJob, setDetailJob] = useState<any>(null);
  const [detailBusy, setDetailBusy] = useState<string | null>(null);
  const [linkVal, setLinkVal] = useState("");
  const [famDraft, setFamDraft] = useState<FamilyMember[]>([]);
  const [dispDraft, setDispDraft] = useState("");

  // settings modal
  const [showSettings, setShowSettings] = useState(false);
  const [setDraft, setSetDraft] = useState<Settings | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);

  const cid = companyId && companyId !== "all" ? companyId : "";
  const label = portal === "esic" ? "ESIC IP" : "PF UAN";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = cid ? `?company_id=${cid}` : "";
      const [d, r, e] = await Promise.all([
        api<any>(`/admin/statutory/${portal}/dashboard${q}`),
        api<any>(`/admin/statutory/${portal}/registrations${q}`),
        api<any>(`/admin/statutory/${portal}/eligible${q}`),
      ]);
      setKpis(d.kpis); setSettings(d.settings);
      setRegs(r.registrations || []);
      setEligible(e.employees || []);
    } catch { setKpis(null); setRegs([]); setEligible([]); }
    finally { setLoading(false); }
  }, [portal, cid]);
  useEffect(() => { load(); setSelected(new Set()); }, [load]);

  const filteredRegs = useMemo(() => {
    let rows = regs;
    if (statusFilter !== "all") rows = rows.filter((r) => r.status === statusFilter);
    const t = search.trim().toLowerCase();
    if (t) {
      rows = rows.filter((r) =>
        (r.employee_name || "").toLowerCase().includes(t) ||
        String(r.employee_code || "").toLowerCase().includes(t) ||
        (r.value || "").includes(t));
    }
    return rows;
  }, [regs, statusFilter, search]);

  const filteredEligible = useMemo(() => {
    const t = search.trim().toLowerCase();
    if (!t) return eligible;
    return eligible.filter((e) =>
      (e.name || "").toLowerCase().includes(t) ||
      String(e.employee_code || "").toLowerCase().includes(t));
  }, [eligible, search]);

  const openDetail = async (regId: string) => {
    try {
      const d = await api<any>(`/admin/statutory/registrations/${regId}`);
      setDetail(d.registration); setDetailJob(d.rpa_job || null);
      setFamDraft(d.registration.family_members || []);
      setDispDraft(d.registration.dispensary || "");
      setLinkVal("");
    } catch (e: any) { toast(e?.message || "Failed to open registration"); }
  };

  const act = async (action: string, body?: any) => {
    if (!detail || detailBusy) return;
    setDetailBusy(action);
    try {
      const r = await api<any>(`/admin/statutory/registrations/${detail.reg_id}/${action}`,
        { method: "POST", body: body || {} });
      toast(r.message || "Done.");
      await openDetail(detail.reg_id);
      await load();
    } catch (e: any) { toast(e?.message || "Action failed"); }
    finally { setDetailBusy(null); }
  };

  const saveDetails = async () => {
    if (!detail || detailBusy) return;
    setDetailBusy("save");
    try {
      await api<any>(`/admin/statutory/registrations/${detail.reg_id}`, {
        method: "PUT",
        body: { family_members: famDraft.filter((f) => f.name.trim()), dispensary: dispDraft },
      });
      toast("Details saved.");
      await openDetail(detail.reg_id);
      await load();
    } catch (e: any) { toast(e?.message || "Save failed"); }
    finally { setDetailBusy(null); }
  };

  const downloadForm = async () => {
    if (!detail) return;
    setDetailBusy("form");
    try {
      const r = await api<any>(`/admin/statutory/registrations/${detail.reg_id}/form`);
      if (Platform.OS === "web") {
        const bin = globalThis.atob(r.pdf_base64);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        const url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
        const a = globalThis.document.createElement("a");
        a.href = url; a.download = r.file_name; a.click();
        URL.revokeObjectURL(url);
      } else toast("Form download is available on the web portal.");
    } catch (e: any) { toast(e?.message || "Form generation failed"); }
    finally { setDetailBusy(null); }
  };

  const registerOne = async (emp: EligibleEmp) => {
    try {
      const r = await api<any>(`/admin/statutory/${portal}/registrations`,
        { method: "POST", body: { employee_user_id: emp.user_id } });
      await load();
      await openDetail(r.registration.reg_id);
    } catch (e: any) { toast(e?.message || "Failed to create registration"); }
  };

  const linkExistingFromEligible = async (emp: EligibleEmp) => {
    const val = Platform.OS === "web"
      ? globalThis.prompt(`Enter the existing ${label} number for ${emp.name}:`, emp.duplicate?.value || "")
      : null;
    if (Platform.OS !== "web") { toast("Use the web portal to link existing numbers."); return; }
    if (!val) return;
    try {
      const r = await api<any>(`/admin/statutory/${portal}/registrations`,
        { method: "POST", body: { employee_user_id: emp.user_id } });
      await api<any>(`/admin/statutory/registrations/${r.registration.reg_id}/link-existing`,
        { method: "POST", body: { value: val } });
      toast(`${label} linked for ${emp.name}.`);
      await load();
    } catch (e: any) { toast(e?.message || "Link failed"); }
  };

  const runBulk = async () => {
    if (selected.size === 0 || bulkBusy) return;
    setBulkBusy(true);
    try {
      const r = await api<any>(`/admin/statutory/${portal}/bulk`, {
        method: "POST", body: { employee_user_ids: Array.from(selected) },
      });
      const lines = (r.results || []).map((x: any) =>
        `${x.name || x.user_id}: ${STATUS_META[x.status]?.label || x.status}${x.note ? ` — ${x.note}` : ""}`);
      toast(`Bulk run: ${r.queued}/${r.total} queued.\n\n${lines.slice(0, 12).join("\n")}`);
      setSelected(new Set());
      await load();
    } catch (e: any) { toast(e?.message || "Bulk registration failed"); }
    finally { setBulkBusy(false); }
  };

  const saveSettings = async () => {
    if (!setDraft || savingSettings) return;
    setSavingSettings(true);
    try {
      const r = await api<any>("/admin/statutory/settings", {
        method: "PUT", body: { ...setDraft, company_id: cid || undefined },
      });
      setSettings(r.settings);
      setShowSettings(false);
      toast("Eligibility rules saved.");
      await load();
    } catch (e: any) { toast(e?.message || "Save failed"); }
    finally { setSavingSettings(false); }
  };

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }
  // RBAC — staff users need the registrations permission for this module.
  const isStaff = !!(user as any)?.is_company_staff;
  const staffPerms: string[] = ((user as any)?.staff_permissions || []) as string[];
  if (isStaff && !staffPerms.some((p) => p.startsWith("registrations:"))) {
    return <Redirect href="/portal-dashboard" />;
  }
  const canWrite = !isStaff || staffPerms.includes("registrations:write");
  const canApprove = !isStaff;

  const showFirmBadge = companyId === "all" && role !== "company_admin";
  const dStatus = detail?.status || "";

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      {/* Header */}
      <View style={s.header}>
        <View style={{ flex: 1 }}>
          <Text style={s.title} testID="statutory-title">
            {portal === "esic" ? "ESIC IP Registration" : "EPF UAN Generation"}
          </Text>
          <Text style={s.subtitle}>
            {portal === "esic"
              ? "Automated Insured Person (Part B) registration on the ESIC portal"
              : "Automated member registration & UAN allotment on the EPFO portal"}
          </Text>
        </View>
        <Pressable style={s.iconBtn} onPress={() => { setSetDraft(settings); setShowSettings(true); }}
          testID="btn-settings">
          <Ionicons name="options-outline" size={18} color={colors.brandPrimary} />
        </Pressable>
        <Pressable style={s.iconBtn} onPress={load} testID="btn-refresh">
          <Ionicons name="refresh-outline" size={18} color={colors.brandPrimary} />
        </Pressable>
      </View>

      {/* Portal switch */}
      <View style={s.segRow}>
        {(["esic", "uan"] as Portal[]).map((p) => (
          <Pressable key={p} onPress={() => setPortal(p)}
            style={[s.segBtn, portal === p && s.segBtnOn]} testID={`seg-${p}`}>
            <Ionicons name={p === "esic" ? "medkit-outline" : "briefcase-outline"} size={14}
              color={portal === p ? "#fff" : colors.brandPrimary} />
            <Text style={[s.segTxt, portal === p && s.segTxtOn]}>
              {p === "esic" ? "ESIC IP" : "EPF UAN"}
            </Text>
          </Pressable>
        ))}
        <View style={{ flex: 1 }} />
        {role !== "company_admin" && (
          <View style={{ minWidth: 220 }}>
            <CompanyPicker value={companyId} onChange={(v: any) => setCompanyId(v || "all")} allowAll />
          </View>
        )}
      </View>

      {loading ? (
        <View style={s.center}><ActivityIndicator color={colors.brandPrimary} size="large" /></View>
      ) : (
        <FlatList
          data={tab === "queue" ? (filteredRegs as any[]) : (filteredEligible as any[])}
          keyExtractor={(item: any) => item.reg_id || item.user_id}
          contentContainerStyle={{ paddingBottom: 48 }}
          ListHeaderComponent={
            <View>
              {/* KPI cards */}
              {kpis && (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.kpiRow}
                  contentContainerStyle={{ gap: 10, paddingHorizontal: 16 }}>
                  <KpiCard label="Registered" value={kpis.registered} tone="#059669"
                    icon="shield-checkmark-outline" sub={`${kpis.coverage_pct}% coverage`} />
                  <KpiCard label="Eligible w/o number" value={kpis.eligible_missing} tone="#D97706"
                    icon="people-outline" sub="payroll flag" />
                  <KpiCard label="In Progress" value={kpis.in_progress} tone="#2563EB" icon="sync-outline" />
                  <KpiCard label="Pending Approval" value={kpis.pending_approval} tone="#D97706"
                    icon="hourglass-outline" />
                  <KpiCard label="Action Required" value={kpis.action_required} tone="#EA580C"
                    icon="alert-circle-outline" />
                  <KpiCard label="Failed" value={kpis.failed} tone="#DC2626" icon="close-circle-outline" />
                </ScrollView>
              )}

              {/* Tabs */}
              <View style={s.tabRow}>
                <Pressable style={[s.tabBtn, tab === "queue" && s.tabBtnOn]}
                  onPress={() => setTab("queue")} testID="tab-queue">
                  <Text style={[s.tabTxt, tab === "queue" && s.tabTxtOn]}>
                    Registration Queue ({regs.length})
                  </Text>
                </Pressable>
                <Pressable style={[s.tabBtn, tab === "eligible" && s.tabBtnOn]}
                  onPress={() => setTab("eligible")} testID="tab-eligible">
                  <Text style={[s.tabTxt, tab === "eligible" && s.tabTxtOn]}>
                    Eligible Employees ({eligible.length})
                  </Text>
                </Pressable>
              </View>

              {/* Search + filters */}
              <View style={s.searchRow}>
                <Ionicons name="search-outline" size={16} color={colors.textSecondary} />
                <TextInput
                  style={s.searchInput} placeholder="Search name / code / number"
                  placeholderTextColor={colors.textSecondary}
                  value={search} onChangeText={setSearch} testID="search-input"
                />
              </View>
              {tab === "queue" && (
                <ScrollView horizontal showsHorizontalScrollIndicator={false}
                  contentContainerStyle={{ gap: 6, paddingHorizontal: 16, paddingBottom: 10 }}>
                  {QUEUE_FILTERS.map((f) => (
                    <Pressable key={f} onPress={() => setStatusFilter(f)}
                      style={[s.filterChip, statusFilter === f && s.filterChipOn]}
                      testID={`filter-${f}`}>
                      <Text style={[s.filterTxt, statusFilter === f && s.filterTxtOn]}>
                        {f === "all" ? "All" : STATUS_META[f]?.label || f}
                      </Text>
                    </Pressable>
                  ))}
                </ScrollView>
              )}
              {tab === "eligible" && canWrite && (
                <View style={s.bulkBar}>
                  <Pressable
                    onPress={() => {
                      const ready = filteredEligible.filter((e) => e.ready && !e.open_registration);
                      setSelected(selected.size ? new Set() : new Set(ready.map((e) => e.user_id)));
                    }}
                    style={s.bulkSelectAll} testID="bulk-select-all">
                    <Ionicons
                      name={selected.size ? "checkbox" : "square-outline"}
                      size={16} color={colors.brandPrimary} />
                    <Text style={s.bulkSelectTxt}>
                      {selected.size ? `Clear (${selected.size})` : "Select all ready"}
                    </Text>
                  </Pressable>
                  <Pressable
                    onPress={runBulk}
                    disabled={selected.size === 0 || bulkBusy}
                    style={[s.bulkBtn, (selected.size === 0 || bulkBusy) && { opacity: 0.5 }]}
                    testID="btn-bulk-register">
                    {bulkBusy ? <ActivityIndicator color="#fff" size="small" /> : (
                      <>
                        <Ionicons name="rocket-outline" size={14} color="#fff" />
                        <Text style={s.bulkBtnTxt}>Bulk Register ({selected.size})</Text>
                      </>
                    )}
                  </Pressable>
                </View>
              )}
            </View>
          }
          ListEmptyComponent={
            <View style={s.center}>
              <Ionicons name="file-tray-outline" size={34} color={colors.textSecondary} />
              <Text style={s.emptyTxt}>
                {tab === "queue" ? "No registrations yet — start from the Eligible Employees tab."
                  : `Every employee already has ${label === "ESIC IP" ? "an" : "a"} ${label} number.`}
              </Text>
            </View>
          }
          renderItem={({ item }: { item: any }) =>
            tab === "queue" ? (
              <Pressable style={s.row} onPress={() => openDetail(item.reg_id)}
                testID={`reg-row-${item.reg_id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={s.rowName}>{item.employee_name || item.employee_user_id}
                    {item.employee_code ? `  ·  #${item.employee_code}` : ""}</Text>
                  <Text style={s.rowSub} numberOfLines={1}>
                    {item.value ? `${label}: ${item.value}` :
                      (item.last_error || item.duplicate?.note ||
                        item.validation?.eligibility_note || "—")}
                  </Text>
                  <Text style={s.rowWhen}>{fmtWhen(item.updated_at)} · {item.source || "module"}</Text>
                </View>
                <StatusChip status={item.status} />
                <Ionicons name="chevron-forward" size={16} color={colors.textSecondary} />
              </Pressable>
            ) : (
              <View style={s.row} testID={`elig-row-${item.user_id}`}>
                {canWrite && (
                  <Pressable
                    onPress={() => {
                      const n = new Set(selected);
                      if (n.has(item.user_id)) n.delete(item.user_id); else n.add(item.user_id);
                      setSelected(n);
                    }}
                    disabled={!item.ready || !!item.open_registration}
                    style={{ opacity: item.ready && !item.open_registration ? 1 : 0.3 }}>
                    <Ionicons
                      name={selected.has(item.user_id) ? "checkbox" : "square-outline"}
                      size={18} color={colors.brandPrimary} />
                  </Pressable>
                )}
                <View style={{ flex: 1 }}>
                  <Text style={s.rowName}>{item.name}
                    {item.employee_code ? `  ·  #${item.employee_code}` : ""}</Text>
                  <Text style={s.rowSub} numberOfLines={1}>
                    {showFirmBadge && item.company_name ? `${item.company_name} · ` : ""}
                    {item.eligibility_note}
                  </Text>
                  {item.issues.length > 0 && (
                    <Text style={[s.rowSub, { color: "#DC2626" }]} numberOfLines={1}>
                      ⚠ {item.issues.join("; ")}
                    </Text>
                  )}
                  {item.duplicate && (
                    <Text style={[s.rowSub, { color: "#CA8A04" }]} numberOfLines={2}>
                      ⚠ {item.duplicate.note}
                    </Text>
                  )}
                </View>
                {item.open_registration ? (
                  <Pressable onPress={() => openDetail(item.open_registration.reg_id)}>
                    <StatusChip status={item.open_registration.status} />
                  </Pressable>
                ) : canWrite ? (
                  <View style={{ flexDirection: "row", gap: 6 }}>
                    <Pressable style={s.miniBtn} onPress={() => registerOne(item)}
                      testID={`btn-register-${item.user_id}`}>
                      <Text style={s.miniBtnTxt}>Register</Text>
                    </Pressable>
                    <Pressable style={[s.miniBtn, s.miniBtnAlt]}
                      onPress={() => linkExistingFromEligible(item)}
                      testID={`btn-link-${item.user_id}`}>
                      <Text style={[s.miniBtnTxt, { color: colors.brandPrimary }]}>Link</Text>
                    </Pressable>
                  </View>
                ) : null}
              </View>
            )
          }
        />
      )}

      {/* ------------- Detail modal ------------- */}
      <Modal visible={!!detail} transparent animationType="fade"
        onRequestClose={() => setDetail(null)}>
        <View style={s.modalWrap}>
          <View style={s.modalCard}>
            <View style={s.modalHead}>
              <View style={{ flex: 1 }}>
                <Text style={s.modalTitle}>{detail?.employee_name}
                  {detail?.employee_code ? `  ·  #${detail?.employee_code}` : ""}</Text>
                <View style={{ flexDirection: "row", gap: 8, marginTop: 4, alignItems: "center" }}>
                  <StatusChip status={dStatus} />
                  {detail?.value ? <Text style={s.valueTxt}>{label}: {detail.value}</Text> : null}
                </View>
              </View>
              <Pressable onPress={() => setDetail(null)} testID="btn-close-detail">
                <Ionicons name="close" size={22} color={colors.textPrimary} />
              </Pressable>
            </View>

            <ScrollView style={{ maxHeight: 460 }} showsVerticalScrollIndicator>
              {/* Validation checklist */}
              {detail?.validation && (
                <View style={s.section}>
                  <Text style={s.sectionTitle}>Validation</Text>
                  {detail.validation.issues.map((i, idx) => (
                    <Text key={`i${idx}`} style={[s.valLine, { color: "#DC2626" }]}>✕ {i}</Text>
                  ))}
                  {detail.validation.warnings.map((w, idx) => (
                    <Text key={`w${idx}`} style={[s.valLine, { color: "#D97706" }]}>! {w}</Text>
                  ))}
                  {detail.validation.issues.length === 0 && (
                    <Text style={[s.valLine, { color: "#059669" }]}>✓ All mandatory checks passed</Text>
                  )}
                  <Text style={[s.valLine, { color: colors.textSecondary }]}>
                    Eligibility: {detail.validation.eligibility_note}
                  </Text>
                </View>
              )}

              {detail?.duplicate && (
                <View style={[s.section, { backgroundColor: "#FEF9C3" }]}>
                  <Text style={[s.sectionTitle, { color: "#CA8A04" }]}>Duplicate detected</Text>
                  <Text style={s.valLine}>{detail.duplicate.note}</Text>
                </View>
              )}
              {detail?.last_error && (
                <View style={[s.section, { backgroundColor: "#FEE2E2" }]}>
                  <Text style={[s.sectionTitle, { color: "#DC2626" }]}>Last run</Text>
                  <Text style={s.valLine}>{detail.last_error}</Text>
                </View>
              )}

              {/* Family particulars (editable in draft-ish states) */}
              {portal === "esic" && (
                <View style={s.section}>
                  <Text style={s.sectionTitle}>Family Particulars (ESIC medical benefit)</Text>
                  {famDraft.map((m, idx) => (
                    <View key={idx} style={s.famRow}>
                      <TextInput style={[s.famInput, { flex: 2 }]} placeholder="Name"
                        placeholderTextColor={colors.textSecondary}
                        value={m.name}
                        onChangeText={(v) => {
                          const n = [...famDraft]; n[idx] = { ...m, name: v }; setFamDraft(n);
                        }} />
                      <TextInput style={[s.famInput, { flex: 1.3 }]} placeholder="Relation"
                        placeholderTextColor={colors.textSecondary}
                        value={m.relation}
                        onChangeText={(v) => {
                          const n = [...famDraft]; n[idx] = { ...m, relation: v }; setFamDraft(n);
                        }} />
                      <TextInput style={[s.famInput, { flex: 1.3 }]} placeholder="DOB (YYYY-MM-DD)"
                        placeholderTextColor={colors.textSecondary}
                        value={m.dob || ""}
                        onChangeText={(v) => {
                          const n = [...famDraft]; n[idx] = { ...m, dob: v }; setFamDraft(n);
                        }} />
                      <Pressable onPress={() => setFamDraft(famDraft.filter((_, i) => i !== idx))}>
                        <Ionicons name="trash-outline" size={16} color="#DC2626" />
                      </Pressable>
                    </View>
                  ))}
                  <View style={{ flexDirection: "row", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
                    <Pressable style={s.addFamBtn}
                      onPress={() => setFamDraft([...famDraft, { name: "", relation: "", residing: true }])}
                      testID="btn-add-family">
                      <Ionicons name="add" size={14} color={colors.brandPrimary} />
                      <Text style={s.addFamTxt}>Add member</Text>
                    </Pressable>
                  </View>
                  <TextInput style={[s.famInput, { marginTop: 8 }]}
                    placeholder="Dispensary / IMP (e.g. Bhilwara ESI Dispensary)"
                    placeholderTextColor={colors.textSecondary}
                    value={dispDraft} onChangeText={setDispDraft} testID="input-dispensary" />
                  {canWrite && ["draft", "failed", "action_required", "existing_found", "rejected"].includes(dStatus) && (
                    <Pressable style={[s.actBtn, { alignSelf: "flex-start", marginTop: 8 }]}
                      onPress={saveDetails} disabled={detailBusy === "save"} testID="btn-save-details">
                      {detailBusy === "save" ? <ActivityIndicator color="#fff" size="small" /> :
                        <Text style={s.actBtnTxt}>Save Details</Text>}
                    </Pressable>
                  )}
                </View>
              )}

              {/* RPA job trail */}
              {detailJob && (
                <View style={s.section}>
                  <Text style={s.sectionTitle}>Portal Automation Run ({detailJob.status})</Text>
                  {(detailJob.steps || []).slice(-5).map((st: any, idx: number) => (
                    <Text key={idx} style={s.valLine}>• {st.msg || st.note}</Text>
                  ))}
                  {detailJob.manual_reason ? (
                    <Text style={[s.valLine, { color: "#EA580C" }]}>{detailJob.manual_reason}</Text>
                  ) : null}
                </View>
              )}

              {/* Audit history */}
              <View style={s.section}>
                <Text style={s.sectionTitle}>Audit History</Text>
                {(detail?.history || []).slice().reverse().map((h, idx) => (
                  <View key={idx} style={s.histRow}>
                    <View style={s.histDot} />
                    <View style={{ flex: 1 }}>
                      <Text style={s.histAction}>
                        {STATUS_META[h.action]?.label || h.action}
                        <Text style={s.histBy}>  — {h.by_name || "System"}</Text>
                      </Text>
                      {h.note ? <Text style={s.histNote}>{h.note}</Text> : null}
                      <Text style={s.histWhen}>{fmtWhen(h.at)}</Text>
                    </View>
                  </View>
                ))}
              </View>

              {/* Link existing */}
              {canWrite && !["generated", "linked_existing"].includes(dStatus) && (
                <View style={s.section}>
                  <Text style={s.sectionTitle}>Link an existing {label} instead</Text>
                  <View style={{ flexDirection: "row", gap: 8 }}>
                    <TextInput style={[s.famInput, { flex: 1 }]}
                      placeholder={portal === "uan" ? "12-digit UAN" : "10–17 digit Insurance No."}
                      placeholderTextColor={colors.textSecondary}
                      keyboardType="number-pad"
                      value={linkVal} onChangeText={setLinkVal} testID="input-link-existing" />
                    <Pressable style={[s.actBtn, { backgroundColor: "#0891B2" }]}
                      disabled={!linkVal.trim() || detailBusy === "link-existing"}
                      onPress={() => act("link-existing", { value: linkVal })}
                      testID="btn-link-existing">
                      {detailBusy === "link-existing" ? <ActivityIndicator color="#fff" size="small" /> :
                        <Text style={s.actBtnTxt}>Link</Text>}
                    </Pressable>
                  </View>
                </View>
              )}
            </ScrollView>

            {/* Action bar */}
            <View style={s.actionBar}>
              {canWrite && ["draft", "failed", "action_required", "existing_found", "rejected"].includes(dStatus) && (
                <Pressable style={s.actBtn} onPress={() => act("submit")}
                  disabled={!!detailBusy} testID="btn-submit-reg">
                  {detailBusy === "submit" ? <ActivityIndicator color="#fff" size="small" /> : (
                    <><Ionicons name="paper-plane-outline" size={14} color="#fff" />
                      <Text style={s.actBtnTxt}>Submit</Text></>
                  )}
                </Pressable>
              )}
              {canApprove && dStatus === "pending_approval" && (
                <>
                  <Pressable style={[s.actBtn, { backgroundColor: "#059669" }]}
                    onPress={() => act("approve")} disabled={!!detailBusy} testID="btn-approve-reg">
                    {detailBusy === "approve" ? <ActivityIndicator color="#fff" size="small" /> : (
                      <><Ionicons name="checkmark-outline" size={14} color="#fff" />
                        <Text style={s.actBtnTxt}>Approve & Queue</Text></>
                    )}
                  </Pressable>
                  <Pressable style={[s.actBtn, { backgroundColor: "#DC2626" }]}
                    onPress={() => act("reject")} disabled={!!detailBusy} testID="btn-reject-reg">
                    <Text style={s.actBtnTxt}>Reject</Text>
                  </Pressable>
                </>
              )}
              {canWrite && ["failed", "action_required"].includes(dStatus) && (
                <Pressable style={[s.actBtn, { backgroundColor: "#EA580C" }]}
                  onPress={() => act("retry")} disabled={!!detailBusy} testID="btn-retry-reg">
                  {detailBusy === "retry" ? <ActivityIndicator color="#fff" size="small" /> : (
                    <><Ionicons name="refresh-outline" size={14} color="#fff" />
                      <Text style={s.actBtnTxt}>Retry</Text></>
                  )}
                </Pressable>
              )}
              <Pressable style={[s.actBtn, { backgroundColor: colors.textSecondary }]}
                onPress={downloadForm} disabled={!!detailBusy} testID="btn-download-form">
                {detailBusy === "form" ? <ActivityIndicator color="#fff" size="small" /> : (
                  <><Ionicons name="document-text-outline" size={14} color="#fff" />
                    <Text style={s.actBtnTxt}>{portal === "esic" ? "Form-1 PDF" : "Form-11 PDF"}</Text></>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* ------------- Settings modal ------------- */}
      <Modal visible={showSettings} transparent animationType="fade"
        onRequestClose={() => setShowSettings(false)}>
        <View style={s.modalWrap}>
          <View style={[s.modalCard, { maxWidth: 460 }]}>
            <View style={s.modalHead}>
              <Text style={s.modalTitle}>Eligibility Rules</Text>
              <Pressable onPress={() => setShowSettings(false)}>
                <Ionicons name="close" size={22} color={colors.textPrimary} />
              </Pressable>
            </View>
            {setDraft && (
              <View style={{ gap: 12 }}>
                <View>
                  <Text style={s.setLabel}>ESIC wage ceiling (₹/month)</Text>
                  <TextInput style={s.famInput} keyboardType="number-pad"
                    value={String(setDraft.esic_wage_ceiling)}
                    onChangeText={(v) => setSetDraft({ ...setDraft, esic_wage_ceiling: Number(v) || 0 })}
                    testID="input-esic-ceiling" />
                </View>
                <View>
                  <Text style={s.setLabel}>EPF mandatory wage ceiling (₹/month)</Text>
                  <TextInput style={s.famInput} keyboardType="number-pad"
                    value={String(setDraft.pf_wage_ceiling)}
                    onChangeText={(v) => setSetDraft({ ...setDraft, pf_wage_ceiling: Number(v) || 0 })}
                    testID="input-pf-ceiling" />
                </View>
                <View style={s.switchRow}>
                  <Text style={s.setLabel}>Firm covers ALL employees under EPF</Text>
                  <Switch value={setDraft.pf_cover_all}
                    onValueChange={(v) => setSetDraft({ ...setDraft, pf_cover_all: v })} />
                </View>
                <View style={s.switchRow}>
                  <Text style={s.setLabel}>Require HR approval before portal run</Text>
                  <Switch value={setDraft.require_approval}
                    onValueChange={(v) => setSetDraft({ ...setDraft, require_approval: v })} />
                </View>
                <Pressable style={[s.actBtn, { alignSelf: "flex-end" }]} onPress={saveSettings}
                  disabled={savingSettings || !canWrite} testID="btn-save-settings">
                  {savingSettings ? <ActivityIndicator color="#fff" size="small" /> :
                    <Text style={s.actBtnTxt}>Save Rules</Text>}
                </Pressable>
              </View>
            )}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  center: { alignItems: "center", justifyContent: "center", padding: 40, gap: 10 },
  emptyTxt: { color: colors.textSecondary, fontSize: 13, textAlign: "center", maxWidth: 320 },

  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 16, paddingTop: 14, paddingBottom: 6,
  },
  title: { fontSize: 20, fontWeight: "800", color: colors.textPrimary },
  subtitle: { fontSize: 12, color: colors.textSecondary, marginTop: 2 },
  iconBtn: {
    width: 38, height: 38, borderRadius: 10, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
  },

  segRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 16, paddingVertical: 8, flexWrap: "wrap",
  },
  segBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999,
    borderWidth: 1, borderColor: colors.brandPrimary, backgroundColor: colors.surfaceSecondary,
  },
  segBtnOn: { backgroundColor: colors.brandPrimary },
  segTxt: { fontSize: 12.5, fontWeight: "700", color: colors.brandPrimary },
  segTxtOn: { color: "#fff" },

  kpiRow: { paddingVertical: 8 },
  kpiCard: {
    minWidth: 138, backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, padding: 12, gap: 4,
  },
  kpiIcon: { width: 28, height: 28, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  kpiValue: { fontSize: 20, fontWeight: "800", color: colors.textPrimary },
  kpiLabel: { fontSize: 11.5, color: colors.textSecondary, fontWeight: "600" },
  kpiSub: { fontSize: 10.5, fontWeight: "700" },

  tabRow: { flexDirection: "row", gap: 8, paddingHorizontal: 16, paddingVertical: 10 },
  tabBtn: {
    paddingHorizontal: 14, paddingVertical: 9, borderRadius: 10,
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
  },
  tabBtnOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, fontWeight: "700", color: colors.textPrimary },
  tabTxtOn: { color: "#fff" },

  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 8, marginHorizontal: 16, marginBottom: 10,
    paddingHorizontal: 12, borderRadius: 10, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary, height: 42,
  },
  searchInput: { flex: 1, fontSize: 13.5, color: colors.textPrimary },

  filterChip: {
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  filterChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  filterTxt: { fontSize: 11.5, fontWeight: "700", color: colors.textSecondary },
  filterTxtOn: { color: "#fff" },

  bulkBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 16, paddingBottom: 10, gap: 10,
  },
  bulkSelectAll: { flexDirection: "row", alignItems: "center", gap: 6 },
  bulkSelectTxt: { fontSize: 12.5, fontWeight: "700", color: colors.brandPrimary },
  bulkBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.brandPrimary,
    paddingHorizontal: 16, paddingVertical: 10, borderRadius: 10,
  },
  bulkBtnTxt: { color: "#fff", fontSize: 12.5, fontWeight: "800" },

  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    marginHorizontal: 16, marginBottom: 8, padding: 12,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
  },
  rowName: { fontSize: 13.5, fontWeight: "700", color: colors.textPrimary },
  rowSub: { fontSize: 11.5, color: colors.textSecondary, marginTop: 2 },
  rowWhen: { fontSize: 10.5, color: colors.textSecondary, marginTop: 2, opacity: 0.8 },

  chip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999,
  },
  chipTxt: { fontSize: 10.5, fontWeight: "800" },

  miniBtn: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8,
    backgroundColor: colors.brandPrimary,
  },
  miniBtnAlt: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.brandPrimary,
  },
  miniBtnTxt: { color: "#fff", fontSize: 11.5, fontWeight: "800" },

  modalWrap: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.55)",
    alignItems: "center", justifyContent: "center", padding: 16,
  },
  modalCard: {
    width: "100%", maxWidth: 640, backgroundColor: colors.surface,
    borderRadius: radius.lg, padding: 16, gap: 10,
  },
  modalHead: { flexDirection: "row", alignItems: "flex-start", gap: 10, marginBottom: 4 },
  modalTitle: { fontSize: 16, fontWeight: "800", color: colors.textPrimary, flex: 1 },
  valueTxt: { fontSize: 12, fontWeight: "800", color: "#059669" },

  section: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 12, padding: 12,
    borderWidth: 1, borderColor: colors.border, marginBottom: 10,
  },
  sectionTitle: { fontSize: 12.5, fontWeight: "800", color: colors.textPrimary, marginBottom: 6 },
  valLine: { fontSize: 12, color: colors.textPrimary, marginBottom: 3, lineHeight: 17 },

  famRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 },
  famInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: Platform.OS === "web" ? 8 : 6,
    fontSize: 12.5, color: colors.textPrimary, backgroundColor: colors.surface,
  },
  addFamBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8,
    borderWidth: 1, borderColor: colors.brandPrimary,
  },
  addFamTxt: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },

  histRow: { flexDirection: "row", gap: 8, marginBottom: 8 },
  histDot: {
    width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brandPrimary, marginTop: 5,
  },
  histAction: { fontSize: 12, fontWeight: "800", color: colors.textPrimary },
  histBy: { fontWeight: "600", color: colors.textSecondary },
  histNote: { fontSize: 11.5, color: colors.textSecondary, marginTop: 1 },
  histWhen: { fontSize: 10.5, color: colors.textSecondary, marginTop: 1, opacity: 0.8 },

  actionBar: {
    flexDirection: "row", flexWrap: "wrap", gap: 8, paddingTop: 4,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  actBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, paddingHorizontal: 14, paddingVertical: 9,
    borderRadius: 9,
  },
  actBtnTxt: { color: "#fff", fontSize: 12, fontWeight: "800" },

  setLabel: { fontSize: 12.5, fontWeight: "700", color: colors.textPrimary, marginBottom: 4, flex: 1 },
  switchRow: { flexDirection: "row", alignItems: "center", gap: 10 },
});
