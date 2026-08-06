/**
 * Iter 145 — Punch Log Report (Utility).
 *
 * Full punch audit trail: every IN/OUT from biometric machines, the mobile
 * app, imports and admin manual entries. Filters: date range, firm and
 * machine. One-click Excel download of the filtered log.
 */
import React, { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Platform,
  Modal,
  Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import EmployeePhoto from "@/src/components/EmployeePhoto";
import ReportTable, { ReportCol } from "@/src/components/ReportTable";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";
import DateField from "@/src/components/DateField";

type Row = {
  record_id?: string;
  user_id?: string | null;
  date: string;
  time: string;
  kind: string;
  ot?: boolean;
  employee_code: string;
  name: string;
  name_in_machine: string;
  bio_code: string;
  machine_name: string;
  machine: string;
  machine_key: string;
  company_name: string;
  status: string;
  has_photo?: boolean;
  photo_ref?: string | null;
  // Iter 341 — "not_found" | "new_registration" | ""
  flag?: string;
};

type Machine = { key: string; label: string };

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}
function daysAgoIso(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

// Iter 496 — Universal Report Table engine columns (auto width, sticky
// code+name, ellipsis+tooltip, saved layout).
const COLS: ReportCol<Row>[] = [
  {
    key: "user_id", label: "", type: "center", min: 44, max: 44, sticky: true,
    render: (r) => (
      <View style={{ alignItems: "center", justifyContent: "center" }}>
        <EmployeePhoto
          userId={r.user_id}
          name={r.name}
          code={r.employee_code || r.bio_code}
          machine={r.machine_name || r.machine}
          size={28}
        />
      </View>
    ),
  },
  { key: "employee_code", label: "Code", type: "center", min: 64, sticky: true },
  {
    key: "name", label: "Employee", min: 200, max: 300, sticky: true,
    // Iter 503 (user request) — one-click "Register" on NOT-FOUND rows:
    // opens Add New Employee with Bio Code (+ machine name) pre-filled.
    render: (r) =>
      r.flag === "not_found" ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <Text style={{ fontSize: 11.5, fontWeight: "800", color: "#B91C1C" }} numberOfLines={1}>
            ⛔ {r.name || "NOT FOUND"}
          </Text>
          <Pressable
            onPress={() => (globalThis as any).__punchRegister?.(r)}
            hitSlop={6}
            testID={`plr-register-${r.bio_code}`}
            style={{
              flexDirection: "row", alignItems: "center",
              borderWidth: 1, borderColor: "#15803D", borderRadius: 999,
              paddingHorizontal: 8, paddingVertical: 2, backgroundColor: "#F0FDF4",
            }}
          >
            <Text style={{ fontSize: 10.5, fontWeight: "800", color: "#15803D" }}>➕ Register</Text>
          </Pressable>
        </View>
      ) : (
        <Text
          numberOfLines={1}
          style={{
            fontSize: 12,
            color: r.flag === "new_registration" ? "#15803D" : "#1E2A2A",
            fontWeight: r.flag === "new_registration" ? "800" : "400",
          }}
        >
          {r.flag === "new_registration" ? `${r.name} 🆕 NEW` : r.name || "—"}
        </Text>
      ),
    value: (r) =>
      r.flag === "not_found"
        ? `⛔ ${r.name || "NOT FOUND"}`
        : r.flag === "new_registration"
          ? `${r.name} 🆕 NEW`
          : r.name || "—",
    textStyle: (r) =>
      r.flag === "not_found"
        ? { fontWeight: "800", color: "#B91C1C" }
        : r.flag === "new_registration"
          ? { fontWeight: "800", color: "#15803D" }
          : null,
  },
  { key: "date", label: "Date", type: "date" },
  { key: "time", label: "Time", type: "center", min: 72 },
  {
    key: "kind", label: "IN/OUT", type: "center", min: 72,
    value: (r) => (r.kind || "").toUpperCase(),
    textStyle: (r) => ({
      fontWeight: "800",
      color: r.kind === "in" ? "#15803D" : "#B45309",
    }),
  },
  {
    key: "ot", label: "OT", type: "center", min: 90,
    value: (r) => (r.ot ? "⏱ OT PUNCH" : "—"),
    textStyle: (r) => (r.ot ? { fontWeight: "800", color: "#B45309" } : null),
  },
  { key: "name_in_machine", label: "Name in Machine", min: 140, max: 240 },
  { key: "bio_code", label: "Bio", type: "center", min: 54 },
  { key: "machine_name", label: "Machine Name", min: 110, max: 200 },
  { key: "machine", label: "Machine / Source", min: 130, max: 240 },
  { key: "company_name", label: "Firm", min: 130, max: 240 },
  { key: "status", label: "Status", type: "center", min: 84 },
  {
    key: "has_photo", label: "Photo", type: "center", min: 56,
    // Iter 503 (user request) — tap 📷 to VIEW the machine photo, incl.
    // "NOT FOUND IN MASTER" rows (parked ATTPHOTO of the unknown user).
    render: (r) => (
      r.has_photo && r.photo_ref ? (
        <Pressable
          onPress={() => (globalThis as any).__punchPhotoOpen?.(r)}
          hitSlop={8}
          style={{ alignItems: "center" }}
          testID={`plr-photo-${r.photo_ref}`}
        >
          <Text style={{ fontSize: 13 }}>📷</Text>
        </Pressable>
      ) : (
        <Text style={{ fontSize: 11, color: "#94A3B8", textAlign: "center" }}>—</Text>
      )
    ),
    value: (r) => (r.has_photo ? "📷" : "—"),
  },
];

