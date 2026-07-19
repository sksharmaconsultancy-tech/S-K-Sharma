// Iter 176 — Guided punch workflow (user-specified pipeline):
//   Login → GPS Verification → Select Worksite (if applicable) →
//   Face Verification → Optional Device Biometric → Attendance Saved
//   (Photo + Location + Time stored) → Payroll Updated.
// A visible stepper walks the employee through each stage.
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Modal,
  ActivityIndicator,
  Platform,
  ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Location from "expo-location";
import * as LocalAuthentication from "expo-local-authentication";

import { api } from "@/src/api/client";
import { colors, radius, type } from "@/src/theme";
import FaceCaptureModal from "@/src/components/FaceCaptureModal";
import {
  fingerprintSupported, verifyFingerprint, enrollFingerprint, fingerprintEnrolled,
} from "@/src/utils/fingerprintGate";
import { formatDistance } from "@/src/utils/location";

type Worksite = {
  worksite_id: string;
  name: string;
  office_lat: number;
  office_lng: number;
  geofence_radius_m: number;
};

type StepKey = "gps" | "worksite" | "face" | "biometric" | "save";
type StepState = "pending" | "active" | "done" | "skipped" | "failed";

type Props = {
  visible: boolean;
  kind: "in" | "out";
  user: any;
  /** Offline-capable poster from the attendance screen. Falls back to a
   *  direct API call when not provided. Returns {offline:true} if queued. */
  postPunch?: (body: Record<string, any>) => Promise<any>;
  onClose: () => void;
  onDone: () => void;
};

const STEP_META: Record<StepKey, { label: string; icon: string }> = {
  gps: { label: "GPS Verification", icon: "location-outline" },
  worksite: { label: "Select Worksite", icon: "business-outline" },
  face: { label: "Face Verification", icon: "happy-outline" },
  biometric: { label: "Device Biometric", icon: "finger-print-outline" },
  save: { label: "Save Attendance", icon: "cloud-done-outline" },
};

