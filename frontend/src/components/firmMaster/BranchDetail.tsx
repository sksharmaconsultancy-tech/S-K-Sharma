/**
 * Iter 737 — BRANCH DETAIL (Branch Master drill-down).
 * Tabs: Overview | Compliance | Payroll | Attendance | Employees |
 * Documents | History. All configs are MAPPINGS/DEFAULTS only — the
 * attendance / payroll / compliance calculation engines are untouched.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";
import {
  BmField, BmToggle, BmBtn, BmChipRow, StatusPill, bm, showWebMsg,
} from "@/src/components/firmMaster/branchMasterUi";
import type { Branch } from "@/src/components/firmMaster/BranchesSection";
import BranchEmployeesTab from "@/src/components/firmMaster/BranchEmployeesTab";
import BranchDocsTab from "@/src/components/firmMaster/BranchDocsTab";

const TABS = [
  { id: "overview", label: "Overview", icon: "speedometer-outline" },
  { id: "compliance", label: "Compliance", icon: "shield-checkmark-outline" },
  { id: "payroll", label: "Payroll", icon: "cash-outline" },
  { id: "attendance", label: "Attendance", icon: "time-outline" },
  { id: "employees", label: "Employees", icon: "people-outline" },
  { id: "documents", label: "Documents", icon: "document-text-outline" },
  { id: "history", label: "History", icon: "git-compare-outline" },
] as const;

type TabId = typeof TABS[number]["id"];

export default function BranchDetail({
  branchId, companyId, branches, onClose,
}: {
  branchId: string;
  companyId: string;
  branches: Branch[];
  onClose: () => void;
}) {
  const [branch, setBranch] = useState<any>(null);
  const [audit, setAudit] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<TabId>("overview");
  const [stateNames, setStateNames] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ branch: any; audit: any[] }>(`/admin/branch-master/${branchId}`);
      setBranch(r.branch);
      setAudit(r.audit || []);
    } catch (e: any) {
      showWebMsg(e?.message || "Could not load branch");
    } finally { setLoading(false); }
  }, [branchId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api<{ states: any[] }>("/admin/branch-extras/states")
      .then((r) => setStateNames((r.states || []).map((s) => s.state)))
      .catch(() => {});
  }, []);

  const patch = async (body: any) => {
    const r = await api<{ branch: any }>(`/admin/branch-master/${branchId}`, {
      method: "PATCH", body,
    });
    setBranch(r.branch);
    return r.branch;
  };

  if (loading || !branch) {
    return (
      <View style={styles.card}>
        <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 30 }} />
      </View>
    );
  }

  return (
    <View style={styles.card} testID="fm-branch-detail">
      {/* Header: name + code + state + status */}
      <View style={styles.head}>
        <Pressable onPress={onClose} style={styles.backBtn} testID="fm-branch-detail-back">
          <Ionicons name="arrow-back" size={16} color={colors.brandPrimary} />
          <Text style={styles.backTxt}>All branches</Text>
        </Pressable>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <Text style={styles.title}>{branch.name}</Text>
          {branch.code ? <Text style={styles.codeTxt}>{branch.code}</Text> : null}
          {branch.state ? (
            <View style={styles.statePill}>
              <Ionicons name="map-outline" size={11} color={colors.brandPrimary} />
              <Text style={styles.statePillTxt}>{branch.state}</Text>
            </View>
          ) : null}
          <StatusPill active={branch.active !== false} />
          <BmBtn
            label={branch.active !== false ? "Deactivate" : "Activate"}
            kind={branch.active !== false ? "danger" : "primary"} small
            onPress={async () => {
              try { await patch({ active: branch.active === false }); }
              catch (e: any) { showWebMsg(e?.message || "Failed"); }
            }}
            testID="fm-branch-toggle-active"
          />
        </View>
      </View>

      {/* Tab bar */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false}
                  contentContainerStyle={{ gap: 6, paddingVertical: 8 }}>
        {TABS.map((t) => (
          <Pressable key={t.id} onPress={() => setTab(t.id)}
                     style={[styles.tab, tab === t.id && styles.tabOn]}
                     testID={`fm-branch-tab-${t.id}`}>
            <Ionicons name={t.icon as any} size={13}
                      color={tab === t.id ? "#FFF" : colors.onSurfaceSecondary} />
            <Text style={[styles.tabTxt, tab === t.id && { color: "#FFF" }]}>{t.label}</Text>
          </Pressable>
        ))}
      </ScrollView>

      {tab === "overview" ? <OverviewTab branch={branch} branchId={branchId} onGoTab={setTab} /> : null}
      {tab === "compliance" ? (
        <ComplianceTab branch={branch} stateNames={stateNames} onSave={patch} />
      ) : null}
      {tab === "payroll" ? <PayrollTab branch={branch} onSave={patch} /> : null}
      {tab === "attendance" ? <AttendanceTab branch={branch} onSave={patch} /> : null}
      {tab === "employees" ? (
        <BranchEmployeesTab branch={branch} branches={branches} companyId={companyId} />
      ) : null}
      {tab === "documents" ? <BranchDocsTab branchId={branchId} /> : null}
      {tab === "history" ? <HistoryTab branchId={branchId} audit={audit} /> : null}
    </View>
  );
}

