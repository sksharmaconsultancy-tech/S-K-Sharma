/**
 * Location Audit — Iter 64.
 *
 * Admin-only investigative view of punch locations. For every punch it
 * shows:
 *   • Employee + firm
 *   • Time / date / IN|OUT
 *   • Location pill (inside / outside / no-gps)
 *   • Distance from office
 *   • Biometric method + record source
 *   • Optional outside_note (why it was flagged)
 *
 * Filters: Company (multi-firm) · Employee · Date range · Location status.
 * Export: single-click XLSX.
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
import { useOnRefresh } from "@/src/context/RefreshBusContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import MultiCompanyPicker from "@/src/components/MultiCompanyPicker";
import LocationPill from "@/src/components/LocationPill";
import { colors, radius, spacing, type } from "@/src/theme";

type Rec = {
  record_id: string;
  date: string;
  at: string;
  kind: "in" | "out";
  distance_m?: number | null;
  latitude?: number | null;
  longitude?: number | null;
  location_status?: "inside" | "outside" | "no-gps" | string;
  biometric_method?: string;
  source?: string;
  status?: string;
  outside_note?: string | null;
  user_name?: string;
  employee_code?: string;
  company_name?: string;
};

type Resp = {
  records: Rec[];
  count: number;
  summary: { inside: number; outside: number; "no-gps": number };
};

function fmtTime(iso?: string) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function fmtDate(d?: string) {
  if (!d) return "—";
  try {
    const dt = new Date(d + "T00:00:00Z");
    return dt.toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
      year: "2-digit",
    });
  } catch {
    return d;
  }
}

function showMsg(msg: string, title = "Location Audit") {
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

const STATUS_TABS: {
  key: "" | "inside" | "outside" | "no-gps";
  label: string;
}[] = [
  { key: "", label: "All" },
  { key: "inside", label: "Inside" },
  { key: "outside", label: "Outside" },
  { key: "no-gps", label: "No-GPS" },
];

export default function LocationAuditScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isAdminish = user?.role === "super_admin" || user?.role === "sub_admin" || user?.role === "company_admin";
  const { selectedCompanyId: globalCid } = useSelectedCompany();

  // Iter 64 — multi-firm mode. Reuses the shared MultiCompanyPicker.
  const [crossFirmMode, setCrossFirmMode] = useState(false);
  const [crossFirmSet, setCrossFirmSet] = useState<Set<string>>(new Set());
  const [companyId, setCompanyId] = useState<string>(globalCid || "");
  useEffect(() => setCompanyId(globalCid || ""), [globalCid]);

  const [empQuery, setEmpQuery] = useState("");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<"" | "inside" | "outside" | "no-gps">("");

  const [rows, setRows] = useState<Rec[]>([]);
  const [summary, setSummary] = useState<Resp["summary"] | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const queryString = useCallback(() => {
    const qs: string[] = [];
    if (crossFirmMode) {
      for (const c of Array.from(crossFirmSet)) {
        qs.push(`company_ids=${encodeURIComponent(c)}`);
      }
    } else if (companyId) {
      qs.push(`company_id=${encodeURIComponent(companyId)}`);
    }
    if (dateFrom) qs.push(`date_from=${encodeURIComponent(dateFrom)}`);
    if (dateTo) qs.push(`date_to=${encodeURIComponent(dateTo)}`);
    if (statusFilter) qs.push(`location_status=${encodeURIComponent(statusFilter)}`);
    return qs.length ? `?${qs.join("&")}` : "";
  }, [crossFirmMode, crossFirmSet, companyId, dateFrom, dateTo, statusFilter]);

  const load = useCallback(async () => {
    if (!isAdminish) return;
    if (crossFirmMode && crossFirmSet.size === 0) {
      setRows([]);
      setSummary({ inside: 0, outside: 0, "no-gps": 0 });
      return;
    }
    setLoading(true);
    try {
      const r = await api<Resp>(`/admin/attendance/location-audit${queryString()}`);
      setRows(r.records || []);
      setSummary(r.summary || null);
    } catch (e: any) {
      showMsg(e?.message || "Could not load");
    } finally {
      setLoading(false);
    }
  }, [isAdminish, crossFirmMode, crossFirmSet, queryString]);

  useEffect(() => {
    void load();
  }, [load]);
  useOnRefresh(load);

  const filteredRows = useMemo(() => {
    const q = empQuery.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        (r.user_name || "").toLowerCase().includes(q) ||
        (r.employee_code || "").toLowerCase().includes(q),
    );
  }, [rows, empQuery]);

  const doDownload = async () => {
    setDownloading(true);
    try {
      await downloadBinary(
        `/admin/attendance/location-audit.xlsx${queryString()}`,
        `LocationAudit_${new Date().toISOString().slice(0, 10)}.xlsx`,
      );
    } finally {
      setDownloading(false);
    }
  };

  if (!isAdminish) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Only admins can access location audit.</Text>
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
            <Text style={styles.h1}>Location Audit</Text>
            <Text style={styles.hsub}>
              Where every punch was captured · inside / outside / biometric-only
            </Text>
          </View>
          <Pressable
            onPress={doDownload}
            disabled={downloading || rows.length === 0}
            style={[styles.dlBtn, (downloading || rows.length === 0) && { opacity: 0.5 }]}
            testID="la-download"
          >
            {downloading ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Ionicons name="download-outline" size={16} color="#fff" />
            )}
            <Text style={styles.dlBtnTxt}>{downloading ? "…" : "Excel"}</Text>
          </Pressable>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Summary cards */}
        {summary ? (
          <View style={styles.sumRow}>
            <SumCard
              label="Inside office"
              value={summary.inside}
              tone="inside"
            />
            <SumCard
              label="Outside office"
              value={summary.outside}
              tone="outside"
            />
            <SumCard
              label="Biometric-only"
              value={summary["no-gps"]}
              tone="no-gps"
            />
          </View>
        ) : null}

        {/* Filters */}
        <View style={styles.card}>
          <View style={styles.filterRow}>
            <Pressable
              onPress={() => {
                const next = !crossFirmMode;
                setCrossFirmMode(next);
                if (next && crossFirmSet.size === 0 && globalCid) {
                  setCrossFirmSet(new Set([globalCid]));
                }
              }}
              style={styles.crossToggle}
              testID="la-cross-toggle"
            >
              <Ionicons
                name={crossFirmMode ? "checkbox" : "square-outline"}
                size={16}
                color={crossFirmMode ? colors.brandPrimary : colors.onSurfaceSecondary}
              />
              <Text style={styles.crossToggleTxt}>Multi-firm</Text>
            </Pressable>
          </View>

          <View style={styles.gridRow}>
            <View style={styles.gridCol}>
              <Text style={styles.label}>
                {crossFirmMode ? "Firms (multi-select)" : "Company"}
              </Text>
              {crossFirmMode ? (
                <MultiCompanyPicker
                  value={crossFirmSet}
                  onChange={setCrossFirmSet}
                  testID="la-multi-picker"
                />
              ) : (
                <Text style={styles.hintNote}>
                  Current firm ·{" "}
                  <Text style={{ fontWeight: "700" }}>
                    {user?.company_name || "—"}
                  </Text>
                </Text>
              )}
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Date from</Text>
              {Platform.OS === "web" ? (
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom((e.target as HTMLInputElement).value)}
                  style={styles.dateInput as any}
                />
              ) : (
                <TextInput
                  value={dateFrom}
                  onChangeText={setDateFrom}
                  placeholder="YYYY-MM-DD"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                />
              )}
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Date to</Text>
              {Platform.OS === "web" ? (
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo((e.target as HTMLInputElement).value)}
                  style={styles.dateInput as any}
                />
              ) : (
                <TextInput
                  value={dateTo}
                  onChangeText={setDateTo}
                  placeholder="YYYY-MM-DD"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                />
              )}
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Employee search</Text>
              <TextInput
                value={empQuery}
                onChangeText={setEmpQuery}
                placeholder="Name or code…"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.input}
              />
            </View>
          </View>

          <View style={styles.statusRow}>
            {STATUS_TABS.map((t) => (
              <Pressable
                key={t.key || "all"}
                onPress={() => setStatusFilter(t.key)}
                style={[
                  styles.statusChip,
                  statusFilter === t.key && styles.statusChipActive,
                ]}
              >
                <Text
                  style={[
                    styles.statusChipTxt,
                    { color: statusFilter === t.key ? "#fff" : colors.onSurfaceSecondary },
                  ]}
                >
                  {t.label}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>

        {/* Results */}
        {loading ? (
          <ActivityIndicator style={{ marginTop: 20 }} />
        ) : filteredRows.length === 0 ? (
          <View style={styles.card}>
            <Text style={styles.emptyTxt}>No records match the current filters.</Text>
          </View>
        ) : (
          <View style={styles.card}>
            <Text style={styles.count}>
              {filteredRows.length} punch{filteredRows.length === 1 ? "" : "es"}
            </Text>
            {filteredRows.map((r) => (
              <View key={r.record_id} style={styles.row}>
                <View style={styles.rowMain}>
                  <View style={styles.rowLeft}>
                    <Text style={styles.rowName}>
                      {r.user_name || "—"}
                      {r.employee_code ? (
                        <Text style={styles.rowCode}> · {r.employee_code}</Text>
                      ) : null}
                    </Text>
                    <Text style={styles.rowSub}>
                      {r.company_name || "—"} · {fmtDate(r.date)} · {fmtTime(r.at)}
                    </Text>
                    {r.outside_note ? (
                      <Text style={styles.outsideNote}>{r.outside_note}</Text>
                    ) : null}
                  </View>
                  <View style={styles.rowRight}>
                    <View style={[styles.kindPill, r.kind === "in" ? styles.kindIn : styles.kindOut]}>
                      <Ionicons
                        name={r.kind === "in" ? "arrow-down-circle" : "arrow-up-circle"}
                        size={12}
                        color="#fff"
                      />
                      <Text style={styles.kindTxt}>{r.kind === "in" ? "IN" : "OUT"}</Text>
                    </View>
                  </View>
                </View>
                <View style={styles.rowMeta}>
                  <LocationPill
                    status={r.location_status}
                    distanceM={r.distance_m}
                    showDistance
                  />
                  <Text style={styles.metaTxt}>
                    <Ionicons
                      name={r.biometric_method === "face" ? "happy-outline" : "finger-print-outline"}
                      size={11}
                      color={colors.onSurfaceSecondary}
                    />{" "}
                    {r.biometric_method || "—"}
                  </Text>
                  <Text style={styles.metaTxt}>
                    <Ionicons name="cog-outline" size={11} color={colors.onSurfaceSecondary} />{" "}
                    {(r.source || "manual").replace(/_/g, " ")}
                  </Text>
                  {r.status && r.status !== "approved" ? (
                    <Text style={[styles.metaTxt, { color: "#B45309", fontWeight: "700" }]}>
                      {r.status.toUpperCase()}
                    </Text>
                  ) : null}
                </View>
              </View>
            ))}
          </View>
        )}

        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

function SumCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "inside" | "outside" | "no-gps";
}) {
  const tones = {
    inside: { bg: "#DCFCE7", fg: "#166534" },
    outside: { bg: "#FEF3C7", fg: "#92400E" },
    "no-gps": { bg: "#E5E7EB", fg: "#374151" },
  };
  const t = tones[tone];
  return (
    <View style={[styles.sumCard, { backgroundColor: t.bg }]}>
      <Text style={[styles.sumVal, { color: t.fg }]}>{value}</Text>
      <Text style={[styles.sumLbl, { color: t.fg }]}>{label}</Text>
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
  dlBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: colors.brandPrimary,
  },
  dlBtnTxt: { color: "#fff", fontSize: 12, fontWeight: "800" },
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
  sumRow: { flexDirection: "row", gap: 8, marginBottom: spacing.md, flexWrap: "wrap" },
  sumCard: {
    flex: 1,
    minWidth: 130,
    padding: spacing.md,
    borderRadius: radius.lg,
    alignItems: "center",
  },
  sumVal: { fontSize: 28, fontWeight: "800" },
  sumLbl: { fontSize: 12, fontWeight: "700", marginTop: 2 },
  filterRow: { flexDirection: "row", justifyContent: "flex-end", marginBottom: 8 },
  crossToggle: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 4 },
  crossToggleTxt: { color: colors.onSurface, fontSize: 12, fontWeight: "700" },
  gridRow: { flexDirection: "row", gap: 12, flexWrap: "wrap" },
  gridCol: { flex: 1, minWidth: 180 },
  hintNote: {
    color: colors.onSurfaceSecondary,
    fontSize: 12,
    paddingVertical: 10,
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
  dateInput: {
    padding: 10,
    borderRadius: 8,
    borderColor: colors.borderStrong,
    borderWidth: 1,
    fontSize: 14,
    width: "100%",
  },
  statusRow: { flexDirection: "row", gap: 6, marginTop: 12, flexWrap: "wrap" },
  statusChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  statusChipActive: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  statusChipTxt: { fontSize: 12, fontWeight: "700" },
  count: { color: colors.onSurfaceSecondary, fontSize: 11, marginBottom: 8, fontWeight: "700" },
  row: {
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  rowMain: { flexDirection: "row", alignItems: "center", gap: 8 },
  rowLeft: { flex: 1 },
  rowRight: { alignItems: "flex-end" },
  rowName: { color: colors.onSurface, fontSize: 14, fontWeight: "700" },
  rowCode: { color: colors.onSurfaceSecondary, fontSize: 12, fontWeight: "500" },
  rowSub: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 2 },
  outsideNote: {
    color: "#92400E",
    fontSize: 11,
    marginTop: 3,
    fontStyle: "italic",
  },
  rowMeta: {
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
    marginTop: 6,
    flexWrap: "wrap",
  },
  metaTxt: { color: colors.onSurfaceSecondary, fontSize: 11 },
  kindPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
  },
  kindIn: { backgroundColor: "#065F46" },
  kindOut: { backgroundColor: "#7A4E00" },
  kindTxt: { color: "#fff", fontSize: 10, fontWeight: "800" },
  emptyTxt: {
    color: colors.onSurfaceSecondary,
    fontSize: 13,
    textAlign: "center",
    paddingVertical: spacing.md,
  },
});
