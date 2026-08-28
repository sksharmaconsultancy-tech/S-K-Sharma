import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
  Switch,
  TextInput,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useLiveSync } from "@/src/api/live-sync";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, shadow, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };

type SyncStatus = {
  total_devices: number;
  online_devices: number;
  offline_devices: number;
  pending_sync: number;
  processing: number;
  employees_synced: number;
  failed_sync: number;
  current_queue: number;
  last_sync_time: string | null;
  open_conflicts: number;
};

type Job = {
  job_id: string;
  name?: string;
  pin?: string;
  action: string;
  status: string;
  attempts: number;
  targets?: string[];
  created_at: string;
  updated_at: string;
  error?: string | null;
};

type LogRow = {
  log_id: string;
  device_serial: string;
  pin?: string;
  action: string;
  command: string;
  status: string;
  error?: string | null;
  created_at: string;
};

type Conflict = {
  conflict_id: string;
  pin: string;
  kind: string;
  device_serial: string;
  detail: string;
  created_at: string;
};

type Machine = {
  device_id: string;
  serial_number: string;
  name?: string;
  brand?: string;
  model?: string;
  kind?: string;
  enabled?: boolean;
  sync_enabled?: boolean;
  online: boolean;
  last_seen_at?: string | null;
  employees_on_machine?: number | null;
  fp_count?: number | null;
  att_log_count?: number | null;
  firmware?: string | null;
  device_ip?: string | null;
  pending_cmds: number;
};

type Settings = {
  enable_auto_sync: boolean;
  // Iter 584 — final sync rules
  machine_to_payroll_punch_sync?: boolean;
  machine_to_machine_sync?: boolean;
  manual_employee_registration?: boolean;
  manual_employee_delete?: boolean;
  auto_master_sync?: string;
  sync_fingerprints: boolean;
  sync_face: boolean;
  sync_card: boolean;
  sync_password: boolean;
  sync_photos: boolean;
  retry_failed: boolean;
  max_retry_count: number;
  sync_interval: number;
};

const TABS = ["Dashboard", "Machines", "Queue", "History", "Settings", "Conflicts"] as const;
type Tab = (typeof TABS)[number];

const STATUS_COLORS: Record<string, string> = {
  pending: "#B45309",
  retry: "#B45309",
  processing: "#1D4ED8",
  success: "#16A34A",
  failed: "#DC2626",
  cancelled: "#6B7280",
  queued: "#1D4ED8",
};

function fmtTime(iso?: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const g = (x: number) => String(x).padStart(2, "0");
    return `${g(d.getDate())}-${d.toLocaleString("en", { month: "short" })} ${g(d.getHours())}:${g(d.getMinutes())}`;
  } catch {
    return iso;
  }
}

