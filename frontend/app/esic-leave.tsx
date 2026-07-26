/**
 * ESIC Leave Module — Iter 313.
 *
 * Workflow: HR enters ESIC Leave period (From–To) → uploads medical
 * certificate → HR/Compliance approves → attendance auto-marked (approved
 * "esic" leave) → Compliance Salary Process auto-imports the days →
 * Salary Register shows ESIC Leave separately.
 *
 * Per-firm settings: enable module · link with compliance · auto-mark
 * attendance · lock after payroll freeze · require certificate ·
 * backdated entry limit · separate Salary Register column.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Switch,
  Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, shadow, spacing } from "@/src/theme";

const BRAND = "#0F3B5C";
const ACCENT = "#B45309";

type Emp = { user_id: string; name?: string; employee_code?: string };
type Entry = {
  entry_id: string; user_id: string; employee_name?: string; employee_code?: string;
  esi_ip_no?: string; from_date: string; to_date: string; days: number;
  remarks?: string; has_certificate?: boolean; certificate_name?: string;
  status: "pending" | "approved" | "rejected";
  created_by_name?: string; approved_by_name?: string; reject_reason?: string;
};
type Settings = {
  enabled: boolean; link_compliance: boolean; auto_mark_attendance: boolean;
  lock_after_freeze: boolean; require_certificate: boolean;
  allow_backdated: boolean; max_backdate_days: number;
  show_separate_register: boolean;
};

const SETTING_ROWS: { key: keyof Settings; label: string }[] = [
  { key: "enabled", label: "Enable ESIC Leave Module" },
  { key: "link_compliance", label: "Link ESIC Leave with Compliance Salary Process" },
  { key: "auto_mark_attendance", label: "Auto-mark Attendance as ESIC Leave" },
  { key: "lock_after_freeze", label: "Lock Attendance after Payroll Freeze" },
  { key: "require_certificate", label: "Require Medical Certificate" },
  { key: "allow_backdated", label: "Allow Backdated ESIC Leave Entry" },
  { key: "show_separate_register", label: "Show ESIC Leave Separately on Salary Register" },
];

const STATUS_COLORS: Record<string, { bg: string; fg: string }> = {
  pending: { bg: "#FEF3C7", fg: "#92400E" },
  approved: { bg: "#DCFCE7", fg: "#166534" },
  rejected: { bg: "#FEE2E2", fg: "#991B1B" },
};

export default function EsicLeaveScreen() {
  const { user } = useAuth();
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";
  const [companyId, setCompanyId] = useState<string | "all">(
    globalCid && globalCid !== "all" ? globalCid : "all");
  const cid = isSuper ? (companyId === "all" ? "" : companyId) : (user?.company_id || "");

  const [settings, setSettings] = useState<Settings | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);

  const [emps, setEmps] = useState<Emp[]>([]);
  const [empSearch, setEmpSearch] = useState("");
  const [selEmp, setSelEmp] = useState<Emp | null>(null);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [remarks, setRemarks] = useState("");
  const [cert, setCert] = useState<{ name: string; data: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [month, setMonth] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (globalCid && globalCid !== "all") setCompanyId(globalCid);
  }, [globalCid]);

  const flash = (ok: string | null, e?: string) => {
    if (ok) { setMsg(ok); setErr(""); } else { setErr(e || "Failed"); setMsg(""); }
    setTimeout(() => { setMsg(""); setErr(""); }, 5000);
  };

  // ---- loaders ----
  const loadAll = useCallback(async () => {
    if (!cid) { setSettings(null); setEntries([]); setEmps([]); return; }
    setLoading(true);
    try {
      const p = new URLSearchParams();
      p.set("company_id", cid);
      if (month.trim()) p.set("month", month.trim());
      if (statusFilter !== "all") p.set("status", statusFilter);
      const [st, list, el] = await Promise.all([
        api<{ settings: Settings }>(`/admin/esic-leave/settings?company_id=${cid}`),
        api<{ entries: Entry[] }>(`/admin/esic-leave?${p}`),
        api<{ employees: Emp[] }>(`/admin/employee-detail-slip/employees?company_id=${cid}`),
      ]);
      setSettings(st.settings);
      setEntries(list.entries || []);
      setEmps(el.employees || []);
    } catch (e: any) {
      flash(null, e?.message || "Failed to load ESIC Leave data");
    } finally { setLoading(false); }
  }, [cid, month, statusFilter]);
  useEffect(() => { loadAll(); }, [loadAll]);

  const filteredEmps = useMemo(() => {
    const s = empSearch.trim().toLowerCase();
    if (!s) return emps.slice(0, 40);
    return emps.filter((e) =>
      (e.name || "").toLowerCase().includes(s) ||
      String(e.employee_code || "").toLowerCase().includes(s)).slice(0, 40);
  }, [emps, empSearch]);

  // ---- actions ----
  const saveSettings = async () => {
    if (!cid || !settings) return;
    setSavingSettings(true);
    try {
      await api(`/admin/esic-leave/settings`, {
        method: "PUT", body: { company_id: cid, ...settings },
      });
      flash("Settings saved");
    } catch (e: any) { flash(null, e?.message); } finally { setSavingSettings(false); }
  };

  const pickCertificate = async () => {
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: ["application/pdf", "image/*"], copyToCacheDirectory: true,
      });
      if (res.canceled || !res.assets?.length) return;
      const a = res.assets[0];
      if ((a.size || 0) > 8 * 1024 * 1024) { flash(null, "File too large (max 8 MB)"); return; }
      const blob = await (await fetch(a.uri)).blob();
      const dataUrl: string = await new Promise((ok, bad) => {
        const r = new FileReader();
        r.onload = () => ok(r.result as string);
        r.onerror = bad;
        r.readAsDataURL(blob);
      });
      setCert({ name: a.name || "certificate", data: dataUrl });
    } catch (e: any) { flash(null, e?.message || "Could not read file"); }
  };

  const submitEntry = async () => {
    if (!cid || !selEmp) { flash(null, "Select an employee"); return; }
    if (!fromDate.trim() || !toDate.trim()) { flash(null, "Enter From & To dates (YYYY-MM-DD)"); return; }
    setSubmitting(true);
    try {
      await api(`/admin/esic-leave`, {
        method: "POST",
        body: {
          company_id: cid, user_id: selEmp.user_id,
          from_date: fromDate.trim(), to_date: toDate.trim(),
          remarks: remarks.trim() || undefined,
          certificate_base64: cert?.data, certificate_name: cert?.name,
        },
      });
      setSelEmp(null); setFromDate(""); setToDate(""); setRemarks(""); setCert(null);
      flash("ESIC Leave entry created (pending approval)");
      loadAll();
    } catch (e: any) { flash(null, e?.message); } finally { setSubmitting(false); }
  };

  const act = async (id: string, action: "approve" | "reject" | "delete") => {
    setBusyId(id);
    try {
      if (action === "delete") {
        await api(`/admin/esic-leave/${id}`, { method: "DELETE" });
      } else {
        await api(`/admin/esic-leave/${id}/${action}`, { method: "POST", body: {} });
      }
      flash(action === "approve" ? "Approved — attendance auto-marked"
        : action === "reject" ? "Rejected" : "Deleted");
      loadAll();
    } catch (e: any) { flash(null, e?.message); } finally { setBusyId(null); }
  };

  const viewCert = async (id: string) => {
    try {
      const res = await apiBinary(`/admin/esic-leave/${id}/certificate`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        window.open(res.webBlobUrl, "_blank");
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) { flash(null, e?.message); }
  };

  const dmy = (s?: string) => (s ? s.split("-").reverse().join("-") : "—");

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title}>ESIC Leave Module</Text>
        <Text style={styles.subtitle}>
          Medical-certificate leave · auto attendance marking · payroll linked
        </Text>

        {isSuper ? (
          <View style={styles.card}>
            <CompanyPicker value={companyId} onChange={setCompanyId} includeAll={false} />
          </View>
        ) : null}

        {msg ? <Text style={styles.msg}>{msg}</Text> : null}
        {err ? <Text style={styles.err}>{err}</Text> : null}

        {!cid ? (
          <Text style={styles.hint}>Select a firm to manage ESIC Leave.</Text>
        ) : (
          <>
            {/* Settings */}
            <View style={styles.card}>
              <Pressable style={styles.secToggle} onPress={() => setSettingsOpen((v) => !v)} testID="esic-settings-toggle">
                <Ionicons name="settings-outline" size={16} color={BRAND} />
                <Text style={styles.secToggleTxt}>Module Settings</Text>
                <Ionicons name={settingsOpen ? "chevron-up" : "chevron-down"} size={16} color={colors.onSurfaceSecondary} />
              </Pressable>
              {settingsOpen && settings ? (
                <View style={{ marginTop: 8 }}>
                  {SETTING_ROWS.map((r) => (
                    <View key={r.key} style={styles.setRow}>
                      <Text style={styles.setLbl}>{r.label}</Text>
                      <Switch
                        value={!!settings[r.key]}
                        onValueChange={(v) => setSettings((s) => (s ? { ...s, [r.key]: v } : s))}
                        trackColor={{ true: BRAND, false: "#CBD5E1" }}
                        thumbColor="#fff"
                        testID={`esic-set-${r.key}`}
                      />
                    </View>
                  ))}
                  {settings.allow_backdated ? (
                    <View style={styles.setRow}>
                      <Text style={styles.setLbl}>Maximum Backdated Days</Text>
                      <TextInput
                        value={String(settings.max_backdate_days ?? 0)}
                        onChangeText={(v) => setSettings((s) => (s ? { ...s, max_backdate_days: Number(v.replace(/[^0-9]/g, "")) || 0 } : s))}
                        keyboardType="numeric"
                        style={styles.numInput}
                        testID="esic-set-maxdays"
                      />
                    </View>
                  ) : null}
                  <Pressable onPress={saveSettings} style={styles.primaryBtn} disabled={savingSettings} testID="esic-settings-save">
                    {savingSettings ? <ActivityIndicator size="small" color="#fff" /> : (
                      <Text style={styles.primaryBtnTxt}>Save Settings</Text>
                    )}
                  </Pressable>
                </View>
              ) : null}
            </View>

            {/* New entry */}
            <View style={styles.card}>
              <Text style={styles.cardTitle}>
                <Ionicons name="medkit-outline" size={14} color={ACCENT} />  New ESIC Leave Entry
              </Text>
              <View style={styles.searchRow}>
                <Ionicons name="search-outline" size={14} color={colors.onSurfaceTertiary} />
                <TextInput
                  value={selEmp ? `${selEmp.employee_code || ""} · ${selEmp.name || ""}` : empSearch}
                  onChangeText={(v) => { setSelEmp(null); setEmpSearch(v); }}
                  placeholder="Search employee by name or code…"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.searchInput}
                  testID="esic-emp-search"
                />
                {selEmp ? (
                  <Pressable onPress={() => { setSelEmp(null); setEmpSearch(""); }} hitSlop={6}>
                    <Ionicons name="close-circle" size={16} color={colors.onSurfaceTertiary} />
                  </Pressable>
                ) : null}
              </View>
              {!selEmp ? (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
                  <View style={{ flexDirection: "row", gap: 6 }}>
                    {filteredEmps.map((e) => (
                      <Pressable key={e.user_id} onPress={() => setSelEmp(e)} style={styles.chip} testID={`esic-emp-${e.employee_code || e.user_id}`}>
                        <Text style={styles.chipTxt} numberOfLines={1}>
                          {e.employee_code ? `${e.employee_code} · ` : ""}{e.name || "—"}
                        </Text>
                      </Pressable>
                    ))}
                  </View>
                </ScrollView>
              ) : null}
              <View style={styles.dateRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.fieldLbl}>From (YYYY-MM-DD)</Text>
                  <TextInput value={fromDate} onChangeText={setFromDate} placeholder="2026-07-01"
                    placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} testID="esic-from" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.fieldLbl}>To (YYYY-MM-DD)</Text>
                  <TextInput value={toDate} onChangeText={setToDate} placeholder="2026-07-05"
                    placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} testID="esic-to" />
                </View>
              </View>
              <Text style={styles.fieldLbl}>Remarks</Text>
              <TextInput value={remarks} onChangeText={setRemarks} placeholder="Sickness / accident details…"
                placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} testID="esic-remarks" />
              <View style={{ flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                <Pressable onPress={pickCertificate} style={styles.outlineBtn} testID="esic-attach">
                  <Ionicons name="attach-outline" size={15} color={BRAND} />
                  <Text style={styles.outlineBtnTxt} numberOfLines={1}>
                    {cert ? cert.name : "Attach Medical Certificate"}
                  </Text>
                </Pressable>
                <Pressable onPress={submitEntry} style={[styles.primaryBtn, { marginTop: 0, flexGrow: 1 }]} disabled={submitting} testID="esic-submit">
                  {submitting ? <ActivityIndicator size="small" color="#fff" /> : (
                    <Text style={styles.primaryBtnTxt}>Submit ESIC Leave</Text>
                  )}
                </Pressable>
              </View>
              {settings?.require_certificate ? (
                <Text style={styles.hintSmall}>
                  ⚠ Medical certificate is required before approval (firm setting).
                </Text>
              ) : null}
            </View>

            {/* Filters + list */}
            <View style={styles.card}>
              <Text style={styles.cardTitle}>
                <Ionicons name="list-outline" size={14} color={BRAND} />  ESIC Leave Register
              </Text>
              <View style={{ flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <TextInput value={month} onChangeText={setMonth} placeholder="Month (YYYY-MM)"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={[styles.input, { width: 150, marginTop: 0 }]} testID="esic-month" />
                {["all", "pending", "approved", "rejected"].map((s) => (
                  <Pressable key={s} onPress={() => setStatusFilter(s)}
                    style={[styles.chip, statusFilter === s && { backgroundColor: BRAND, borderColor: BRAND }]}
                    testID={`esic-filter-${s}`}>
                    <Text style={[styles.chipTxt, statusFilter === s && { color: "#fff" }]}>{s.toUpperCase()}</Text>
                  </Pressable>
                ))}
              </View>

              {loading ? <ActivityIndicator style={{ marginTop: 16 }} color={BRAND} /> : null}
              {!loading && !entries.length ? (
                <Text style={styles.hintSmall}>No ESIC Leave entries found.</Text>
              ) : null}
              {entries.map((e) => {
                const sc = STATUS_COLORS[e.status] || STATUS_COLORS.pending;
                return (
                  <View key={e.entry_id} style={styles.entryRow}>
                    <View style={{ flex: 1, minWidth: 200 }}>
                      <Text style={styles.entryName}>
                        {e.employee_code ? `${e.employee_code} · ` : ""}{e.employee_name || e.user_id}
                      </Text>
                      <Text style={styles.entryMeta}>
                        {dmy(e.from_date)} → {dmy(e.to_date)} · {e.days} day(s){e.esi_ip_no ? ` · IP ${e.esi_ip_no}` : ""}
                      </Text>
                      {e.remarks ? <Text style={styles.entryMeta} numberOfLines={1}>“{e.remarks}”</Text> : null}
                      {e.status === "rejected" && e.reject_reason ? (
                        <Text style={[styles.entryMeta, { color: "#991B1B" }]}>Reason: {e.reject_reason}</Text>
                      ) : null}
                    </View>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      {e.has_certificate ? (
                        <Pressable onPress={() => viewCert(e.entry_id)} style={styles.certBadge} testID={`esic-cert-${e.entry_id}`}>
                          <Ionicons name="document-attach-outline" size={13} color="#0369A1" />
                          <Text style={{ fontSize: 10.5, fontWeight: "700", color: "#0369A1" }}>Certificate</Text>
                        </Pressable>
                      ) : (
                        <View style={[styles.certBadge, { backgroundColor: "#FEF2F2" }]}>
                          <Ionicons name="alert-circle-outline" size={13} color="#B91C1C" />
                          <Text style={{ fontSize: 10.5, fontWeight: "700", color: "#B91C1C" }}>No cert</Text>
                        </View>
                      )}
                      <View style={[styles.statusChip, { backgroundColor: sc.bg }]}>
                        <Text style={{ fontSize: 10.5, fontWeight: "800", color: sc.fg }}>{e.status.toUpperCase()}</Text>
                      </View>
                      {busyId === e.entry_id ? <ActivityIndicator size="small" color={BRAND} /> : (
                        <>
                          {e.status === "pending" ? (
                            <>
                              <Pressable onPress={() => act(e.entry_id, "approve")} style={[styles.miniBtn, { backgroundColor: "#166534" }]} testID={`esic-approve-${e.entry_id}`}>
                                <Text style={styles.miniBtnTxt}>Approve</Text>
                              </Pressable>
                              <Pressable onPress={() => act(e.entry_id, "reject")} style={[styles.miniBtn, { backgroundColor: "#B91C1C" }]} testID={`esic-reject-${e.entry_id}`}>
                                <Text style={styles.miniBtnTxt}>Reject</Text>
                              </Pressable>
                            </>
                          ) : null}
                          <Pressable onPress={() => act(e.entry_id, "delete")} style={[styles.miniBtn, { backgroundColor: "#64748B" }]} testID={`esic-delete-${e.entry_id}`}>
                            <Ionicons name="trash-outline" size={13} color="#fff" />
                          </Pressable>
                        </>
                      )}
                    </View>
                  </View>
                );
              })}
            </View>

            {/* Workflow strip */}
            <View style={[styles.card, { backgroundColor: "#F0F7FF" }]}>
              <Text style={{ fontSize: 11.5, color: "#0C4A6E", fontWeight: "600", lineHeight: 18 }}>
                Certificate → ESIC Leave period → Approval → Attendance auto-marked →
                Compliance Salary Process imports ESIC leave → Freeze → PF / ESIC → Salary Sheet
              </Text>
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: spacing.md, paddingBottom: 60 },
  title: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2, marginBottom: spacing.sm },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm, ...shadow.sm,
  },
  cardTitle: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  msg: { color: "#166534", fontSize: 12, fontWeight: "700", marginBottom: 6 },
  err: { color: "#B91C1C", fontSize: 12, fontWeight: "700", marginBottom: 6 },
  hint: { textAlign: "center", marginTop: 24, color: colors.onSurfaceTertiary },
  hintSmall: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 8 },
  secToggle: { flexDirection: "row", alignItems: "center", gap: 8 },
  secToggleTxt: { flex: 1, fontSize: 13.5, fontWeight: "800", color: BRAND },
  setRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 7, borderBottomWidth: 0.5, borderBottomColor: colors.border,
  },
  setLbl: { flex: 1, fontSize: 12.5, color: colors.onSurface, fontWeight: "600", paddingRight: 8 },
  numInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8, width: 70,
    paddingHorizontal: 8, paddingVertical: 5, fontSize: 13, textAlign: "center",
    color: colors.onSurface,
  },
  primaryBtn: {
    backgroundColor: BRAND, borderRadius: 10, paddingVertical: 11,
    alignItems: "center", marginTop: 12, paddingHorizontal: 16,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  outlineBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1,
    borderColor: BRAND, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10,
    maxWidth: 260,
  },
  outlineBtnTxt: { fontSize: 12, fontWeight: "700", color: BRAND, flexShrink: 1 },
  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1,
    borderColor: colors.border, borderRadius: 999, paddingHorizontal: 12,
    paddingVertical: 8, backgroundColor: colors.surfaceSecondary,
  },
  searchInput: {
    flex: 1, fontSize: 13, color: colors.onSurface, paddingVertical: 0,
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
  },
  chip: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface, maxWidth: 220,
  },
  chipTxt: { fontSize: 11.5, fontWeight: "600", color: colors.onSurfaceSecondary },
  dateRow: { flexDirection: "row", gap: 10, marginTop: 10 },
  fieldLbl: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 8, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 10,
    paddingVertical: 8, fontSize: 13, color: colors.onSurface, marginTop: 0,
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
  },
  entryRow: {
    flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap",
    borderWidth: 1, borderColor: colors.border, borderRadius: 10,
    padding: 10, marginTop: 8, backgroundColor: colors.surface,
  },
  entryName: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  entryMeta: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 1 },
  certBadge: {
    flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: "#EFF6FF",
    borderRadius: 999, paddingHorizontal: 8, paddingVertical: 4,
  },
  statusChip: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 4 },
  miniBtn: {
    borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6,
    alignItems: "center", justifyContent: "center",
  },
  miniBtnTxt: { color: "#fff", fontSize: 11, fontWeight: "800" },
});