export default function PunchLogReportScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { companies, selectedCompanyId } = useSelectedCompany();
  const isAdmin =
    user?.role === "super_admin" || user?.role === "sub_admin" || user?.role === "company_admin";

  const [fromDate, setFromDate] = useState<string>(daysAgoIso(7));
  const [toDate, setToDate] = useState<string>(todayIso());
  const [firmId, setFirmId] = useState<string>(selectedCompanyId || "");
  const [machine, setMachine] = useState<string>("");
  const [machines, setMachines] = useState<Machine[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [truncated, setTruncated] = useState(false);
  // Iter 503 — punch photo viewer (works for NOT FOUND rows too)
  const [photo, setPhoto] = useState<{ uri: string; caption: string } | null>(null);
  const [photoLoading, setPhotoLoading] = useState(false);
  useEffect(() => {
    (globalThis as any).__punchPhotoOpen = async (r: Row) => {
      if (!r.photo_ref) return;
      setPhotoLoading(true); setPhoto(null);
      try {
        const resp = await api<any>(`/admin/punch-logs/photo?ref=${encodeURIComponent(r.photo_ref)}`);
        setPhoto({
          uri: `data:image/jpeg;base64,${resp.photo_base64}`,
          caption: `${resp.caption || r.name} · ${r.date} ${r.time}`,
        });
      } catch {
        setPhoto(null);
      }
      setPhotoLoading(false);
    };
    return () => { (globalThis as any).__punchPhotoOpen = undefined; };
  }, []);
  // Iter 503 — one-click "Register this employee" from a NOT-FOUND row.
  useEffect(() => {
    (globalThis as any).__punchRegister = (r: Row) => {
      const qs = new URLSearchParams();
      if (r.bio_code) qs.set("prefill_bio", r.bio_code);
      if (r.name_in_machine) qs.set("prefill_name", r.name_in_machine);
      router.push(`/employee-add?${qs.toString()}` as any);
    };
    return () => { (globalThis as any).__punchRegister = undefined; };
  }, [router]);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const showMsg = (m: string) => {
    if (Platform.OS === "web") globalThis.alert(m);
  };

  const qs = (withMachine: boolean) => {
    const p = new URLSearchParams();
    if (fromDate) p.set("from_date", fromDate);
    if (toDate) p.set("to_date", toDate);
    if (firmId) p.set("company_id", firmId);
    if (withMachine && machine) p.set("machine", machine);
    return p.toString();
  };

  const fetchLog = async (withMachine = true) => {
    setLoading(true);
    try {
      const r = await api<{
        rows: Row[];
        total: number;
        truncated: boolean;
        machines: Machine[];
      }>(`/admin/punch-logs?${qs(withMachine)}`);
      setRows(r.rows || []);
      setTotal(r.total || 0);
      setTruncated(!!r.truncated);
      if (!withMachine || !machine) setMachines(r.machines || []);
    } catch (e: any) {
      showMsg(e?.message || "Failed to load punch log");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchLog(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // Iter 253 (user request) — changing the Firm refreshes the Machine list
  // for THAT firm and resets the on-screen data / download state.
  const firmFirstRun = useRef(true);
  useEffect(() => {
    if (firmFirstRun.current) { firmFirstRun.current = false; return; }
    setMachine("");
    setRows([]);
    setTotal(0);
    setTruncated(false);
    setMachines([]);
    fetchLog(false); // reload for the new firm; repopulates its machines
  }, [firmId]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Iter 252 (user request) — pull machine punches UP TO DATE: asks every
  // connected machine to re-upload all stored punches, then refresh.
  const [syncing, setSyncing] = useState(false);
  const syncMachines = async () => {
    if (syncing) return;
    setSyncing(true);
    try {
      const params = firmId ? `?company_id=${firmId}` : "";
      const r = await api<{ ok: boolean; message: string }>(
        `/biometric/devices/resync-all${params}`,
        { method: "POST" },
      );
      showMsg(r.message);
    } catch (e: any) {
      showMsg(e?.message || "Sync request failed");
    } finally {
      setSyncing(false);
    }
  };

  const downloadXlsx = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      const res = await apiBinary(`/admin/punch-logs.xlsx?${qs(true)}`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = `Punch_Log_${fromDate}_${toDate}.xlsx`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      showMsg(e?.message || "Download failed");
    } finally {
      setDownloading(false);
    }
  };

  if (!isAdmin) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <Text style={styles.subtitle}>Admin access only.</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="plog-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Punch Log Report</Text>
          <Text style={styles.subtitle}>
            Every punch — machine, app, import &amp; manual — by date, machine and firm
          </Text>
        </View>
        <Pressable
          onPress={syncMachines}
          style={[styles.dlBtn, { backgroundColor: "#16a34a" }, syncing && { opacity: 0.6 }]}
          disabled={syncing}
          testID="plog-sync-machines"
        >
          {syncing ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <Ionicons name="sync-outline" size={16} color="#fff" />
          )}
          <Text style={styles.dlBtnTxt}>Sync from machines</Text>
        </Pressable>
        <Pressable
          onPress={downloadXlsx}
          style={[styles.dlBtn, downloading && { opacity: 0.6 }]}
          disabled={downloading}
          testID="plog-download"
        >
          {downloading ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <Ionicons name="download-outline" size={16} color="#fff" />
          )}
          <Text style={styles.dlBtnTxt}>Download Excel</Text>
        </Pressable>
      </View>

      {/* Filters */}
      <View style={styles.filterCard}>
        <View style={styles.filterRow}>
          <View style={{ width: 150 }}>
            <Text style={styles.lbl}>From</Text>
            <DateField value={fromDate} onChangeISO={setFromDate} testID="plog-from" />
          </View>
          <View style={{ width: 150 }}>
            <Text style={styles.lbl}>To</Text>
            <DateField value={toDate} onChangeISO={setToDate} testID="plog-to" />
          </View>
          {user?.role !== "company_admin" ? (
            <View style={{ minWidth: 200 }}>
              <Text style={styles.lbl}>Firm</Text>
              {Platform.OS === "web" ? (
                <select
                  value={firmId}
                  onChange={(e) => setFirmId((e.target as HTMLSelectElement).value)}
                  style={styles.select as any}
                >
                  <option value="">All firms</option>
                  {companies.map((c: any) => (
                    <option key={c.company_id} value={c.company_id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              ) : null}
            </View>
          ) : null}
          <View style={{ minWidth: 200 }}>
            <Text style={styles.lbl}>Machine / Source</Text>
            {Platform.OS === "web" ? (
              <select
                value={machine}
                onChange={(e) => setMachine((e.target as HTMLSelectElement).value)}
                style={styles.select as any}
              >
                <option value="">All machines / sources</option>
                {machines.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.label}
                  </option>
                ))}
              </select>
            ) : null}
          </View>
          <Pressable onPress={() => fetchLog(true)} style={styles.applyBtn} testID="plog-apply">
            <Ionicons name="search-outline" size={15} color="#fff" />
            <Text style={styles.applyTxt}>Apply</Text>
          </Pressable>
        </View>
        <Text style={styles.countTxt}>
          {loading ? "Loading…" : `${total} punch${total === 1 ? "" : "es"}`}
          {truncated ? " (showing first 2000 — use Download Excel for the full log)" : ""}
        </Text>
      </View>

      {/* Grid — Iter 496: Universal Report Table engine */}
      <ReportTable<Row>
        reportKey="punch_log"
        columns={COLS}
        rows={rows}
        loading={loading}
        emptyText="No punches found for the selected filters."
        rowStyle={(r) =>
          r.flag === "not_found"
            ? { backgroundColor: "#FEF2F2" }
            : r.flag === "new_registration"
              ? { backgroundColor: "#F0FDF4" }
              : null
        }
      />
      {/* Iter 503 — punch photo viewer */}
      <Modal visible={!!photo || photoLoading} transparent animationType="fade"
        onRequestClose={() => { setPhoto(null); setPhotoLoading(false); }}>
        <Pressable
          style={{ flex: 1, backgroundColor: "rgba(15,23,42,0.82)", alignItems: "center", justifyContent: "center", padding: 14 }}
          onPress={() => { setPhoto(null); setPhotoLoading(false); }}>
          {photoLoading ? (
            <ActivityIndicator size="large" color="#fff" />
          ) : photo ? (
            <View style={{ alignItems: "center" }}>
              <Image source={{ uri: photo.uri }} resizeMode="contain"
                style={{ width: 520, height: 520, maxWidth: "95%", borderRadius: 10, backgroundColor: "#000" }} />
              <Text style={{ color: "#fff", fontSize: 12.5, fontWeight: "700", marginTop: 10, textAlign: "center" }}>
                {photo.caption}
              </Text>
              <Text style={{ color: "#CBD5E1", fontSize: 11, marginTop: 3 }}>tap anywhere to close</Text>
            </View>
          ) : null}
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  backBtn: { padding: 6 },
  title: { fontSize: type.lg, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: type.xs, color: colors.onSurfaceSecondary },
  dlBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  dlBtnTxt: { color: "#fff", fontWeight: "800", fontSize: type.sm },
  filterCard: {
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  filterRow: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, flexWrap: "wrap" },
  lbl: { fontSize: type.xs, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  select: {
    height: 38,
    borderRadius: 8,
    border: `1px solid ${colors.border}`,
    paddingHorizontal: 8,
    paddingVertical: 0,
    backgroundColor: colors.surface,
    color: colors.onSurface,
    fontSize: 13,
  },
  applyBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brand,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    height: 38,
  },
  applyTxt: { color: "#fff", fontWeight: "800", fontSize: type.sm },
  countTxt: { marginTop: 8, fontSize: type.xs, color: colors.onSurfaceSecondary },
  headRow: {
    flexDirection: "row",
    backgroundColor: colors.surfaceSecondary,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    paddingVertical: 8,
    paddingHorizontal: spacing.sm,
  },
  headCell: { fontSize: type.xs, fontWeight: "800", color: colors.onSurfaceSecondary },
  row: {
    flexDirection: "row",
    paddingVertical: 7,
    paddingHorizontal: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  rowAlt: { backgroundColor: colors.surfaceSecondary },
  cell: { fontSize: type.xs, color: colors.onSurface, paddingRight: 6 },
  empty: {
    textAlign: "center",
    marginTop: 40,
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
  },
});
