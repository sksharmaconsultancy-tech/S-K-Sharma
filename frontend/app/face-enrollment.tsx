/**
 * Iter 601 — ADMIN: Face Enrollment (HR/Admin ONLY, live camera only).
 *
 * Opened with ?user_id=&name= from the Employee Master. Captures 3 LIVE
 * camera samples (no gallery upload anywhere), each validated server-side
 * (one face, quality), then the backend builds an encrypted ArcFace
 * template. Employees can NEVER register/replace their own face.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useLocalSearchParams } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing } from "@/src/theme";

type FaceStatus = {
  status: string; registered_at?: string; registered_by_name?: string;
  samples?: number; last_verified_at?: string | null; model?: string;
};

const SAMPLES_NEEDED = 3;

export default function FaceEnrollmentScreen() {
  const { user } = useAuth();
  const { user_id, name } = useLocalSearchParams<{ user_id?: string; name?: string }>();
  const camRef = useRef<any>(null);
  const [perm, requestPerm] = useCameraPermissions();
  const [face, setFace] = useState<FaceStatus | null>(null);
  const [engineReady, setEngineReady] = useState<boolean | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [samples, setSamples] = useState<string[]>([]);
  const [stepMsg, setStepMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  const loadStatus = useCallback(async () => {
    if (!user_id) return;
    try {
      const r = await api<{ face: FaceStatus }>(
        `/admin/face-verification/status?user_id=${encodeURIComponent(user_id)}`);
      setFace(r.face);
    } catch (e: any) { setErr(e?.message || "Status load failed"); }
  }, [user_id]);

  useEffect(() => {
    loadStatus();
    api<{ ready: boolean }>("/admin/face-verification/engine-status")
      .then((r) => setEngineReady(r.ready))
      .catch(() => setEngineReady(false));
  }, [loadStatus]);

  if (user && !["super_admin", "sub_admin", "company_admin"].includes(user.role)) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={34} color={colors.onSurfaceSecondary} />
          <Text style={styles.cardTitle}>HR / Admin only</Text>
          <Text style={styles.mutedTxt}>Face enrollment is restricted.</Text>
        </View>
      </SafeAreaView>
    );
  }

  const captureSample = async () => {
    if (!camRef.current || capturing) return;
    setCapturing(true); setErr("");
    try {
      const photo = await camRef.current.takePictureAsync({
        base64: true, quality: 0.75, skipProcessing: true,
      });
      const b64 = `data:image/jpeg;base64,${photo.base64}`;
      setStepMsg("Checking frame…");
      const chk = await api<{ ok: boolean; reason?: string }>(
        "/admin/face-verification/check-frame",
        { method: "POST", body: { frame: b64 } });
      if (!chk.ok) {
        setErr(chk.reason || "Frame rejected — retake");
        setStepMsg("");
        return;
      }
      const next = [...samples, b64];
      setSamples(next);
      setStepMsg(next.length < SAMPLES_NEEDED
        ? `✓ Sample ${next.length} accepted — slightly change your head angle and capture the next one`
        : "All samples captured — press Register Face");
    } catch (e: any) {
      setErr(e?.message || "Capture failed");
    } finally { setCapturing(false); }
  };

  const enroll = async () => {
    if (samples.length < 2 || !user_id) return;
    setBusy("enroll"); setErr("");
    try {
      const r = await api<{ message: string; face: FaceStatus }>(
        "/admin/face-verification/enroll",
        { method: "POST", body: { user_id, frames: samples } });
      setFace(r.face);
      setSamples([]);
      setStepMsg(r.message);
    } catch (e: any) {
      setErr(e?.message || "Enrollment failed");
    } finally { setBusy(""); }
  };

  const toggleEnabled = async () => {
    if (!user_id || !face) return;
    const action = face.status === "active" ? "disable" : "enable";
    setBusy(action); setErr("");
    try {
      await api(`/admin/face-verification/${action}`, { method: "POST", body: { user_id } });
      await loadStatus();
    } catch (e: any) { setErr(e?.message || "Action failed"); }
    finally { setBusy(""); }
  };

  const registered = face && face.status !== "not_registered";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.headerRow}>
          <View style={styles.headerIcon}>
            <Ionicons name="scan-outline" size={20} color={colors.onBrandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Face Enrollment</Text>
            <Text style={styles.subtitle}>{name || user_id || "Select an employee"}</Text>
          </View>
        </View>

        {/* Status card (Employee Master spec format) */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Face Verification</Text>
          {face === null ? <ActivityIndicator /> : (
            <>
              <Text style={[styles.statusTxt, {
                color: face.status === "active" ? "#047857"
                  : face.status === "disabled" ? "#B45309" : colors.onSurfaceSecondary,
              }]}>
                Status: {face.status === "active" ? "Registered ✓"
                  : face.status === "disabled" ? "Disabled ⏸" : "Not Registered"}
              </Text>
              {registered ? (
                <Text style={styles.mutedTxt}>
                  Registered On: {face.registered_at
                    ? new Date(face.registered_at).toLocaleDateString("en-IN")
                    : "—"} by {face.registered_by_name || "—"}{"\n"}
                  Samples: {face.samples || "—"} · Model: {face.model || "—"}{"\n"}
                  Last Verified: {face.last_verified_at
                    ? new Date(face.last_verified_at).toLocaleString("en-IN") : "—"}
                </Text>
              ) : null}
              {registered ? (
                <Pressable style={styles.linkBtn} onPress={toggleEnabled} disabled={!!busy} testID="face-toggle">
                  <Text style={styles.linkTxt}>
                    {face.status === "active" ? "Disable face verification" : "Enable face verification"}
                  </Text>
                </Pressable>
              ) : null}
            </>
          )}
          {engineReady === false ? (
            <Text style={styles.warnTxt}>
              ⚠ Face AI engine is not ready on the server yet (models loading).
              Try again in a minute.
            </Text>
          ) : null}
        </View>

        {/* Live camera enrollment — NO gallery upload, camera stream only */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>
            {registered ? "Re-register Face (replaces current template)" : "Register Face"}
          </Text>
          <Text style={styles.mutedTxt}>
            Live camera only — gallery upload is not permitted for biometric
            enrollment. Capture {SAMPLES_NEEDED} samples with slightly
            different head angles.
          </Text>
          {!perm?.granted ? (
            <Pressable style={styles.btn} onPress={requestPerm} testID="face-cam-perm">
              <Ionicons name="camera-outline" size={16} color="#fff" />
              <Text style={styles.btnTxt}>Allow Camera</Text>
            </Pressable>
          ) : (
            <>
              <View style={styles.camBox}>
                <CameraView ref={camRef} style={{ flex: 1 }} facing="front" />
              </View>
              <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
                {Array.from({ length: SAMPLES_NEEDED }).map((_, i) => (
                  <Ionicons key={i}
                    name={i < samples.length ? "checkmark-circle" : "ellipse-outline"}
                    size={18} color={i < samples.length ? "#047857" : colors.onSurfaceTertiary} />
                ))}
                <Text style={styles.mutedTxt}> {samples.length}/{SAMPLES_NEEDED} samples</Text>
              </View>
              {samples.length < SAMPLES_NEEDED ? (
                <Pressable style={[styles.btn, capturing && { opacity: 0.6 }]}
                  onPress={captureSample} disabled={capturing} testID="face-capture">
                  {capturing ? <ActivityIndicator color="#fff" size="small" />
                    : <Ionicons name="camera" size={16} color="#fff" />}
                  <Text style={styles.btnTxt}>Capture Sample {samples.length + 1}</Text>
                </Pressable>
              ) : (
                <Pressable style={[styles.btn, { backgroundColor: "#047857" }]}
                  onPress={enroll} disabled={busy === "enroll"} testID="face-enroll">
                  {busy === "enroll" ? <ActivityIndicator color="#fff" size="small" />
                    : <Ionicons name="shield-checkmark" size={16} color="#fff" />}
                  <Text style={styles.btnTxt}>Register Face</Text>
                </Pressable>
              )}
              {samples.length > 0 ? (
                <Pressable style={styles.linkBtn} onPress={() => { setSamples([]); setStepMsg(""); }}>
                  <Text style={styles.linkTxt}>Retake all samples</Text>
                </Pressable>
              ) : null}
            </>
          )}
          {!!stepMsg && <Text style={styles.okTxt}>{stepMsg}</Text>}
          {!!err && <Text style={styles.errTxt}>{err}</Text>}
        </View>

        <View style={[styles.card, { backgroundColor: "#F0FDF4", borderColor: "#BBF7D0" }]}>
          <Text style={styles.cardTitle}>🔒 Biometric privacy</Text>
          <Text style={styles.mutedTxt}>
            Only an encrypted mathematical face template is stored — no photos
            are kept. Access to biometric records is restricted and every
            admin action is audit-logged. Employees cannot view or replace
            templates themselves.
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.lg, gap: spacing.md, maxWidth: 560, width: "100%", alignSelf: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  headerIcon: {
    width: 38, height: 38, borderRadius: 10, backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  title: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceSecondary },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.borderLight, padding: spacing.md, gap: 8, ...shadow.sm,
  },
  cardTitle: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  statusTxt: { fontSize: 13, fontWeight: "700" },
  mutedTxt: { fontSize: 12, color: colors.onSurfaceSecondary, lineHeight: 18 },
  warnTxt: { fontSize: 12, color: "#B45309", lineHeight: 18 },
  okTxt: { fontSize: 12.5, color: "#047857", fontWeight: "600" },
  errTxt: { fontSize: 12.5, color: "#DC2626", fontWeight: "600" },
  camBox: {
    height: 320, borderRadius: 12, overflow: "hidden",
    backgroundColor: "#111", borderWidth: 1, borderColor: colors.borderLight,
  },
  btn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brandPrimary, borderRadius: 10, paddingVertical: 12,
    minHeight: 44,
  },
  btnTxt: { color: "#fff", fontSize: 13.5, fontWeight: "700" },
  linkBtn: { paddingVertical: 6 },
  linkTxt: { color: colors.brandPrimary, fontSize: 12.5, fontWeight: "600" },
});
