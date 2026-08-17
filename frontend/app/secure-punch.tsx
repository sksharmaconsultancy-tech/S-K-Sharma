/**
 * Iter 602 — EMPLOYEE PWA: SECURE PUNCH (Phase 2 user spec).
 *
 * Device auth (WebAuthn, if registered) → live camera → random liveness
 * challenges → server-side anti-spoof + 1:1 face match → punch. No gallery
 * upload anywhere — frames come only from the live camera stream. The
 * BACKEND is the final authority for every step.
 */
import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { authenticateDevice } from "@/src/utils/webauthnClient";
import { colors, radius, shadow, spacing } from "@/src/theme";

type Step = { step: string; instruction: string };
type Phase = "policy" | "device" | "camera" | "verifying" | "punching" | "success" | "error";

export default function SecurePunchScreen() {
  const router = useRouter();
  const { kind } = useLocalSearchParams<{ kind?: string }>();
  const punchKind = kind === "out" ? "out" : "in";
  const camRef = useRef<any>(null);
  const [perm, requestPerm] = useCameraPermissions();
  const [phase, setPhase] = useState<Phase>("policy");
  const [policy, setPolicy] = useState<any>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [stepIdx, setStepIdx] = useState(0);
  const [vsId, setVsId] = useState("");
  const framesRef = useRef<{ step: string; frame: string }[]>([]);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<any>("/attendance/face-verify/policy")
      .then((p) => { setPolicy(p); setPhase(p.device_registered ? "device" : "camera"); })
      .catch((e) => { setErr(e?.message || "Policy load failed"); setPhase("error"); });
  }, []);

  const startChallenges = async (sessionId?: string) => {
    setBusy(true); setErr("");
    try {
      const r = await api<{ verification_session_id: string; steps: Step[] }>(
        "/attendance/face-verify/start",
        { method: "POST", body: sessionId ? { verification_session_id: sessionId } : {} });
      setVsId(r.verification_session_id);
      setSteps(r.steps);
      setStepIdx(0);
      framesRef.current = [];
      setPhase("camera");
    } catch (e: any) {
      setErr(e?.message || "Could not start verification"); setPhase("error");
    } finally { setBusy(false); }
  };

  const doDeviceAuth = async () => {
    setBusy(true); setErr("");
    try {
      const sessionId = await authenticateDevice();
      await startChallenges(sessionId);
    } catch (e: any) {
      setErr(e?.message || "Device verification failed"); setPhase("error");
    } finally { setBusy(false); }
  };

  const captureStep = async () => {
    if (!camRef.current || busy) return;
    setBusy(true); setErr("");
    try {
      if (!vsId) { await startChallenges(); setBusy(false); return; }
      const photo = await camRef.current.takePictureAsync({
        base64: true, quality: 0.7, skipProcessing: true });
      framesRef.current.push({
        step: steps[stepIdx].step,
        frame: `data:image/jpeg;base64,${photo.base64}`,
      });
      if (stepIdx + 1 < steps.length) {
        setStepIdx(stepIdx + 1);
      } else {
        await completeVerification();
      }
    } catch (e: any) {
      setErr(e?.message || "Capture failed");
    } finally { setBusy(false); }
  };

  const completeVerification = async () => {
    setPhase("verifying");
    try {
      const r = await api<any>("/attendance/face-verify/complete", {
        method: "POST",
        body: { verification_session_id: vsId, frames: framesRef.current },
      });
      await doPunch(r);
    } catch (e: any) {
      setErr(e?.message || "Verification failed"); setPhase("error");
    }
  };

  const doPunch = async (verify: any) => {
    setPhase("punching");
    try {
      let lat: number | null = null, lng: number | null = null;
      if (Platform.OS === "web" && (navigator as any)?.geolocation) {
        try {
          const pos: any = await new Promise((res, rej) =>
            (navigator as any).geolocation.getCurrentPosition(res, rej,
              { enableHighAccuracy: true, timeout: 12000 }));
          lat = pos.coords.latitude; lng = pos.coords.longitude;
        } catch { /* geofence policy will decide */ }
      }
      const center = framesRef.current.find((f) => f.step === "CENTER");
      const r = await api<any>("/attendance/punch", {
        method: "POST",
        body: {
          kind: punchKind,
          biometric_method: "face",
          latitude: lat, longitude: lng,
          selfie_base64: center?.frame || null,
          verification_session_id: verify.verification_session_id,
          device_info: Platform.OS === "web" ? (navigator as any)?.userAgent?.slice(0, 90) : "app",
          source: "manual",
        },
      });
      setResult({ ...r, verify });
      setPhase("success");
    } catch (e: any) {
      setErr(e?.message || "Punch failed"); setPhase("error");
    }
  };

  const instruction = steps[stepIdx]?.instruction || "Look straight at the camera";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.title}>
          Secure {punchKind === "in" ? "IN" : "OUT"} Punch
        </Text>

        {phase === "policy" ? <ActivityIndicator style={{ marginTop: 40 }} /> : null}

        {phase === "device" ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Step 1 — Verify your registered device</Text>
            <Text style={styles.mutedTxt}>
              Use Face ID / Face Unlock / Fingerprint. Your biometric stays on
              your phone — only a cryptographic result is sent.
            </Text>
            <Pressable style={styles.btn} onPress={doDeviceAuth} disabled={busy} testID="sp-device">
              {busy ? <ActivityIndicator color="#fff" size="small" />
                : <Ionicons name="finger-print-outline" size={16} color="#fff" />}
              <Text style={styles.btnTxt}>Continue</Text>
            </Pressable>
          </View>
        ) : null}

        {phase === "camera" ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>
              {vsId ? `Liveness Check — Step ${stepIdx + 1} of ${steps.length}` : "Live Face Verification"}
            </Text>
            {!perm?.granted ? (
              <Pressable style={styles.btn} onPress={requestPerm} testID="sp-cam-perm">
                <Ionicons name="camera-outline" size={16} color="#fff" />
                <Text style={styles.btnTxt}>Allow Camera</Text>
              </Pressable>
            ) : (
              <>
                <View style={styles.camBox}>
                  <CameraView ref={camRef} style={{ flex: 1 }} facing="front" />
                </View>
                <Text style={styles.instruction}>
                  {vsId ? instruction : "Live camera only — no gallery upload. Press Start."}
                </Text>
                <Pressable style={[styles.btn, busy && { opacity: 0.6 }]}
                  onPress={captureStep} disabled={busy} testID="sp-capture">
                  {busy ? <ActivityIndicator color="#fff" size="small" />
                    : <Ionicons name="camera" size={16} color="#fff" />}
                  <Text style={styles.btnTxt}>{vsId ? "Capture" : "Start Verification"}</Text>
                </Pressable>
              </>
            )}
            {!!err && <Text style={styles.errTxt}>{err}</Text>}
          </View>
        ) : null}

        {phase === "verifying" || phase === "punching" ? (
          <View style={[styles.card, { alignItems: "center", gap: 12 }]}>
            <ActivityIndicator size="large" color={colors.brandPrimary} />
            <Text style={styles.cardTitle}>
              {phase === "verifying"
                ? "Verifying live person, anti-spoof & face match…"
                : "Creating your punch…"}
            </Text>
          </View>
        ) : null}

        {phase === "success" && result ? (
          <View style={[styles.card, { borderColor: "#A7F3D0", backgroundColor: "#ECFDF5" }]}>
            <Text style={[styles.cardTitle, { color: "#047857", fontSize: 17 }]}>
              ✓ PUNCH SUCCESSFUL — {punchKind.toUpperCase()} PUNCH
            </Text>
            <Text style={styles.mutedTxt}>
              {new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })} ·{" "}
              {new Date().toLocaleDateString("en-IN")}
            </Text>
            <CheckRow label="Device Authentication" ok />
            <CheckRow label="Live Person" ok />
            <CheckRow label="Anti-Spoof" ok />
            <CheckRow label={`Face Match (${result.verify?.face_match_score}%)`} ok />
            <CheckRow label={result.approval_required ? "Pending approval" : "Location / Policy"} ok />
            <Pressable style={[styles.btn, { backgroundColor: "#047857" }]}
              onPress={() => router.back()} testID="sp-done">
              <Text style={styles.btnTxt}>Done</Text>
            </Pressable>
          </View>
        ) : null}

        {phase === "error" ? (
          <View style={[styles.card, { borderColor: "#FECACA", backgroundColor: "#FEF2F2" }]}>
            <Text style={[styles.cardTitle, { color: "#B91C1C" }]}>⚠ Punch Rejected</Text>
            <Text style={styles.mutedTxt}>{err}</Text>
            <Pressable style={styles.btn} onPress={() => {
              setErr(""); setVsId(""); framesRef.current = [];
              setPhase(policy?.device_registered ? "device" : "camera");
            }} testID="sp-retry">
              <Text style={styles.btnTxt}>Try Again</Text>
            </Pressable>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function CheckRow({ label, ok }: { label: string; ok: boolean }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
      <Ionicons name={ok ? "checkmark-circle" : "close-circle"} size={15}
        color={ok ? "#047857" : "#DC2626"} />
      <Text style={{ fontSize: 12.5, color: colors.onSurface }}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.lg, gap: spacing.md, maxWidth: 520, width: "100%", alignSelf: "center" },
  title: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.borderLight, padding: spacing.md, gap: 10, ...shadow.sm,
  },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  mutedTxt: { fontSize: 12, color: colors.onSurfaceSecondary, lineHeight: 18 },
  instruction: {
    fontSize: 15, fontWeight: "800", color: colors.brandPrimary,
    textAlign: "center", paddingVertical: 4,
  },
  errTxt: { fontSize: 12.5, color: "#DC2626", fontWeight: "600" },
  camBox: {
    height: 340, borderRadius: 12, overflow: "hidden", backgroundColor: "#111",
    borderWidth: 1, borderColor: colors.borderLight,
  },
  btn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brandPrimary, borderRadius: 10, paddingVertical: 12,
    minHeight: 44,
  },
  btnTxt: { color: "#fff", fontSize: 13.5, fontWeight: "700" },
});
