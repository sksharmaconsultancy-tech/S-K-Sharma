/**
 * Iter 581 — Attendance Eligibility (Onboarding Gate) — HR dashboard.
 *
 * Lists employees whose punches are HELD (inside the permission window)
 * or BLOCKED (window over) because mandatory onboarding data (Aadhaar /
 * Bank / PAN / Photo) is missing. HR can:
 *   • Release punches (reason MANDATORY when any punch is BLOCKED)
 *   • Reject punches (reason always mandatory)
 * Raw punches are never deleted.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing } from "@/src/theme";
import CompanyPicker from "@/src/components/CompanyPicker";

type EmpRow = {
  user_id: string;
  name?: string;
  employee_code?: string;
  held_count: number;
  blocked_count: number;
  first_date: string;
  last_date: string;
  missing: { key: string; label: string }[];
  data_complete: boolean;
  days_left?: number | null;
  deadline?: string | null;
};

type PunchRec = {
  record_id: string;
  date: string;
  kind: string;
  at: string;
  status: string;
  source?: string;
  eligibility_missing?: string[];
  missing_labels?: string[];
};

export default function AttendanceEligibilityScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { companies, selectedCompanyId } = useSelectedCompany();
  const isScoped = user?.role === "company_admin";
  const [firmId, setFirmId] = useState<string>("");
  const cid = isScoped ? user?.company_id || "" : firmId || selectedCompanyId || "";

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [gate, setGate] = useState<any>(null);
  const [rows, setRows] = useState<EmpRow[]>([]);
  const [totals, setTotals] = useState<{ held: number; blocked: number } | null>(null);
  const [onboardingStats, setOnboardingStats] = useState<any>(null);

  // Expanded employee → their held/blocked punch list.
  const [openUid, setOpenUid] = useState<string | null>(null);
  const [recs, setRecs] = useState<PunchRec[]>([]);
  const [recsLoading, setRecsLoading] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Release / reject modal.
  const [action, setAction] = useState<null | { mode: "release" | "reject"; hasBlocked: boolean }>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const showToast = (m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    if (!cid) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api<any>(`/admin/attendance-eligibility/summary?company_id=${cid}`);
      setGate(r.gate);
      setRows(r.employees || []);
      setTotals(r.totals || null);
      setOnboardingStats(r.onboarding || null);
    } catch (e: any) {
      setError(e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [cid]);

  useEffect(() => {
    void load();
    setOpenUid(null);
    setRecs([]);
    setSelected(new Set());
  }, [load]);

  const openEmployee = async (uid: string) => {
    if (openUid === uid) {
      setOpenUid(null);
      setRecs([]);
      setSelected(new Set());
      return;
    }
    setOpenUid(uid);
    setRecs([]);
    setSelected(new Set());
    setRecsLoading(true);
    try {
      const r = await api<{ records: PunchRec[] }>(
        `/admin/attendance-eligibility/records?company_id=${cid}&user_id=${uid}`,
      );
      setRecs(r.records || []);
    } catch (e: any) {
      showToast(e.message || "Failed to load punches");
    } finally {
      setRecsLoading(false);
    }
  };

  const toggleSel = (rid: string) => {
    const s = new Set(selected);
    if (s.has(rid)) s.delete(rid);
    else s.add(rid);
    setSelected(s);
  };

  const startAction = (mode: "release" | "reject") => {
    const ids = selected.size > 0 ? Array.from(selected) : recs.map((r) => r.record_id);
    if (ids.length === 0) {
      showToast("No punches selected");
      return;
    }
    const hasBlocked = recs.some((r) => ids.includes(r.record_id) && r.status === "blocked");
    setReason("");
    setAction({ mode, hasBlocked });
  };

  const submitAction = async () => {
    if (!action || !openUid) return;
    const ids = selected.size > 0 ? Array.from(selected) : recs.map((r) => r.record_id);
    const needReason = action.mode === "reject" || action.hasBlocked;
    if (needReason && !reason.trim()) {
      showToast(
        action.mode === "reject"
          ? "Rejection reason is mandatory."
          : "Release reason is MANDATORY for BLOCKED punches.",
      );
      return;
    }
    setSaving(true);
    try {
      const r = await api<any>(
        `/admin/attendance-eligibility/${action.mode}?company_id=${cid}`,
        { method: "POST", body: { record_ids: ids, reason: reason.trim() } },
      );
      showToast(
        action.mode === "release"
          ? `Released ${r.released} punch${r.released === 1 ? "" : "es"}`
          : `Rejected ${r.rejected} punch${r.rejected === 1 ? "" : "es"}`,
      );
      setAction(null);
      setOpenUid(null);
      setRecs([]);
      setSelected(new Set());
      await load();
    } catch (e: any) {
      showToast(e.message || "Action failed");
    } finally {
      setSaving(false);
    }
  };

  const missingChips = (missing: { key: string; label: string }[]) => (
    <View style={styles.chipsWrap}>
      {missing.map((m) => (
        <View key={m.key} style={styles.missChip}>
          <Text style={styles.missChipTxt}>{m.label}</Text>
        </View>
      ))}
    </View>
  );

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="ae-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>Attendance Eligibility</Text>
          <Text style={styles.sub}>Held / blocked punches — onboarding gate</Text>
        </View>
        <Pressable onPress={() => void load()} style={styles.backBtn} testID="ae-refresh">
          <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        {!isScoped ? (
          <CompanyPicker
            value={cid || ""}
            onChange={(v: string) => setFirmId(v)}
            companies={companies}
            label="Firm"
            testID="ae-firm-dd"
          />
        ) : null}

        {gate && !gate.enabled ? (
          <View style={styles.infoCard}>
            <Ionicons name="information-circle-outline" size={18} color={colors.brandPrimary} />
            <Text style={styles.infoTxt}>
              The Onboarding Gate is OFF for this firm. Enable it in Attendance
              Policy → Employee Onboarding Gate. Existing held/blocked punches
              (if any) are listed below.
            </Text>
          </View>
        ) : null}

        {totals ? (
          <View style={styles.totalsRow}>
            <View style={[styles.totCard, { borderColor: "#FDE68A", backgroundColor: "#FFFBEB" }]}>
              <Text style={[styles.totNum, { color: "#B45309" }]}>{totals.held}</Text>
              <Text style={styles.totLbl}>Held</Text>
            </View>
            <View style={[styles.totCard, { borderColor: "#FECACA", backgroundColor: "#FEF2F2" }]}>
              <Text style={[styles.totNum, { color: "#B91C1C" }]}>{totals.blocked}</Text>
              <Text style={styles.totLbl}>Blocked</Text>
            </View>
            <View style={styles.totCard}>
              <Text style={styles.totNum}>{rows.length}</Text>
              <Text style={styles.totLbl}>Employees</Text>
            </View>
          </View>
        ) : null}

        {/* Iter 582 — firm-wide onboarding completion widget */}
        {onboardingStats ? (
          <View style={styles.obCard} testID="ae-onboarding-widget">
            <View style={styles.obHead}>
              <Ionicons name="clipboard-outline" size={16} color={colors.brandPrimary} />
              <Text style={styles.obTitle}>Onboarding Completion</Text>
              <Text
                style={[
                  styles.obPct,
                  { color: onboardingStats.pct >= 80 ? "#16A34A" : onboardingStats.pct >= 50 ? "#B45309" : "#B91C1C" },
                ]}
              >
                {onboardingStats.pct}%
              </Text>
            </View>
            <View style={styles.obTrack}>
              <View
                style={[
                  styles.obFill,
                  {
                    width: `${Math.min(onboardingStats.pct, 100)}%`,
                    backgroundColor:
                      onboardingStats.pct >= 80 ? "#16A34A" : onboardingStats.pct >= 50 ? "#F59E0B" : "#DC2626",
                  },
                ]}
              />
            </View>
            <Text style={styles.obSub}>
              {onboardingStats.complete} of {onboardingStats.total_employees} employees have
              all mandatory data ({(onboardingStats.required_items || []).join(", ")}).
              {onboardingStats.incomplete > 0 ? ` ${onboardingStats.incomplete} incomplete.` : ""}
            </Text>
          </View>
        ) : null}

        {loading ? (
          <ActivityIndicator style={{ marginTop: 30 }} color={colors.brandPrimary} />
        ) : error ? (
          <Text style={styles.err}>{error}</Text>
        ) : !cid ? (
          <Text style={styles.empty}>Select a firm to view held/blocked attendance.</Text>
        ) : rows.length === 0 ? (
          <View style={styles.emptyCard} testID="ae-empty">
            <Ionicons name="checkmark-done-circle-outline" size={34} color="#16A34A" />
            <Text style={styles.emptyTitle}>All clear</Text>
            <Text style={styles.empty}>No held or blocked punches for this firm.</Text>
          </View>
        ) : (
          rows.map((r) => (
            <View key={r.user_id} style={styles.empCard} testID={`ae-emp-${r.user_id}`}>
              <Pressable style={styles.empHead} onPress={() => void openEmployee(r.user_id)}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.empName}>
                    {r.name || "Employee"}
                    {r.employee_code ? `  ·  ${r.employee_code}` : ""}
                  </Text>
                  <Text style={styles.empSub}>
                    {r.first_date === r.last_date ? r.first_date : `${r.first_date} → ${r.last_date}`}
                  </Text>
                  {r.data_complete ? (
                    <Text style={[styles.empSub, { color: "#16A34A", fontWeight: "700" }]}>
                      ✓ Data now complete — ready to release
                    </Text>
                  ) : (
                    missingChips(r.missing)
                  )}
                </View>
                <View style={{ alignItems: "flex-end", gap: 4 }}>
                  {r.held_count > 0 ? (
                    <View style={[styles.pill, { backgroundColor: "#FFFBEB", borderColor: "#FDE68A" }]}>
                      <Text style={[styles.pillTxt, { color: "#B45309" }]}>{r.held_count} held</Text>
                    </View>
                  ) : null}
                  {r.blocked_count > 0 ? (
                    <View style={[styles.pill, { backgroundColor: "#FEF2F2", borderColor: "#FECACA" }]}>
                      <Text style={[styles.pillTxt, { color: "#B91C1C" }]}>{r.blocked_count} blocked</Text>
                    </View>
                  ) : null}
                  <Ionicons
                    name={openUid === r.user_id ? "chevron-up" : "chevron-down"}
                    size={16}
                    color={colors.onSurfaceTertiary}
                  />
                </View>
              </Pressable>

              {openUid === r.user_id ? (
                <View style={styles.recsWrap}>
                  {recsLoading ? (
                    <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 10 }} />
                  ) : (
                    <>
                      {recs.map((p) => {
                        const sel = selected.has(p.record_id);
                        return (
                          <Pressable
                            key={p.record_id}
                            style={[styles.recRow, sel && styles.recRowSel]}
                            onPress={() => toggleSel(p.record_id)}
                            testID={`ae-rec-${p.record_id}`}
                          >
                            <Ionicons
                              name={sel ? "checkbox" : "square-outline"}
                              size={18}
                              color={sel ? colors.brandPrimary : colors.onSurfaceTertiary}
                            />
                            <View style={{ flex: 1 }}>
                              <Text style={styles.recMain}>
                                {p.date} · {(p.kind || "").toUpperCase()} · {(p.at || "").slice(11, 16)}
                              </Text>
                              <Text style={styles.recSub}>
                                {p.source || "app"}
                                {(p.missing_labels || []).length
                                  ? ` · missing: ${(p.missing_labels || []).join(", ")}`
                                  : ""}
                              </Text>
                            </View>
                            <View
                              style={[
                                styles.pill,
                                p.status === "blocked"
                                  ? { backgroundColor: "#FEF2F2", borderColor: "#FECACA" }
                                  : { backgroundColor: "#FFFBEB", borderColor: "#FDE68A" },
                              ]}
                            >
                              <Text
                                style={[
                                  styles.pillTxt,
                                  { color: p.status === "blocked" ? "#B91C1C" : "#B45309" },
                                ]}
                              >
                                {p.status.toUpperCase()}
                              </Text>
                            </View>
                          </Pressable>
                        );
                      })}
                      <Text style={styles.selHint}>
                        {selected.size > 0
                          ? `${selected.size} selected`
                          : "No selection — actions apply to ALL listed punches"}
                      </Text>
                      <View style={styles.actionsRow}>
                        <Pressable
                          style={[styles.actBtn, { backgroundColor: "#16A34A" }]}
                          onPress={() => startAction("release")}
                          testID="ae-release-btn"
                        >
                          <Ionicons name="checkmark-circle-outline" size={16} color="#fff" />
                          <Text style={styles.actTxt}>Release</Text>
                        </Pressable>
                        <Pressable
                          style={[styles.actBtn, { backgroundColor: "#DC2626" }]}
                          onPress={() => startAction("reject")}
                          testID="ae-reject-btn"
                        >
                          <Ionicons name="close-circle-outline" size={16} color="#fff" />
                          <Text style={styles.actTxt}>Reject</Text>
                        </Pressable>
                      </View>
                    </>
                  )}
                </View>
              ) : null}
            </View>
          ))
        )}
      </ScrollView>

      {/* Release / Reject reason modal */}
      <Modal visible={!!action} transparent animationType="fade" onRequestClose={() => setAction(null)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>
              {action?.mode === "release" ? "Release punches" : "Reject punches"}
            </Text>
            <Text style={styles.modalSub}>
              {action?.mode === "reject"
                ? "Rejection reason is mandatory."
                : action?.hasBlocked
                ? "Selection includes BLOCKED punches — an authenticated release reason is MANDATORY."
                : "Reason (optional for held punches)."}
            </Text>
            <TextInput
              style={styles.reasonInput}
              placeholder="Reason…"
              placeholderTextColor={colors.onSurfaceTertiary}
              value={reason}
              onChangeText={setReason}
              multiline
              testID="ae-reason-input"
            />
            <View style={styles.actionsRow}>
              <Pressable style={[styles.actBtn, { backgroundColor: colors.surfaceSecondary }]} onPress={() => setAction(null)}>
                <Text style={[styles.actTxt, { color: colors.onSurface }]}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[
                  styles.actBtn,
                  { backgroundColor: action?.mode === "release" ? "#16A34A" : "#DC2626" },
                  saving && { opacity: 0.6 },
                ]}
                onPress={() => void submitAction()}
                disabled={saving}
                testID="ae-confirm-btn"
              >
                <Text style={styles.actTxt}>{saving ? "Saving…" : "Confirm"}</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {toast ? (
        <View style={styles.toast} testID="ae-toast">
          <Text style={styles.toastTxt}>{toast}</Text>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  backBtn: { padding: 6 },
  h1: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: 1 },
  scroll: { padding: spacing.lg, paddingBottom: 60, gap: 10 },
  infoCard: {
    flexDirection: "row", gap: 8, alignItems: "flex-start",
    backgroundColor: colors.surfaceSecondary, borderWidth: 1,
    borderColor: colors.border, borderRadius: radius.md, padding: 12,
  },
  infoTxt: { flex: 1, fontSize: 12, color: colors.onSurfaceSecondary, lineHeight: 17 },
  totalsRow: { flexDirection: "row", gap: 10 },
  totCard: {
    flex: 1, alignItems: "center", paddingVertical: 12,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
  },
  totNum: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  totLbl: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  obCard: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg,
    backgroundColor: colors.surfaceSecondary, padding: 12, gap: 8,
  },
  obHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  obTitle: { flex: 1, fontSize: 13, fontWeight: "800", color: colors.onSurface },
  obPct: { fontSize: 16, fontWeight: "800" },
  obTrack: {
    height: 8, borderRadius: 4, backgroundColor: colors.border, overflow: "hidden",
  },
  obFill: { height: 8, borderRadius: 4 },
  obSub: { fontSize: 11.5, color: colors.onSurfaceSecondary, lineHeight: 16 },
  err: { color: "#DC2626", marginTop: 20, textAlign: "center" },
  empty: { color: colors.onSurfaceTertiary, textAlign: "center", fontSize: 12.5 },
  emptyCard: { alignItems: "center", gap: 6, paddingVertical: 40 },
  emptyTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  empCard: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg,
    backgroundColor: colors.surfaceSecondary, overflow: "hidden",
  },
  empHead: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12 },
  empName: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  empSub: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 2 },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 },
  missChip: {
    backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FECACA",
    borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3,
  },
  missChipTxt: { fontSize: 10.5, fontWeight: "700", color: "#B91C1C" },
  pill: {
    borderWidth: 1, borderRadius: 999,
    paddingHorizontal: 8, paddingVertical: 3,
  },
  pillTxt: { fontSize: 10.5, fontWeight: "800" },
  recsWrap: {
    borderTopWidth: 1, borderTopColor: colors.border,
    padding: 10, gap: 6, backgroundColor: colors.surface,
  },
  recRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: 8, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
  },
  recRowSel: { borderColor: colors.brandPrimary, backgroundColor: "#F0F9FF" },
  recMain: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  recSub: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 1 },
  selHint: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 4 },
  actionsRow: { flexDirection: "row", gap: 10, marginTop: 8 },
  actBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, borderRadius: radius.md, paddingVertical: 11, minHeight: 44,
  },
  actTxt: { color: "#fff", fontSize: 13, fontWeight: "800" },
  modalBg: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.45)",
    alignItems: "center", justifyContent: "center", padding: 20,
  },
  modalCard: {
    width: "100%", maxWidth: 440, backgroundColor: colors.surface,
    borderRadius: radius.lg, padding: 18, gap: 8,
  },
  modalTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  modalSub: { fontSize: 12, color: colors.onSurfaceSecondary, lineHeight: 17 },
  reasonInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    minHeight: 70, padding: 10, color: colors.onSurface, fontSize: 13,
    textAlignVertical: "top", backgroundColor: colors.surfaceSecondary,
  },
  toast: {
    position: "absolute", bottom: 24, left: 20, right: 20,
    backgroundColor: "#111827", borderRadius: radius.md, padding: 12,
  },
  toastTxt: { color: "#fff", fontSize: 12.5, textAlign: "center" },
});
