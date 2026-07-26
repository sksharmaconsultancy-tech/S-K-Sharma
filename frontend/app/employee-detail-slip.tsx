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
  ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet,
  Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

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
  profile_completion: number;
};

const BRAND = "#0F3B5C";

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
  }, [selId]);

  const showMsg = (t: string) => { setMsg(t); setTimeout(() => setMsg(""), 4000); };

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
          <View style={styles.a4}>
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
            <View style={styles.toolbar}>
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
              <Text style={styles.empName}>{(data.employee?.name || "").toUpperCase()}</Text>
              <Text style={styles.empMeta}>
                Code: {data.employee?.employee_code || "—"}   ·   {data.employee?.designation || "—"}
              </Text>
            </View>

            {/* Sections */}
            {data.sections.map((s) => (
              <View key={s.title} style={styles.section}>
                <View style={styles.secHdr}><Text style={styles.secHdrTxt}>{s.title}</Text></View>
                <View style={styles.secGrid}>
                  {s.fields.map((f, i) => (
                    <View key={`${s.title}-${i}`} style={styles.fieldCell}>
                      <Text style={styles.fieldLbl}>{f.label}</Text>
                      <Text style={styles.fieldVal}>{f.value !== null && f.value !== undefined && f.value !== "" ? String(f.value) : "—"}</Text>
                    </View>
                  ))}
                </View>
              </View>
            ))}

            {/* Attendance FYTD */}
            <View style={styles.section}>
              <View style={styles.secHdr}>
                <Text style={styles.secHdrTxt}>Attendance Summary — {data.attendance_fytd?.fy_label || "FYTD"}</Text>
              </View>
              <View style={styles.secGrid}>
                <View style={styles.fieldCell}>
                  <Text style={styles.fieldLbl}>Days Present (FYTD)</Text>
                  <Text style={styles.fieldVal}>{data.attendance_fytd?.days_present ?? "—"}</Text>
                </View>
                <View style={styles.fieldCell}>
                  <Text style={styles.fieldLbl}>First Punch</Text>
                  <Text style={styles.fieldVal}>{data.attendance_fytd?.first_punch_date || "—"}</Text>
                </View>
                <View style={styles.fieldCell}>
                  <Text style={styles.fieldLbl}>Last Punch</Text>
                  <Text style={styles.fieldVal}>{data.attendance_fytd?.last_punch_date || "—"}</Text>
                </View>
                {Object.entries(data.attendance_fytd?.by_month || {}).map(([m, n]) => (
                  <View key={m} style={styles.fieldCell}>
                    <Text style={styles.fieldLbl}>Month {m}</Text>
                    <Text style={styles.fieldVal}>{n} day(s)</Text>
                  </View>
                ))}
              </View>
            </View>

            {/* Leaves FYTD */}
            <View style={styles.section}>
              <View style={styles.secHdr}>
                <Text style={styles.secHdrTxt}>Leave Information — {data.attendance_fytd?.fy_label || "FYTD"}</Text>
              </View>
              <View style={styles.secGrid}>
                {(data.leaves_fytd || []).length ? data.leaves_fytd.map((x) => (
                  <View key={x.type} style={styles.fieldCell}>
                    <Text style={styles.fieldLbl}>{x.type} Leave</Text>
                    <Text style={styles.fieldVal}>{x.days} day(s)</Text>
                  </View>
                )) : (
                  <View style={styles.fieldCell}>
                    <Text style={styles.fieldLbl}>Approved Leaves (FYTD)</Text>
                    <Text style={styles.fieldVal}>—</Text>
                  </View>
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
});
