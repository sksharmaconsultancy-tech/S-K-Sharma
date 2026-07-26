/**
 * Employee Master Detail Slip — Iter 310 (Phase 1).
 *
 * Employees → Employee Detail Slip. Professional A4-styled slip showing
 * the complete Employee Master information with:
 *   • Firm + employee search, prev/next navigation
 *   • Profile completion %
 *   • FYTD Attendance Summary + Leave Information
 *   • Exports: Print / PDF (with QR code) / Excel / Email
 * Fields not yet on the Employee Master render "—" (Phase-1 directive).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, Modal, Platform, Pressable, ScrollView, StyleSheet,
  Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, shadow, spacing } from "@/src/theme";

type Emp = { user_id: string; name?: string; employee_code?: string; designation?: string };
type SlipField = { label: string; value: any };
type SlipSection = { title: string; fields: SlipField[] };
type SlipData = {
  user_id: string;
  employee: { name?: string; employee_code?: string; designation?: string };
  firm: { name?: string; address?: string; pf_code?: string; esi_code?: string };
  sections: SlipSection[];
  attendance_fytd: {
    fy_label?: string; days_present?: number;
    by_month?: Record<string, number>;
    first_punch_date?: string | null; last_punch_date?: string | null;
  };
  leaves_fytd: { type: string; days: number }[];
  timeline: { date: string; date_dmy?: string; label: string }[];
  audit_log: { at: string; by?: string; fields: string[] }[];
  profile_completion: number;
};

const BRAND = "#0F3B5C";

// Iter 312 — Phase-2 master fields editable right from the slip.
const EDIT_FIELDS: { key: string; label: string; placeholder?: string }[] = [
  { key: "mother_name", label: "Mother Name" },
  { key: "grade", label: "Grade" },
  { key: "cost_centre", label: "Cost Centre" },
  { key: "confirmation_date", label: "Confirmation Date", placeholder: "YYYY-MM-DD" },
  { key: "education", label: "Education" },
  { key: "experience", label: "Experience" },
  { key: "company_assets", label: "Company Assets" },
  { key: "nominee_name", label: "Nominee Name" },
  { key: "nominee_relation", label: "Nominee Relation" },
];

export default function EmployeeDetailSlipScreen() {
  const { user } = useAuth();
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  const [companyId, setCompanyId] = useState<string | "all">(
    globalCid && globalCid !== "all" ? globalCid : "all",
  );
  const [emps, setEmps] = useState<Emp[]>([]);
  const [search, setSearch] = useState("");
  const [selId, setSelId] = useState<string>("");
  const [data, setData] = useState<SlipData | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [emailOpen, setEmailOpen] = useState(false);
  const [emailTo, setEmailTo] = useState("");
  const [emailBusy, setEmailBusy] = useState(false);
  // Iter 312 — dark mode (persisted) + Phase-2 edit modal.
  const [dark, setDark] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState<Record<string, string>>({});
  const [editBusy, setEditBusy] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem("eds_dark").then((v) => setDark(v === "1")).catch(() => {});
  }, []);
  const toggleDark = () => {
    setDark((d) => {
      AsyncStorage.setItem("eds_dark", d ? "0" : "1").catch(() => {});
      return !d;
    });
  };

  const cid = isSuper ? (companyId === "all" ? "" : companyId) : (user?.company_id || "");

  useEffect(() => {
    if (globalCid && globalCid !== "all") setCompanyId(globalCid);
  }, [globalCid]);

  // ---- employee list ------------------------------------------------------
  const loadEmps = useCallback(async () => {
    try {
      const p = new URLSearchParams();
      if (cid) p.set("company_id", cid);
      const r = await api<{ employees: Emp[] }>(`/admin/employee-detail-slip/employees?${p}`);
      setEmps(r.employees || []);
      setSelId((prev) =>
        prev && (r.employees || []).some((e) => e.user_id === prev)
          ? prev
          : r.employees?.[0]?.user_id || "");
    } catch (e: any) {
      setErr(e?.message || "Failed to load employees");
    }
  }, [cid]);
  useEffect(() => { loadEmps(); }, [loadEmps]);

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    if (!s) return emps;
    return emps.filter((e) =>
      (e.name || "").toLowerCase().includes(s) ||
      String(e.employee_code || "").toLowerCase().includes(s));
  }, [emps, search]);

  const idx = useMemo(() => filtered.findIndex((e) => e.user_id === selId), [filtered, selId]);

  // ---- slip data ----------------------------------------------------------
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => {
    if (!selId) { setData(null); return; }
    let dead = false;
    (async () => {
      setLoading(true); setErr("");
      try {
        const r = await api<SlipData>(`/admin/employee-detail-slip/${selId}`);
        if (!dead) setData(r);
      } catch (e: any) {
        if (!dead) { setData(null); setErr(e?.message || "Failed to load slip"); }
      } finally { if (!dead) setLoading(false); }
    })();
    return () => { dead = true; };
  }, [selId, refreshKey]);

  const showMsg = (t: string) => { setMsg(t); setTimeout(() => setMsg(""), 4000); };

  // ---- Iter 312 — Phase-2 edit modal --------------------------------------
  const openEdit = async () => {
    if (!selId) return;
    try {
      const p = await api<any>(`/admin/employees/${selId}/profile`);
      const f: Record<string, string> = {};
      for (const fd of EDIT_FIELDS) f[fd.key] = p[fd.key] ? String(p[fd.key]) : "";
      setEditForm(f);
      setEditOpen(true);
    } catch (e: any) {
      showMsg(e?.message || "Failed to load fields");
    }
  };

  const saveEdit = async () => {
    if (!selId) return;
    setEditBusy(true);
    try {
      const body: Record<string, any> = {};
      for (const fd of EDIT_FIELDS) body[fd.key] = editForm[fd.key]?.trim() || null;
      await api(`/admin/employees/${selId}/profile`, { method: "PATCH", body });
      setEditOpen(false);
      setRefreshKey((k) => k + 1);
      showMsg("Details saved to Employee Master");
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally { setEditBusy(false); }
  };

  // ---- exports ------------------------------------------------------------
  const doExport = async (kind: "pdf" | "xlsx" | "print") => {
    if (!selId) return;
    setExporting(kind);
    try {
      const path = kind === "xlsx"
        ? `/admin/employee-detail-slip/${selId}/slip.xlsx`
        : `/admin/employee-detail-slip/${selId}/slip.pdf`;
      const res = await apiBinary(path);
      if (Platform.OS === "web" && res.webBlobUrl) {
        if (kind === "print" || kind === "pdf") {
          window.open(res.webBlobUrl, "_blank");
        } else {
          const a = document.createElement("a");
          a.href = res.webBlobUrl;
          a.download = `Employee_Detail_Slip_${data?.employee?.employee_code || "emp"}.xlsx`;
          a.click();
        }
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      } else {
        showMsg("Export ready — please use the web portal to download files.");
      }
    } catch (e: any) {
      showMsg(e?.message || "Export failed");
    } finally { setExporting(null); }
  };

  const sendEmail = async () => {
    if (!selId || !emailTo.trim()) return;
    setEmailBusy(true);
    try {
      await api(`/admin/employee-detail-slip/${selId}/email`, {
        method: "POST", body: { to: emailTo.trim() },
      });
      setEmailOpen(false);
      showMsg(`Slip emailed to ${emailTo.trim()}`);
    } catch (e: any) {
      showMsg(e?.message || "Email failed");
    } finally { setEmailBusy(false); }
  };

  // ---- render -------------------------------------------------------------
  const comp = data?.profile_completion ?? 0;
  const compColor = comp >= 80 ? "#16A34A" : comp >= 50 ? "#D97706" : "#DC2626";
  // Iter 312 — dark palette for the slip card.
  const pal = dark
    ? { card: "#0B1620", secBorder: "#1E3448", cellBorder: "#152736",
        lbl: "#7E97AB", val: "#E7EFF6", name: "#7FC4F5", tool: "#0F1F2D",
        secHdr: "#123049" }
    : { card: "#fff", secBorder: "#DDE4EA", cellBorder: "#EDF1F5",
        lbl: colors.onSurfaceTertiary, val: colors.onSurface, name: BRAND,
        tool: colors.surfaceSecondary, secHdr: BRAND };

  const Cell = ({ label, value }: { label: any; value: any }) => (
    <View style={[styles.fieldCell, { borderColor: pal.cellBorder }]}>
      <Text style={[styles.fieldLbl, { color: pal.lbl }]}>{String(label)}</Text>
      <Text style={[styles.fieldVal, { color: pal.val }]}>
        {value !== null && value !== undefined && value !== "" ? String(value) : "—"}
      </Text>
    </View>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.headerRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Employee Detail Slip</Text>
            <Text style={styles.subtitle}>Complete Employee Master information · A4 printable</Text>
          </View>
        </View>

        {/* Controls */}
        <View style={styles.card}>
          {isSuper ? (
            <CompanyPicker value={companyId} onChange={setCompanyId} includeAll={false} />
          ) : null}
          <View style={styles.searchRow}>
            <Ionicons name="search-outline" size={14} color={colors.onSurfaceTertiary} />
            <TextInput
              value={search}
              onChangeText={setSearch}
              placeholder="Search employee by name or code…"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.searchInput}
              testID="eds-search"
            />
            {search ? (
              <Pressable onPress={() => setSearch("")} hitSlop={6}>
                <Ionicons name="close-circle" size={14} color={colors.onSurfaceTertiary} />
              </Pressable>
            ) : null}
          </View>
          {/* Employee chips (first 60 matches) */}
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
            <View style={{ flexDirection: "row", gap: 6 }}>
              {filtered.slice(0, 60).map((e) => (
                <Pressable
                  key={e.user_id}
                  onPress={() => setSelId(e.user_id)}
                  style={[styles.chip, selId === e.user_id && styles.chipOn]}
                  testID={`eds-emp-${e.employee_code || e.user_id}`}
                >
                  <Text style={[styles.chipTxt, selId === e.user_id && styles.chipTxtOn]} numberOfLines={1}>
                    {e.employee_code ? `${e.employee_code} · ` : ""}{e.name || "—"}
                  </Text>
                </Pressable>
              ))}
              {!filtered.length ? (
                <Text style={{ fontSize: 12, color: colors.onSurfaceTertiary }}>No employees match.</Text>
              ) : null}
            </View>
          </ScrollView>
        </View>

        {msg ? <Text style={styles.msg}>{msg}</Text> : null}
        {err ? <Text style={styles.err}>{err}</Text> : null}

        {loading ? <ActivityIndicator style={{ marginTop: 24 }} color={BRAND} /> : null}

        {data && !loading ? (
          <View style={[styles.a4, { backgroundColor: pal.card, borderColor: pal.secBorder }]}>
            {/* Slip header band */}
            <View style={styles.band}>
              <View style={{ flex: 1 }}>
                <Text style={styles.bandFirm}>{(data.firm?.name || "").toUpperCase()}</Text>
                {data.firm?.address ? <Text style={styles.bandSub} numberOfLines={1}>{data.firm.address}</Text> : null}
                <Text style={styles.bandSub}>
                  {[data.firm?.pf_code ? `PF: ${data.firm.pf_code}` : "", data.firm?.esi_code ? `ESI: ${data.firm.esi_code}` : ""].filter(Boolean).join("  ·  ")}
                </Text>
              </View>
              <View style={{ alignItems: "flex-end" }}>
                <Text style={styles.bandTitle}>EMPLOYEE MASTER DETAIL SLIP</Text>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 }}>
                  <View style={styles.compTrack}>
                    <View style={[styles.compFill, { width: `${Math.min(100, comp)}%` as any, backgroundColor: compColor }]} />
                  </View>
                  <Text style={[styles.compTxt, { color: "#fff" }]}>{comp}% complete</Text>
                </View>
              </View>
            </View>

            {/* Nav + exports toolbar */}
            <View style={[styles.toolbar, { backgroundColor: pal.tool, borderBottomColor: pal.secBorder }]}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flex: 1 }}>
                <Pressable
                  onPress={() => idx > 0 && setSelId(filtered[idx - 1].user_id)}
                  disabled={idx <= 0}
                  style={[styles.navBtn, idx <= 0 && { opacity: 0.4 }]}
                  testID="eds-prev"
                >
                  <Ionicons name="chevron-back" size={16} color={BRAND} />
                </Pressable>
                <Text style={styles.navTxt}>
                  {idx >= 0 ? `${idx + 1} / ${filtered.length}` : "—"}
                </Text>
                <Pressable
                  onPress={() => idx >= 0 && idx < filtered.length - 1 && setSelId(filtered[idx + 1].user_id)}
                  disabled={idx < 0 || idx >= filtered.length - 1}
                  style={[styles.navBtn, (idx < 0 || idx >= filtered.length - 1) && { opacity: 0.4 }]}
                  testID="eds-next"
                >
                  <Ionicons name="chevron-forward" size={16} color={BRAND} />
                </Pressable>
              </View>
              <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
                {([["print", "print-outline", "Print"],
                   ["pdf", "document-text-outline", "PDF"],
                   ["xlsx", "grid-outline", "Excel"]] as const).map(([k, icon, lab]) => (
                  <Pressable
                    key={k}
                    onPress={() => doExport(k)}
                    style={styles.expBtn}
                    disabled={!!exporting}
                    testID={`eds-export-${k}`}
                  >
                    {exporting === k ? <ActivityIndicator size="small" color={BRAND} /> : (
                      <>
                        <Ionicons name={icon as any} size={14} color={BRAND} />
                        <Text style={styles.expTxt}>{lab}</Text>
                      </>
                    )}
                  </Pressable>
                ))}
                <Pressable onPress={() => setEmailOpen((v) => !v)} style={styles.expBtn} testID="eds-export-email">
                  <Ionicons name="mail-outline" size={14} color={BRAND} />
                  <Text style={styles.expTxt}>Email</Text>
                </Pressable>
                {/* Iter 312 — Phase-2 edit + dark mode */}
                <Pressable onPress={openEdit} style={[styles.expBtn, { borderColor: "#B45309" }]} testID="eds-edit">
                  <Ionicons name="create-outline" size={14} color="#B45309" />
                  <Text style={[styles.expTxt, { color: "#B45309" }]}>Edit</Text>
                </Pressable>
                <Pressable onPress={toggleDark} style={[styles.expBtn, dark && { backgroundColor: "#123049", borderColor: "#123049" }]} testID="eds-dark-toggle">
                  <Ionicons name={dark ? "sunny-outline" : "moon-outline"} size={14} color={dark ? "#FCD34D" : BRAND} />
                  <Text style={[styles.expTxt, dark && { color: "#FCD34D" }]}>{dark ? "Light" : "Dark"}</Text>
                </Pressable>
              </View>
            </View>

            {emailOpen ? (
              <View style={styles.emailRow}>
                <TextInput
                  value={emailTo}
                  onChangeText={setEmailTo}
                  placeholder="recipient@email.com"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  autoCapitalize="none"
                  keyboardType="email-address"
                  style={styles.emailInput}
                  testID="eds-email-to"
                />
                <Pressable onPress={sendEmail} style={styles.emailSend} disabled={emailBusy} testID="eds-email-send">
                  {emailBusy ? <ActivityIndicator size="small" color="#fff" /> : (
                    <Text style={{ color: "#fff", fontWeight: "700", fontSize: 12 }}>Send</Text>
                  )}
                </Pressable>
              </View>
            ) : null}

            {/* Employee name block */}
            <View style={styles.nameBlock}>
              <Text style={[styles.empName, { color: pal.name }]}>{(data.employee?.name || "").toUpperCase()}</Text>
              <Text style={[styles.empMeta, { color: pal.lbl }]}>
                Code: {data.employee?.employee_code || "—"}   ·   {data.employee?.designation || "—"}
              </Text>
            </View>

            {/* Sections */}
            {data.sections.map((s) => (
              <View key={s.title} style={[styles.section, { borderColor: pal.secBorder }]}>
                <View style={[styles.secHdr, { backgroundColor: pal.secHdr }]}><Text style={styles.secHdrTxt}>{s.title}</Text></View>
                <View style={styles.secGrid}>
                  {s.fields.map((f, i) => (
                    <Cell key={`${s.title}-${i}`} label={f.label} value={f.value} />
                  ))}
                </View>
              </View>
            ))}

            {/* Attendance FYTD */}
            <View style={[styles.section, { borderColor: pal.secBorder }]}>
              <View style={[styles.secHdr, { backgroundColor: pal.secHdr }]}>
                <Text style={styles.secHdrTxt}>Attendance Summary — {data.attendance_fytd?.fy_label || "FYTD"}</Text>
              </View>
              <View style={styles.secGrid}>
                <Cell label="Days Present (FYTD)" value={data.attendance_fytd?.days_present} />
                <Cell label="First Punch" value={data.attendance_fytd?.first_punch_date} />
                <Cell label="Last Punch" value={data.attendance_fytd?.last_punch_date} />
                {Object.entries(data.attendance_fytd?.by_month || {}).map(([m, n]) => (
                  <Cell key={m} label={`Month ${m}`} value={`${n} day(s)`} />
                ))}
              </View>
            </View>

            {/* Leaves FYTD */}
            <View style={[styles.section, { borderColor: pal.secBorder }]}>
              <View style={[styles.secHdr, { backgroundColor: pal.secHdr }]}>
                <Text style={styles.secHdrTxt}>Leave Information — {data.attendance_fytd?.fy_label || "FYTD"}</Text>
              </View>
              <View style={styles.secGrid}>
                {(data.leaves_fytd || []).length ? data.leaves_fytd.map((x) => (
                  <Cell key={x.type} label={`${x.type} Leave`} value={`${x.days} day(s)`} />
                )) : (
                  <Cell label="Approved Leaves (FYTD)" value={null} />
                )}
              </View>
            </View>

            {/* Iter 312 — Employment Timeline */}
            {(data.timeline || []).length ? (
              <View style={[styles.section, { borderColor: pal.secBorder }]}>
                <View style={[styles.secHdr, { backgroundColor: pal.secHdr }]}>
                  <Text style={styles.secHdrTxt}>Employment Timeline</Text>
                </View>
                <View style={{ paddingVertical: 6 }}>
                  {data.timeline.map((t, i) => (
                    <View key={`${t.date}-${i}`} style={styles.tlRow}>
                      <View style={styles.tlDotWrap}>
                        <View style={[styles.tlDot, { backgroundColor: pal.name }]} />
                        {i < data.timeline.length - 1 ? <View style={[styles.tlLine, { backgroundColor: pal.cellBorder }]} /> : null}
                      </View>
                      <Text style={[styles.tlDate, { color: pal.lbl }]}>{t.date_dmy || t.date}</Text>
                      <Text style={[styles.tlLabel, { color: pal.val }]}>{t.label}</Text>
                    </View>
                  ))}
                </View>
              </View>
            ) : null}

            {/* Iter 312 — Audit Log (Employee Master edits) */}
            <View style={[styles.section, { borderColor: pal.secBorder }]}>
              <View style={[styles.secHdr, { backgroundColor: pal.secHdr }]}>
                <Text style={styles.secHdrTxt}>Audit Log — Recent Master Changes</Text>
              </View>
              <View style={{ paddingVertical: 4 }}>
                {(data.audit_log || []).length ? data.audit_log.map((a, i) => (
                  <View key={i} style={[styles.auditRow, { borderBottomColor: pal.cellBorder }]}>
                    <Text style={[styles.tlDate, { color: pal.lbl, width: 118 }]}>{a.at}</Text>
                    <Text style={[styles.tlLabel, { color: pal.val, flex: 1 }]} numberOfLines={2}>
                      {a.by || "—"} changed: {a.fields.join(", ")}
                    </Text>
                  </View>
                )) : (
                  <Text style={{ fontSize: 11.5, color: pal.lbl, paddingHorizontal: 10, paddingVertical: 6 }}>
                    No master edits recorded yet.
                  </Text>
                )}
              </View>
            </View>
          </View>
        ) : null}

        {!selId && !loading ? (
          <Text style={{ textAlign: "center", marginTop: 32, color: colors.onSurfaceTertiary }}>
            Select a firm and an employee to view the Detail Slip.
          </Text>
        ) : null}
      </ScrollView>

      {/* Iter 312 — Phase-2 fields edit modal (writes to Employee Master) */}
      <Modal visible={editOpen} transparent animationType="fade" onRequestClose={() => setEditOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 10 }}>
              <Text style={{ flex: 1, fontSize: 15, fontWeight: "800", color: BRAND }}>
                Edit Additional Details
              </Text>
              <Pressable onPress={() => setEditOpen(false)} hitSlop={8} testID="eds-edit-close">
                <Ionicons name="close" size={20} color={colors.onSurfaceSecondary} />
              </Pressable>
            </View>
            <Text style={{ fontSize: 11.5, color: colors.onSurfaceSecondary, marginBottom: 10 }}>
              Saved directly to the Employee Master · every change is audit-logged.
            </Text>
            <ScrollView style={{ maxHeight: 420 }}>
              {EDIT_FIELDS.map((f) => (
                <View key={f.key} style={{ marginBottom: 10 }}>
                  <Text style={styles.modalLbl}>{f.label}</Text>
                  <TextInput
                    value={editForm[f.key] || ""}
                    onChangeText={(v) => setEditForm((p) => ({ ...p, [f.key]: v }))}
                    placeholder={f.placeholder || f.label}
                    placeholderTextColor={colors.onSurfaceTertiary}
                    style={styles.modalInput}
                    testID={`eds-edit-${f.key}`}
                  />
                </View>
              ))}
            </ScrollView>
            <Pressable onPress={saveEdit} style={styles.modalSave} disabled={editBusy} testID="eds-edit-save">
              {editBusy ? <ActivityIndicator size="small" color="#fff" /> : (
                <Text style={{ color: "#fff", fontWeight: "800", fontSize: 13 }}>Save to Employee Master</Text>
              )}
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: spacing.md, paddingBottom: 60 },
  headerRow: { flexDirection: "row", alignItems: "center", marginBottom: spacing.sm },
  title: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm, ...shadow.sm,
  },
  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1,
    borderColor: colors.border, borderRadius: 999, paddingHorizontal: 12,
    paddingVertical: 8, marginTop: 8, backgroundColor: colors.surfaceSecondary,
  },
  searchInput: {
    flex: 1, fontSize: 13, color: colors.onSurface, paddingVertical: 0,
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
  },
  chip: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface, maxWidth: 220,
  },
  chipOn: { backgroundColor: BRAND, borderColor: BRAND },
  chipTxt: { fontSize: 11.5, fontWeight: "600", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  msg: { color: "#166534", fontSize: 12, fontWeight: "700", marginBottom: 6 },
  err: { color: "#B91C1C", fontSize: 12, fontWeight: "700", marginBottom: 6 },
  a4: {
    backgroundColor: "#fff", borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, overflow: "hidden", maxWidth: 900,
    width: "100%", alignSelf: "center", ...shadow.md,
  },
  band: {
    backgroundColor: BRAND, paddingHorizontal: 16, paddingVertical: 14,
    flexDirection: "row", alignItems: "center", gap: 12,
  },
  bandFirm: { color: "#fff", fontSize: 16, fontWeight: "800" },
  bandSub: { color: "#CBD9E4", fontSize: 10.5, marginTop: 2 },
  bandTitle: { color: "#fff", fontSize: 12, fontWeight: "800", letterSpacing: 0.4 },
  compTrack: { width: 90, height: 6, borderRadius: 999, backgroundColor: "rgba(255,255,255,0.25)", overflow: "hidden" },
  compFill: { height: 6, borderRadius: 999 },
  compTxt: { fontSize: 10.5, fontWeight: "700" },
  toolbar: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 12,
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.surfaceSecondary, gap: 8, flexWrap: "wrap",
  },
  navBtn: {
    width: 30, height: 30, borderRadius: 8, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center", backgroundColor: "#fff",
  },
  navTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  expBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10,
    paddingVertical: 7, borderRadius: 8, borderWidth: 1, borderColor: BRAND,
    backgroundColor: "#fff",
  },
  expTxt: { fontSize: 11.5, fontWeight: "700", color: BRAND },
  emailRow: {
    flexDirection: "row", gap: 8, paddingHorizontal: 12, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: colors.border, alignItems: "center",
  },
  emailInput: {
    flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 7, fontSize: 12.5, color: colors.onSurface,
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
  },
  emailSend: {
    backgroundColor: BRAND, borderRadius: 8, paddingHorizontal: 16,
    paddingVertical: 8, alignItems: "center", justifyContent: "center",
  },
  nameBlock: { paddingHorizontal: 16, paddingTop: 12, paddingBottom: 4 },
  empName: { fontSize: 16, fontWeight: "800", color: BRAND },
  empMeta: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  section: { marginHorizontal: 12, marginTop: 10, borderWidth: 1, borderColor: "#DDE4EA", borderRadius: 8, overflow: "hidden", marginBottom: 2 },
  secHdr: { backgroundColor: BRAND, paddingHorizontal: 10, paddingVertical: 6 },
  secHdrTxt: { color: "#fff", fontSize: 11.5, fontWeight: "800", letterSpacing: 0.3 },
  secGrid: { flexDirection: "row", flexWrap: "wrap" },
  fieldCell: {
    width: Platform.OS === "web" ? ("33.33%" as any) : ("50%" as any),
    paddingHorizontal: 10, paddingVertical: 6, borderBottomWidth: 0.5,
    borderRightWidth: 0.5, borderColor: "#EDF1F5",
  },
  fieldLbl: { fontSize: 10, color: colors.onSurfaceTertiary, fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.3 },
  fieldVal: { fontSize: 12.5, color: colors.onSurface, fontWeight: "700", marginTop: 1 },
  // Iter 312 — timeline / audit / modal
  tlRow: { flexDirection: "row", alignItems: "flex-start", paddingHorizontal: 12, minHeight: 26 },
  tlDotWrap: { width: 14, alignItems: "center", alignSelf: "stretch" },
  tlDot: { width: 8, height: 8, borderRadius: 4, marginTop: 4 },
  tlLine: { width: 2, flex: 1, marginTop: 2 },
  tlDate: { width: 92, fontSize: 11, fontWeight: "700", marginLeft: 6 },
  tlLabel: { flex: 1, fontSize: 12, fontWeight: "600", marginLeft: 6, paddingBottom: 8 },
  auditRow: { flexDirection: "row", alignItems: "flex-start", paddingHorizontal: 10, paddingVertical: 5, borderBottomWidth: 0.5 },
  modalBg: { flex: 1, backgroundColor: "rgba(15,42,61,0.55)", alignItems: "center", justifyContent: "center", padding: 16 },
  modalCard: { backgroundColor: "#fff", borderRadius: radius.md, padding: 16, width: "100%", maxWidth: 520, ...shadow.md },
  modalLbl: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  modalInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 10,
    paddingVertical: 8, fontSize: 13, color: colors.onSurface,
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
  },
  modalSave: {
    backgroundColor: BRAND, borderRadius: 10, paddingVertical: 12,
    alignItems: "center", marginTop: 12,
  },
});
