import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ActivityIndicator,
  RefreshControl,
  Modal,
  ScrollView,
  Alert,
  Animated,
  Platform,
  Share,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

import { api, apiBinary } from "@/src/api/client";
import { useLiveSync } from "@/src/api/live-sync";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";

type Device = {
  device_id: string;
  serial_number: string;
  name: string;
  kind: "in" | "out" | "both";
  company_id: string;
  location?: string | null;
  enabled: boolean;
  online?: boolean;
  locked?: boolean;            // Iter 261 — portal-side lock
  gmt_offset?: string;         // Iter 263 — machine time zone (e.g. +05:30)
  brand?: string;              // Iter 294 — zkteco | essl | matrix | mantra
  webhook_key?: string;        // Iter 294 — JSON webhook secret (matrix/mantra)
  last_source_ip?: string;     // SEC-002 — last IP the machine pushed from
  ip_lock?: boolean;           // SEC-002 — reject other IPs when true
  ip_allowlist?: string[];     // SEC-002 — allowed source IPs
  templates_captured?: number; // Iter 261 — FP/Face templates captured
  last_seen_at?: string | null;
  last_push_at?: string | null;
  model?: string;
  total_pushes?: number;
  total_punches_ingested?: number;
};

// Iter 261 — Live Dashboard punch feed row.
type FeedRow = {
  at: string;
  date: string;
  kind: "in" | "out";
  status?: string;
  name: string;
  bio_code?: string | null;
  device?: string | null;
};

type Company = { company_id: string; name: string };

const emptyDraft = {
  serial_number: "",
  name: "",
  kind: "in" as "in" | "out" | "both",
  company_id: "",
  location: "",
  branch_name: "", // Iter 298 — branch tag for two-branch payroll
  gmt_offset: "+05:30", // Iter 263 — machine time zone (India default)
  brand: "zkteco",      // Iter 294 — device brand
  enabled: true,
};

// Iter 294 — supported device brands. ZKTeco & eSSL use the same
// iClock/ADMS push protocol; Matrix COSEC & Mantra push JSON to a
// per-device webhook URL (shown after saving).
const BRANDS: { key: string; label: string; adms: boolean }[] = [
  { key: "zkteco", label: "ZKTeco", adms: true },
  { key: "essl", label: "eSSL", adms: true },
  { key: "bioface", label: "BIOFACE (MSD1K)", adms: true },
  { key: "matrix", label: "Matrix COSEC", adms: false },
  { key: "mantra", label: "Mantra", adms: false },
  { key: "other", label: "Other", adms: false },
];

// Iter 263 — parse '+05:30' / '5:30' / '-4' / '5.5' into signed minutes.
function parseGmtMinutes(raw?: string | null): number {
  const s = String(raw || "").trim().toUpperCase().replace(/GMT|UTC/g, "").trim();
  const m = /^([+-]?)(\d{1,2})(?::(\d{2})|\.(\d+))?$/.exec(s);
  if (!m) return 330;
  const sign = m[1] === "-" ? -1 : 1;
  const mins = m[3] ? parseInt(m[3], 10) : m[4] ? Math.round(parseFloat(`0.${m[4]}`) * 60) : 0;
  const total = sign * (parseInt(m[2], 10) * 60 + mins);
  return total < -720 || total > 840 ? 330 : total;
}

