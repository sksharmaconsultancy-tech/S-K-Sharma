/**
 * Iter 737 — Branch Employees tab: paginated list, single & BULK transfer
 * (effective-dated → immutable branch history), employee timeline and
 * Excel export. Employee master structure untouched — only
 * users.home_branch_id mapping via the existing transfer register.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api, apiBinary } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";
import {
  BmField, BmBtn, BmChip, bm, showWebMsg,
} from "@/src/components/firmMaster/branchMasterUi";
import type { Branch } from "@/src/components/firmMaster/BranchesSection";

const PAGE_SIZE = 25;

export default function BranchEmployeesTab({
  branch, branches, companyId,
}: {
  branch: any;
  branches: Branch[];
  companyId: string;
}) {
  const [emps, setEmps] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showTransfer, setShowTransfer] = useState(false);
  const [showAssign, setShowAssign] = useState(false);
  const [historyOf, setHistoryOf] = useState<any>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
      if (q.trim()) qs.set("q", q.trim());
      const r = await api<{ employees: any[]; total: number }>(
        `/admin/branch-master/${branch.branch_id}/employees?${qs.toString()}`);
      setEmps(r.employees || []);
      setTotal(r.total || 0);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [branch.branch_id, page, q]);

  useEffect(() => { load(); }, [load]);

  const toggleSel = (uid: string) => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(uid)) n.delete(uid); else n.add(uid);
      return n;
    });
  };

  const exportXlsx = async () => {
    try {
      const r = await apiBinary(`/admin/branch-master/${branch.branch_id}/employees-export`);
      if (Platform.OS === "web" && r.webBlobUrl) {
        const a = document.createElement("a");
        a.href = r.webBlobUrl;
        a.download = `Branch_Employees_${branch.code || branch.name}.xlsx`;
        a.click();
      }
    } catch (e: any) { showWebMsg(e?.message || "Export failed"); }
  };

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <View>
      <View style={styles.toolbar}>
        <View style={styles.searchRow}>
          <Ionicons name="search" size={13} color={colors.onSurfaceTertiary} />
          <TextInput
            value={q}
            onChangeText={(t) => { setQ(t); setPage(1); }}
            placeholder="Search name / code…"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={styles.searchInput}
            testID="be-search"
          />
        </View>
        <BmBtn label="Assign to this branch" kind="ghost" icon="person-add-outline" small
               onPress={() => setShowAssign(!showAssign)} testID="be-assign" />
        <BmBtn label={selected.size ? `Transfer (${selected.size})` : "Transfer"}
               kind="ghost" icon="swap-horizontal-outline" small
               onPress={() => {
                 if (!selected.size) { showWebMsg("पहले employees select करें (checkbox)"); return; }
                 setShowTransfer(true);
               }} testID="be-transfer" />
        <BmBtn label="Export" kind="ghost" icon="download-outline" small
               onPress={exportXlsx} testID="be-export" />
      </View>

      {showAssign ? (
        <AssignPanel branch={branch} companyId={companyId}
                     onDone={() => { setShowAssign(false); load(); }} />
      ) : null}

      {showTransfer ? (
        <TransferPanel
          userIds={[...selected]}
          branch={branch}
          branches={branches.filter((b) => b.branch_id !== branch.branch_id && b.active !== false)}
          onDone={() => { setShowTransfer(false); setSelected(new Set()); load(); }}
          onCancel={() => setShowTransfer(false)}
        />
      ) : null}

      {historyOf ? (
        <EmployeeHistory emp={historyOf} onClose={() => setHistoryOf(null)} />
      ) : null}

      {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 14 }} /> : (
        <>
          <Text style={styles.totalTxt}>{total} employee(s) in this branch</Text>
          {emps.map((e) => (
            <View key={e.user_id} style={styles.eRow} testID={`be-emp-${e.user_id}`}>
              <Pressable onPress={() => toggleSel(e.user_id)} testID={`be-sel-${e.user_id}`}>
                <Ionicons
                  name={selected.has(e.user_id) ? "checkbox" : "square-outline"}
                  size={17}
                  color={selected.has(e.user_id) ? colors.brandPrimary : colors.onSurfaceTertiary}
                />
              </Pressable>
              <View style={{ flex: 1 }}>
                <Text style={styles.eName}>
                  {e.employee_code ? `${e.employee_code} · ` : ""}{e.name}
                </Text>
                <Text style={styles.eMeta}>
                  {[e.designation, e.department, e.doj || e.date_of_joining]
                    .filter(Boolean).join(" · ") || "—"}
                  {e.status === "inactive" ? " · INACTIVE" : ""}
                </Text>
              </View>
              <Pressable onPress={() => setHistoryOf(e)} style={styles.histBtn}
                         testID={`be-history-${e.user_id}`}>
                <Ionicons name="time-outline" size={13} color={colors.brandPrimary} />
                <Text style={styles.histBtnTxt}>History</Text>
              </Pressable>
            </View>
          ))}
          {pages > 1 ? (
            <View style={styles.pager}>
              <BmBtn label="‹ Prev" kind="ghost" small onPress={() => setPage(Math.max(1, page - 1))} />
              <Text style={styles.pagerTxt}>Page {page} / {pages}</Text>
              <BmBtn label="Next ›" kind="ghost" small onPress={() => setPage(Math.min(pages, page + 1))} />
            </View>
          ) : null}
        </>
      )}
    </View>
  );
}

/* ---------------- assign existing (unassigned/other) employees -------- */

