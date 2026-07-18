/**
 * KYC & Document Expiry Tracker — Enterprise module.
 *
 * Per-employee KYC completeness (Aadhaar / PAN / Bank) + document
 * validity tracking (Driving Licence & Passport "valid upto" dates)
 * with expiry reminders (expired / expiring within 60 days).
 *
 * Design follows the SAP/Workday enterprise standard established in
 * employee-add.tsx: KPI stat cards, filter chips, clean data rows,
 * sticky header, 16px radius cards and soft shadows.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, Pressable, ActivityIndicator,
  TextInput, Modal, ScrollView, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import DateField from "@/src/components/DateField";
import { colors, radius } from "@/src/theme";

type Emp = {
  user_id: string;
  name: string;
  employee_code?: string;
  company_id?: string;
  company_name?: string;
  department?: string;
  designation?: string;
  aadhaar_masked?: string | null;
  has_aadhaar: boolean;
  pan?: string | null;
  has_pan: boolean;
  bank_ok: boolean;
  uan_no?: string | null;
  esi_ip_no?: string | null;
  dl_number?: string | null;
  dl_valid_upto?: string | null;
  passport_no?: string | null;
  passport_valid_upto?: string | null;
  uploaded_docs: string[];
  missing: string[];
  expired_docs: string[];
  expiring_docs: string[];
  status: "complete" | "incomplete" | "expiring" | "expired";
};

type Summary = {
  total: number; complete: number; incomplete: number;
  missing_aadhaar: number; missing_pan: number; missing_bank: number;
  expiring: number; expired: number;
};

type FilterKey =
  | "all" | "complete" | "incomplete"
  | "missing_aadhaar" | "missing_pan" | "missing_bank"
  | "expiring" | "expired";

const FILTER_CHIPS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "complete", label: "Complete" },
  { key: "incomplete", label: "Incomplete" },
  { key: "missing_aadhaar", label: "No Aadhaar" },
  { key: "missing_pan", label: "No PAN" },
  { key: "missing_bank", label: "No Bank" },
  { key: "expiring", label: "Expiring Soon" },
  { key: "expired", label: "Expired" },
];

function fmtDMY(iso?: string | null) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}-${m}-${y}`;
}

/* ---------------------------------------------------------------- */
/* Small doc status chip used inside each employee row               */
/* ---------------------------------------------------------------- */
function DocChip({
  label, tone, sub,
}: { label: string; tone: "ok" | "missing" | "expiring" | "expired" | "neutral"; sub?: string }) {
  const palette = {
    ok: { bg: "rgba(5,150,105,0.10)", fg: "#059669", icon: "checkmark-circle" as const },
    missing: { bg: "rgba(217,119,6,0.10)", fg: "#B45309", icon: "alert-circle-outline" as const },
    expiring: { bg: "rgba(234,88,12,0.12)", fg: "#C2410C", icon: "time-outline" as const },
    expired: { bg: "rgba(220,38,38,0.10)", fg: "#DC2626", icon: "close-circle" as const },
    neutral: { bg: "rgba(100,116,139,0.10)", fg: "#64748B", icon: "remove-circle-outline" as const },
  }[tone];
  return (
    <View style={[s.docChip, { backgroundColor: palette.bg }]}>
      <Ionicons name={palette.icon} size={12} color={palette.fg} />
      <Text style={[s.docChipTxt, { color: palette.fg }]}>
        {label}{sub ? ` · ${sub}` : ""}
      </Text>
    </View>
  );
}

/* ---------------------------------------------------------------- */
/* KPI stat card                                                      */
/* ---------------------------------------------------------------- */
function StatCard({
  label, value, tone, icon, active, onPress,
}: {
  label: string; value: number; icon: keyof typeof Ionicons.glyphMap;
  tone: string; active?: boolean; onPress?: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={[s.statCard, active && { borderColor: tone, borderWidth: 1.5 }]}
      testID={`kpi-${label.replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase()}`}
    >
      <View style={[s.statIconWrap, { backgroundColor: `${tone}18` }]}>
        <Ionicons name={icon} size={16} color={tone} />
      </View>
      <Text style={s.statValue}>{value}</Text>
      <Text style={s.statLabel} numberOfLines={1}>{label}</Text>
    </Pressable>
  );
}