export default function BiometricDevicesScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const canManage = user?.role === "super_admin" || user?.role === "company_admin" || (user?.role as string) === "sub_admin";
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [unmappedCount, setUnmappedCount] = useState(0);
  const [companies, setCompanies] = useState<Company[]>([]);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Device | null>(null);
  const [draft, setDraft] = useState({ ...emptyDraft });
  const [saving, setSaving] = useState(false);
  const [simulating, setSimulating] = useState<string | null>(null);
  const [companyPickerOpen, setCompanyPickerOpen] = useState(false);
  const [showGuide, setShowGuide] = useState(false);

  // Iter 297 — Connection Doctor (per-device online/never-connected
  // verdicts + unknown serials that reached the server unregistered).
  const [doctorOpen, setDoctorOpen] = useState(false);
  const [doctorBusy, setDoctorBusy] = useState(false);
  const [doctor, setDoctor] = useState<any>(null);
  const runDoctor = async () => {
    setDoctorOpen(true);
    setDoctorBusy(true);
    try {
      const r = await api<any>("/biometric/connection-doctor");
      setDoctor(r);
    } catch (e: any) {
      alertUser("Failed", e?.message || "Could not run the connection check.");
    } finally {
      setDoctorBusy(false);
    }
  };

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await api<{ devices: Device[]; unmapped_count: number }>(
        "/biometric/devices",
      );
      setDevices(r.devices || []);
      setUnmappedCount(r.unmapped_count || 0);
      if (isSuper) {
        try {
          const c = await api<{ companies: Company[] }>("/companies?lite=1");
          setCompanies(c.companies || []);
        } catch {}
      }
    } catch (e: any) {
      setError(e?.message || "Failed to load devices");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [isSuper]);

  useEffect(() => {
    if (!canManage) return;
    load();
  }, [canManage, load]);

  // ---- Iter 261 — Live Dashboard: real-time punch feed + auto status ----
  const [feed, setFeed] = useState<FeedRow[]>([]);
  const [feedOpen, setFeedOpen] = useState(true);
  const loadFeed = useCallback(async () => {
    try {
      const r = await api<{ feed: FeedRow[] }>("/biometric/live-feed?limit=25");
      setFeed(r.feed || []);
    } catch {}
  }, []);
  useEffect(() => {
    if (!canManage) return;
    loadFeed();
    // Polling fallback (15 s) — WS below refreshes instantly on pushes.
    const t = setInterval(() => {
      loadFeed();
      load();
    }, 15000);
    return () => clearInterval(t);
  }, [canManage, loadFeed, load]);
  useLiveSync(user?.company_id || null, (ev) => {
    if (ev.type === "attendance.zk-pushed" || ev.type === "punch.created") {
      loadFeed();
      load();
    }
  });

  const openCreate = () => {
    setEditing(null);
    setDraft({ ...emptyDraft, company_id: isSuper ? "" : (user?.company_id || "") });
    setEditorOpen(true);
  };

  const openEdit = (d: Device) => {
    setEditing(d);
    setDraft({
      serial_number: d.serial_number,
      name: d.name,
      kind: d.kind,
      company_id: d.company_id || "",
      location: d.location || "",
      branch_name: (d as any).branch_name || "",
      gmt_offset: d.gmt_offset || "+05:30",
      brand: d.brand || "zkteco",
      enabled: d.enabled,
    });
    setEditorOpen(true);
  };

  const save = async () => {
    if (!draft.serial_number.trim() || !draft.name.trim()) {
      alertUser("Missing details", "Please enter serial number and a friendly name.");
      return;
    }
    if (isSuper && !draft.company_id) {
      alertUser("Company required", "Please pick which firm this device belongs to.");
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await api(`/biometric/devices/${editing.device_id}`, {
          method: "PATCH",
          body: {
            name: draft.name.trim(),
            kind: draft.kind,
            company_id: isSuper ? draft.company_id : undefined,
            location: draft.location.trim() || undefined,
            branch_name: ((draft as any).branch_name || "").trim(),
            gmt_offset: draft.gmt_offset.trim() || "+05:30",
            brand: draft.brand,
            enabled: draft.enabled,
          },
        });
      } else {
        await api("/biometric/devices", {
          method: "POST",
          body: {
            serial_number: draft.serial_number.trim(),
            name: draft.name.trim(),
            kind: draft.kind,
            company_id: draft.company_id || undefined,
            location: draft.location.trim() || undefined,
            branch_name: ((draft as any).branch_name || "").trim() || undefined,
            gmt_offset: draft.gmt_offset.trim() || "+05:30",
            brand: draft.brand,
            enabled: draft.enabled,
          },
        });
      }
      setEditorOpen(false);
      await load();
    } catch (e: any) {
      alertUser("Save failed", e?.message || "Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const removeDevice = (d: Device) => {
    const proceed = async () => {
      try {
        await api(`/biometric/devices/${d.device_id}`, { method: "DELETE" });
        await load();
      } catch (e: any) {
        alertUser("Delete failed", e?.message || "Please try again.");
      }
    };
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && window.confirm(`Remove device "${d.name}" (${d.serial_number})?`))
        proceed();
    } else {
      Alert.alert(
        "Remove device",
        `Remove "${d.name}" (${d.serial_number})? Punches already ingested will be kept.`,
        [
          { text: "Cancel", style: "cancel" },
          { text: "Remove", style: "destructive", onPress: proceed },
        ],
      );
    }
  };

  const simulate = async (d: Device) => {
    // Prompt for a device user ID to test with
    const askVal = async (): Promise<string | null> => {
      if (Platform.OS === "web") {
        const v = typeof window !== "undefined"
          ? window.prompt(`Device User ID to simulate a ${d.kind.toUpperCase()} punch as (matches employee bio_code):`, "1001")
          : "1001";
        return v || null;
      }
      return new Promise((resolve) => {
        Alert.prompt?.(
          "Simulate punch",
          `Device User ID to simulate a ${d.kind.toUpperCase()} punch as (matches employee bio_code):`,
          [
            { text: "Cancel", style: "cancel", onPress: () => resolve(null) },
            { text: "Send", onPress: (v?: string) => resolve(v || "1001") },
          ],
          "plain-text",
          "1001",
        ) ?? resolve("1001");
      });
    };
    const deviceUserId = await askVal();
    if (!deviceUserId) return;
    setSimulating(d.device_id);
    try {
      const r = await api<{ ok: boolean; reason?: string }>(
        "/biometric/devices/simulate-punch",
        {
          method: "POST",
          body: { serial_number: d.serial_number, device_user_id: deviceUserId },
        },
      );
      if (r.ok && !r.reason) {
        alertUser("Punch simulated", "The attendance record was created and auto-approved.");
      } else if (r.reason?.startsWith("unmapped_user")) {
        alertUser(
          "Employee not mapped",
          `No employee has bio_code = "${deviceUserId}". Update the employee's bio_code on their profile and try again.`,
        );
      } else if (r.reason === "duplicate_ignored") {
        alertUser("Duplicate ignored", "A punch with the same timestamp was already recorded.");
      } else {
        alertUser("Simulate failed", r.reason || "Please try again.");
      }
      await load();
    } catch (e: any) {
      alertUser("Simulate failed", e?.message || "Please try again.");
    } finally {
      setSimulating(null);
    }
  };

  // Iter 250 (user request) — fetch OLD punches stored inside the machine.
  const [resyncing, setResyncing] = useState<string | null>(null);
  const resyncDevice = async (d: Device) => {
    setResyncing(d.device_id);
    try {
      const r = await api<{ ok: boolean; message: string }>(
        `/biometric/devices/${d.device_id}/resync`,
        { method: "POST" },
      );
      alertUser("Old data fetch started", r.message);
    } catch (e: any) {
      alertUser("Failed", e?.message || "Please try again.");
    } finally {
      setResyncing(null);
    }
  };

  // Iter 258 — remote device controls + employee push.
  // Iter 262 (user request) — "Set date & time" opens an editable dialog;
  // Apply syncs the chosen date/time to the machine.
  const [timeDlg, setTimeDlg] = useState<Device | null>(null);
  const [dlgDate, setDlgDate] = useState("");
  const [dlgTime, setDlgTime] = useState("");
  const fillNow = (dev?: Device | null) => {
    // Iter 263 — current time in the MACHINE's configured GMT zone.
    const mins = parseGmtMinutes((dev ?? timeDlg)?.gmt_offset);
    const zoned = new Date(Date.now() + mins * 60000);
    const g = (x: number) => String(x).padStart(2, "0");
    setDlgDate(`${g(zoned.getUTCDate())}-${g(zoned.getUTCMonth() + 1)}-${zoned.getUTCFullYear()}`);
    setDlgTime(`${g(zoned.getUTCHours())}:${g(zoned.getUTCMinutes())}:${g(zoned.getUTCSeconds())}`);
  };
  const openTimeDlg = (d: Device) => {
    fillNow(d);
    setTimeDlg(d);
  };
  const applyTime = async () => {
    if (!timeDlg) return;
    if (!/^\d{2}-\d{2}-\d{4}$/.test(dlgDate.trim())) {
      alertUser("Invalid date", "Enter the date as DD-MM-YYYY (e.g. 23-06-2026).");
      return;
    }
    if (!/^\d{2}:\d{2}(:\d{2})?$/.test(dlgTime.trim())) {
      alertUser("Invalid time", "Enter the time as HH:MM or HH:MM:SS (24-hour).");
      return;
    }
    try {
      const r = await api<{ message: string }>(
        `/biometric/devices/${timeDlg.device_id}/command`,
        {
          method: "POST",
          body: { action: "sync_time", date: dlgDate.trim(), time: dlgTime.trim() },
        },
      );
      setTimeDlg(null);
      alertUser("Date & time queued", r.message);
    } catch (e: any) {
      alertUser("Failed", e?.message || "Please try again.");
    }
  };

  const sendCommand = async (d: Device, action: string) => {
    if (action === "sync_time") {
      openTimeDlg(d);
      return;
    }
    if (action === "restart") {
      const ok = Platform.OS === "web"
        ? window.confirm(`Restart machine "${d.name}" now?`)
        : true;
      if (!ok) return;
    }
    try {
      const r = await api<{ message: string }>(
        `/biometric/devices/${d.device_id}/command`,
        { method: "POST", body: { action } },
      );
      alertUser("Command queued", r.message);
    } catch (e: any) {
      alertUser("Failed", e?.message || "Please try again.");
    }
  };
  const pushEmployees = async (d: Device) => {
    const ok = Platform.OS === "web"
      ? window.confirm(`Push ALL employees (with Bio Code) of this firm to "${d.name}"?`)
      : true;
    if (!ok) return;
    try {
      const r = await api<{ message: string }>(
        "/biometric/devices/push-employees",
        { method: "POST", body: { company_id: d.company_id, device_id: d.device_id } },
      );
      alertUser("Employee push", r.message);
    } catch (e: any) {
      alertUser("Failed", e?.message || "Please try again.");
    }
  };

  // ---- Iter 261 — Phase 2: FP/Face template sync + lock/unlock ----------
  const fetchTemplates = async (d: Device) => {
    try {
      const r = await api<{ message: string }>(
        `/biometric/devices/${d.device_id}/fetch-templates`,
        { method: "POST", body: {} },
      );
      alertUser("Fetch FP/Face", r.message);
    } catch (e: any) {
      alertUser("Failed", e?.message || "Please try again.");
    }
  };
  const syncTemplates = async (d: Device) => {
    const ok = Platform.OS === "web"
      ? window.confirm(
          `Install ALL stored fingerprint / face templates of this firm onto "${d.name}"?\n\n` +
          "Tip: first press 'Fetch FP/Face' on the machine where employees are enrolled.",
        )
      : true;
    if (!ok) return;
    try {
      const r = await api<{ message: string }>(
        `/biometric/devices/${d.device_id}/sync-templates`,
        { method: "POST", body: {} },
      );
      alertUser("Sync FP/Face", r.message);
    } catch (e: any) {
      alertUser("Failed", e?.message || "Please try again.");
    }
  };
  // SEC-002 — lock a device to its current source IP (or unlock).
  const toggleIpLock = async (d: Device) => {
    const locking = !d.ip_lock;
    if (locking && !d.last_source_ip) {
      alertUser(
        "No IP seen yet",
        "Wait until this machine has pushed at least once, then lock it to that IP.",
      );
      return;
    }
    const ok = Platform.OS === "web"
      ? window.confirm(
          locking
            ? `Lock "${d.name}" to IP ${d.last_source_ip}?\n\nPunches/commands from any other IP will be rejected. Use this once you've confirmed this is your machine's stable IP.`
            : `Remove the IP lock on "${d.name}" and accept punches from any IP again?`,
        )
      : true;
    if (!ok) return;
    try {
      const r = await api<{ message: string }>(
        `/biometric/devices/${d.device_id}/ip-lock`,
        { method: "POST", body: { mode: locking ? "lock" : "unlock" } },
      );
      alertUser(locking ? "IP locked" : "IP unlocked", r.message);
      load();
    } catch (e: any) {
      alertUser("Failed", e?.message || "Please try again.");
    }
  };


  const toggleLock = async (d: Device) => {
    const locking = !d.locked;
    const ok = Platform.OS === "web"
      ? window.confirm(
          locking
            ? `LOCK "${d.name}"?\n\nPunches from this machine will be parked and will NOT enter attendance until unlocked.`
            : `Unlock "${d.name}" and accept its punches again?`,
        )
      : true;
    if (!ok) return;
    try {
      const r = await api<{ message: string }>(
        `/biometric/devices/${d.device_id}/command`,
        { method: "POST", body: { action: locking ? "lock" : "unlock" } },
      );
      alertUser(locking ? "Device locked" : "Device unlocked", r.message);
      load();
    } catch (e: any) {
      alertUser("Failed", e?.message || "Please try again.");
    }
  };

  const shareGuide = async () => {    const guide = buildSetupGuideText(devices);
    try {
      if (Platform.OS === "web" && navigator?.clipboard) {
        await navigator.clipboard.writeText(guide);
        alertUser("Copied", "Setup guide copied to clipboard.");
      } else {
        await Share.share({ message: guide });
      }
    } catch {}
  };

  const companyName = (id?: string) => {
    if (!id) return "—";
    if (!isSuper) return user?.company_name || "Your firm";
    const c = companies.find((x) => x.company_id === id);
    return c?.name || id;
  };

  const inDevices = useMemo(() => devices.filter((d) => d.kind === "in"), [devices]);
  const outDevices = useMemo(() => devices.filter((d) => d.kind === "out"), [devices]);

  if (!canManage) {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
          <Header title="Biometric devices" onBack={() => router.back()} />
        </SafeAreaView>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.dimTitle}>Admins only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root} testID="biometric-devices-screen">
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <Header
          title="ZKTeco Biometric Devices"
          onBack={() => router.back()}
          right={
            <Pressable onPress={() => setShowGuide(true)} hitSlop={6} style={styles.headBtn}>
              <Ionicons name="help-circle-outline" size={16} color={colors.brandPrimary} />
              <Text style={styles.headBtnTxt}>Setup guide</Text>
            </Pressable>
          }
        />
      </SafeAreaView>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => {
                setRefreshing(true);
                load();
              }}
              tintColor={colors.brandPrimary}
            />
          }
        >
          <View style={styles.summary}>
            <SummaryTile
              icon="log-in-outline"
              label="ENTRY DEVICES"
              value={inDevices.length}
              accent={colors.brandPrimary}
            />
            <SummaryTile
              icon="log-out-outline"
              label="EXIT DEVICES"
              value={outDevices.length}
              accent={colors.accent}
            />
            <SummaryTile
              icon="help-circle-outline"
              label="UNMAPPED PUNCHES"
              value={unmappedCount}
              accent={unmappedCount > 0 ? "#B45309" : colors.onSurfaceTertiary}
            />
          </View>

          {/* Iter 261 — Live Dashboard: real-time punch feed */}
          <View style={styles.liveCard} testID="live-dashboard">
            <Pressable style={styles.liveHead} onPress={() => setFeedOpen(!feedOpen)}>
              <View style={styles.liveDot} />
              <Text style={styles.liveTitle}>Live punch feed</Text>
              <Text style={styles.liveSub}>
                {devices.filter((d) => d.online).length}/{devices.length} machines online
              </Text>
              <Ionicons
                name={feedOpen ? "chevron-up" : "chevron-down"}
                size={16}
                color={colors.onSurfaceTertiary}
              />
            </Pressable>
            {feedOpen && (
              feed.length === 0 ? (
                <Text style={styles.liveEmpty}>
                  No machine punches yet — they appear here in real time.
                </Text>
              ) : (
                feed.slice(0, 12).map((f, i) => (
                  <View key={`${f.at}-${i}`} style={styles.liveRow}>
                    <Text style={styles.liveTime}>{fmtFeedTime(f.at)}</Text>
                    <View
                      style={[
                        styles.livePill,
                        { backgroundColor: f.kind === "in" ? "#DBEAFE" : "#FEF3C7" },
                      ]}
                    >
                      <Text
                        style={[
                          styles.livePillTxt,
                          { color: f.kind === "in" ? "#1D4ED8" : "#B45309" },
                        ]}
                      >
                        {f.kind === "in" ? "IN" : "OUT"}
                      </Text>
                    </View>
                    <Text style={styles.liveName} numberOfLines={1}>
                      {f.name}
                      {f.bio_code ? `  ·  ${f.bio_code}` : ""}
                    </Text>
                    <Text style={styles.liveDevice} numberOfLines={1}>{f.device || "—"}</Text>
                  </View>
                ))
              )
            )}
          </View>

          {error ? (
            <View style={styles.errBox}>
              <Ionicons name="alert-circle" size={16} color="#fff" />
              <Text style={styles.errTxt}>{error}</Text>
            </View>
          ) : null}

          <View style={{ flexDirection: "row", gap: 8 }}>
            <Pressable testID="add-device-btn" style={[styles.addBtn, { flex: 1 }]} onPress={openCreate}>
              <Ionicons name="add-circle" size={18} color={colors.onCta} />
              <Text style={styles.addBtnTxt}>Register new device</Text>
            </Pressable>
            {/* Iter 259 — Device Health Report (Excel) */}
            <Pressable
              testID="device-health-xlsx"
              style={[styles.addBtn, { flex: 1, backgroundColor: "#16a34a" }]}
              onPress={async () => {
                try {
                  const res = await apiBinary("/biometric/devices/health-report.xlsx");
                  if (Platform.OS === "web" && res.webBlobUrl) {
                    const a = document.createElement("a");
                    a.href = res.webBlobUrl;
                    a.download = "device-health-report.xlsx";
                    a.click();
                  }
                } catch (e: any) {
                  alertUser("Failed", e?.message || "Could not download the report.");
                }
              }}
            >
              <Ionicons name="download-outline" size={18} color={colors.onCta} />
              <Text style={styles.addBtnTxt}>Health Report (Excel)</Text>
            </Pressable>
          </View>
          {/* Iter 297 — Connection Doctor */}
          <Pressable
            testID="connection-doctor-btn"
            style={[styles.addBtn, { backgroundColor: "#B45309" }]}
            onPress={runDoctor}
          >
            <Ionicons name="pulse-outline" size={18} color={colors.onCta} />
            <Text style={styles.addBtnTxt}>Connection Doctor — why is my machine not connecting?</Text>
          </Pressable>

          {devices.length === 0 ? (
            <View style={styles.emptyBox}>
              <Ionicons name="finger-print" size={40} color={colors.brandPrimary} />
              <Text style={styles.emptyTitle}>No devices yet</Text>
              <Text style={styles.emptyBody}>
                Register your ZKTeco AC Mini Plus units — one for Entry (IN) and one for Exit
                (OUT). Punches will flow into the same attendance report as mobile punches, and
                will be auto-approved.
              </Text>
              <Pressable onPress={() => setShowGuide(true)} style={styles.emptyLink}>
                <Text style={styles.emptyLinkTxt}>Read the setup guide first ›</Text>
              </Pressable>
            </View>
          ) : (
            devices.map((d) => (
              <DeviceCard
                key={d.device_id}
                device={d}
                busy={simulating === d.device_id}
                resyncing={resyncing === d.device_id}
                companyName={companyName(d.company_id)}
                onEdit={() => openEdit(d)}
                onDelete={() => removeDevice(d)}
                onSimulate={() => simulate(d)}
                onResync={() => resyncDevice(d)}
                onCommand={(action) => sendCommand(d, action)}
                onPushEmployees={() => pushEmployees(d)}
                onFetchTemplates={() => fetchTemplates(d)}
                onSyncTemplates={() => syncTemplates(d)}
                onToggleLock={() => toggleLock(d)}
                onToggleIpLock={() => toggleIpLock(d)}
              />
            ))
          )}
          <Pressable onPress={shareGuide} style={styles.shareBtn}>
            <Ionicons name="share-outline" size={14} color={colors.brandPrimary} />
            <Text style={styles.shareTxt}>Share setup guide with technician</Text>
          </Pressable>
          <View style={{ height: 40 }} />
        </ScrollView>
      )}

      {/* Iter 297 — Connection Doctor modal */}
      <Modal transparent animationType="slide" visible={doctorOpen} onRequestClose={() => setDoctorOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setDoctorOpen(false)} />
        <View style={[styles.sheet, { maxHeight: "85%" }]}>
          <View style={styles.grip} />
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Ionicons name="pulse-outline" size={18} color="#B45309" />
            <Text style={[styles.sheetTitle, { flex: 1 }]}>Connection Doctor</Text>
            <Pressable onPress={runDoctor} hitSlop={8}>
              <Ionicons name="refresh" size={18} color={colors.brandPrimary} />
            </Pressable>
            <Pressable onPress={() => setDoctorOpen(false)} hitSlop={8}>
              <Ionicons name="close" size={20} color={colors.onSurfaceTertiary} />
            </Pressable>
          </View>
          {doctorBusy ? (
            <View style={{ paddingVertical: 40, alignItems: "center" }}>
              <ActivityIndicator color={colors.brandPrimary} />
              <Text style={{ marginTop: 8, color: colors.onSurfaceTertiary, fontSize: 12 }}>
                Checking every machine…
              </Text>
            </View>
          ) : (
            <ScrollView style={{ marginTop: 10 }}>
              {(doctor?.devices || []).map((d: any) => {
                const c = d.verdict === "online" ? "#16a34a" : d.verdict === "offline" ? "#B45309" : "#DC2626";
                const label = d.verdict === "online" ? "ONLINE" : d.verdict === "offline" ? "OFFLINE" : "NEVER CONNECTED";
                return (
                  <View key={d.device_id} style={{ borderWidth: 1, borderColor: "#E5E7EB", borderRadius: 10, padding: 10, marginBottom: 8 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: c }} />
                      <Text style={{ fontWeight: "700", color: colors.onSurface, flex: 1 }} numberOfLines={1}>
                        {d.name}  ·  {d.serial_number}
                      </Text>
                      <Text style={{ fontWeight: "800", fontSize: 11, color: c }}>{label}</Text>
                    </View>
                    <Text style={{ marginTop: 6, fontSize: 12, color: colors.onSurfaceSecondary, lineHeight: 17 }}>
                      {d.advice}
                    </Text>
                    {d.last_seen_at ? (
                      <Text style={{ marginTop: 4, fontSize: 11, color: colors.onSurfaceTertiary }}>
                        Last reached server: {String(d.last_seen_at).replace("T", " ").slice(0, 19)}
                        {d.last_source_ip ? `  ·  from IP ${d.last_source_ip}` : ""}
                      </Text>
                    ) : null}
                  </View>
                );
              })}
              {(doctor?.unknown_devices || []).length > 0 && (
                <>
                  <Text style={{ fontWeight: "800", color: "#DC2626", marginTop: 6, marginBottom: 6, fontSize: 13 }}>
                    ⚠ Machines reaching the server but NOT registered
                  </Text>
                  {(doctor?.unknown_devices || []).map((u: any) => (
                    <View key={u.serial_number} style={{ borderWidth: 1, borderColor: "#FECACA", backgroundColor: "#FEF2F2", borderRadius: 10, padding: 10, marginBottom: 8 }}>
                      <Text style={{ fontWeight: "700", color: "#991B1B" }}>{u.serial_number}</Text>
                      <Text style={{ marginTop: 4, fontSize: 12, color: "#7F1D1D", lineHeight: 17 }}>{u.hint}</Text>
                      <Text style={{ marginTop: 4, fontSize: 11, color: "#B91C1C" }}>
                        Last attempt: {String(u.last_seen_at || "").replace("T", " ").slice(0, 19)} · {u.hits} attempts
                      </Text>
                    </View>
                  ))}
                </>
              )}
              {!doctorBusy && (doctor?.devices || []).length === 0 && (
                <Text style={{ color: colors.onSurfaceTertiary, fontSize: 12 }}>No devices registered yet.</Text>
              )}
              <View style={{ height: 24 }} />
            </ScrollView>
          )}
        </View>
      </Modal>

      {/* Editor modal */}
      <Modal transparent animationType="slide" visible={editorOpen} onRequestClose={() => setEditorOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setEditorOpen(false)} />
        <KeyboardAwareScrollView
          bottomOffset={40}
          contentContainerStyle={{ flexGrow: 1, justifyContent: "flex-end" }}
        >
          <View style={styles.sheet}>
            <View style={styles.grip} />
            <Text style={styles.sheetTitle}>
              {editing ? "Edit device" : "Register device"}
            </Text>
            <Text style={styles.sheetSub}>
              Every ZKTeco device pushes attendance to the app under its serial number. Set
              this device to Entry (IN), Exit (OUT), or Both (single machine — punches
              alternate IN/OUT automatically). Punches are auto-approved.
            </Text>

            <Text style={styles.lbl}>Serial number (from device menu)</Text>
            <TextInput
              testID="d-sn"
              value={draft.serial_number}
              onChangeText={(t) => setDraft({ ...draft, serial_number: t })}
              editable={!editing}
              placeholder="E.g. CJU8123400123"
              placeholderTextColor={colors.onSurfaceTertiary}
              autoCapitalize="characters"
              style={[styles.input, editing && { opacity: 0.7 }]}
            />
            {editing ? (
              <Text style={styles.help}>Serial number cannot be changed once registered.</Text>
            ) : null}

            <Text style={styles.lbl}>Friendly name</Text>
            <TextInput
              testID="d-name"
              value={draft.name}
              onChangeText={(t) => setDraft({ ...draft, name: t })}
              placeholder="E.g. Main Gate Entry"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.input}
            />

            <Text style={styles.lbl}>Direction (IN / OUT / Both)</Text>
            <View style={styles.segRow}>
              <Pressable
                testID="d-kind-in"
                onPress={() => setDraft({ ...draft, kind: "in" })}
                style={[styles.seg, draft.kind === "in" && styles.segOn]}
              >
                <Ionicons
                  name="log-in-outline"
                  size={16}
                  color={draft.kind === "in" ? colors.onCta : colors.brandPrimary}
                />
                <Text style={[styles.segTxt, draft.kind === "in" && styles.segTxtOn]}>
                  IN · Entry
                </Text>
              </Pressable>
              <Pressable
                testID="d-kind-out"
                onPress={() => setDraft({ ...draft, kind: "out" })}
                style={[styles.seg, draft.kind === "out" && styles.segOn]}
              >
                <Ionicons
                  name="log-out-outline"
                  size={16}
                  color={draft.kind === "out" ? colors.onCta : colors.brandPrimary}
                />
                <Text style={[styles.segTxt, draft.kind === "out" && styles.segTxtOn]}>
                  OUT · Exit
                </Text>
              </Pressable>
              <Pressable
                testID="d-kind-both"
                onPress={() => setDraft({ ...draft, kind: "both" })}
                style={[styles.seg, draft.kind === "both" && styles.segOn]}
              >
                <Ionicons
                  name="swap-horizontal-outline"
                  size={16}
                  color={draft.kind === "both" ? colors.onCta : colors.brandPrimary}
                />
                <Text style={[styles.segTxt, draft.kind === "both" && styles.segTxtOn]}>
                  BOTH · Single
                </Text>
              </Pressable>
            </View>
            {draft.kind === "both" ? (
              <Text style={styles.help}>
                Single machine for entry + exit: each employee&apos;s punches alternate
                automatically (1st punch of the day = IN, 2nd = OUT, 3rd = IN …).
              </Text>
            ) : null}

            {isSuper ? (
              <>
                <Text style={styles.lbl}>Company</Text>
                <Pressable onPress={() => setCompanyPickerOpen(true)} style={styles.field}>
                  <Text
                    style={[
                      styles.fieldTxt,
                      !draft.company_id && { color: colors.onSurfaceTertiary },
                    ]}
                    numberOfLines={1}
                  >
                    {draft.company_id ? companyName(draft.company_id) : "Pick company"}
                  </Text>
                  <Ionicons name="chevron-down" size={16} color={colors.onSurfaceSecondary} />
                </Pressable>
              </>
            ) : null}

            {/* Iter 294 — device brand. */}
            <Text style={styles.lbl}>Device Brand</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 4 }}>
              {BRANDS.map((b) => (
                <Pressable
                  key={b.key}
                  onPress={() => setDraft({ ...draft, brand: b.key })}
                  style={[styles.field, { paddingVertical: 8, paddingHorizontal: 12, width: undefined },
                    draft.brand === b.key && { borderColor: colors.brandPrimary, backgroundColor: colors.brandTertiary }]}
                  testID={`d-brand-${b.key}`}
                >
                  <Text style={[styles.fieldTxt, draft.brand === b.key && { color: colors.brandPrimary, fontWeight: "800" }]}>
                    {b.label}
                  </Text>
                </Pressable>
              ))}
            </View>
            <Text style={styles.hint}>
              {BRANDS.find((b) => b.key === draft.brand)?.adms
                ? "ZKTeco / eSSL machines connect via the ADMS (iClock) push protocol — point the device's Cloud Server to this portal."
                : "Matrix / Mantra / other devices push punches as JSON to a per-device Webhook URL — shown on the device card after saving."}
            </Text>

            <Text style={styles.lbl}>Location (optional)</Text>
            <TextInput
              testID="d-loc"
              value={draft.location}
              onChangeText={(t) => setDraft({ ...draft, location: t })}
              placeholder="E.g. Ground floor lobby"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.input}
            />

            {/* Iter 298 — branch tag for two-branch payroll split. */}
            <Text style={styles.lbl}>Branch (optional — multi-branch firms)</Text>
            <TextInput
              testID="d-branch"
              value={(draft as any).branch_name || ""}
              onChangeText={(t) => setDraft({ ...draft, branch_name: t } as any)}
              placeholder="E.g. BRANCH 2 — must match employees' Branch"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.input}
            />
            <Text style={styles.hint}>
              Punches from this machine count as duty at this Branch — used by
              the Actual Salary Process to split an employee&apos;s days between
              branches. Leave blank for single-branch firms.
            </Text>

            {/* Iter 263 — machine GMT / time-zone setting. */}
            <Text style={styles.lbl}>GMT offset (time zone)</Text>
            <TextInput
              testID="d-gmt"
              value={draft.gmt_offset}
              onChangeText={(t) => setDraft({ ...draft, gmt_offset: t })}
              placeholder="+05:30"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.input}
            />
            <Text style={styles.hint}>
              Sent to the machine on every handshake. India = +05:30 (default).
              Examples: +05:30, +04:00, -05:00.
            </Text>

            <Pressable
              onPress={() => setDraft({ ...draft, enabled: !draft.enabled })}
              style={styles.enableRow}
              testID="d-enabled"
            >
              <View>
                <Text style={styles.enableLbl}>Device is active</Text>
                <Text style={styles.enableHint}>
                  Turn off to temporarily reject pushes from this device.
                </Text>
              </View>
              <View style={[styles.toggle, draft.enabled && styles.toggleOn]}>
                <View style={[styles.toggleKnob, draft.enabled && styles.toggleKnobOn]} />
              </View>
            </Pressable>

            <View style={styles.sheetActions}>
              <Pressable onPress={() => setEditorOpen(false)} style={[styles.sheetBtn, styles.sheetCancel]}>
                <Text style={styles.sheetCancelTxt}>Cancel</Text>
              </Pressable>
              <Pressable
                testID="d-save"
                style={[styles.sheetBtn, styles.sheetSubmit, saving && { opacity: 0.7 }]}
                onPress={save}
                disabled={saving}
              >
                {saving ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons name="checkmark-circle" size={16} color="#fff" />
                    <Text style={styles.sheetSubmitTxt}>
                      {editing ? "Save" : "Register"}
                    </Text>
                  </>
                )}
              </Pressable>
            </View>
          </View>
        </KeyboardAwareScrollView>
      </Modal>

      {/* Company picker */}
      <Modal transparent animationType="slide" visible={companyPickerOpen} onRequestClose={() => setCompanyPickerOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setCompanyPickerOpen(false)} />
        <View style={[styles.sheet, { maxHeight: "70%" }]}>
          <View style={styles.grip} />
          <Text style={styles.sheetTitle}>Pick company</Text>
          <ScrollView>
            {companies.map((c) => (
              <Pressable
                key={c.company_id}
                onPress={() => {
                  setDraft({ ...draft, company_id: c.company_id });
                  setCompanyPickerOpen(false);
                }}
                style={styles.pickRow}
              >
                <Text style={styles.pickTxt}>{c.name}</Text>
                {draft.company_id === c.company_id ? (
                  <Ionicons name="checkmark-circle" size={18} color={colors.brandPrimary} />
                ) : null}
              </Pressable>
            ))}
          </ScrollView>
        </View>
      </Modal>

      {/* Setup guide */}
      <Modal transparent animationType="slide" visible={showGuide} onRequestClose={() => setShowGuide(false)}>
        <Pressable style={styles.backdrop} onPress={() => setShowGuide(false)} />
        <View style={[styles.sheet, { maxHeight: "88%" }]}>
          <View style={styles.grip} />
          <View style={styles.guideHead}>
            <Text style={styles.sheetTitle}>ZKTeco AC Mini Plus — Setup Guide</Text>
            <Pressable onPress={() => setShowGuide(false)} hitSlop={8}>
              <Ionicons name="close" size={22} color={colors.onSurface} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
            <SetupGuide devices={devices} />
            <Pressable onPress={shareGuide} style={[styles.shareBtn, { marginTop: 12 }]}>
              <Ionicons name="share-outline" size={14} color={colors.brandPrimary} />
              <Text style={styles.shareTxt}>Copy / share plain-text guide</Text>
            </Pressable>
          </ScrollView>
        </View>
      </Modal>

      {/* Iter 262 — Set machine date & time (editable) */}
      <Modal transparent animationType="fade" visible={!!timeDlg} onRequestClose={() => setTimeDlg(null)}>
        <Pressable style={styles.backdrop} onPress={() => setTimeDlg(null)} />
        <View style={styles.timeDlgWrap} pointerEvents="box-none">
          <View style={styles.timeDlgCard} testID="time-dialog">
            <View style={styles.guideHead}>
              <Text style={styles.sheetTitle}>Set machine date & time</Text>
              <Pressable onPress={() => setTimeDlg(null)} hitSlop={8}>
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            <Text style={styles.timeDlgSub}>
              {timeDlg?.name} · SN {timeDlg?.serial_number}. Edit the values below and press
              Apply — the machine clock updates within seconds while it is online.
            </Text>
            <Text style={styles.timeDlgLabel}>Date (DD-MM-YYYY)</Text>
            <TextInput
              value={dlgDate}
              onChangeText={setDlgDate}
              placeholder="23-06-2026"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.timeDlgInput}
              keyboardType={Platform.OS === "web" ? undefined : "numbers-and-punctuation"}
              testID="time-dialog-date"
            />
            <Text style={styles.timeDlgLabel}>Time (HH:MM:SS — 24 hour)</Text>
            <TextInput
              value={dlgTime}
              onChangeText={setDlgTime}
              placeholder="09:30:00"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.timeDlgInput}
              keyboardType={Platform.OS === "web" ? undefined : "numbers-and-punctuation"}
              testID="time-dialog-time"
            />
            <View style={{ flexDirection: "row", gap: 8, marginTop: 14 }}>
              <Pressable onPress={() => fillNow()} style={[styles.actBtn, styles.actGhost, { flex: 1 }]}>
                <Ionicons name="time-outline" size={14} color={colors.brandPrimary} />
                <Text style={styles.actGhostTxt}>Use current time</Text>
              </Pressable>
              <Pressable
                onPress={applyTime}
                style={[styles.addBtn, { flex: 1, marginTop: 0 }]}
                testID="time-dialog-apply"
              >
                <Ionicons name="checkmark-circle" size={16} color={colors.onCta} />
                <Text style={styles.addBtnTxt}>Apply to machine</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