function AssignPanel({ branch, companyId, onDone }: {
  branch: any; companyId: string; onDone: () => void;
}) {
  const [all, setAll] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  useEffect(() => {
    api<{ employees: any[] }>(`/admin/branch-management/employees?company_id=${companyId}`)
      .then((r) => setAll((r.employees || []).filter((e) => e.home_branch_id !== branch.branch_id)))
      .catch(() => {});
  }, [companyId, branch.branch_id]);

  const filtered = all.filter((e) =>
    !q.trim() || (e.name || "").toLowerCase().includes(q.toLowerCase())
    || (e.employee_code || "").toLowerCase().includes(q.toLowerCase())).slice(0, 25);

  const assign = async (e: any) => {
    setBusyId(e.user_id);
    try {
      // Immediate assignment via effective-dated transfer (today) so branch
      // history is preserved automatically.
      const today = new Date().toISOString().slice(0, 10);
      await api("/admin/branch-master/transfer", {
        method: "POST",
        body: { user_ids: [e.user_id], new_branch_id: branch.branch_id,
                effective_date: today, reason: "Assigned from Branch Master" },
      });
      setAll((prev) => prev.filter((x) => x.user_id !== e.user_id));
      onDone();
    } catch (er: any) { showWebMsg(er?.message || "Assign failed"); }
    finally { setBusyId(null); }
  };

  return (
    <View style={styles.panel} testID="be-assign-panel">
      <Text style={styles.panelTitle}>Assign employee to {branch.name}</Text>
      <BmField label="Search employee" value={q} onChangeText={setQ}
               placeholder="Name or code…" testID="be-assign-search" />
      {filtered.map((e) => (
        <View key={e.user_id} style={styles.eRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.eName}>{e.employee_code ? `${e.employee_code} · ` : ""}{e.name}</Text>
            <Text style={styles.eMeta}>{e.home_branch_id ? "Currently in another branch" : "Unassigned (Main)"}</Text>
          </View>
          <BmBtn label="Assign" small busy={busyId === e.user_id}
                 onPress={() => assign(e)} testID={`be-assign-${e.user_id}`} />
        </View>
      ))}
      {filtered.length === 0 ? <Text style={styles.eMeta}>No matching employees.</Text> : null}
    </View>
  );
}

/* ---------------- controlled transfer (single/bulk) ------------------- */

