/**
 * Iter 610 — ESS: My Attendance (enhanced) + Shift/Roster + Correction Request.
 * Shows per-day IN/OUT, hours, punch SOURCE (Mobile/ZKTeco/ESSL/Manual),
 * holidays; "Request Correction" creates an ess_request (original punches
 * are never deleted). Shift tab shows today + upcoming roster.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/api/client";
import { colors } from "@/src/theme";

const nowMonth = () => new Date().toISOString().slice(0, 7);
const fmtT = (iso?: string | null) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });
  } catch { return iso.slice(11, 16); }
};
const SRC_COLOR: Record<string, string> = {
  mobile: "#2563EB", machine: "#7C3AED", zkteco: "#7C3AED", essl: "#7C3AED",
  manual: "#B45309", manual_correction: "#B45309", import: "#64748B",
};

export default function MyAttendance() {
  const router = useRouter();
  const [tab, setTab] = useState<"attendance" | "shift">("attendance");
  const [month, setMonth] = useState(nowMonth());
  const [data, setData] = useState<any>(null);
  const [shift, setShift] = useState<any>(null);
  const [corr, setCorr] = useState<any>(null); // day being corrected
  const [reqIn, setReqIn] = useState(""); const [reqOut, setReqOut] = useState("");
  const [reason, setReason] = useState(""); const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api(`/ess/attendance?month=${month}`).then(setData).catch(() => setData({ days: [] }));
    api("/ess/shift?days=8").then(setShift).catch(() => {});
  }, [month]);
  useEffect(() => { load(); }, [load]);

  const submitCorrection = async () => {
    if (!reqIn && !reqOut) { setMsg("Enter requested IN or OUT time"); return; }
    if (!reason.trim()) { setMsg("Reason is required"); return; }
    setBusy(true);
    try {
      const mk = (t: string) => (t ? `${corr.date}T${t.length === 5 ? t : t.padStart(5, "0")}:00+05:30` : null);
      const r = await api("/ess/requests", {
        method: "POST",
        body: {
          type: "attendance_correction", reason,
          payload: {
            date: corr.date, existing_in: corr.in, existing_out: corr.out,
            requested_in: mk(reqIn), requested_out: mk(reqOut),
          },
        },
      });
      setMsg(`Correction request ${r.request?.request_no} sent to HR ✓`);
      setCorr(null); setReqIn(""); setReqOut(""); setReason("");
    } catch (e: any) { setMsg(String(e?.message || e)); }
    finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="arrow-back" size={22} color={colors.onSurface} /></Pressable>
        <Text style={s.title}>My Attendance & Shift</Text>
      </View>
      <View style={s.tabs}>
        <Pressable style={[s.tab, tab === "attendance" && s.tabOn]} onPress={() => setTab("attendance")} testID="att-tab-attendance">
          <Text style={[s.tabTxt, tab === "attendance" && { color: "#fff" }]}>Attendance</Text>
        </Pressable>
        <Pressable style={[s.tab, tab === "shift" && s.tabOn]} onPress={() => setTab("shift")} testID="att-tab-shift">
          <Text style={[s.tabTxt, tab === "shift" && { color: "#fff" }]}>Shift / Roster</Text>
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={s.body}>
        {msg ? <Text style={s.msg}>{msg}</Text> : null}

        {tab === "attendance" ? (
          <>
            <View style={s.monthRow}>
              <TextInput style={s.monthInput} value={month} onChangeText={setMonth} placeholder="YYYY-MM"
                placeholderTextColor={colors.onSurfaceTertiary} testID="att-month" />
              <Pressable style={s.goBtn} onPress={load}><Text style={s.goTxt}>Load</Text></Pressable>
            </View>
            {!data ? <ActivityIndicator color={colors.brandPrimary} /> : null}
            {data && (data.days || []).length === 0 ? <Text style={s.muted}>No punches this month.</Text> : null}
            {(data?.days || []).slice().reverse().map((d: any) => (
              <View key={d.date} style={s.card} testID={`att-day-${d.date}`}>
                <View style={s.cardTop}>
                  <Text style={s.date}>{d.date}</Text>
                  {d.holiday ? <Text style={s.hol}>🎉 {d.holiday}</Text> : null}
                  <Text style={s.hours}>{d.hours != null ? `${d.hours}h` : ""}</Text>
                </View>
                <View style={s.ioRow}>
                  <Text style={s.io}>IN <Text style={s.ioT}>{fmtT(d.in)}</Text></Text>
                  <Text style={s.io}>OUT <Text style={s.ioT}>{fmtT(d.out)}</Text></Text>
                </View>
                <View style={s.srcRow}>
                  {(d.punches || []).map((p: any, i: number) => (
                    <View key={i} style={[s.srcPill, { backgroundColor: `${SRC_COLOR[p.source] || "#64748B"}18` }]}>
                      <Text style={[s.srcTxt, { color: SRC_COLOR[p.source] || "#64748B" }]}>
                        {p.kind?.toUpperCase()} · {p.source_label}{p.face_match_score ? " · 🔐" : ""}
                      </Text>
                    </View>
                  ))}
                </View>
                <Pressable style={s.corrBtn} onPress={() => { setCorr(d); setMsg(""); }} testID={`att-correct-${d.date}`}>
                  <Ionicons name="create-outline" size={13} color={colors.brandPrimary} />
                  <Text style={s.corrTxt}>Request Correction</Text>
                </Pressable>
              </View>
            ))}
          </>
        ) : (
          <>
            {!shift ? <ActivityIndicator color={colors.brandPrimary} /> : (
              <>
                <View style={[s.card, { borderColor: colors.brandPrimary, borderWidth: 1.5 }]}>
                  <Text style={s.secT}>TODAY&apos;S SHIFT</Text>
                  <Text style={s.shiftName}>{shift.today?.shift_name || "General"}</Text>
                  <Text style={s.sub}>
                    {shift.today?.start && shift.today?.end ? `${shift.today.start} – ${shift.today.end}` : "Timing as per firm policy"}
                    {shift.today?.worksite ? ` · ${shift.today.worksite}` : ""}
                  </Text>
                </View>
                <Text style={s.secT}>UPCOMING</Text>
                {(shift.roster || []).slice(1).map((r: any) => (
                  <View key={r.date} style={s.card}>
                    <View style={s.cardTop}>
                      <Text style={s.date}>{r.date}</Text>
                      <Text style={s.sub}>{r.shift_name}{r.start ? ` · ${r.start}–${r.end}` : ""}</Text>
                    </View>
                  </View>
                ))}
                <Text style={s.hint}>If HR changes your shift, you&apos;ll get a notification.</Text>
              </>
            )}
          </>
        )}
        <View style={{ height: 40 }} />
      </ScrollView>

      <Modal visible={!!corr} transparent animationType="fade" onRequestClose={() => setCorr(null)}>
        <Pressable style={s.modalBg} onPress={() => setCorr(null)}>
          <Pressable style={s.modalCard} onPress={() => {}}>
            <Text style={s.modalTitle}>Attendance Correction · {corr?.date}</Text>
            <Text style={s.sub}>Current: IN {fmtT(corr?.in)} · OUT {fmtT(corr?.out)}. Original punches are never deleted.</Text>
            <Text style={s.lbl}>Requested IN time (HH:MM, 24h) — leave blank if unchanged</Text>
            <TextInput style={s.input} value={reqIn} onChangeText={setReqIn} placeholder="09:00"
              placeholderTextColor={colors.onSurfaceTertiary} testID="att-corr-in" />
            <Text style={s.lbl}>Requested OUT time (HH:MM, 24h)</Text>
            <TextInput style={s.input} value={reqOut} onChangeText={setReqOut} placeholder="18:05"
              placeholderTextColor={colors.onSurfaceTertiary} testID="att-corr-out" />
            <Text style={s.lbl}>Reason *</Text>
            <TextInput style={s.input} value={reason} onChangeText={setReason}
              placeholder="e.g. Forgot to punch out" placeholderTextColor={colors.onSurfaceTertiary} testID="att-corr-reason" />
            <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
              <Pressable style={[s.mBtn, s.mBtnLight]} onPress={() => setCorr(null)}>
                <Text style={[s.mBtnTxt, { color: colors.onSurface }]}>Cancel</Text>
              </Pressable>
              <Pressable style={[s.mBtn, { backgroundColor: colors.brandPrimary }]} disabled={busy}
                onPress={submitCorrection} testID="att-corr-submit">
                {busy ? <ActivityIndicator size="small" color="#fff" /> : <Text style={s.mBtnTxt}>Submit to HR</Text>}
              </Pressable>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { flex: 1, fontSize: 17, fontWeight: "800", color: colors.onSurface },
  tabs: { flexDirection: "row", gap: 8, padding: 12, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  tab: { flex: 1, borderRadius: 999, paddingVertical: 9, alignItems: "center", backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, minHeight: 40 },
  tabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, fontWeight: "800", color: colors.onSurfaceSecondary },
  body: { padding: 16 },
  msg: { color: "#059669", fontWeight: "700", fontSize: 12.5, marginBottom: 8 },
  monthRow: { flexDirection: "row", gap: 10, marginBottom: 12 },
  monthInput: { flex: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, minHeight: 44, fontSize: 14, color: colors.onSurface },
  goBtn: { backgroundColor: colors.brandPrimary, borderRadius: 10, paddingHorizontal: 18, minHeight: 44, alignItems: "center", justifyContent: "center" },
  goTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  muted: { color: colors.onSurfaceTertiary, fontSize: 13, textAlign: "center", marginTop: 20 },
  card: { backgroundColor: colors.surface, borderRadius: 14, padding: 13, borderWidth: 1, borderColor: colors.border, marginBottom: 10 },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  date: { flex: 1, fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  hol: { fontSize: 11.5, color: "#B45309", fontWeight: "700" },
  hours: { fontSize: 13, fontWeight: "800", color: "#059669" },
  ioRow: { flexDirection: "row", gap: 20, marginTop: 6 },
  io: { fontSize: 12, color: colors.onSurfaceTertiary, fontWeight: "700" },
  ioT: { fontSize: 13, color: colors.onSurface, fontWeight: "800" },
  srcRow: { flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap" },
  srcPill: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  srcTxt: { fontSize: 10, fontWeight: "800" },
  corrBtn: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 8, alignSelf: "flex-start", minHeight: 32 },
  corrTxt: { fontSize: 12, color: colors.brandPrimary, fontWeight: "800" },
  secT: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceTertiary, textTransform: "uppercase", marginBottom: 6, marginTop: 4 },
  shiftName: { fontSize: 17, fontWeight: "800", color: colors.brandPrimary },
  sub: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: 3, lineHeight: 17 },
  hint: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 8, textAlign: "center" },
  lbl: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 10, marginBottom: 4 },
  input: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 9, fontSize: 13.5, color: colors.onSurface, minHeight: 42 },
  modalBg: { flex: 1, backgroundColor: "rgba(15,23,42,.5)", alignItems: "center", justifyContent: "center", padding: 20 },
  modalCard: { backgroundColor: colors.surface, borderRadius: 16, padding: 16, width: "100%", maxWidth: 420 },
  modalTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginBottom: 4 },
  mBtn: { flex: 1, borderRadius: 10, minHeight: 44, alignItems: "center", justifyContent: "center" },
  mBtnLight: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  mBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
});