// ---------------------------- Sub-components ----------------------------

function Header({
  title,
  onBack,
  right,
}: {
  title: string;
  onBack: () => void;
  right?: React.ReactNode;
}) {
  return (
    <View style={styles.header}>
      <Pressable onPress={onBack} hitSlop={8}>
        <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
      </Pressable>
      <Text style={styles.h1}>{title}</Text>
      <View style={{ minWidth: 26, alignItems: "flex-end" }}>{right || null}</View>
    </View>
  );
}

function SummaryTile({
  icon,
  label,
  value,
  accent,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  value: number;
  accent: string;
}) {
  return (
    <View style={[styles.sumTile, { borderLeftColor: accent }]}>
      <Ionicons name={icon} size={18} color={accent} />
      <Text style={styles.sumVal}>{value}</Text>
      <Text style={styles.sumLbl}>{label}</Text>
    </View>
  );
}

function DeviceCard({
  device,
  busy,
  resyncing,
  companyName,
  onEdit,
  onDelete,
  onSimulate,
  onResync,
  onCommand,
  onPushEmployees,
  onFetchTemplates,
  onSyncTemplates,
  onToggleLock,
  onToggleIpLock,
}: {
  device: Device;
  busy: boolean;
  resyncing: boolean;
  companyName: string;
  onEdit: () => void;
  onDelete: () => void;
  onSimulate: () => void;
  onResync: () => void;
  onCommand: (action: string) => void;
  onPushEmployees: () => void;
  onFetchTemplates: () => void;
  onSyncTemplates: () => void;
  onToggleLock: () => void;
  onToggleIpLock: () => void;
}) {
  const kindColor = device.kind === "in" ? colors.brandPrimary : colors.accent;
  return (
    <View style={styles.card} testID={`device-${device.device_id}`}>
      <View style={styles.cardHead}>
        <View style={[styles.kindPill, { backgroundColor: kindColor }]}>
          <Ionicons
            name={device.kind === "in" ? "log-in-outline" : "log-out-outline"}
            size={12}
            color="#fff"
          />
          <Text style={styles.kindPillTxt}>{device.kind.toUpperCase()}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.name} numberOfLines={1}>{device.name}</Text>
          <Text style={styles.sn}>
            SN · {device.serial_number}
            {device.brand && device.brand !== "zkteco" ? `  ·  ${device.brand.toUpperCase()}` : ""}
          </Text>
        </View>
        <View style={styles.dot}>
          {device.locked ? (
            <View style={styles.lockedBadge}>
              <Ionicons name="lock-closed" size={10} color="#fff" />
              <Text style={styles.lockedBadgeTxt}>LOCKED</Text>
            </View>
          ) : null}
          <BlinkDot online={!!device.online} />
          <Text style={[styles.dotTxt, { color: device.online ? "#2563EB" : "#DC2626", fontWeight: "800" }]}>
            {device.online ? "Online" : "Offline"}
          </Text>
        </View>
      </View>

      {/* Iter 294 — JSON webhook URL for Matrix / Mantra / other brands. */}
      {device.webhook_key && device.brand && !["zkteco", "essl"].includes(device.brand) ? (
        <Pressable
          onPress={() => {
            if (Platform.OS === "web" && navigator?.clipboard) {
              navigator.clipboard.writeText(
                `${window.location.origin}/api/device-webhook/${device.webhook_key}`);
              alertUser("Copied", "Webhook URL copied to clipboard. Configure your device middleware to POST JSON punches to it.");
            }
          }}
          style={styles.webhookRow}
          testID={`webhook-${device.serial_number}`}
        >
          <Ionicons name="link-outline" size={13} color="#2563EB" />
          <Text style={styles.webhookTxt} numberOfLines={1}>
            Webhook: /api/device-webhook/{device.webhook_key}
          </Text>
          <Ionicons name="copy-outline" size={13} color="#2563EB" />
        </Pressable>
      ) : null}

      <View style={styles.factGrid}>
        <Fact label="COMPANY" value={companyName} />
        <Fact label="LOCATION" value={device.location || "—"} />
        <Fact label="GMT" value={device.gmt_offset || "+05:30"} />
        <Fact
          label="SOURCE IP"
          value={device.ip_lock ? `${device.last_source_ip || "—"} 🔒` : (device.last_source_ip || "—")}
        />
        <Fact
          label="LAST SEEN"
          value={device.last_seen_at ? fmtRelative(device.last_seen_at) : "Never"}
        />
        <Fact
          label="PUNCHES"
          value={String(device.total_punches_ingested || 0)}
          accent
        />
        <Fact label="FIRMWARE" value={(device as any).firmware || "—"} />
        <Fact label="USERS ON DEVICE" value={(device as any).user_count != null ? String((device as any).user_count) : "—"} />
        <Fact label="FINGERPRINTS" value={(device as any).fp_count != null ? String((device as any).fp_count) : "—"} />
        <Fact label="LOGS ON DEVICE" value={(device as any).att_log_count != null ? String((device as any).att_log_count) : "—"} />
        <Fact label="DEVICE IP" value={(device as any).device_ip || "—"} />
      </View>

      {/* Iter 258 — remote device controls (executed within seconds while
          the machine is online; queued until it connects otherwise). */}
      <View style={styles.actions}>
        {([
          ["sync_data", "sync-outline", "Sync data"],
          ["refresh_info", "information-circle-outline", "Refresh info"],
          ["sync_time", "time-outline", "Set date & time"],
          ["restart", "power-outline", "Restart"],
        ] as [string, any, string][]).map(([action, icon, label]) => (
          <Pressable
            key={action}
            onPress={() => onCommand(action)}
            style={[styles.actBtn, styles.actGhost]}
            testID={`cmd-${action}-${device.device_id}`}
          >
            <Ionicons name={icon} size={14} color={colors.brandPrimary} />
            <Text style={styles.actGhostTxt}>{label}</Text>
          </Pressable>
        ))}
        <Pressable
          onPress={onPushEmployees}
          style={[styles.actBtn, styles.actGhost]}
          testID={`cmd-push-emps-${device.device_id}`}
        >
          <Ionicons name="people-outline" size={14} color={colors.brandPrimary} />
          <Text style={styles.actGhostTxt}>Push employees</Text>
        </Pressable>
      </View>

      {/* Iter 261 — Phase 2: FP/Face template sync + lock/unlock + door. */}
      <View style={styles.actions}>
        <Pressable
          onPress={onFetchTemplates}
          style={[styles.actBtn, styles.actGhost]}
          testID={`cmd-fetch-tmpl-${device.device_id}`}
        >
          <Ionicons name="finger-print-outline" size={14} color={colors.brandPrimary} />
          <Text style={styles.actGhostTxt}>Fetch FP/Face</Text>
        </Pressable>
        <Pressable
          onPress={onSyncTemplates}
          style={[styles.actBtn, styles.actGhost]}
          testID={`cmd-sync-tmpl-${device.device_id}`}
        >
          <Ionicons name="cloud-upload-outline" size={14} color={colors.brandPrimary} />
          <Text style={styles.actGhostTxt}>Sync FP/Face</Text>
        </Pressable>
        <Pressable
          onPress={() => onCommand("unlock_door")}
          style={[styles.actBtn, styles.actGhost]}
          testID={`cmd-unlock-door-${device.device_id}`}
        >
          <Ionicons name="key-outline" size={14} color={colors.brandPrimary} />
          <Text style={styles.actGhostTxt}>Unlock door</Text>
        </Pressable>
        <Pressable
          onPress={onToggleLock}
          style={[styles.actBtn, device.locked ? styles.actGhost : styles.actDanger]}
          testID={`cmd-lock-${device.device_id}`}
        >
          <Ionicons
            name={device.locked ? "lock-open-outline" : "lock-closed-outline"}
            size={14}
            color={device.locked ? colors.brandPrimary : colors.error}
          />
          <Text style={device.locked ? styles.actGhostTxt : styles.actDangerTxt}>
            {device.locked ? "Unlock device" : "Lock device"}
          </Text>
        </Pressable>
        <Pressable
          onPress={onToggleIpLock}
          style={[styles.actBtn, styles.actGhost]}
          testID={`cmd-ip-lock-${device.device_id}`}
        >
          <Ionicons
            name={device.ip_lock ? "shield-checkmark" : "shield-outline"}
            size={14}
            color={device.ip_lock ? "#16A34A" : colors.brandPrimary}
          />
          <Text style={styles.actGhostTxt}>
            {device.ip_lock ? "Unlock IP" : "Lock to IP"}
          </Text>
        </Pressable>
      </View>

      <View style={styles.actions}>
        <Pressable
          onPress={onResync}
          disabled={resyncing}
          style={[styles.actBtn, styles.actGhost, resyncing && { opacity: 0.6 }]}
          testID={`resync-${device.device_id}`}
        >
          {resyncing ? (
            <ActivityIndicator color={colors.brandPrimary} size="small" />
          ) : (
            <>
              <Ionicons name="cloud-download-outline" size={14} color={colors.brandPrimary} />
              <Text style={styles.actGhostTxt}>Fetch old data</Text>
            </>
          )}
        </Pressable>
        <Pressable
          onPress={onSimulate}
          disabled={busy}
          style={[styles.actBtn, styles.actGhost, busy && { opacity: 0.6 }]}
        >
          {busy ? (
            <ActivityIndicator color={colors.brandPrimary} size="small" />
          ) : (
            <>
              <Ionicons name="flash-outline" size={14} color={colors.brandPrimary} />
              <Text style={styles.actGhostTxt}>Test punch</Text>
            </>
          )}
        </Pressable>
        <Pressable onPress={onEdit} style={[styles.actBtn, styles.actGhost]}>
          <Ionicons name="create-outline" size={14} color={colors.brandPrimary} />
          <Text style={styles.actGhostTxt}>Edit</Text>
        </Pressable>
        <Pressable onPress={onDelete} style={[styles.actBtn, styles.actDanger]}>
          <Ionicons name="trash-outline" size={14} color={colors.error} />
          <Text style={styles.actDangerTxt}>Remove</Text>
        </Pressable>
      </View>
    </View>
  );
}

