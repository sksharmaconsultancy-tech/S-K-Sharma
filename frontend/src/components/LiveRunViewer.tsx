/**
 * LiveRunViewer — real-time view of an RPA portal registration.
 *
 * Polls /admin/portal-automation/jobs/{jobId}/live every 2 seconds and
 * renders the actual browser screen (streamed as JPEG frames by the
 * Playwright worker) with a pulsing LIVE badge, the current portal URL and
 * a running step log — so the admin can watch the whole registration
 * happening on the government portal.
 */
import React, { useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Image, ActivityIndicator, TextInput, Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

type LiveFeed = {
  status: string;
  action_type?: string;
  employee_name?: string;
  live_frame_base64?: string | null;
  live_frame_at?: string | null;
  live_url?: string | null;
  steps: { at?: string; note?: string }[];
  manual_reason?: string | null;
  error?: string | null;
  result?: Record<string, string> | null;
};

const TERMINAL = ["completed", "failed", "manual_required"];

export default function LiveRunViewer({ jobId, onDone }: {
  jobId: string;
  onDone?: (status: string) => void;
}) {
  const [feed, setFeed] = useState<LiveFeed | null>(null);
  const [otp, setOtp] = useState("");
  const [otpBusy, setOtpBusy] = useState(false);
  const [otpMsg, setOtpMsg] = useState("");
  const doneRef = useRef(false);

  const sendOtp = async () => {
    if (!otp.trim() || otpBusy) return;
    setOtpBusy(true);
    try {
      const r = await api<{ message?: string }>(
        `/admin/portal-automation/jobs/${jobId}/otp`,
        { method: "POST", body: { code: otp.trim() } });
      setOtpMsg(r.message || "OTP sent — continuing…");
      setOtp("");
    } catch (e: any) { setOtpMsg(e?.message || "Failed to send OTP"); }
    finally { setOtpBusy(false); }
  };

  useEffect(() => {
    doneRef.current = false;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      try {
        const r = await api<LiveFeed & { ok: boolean }>(
          `/admin/portal-automation/jobs/${jobId}/live`);
        if (stop) return;
        setFeed(r);
        if (TERMINAL.includes(r.status)) {
          if (!doneRef.current) { doneRef.current = true; onDone?.(r.status); }
          return; // stop polling — keep final frame on screen
        }
      } catch { /* transient — keep polling */ }
      if (!stop) timer = setTimeout(tick, 2000);
    };
    tick();
    return () => { stop = true; if (timer) clearTimeout(timer); };
  }, [jobId, onDone]);

  const status = feed?.status || "pending";
  const isLive = status === "in_progress";
  const isQueued = status === "pending";
  const isOtp = status === "awaiting_otp";
  const badge = isLive
    ? { txt: "● LIVE ON PORTAL", bg: "#DC2626" }
    : isOtp
      ? { txt: "⏸ ENTER AADHAAR OTP", bg: "#D97706" }
      : isQueued
      ? { txt: "QUEUED — worker starting…", bg: "#2563EB" }
      : status === "completed"
        ? { txt: "COMPLETED", bg: "#059669" }
        : status === "manual_required"
          ? { txt: "ACTION REQUIRED", bg: "#EA580C" }
          : { txt: "FAILED", bg: "#DC2626" };

  const resultVal = feed?.result?.uan_no || feed?.result?.esi_ip_no;

  return (
    <View style={st.wrap} testID="live-run-viewer">
      <View style={st.head}>
        <View style={[st.badge, { backgroundColor: badge.bg }]}>
          <Text style={st.badgeTxt}>{badge.txt}</Text>
        </View>
        {feed?.employee_name ? (
          <Text style={st.who} numberOfLines={1}>
            {feed.action_type === "generate_uan" ? "EPF UAN" : "ESIC IP"} · {feed.employee_name}
          </Text>
        ) : null}
      </View>

      {/* Browser URL bar */}
      <View style={st.urlBar}>
        <Ionicons name="lock-closed" size={11} color="#059669" />
        <Text style={st.urlTxt} numberOfLines={1}>
          {feed?.live_url || "Connecting to the government portal…"}
        </Text>
      </View>

      {/* Live browser screen */}
      {feed?.live_frame_base64 ? (
        <Image
          source={{ uri: `data:image/jpeg;base64,${feed.live_frame_base64}` }}
          style={st.frame}
          resizeMode="contain"
        />
      ) : (
        <View style={[st.frame, st.framePlaceholder]}>
          <ActivityIndicator color={colors.brandPrimary} />
          <Text style={st.placeholderTxt}>
            {isQueued
              ? "Waiting for the automation worker to pick up the job (≈30s)…"
              : "Waiting for the first screen frame from the portal…"}
          </Text>
        </View>
      )}

      {/* Aadhaar OTP handoff — the portal sent an OTP; type it here and
          the automation continues live. */}
      {isOtp && (
        <View style={st.otpBox} testID="live-otp-box">
          <Text style={st.otpTitle}>
            Aadhaar authentication OTP sent to the employee&apos;s Aadhaar-linked
            mobile — enter it to continue:
          </Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <TextInput
              style={st.otpInput}
              placeholder="Enter OTP"
              placeholderTextColor="#64748B"
              keyboardType="number-pad"
              maxLength={8}
              value={otp}
              onChangeText={setOtp}
              testID="live-otp-input"
            />
            <Pressable style={[st.otpBtn, (!otp.trim() || otpBusy) && { opacity: 0.5 }]}
              onPress={sendOtp} disabled={!otp.trim() || otpBusy} testID="live-otp-send">
              {otpBusy ? <ActivityIndicator color="#fff" size="small" /> :
                <Text style={st.otpBtnTxt}>Continue</Text>}
            </Pressable>
          </View>
          {otpMsg ? <Text style={st.otpMsg}>{otpMsg}</Text> : null}
        </View>
      )}

      {/* Result / reason */}
      {resultVal ? (
        <View style={[st.note, { backgroundColor: "#ECFDF5", borderColor: "#A7F3D0" }]}>
          <Text style={[st.noteTxt, { color: "#065F46", fontWeight: "800" }]}>
            ✓ Number generated: {resultVal} — saved to the Employee Master.
          </Text>
        </View>
      ) : feed?.manual_reason || feed?.error ? (
        <View style={[st.note, { backgroundColor: "#FFF7ED", borderColor: "#FED7AA" }]}>
          <Text style={[st.noteTxt, { color: "#9A3412" }]}>
            {feed?.manual_reason || feed?.error}
          </Text>
        </View>
      ) : null}

      {/* Running step log */}
      {(feed?.steps || []).length > 0 && (
        <View style={st.stepsBox}>
          {(feed?.steps || []).slice(-4).map((s, i) => (
            <Text key={i} style={st.stepTxt} numberOfLines={2}>
              ▸ {s.note}
            </Text>
          ))}
        </View>
      )}
    </View>
  );
}