/* ------------------------------------------------------------------ */
/*  Overview — dashboard cards from existing system data              */
/* ------------------------------------------------------------------ */

function OverviewTab({ branch, branchId, onGoTab }: {
  branch: any; branchId: string; onGoTab: (t: TabId) => void;
}) {
  const router = useRouter();
  const [d, setD] = useState<any>(null);
  useEffect(() => {
    api<any>(`/admin/branch-master/${branchId}/dashboard`)
      .then(setD).catch(() => setD({}));
  }, [branchId]);

  const addr = [branch.address1, branch.address2, branch.area, branch.city,
    branch.district, branch.state, branch.pin_code, branch.country]
    .filter(Boolean).join(", ");

  const cards: { label: string; value: any; color?: string; onPress?: () => void }[] = d ? [
    { label: "Total Employees", value: d.total_employees, onPress: () => onGoTab("employees") },
    { label: "Active", value: d.active_employees, color: "#15803D", onPress: () => onGoTab("employees") },
    { label: "Present Today", value: d.present_today, color: "#15803D",
      onPress: () => router.push("/attendance-report" as any) },
    { label: "Absent Today", value: d.absent_today, color: "#B91C1C",
      onPress: () => router.push("/attendance-report" as any) },
    { label: "On Leave", value: d.on_leave, color: "#B45309" },
    { label: "On Duty (temp)", value: d.on_duty },
    { label: "Attendance %", value: `${d.attendance_pct ?? 0}%` },
    { label: "Payroll Status", value: String(d.payroll_status || "—").replace("_", " "),
      onPress: () => router.push("/salary-register" as any) },
    { label: "Compliance", value: String(d.compliance_status || "—").replace("_", " "),
      color: d.compliance_status === "configured" ? "#15803D" : "#B45309",
      onPress: () => onGoTab("compliance") },
    { label: "Pending Approvals", value: d.pending_approvals, color: "#B45309",
      onPress: () => router.push("/branch-compliance" as any) },
    { label: "New Joiners", value: d.new_joiners },
    { label: "Exits", value: d.exits },
    { label: "Open F&F", value: d.open_fnf,
      onPress: () => router.push("/fnf-calculator" as any) },
  ] : [];

  return (
    <View>
      {!d ? <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 20 }} /> : (
        <View style={styles.cardsWrap}>
          {cards.map((c) => (
            <Pressable key={c.label} style={styles.dashCard} onPress={c.onPress}
                       disabled={!c.onPress} testID={`fm-dash-${c.label.replace(/\W+/g, "-")}`}>
              <Text style={[styles.dashVal, c.color ? { color: c.color } : null]}>
                {c.value ?? 0}
              </Text>
              <Text style={styles.dashLbl}>{c.label}</Text>
            </Pressable>
          ))}
        </View>
      )}
      <Text style={bm.secTitle}>Branch Information</Text>
      <View style={styles.infoBox}>
        <InfoRow k="Branch ID" v={branch.branch_id} />
        <InfoRow k="Type" v={branch.branch_type || "Branch"} />
        <InfoRow k="Manager" v={branch.manager_name} />
        <InfoRow k="Contact" v={[branch.contact_person, branch.mobile, branch.email].filter(Boolean).join(" · ")} />
        <InfoRow k="Address" v={addr || branch.address} />
        <InfoRow k="GPS" v={branch.office_lat != null
          ? `${Number(branch.office_lat).toFixed(6)}, ${Number(branch.office_lng).toFixed(6)} · radius ${branch.geofence_radius_m || 200} m · geofence ${branch.geofence_enabled === false ? "OFF" : "ON"}`
          : "—"} />
        <InfoRow k="Created" v={`${(branch.created_at || "").slice(0, 10)}${branch.created_by_name ? ` · by ${branch.created_by_name}` : ""}`} />
        {branch.updated_at ? (
          <InfoRow k="Last updated" v={`${String(branch.updated_at).replace("T", " ").slice(0, 16)}${branch.updated_by_name ? ` · by ${branch.updated_by_name}` : ""}`} />
        ) : null}
      </View>
    </View>
  );
}