function TransferPanel({ userIds, branch, branches, onDone, onCancel }: {
  userIds: string[];
  branch: any;
  branches: Branch[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const [target, setTarget] = useState<string>("");
  const [eff, setEff] = useState(new Date().toISOString().slice(0, 10));
  const [reason, setReason] = useState("");
  const [remarks, setRemarks] = useState("");
  const [busy, setBusy] = useState(false);

  const confirm = async () => {
    if (!target) { showWebMsg("Target branch चुनें"); return; }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(eff)) { showWebMsg("Effective date YYYY-MM-DD format में दें"); return; }
    setBusy(true);
    try {
      const r = await api<{ created: number }>("/admin/branch-master/transfer", {
        method: "POST",
        body: { user_ids: userIds, new_branch_id: target,
                effective_date: eff, reason: reason.trim() || null,
                remarks: remarks.trim() || null },
      });
      showWebMsg(`Transfer created for ${r.created} employee(s) ✓\nEffective ${eff} — branch history automatically save हो गई. पुराने payroll/attendance records untouched.`);
      onDone();
    } catch (e: any) { showWebMsg(e?.message || "Transfer failed"); }
    finally { setBusy(false); }
  };

  return (
    <View style={styles.panel} testID="be-transfer-panel">
      <Text style={styles.panelTitle}>
        Transfer {userIds.length} employee(s) from {branch.name}
      </Text>
      <Text style={styles.panelLbl}>New Branch</Text>
      <View style={bm.chipsWrap}>
        {branches.map((b) => (
          <BmChip key={b.branch_id} label={`${b.name}${b.code ? ` (${b.code})` : ""}`}
                  on={target === b.branch_id}
                  onPress={() => setTarget(b.branch_id)}
                  testID={`be-target-${b.branch_id}`} />
        ))}
      </View>
      <View style={[bm.row, { marginTop: 8 }]}>
        <BmField label="Effective Date (YYYY-MM-DD)" value={eff} onChangeText={setEff}
                 width={190} testID="be-eff-date" />
        <BmField label="Transfer Reason" value={reason} onChangeText={setReason}
                 placeholder="e.g. Site requirement" testID="be-reason" />
        <BmField label="Remarks" value={remarks} onChangeText={setRemarks} />
      </View>
      <View style={{ flexDirection: "row", gap: 8, justifyContent: "flex-end" }}>
        <BmBtn label="Cancel" kind="ghost" onPress={onCancel} />
        <BmBtn label="Confirm Transfer" onPress={confirm} busy={busy} testID="be-confirm-transfer" />
      </View>
    </View>
  );
}

/* ---------------- employee branch-history timeline -------------------- */

function EmployeeHistory({ emp, onClose }: { emp: any; onClose: () => void }) {
  const [data, setData] = useState<any>(null);
  useEffect(() => {
    api<any>(`/admin/branch-master/employee-history/${emp.user_id}`)
      .then(setData).catch(() => setData({ timeline: [] }));
  }, [emp.user_id]);
  return (
    <View style={styles.panel} testID="be-history-panel">
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <Text style={styles.panelTitle}>Branch History — {emp.name}</Text>
        <Pressable onPress={onClose}>
          <Ionicons name="close" size={18} color={colors.onSurfaceSecondary} />
        </Pressable>
      </View>
      {!data ? <ActivityIndicator color={colors.brandPrimary} /> :
        (data.timeline || []).map((t: any, i: number) => (
          <View key={i} style={styles.tlRow}>
            <Ionicons name="location-outline" size={14}
                      color={t.to == null ? "#15803D" : colors.onSurfaceTertiary} />
            <Text style={styles.tlTxt}>
              {t.from || "Joining"} → {t.to || "Present"} : <Text style={{ fontWeight: "800" }}>{t.branch}</Text>
              {t.next_reason ? `  (next: ${t.next_reason})` : ""}
            </Text>
          </View>
        ))}
    </View>
  );
}

const styles = StyleSheet.create({
  toolbar: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 },
  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 6, flex: 1, minWidth: 180,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 9, paddingVertical: 6, backgroundColor: colors.surfaceSecondary,
  },
  searchInput: { flex: 1, fontSize: 12.5, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" } as any : {}) },
  totalTxt: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceTertiary, marginBottom: 6 },
  eRow: {
    flexDirection: "row", alignItems: "center", gap: 9,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 8, marginBottom: 5,
    backgroundColor: colors.surfaceSecondary,
  },
  eName: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  eMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 1 },
  histBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 10,
    paddingHorizontal: 8, paddingVertical: 4,
  },
  histBtnTxt: { fontSize: 10.5, fontWeight: "800", color: colors.brandPrimary },
  pager: { flexDirection: "row", alignItems: "center", gap: 10, justifyContent: "center", marginTop: 8 },
  pagerTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  panel: {
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    padding: spacing.sm, marginBottom: spacing.sm, backgroundColor: colors.surface,
  },
  panelTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  panelLbl: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  tlRow: { flexDirection: "row", alignItems: "center", gap: 7, paddingVertical: 4 },
  tlTxt: { fontSize: 12, color: colors.onSurface },
});
