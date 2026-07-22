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
  Platform,
  Share,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

import { api } from "@/src/api/client";
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
  last_seen_at?: string | null;
  last_push_at?: string | null;
  model?: string;
  total_pushes?: number;
  total_punches_ingested?: number;
};

type Company = { company_id: string; name: string };

const emptyDraft = {
  serial_number: "",
  name: "",
  kind: "in" as "in" | "out" | "both",
  company_id: "",
  location: "",
  enabled: true,
};

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
          const c = await api<{ companies: Company[] }>("/companies");
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

          {error ? (
            <View style={styles.errBox}>
              <Ionicons name="alert-circle" size={16} color="#fff" />
              <Text style={styles.errTxt}>{error}</Text>
            </View>
          ) : null}

          <Pressable testID="add-device-btn" style={styles.addBtn} onPress={openCreate}>
            <Ionicons name="add-circle" size={18} color={colors.onCta} />
            <Text style={styles.addBtnTxt}>Register new device</Text>
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

            <Text style={styles.lbl}>Location (optional)</Text>
            <TextInput
              testID="d-loc"
              value={draft.location}
              onChangeText={(t) => setDraft({ ...draft, location: t })}
              placeholder="E.g. Ground floor lobby"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.input}
            />

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
}: {
  device: Device;
  busy: boolean;
  resyncing: boolean;
  companyName: string;
  onEdit: () => void;
  onDelete: () => void;
  onSimulate: () => void;
  onResync: () => void;
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
          <Text style={styles.sn}>SN · {device.serial_number}</Text>
        </View>
        <View style={styles.dot}>
          <View style={[styles.dotCircle, { backgroundColor: device.online ? "#22C55E" : colors.onSurfaceTertiary }]} />
          <Text style={styles.dotTxt}>{device.online ? "Online" : "Offline"}</Text>
        </View>
      </View>

      <View style={styles.factGrid}>
        <Fact label="COMPANY" value={companyName} />
        <Fact label="LOCATION" value={device.location || "—"} />
        <Fact
          label="LAST SEEN"
          value={device.last_seen_at ? fmtRelative(device.last_seen_at) : "Never"}
        />
        <Fact
          label="PUNCHES"
          value={String(device.total_punches_ingested || 0)}
          accent
        />
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

function Fact({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
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

  dot: { flexDirection: "row", alignItems: "center", gap: 4 },
  dotCircle: { width: 8, height: 8, borderRadius: 4 },
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