function haversineM(lat1: number, lon1: number, lat2: number, lon2: number) {
  const R = 6371000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

export default function PunchFlowModal({ visible, kind, user, postPunch, onClose, onDone }: Props) {
  const [steps, setSteps] = useState<Record<StepKey, StepState>>({
    gps: "pending", worksite: "pending", face: "pending", biometric: "pending", save: "pending",
  });
  const [stepNote, setStepNote] = useState<Partial<Record<StepKey, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [coords, setCoords] = useState<{ latitude: number; longitude: number } | null>(null);
  const [worksites, setWorksites] = useState<Worksite[]>([]);
  const [chosenSite, setChosenSite] = useState<Worksite | null>(null);
  const [awaitingSitePick, setAwaitingSitePick] = useState(false);
  const [faceOpen, setFaceOpen] = useState(false);
  const [result, setResult] = useState<{ pending: boolean; distance_m: number; offline?: boolean } | null>(null);
  const runningRef = useRef(false);
  const selfieRef = useRef<string | null>(null);
  const methodRef = useRef<"fingerprint" | "face">("face");

  const setStep = (k: StepKey, s: StepState, note?: string) => {
    setSteps((p) => ({ ...p, [k]: s }));
    if (note !== undefined) setStepNote((p) => ({ ...p, [k]: note }));
  };

  const reset = () => {
    setSteps({ gps: "pending", worksite: "pending", face: "pending", biometric: "pending", save: "pending" });
    setStepNote({});
    setError(null);
    setCoords(null);
    setChosenSite(null);
    setAwaitingSitePick(false);
    setResult(null);
    selfieRef.current = null;
    runningRef.current = false;
  };

  // ---- Step 1: GPS verification (mandatory geofence) ----
  const runGps = useCallback(async (): Promise<{ ok: boolean; sites: Worksite[]; pos?: { latitude: number; longitude: number } }> => {
    setStep("gps", "active");
    let sites: Worksite[] = [];
    try {
      const r = await api<{ worksites: Worksite[] }>("/attendance/worksites");
      sites = r.worksites || [];
      setWorksites(sites);
    } catch { /* worksites optional */ }
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (!perm.granted) {
        setStep("gps", "failed", "Location permission denied — enable GPS to punch.");
        setError("Turn on location — geofence verification is mandatory for every punch.");
        return { ok: false, sites };
      }
      const l = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      const pos = { latitude: l.coords.latitude, longitude: l.coords.longitude };
      setCoords(pos);
      if (!sites.length) {
        setStep("gps", "done", "Location captured (no geofence configured)");
        return { ok: true, sites, pos };
      }
      // nearest site
      let best: Worksite = sites[0];
      let bestD = Infinity;
      for (const s of sites) {
        const d = haversineM(pos.latitude, pos.longitude, s.office_lat, s.office_lng);
        if (d < bestD) { bestD = d; best = s; }
      }
      const inside = bestD <= (best.geofence_radius_m || 200);
      if (!inside && !user?.is_live_in) {
        setStep("gps", "failed", `${formatDistance(bestD)} outside ${best.name}`);
        setError(`You're ${formatDistance(bestD - (best.geofence_radius_m || 200))} outside the work zone. Come inside the geofence to punch.`);
        return { ok: false, sites };
      }
      setChosenSite(best);
      setStep("gps", "done", `Inside geofence · ${Math.round(bestD)}m from ${best.name}`);
      return { ok: true, sites, pos };
    } catch {
      setStep("gps", "failed", "Could not get your location");
      setError("Could not fetch GPS location. Check location settings and retry.");
      return { ok: false, sites };
    }
  }, [user]);

  // ---- Step 2: worksite selection (if applicable) ----
  const runWorksite = useCallback(async (sites: Worksite[]): Promise<boolean> => {
    if (sites.length <= 1) {
      setStep("worksite", "skipped", sites.length === 1 ? sites[0].name : "Not applicable");
      return true;
    }
    setStep("worksite", "active", "Choose your worksite below");
    setAwaitingSitePick(true);
    return false; // flow resumes when user picks
  }, []);

  // ---- Step 3: face verification ----
  const runFace = useCallback(() => {
    setStep("face", "active", "Position your face inside the oval");
    setFaceOpen(true);
  }, []);

  // ---- Step 4: optional device biometric ----
  const runBiometric = useCallback(async (): Promise<boolean> => {
    setStep("biometric", "active");
    try {
      if (Platform.OS === "web") {
        const required = user?.fingerprint_required === true;
        const supported = await fingerprintSupported();
        if (!supported) {
          if (required) {
            setStep("biometric", "failed", "Fingerprint not supported on this device");
            setError("Fingerprint verification is required by your company but this device doesn't support it.");
            return false;
          }
          setStep("biometric", "skipped", "Not supported on this device");
          return true;
        }
        if (!required && !fingerprintEnrolled(user?.user_id || "")) {
          setStep("biometric", "skipped", "Optional — enable in Profile → Biometric preferences");
          return true;
        }
        let r = await verifyFingerprint(user!.user_id, `Verify fingerprint to punch ${kind.toUpperCase()}`);
        if (!r.ok && !fingerprintEnrolled(user?.user_id || "")) {
          const e = await enrollFingerprint(user!.user_id, user!.name || "");
          if (e.ok) r = await verifyFingerprint(user!.user_id, `Verify fingerprint to punch ${kind.toUpperCase()}`);
        }
        if (!r.ok) {
          if (required) {
            setStep("biometric", "failed", r.message || "Verification failed");
            setError(r.message || "Fingerprint verification failed");
            return false;
          }
          setStep("biometric", "skipped", "Optional — skipped");
          return true;
        }
        methodRef.current = "fingerprint";
        setStep("biometric", "done", "Fingerprint verified");
        return true;
      }
      // Native — expo-local-authentication (optional if not enrolled).
      const hasHw = await LocalAuthentication.hasHardwareAsync();
      const enrolled = await LocalAuthentication.isEnrolledAsync();
      if (!hasHw || !enrolled) {
        setStep("biometric", "skipped", "Optional — no device biometric set up");
        return true;
      }
      const res = await LocalAuthentication.authenticateAsync({
        promptMessage: `Authenticate to punch ${kind.toUpperCase()}`,
        cancelLabel: "Cancel",
        disableDeviceFallback: false,
      });
      if (!res.success) {
        setStep("biometric", "failed", "Authentication failed");
        setError("Device biometric failed — try again.");
        return false;
      }
      methodRef.current = "fingerprint";
      setStep("biometric", "done", "Verified");
      return true;
    } catch {
      setStep("biometric", "skipped", "Optional — skipped");
      return true;
    }
  }, [user, kind]);

  // ---- Step 5: save punch (offline-aware when postPunch prop is given) ----
  const runSave = useCallback(async (pos: { latitude: number; longitude: number } | null, site: Worksite | null) => {
    setStep("save", "active", "Saving attendance…");
    try {
      const body = {
        kind,
        latitude: pos?.latitude ?? null,
        longitude: pos?.longitude ?? null,
        biometric_method: methodRef.current,
        selfie_base64: selfieRef.current,
        device_info: Platform.OS,
        ...(site && site.worksite_id !== "main"
          ? { worksite_id: site.worksite_id, worksite_name: site.name }
          : site ? { worksite_name: site.name } : {}),
      };
      const res = postPunch
        ? await postPunch(body)
        : await api<{ ok: boolean; distance_m: number; status?: string; approval_required?: boolean }>(
            "/attendance/punch", { method: "POST", body },
          );
      if (res?.offline) {
        setStep("save", "done", "Saved on device — pending synchronization");
        setResult({ pending: false, distance_m: 0, offline: true });
        onDone();
        return;
      }
      setStep("save", "done", "Attendance saved");
      setResult({
        pending: res?.status === "pending" || res?.approval_required === true,
        distance_m: Math.round(res?.distance_m || 0),
      });
      onDone();
    } catch (e: any) {
      setStep("save", "failed", e?.message || "Save failed");
      setError(e?.message || "Punch failed");
    }
  }, [kind, onDone, postPunch]);

  // ---- Orchestrator ----
  const start = useCallback(async () => {
    if (runningRef.current) return;
    runningRef.current = true;
    setError(null);
    const gps = await runGps();
    if (!gps.ok) { runningRef.current = false; return; }
    const proceed = await runWorksite(gps.sites);
    if (!proceed) { runningRef.current = false; return; } // waits for site pick
    runFace(); // resumes in onCapture
    runningRef.current = false;
  }, [runGps, runWorksite, runFace]);

  useEffect(() => {
    if (visible) { reset(); setTimeout(() => start(), 250); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const pickSite = (s: Worksite) => {
    setChosenSite(s);
    setAwaitingSitePick(false);
    setStep("worksite", "done", s.name);
    runFace();
  };

  const onFaceCaptured = async (b64: string) => {
    setFaceOpen(false);
    selfieRef.current = b64;
    methodRef.current = "face";
    setStep("face", "done", "Selfie captured — identity will be verified");
    const ok = await runBiometric();
    if (!ok) return;
    await runSave(coords, chosenSite);
  };

  const retry = () => { reset(); setTimeout(() => start(), 150); };

  const ICONS: Record<StepState, { name: any; color: string }> = {
    pending: { name: "ellipse-outline", color: colors.onSurfaceTertiary },
    active: { name: "time-outline", color: "#B45309" },
    done: { name: "checkmark-circle", color: "#16A34A" },
    skipped: { name: "remove-circle-outline", color: colors.onSurfaceTertiary },
    failed: { name: "close-circle", color: "#B91C1C" },
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={st.overlay}>
        <View style={st.card}>
          <View style={st.head}>
            <Ionicons name={kind === "in" ? "log-in-outline" : "log-out-outline"} size={18} color={colors.brandPrimary} />
            <Text style={st.title}>Punch {kind.toUpperCase()} — Verification</Text>
            <Pressable onPress={onClose} hitSlop={10} testID="pf-close">
              <Ionicons name="close" size={20} color={colors.onSurfaceSecondary} />
            </Pressable>
          </View>

          {result ? (
            <View style={st.doneBox} testID="pf-success">
              <Ionicons
                name={result.offline ? "cloud-offline-outline" : "checkmark-circle"}
                size={46}
                color={result.offline ? "#B45309" : "#16A34A"}
              />
              <Text style={st.doneTitle}>
                {result.offline ? "Saved — Pending Sync" : "Attendance Saved"}
              </Text>
              <Text style={st.doneTxt}>
                {result.offline
                  ? "📸 Photo · 📍 Location · 🕘 Time stored on this device.\nAttendance saved successfully. Status: Pending Synchronization — it will upload automatically when internet returns."
                  : `📸 Photo · 📍 Location · 🕘 Time stored\n${result.distance_m ? `${result.distance_m}m from worksite · ` : ""}${result.pending ? "Awaiting admin approval — payroll updates after approval." : "Payroll will update automatically."}`}
              </Text>
              <Pressable onPress={onClose} style={st.primaryBtn} testID="pf-done">
                <Text style={st.primaryBtnTxt}>Done</Text>
              </Pressable>
            </View>
          ) : (
            <ScrollView style={{ maxHeight: 460 }}>
              {(Object.keys(STEP_META) as StepKey[]).map((k, i) => {
                const stt = steps[k];
                const ic = ICONS[stt];
                return (
                  <View key={k} style={st.stepRow} testID={`pf-step-${k}`}>
                    <View style={{ alignItems: "center" }}>
                      {stt === "active" ? (
                        <ActivityIndicator size="small" color="#B45309" />
                      ) : (
                        <Ionicons name={ic.name} size={20} color={ic.color} />
                      )}
                      {i < 4 ? <View style={[st.rail, (stt === "done" || stt === "skipped") && { backgroundColor: "#16A34A" }]} /> : null}
                    </View>
                    <View style={{ flex: 1, paddingBottom: 14 }}>
                      <Text style={[st.stepLbl, stt === "failed" && { color: "#B91C1C" }]}>
                        {STEP_META[k].label}
                        {k === "worksite" ? " (if applicable)" : k === "biometric" ? " (optional)" : ""}
                      </Text>
                      {stepNote[k] ? <Text style={st.stepNote}>{stepNote[k]}</Text> : null}
                      {k === "worksite" && awaitingSitePick ? (
                        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                          {worksites.map((s) => {
                            const d = coords ? haversineM(coords.latitude, coords.longitude, s.office_lat, s.office_lng) : null;
                            const near = d !== null && d <= (s.geofence_radius_m || 200);
                            return (
                              <Pressable key={s.worksite_id} onPress={() => pickSite(s)}
                                style={[st.siteChip, near && st.siteChipNear]} testID={`pf-site-${s.worksite_id}`}>
                                <Ionicons name="business-outline" size={12} color={near ? "#16A34A" : colors.brandPrimary} />
                                <Text style={[st.siteChipTxt, near && { color: "#16A34A" }]}>
                                  {s.name}{d !== null ? ` · ${formatDistance(d)}` : ""}{near ? " ✓" : ""}
                                </Text>
                              </Pressable>
                            );
                          })}
                        </View>
                      ) : null}
                    </View>
                  </View>
                );
              })}
              {error ? (
                <View style={st.errBox}>
                  <Text style={st.errTxt}>{error}</Text>
                  <Pressable onPress={retry} style={[st.primaryBtn, { marginTop: 8 }]} testID="pf-retry">
                    <Text style={st.primaryBtnTxt}>Retry</Text>
                  </Pressable>
                </View>
              ) : null}
            </ScrollView>
          )}
        </View>
      </View>

      <FaceCaptureModal
        visible={faceOpen}
        title="Face Verification"
        subtitle="Your photo is stored with the punch and matched to your profile"
        onCancel={() => { setFaceOpen(false); setStep("face", "failed", "Cancelled"); setError("Face verification is required to punch."); }}
        onCapture={onFaceCaptured}
      />
    </Modal>
  );
}

const st = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(15,23,42,0.6)", alignItems: "center", justifyContent: "center", padding: 16 },
  card: { width: "100%", maxWidth: 440, backgroundColor: colors.surface, borderRadius: radius.lg, padding: 16 },
  head: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 14 },
  title: { ...type.h3, flex: 1, color: colors.onSurface, fontSize: 16 },
  stepRow: { flexDirection: "row", gap: 12 },
  rail: { width: 2, flex: 1, minHeight: 14, backgroundColor: colors.divider, marginTop: 2 },
  stepLbl: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  stepNote: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 2 },
  siteChip: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 11, paddingVertical: 7,
  },
  siteChipNear: { borderColor: "#16A34A", backgroundColor: "#F0FDF4" },
  siteChipTxt: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },
  errBox: { backgroundColor: "#FEF2F2", borderRadius: radius.md, padding: 10, marginTop: 4 },
  errTxt: { fontSize: 12, color: "#B91C1C" },
  primaryBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 18, paddingVertical: 10, alignItems: "center", alignSelf: "center",
  },
  primaryBtnTxt: { color: "#fff", fontSize: 13, fontWeight: "800" },
  doneBox: { alignItems: "center", paddingVertical: 18, gap: 8 },
  doneTitle: { ...type.h3, color: colors.onSurface },
  doneTxt: { fontSize: 12.5, color: colors.onSurfaceSecondary, textAlign: "center", lineHeight: 19, marginBottom: 6 },
});