export default function SyncEngineScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const canManage =
    user?.role === "super_admin" ||
    user?.role === "company_admin" ||
    (user?.role as string) === "sub_admin";
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  const [tab, setTab] = useState<Tab>("Dashboard");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [companies, setCompanies] = useState<Company[]>([]);
  // Iter 419 (user request) — always open with the firm currently selected
  // in the top bar, and follow it when the admin switches firms.
  const { selectedCompanyId } = useSelectedCompany();
  const [companyId, setCompanyId] = useState<string>("");
  useEffect(() => {
    if (isSuper && selectedCompanyId) setCompanyId(selectedCompanyId);
  }, [isSuper, selectedCompanyId]);
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [logs, setLogs] = useState<LogRow[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [machines, setMachines] = useState<Machine[]>([]);
  // Iter 768 — Machine → Machine sync log report rows.
  const [m2mLogs, setM2mLogs] = useState<any[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const qs = useMemo(
    () => (isSuper && companyId ? `?company_id=${companyId}` : ""),
    [isSuper, companyId],
  );

  const loadCompanies = useCallback(async () => {
    if (!isSuper) return;
    try {
      const c = await api<{ companies: Company[] }>("/companies?lite=1");
      setCompanies(c.companies || []);
      setCompanyId((prev) =>
        prev || selectedCompanyId || (c.companies?.[0]?.company_id ?? ""));
    } catch {}
  }, [isSuper, selectedCompanyId]);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api<SyncStatus>(`/sync/status${qs}`));
    } catch {}
  }, [qs]);

  const loadAll = useCallback(async () => {
    try {
      const [s, j, l, cf, st, mc, ml] = await Promise.all([
        api<SyncStatus>(`/sync/status${qs}`),
        api<{ jobs: Job[] }>(`/queue${qs}${qs ? "&" : "?"}limit=100`),
        api<{ logs: LogRow[] }>(`/sync/logs${qs}${qs ? "&" : "?"}limit=150`),
        api<{ conflicts: Conflict[] }>(`/sync/conflicts${qs}`),
        api<Settings>(`/sync/settings${qs}`),
        api<{ machines: Machine[] }>(`/sync/machines/overview${qs}`),
        api<{ logs: any[] }>(`/sync/machines/logs${qs}${qs ? "&" : "?"}limit=50`),
      ]);
      setStatus(s);
      setJobs(j.jobs || []);
      setLogs(l.logs || []);
      setConflicts(cf.conflicts || []);
      setSettings(st);
      setMachines(mc.machines || []);
      setM2mLogs(ml.logs || []);
    } catch (e: any) {
      setBanner(e?.message || "Failed to load sync data");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [qs]);

  useEffect(() => {
    if (!canManage) return;
    loadCompanies();
  }, [canManage, loadCompanies]);

  useEffect(() => {
    if (!canManage) return;
    if (isSuper && !companyId) return;
    setLoading(true);
    loadAll();
    const t = setInterval(loadStatus, 10000);
    return () => clearInterval(t);
  }, [canManage, isSuper, companyId, loadAll, loadStatus]);

  useLiveSync(user?.company_id || null, (ev) => {
    if (String(ev.type).startsWith("sync.") || String(ev.type).startsWith("attendance.")) {
      loadStatus();
    }
  });

  const flash = (msg: string) => {
    setBanner(msg);
    setTimeout(() => setBanner(null), 4000);
  };

  // Iter 541 — delete-from-machine helpers
  const [delCode, setDelCode] = useState("");
  const cidBody = () =>
    (isSuper && companyId ? { company_id: companyId } : {});
  const deleteOneFromMachines = async () => {
    const code = delCode.trim();
    if (!code) { flash("Enter the Emp Code or Bio Code first"); return; }
    setBusy(true);
    try {
      // resolve first (try employee code, then bio code) for a named confirm
      let r: any;
      try {
        r = await api<any>("/sync/delete-employee", {
          method: "POST",
          body: { ...cidBody(), employee_code: code, dry_run: true } });
      } catch {
        r = await api<any>("/sync/delete-employee", {
          method: "POST",
          body: { ...cidBody(), bio_code: code, dry_run: true } });
      }
      const emp = r.employee;
      const ok = Platform.OS === "web"
        ? window.confirm(
            `Delete "${emp.name}" (Code ${emp.employee_code} · Bio ${emp.bio_code}) ` +
            "from ALL sync-enabled machines of this firm?\n\n" +
            "They will no longer be able to punch. Portal data is NOT touched.")
        : true;
      if (!ok) return;
      const res = await api<any>("/sync/delete-employee", {
        method: "POST", body: { ...cidBody(), user_id: emp.user_id } });
      flash(`Delete queued for ${res.employee?.name || code}`);
      setDelCode("");
      loadAll();
    } catch (e: any) {
      flash(e?.message || "Employee not found");
    } finally {
      setBusy(false);
    }
  };
  const deleteLeftFromMachines = async () => {
    setBusy(true);
    try {
      const r = await api<any>("/sync/delete-left", {
        method: "POST", body: { ...cidBody(), dry_run: true } });
      if (!r.count) { flash("No LEFT employees with a Bio Code found"); return; }
      const names = (r.employees || []).slice(0, 10)
        .map((e: any) => `${e.employee_code} ${e.name}`).join("\n");
      const ok = Platform.OS === "web"
        ? window.confirm(
            `${r.count} LEFT employee(s) will be DELETED from all machines:\n\n` +
            names + (r.count > 10 ? `\n…and ${r.count - 10} more` : "") +
            "\n\nProceed?")
        : true;
      if (!ok) return;
      const res = await api<any>("/sync/delete-left", {
        method: "POST", body: cidBody() });
      flash(`Queued machine-delete for ${res.queued} LEFT employee(s)`);
      loadAll();
    } catch (e: any) {
      flash(e?.message || "Action failed");
    } finally {
      setBusy(false);
    }
  };

  // Iter 584 — Employee Device Management (manual register / delete)
  const [edmCode, setEdmCode] = useState("");
  const [edmPreview, setEdmPreview] = useState<any>(null);
  const [edmSel, setEdmSel] = useState<Set<string>>(new Set());
  const [edmFields, setEdmFields] = useState<Set<string>>(new Set());
  const [edmActivity, setEdmActivity] = useState<any[]>([]);
  const loadEdmActivity = useCallback(async () => {
    try {
      const r = await api<{ jobs: any[] }>(`/device-sync/activity${qs}`);
      setEdmActivity(r.jobs || []);
    } catch {}
  }, [qs]);
  useEffect(() => { if (canManage && (!isSuper || companyId)) void loadEdmActivity(); }, [canManage, isSuper, companyId, loadEdmActivity]);
  const loadEdmPreview = async () => {
    const code = edmCode.trim();
    if (!code) { flash("Enter the Employee Code first"); return; }
    setBusy(true);
    setEdmPreview(null);
    try {
      const r = await api<any>(
        `/device-sync/registration-preview${qs}${qs ? "&" : "?"}employee_code=${encodeURIComponent(code)}`);
      setEdmPreview(r);
      setEdmSel(new Set());
      const f = new Set<string>();
      (["card", "password", "fingerprint", "face"] as const).forEach((k) => {
        if (r.fields?.[k]?.available) f.add(k);
      });
      setEdmFields(f);
    } catch (e: any) {
      flash(e?.message || "Employee not found");
    } finally {
      setBusy(false);
    }
  };
  const edmToggleSel = (sn: string) => {
    const s = new Set(edmSel);
    if (s.has(sn)) s.delete(sn); else s.add(sn);
    setEdmSel(s);
  };
  const edmToggleField = (k: string) => {
    const s = new Set(edmFields);
    if (s.has(k)) s.delete(k); else s.add(k);
    setEdmFields(s);
  };
  const edmRegister = async () => {
    if (!edmPreview || edmSel.size === 0) { flash("Select at least one machine"); return; }
    const dup = edmPreview.machines.filter((m: any) => edmSel.has(m.serial_number) && m.already_registered);
    let updateExisting = false;
    if (dup.length) {
      const ok = Platform.OS === "web"
        ? window.confirm(
            `Employee already exists on: ${dup.map((m: any) => m.name || m.serial_number).join(", ")}.\n\n` +
            "OK = Update Device User · Cancel = abort")
        : true;
      if (!ok) return;
      updateExisting = true;
    }
    const ok2 = Platform.OS === "web"
      ? window.confirm(
          `CONFIRM & REGISTER\n\nEmployee: ${edmPreview.employee.employee_code} - ${edmPreview.employee.name}\n` +
          `Device User ID: ${edmPreview.employee.device_user_id}\n` +
          `Machines: ${Array.from(edmSel).join(", ")}\n` +
          `Data to send: Name, Employee Code, Device User ID${edmFields.size ? ", " + Array.from(edmFields).join(", ") : ""}`)
      : true;
    if (!ok2) return;
    setBusy(true);
    try {
      const r = await api<any>("/device-sync/manual-register-employee", {
        method: "POST",
        body: { ...cidBody(), user_id: edmPreview.employee.user_id,
                device_serials: Array.from(edmSel),
                fields: Array.from(edmFields),
                update_existing: updateExisting },
      });
      flash(`${r.status}: registration queued on ${r.machines.length} machine(s)`);
      setEdmPreview(null);
      setEdmCode("");
      loadAll();
      loadEdmActivity();
    } catch (e: any) {
      flash(e?.message || "Registration failed");
    } finally {
      setBusy(false);
    }
  };
  const edmDelete = async (allRegistered: boolean) => {
    if (!edmPreview) return;
    if (!allRegistered && edmSel.size === 0) { flash("Select at least one machine"); return; }
    let confirmCode: string | undefined;
    if (allRegistered && Platform.OS === "web") {
      confirmCode = window.prompt(
        `Delete ${edmPreview.employee.name} from ALL machines where registered ` +
        `(${(edmPreview.registered_on || []).join(", ") || "none"})?\n\n` +
        "Type the Employee Code to confirm:") || undefined;
      if (!confirmCode) return;
    }
    const ok = Platform.OS === "web" && !allRegistered
      ? window.confirm(
          `CONFIRM DELETE FROM MACHINE\n\nEmployee: ${edmPreview.employee.employee_code} - ${edmPreview.employee.name}\n` +
          `Device User ID: ${edmPreview.employee.device_user_id}\n` +
          `Machines: ${Array.from(edmSel).join(", ")}\n\n` +
          "Payroll employee, attendance & salary history are NOT touched.")
      : true;
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api<any>("/device-sync/manual-delete-employee", {
        method: "POST",
        body: { ...cidBody(), user_id: edmPreview.employee.user_id,
                ...(allRegistered
                  ? { all_registered: true, confirm_code: confirmCode }
                  : { device_serials: Array.from(edmSel) }) },
      });
      flash(`${r.status}: machine delete queued (${r.machines.length} machine(s)) — payroll unchanged`);
      setEdmPreview(null);
      setEdmCode("");
      loadAll();
      loadEdmActivity();
    } catch (e: any) {
      flash(e?.message || "Delete failed");
    } finally {
      setBusy(false);
    }
  };

  const runManual = async (path: string, body: any, label: string) => {
    setBusy(true);
    try {
      const r = await api<{ message?: string; queued?: number }>(path, {
        method: "POST",
        body: { ...(isSuper && companyId ? { company_id: companyId } : {}), ...body },
      });
      flash(r.message || `${label} — queued ${r.queued ?? ""}`.trim());
      loadAll();
    } catch (e: any) {
      flash(e?.message || "Action failed");
    } finally {
      setBusy(false);
    }
  };

  const saveSettings = async (patch: Partial<Settings>) => {
    if (!settings) return;
    const next = { ...settings, ...patch };
    setSettings(next);
    try {
      await api("/sync/settings", {
        method: "PUT",
        body: { ...(isSuper && companyId ? { company_id: companyId } : {}), ...patch },
      });
    } catch (e: any) {
      flash(e?.message || "Could not save setting");
      loadAll();
    }
  };

  const resolveConflict = async (id: string, decision: "approve" | "reject") => {
    try {
      await api(`/sync/conflicts/${id}/resolve`, { method: "POST", body: { decision } });
      setConflicts((cs) => cs.filter((c) => c.conflict_id !== id));
      loadStatus();
    } catch (e: any) {
      flash(e?.message || "Failed");
    }
  };

  const downloadReport = async () => {
    try {
      const res = await apiBinary(`/sync/report.xlsx${qs}`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = "sync-report.xlsx";
        a.click();
      }
    } catch (e: any) {
      flash(e?.message || "Report download failed");
    }
  };

  if (!canManage) {
    return (
      <SafeAreaView style={styles.center}>
        <Text style={styles.muted}>Admins only.</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      {/* Header */}
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={styles.backBtn}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Device Sync Engine</Text>
          <Text style={styles.subtitle}>Real-time multi-machine employee sync</Text>
        </View>
        <Pressable onPress={downloadReport} style={styles.reportBtn} testID="sync-report">
          <Ionicons name="download-outline" size={16} color={colors.brandPrimary} />
          <Text style={styles.reportTxt}>Report</Text>
        </Pressable>
      </View>

      {/* Super-admin firm picker — Iter 295 (user request): dropdown with
          the full company list instead of horizontal chips. */}
      {isSuper && companies.length > 0 && (
        <View style={styles.firmDdWrap}>
          <CompanyPicker
            value={companyId || ""}
            onChange={(v: any) => { if (v && v !== "all") setCompanyId(v); }}
            companies={companies}
            allowAll={false}
            label="Firm"
            testID="sync-firm-dd"
          />
        </View>
      )}

      {/* Tabs */}
      <View style={styles.tabs}>
        {TABS.map((t) => (
          <Pressable key={t} onPress={() => setTab(t)}
            style={[styles.tab, tab === t && styles.tabOn]} testID={`tab-${t}`}>
            <Text style={[styles.tabTxt, tab === t && styles.tabTxtOn]}>{t}</Text>
            {t === "Conflicts" && (status?.open_conflicts ?? 0) > 0 && (
              <View style={styles.badge}><Text style={styles.badgeTxt}>{status?.open_conflicts}</Text></View>
            )}
          </Pressable>
        ))}
      </View>

      {banner && (
        <View style={styles.banner}><Text style={styles.bannerTxt}>{banner}</Text></View>
      )}

      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" color={colors.brandPrimary} /></View>
      ) : (
        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); loadAll(); }} />}
        >
          {tab === "Dashboard" && (
            <>
              <View style={styles.tiles}>
                <Tile icon="hardware-chip-outline" label="Total Devices" value={status?.total_devices ?? 0} />
                <Tile icon="wifi-outline" label="Online" value={status?.online_devices ?? 0} accent="#16A34A" />
                <Tile icon="cloud-offline-outline" label="Offline" value={status?.offline_devices ?? 0} accent="#DC2626" />
                <Tile icon="hourglass-outline" label="Pending" value={status?.pending_sync ?? 0} accent="#B45309" />
                <Tile icon="checkmark-done-outline" label="Synced" value={status?.employees_synced ?? 0} accent="#16A34A" />
                <Tile icon="alert-circle-outline" label="Failed" value={status?.failed_sync ?? 0} accent="#DC2626" />
                <Tile icon="layers-outline" label="In Queue" value={status?.current_queue ?? 0} accent="#1D4ED8" />
                <Tile icon="git-compare-outline" label="Conflicts" value={status?.open_conflicts ?? 0} accent="#B45309" />
              </View>
              <Text style={styles.lastSync}>Last sync: {fmtTime(status?.last_sync_time)}</Text>

              <Text style={styles.section}>Manual sync</Text>
              <View style={styles.actionsGrid}>
                <ActionBtn icon="hardware-chip-outline" label="Sync Machines Only" busy={busy}
                  onPress={() => {
                    const ok = Platform.OS === "web"
                      ? window.confirm(
                          "Machine-only sync: copies users + fingerprints/faces " +
                          "from every machine to all other machines of this firm.\n\n" +
                          "Employee Master is NOT checked — use this while master " +
                          "data feeding is still pending.")
                      : true;
                    if (ok) runManual("/sync/machines", {}, "Machine sync");
                  }} />
                <ActionBtn icon="download-outline" label="Download Report" busy={busy}
                  onPress={downloadReport} ghost />
              </View>

              {/* Iter 584 — EMPLOYEE DEVICE MANAGEMENT (only Portal→Device ops) */}
              <Text style={styles.section}>Employee Device Management</Text>
              <Text style={styles.delNote}>
                Manual Registration: {settings?.manual_employee_registration ? "ON" : "OFF"} ·
                Manual Delete: {settings?.manual_employee_delete ? "ON" : "OFF"} ·
                Automatic Master Sync: DISABLED (locked)
              </Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, alignItems: "center", marginTop: 6 }}>
                <TextInput
                  value={edmCode} onChangeText={setEdmCode}
                  placeholder="Employee Code"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.delInput} testID="edm-code" />
                <ActionBtn icon="search-outline" label="Load Employee & Machines"
                  busy={busy} onPress={loadEdmPreview} />
              </View>
              {edmPreview ? (
                <View style={styles.machineCard} testID="edm-preview">
                  <Text style={styles.rowTitle}>
                    {edmPreview.employee.employee_code} - {edmPreview.employee.name}
                    {"  ·  Device User ID: "}{edmPreview.employee.device_user_id || "—"}
                  </Text>
                  <Text style={[styles.rowSub, { marginTop: 4 }]}>Data to send (Name, Code & Device User ID always included):</Text>
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginVertical: 6 }}>
                    {(["card", "password", "fingerprint", "face"] as const).map((k) => {
                      const av = edmPreview.fields?.[k]?.available;
                      const on = edmFields.has(k);
                      return (
                        <Pressable key={k} disabled={!av} onPress={() => edmToggleField(k)}
                          style={[styles.miniBtn, {
                            backgroundColor: !av ? "#E2E8F0" : on ? "#16A34A" : "#94A3B8" }]}
                          testID={`edm-field-${k}`}>
                          <Text style={styles.miniBtnTxt}>
                            {av ? (on ? "✓ " : "") : "✕ "}{k}{av ? "" : " (not supported)"}
                          </Text>
                        </Pressable>
                      );
                    })}
                  </View>
                  <Text style={styles.rowSub}>Select machine(s):</Text>
                  {(edmPreview.machines || []).map((m: any) => (
                    <Pressable key={m.serial_number} onPress={() => edmToggleSel(m.serial_number)}
                      style={[styles.row, edmSel.has(m.serial_number) && { borderColor: colors.brandPrimary, borderWidth: 1.5 }]}
                      testID={`edm-machine-${m.serial_number}`}>
                      <Ionicons
                        name={edmSel.has(m.serial_number) ? "checkbox" : "square-outline"}
                        size={18} color={edmSel.has(m.serial_number) ? colors.brandPrimary : colors.onSurfaceTertiary} />
                      <View style={{ flex: 1, marginLeft: 8 }}>
                        <Text style={styles.rowTitle}>{m.name || m.serial_number}</Text>
                        <Text style={styles.rowSub}>
                          {m.serial_number}{m.model ? ` · ${m.model}` : ""}{m.location ? ` · ${m.location}` : ""}
                          {" · "}{m.online ? "ONLINE" : "OFFLINE"}
                          {m.already_registered ? "  ·  ⚠ already registered" : ""}
                        </Text>
                      </View>
                    </Pressable>
                  ))}
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 8 }}>
                    <ActionBtn icon="person-add-outline" label="Confirm & Register" busy={busy}
                      onPress={edmRegister} />
                    <ActionBtn icon="person-remove-outline" label="Delete From Selected" busy={busy}
                      ghost onPress={() => edmDelete(false)} />
                    <ActionBtn icon="trash-outline" label="Delete From All Registered" busy={busy}
                      ghost onPress={() => edmDelete(true)} />
                  </View>
                </View>
              ) : null}
              {edmActivity.length > 0 ? (
                <>
                  <Text style={styles.section}>Recent manual device actions</Text>
                  {edmActivity.slice(0, 8).map((j: any) => (
                    <View key={j.job_id} style={styles.row}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.rowTitle}>
                          {j.name || j.pin} · {j.sync_type === "MANUAL_EMPLOYEE_DELETE" ? "DELETE" : "REGISTER"}
                        </Text>
                        <Text style={styles.rowSub}>
                          PIN {j.pin} · {(j.targets || []).length} machine(s) · by {j.created_by}
                        </Text>
                        <Text style={styles.rowTime}>{fmtTime(j.updated_at)}</Text>
                      </View>
                      <StatusPill status={j.status} />
                    </View>
                  ))}
                </>
              ) : null}

              {/* Iter 541 (user request) — delete employees FROM machines */}
              <Text style={styles.section}>Remove from machines</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
                <TextInput
                  value={delCode} onChangeText={setDelCode}
                  placeholder="Emp Code or Bio Code"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.delInput} testID="sync-del-code" />
                <ActionBtn icon="person-remove-outline" label="Delete From Machines"
                  busy={busy} onPress={deleteOneFromMachines} />
                <ActionBtn icon="exit-outline" label="Remove All LEFT Employees"
                  busy={busy} ghost onPress={deleteLeftFromMachines} />
              </View>
              <Text style={styles.delNote}>
                Queues a DELETE USERINFO command to every sync-enabled machine
                of this firm — the employee can no longer punch. Portal data
                (Employee Master, attendance, salary) is NOT touched.
              </Text>
            </>
          )}

          {tab === "Machines" && (
            machines.length === 0 ? <Empty text="No machine registered for this firm." /> :
            <>
              <Text style={styles.section}>
                {machines.length} registered machine(s) · {machines.filter((m) => m.online).length} online
              </Text>
              {machines.map((m) => (
                <View key={m.device_id} style={styles.machineCard} testID={`machine-${m.serial_number}`}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                    <Ionicons name="hardware-chip-outline" size={18}
                      color={m.online ? "#16A34A" : "#DC2626"} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.rowTitle}>{m.name || m.serial_number}</Text>
                      <Text style={styles.rowSub}>
                        {m.serial_number}
                        {m.model ? ` · ${m.model}` : m.brand ? ` · ${String(m.brand).toUpperCase()}` : ""}
                        {m.firmware ? ` · ${m.firmware}` : ""}
                        {m.device_ip ? ` · ${m.device_ip}` : ""}
                      </Text>
                    </View>
                    <View style={[styles.onlinePill, { backgroundColor: m.online ? "#DCFCE7" : "#FEE2E2" }]}>
                      <Text style={{ fontSize: 11, fontWeight: "800", color: m.online ? "#16A34A" : "#DC2626" }}>
                        {m.online ? "ONLINE" : "OFFLINE"}
                      </Text>
                    </View>
                  </View>
                  <View style={styles.machineStats}>
                    <View style={styles.statBox}>
                      <Text style={styles.statVal}>{m.employees_on_machine ?? "—"}</Text>
                      <Text style={styles.statLbl}>Employees on machine</Text>
                    </View>
                    <View style={styles.statBox}>
                      <Text style={styles.statVal}>{m.fp_count ?? "—"}</Text>
                      <Text style={styles.statLbl}>Fingerprints</Text>
                    </View>
                    <View style={styles.statBox}>
                      <Text style={styles.statVal}>{m.att_log_count ?? "—"}</Text>
                      <Text style={styles.statLbl}>Punch records</Text>
                    </View>
                    <View style={styles.statBox}>
                      <Text style={[styles.statVal, m.pending_cmds > 0 && { color: "#B45309" }]}>{m.pending_cmds}</Text>
                      <Text style={styles.statLbl}>Sync commands waiting</Text>
                    </View>
                  </View>
                  <Text style={styles.rowTime}>
                    Last contact: {fmtTime(m.last_seen_at)}
                    {m.sync_enabled === false ? "  ·  ⚠ Sync disabled for this machine" : ""}
                  </Text>
                </View>
              ))}
              <Text style={styles.machineHint}>
                Counts are reported by each machine itself on its heartbeat — refresh a
                minute after a sync to see updated employee counts.
              </Text>

              {/* Iter 768 (user request) — Machine → Machine SYNC LOG REPORT:
                  every manual + AUTO run with trigger reason and counts. */}
              <Text style={styles.section}>Machine Sync Log Report</Text>
              {m2mLogs.length === 0 ? (
                <Empty text="Abhi tak koi machine sync run nahi hua." />
              ) : (
                m2mLogs.map((l: any) => (
                  <View key={l.log_id || l.run_id} style={styles.machineCard} testID={`m2m-log-${l.run_id}`}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <View style={[styles.onlinePill, { backgroundColor: l.source === "auto" ? "#DBEAFE" : "#F3E8FF" }]}>
                        <Text style={{ fontSize: 11, fontWeight: "800", color: l.source === "auto" ? "#1D4ED8" : "#7C3AED" }}>
                          {l.source === "auto" ? "AUTO" : "MANUAL"}
                        </Text>
                      </View>
                      <Text style={[styles.rowTitle, { flex: 1 }]}>{fmtTime(l.created_at)}</Text>
                      <View style={[styles.onlinePill, { backgroundColor: l.status === "done" ? "#DCFCE7" : "#FEF3C7" }]}>
                        <Text style={{ fontSize: 11, fontWeight: "800", color: l.status === "done" ? "#16A34A" : "#B45309" }}>
                          {l.status === "done" ? "COMPLETED" : "SYNCING…"}
                        </Text>
                      </View>
                    </View>
                    {(l.reasons || []).slice(0, 3).map((r: string, i: number) => (
                      <Text key={i} style={styles.rowSub}>• {r}</Text>
                    ))}
                    {(l.reasons || []).length > 3 ? (
                      <Text style={styles.rowSub}>… +{(l.reasons || []).length - 3} more trigger(s)</Text>
                    ) : null}
                    <Text style={styles.rowTime}>
                      {(l.machines || []).length} machine(s)
                      {l.status === "done"
                        ? ` · ${l.users ?? 0} user(s) · ${l.templates ?? 0} template(s) · ${l.queued ?? 0} command(s) queued`
                        : " · collecting data, distribution ~2 min me"}
                    </Text>
                  </View>
                ))
              )}
            </>
          )}

          {tab === "Queue" && (
            jobs.length === 0 ? <Empty text="Queue is empty." /> :
            jobs.map((j) => (
              <View key={j.job_id} style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{j.name || j.pin} · {j.action}</Text>
                  <Text style={styles.rowSub}>
                    PIN {j.pin} · {(j.targets || []).length} device(s) · attempt {j.attempts}
                    {j.error ? ` · ${j.error}` : ""}
                  </Text>
                  <Text style={styles.rowTime}>{fmtTime(j.updated_at)}</Text>
                </View>
                <StatusPill status={j.status} />
              </View>
            ))
          )}

          {tab === "History" && (
            logs.length === 0 ? <Empty text="No sync history yet." /> :
            logs.map((l) => (
              <View key={l.log_id} style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{l.command}</Text>
                  <Text style={styles.rowSub}>
                    {l.device_serial} · PIN {l.pin} · {l.action}
                    {l.error ? ` · ${l.error}` : ""}
                  </Text>
                  <Text style={styles.rowTime}>{fmtTime(l.created_at)}</Text>
                </View>
                <StatusPill status={l.status} />
              </View>
            ))
          )}

          {tab === "Settings" && settings && (
            <>
              <Text style={styles.section}>Biometric Device Integration</Text>
              <ToggleRow label="Machine → Payroll Punch Sync"
                hint="Punch/ATTLOG data flows from every machine into attendance"
                value={settings.machine_to_payroll_punch_sync !== false}
                onValueChange={(v) => saveSettings({ machine_to_payroll_punch_sync: v } as any)} />
              <ToggleRow label="Machine → Machine Sync"
                hint="Device-to-device user + template synchronization"
                value={settings.machine_to_machine_sync !== false}
                onValueChange={(v) => saveSettings({ machine_to_machine_sync: v } as any)} />
              <ToggleRow label="Auto Machine → Machine Sync"
                hint="Machine par NAYA employee ya koi change milte hi baaki machines par auto-sync (har run ka log report banta hai)"
                value={(settings as any).machine_auto_sync !== false}
                onValueChange={(v) => saveSettings({ machine_auto_sync: v } as any)} />
              <ToggleRow label="Manual Employee Registration"
                hint="Allow HR to manually register an employee on selected machine(s)"
                value={!!settings.manual_employee_registration}
                onValueChange={(v) => saveSettings({ manual_employee_registration: v } as any)} />
              <ToggleRow label="Manual Employee Delete"
                hint="Allow HR to manually delete an employee from selected machine(s)"
                value={!!settings.manual_employee_delete}
                onValueChange={(v) => saveSettings({ manual_employee_delete: v } as any)} />
              <View style={styles.row} testID="setting-auto-master-locked">
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>Automatic Employee Master Sync</Text>
                  <Text style={styles.rowSub}>
                    Employee create/update/delete/transfer NEVER touches the machines.
                    Portal → Device is manual-only.
                  </Text>
                </View>
                <View style={[styles.onlinePill, { backgroundColor: "#FEE2E2" }]}>
                  <Text style={{ fontSize: 11, fontWeight: "800", color: "#DC2626" }}>DISABLED · LOCKED</Text>
                </View>
              </View>

              <Text style={styles.section}>Data included in manual registration</Text>
              <ToggleRow label="Sync Fingerprints" value={settings.sync_fingerprints}
                onValueChange={(v) => saveSettings({ sync_fingerprints: v })} />
              <ToggleRow label="Sync Face" value={settings.sync_face}
                onValueChange={(v) => saveSettings({ sync_face: v })} />
              <ToggleRow label="Sync Card Number" value={settings.sync_card}
                onValueChange={(v) => saveSettings({ sync_card: v })} />
              <ToggleRow label="Sync Password" value={settings.sync_password}
                onValueChange={(v) => saveSettings({ sync_password: v })} />
              <ToggleRow label="Sync Photos" value={settings.sync_photos}
                onValueChange={(v) => saveSettings({ sync_photos: v })} />
              <ToggleRow label="Retry Failed Jobs" value={settings.retry_failed}
                onValueChange={(v) => saveSettings({ retry_failed: v })} />
              <NumRow label="Maximum Retry Count" value={settings.max_retry_count} min={0} max={10}
                onCommit={(n) => saveSettings({ max_retry_count: n })} />
              <NumRow label="Sync Interval (seconds)" value={settings.sync_interval} min={15} max={3600}
                onCommit={(n) => saveSettings({ sync_interval: n })} />
            </>
          )}

          {tab === "Conflicts" && (
            conflicts.length === 0 ? <Empty text="No conflicts — machine data is captured & approved automatically. 🎉" /> :
            conflicts.map((c) => (
              <View key={c.conflict_id} style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>PIN {c.pin} · {c.kind.toUpperCase()} on {c.device_serial}</Text>
                  <Text style={styles.rowSub}>{c.detail}</Text>
                  <Text style={styles.rowTime}>{fmtTime(c.created_at)}</Text>
                </View>
                <View style={{ gap: 6 }}>
                  <Pressable onPress={() => resolveConflict(c.conflict_id, "approve")}
                    style={[styles.miniBtn, { backgroundColor: "#16A34A" }]}>
                    <Text style={styles.miniBtnTxt}>Keep</Text>
                  </Pressable>
                  <Pressable onPress={() => resolveConflict(c.conflict_id, "reject")}
                    style={[styles.miniBtn, { backgroundColor: "#DC2626" }]}>
                    <Text style={styles.miniBtnTxt}>Ignore</Text>
                  </Pressable>
                </View>
              </View>
            ))
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function Tile({ icon, label, value, accent }: { icon: any; label: string; value: number; accent?: string }) {
  return (
    <View style={styles.tile}>
      <Ionicons name={icon} size={18} color={accent || colors.onSurfaceSecondary} />
      <Text style={[styles.tileVal, accent ? { color: accent } : null]}>{value}</Text>
      <Text style={styles.tileLbl}>{label}</Text>
    </View>
  );
}

function StatusPill({ status }: { status: string }) {
  const c = STATUS_COLORS[status] || "#6B7280";
  return (
    <View style={[styles.pill, { backgroundColor: `${c}22` }]}>
      <Text style={[styles.pillTxt, { color: c }]}>{status}</Text>
    </View>
  );
}

function ActionBtn({ icon, label, onPress, busy, ghost }: {
  icon: any; label: string; onPress: () => void; busy?: boolean; ghost?: boolean;
}) {
  return (
    <Pressable onPress={onPress} disabled={busy}
      style={[styles.action, ghost && styles.actionGhost, busy && { opacity: 0.5 }]}>
      <Ionicons name={icon} size={16} color={ghost ? colors.brandPrimary : colors.onCta} />
      <Text style={[styles.actionTxt, ghost && { color: colors.brandPrimary }]}>{label}</Text>
    </Pressable>
  );
}

function ToggleRow({ label, hint, value, onValueChange }: {
  label: string; hint?: string; value: boolean; onValueChange: (v: boolean) => void;
}) {
  return (
    <View style={styles.toggleRow}>
      <View style={{ flex: 1 }}>
        <Text style={styles.toggleLbl}>{label}</Text>
        {hint ? <Text style={styles.toggleHint}>{hint}</Text> : null}
      </View>
      <Switch value={value} onValueChange={onValueChange}
        trackColor={{ true: colors.brandPrimary }} />
    </View>
  );
}

function NumRow({ label, value, min, max, onCommit }: {
  label: string; value: number; min: number; max: number; onCommit: (n: number) => void;
}) {
  const [txt, setTxt] = useState(String(value));
  useEffect(() => setTxt(String(value)), [value]);
  return (
    <View style={styles.toggleRow}>
      <Text style={[styles.toggleLbl, { flex: 1 }]}>{label}</Text>
      <TextInput
        value={txt}
        onChangeText={setTxt}
        onBlur={() => {
          const n = Math.max(min, Math.min(max, parseInt(txt || "0", 10) || min));
          onCommit(n);
        }}
        keyboardType="number-pad"
        style={styles.numInput}
      />
    </View>
  );
}

function Empty({ text }: { text: string }) {
  return <View style={styles.center}><Text style={styles.muted}>{text}</Text></View>;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 30 },
  muted: { color: colors.onSurfaceTertiary, fontSize: type.md },
  header: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: spacing.md, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  backBtn: { padding: 2 },
  title: { fontSize: type.lg, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: type.xs, color: colors.onSurfaceTertiary },
  reportBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: 10, paddingVertical: 6,
  },
  delInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: 12, paddingVertical: 9, fontSize: type.sm,
    color: colors.onSurface, backgroundColor: colors.surface, minWidth: 180,
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
  },
  delNote: {
    fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 8, lineHeight: 15,
  },
  reportTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: type.sm },
  firmDdWrap: {
    paddingHorizontal: spacing.md, paddingVertical: 8,
    backgroundColor: colors.surface, borderBottomWidth: 1,
    borderBottomColor: colors.border, zIndex: 50,
  },
  firmBar: { maxHeight: 46, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  firmChip: {
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, marginVertical: 6,
  },
  firmChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  firmChipTxt: { color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "600" },
  firmChipTxtOn: { color: colors.onCta },
  tabs: {
    flexDirection: "row", backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  tab: { flex: 1, alignItems: "center", paddingVertical: 12, flexDirection: "row", justifyContent: "center", gap: 4 },
  tabOn: { borderBottomWidth: 2, borderBottomColor: colors.brandPrimary },
  tabTxt: { color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "600" },
  tabTxtOn: { color: colors.brandPrimary, fontWeight: "800" },
  badge: { backgroundColor: "#DC2626", borderRadius: 999, minWidth: 16, paddingHorizontal: 4, alignItems: "center" },
  badgeTxt: { color: "#fff", fontSize: 9, fontWeight: "800" },
  banner: { backgroundColor: "#1D4ED8", paddingHorizontal: spacing.md, paddingVertical: 8 },
  bannerTxt: { color: "#fff", fontSize: type.sm, fontWeight: "600" },
  tiles: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  tile: {
    width: "47%", flexGrow: 1, backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, padding: 12, ...shadow.card,
  },
  tileVal: { fontSize: 24, fontWeight: "800", color: colors.onSurface, marginTop: 4 },
  tileLbl: { fontSize: type.xs, color: colors.onSurfaceTertiary, marginTop: 2 },
  lastSync: { color: colors.onSurfaceTertiary, fontSize: type.xs, marginTop: 10 },
  section: { fontSize: type.md, fontWeight: "800", color: colors.onSurface, marginTop: 18, marginBottom: 8 },
  actionsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  action: {
    flexGrow: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: colors.brandPrimary, borderRadius: radius.sm, paddingVertical: 12, paddingHorizontal: 14,
  },
  actionGhost: { backgroundColor: "transparent", borderWidth: 1, borderColor: colors.border },
  actionTxt: { color: colors.onCta, fontWeight: "700", fontSize: type.sm },
  filterCard: {
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, padding: 12, marginTop: 8,
  },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: 12, paddingVertical: 10, fontSize: type.md, color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary, marginBottom: 8,
  },
  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, padding: 12, marginBottom: 8,
  },
  rowTitle: { fontSize: type.sm, fontWeight: "700", color: colors.onSurface },
  rowSub: { fontSize: type.xs, color: colors.onSurfaceSecondary, marginTop: 2 },
  rowTime: { fontSize: type.xs, color: colors.onSurfaceTertiary, marginTop: 2 },
  // Iter 419 — Machines tab
  machineCard: {
    backgroundColor: colors.surface, borderRadius: radius.md, padding: 14,
    marginBottom: 10, borderWidth: 1, borderColor: colors.border,
  },
  onlinePill: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  machineStats: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12, marginBottom: 8 },
  statBox: {
    flexGrow: 1, minWidth: 120, backgroundColor: colors.background,
    borderRadius: radius.sm, paddingVertical: 10, paddingHorizontal: 12, alignItems: "center",
  },
  statVal: { fontSize: 20, fontWeight: "900", color: colors.onSurface },
  statLbl: { fontSize: type.xs, color: colors.onSurfaceSecondary, marginTop: 2, textAlign: "center" },
  machineHint: { fontSize: type.xs, color: colors.onSurfaceTertiary, marginTop: 6, lineHeight: 17 },
  pill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  pillTxt: { fontSize: 10, fontWeight: "800", textTransform: "uppercase" },
  miniBtn: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.sm },
  miniBtnTxt: { color: "#fff", fontSize: type.xs, fontWeight: "700", textAlign: "center" },
  toggleRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, paddingHorizontal: 14, paddingVertical: 12, marginBottom: 8,
  },
  toggleLbl: { fontSize: type.sm, fontWeight: "600", color: colors.onSurface },
  toggleHint: { fontSize: type.xs, color: colors.onSurfaceTertiary, marginTop: 2 },
  numInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: 12, paddingVertical: 8, minWidth: 70, textAlign: "center",
    color: colors.onSurface, backgroundColor: colors.surfaceSecondary, fontVariant: ["tabular-nums"],
  },
});