// Iter 251 (user request) — machine status LED: BLUE blink while online,
// RED blink while offline.
function BlinkDot({ online }: { online: boolean }) {
  const opacity = React.useRef(new Animated.Value(1)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 0.15,
          duration: online ? 600 : 450,
          useNativeDriver: Platform.OS !== "web",
        }),
        Animated.timing(opacity, {
          toValue: 1,
          duration: online ? 600 : 450,
          useNativeDriver: Platform.OS !== "web",
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [online, opacity]);
  const color = online ? "#2563EB" : "#DC2626";
  return (
    <Animated.View
      style={[
        styles.dotCircle,
        {
          backgroundColor: color,
          opacity,
          shadowColor: color,
          shadowOpacity: 0.9,
          shadowRadius: 4,
          shadowOffset: { width: 0, height: 0 },
        },
      ]}
    />
  );
}

function Fact({ label, value, accent }: { label: string; value: string; accent?: boolean }) {  return (
    <View style={styles.fact}>
      <Text style={styles.factLbl}>{label}</Text>
      <Text
        style={[styles.factVal, accent && { color: colors.brandPrimary, fontWeight: "800" }]}
        numberOfLines={1}
      >
        {value}
      </Text>
    </View>
  );
}

function SetupGuide({ devices }: { devices: Device[] }) {
  const sn1 = devices.find((d) => d.kind === "in" || d.kind === "both")?.serial_number || "<Entry-device-SN>";
  const sn2 = devices.find((d) => d.kind === "out")?.serial_number || "<Exit-device-SN>";
  return (
    <View style={{ paddingTop: 8 }}>
      <GuideStep n={1} title="Your server domain">
        This portal runs at{" "}
        <Text style={styles.mono}>https://www.smartpayrolling.com</Text>. All ZKTeco devices
        must point at this domain.
      </GuideStep>
      <GuideStep n={2} title="Register the device(s) in the app">
        On this screen, tap <Text style={styles.b}>Register new device</Text>. For a single
        machine handling entry + exit, pick <Text style={styles.b}>BOTH · Single</Text>{" "}
        (punches auto-alternate IN/OUT). For two machines, register one as IN and one as OUT.
        Enter each machine&apos;s <Text style={styles.b}>Serial Number</Text> (on the device
        sticker or under <Text style={styles.mono}>Menu → System → About</Text>).
      </GuideStep>
      <GuideStep n={3} title="Configure the device">
        On the ZKTeco AC Mini Plus keypad go to:
        {"\n\n"}
        <Text style={styles.mono}>
          Menu → Comm → ADMS (Cloud Server Setting)
          {"\n"}Server Mode: ADMS
          {"\n"}Enable Domain Name: ON
          {"\n"}Server Address: http://www.smartpayrolling.com
          {"\n"}   (if http:// is not accepted, enter: www.smartpayrolling.com)
          {"\n"}Enable Proxy Server: OFF
          {"\n"}Proxy Server IP: (leave blank)
          {"\n"}Proxy Server Port: (leave blank)
        </Text>
        {"\n\n"}
        Then <Text style={styles.b}>Save</Text> and restart the device. It will connect within
        30–60 seconds. (Entry/Both device Serial:{" "}
        <Text style={styles.mono}>{sn1}</Text>).
      </GuideStep>
      <GuideStep n={4} title="Second device (only for IN + OUT pairs)">
        If you use two machines, repeat the same steps on the second machine — same server
        settings but tag it as <Text style={styles.b}>OUT</Text> in this app (Serial:{" "}
        <Text style={styles.mono}>{sn2}</Text>). Every punch from this device becomes a
        Punch-OUT.
      </GuideStep>
      <GuideStep n={5} title="Enrol employees with matching bio-code">
        For every employee in the app, open their profile and set{" "}
        <Text style={styles.b}>Bio Code</Text> to the number they punch on the device (e.g.
        1001). We match device punches to app employees using this field — no manual mapping
        needed on the device side.
      </GuideStep>
      <GuideStep n={6} title="Verify real-time push">
        After configuration, punch once on each device. Within 3–5 seconds the punches should
        appear on the <Text style={styles.b}>Attendance</Text> tab of the corresponding
        employee. The device card here will turn <Text style={styles.b}>Online</Text> once it
        starts pushing.
      </GuideStep>
      <GuideStep n={7} title="Keep the connection stable (IP & power)">
        The machine always dials <Text style={styles.b}>out</Text> to the server, so the
        machine&apos;s own IP changing does <Text style={styles.b}>not</Text> break punch
        syncing. Still, give the machine a fixed IP so it is always reachable on your LAN:
        {"\n\n"}
        <Text style={styles.mono}>
          Menu → Comm → Ethernet
          {"\n"}DHCP: OFF
          {"\n"}IP Address: 192.168.1.201 (pick one outside the router&apos;s DHCP range)
          {"\n"}Subnet Mask: 255.255.255.0
          {"\n"}Gateway: your router IP (usually 192.168.1.1)
          {"\n"}DNS: 8.8.8.8
        </Text>
        {"\n\n"}
        (Alternative: keep DHCP ON and add a <Text style={styles.b}>DHCP reservation</Text>{" "}
        for the machine&apos;s MAC address in your router — same fixed IP, no device change.)
        {"\n\n"}
        <Text style={styles.b}>After a power cut:</Text> the machine sometimes boots before
        the internet router is ready and then waits on a long retry cycle. If punches stop
        appearing for 2–3 minutes, restart the machine once. Best practice: power the machine
        and router from a small UPS so both stay online together.
      </GuideStep>
      <GuideStep n={8} title="Approval policy">
        Machine punches are <Text style={styles.b}>auto-approved</Text> — they skip the
        Punch-Approvals queue (which is used only for mobile auto-punches). If a device pushes
        a User ID that is not enrolled in the app, it lands in the{" "}
        <Text style={styles.b}>Unmapped Punches</Text> log for follow-up.
      </GuideStep>
    </View>
  );
}

function GuideStep({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <View style={styles.step}>
      <View style={styles.stepNum}>
        <Text style={styles.stepNumTxt}>{n}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.stepTitle}>{title}</Text>
        <Text style={styles.stepBody}>{children as any}</Text>
      </View>
    </View>
  );
}