function InfoRow({ k, v }: { k: string; v?: any }) {
  return (
    <View style={styles.infoRow}>
      <Text style={styles.infoK}>{k}</Text>
      <Text style={styles.infoV}>{v || "—"}</Text>
    </View>
  );
}

/* ------------------------------------------------------------------ */
/*  Compliance config (mapping only — engine untouched)               */
/* ------------------------------------------------------------------ */

function ComplianceTab({ branch, stateNames, onSave }: {
  branch: any; stateNames: string[]; onSave: (b: any) => Promise<any>;
}) {
  const cc0 = branch.compliance_config || {};
  const [cc, setCc] = useState<any>({ ...cc0 });
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => setCc((p: any) => ({ ...p, [k]: v }));

  const save = async () => {
    setBusy(true);
    try {
      await onSave({ compliance_config: cc, state: cc.mw_state || branch.state || null });
      showWebMsg("Compliance configuration saved ✓");
    } catch (e: any) { showWebMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  return (
    <View>
      <Text style={styles.tabHint}>
        Branch-level compliance MAPPING — existing compliance salary engine
        untouched. State mapping PT/LWF/Min-Wage reports (Iter 733) में use
        होती है.
      </Text>
      <Text style={bm.secTitle}>Professional Tax</Text>
      <BmToggle label="PT Applicable" value={!!cc.pt_applicable}
                onChange={(v) => set("pt_applicable", v)} testID="cc-pt-applicable" />
      {cc.pt_applicable ? (
        <View style={bm.row}>
          <BmChipRow label="PT State" options={stateNames} value={cc.pt_state}
                     onChange={(v) => set("pt_state", v)} />
          <BmField label="PT Registration No." value={cc.pt_regn_no || ""}
                   onChangeText={(v) => set("pt_regn_no", v)} width={220} />
        </View>
      ) : null}

      <Text style={bm.secTitle}>Labour Welfare Fund</Text>
      <BmToggle label="LWF Applicable" value={!!cc.lwf_applicable}
                onChange={(v) => set("lwf_applicable", v)} testID="cc-lwf-applicable" />
      {cc.lwf_applicable ? (
        <View style={bm.row}>
          <BmChipRow label="LWF State" options={stateNames} value={cc.lwf_state}
                     onChange={(v) => set("lwf_state", v)} />
          <BmField label="LWF Registration No." value={cc.lwf_regn_no || ""}
                   onChangeText={(v) => set("lwf_regn_no", v)} width={220} />
        </View>
      ) : null}

      <Text style={bm.secTitle}>Minimum Wage</Text>
      <BmChipRow label="Minimum Wage State" options={stateNames} value={cc.mw_state || branch.state}
                 onChange={(v) => set("mw_state", v)} testID="cc-mw-state" />
      <View style={bm.row}>
        <BmField label="Zone / Area" value={cc.mw_zone || ""}
                 onChangeText={(v) => set("mw_zone", v)} width={180} />
        <BmChipRow label="Wage Category" value={cc.mw_category}
                   options={["unskilled", "semi_skilled", "skilled", "highly_skilled"]}
                   onChange={(v) => set("mw_category", v)} />
      </View>

      <Text style={bm.secTitle}>PF / ESIC</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
        <BmToggle label="PF Applicable" value={!!cc.pf_applicable}
                  onChange={(v) => set("pf_applicable", v)} testID="cc-pf-applicable" />
        <BmToggle label="ESIC Applicable" value={!!cc.esic_applicable}
                  onChange={(v) => set("esic_applicable", v)} testID="cc-esic-applicable" />
      </View>

      <Text style={bm.secTitle}>Establishment</Text>
      <View style={bm.row}>
        <BmField label="Establishment Type" value={cc.establishment_type || ""}
                 onChangeText={(v) => set("establishment_type", v)}
                 placeholder="Shop / Factory / Commercial…" />
        <BmField label="S&E Registration No." value={cc.sne_regn_no || ""}
                 onChangeText={(v) => set("sne_regn_no", v)} />
      </View>
      <View style={bm.row}>
        <BmField label="Registration Date (YYYY-MM-DD)" value={cc.sne_regn_date || ""}
                 onChangeText={(v) => set("sne_regn_date", v)} placeholder="2024-04-01" width={200} />
        <BmField label="Registration Expiry (YYYY-MM-DD)" value={cc.sne_expiry_date || ""}
                 onChangeText={(v) => set("sne_expiry_date", v)} placeholder="2027-03-31" width={200} />
      </View>
      <BmField label="Other Compliance Notes" value={cc.other_notes || ""}
               onChangeText={(v) => set("other_notes", v)} />
      <View style={{ alignItems: "flex-end", marginTop: 8 }}>
        <BmBtn label="Save Compliance Config" onPress={save} busy={busy}
               testID="cc-save" />
      </View>
    </View>
  );
}

/* ------------------------------------------------------------------ */
/*  Payroll defaults (mapping only)                                    */
/* ------------------------------------------------------------------ */

function PayrollTab({ branch, onSave }: { branch: any; onSave: (b: any) => Promise<any> }) {
  const p0 = branch.payroll_config || {};
  const [p, setP] = useState<any>({ ...p0 });
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => setP((x: any) => ({ ...x, [k]: v }));
  const save = async () => {
    setBusy(true);
    try {
      await onSave({ payroll_config: p });
      showWebMsg("Payroll defaults saved ✓");
    } catch (e: any) { showWebMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <View>
      <Text style={styles.tabHint}>
        Branch-level payroll DEFAULTS (mapping only) — employee-specific
        settings और existing payroll logic override नहीं होते.
      </Text>
      <BmChipRow label="Payroll Cycle" options={["Monthly", "Weekly", "Fortnightly"]}
                 value={p.payroll_cycle} onChange={(v) => set("payroll_cycle", v)}
                 testID="pc-cycle" />
      <View style={bm.row}>
        <BmField label="Salary Processing Date (day of month)" value={p.processing_date || ""}
                 onChangeText={(v) => set("processing_date", v)} keyboardType="number-pad" width={220} />
        <BmField label="Salary Payment Date (day of month)" value={p.payment_date || ""}
                 onChangeText={(v) => set("payment_date", v)} keyboardType="number-pad" width={220} />
      </View>
      <BmChipRow label="Weekly Off"
                 options={["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]}
                 value={p.weekly_off} onChange={(v) => set("weekly_off", v)} testID="pc-weekoff" />
      <View style={bm.row}>
        <BmField label="Holiday Calendar" value={p.holiday_calendar || ""}
                 onChangeText={(v) => set("holiday_calendar", v)} placeholder="e.g. Rajasthan 2026" />
        <BmField label="Default Leave Policy" value={p.leave_policy || ""}
                 onChangeText={(v) => set("leave_policy", v)} />
      </View>
      <View style={bm.row}>
        <BmField label="Default Attendance Policy" value={p.attendance_policy || ""}
                 onChangeText={(v) => set("attendance_policy", v)} />
        <BmField label="Default Overtime Policy" value={p.ot_policy || ""}
                 onChangeText={(v) => set("ot_policy", v)} />
      </View>
      <View style={bm.row}>
        <BmField label="Default Shift Policy" value={p.shift_policy || ""}
                 onChangeText={(v) => set("shift_policy", v)} />
        <BmField label="Default F&F Policy" value={p.fnf_policy || ""}
                 onChangeText={(v) => set("fnf_policy", v)} />
      </View>
      <View style={{ alignItems: "flex-end", marginTop: 8 }}>
        <BmBtn label="Save Payroll Defaults" onPress={save} busy={busy} testID="pc-save" />
      </View>
    </View>
  );
}

/* ------------------------------------------------------------------ */
/*  Attendance defaults (mapping only — duty-hours engine untouched)   */
/* ------------------------------------------------------------------ */

function AttendanceTab({ branch, onSave }: { branch: any; onSave: (b: any) => Promise<any> }) {
  const a0 = branch.attendance_config || {};
  const [a, setA] = useState<any>({ cross_midnight: true, ...a0 });
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => setA((x: any) => ({ ...x, [k]: v }));
  const save = async () => {
    setBusy(true);
    try {
      await onSave({ attendance_config: a });
      showWebMsg("Attendance defaults saved ✓");
    } catch (e: any) { showWebMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <View>
      <Text style={styles.tabHint}>
        Branch-level attendance DEFAULTS (mapping only) — existing attendance
        / duty-hours calculation logic बिल्कुल untouched है.
      </Text>
      <View style={bm.row}>
        <BmField label="Attendance Policy" value={a.attendance_policy || ""}
                 onChangeText={(v) => set("attendance_policy", v)} />
        <BmField label="Default Shift" value={a.default_shift || ""}
                 onChangeText={(v) => set("default_shift", v)} placeholder="e.g. GEN 09:00-18:00" />
        <BmField label="Punch Policy" value={a.punch_policy || ""}
                 onChangeText={(v) => set("punch_policy", v)} />
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
        <BmToggle label="Mobile Punch Allowed" value={a.mobile_punch_allowed !== false}
                  onChange={(v) => set("mobile_punch_allowed", v)} testID="ac-mobile-punch" />
        <BmToggle label="GPS Required" value={!!a.gps_required}
                  onChange={(v) => set("gps_required", v)} testID="ac-gps" />
        <BmToggle label="Geofence Required" value={!!a.geofence_required}
                  onChange={(v) => set("geofence_required", v)} testID="ac-geofence" />
        <BmToggle label="Photo Required" value={!!a.photo_required}
                  onChange={(v) => set("photo_required", v)} testID="ac-photo" />
        <BmToggle label="Cross Midnight Attendance" value={a.cross_midnight !== false}
                  onChange={(v) => set("cross_midnight", v)} testID="ac-cross-midnight" />
      </View>
      <View style={bm.row}>
        <BmField label="Late Policy" value={a.late_policy || ""}
                 onChangeText={(v) => set("late_policy", v)} />
        <BmField label="Early Exit Policy" value={a.early_exit_policy || ""}
                 onChangeText={(v) => set("early_exit_policy", v)} />
        <BmField label="Grace Period (minutes)" value={String(a.grace_minutes ?? "")}
                 onChangeText={(v) => set("grace_minutes", v)} keyboardType="number-pad" width={160} />
        <BmField label="Overtime Policy" value={a.ot_policy || ""}
                 onChangeText={(v) => set("ot_policy", v)} />
      </View>
      <View style={{ alignItems: "flex-end", marginTop: 8 }}>
        <BmBtn label="Save Attendance Defaults" onPress={save} busy={busy} testID="ac-save" />
      </View>
    </View>
  );
}

/* ------------------------------------------------------------------ */
/*  History — transfers in/out + audit trail                           */
/* ------------------------------------------------------------------ */

function HistoryTab({ branchId, audit }: { branchId: string; audit: any[] }) {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => {
    api<{ history: any[] }>(`/admin/branch-master/${branchId}/history`)
      .then((r) => setRows(r.history || [])).catch(() => setRows([]));
  }, [branchId]);
  return (
    <View>
      <Text style={bm.secTitle}>Employee Transfers (in / out — never deleted)</Text>
      {rows === null ? <ActivityIndicator color={colors.brandPrimary} /> :
        rows.length === 0 ? <Text style={styles.tabHint}>No transfers yet.</Text> :
          rows.map((t) => (
            <View key={t.transfer_id} style={styles.histRow}>
              <Ionicons name={t.direction === "IN" ? "arrow-down-circle" : "arrow-up-circle"}
                        size={16} color={t.direction === "IN" ? "#15803D" : "#B45309"} />
              <View style={{ flex: 1 }}>
                <Text style={styles.histT}>
                  {t.employee_name} — {t.prev_branch_name} → {t.new_branch_name}
                </Text>
                <Text style={styles.histM}>
                  Effective {t.effective_date} · {t.status}
                  {t.reason ? ` · ${t.reason}` : ""}
                </Text>
              </View>
            </View>
          ))}
      <Text style={bm.secTitle}>Audit Trail (old → new)</Text>
      {audit.length === 0 ? <Text style={styles.tabHint}>No changes recorded yet.</Text> :
        audit.map((a) => (
          <View key={a.audit_id} style={styles.histRow}>
            <Ionicons name="create-outline" size={15} color={colors.onSurfaceTertiary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.histT}>
                {String(a.action || "").replace(/_/g, " ")} · {a.by_name || a.by}
              </Text>
              <Text style={styles.histM}>
                {String(a.at || "").replace("T", " ").slice(0, 16)}
                {(a.changes || []).slice(0, 6).map((c: any) =>
                  `\n${c.field}: ${JSON.stringify(c.old) ?? "—"} → ${JSON.stringify(c.new)}`).join("")}
              </Text>
            </View>
          </View>
        ))}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  head: { gap: 8 },
  backBtn: { flexDirection: "row", alignItems: "center", gap: 5, alignSelf: "flex-start" },
  backTxt: { fontSize: 12, fontWeight: "800", color: colors.brandPrimary },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  codeTxt: {
    fontSize: 11.5, fontWeight: "800", color: colors.onSurfaceSecondary,
    backgroundColor: colors.surfaceSecondary, borderRadius: 8,
    paddingHorizontal: 8, paddingVertical: 3, overflow: "hidden",
  },
  statePill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 12,
    paddingHorizontal: 8, paddingVertical: 3,
  },
  statePillTxt: { fontSize: 11, fontWeight: "700", color: colors.brandPrimary },
  tab: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderColor: colors.border, borderRadius: 16,
    paddingHorizontal: 11, paddingVertical: 6, backgroundColor: colors.surface,
  },
  tabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabHint: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginBottom: 8 },
  cardsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  dashCard: {
    minWidth: 118, flexGrow: 1, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: 10, backgroundColor: colors.surfaceSecondary,
  },
  dashVal: { fontSize: 18, fontWeight: "800", color: colors.onSurface, textTransform: "capitalize" },
  dashLbl: { fontSize: 10.5, fontWeight: "700", color: colors.onSurfaceTertiary, marginTop: 2 },
  infoBox: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.sm, backgroundColor: colors.surfaceSecondary,
  },
  infoRow: { flexDirection: "row", gap: 8, paddingVertical: 3 },
  infoK: { width: 110, fontSize: 11.5, fontWeight: "800", color: colors.onSurfaceTertiary },
  infoV: { flex: 1, fontSize: 12, color: colors.onSurface },
  histRow: {
    flexDirection: "row", gap: 8, alignItems: "flex-start",
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 8, marginBottom: 6, backgroundColor: colors.surfaceSecondary,
  },
  histT: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  histM: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
});