export default function KycTracker() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const role = user?.role as string;

  const [companyId, setCompanyId] = useState<string | "all">(
    role === "company_admin" ? (user?.company_id || "all") : (selectedCompanyId || "all"),
  );
  const [data, setData] = useState<{ summary: Summary; employees: Emp[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");

  // Expiry editor modal
  const [editEmp, setEditEmp] = useState<Emp | null>(null);
  const [dlDate, setDlDate] = useState("");
  const [ppDate, setPpDate] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = companyId && companyId !== "all" ? `?company_id=${companyId}` : "";
      setData(await api(`/admin/kyc-tracker${q}`));
    } catch { setData(null); }
    finally { setLoading(false); }
  }, [companyId]);
  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    let rows = data?.employees || [];
    if (filter === "complete") rows = rows.filter((e) => e.missing.length === 0);
    else if (filter === "incomplete") rows = rows.filter((e) => e.missing.length > 0);
    else if (filter === "missing_aadhaar") rows = rows.filter((e) => e.missing.includes("aadhaar"));
    else if (filter === "missing_pan") rows = rows.filter((e) => e.missing.includes("pan"));
    else if (filter === "missing_bank") rows = rows.filter((e) => e.missing.includes("bank"));
    else if (filter === "expiring") rows = rows.filter((e) => e.expiring_docs.length > 0);
    else if (filter === "expired") rows = rows.filter((e) => e.expired_docs.length > 0);
    const term = search.trim().toLowerCase();
    if (term) {
      rows = rows.filter((e) =>
        (e.name || "").toLowerCase().includes(term) ||
        String(e.employee_code || "").toLowerCase().includes(term) ||
        (e.pan || "").toLowerCase().includes(term),
      );
    }
    return rows;
  }, [data, filter, search]);

  const openExpiryEditor = (e: Emp) => {
    setEditEmp(e);
    setDlDate(e.dl_valid_upto || "");
    setPpDate(e.passport_valid_upto || "");
  };

  const saveExpiry = async () => {
    if (!editEmp) return;
    setSaving(true);
    try {
      await api(`/admin/employees/${editEmp.user_id}/kyc`, {
        method: "PATCH",
        body: { dl_valid_upto: dlDate || "", passport_valid_upto: ppDate || "" },
      });
      setEditEmp(null);
      await load();
    } catch (err: any) {
      const msg = err?.message || "Failed to save validity dates";
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Error", msg);
    } finally { setSaving(false); }
  };

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }

  const sum = data?.summary;
  const showFirmBadge = companyId === "all" && role !== "company_admin";

  const dlTone = (e: Emp): { tone: "ok" | "missing" | "expiring" | "expired" | "neutral"; sub?: string } => {
    if (!e.dl_number && !e.dl_valid_upto) return { tone: "neutral" };
    if (e.expired_docs.includes("dl_valid_upto")) return { tone: "expired", sub: fmtDMY(e.dl_valid_upto) };
    if (e.expiring_docs.includes("dl_valid_upto")) return { tone: "expiring", sub: fmtDMY(e.dl_valid_upto) };
    if (e.dl_valid_upto) return { tone: "ok", sub: fmtDMY(e.dl_valid_upto) };
    return { tone: "ok" };
  };
  const ppTone = (e: Emp): { tone: "ok" | "missing" | "expiring" | "expired" | "neutral"; sub?: string } => {
    if (!e.passport_no && !e.passport_valid_upto) return { tone: "neutral" };
    if (e.expired_docs.includes("passport_valid_upto")) return { tone: "expired", sub: fmtDMY(e.passport_valid_upto) };
    if (e.expiring_docs.includes("passport_valid_upto")) return { tone: "expiring", sub: fmtDMY(e.passport_valid_upto) };
    if (e.passport_valid_upto) return { tone: "ok", sub: fmtDMY(e.passport_valid_upto) };
    return { tone: "ok" };
  };

  const renderRow = ({ item: e }: { item: Emp }) => (
    <Pressable
      style={s.row}
      testID={`kyc-row-${e.user_id}`}
      onPress={() => router.push({ pathname: "/employee-master", params: { user_id: e.user_id } } as any)}
    >
      <View style={s.rowTop}>
        <View style={s.avatar}>
          <Text style={s.avatarTxt}>{(e.name || "?").slice(0, 1)}</Text>
        </View>
        <View style={{ flex: 1, minWidth: 0 }}>
          <View style={s.nameRow}>
            <Text style={s.name} numberOfLines={1}>{e.name}</Text>
            {e.employee_code ? (
              <View style={s.codePill}><Text style={s.codePillTxt}>#{e.employee_code}</Text></View>
            ) : null}
            {e.status === "expired" ? (
              <View style={[s.statusPill, { backgroundColor: "rgba(220,38,38,0.10)" }]}>
                <Text style={[s.statusPillTxt, { color: "#DC2626" }]}>EXPIRED</Text>
              </View>
            ) : e.status === "expiring" ? (
              <View style={[s.statusPill, { backgroundColor: "rgba(234,88,12,0.12)" }]}>
                <Text style={[s.statusPillTxt, { color: "#C2410C" }]}>EXPIRING</Text>
              </View>
            ) : null}
          </View>
          <Text style={s.meta} numberOfLines={1}>
            {[e.designation, e.department, showFirmBadge ? (e.company_name || e.company_id) : null]
              .filter(Boolean).join(" · ") || "—"}
          </Text>
        </View>
        <Pressable
          onPress={(ev) => { (ev as any)?.stopPropagation?.(); openExpiryEditor(e); }}
          style={s.expiryBtn}
          hitSlop={8}
          testID={`edit-expiry-${e.user_id}`}
        >
          <Ionicons name="calendar-outline" size={15} color={colors.brandPrimary} />
          <Text style={s.expiryBtnTxt}>Validity</Text>
        </Pressable>
      </View>
      <View style={s.chipsRow}>
        <DocChip label="Aadhaar" tone={e.has_aadhaar ? "ok" : "missing"} sub={e.aadhaar_masked ? e.aadhaar_masked.slice(-4) : undefined} />
        <DocChip label="PAN" tone={e.has_pan ? "ok" : "missing"} sub={e.pan || undefined} />
        <DocChip label="Bank" tone={e.bank_ok ? "ok" : "missing"} />
        <DocChip label="DL" {...dlTone(e)} />
        <DocChip label="Passport" {...ppTone(e)} />
        {e.uploaded_docs.length > 0 ? (
          <View style={s.uploadsPill}>
            <Ionicons name="document-attach-outline" size={11} color={colors.brandPrimary} />
            <Text style={s.uploadsPillTxt}>{e.uploaded_docs.length} scan{e.uploaded_docs.length > 1 ? "s" : ""}</Text>
          </View>
        ) : null}
      </View>
    </Pressable>
  );

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      {/* Header */}
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.back} testID="kyc-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>KYC &amp; Document Tracker</Text>
          <Text style={s.subtitle}>Aadhaar · PAN · Bank · DL / Passport validity</Text>
        </View>
        <Pressable onPress={load} hitSlop={10} style={s.back} testID="kyc-refresh">
          <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>

      <FlatList
        data={filtered}
        keyExtractor={(e) => e.user_id}
        renderItem={renderRow}
        contentContainerStyle={s.listContent}
        ListHeaderComponent={
          <View>
            {role !== "company_admin" ? (
              <View style={{ marginBottom: 12 }}>
                <CompanyPicker
                  value={companyId}
                  onChange={(v: any) => setCompanyId(v || "all")}
                  allowAll
                />
              </View>
            ) : null}

            {/* KPI cards */}
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 12 }}>
              <View style={s.statsRow}>
                <StatCard label="Employees" value={sum?.total ?? 0} icon="people-outline" tone={colors.brandPrimary} active={filter === "all"} onPress={() => setFilter("all")} />
                <StatCard label="KYC Complete" value={sum?.complete ?? 0} icon="shield-checkmark-outline" tone="#059669" active={filter === "complete"} onPress={() => setFilter("complete")} />
                <StatCard label="No Aadhaar" value={sum?.missing_aadhaar ?? 0} icon="finger-print-outline" tone="#B45309" active={filter === "missing_aadhaar"} onPress={() => setFilter("missing_aadhaar")} />
                <StatCard label="No PAN" value={sum?.missing_pan ?? 0} icon="card-outline" tone="#B45309" active={filter === "missing_pan"} onPress={() => setFilter("missing_pan")} />
                <StatCard label="No Bank" value={sum?.missing_bank ?? 0} icon="business-outline" tone="#B45309" active={filter === "missing_bank"} onPress={() => setFilter("missing_bank")} />
                <StatCard label="Expiring ≤60d" value={sum?.expiring ?? 0} icon="time-outline" tone="#C2410C" active={filter === "expiring"} onPress={() => setFilter("expiring")} />
                <StatCard label="Expired" value={sum?.expired ?? 0} icon="alert-circle-outline" tone="#DC2626" active={filter === "expired"} onPress={() => setFilter("expired")} />
              </View>
            </ScrollView>

            {/* Search */}
            <View style={s.searchWrap}>
              <Ionicons name="search" size={16} color={colors.onSurfaceTertiary} />
              <TextInput
                style={s.searchInput}
                placeholder="Search name, code or PAN…"
                placeholderTextColor={colors.onSurfaceTertiary}
                value={search}
                onChangeText={setSearch}
                testID="kyc-search"
              />
              {search ? (
                <Pressable onPress={() => setSearch("")} hitSlop={8}>
                  <Ionicons name="close-circle" size={16} color={colors.onSurfaceTertiary} />
                </Pressable>
              ) : null}
            </View>

            {/* Filter chips */}
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 12 }}>
              <View style={{ flexDirection: "row", gap: 8 }}>
                {FILTER_CHIPS.map((c) => (
                  <Pressable
                    key={c.key}
                    onPress={() => setFilter(c.key)}
                    style={[s.chip, filter === c.key && s.chipActive]}
                    testID={`filter-${c.key}`}
                  >
                    <Text style={[s.chipTxt, filter === c.key && s.chipTxtActive]}>{c.label}</Text>
                  </Pressable>
                ))}
              </View>
            </ScrollView>

            <Text style={s.countLine}>
              {loading ? "Loading…" : `${filtered.length} employee${filtered.length === 1 ? "" : "s"}`}
            </Text>
          </View>
        }
        ListEmptyComponent={
          loading ? (
            <View style={s.emptyWrap}><ActivityIndicator color={colors.brandPrimary} /></View>
          ) : (
            <View style={s.emptyWrap}>
              <Ionicons name="file-tray-outline" size={36} color={colors.onSurfaceTertiary} />
              <Text style={s.emptyTxt}>No employees match this filter</Text>
            </View>
          )
        }
        ListFooterComponent={<View style={{ height: 40 }} />}
      />

      {/* Document validity editor */}
      <Modal transparent visible={!!editEmp} animationType="fade" onRequestClose={() => setEditEmp(null)}>
        <View style={s.modalRoot}>
          <Pressable style={s.backdrop} onPress={() => setEditEmp(null)} />
          <View style={s.modalCard}>
            <View style={s.modalHead}>
              <View style={{ flex: 1 }}>
                <Text style={s.modalTitle}>Document Validity</Text>
                <Text style={s.modalSub} numberOfLines={1}>
                  {editEmp?.name}{editEmp?.employee_code ? ` · #${editEmp.employee_code}` : ""}
                </Text>
              </View>
              <Pressable onPress={() => setEditEmp(null)} hitSlop={10}>
                <Ionicons name="close" size={22} color={colors.onSurfaceSecondary} />
              </Pressable>
            </View>

            <View style={s.modalSection}>
              <View style={s.modalDocRow}>
                <Ionicons name="car-outline" size={16} color={colors.brandPrimary} />
                <Text style={s.modalDocLabel}>Driving Licence</Text>
                <Text style={s.modalDocNo} numberOfLines={1}>{editEmp?.dl_number || "No number on record"}</Text>
              </View>
              <DateField
                value={dlDate}
                onChangeISO={setDlDate}
                label="DL Valid Upto"
                placeholder="DD-MM-YYYY"
                testID="dl-valid-upto"
              />
            </View>

            <View style={s.modalSection}>
              <View style={s.modalDocRow}>
                <Ionicons name="airplane-outline" size={16} color={colors.brandPrimary} />
                <Text style={s.modalDocLabel}>Passport</Text>
                <Text style={s.modalDocNo} numberOfLines={1}>{editEmp?.passport_no || "No number on record"}</Text>
              </View>
              <DateField
                value={ppDate}
                onChangeISO={setPpDate}
                label="Passport Valid Upto"
                placeholder="DD-MM-YYYY"
                testID="passport-valid-upto"
              />
            </View>

            <Pressable
              onPress={saveExpiry}
              disabled={saving}
              style={[s.saveBtn, saving && { opacity: 0.6 }]}
              testID="save-validity"
            >
              {saving ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <>
                  <Ionicons name="checkmark" size={16} color="#fff" />
                  <Text style={s.saveBtnTxt}>Save Validity Dates</Text>
                </>
              )}
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surfaceSecondary,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  back: {
    width: 38, height: 38, borderRadius: 12, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceTertiary,
  },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 1 },

  listContent: {
    padding: 16, width: "100%", maxWidth: 1100, alignSelf: "center",
  },

  statsRow: { flexDirection: "row", gap: 10 },
  statCard: {
    minWidth: 118, backgroundColor: colors.surfaceSecondary,
    borderRadius: 16, padding: 12,
    borderWidth: 1, borderColor: colors.border,
    ...Platform.select({
      web: { boxShadow: "0 1px 3px rgba(15,23,42,0.06)" } as any,
      default: { shadowColor: "#0F172A", shadowOpacity: 0.05, shadowRadius: 4, shadowOffset: { width: 0, height: 1 }, elevation: 1 },
    }),
  },
  statIconWrap: {
    width: 28, height: 28, borderRadius: 9, alignItems: "center", justifyContent: "center",
    marginBottom: 8,
  },
  statValue: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  statLabel: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2, fontWeight: "600" },

  searchWrap: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceSecondary, borderRadius: 14,
    borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: 12, height: 44, marginBottom: 12,
  },
  searchInput: {
    flex: 1, fontSize: 14, color: colors.onSurface,
    ...Platform.select({ web: { outlineStyle: "none" } as any, default: {} }),
  },

  chip: {
    paddingHorizontal: 14, height: 34, borderRadius: 17,
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12.5, fontWeight: "600", color: colors.onSurfaceSecondary },
  chipTxtActive: { color: "#fff" },

  countLine: { fontSize: 12, color: colors.onSurfaceTertiary, marginBottom: 8, fontWeight: "600" },

  row: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 16,
    borderWidth: 1, borderColor: colors.border,
    padding: 14, marginBottom: 10,
    ...Platform.select({
      web: { boxShadow: "0 1px 3px rgba(15,23,42,0.05)", cursor: "pointer" } as any,
      default: {},
    }),
  },
  rowTop: { flexDirection: "row", alignItems: "center", gap: 10 },
  avatar: {
    width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(37,99,235,0.10)",
  },
  avatarTxt: { fontSize: 16, fontWeight: "800", color: colors.brandPrimary },
  nameRow: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  name: { fontSize: 14.5, fontWeight: "700", color: colors.onSurface, maxWidth: 260 },
  codePill: {
    backgroundColor: colors.surfaceTertiary, borderRadius: 8, paddingHorizontal: 7, paddingVertical: 2,
  },
  codePillTxt: { fontSize: 10.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  statusPill: { borderRadius: 8, paddingHorizontal: 7, paddingVertical: 2 },
  statusPillTxt: { fontSize: 10, fontWeight: "800", letterSpacing: 0.4 },
  meta: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 2 },

  expiryBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderColor: "rgba(37,99,235,0.35)", borderRadius: 10,
    paddingHorizontal: 10, height: 32, backgroundColor: "rgba(37,99,235,0.06)",
  },
  expiryBtnTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },

  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 10 },
  docChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4,
  },
  docChipTxt: { fontSize: 11, fontWeight: "700" },
  uploadsPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4,
    backgroundColor: "rgba(37,99,235,0.08)",
  },
  uploadsPillTxt: { fontSize: 11, fontWeight: "700", color: colors.brandPrimary },

  emptyWrap: { alignItems: "center", paddingVertical: 48, gap: 10 },
  emptyTxt: { fontSize: 13, color: colors.onSurfaceTertiary },

  modalRoot: { flex: 1, alignItems: "center", justifyContent: "center", padding: 20 },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(15,23,42,0.45)" },
  modalCard: {
    width: "100%", maxWidth: 440, backgroundColor: colors.surfaceSecondary,
    borderRadius: radius?.lg ?? 18, padding: 18,
    ...Platform.select({
      web: { boxShadow: "0 20px 50px rgba(15,23,42,0.25)" } as any,
      default: { elevation: 8 },
    }),
  },
  modalHead: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 14 },
  modalTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  modalSub: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: 2 },
  modalSection: {
    backgroundColor: colors.surface, borderRadius: 14, padding: 12,
    borderWidth: 1, borderColor: colors.border, marginBottom: 12,
  },
  modalDocRow: { flexDirection: "row", alignItems: "center", gap: 7, marginBottom: 10 },
  modalDocLabel: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  modalDocNo: { flex: 1, fontSize: 11.5, color: colors.onSurfaceTertiary, textAlign: "right" },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7,
    backgroundColor: colors.brandPrimary, borderRadius: 14, height: 48, marginTop: 2,
  },
  saveBtnTxt: { fontSize: 14, fontWeight: "800", color: "#fff" },
});