const st = StyleSheet.create({
  wrap: {
    borderRadius: radius.lg, borderWidth: 1, borderColor: "#1E293B",
    backgroundColor: "#0F172A", padding: 10, gap: 8,
  },
  head: { flexDirection: "row", alignItems: "center", gap: 10 },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 6 },
  badgeTxt: { color: "#fff", fontSize: 10.5, fontWeight: "900", letterSpacing: 0.5 },
  who: { color: "#CBD5E1", fontSize: 11.5, fontWeight: "700", flex: 1 },
  urlBar: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#1E293B", borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6,
  },
  urlTxt: { color: "#94A3B8", fontSize: 10.5, flex: 1 },
  frame: {
    width: "100%", aspectRatio: 1.45, borderRadius: 8,
    backgroundColor: "#020617",
  },
  framePlaceholder: { alignItems: "center", justifyContent: "center", gap: 10, padding: 16 },
  placeholderTxt: { color: "#94A3B8", fontSize: 11.5, textAlign: "center", maxWidth: 320 },
  note: { borderRadius: 8, borderWidth: 1, padding: 8 },
  noteTxt: { fontSize: 11.5, lineHeight: 16 },
  stepsBox: { gap: 3 },
  stepTxt: { color: "#94A3B8", fontSize: 10.5, lineHeight: 15 },
  otpBox: {
    backgroundColor: "#78350F22", borderWidth: 1, borderColor: "#D97706",
    borderRadius: 8, padding: 10, gap: 8,
  },
  otpTitle: { color: "#FCD34D", fontSize: 11.5, fontWeight: "700", lineHeight: 16 },
  otpInput: {
    flex: 1, backgroundColor: "#1E293B", borderRadius: 8, borderWidth: 1,
    borderColor: "#334155", color: "#F8FAFC", paddingHorizontal: 12,
    paddingVertical: 9, fontSize: 15, fontWeight: "800", letterSpacing: 3,
  },
  otpBtn: {
    backgroundColor: "#D97706", borderRadius: 8, paddingHorizontal: 16,
    alignItems: "center", justifyContent: "center",
  },
  otpBtnTxt: { color: "#fff", fontSize: 12.5, fontWeight: "900" },
  otpMsg: { color: "#94A3B8", fontSize: 10.5 },
});