// ---------------------------- helpers ----------------------------
// Iter 261 — live feed timestamp: "DD-MMM HH:MM" (today → "HH:MM").
function fmtFeedTime(iso: string): string {
  try {
    const d = new Date(iso);
    const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    const today = new Date();
    if (d.toDateString() === today.toDateString()) return hm;
    return `${String(d.getDate()).padStart(2, "0")}-${d.toLocaleString("en", { month: "short" })} ${hm}`;
  } catch {
    return iso;
  }
}

function fmtRelative(iso: string): string {
  try {
    const now = Date.now();
    const then = new Date(iso).getTime();
    const s = Math.max(1, Math.floor((now - then) / 1000));
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    return `${d}d ago`;
  } catch {
    return iso;
  }
}

function alertUser(title: string, msg: string) {
  if (Platform.OS === "web") {
    if (typeof window !== "undefined") window.alert(`${title}\n\n${msg}`);
    return;
  }
  Alert.alert(title, msg);
}

function buildSetupGuideText(devices: Device[]): string {
  const inD = devices.find((d) => d.kind === "in" || d.kind === "both");
  const outD = devices.find((d) => d.kind === "out");
  return [
    "ZKTeco AC Mini Plus — Real-time integration with S.K. Sharma & Co. workforce app",
    "",
    "Server domain: https://www.smartpayrolling.com",
    "",
    "1. Register the device(s) from the app (Biometric Devices screen):",
    "     • Single machine for entry + exit → register as BOTH (punches auto-alternate IN/OUT)",
    "     • Two machines → register one as IN and one as OUT",
    "2. On each device, go to Menu → Comm → ADMS (Cloud Server Setting):",
    "     Server Mode: ADMS",
    "     Enable Domain Name: ON",
    "     Server Address: http://www.smartpayrolling.com",
    "       (if http:// is not accepted, enter: www.smartpayrolling.com)",
    "     Enable Proxy Server: OFF",
    "     Proxy Server IP: (leave blank)",
    "     Proxy Server Port: (leave blank)",
    "3. Save & restart the device. It connects within 30–60 seconds.",
    "4. Enrol employees — set each app user's `bio_code` to the number they punch on the device.",
    "5. Punch on the device — it appears in the app within 3–5 seconds.",
    "",
    "KEEPING THE CONNECTION STABLE (IP & POWER):",
    "  • The machine dials OUT to the server — its own IP changing does NOT break syncing.",
    "  • Still, set a fixed IP: Menu → Comm → Ethernet → DHCP OFF →",
    "      IP 192.168.1.201 / Subnet 255.255.255.0 / Gateway (router IP) / DNS 8.8.8.8",
    "    (or add a DHCP reservation for the machine's MAC address in the router).",
    "  • After a power cut, if punches stop for 2–3 minutes, restart the machine once",
    "    (it may have booted before the router). Ideally power machine + router via a UPS.",
    "",
    `Entry / Both device: SN ${inD?.serial_number || "(register first)"}`,
    `Exit (OUT) device:  SN ${outD?.serial_number || "(only for IN+OUT pairs)"}`,
    "",
    "Machine punches are auto-approved. Unmapped device users are logged for follow-up.",
  ].join("\n");
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  h1: { fontSize: type.lg, color: colors.onSurface, fontWeight: "700", flex: 1, marginLeft: 8 },
  headBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
  },
  headBtnTxt: { color: colors.brandPrimary, fontSize: 11, fontWeight: "700" },

  scroll: { padding: spacing.lg, paddingBottom: spacing.xl },

  summary: { flexDirection: "row", gap: 8, marginBottom: spacing.lg },
  sumTile: {
    flex: 1,
    padding: 10,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderLeftWidth: 3,
    gap: 2,
  },
  sumVal: { color: colors.onSurface, fontSize: 22, fontWeight: "800" },
  sumLbl: { color: colors.onSurfaceTertiary, fontSize: 9, fontWeight: "700", letterSpacing: 0.4 },

  addBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: colors.brandPrimary,
    paddingVertical: 12,
    borderRadius: radius.pill,
    marginBottom: spacing.md,
    ...shadow.cta,
  },
  addBtnTxt: { color: colors.onCta, fontWeight: "700", fontSize: type.base },

  emptyBox: {
    alignItems: "center",
    padding: spacing.xl,
    gap: 10,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
    borderRadius: radius.md,
    marginTop: spacing.sm,
  },
  emptyTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  emptyBody: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    textAlign: "center",
    lineHeight: 20,
  },
  emptyLink: { marginTop: 6 },
  emptyLinkTxt: { color: colors.brandPrimary, fontWeight: "700" },

  // Iter 261 — Live Dashboard styles.
  liveCard: {
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    ...shadow.card,
  },
  liveHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  liveDot: {
    width: 8, height: 8, borderRadius: 4, backgroundColor: "#16A34A",
  },
  liveTitle: { fontWeight: "800", color: colors.onSurface, fontSize: type.md },
  liveSub: { flex: 1, textAlign: "right", color: colors.onSurfaceTertiary, fontSize: type.xs },
  liveEmpty: { color: colors.onSurfaceTertiary, fontSize: type.sm, paddingVertical: 10 },
  liveRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 5,
    borderTopWidth: 1,
    borderTopColor: colors.divider,
  },
  liveTime: { width: 86, color: colors.onSurfaceSecondary, fontSize: type.xs, fontVariant: ["tabular-nums"] },
  livePill: { paddingHorizontal: 6, paddingVertical: 1.5, borderRadius: 6 },
  livePillTxt: { fontSize: 9.5, fontWeight: "800" },
  liveName: { flex: 1, color: colors.onSurface, fontSize: type.sm, fontWeight: "600" },
  liveDevice: { maxWidth: 130, color: colors.onSurfaceTertiary, fontSize: type.xs },
  lockedBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    backgroundColor: "#DC2626",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 6,
    marginBottom: 3,
  },
  lockedBadgeTxt: { color: "#fff", fontSize: 9, fontWeight: "800" },

  // Iter 262 — Set date & time dialog.
  timeDlgWrap: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.lg,
  },
  timeDlgCard: {
    width: "100%",
    maxWidth: 440,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    ...shadow.card,
  },
  timeDlgSub: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginBottom: 10,
    lineHeight: 18,
  },
  timeDlgLabel: {
    color: colors.onSurfaceTertiary,
    fontSize: type.xs,
    fontWeight: "800",
    marginTop: 8,
    marginBottom: 4,
    textTransform: "uppercase",
  },
  // Iter 263 — small helper text under form fields.
  hint: {
    color: colors.onSurfaceTertiary,
    fontSize: type.xs,
    marginTop: 4,
    lineHeight: 15,
  },
  timeDlgInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: type.md,
    color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary,
    fontVariant: ["tabular-nums"],
  },

  card: {
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    marginBottom: spacing.md,
    gap: 8,
    ...shadow.card,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 10 },
  kindPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  kindPillTxt: { color: "#fff", fontWeight: "800", fontSize: 10, letterSpacing: 0.6 },
  name: { color: colors.onSurface, fontWeight: "700", fontSize: type.base },
  sn: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },
  // Iter 294 — webhook URL row (Matrix / Mantra JSON push).
  webhookRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#EFF6FF", borderWidth: 1, borderColor: "#BFDBFE",
    borderRadius: 8, paddingHorizontal: 10, paddingVertical: 7, marginTop: 8,
  },
  webhookTxt: { flex: 1, fontSize: 10.5, color: "#2563EB", fontWeight: "600" },

  dot: { flexDirection: "row", alignItems: "center", gap: 4 },
  dotCircle: { width: 10, height: 10, borderRadius: 5 },
  dotTxt: { color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "600" },

  factGrid: { flexDirection: "row", flexWrap: "wrap" },
  fact: { width: "50%", paddingVertical: 4 },
  factLbl: { color: colors.onSurfaceTertiary, fontSize: 9, fontWeight: "700", letterSpacing: 0.4 },
  factVal: { color: colors.onSurface, fontSize: type.sm, fontWeight: "600", marginTop: 2 },

  actions: { flexDirection: "row", gap: 8, marginTop: 6 },
  actBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1,
  },
  actGhost: { backgroundColor: colors.brandTertiary, borderColor: colors.brandPrimary },
  actGhostTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  actDanger: { backgroundColor: colors.surface, borderColor: colors.error },
  actDangerTxt: { color: colors.error, fontWeight: "700", fontSize: 12 },

  shareBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    marginTop: spacing.md,
  },
  shareTxt: { color: colors.brandPrimary, fontWeight: "600", fontSize: type.sm },

  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.error,
    padding: spacing.sm,
    borderRadius: radius.md,
    marginBottom: spacing.md,
  },
  errTxt: { color: "#fff", fontSize: type.sm, flex: 1 },

  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: 10 },
  dimTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },

  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.4)" },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    padding: spacing.lg,
    maxHeight: "90%",
  },
  grip: {
    alignSelf: "center",
    width: 44,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    marginBottom: 4,
  },
  sheetTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  sheetSub: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    lineHeight: 18,
    marginTop: 4,
  },
  guideHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },

  lbl: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "600",
    marginTop: 10,
    marginBottom: 4,
  },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.onSurface,
    fontSize: type.base,
  },
  help: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 4 },
  field: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  fieldTxt: { color: colors.onSurface, fontSize: type.base, flex: 1 },

  segRow: { flexDirection: "row", gap: 8 },
  seg: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  segOn: { backgroundColor: colors.brandPrimary },
  segTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: type.sm },
  segTxtOn: { color: colors.onCta },

  enableRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
    marginTop: spacing.md,
  },
  enableLbl: { color: colors.onSurface, fontSize: type.base, fontWeight: "600", flex: 1 },
  enableHint: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 2, flex: 1 },
  toggle: { width: 44, height: 26, borderRadius: 13, backgroundColor: colors.border, padding: 2, justifyContent: "center" },
  toggleOn: { backgroundColor: colors.brandPrimary },
  toggleKnob: { width: 22, height: 22, borderRadius: 11, backgroundColor: "#fff" },
  toggleKnobOn: { alignSelf: "flex-end" },

  sheetActions: { flexDirection: "row", gap: 10, marginTop: spacing.lg },
  sheetBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderRadius: radius.pill,
  },
  sheetCancel: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  sheetCancelTxt: { color: colors.onSurface, fontWeight: "700" },
  sheetSubmit: { backgroundColor: colors.brandPrimary },
  sheetSubmitTxt: { color: "#fff", fontWeight: "700" },

  pickRow: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  pickTxt: { color: colors.onSurface, fontSize: type.base },

  step: {
    flexDirection: "row",
    gap: 12,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    marginTop: 10,
  },
  stepNum: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  stepNumTxt: { color: colors.onCta, fontWeight: "800" },
  stepTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "700", marginBottom: 4 },
  stepBody: { color: colors.onSurfaceSecondary, fontSize: type.sm, lineHeight: 20 },
  b: { fontWeight: "800", color: colors.onSurface },
  mono: {
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    color: colors.brandPrimary,
    fontSize: 13,
  },
});
