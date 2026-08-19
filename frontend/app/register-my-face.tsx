/**
 * Iter 611 — ESS: Register My Face (employee self-enrollment).
 * Consent → live camera (3 samples, per-frame server quality gate) →
 * same-person verification → submit as PENDING → HR approves/rejects.
 * NEVER activates face verification by itself.
 */
import React, { useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { CameraView, useCameraPermissions } from "expo-camera";
import { api } from "@/src/api/client";
import { colors } from "@/src/theme";

const NEED = 3;
const POSES = ["Look straight at the camera", "Turn your head slightly LEFT", "Turn your head slightly RIGHT"];
const ST_META: Record<string, { t: string; c: string; icon: string }> = {
  pending: { t: "🟡 Pending HR Approval (auto-approves in 2 days)", c: "#D97706", icon: "hourglass-outline" },
  approved: { t: "🟢 Enrolled & Active", c: "#059669", icon: "shield-checkmark" },
  rejected: { t: "🔴 Rejected", c: "#DC2626", icon: "close-circle" },
  recapture_required: { t: "🟠 Recapture Required", c: "#EA580C", icon: "refresh-circle" },
  not_registered: { t: "Not Registered", c: "#64748B", icon: "person-circle-outline" },
};

export default function RegisterMyFace() {
  const router = useRouter();
  const camRef = useRef<any>(null);
  const [perm, requestPerm] = useCameraPermissions();
  const [status, setStatus] = useState<any>(null);
  const [step, setStep] = useState<"status" | "consent" | "camera" | "done">("status");
  const [consent, setConsent] = useState(false);
  const [samples, setSamples] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");

  const load = () => api("/face-verification/self-status").then(setStatus).catch(() => setStatus({ status: "not_registered" }));
  useEffect(() => { load(); }, []);

  const startCamera = async () => {
    setErr("");
    if (!perm?.granted) {
      const r = await requestPerm();
      if (!r.granted) {
        setErr(r.canAskAgain === false
          ? "Camera blocked — enable it in your phone Settings for this app."
          : "Camera permission is needed to capture your face samples.");
        return;
      }
    }
    setSamples([]); setStep("camera");
    setNote(POSES[0]);
  };

  const capture = async () => {
    if (!camRef.current || busy) return;
    setBusy(true); setErr("");
    try {
      const photo = await camRef.current.takePictureAsync({ base64: true, quality: 0.75, skipProcessing: true });
      // Iter 614 fix — on web, expo-camera may return base64 already as a
      // full data-URL; double-prefixing made the frame unreadable.
      const raw = photo.base64 || photo.uri || "";
      const b64 = String(raw).startsWith("data:") ? String(raw) : `data:image/jpeg;base64,${raw}`;
      setNote("Checking frame…");
      const chk = await api<{ ok: boolean; reason?: string }>(
        "/face-verification/self-check-frame", { method: "POST", body: { frame: b64 } });
      if (!chk.ok) { setErr(chk.reason || "Sample rejected — please try again"); setNote(POSES[samples.length] || ""); return; }
      const next = [...samples, b64];
      setSamples(next);
      if (next.length < NEED) setNote(`✓ Sample ${next.length} accepted — ${POSES[next.length]}`);
      else setNote("All samples captured — submit for HR approval");
    } catch (e: any) { setErr(String(e?.message || "Capture failed")); }
    finally { setBusy(false); }
  };

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      await api("/face-verification/self-enroll", {
        method: "POST", body: { consent: true, frames: samples },
      });
      setStep("done"); load();
    } catch (e: any) { setErr(String(e?.message || e)); setNote(""); }
    finally { setBusy(false); }
  };

  const meta = ST_META[status?.status] || ST_META.not_registered;
  const canRegister = ["not_registered", "rejected", "recapture_required", "approved"].includes(status?.status);

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="arrow-back" size={22} color={colors.onSurface} /></Pressable>
        <Text style={s.title}>Face Registration</Text>
      </View>
      <ScrollView contentContainerStyle={s.body}>
        {step === "status" ? (
          !status ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 40 }} /> : (
            <>
              <View style={[s.stCard, { borderColor: meta.c }]}>
                <Ionicons name={meta.icon as any} size={34} color={meta.c} />
                <Text style={[s.stTxt, { color: meta.c }]}>{meta.t}</Text>
                {status.status === "pending" && status.request ? (
                  <Text style={s.sub}>Submitted {String(status.request.submitted_at || "").slice(0, 16).replace("T", " ")} · {status.request.samples} samples</Text>
                ) : null}
                {status.status === "approved" && status.registered_at ? (
                  <Text style={s.sub}>Registered {String(status.registered_at).slice(0, 10)}</Text>
                ) : null}
                {["rejected", "recapture_required"].includes(status.status) && status.request?.reason ? (
                  <Text style={[s.sub, { color: meta.c }]}>HR: {status.request.reason}</Text>
                ) : null}
              </View>
              {canRegister ? (
                <Pressable style={s.primary} onPress={() => { setConsent(false); setStep("consent"); }} testID="face-register-start">
                  <Ionicons name="scan-outline" size={18} color="#fff" />
                  <Text style={s.primaryTxt}>{status.status === "approved" ? "Request Re-enrollment" : "Register My Face"}</Text>
                </Pressable>
              ) : (
                <Text style={s.hint}>Your submission is with HR — you&apos;ll get a notification once reviewed.</Text>
              )}
              {status.status === "approved" ? (
                <Text style={s.hint}>Your current face stays active until HR approves the new one.</Text>
              ) : null}
            </>
          )
        ) : null}

        {step === "consent" ? (
          <View style={s.card}>
            <Text style={s.cardTitle}>Before you start</Text>
            <Text style={s.para}>Your face will be securely registered for attendance verification. Make sure you are ALONE in front of the camera, in good lighting.</Text>
            <Text style={s.para}>🔒 Privacy: your samples are checked and stored encrypted on your company&apos;s own server — never shared with third parties. HR must approve before your face is used for punching.</Text>
            <Pressable style={s.consentRow} onPress={() => setConsent(!consent)} testID="face-consent">
              <Ionicons name={consent ? "checkbox" : "square-outline"} size={22} color={colors.brandPrimary} />
              <Text style={s.consentTxt}>I understand and consent to face registration for attendance verification.</Text>
            </Pressable>
            <Pressable style={[s.primary, !consent && { opacity: 0.5 }]} disabled={!consent} onPress={startCamera} testID="face-consent-continue">
              <Text style={s.primaryTxt}>Continue</Text>
            </Pressable>
          </View>
        ) : null}

        {step === "camera" ? (
          <>
            <View style={s.camBox}><CameraView ref={camRef} style={{ flex: 1 }} facing="front" /></View>
            <View style={s.dots}>{[...Array(NEED)].map((_, i) => (
              <View key={i} style={[s.dot, i < samples.length && { backgroundColor: "#059669" }]} />))}</View>
            {note ? <Text style={s.note}>{note}</Text> : null}
            {err ? <Text style={s.err}>{err}</Text> : null}
            {samples.length < NEED ? (
              <Pressable style={s.primary} disabled={busy} onPress={capture} testID="face-capture">
                {busy ? <ActivityIndicator size="small" color="#fff" /> : (<>
                  <Ionicons name="camera" size={18} color="#fff" />
                  <Text style={s.primaryTxt}>Capture Sample {samples.length + 1} of {NEED}</Text></>)}
              </Pressable>
            ) : (
              <Pressable style={[s.primary, { backgroundColor: "#059669" }]} disabled={busy} onPress={submit} testID="face-submit">
                {busy ? <ActivityIndicator size="small" color="#fff" /> : <Text style={s.primaryTxt}>Submit for HR Approval</Text>}
              </Pressable>
            )}
          </>
        ) : null}

        {step === "done" ? (
          <View style={[s.stCard, { borderColor: "#D97706" }]}>
            <Ionicons name="hourglass-outline" size={40} color="#D97706" />
            <Text style={[s.stTxt, { color: "#D97706" }]}>Submitted — Pending HR Approval</Text>
            <Text style={s.sub}>You&apos;ll get a notification when HR reviews it. Your face will only be used for punching AFTER approval.</Text>
            <Pressable style={[s.primary, { marginTop: 14 }]} onPress={() => setStep("status")}>
              <Text style={s.primaryTxt}>OK</Text>
            </Pressable>
          </View>
        ) : null}
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { flex: 1, fontSize: 17, fontWeight: "800", color: colors.onSurface },
  body: { padding: 16 },
  stCard: { alignItems: "center", backgroundColor: colors.surface, borderRadius: 16, padding: 24, borderWidth: 1.5, borderColor: colors.border, gap: 8 },
  stTxt: { fontSize: 16, fontWeight: "800" },
  sub: { fontSize: 12.5, color: colors.onSurfaceTertiary, textAlign: "center", lineHeight: 18 },
  primary: { flexDirection: "row", gap: 8, backgroundColor: colors.brandPrimary, borderRadius: 12, minHeight: 48, alignItems: "center", justifyContent: "center", marginTop: 16, paddingHorizontal: 16 },
  primaryTxt: { color: "#fff", fontWeight: "800", fontSize: 14 },
  hint: { fontSize: 12, color: colors.onSurfaceTertiary, textAlign: "center", marginTop: 12, lineHeight: 17 },
  card: { backgroundColor: colors.surface, borderRadius: 16, padding: 18, borderWidth: 1, borderColor: colors.border },
  cardTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  para: { fontSize: 13, color: colors.onSurfaceSecondary, lineHeight: 19, marginBottom: 10 },
  consentRow: { flexDirection: "row", gap: 10, alignItems: "center", marginTop: 4, minHeight: 44 },
  consentTxt: { flex: 1, fontSize: 12.5, color: colors.onSurface, fontWeight: "600", lineHeight: 18 },
  camBox: { height: 380, borderRadius: 16, overflow: "hidden", backgroundColor: "#000" },
  dots: { flexDirection: "row", gap: 8, justifyContent: "center", marginTop: 12 },
  dot: { width: 12, height: 12, borderRadius: 6, backgroundColor: colors.border },
  note: { fontSize: 13, color: colors.brandPrimary, fontWeight: "700", textAlign: "center", marginTop: 10 },
  err: { fontSize: 12.5, color: "#DC2626", fontWeight: "700", textAlign: "center", marginTop: 8 },
});
