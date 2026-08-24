/**
 * Iter 706 — Tour Detail: status, Start/End tour (GPS), live tracking with
 * offline queue, timeline, client visits, expenses, OD attendance, approvals.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Platform, Alert, Linking,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Location from "expo-location";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors } from "@/src/theme";
import { getAccurateFix } from "@/src/utils/accurateLocation";
import { STATUS_META } from "./my-tours";

const toast = (m: string) => (Platform.OS === "web" ? window.alert(m) : Alert.alert("Tour", m));
const confirmYN = async (m: string) =>
  Platform.OS === "web" ? window.confirm(m) : new Promise<boolean>((res) =>
    Alert.alert("Confirm", m, [{ text: "No", onPress: () => res(false) },
      { text: "Yes", onPress: () => res(true) }]));

const QKEY = (id: string) => `tour_track_queue_${id}`;

export default function TourDetail() {
  const router = useRouter();
  const { user } = useAuth();
  const { id } = useLocalSearchParams<{ id: string }>();
  const isAdmin = ["super_admin", "sub_admin", "company_admin"].includes(user?.role as string);

  const [d, setD] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [visitOpen, setVisitOpen] = useState(false);
  const [visit, setVisit] = useState<any>({ client_name: "", contact_person: "", contact_number: "", meeting_purpose: "", summary: "", outcome: "", next_followup: "", start_time: "", end_time: "" });
  const [queueLen, setQueueLen] = useState(0);
  const timerRef = useRef<any>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try { setD(await api<any>(`/tours/${id}`)); }
    catch (e: any) { toast(e?.message || "Could not load tour"); }
    finally { setLoading(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const t = d?.tour;
  const isOwner = t?.user_id === user?.user_id;
  const meta = STATUS_META[t?.status] || STATUS_META.draft;

  // ---- Live tracking (runs while this screen is open on an active tour) --
  const captureAndSync = useCallback(async (tourId: string) => {
    let point: any = null;
    try {
      const fix = await getAccurateFix({ timeoutMs: 12000 });
      point = { lat: fix.latitude, lng: fix.longitude, accuracy: fix.accuracy,
                captured_at: new Date().toISOString(), offline: false };
    } catch { /* no fix this cycle */ }
    try {
      const raw = await AsyncStorage.getItem(QKEY(tourId));
      const queue: any[] = raw ? JSON.parse(raw) : [];
      if (point) queue.push(point);
      if (!queue.length) return;
      try {
        await api(`/tours/${tourId}/track`, { method: "POST", body: { points: queue } });
        await AsyncStorage.removeItem(QKEY(tourId));
        setQueueLen(0);
      } catch {
        // offline — keep queue, mark points as offline-captured
        const q2 = queue.map((p) => ({ ...p, offline: true }));
        await AsyncStorage.setItem(QKEY(tourId), JSON.stringify(q2.slice(-500)));
        setQueueLen(q2.length);
      }
    } catch { /* storage issue — skip cycle */ }
  }, []);

  useEffect(() => {
    if (!t || t.status !== "active" || !isOwner) return;
    const intervalMin = Math.max(1, Number(d?.tracking_interval_min) || 5);
    captureAndSync(t.tour_id);
    timerRef.current = setInterval(() => captureAndSync(t.tour_id), intervalMin * 60 * 1000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [t?.status, t?.tour_id, isOwner, d?.tracking_interval_min, captureAndSync, t]);

  const askLocation = async (): Promise<any | null> => {
    const cur = await Location.getForegroundPermissionsAsync();
    if (!cur.granted) {
      if (!cur.canAskAgain) {
        toast("Location permission is blocked. Please enable it in Settings to record your tour location.");
        Linking.openSettings?.();
        return null;
      }
      const ok = await confirmYN("Your live location is recorded during the official tour so your firm can verify visits. Allow location access?");
      if (!ok) return null;
      const req = await Location.requestForegroundPermissionsAsync();
      if (!req.granted) { toast("Location denied — tour actions will be recorded without GPS."); return null; }
    }
    try {
      const fix = await getAccurateFix({ timeoutMs: 12000 });
      return { lat: fix.latitude, lng: fix.longitude, accuracy: fix.accuracy };
    } catch { return null; }
  };

  const doStart = async () => {
    if (!(await confirmYN(`Start tour ${t.tour_no} now? Location tracking will be ACTIVE during the tour.`))) return;
    setBusy("start");
    try {
      const gps = await askLocation();
      await api(`/tours/${t.tour_id}/start`, { method: "POST", body: {
        ...(gps || {}), platform: Platform.OS,
        user_agent: Platform.OS === "web" ? navigator.userAgent?.slice(0, 180) : "",
      }});
      toast("Tour started — 🔴 tracking active");
      await load();
    } catch (e: any) { toast(e?.message || "Could not start tour"); }
    finally { setBusy(""); }
  };

  const doEnd = async () => {
    setBusy("end");
    try {
      const sm = await api<any>(`/tours/${t.tour_id}/summary`);
      const msg = `End tour ${t.tour_no}?\n\nStarted: ${(t.started_at || "").slice(0, 16).replace("T", " ")}\nDays: ${sm.total_days} · Meetings: ${sm.visits}\nTracking points: ${sm.tracking_points}${sm.distance_km ? ` · ~${sm.distance_km} km` : ""}\nExpenses claimed: ₹${sm.expenses_total} (${sm.expenses_count})`;
      if (!(await confirmYN(msg))) { setBusy(""); return; }
      const gps = await askLocation();
      let remarks: string | undefined;
      if (Platform.OS === "web") remarks = window.prompt("Closing remarks (optional):") || undefined;
      await api(`/tours/${t.tour_id}/end`, { method: "POST", body: { ...(gps || {}), remarks } });
      toast("Tour completed ✓");
      await load();
    } catch (e: any) { toast(e?.message || "Could not end tour"); }
    finally { setBusy(""); }
  };

  const doSubmit = async () => {
    setBusy("submit");
    try {
      await api(`/tours/${t.tour_id}/submit`, { method: "POST", body: {} });
      toast("Submitted for approval ✓"); await load();
    } catch (e: any) { toast(e?.message || "Submit failed"); }
    finally { setBusy(""); }
  };

  const doCancel = async () => {
    if (!(await confirmYN(`Cancel tour ${t.tour_no}?`))) return;
    setBusy("cancel");
    try { await api(`/tours/${t.tour_id}/cancel`, { method: "POST", body: {} }); await load(); }
    catch (e: any) { toast(e?.message || "Cancel failed"); }
    finally { setBusy(""); }
  };

  const saveVisit = async () => {
    if (!visit.client_name.trim()) { toast("Client / company name is required"); return; }
    setBusy("visit");
    try {
      const gps = await askLocation();
      await api(`/tours/${t.tour_id}/visits`, { method: "POST", body: {
        ...visit, ...(gps || {}), visit_date: new Date().toISOString().slice(0, 10) } });
      setVisitOpen(false);
      setVisit({ client_name: "", contact_person: "", contact_number: "", meeting_purpose: "", summary: "", outcome: "", next_followup: "", start_time: "", end_time: "" });
      toast("Visit recorded ✓"); await load();
    } catch (e: any) { toast(e?.message || "Could not save visit"); }
    finally { setBusy(""); }
  };

  const resolveConflict = async (dateKey: string, action: string) => {
    if (!(await confirmYN(`${action.replace(/_/g, " ")} for ${dateKey}?`))) return;
    try {
      await api(`/tours/${t.tour_id}/attendance/resolve`, { method: "POST",
        body: { date: dateKey, action } });
      toast("Resolved ✓"); await load();
    } catch (e: any) { toast(e?.message || "Resolve failed"); }
  };

  if (loading || !t) return <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />;

  const mapsUrl = (g: any) => `https://maps.google.com/?q=${g.lat},${g.lng}`;

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.hBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>{t.tour_no}</Text>
          <Text style={s.subtitle}>{t.tour_type} · {(t.destinations || []).join(", ")}</Text>
        </View>
        <View style={[s.chip, { backgroundColor: meta.bg }]}>
          <Text style={[s.chipT, { color: meta.color }]}>{meta.label}</Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={s.body}>
        {t.status === "active" ? (
          <View style={s.trackBanner} testID="tracking-banner">
            <Text style={{ fontSize: 12 }}>🔴</Text>
            <Text style={s.trackBannerT}>
              Tour Tracking Active — location recorded every {d?.tracking_interval_min || 5} min
              {queueLen > 0 ? ` · ${queueLen} point(s) queued offline` : ""}
            </Text>
          </View>
        ) : null}

        {/* Info */}
        <View style={s.card}>
          <Text style={s.infoT}>{t.employee?.name} {t.employee?.employee_code ? `(${t.employee.employee_code})` : ""}</Text>
          <Text style={s.info}>{t.start_date} {t.start_time} → {t.end_date} {t.end_time} · {t.total_days} day(s)</Text>
          <Text style={s.info}>From: {t.from_location || "—"} · Purpose: {t.purpose || "—"}</Text>
          {t.client_name ? <Text style={s.info}>Client: {t.client_name} {t.contact_person ? `· ${t.contact_person}` : ""}</Text> : null}
          <Text style={s.info}>Estimated: ₹{t.total_estimated || 0}{t.advance_required ? ` · Advance: ₹${t.advance_amount}` : ""}</Text>
          {t.approved_by_name ? <Text style={s.info}>Approved by: {t.approved_by_name}</Text> : null}
          {t.advance_payout ? (
            <Text style={[s.info, { fontWeight: "700" }]}>
              Advance ₹{t.advance_payout.amount} — {String(t.advance_payout.status || "").toUpperCase()}
              {t.advance_payout.paid_at ? ` on ${String(t.advance_payout.paid_at).slice(0, 10)} (${t.advance_payout.mode})` : ""}
              {t.advance_payout.status === "settled" ? ` · balance ₹${t.advance_payout.balance}` : ""}
            </Text>
          ) : null}
          {(t.attachments || []).map((a: any) => (
            <Text key={a.doc_id} style={[s.info, { color: colors.brandPrimary }]}>📎 {a.kind} · {a.name}</Text>
          ))}
        </View>

        {/* Actions */}
        <View style={s.actions}>
          {isOwner && ["draft", "returned"].includes(t.status) ? (
            <>
              <Pressable style={s.btnO} onPress={() => router.push(`/tour-request?id=${t.tour_id}` as any)} testID="tour-edit">
                <Text style={s.btnOT}>Edit</Text>
              </Pressable>
              <Pressable style={s.btnP} disabled={busy !== ""} onPress={doSubmit} testID="tour-submit-btn">
                {busy === "submit" ? <ActivityIndicator size="small" color="#fff" /> : <Text style={s.btnPT}>Submit for Approval</Text>}
              </Pressable>
            </>
          ) : null}
          {isOwner && t.status === "approved" ? (
            <Pressable style={[s.btnP, { backgroundColor: "#059669" }]} disabled={busy !== ""} onPress={doStart} testID="tour-start-btn">
              {busy === "start" ? <ActivityIndicator size="small" color="#fff" /> : <Text style={s.btnPT}>▶ Start Tour</Text>}
            </Pressable>
          ) : null}
          {t.status === "active" && (isOwner || isAdmin) ? (
            <>
              {isOwner ? (
                <Pressable style={s.btnO} onPress={() => setVisitOpen((v) => !v)} testID="tour-add-visit-btn">
                  <Text style={s.btnOT}>+ Add Visit</Text>
                </Pressable>
              ) : null}
              {isOwner ? (
                <Pressable style={s.btnO} testID="tour-add-expense-btn"
                  onPress={() => router.push(`/expense-claim-form?tour_id=${t.tour_id}` as any)}>
                  <Text style={s.btnOT}>+ Add Expense</Text>
                </Pressable>
              ) : null}
              <Pressable style={[s.btnP, { backgroundColor: "#DC2626" }]} disabled={busy !== ""} onPress={doEnd} testID="tour-end-btn">
                {busy === "end" ? <ActivityIndicator size="small" color="#fff" /> : <Text style={s.btnPT}>⏹ End Tour</Text>}
              </Pressable>
            </>
          ) : null}
          {t.status === "completed" && isOwner ? (
            <Pressable style={s.btnO} testID="tour-add-expense-btn"
              onPress={() => router.push(`/expense-claim-form?tour_id=${t.tour_id}` as any)}>
              <Text style={s.btnOT}>+ Add Expense</Text>
            </Pressable>
          ) : null}
          {isOwner && ["draft", "submitted", "pending_approval", "approved"].includes(t.status) ? (
            <Pressable style={[s.btnO, { borderColor: "#DC2626" }]} onPress={doCancel} testID="tour-cancel-btn">
              <Text style={[s.btnOT, { color: "#DC2626" }]}>Cancel</Text>
            </Pressable>
          ) : null}
        </View>

        {/* Add visit form */}
        {visitOpen ? (
          <View style={s.card}>
            <Text style={s.secT}>Add Visit / Client Meeting</Text>
            {[["client_name", "Client / Company Name *"], ["contact_person", "Contact Person"],
              ["contact_number", "Contact Number"], ["meeting_purpose", "Meeting Purpose"],
              ["summary", "Meeting Summary / Discussion"], ["outcome", "Outcome"],
              ["next_followup", "Next Follow-up (YYYY-MM-DD)"]].map(([k, lbl]) => (
              <TextInput key={k} value={visit[k]} onChangeText={(v) => setVisit((p: any) => ({ ...p, [k]: v }))}
                placeholder={lbl} placeholderTextColor={colors.onSurfaceTertiary}
                style={[s.input, ["summary", "meeting_purpose"].includes(k) && { minHeight: 54 }]}
                multiline={["summary", "meeting_purpose"].includes(k)} testID={`visit-${k}`} />
            ))}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
              <TextInput value={visit.start_time} onChangeText={(v) => setVisit((p: any) => ({ ...p, start_time: v }))}
                placeholder="Start 10:30" placeholderTextColor={colors.onSurfaceTertiary} style={[s.input, { flex: 1, marginTop: 0 }]} testID="visit-start" />
              <TextInput value={visit.end_time} onChangeText={(v) => setVisit((p: any) => ({ ...p, end_time: v }))}
                placeholder="End 11:45" placeholderTextColor={colors.onSurfaceTertiary} style={[s.input, { flex: 1, marginTop: 0 }]} testID="visit-end" />
            </View>
            <Pressable style={[s.btnP, { marginTop: 10 }]} disabled={busy !== ""} onPress={saveVisit} testID="visit-save">
              {busy === "visit" ? <ActivityIndicator size="small" color="#fff" /> : <Text style={s.btnPT}>Save Visit (GPS auto-captured)</Text>}
            </Pressable>
          </View>
        ) : null}

        {/* Timeline */}
        {(d.timeline || []).length ? (
          <View style={s.card}>
            <Text style={s.secT}>Tour Timeline</Text>
            {d.timeline.map((e: any, i: number) => (
              <View key={i} style={s.tlRow}>
                <View style={s.tlDot} />
                <View style={{ flex: 1 }}>
                  <Text style={s.tlTime}>{String(e.at || "").slice(0, 16).replace("T", " · ")}</Text>
                  <Text style={s.tlLabel}>{e.label}</Text>
                  {e.detail ? <Text style={s.info}>{e.detail}</Text> : null}
                  {e.gps ? (
                    <Pressable onPress={() => Linking.openURL(mapsUrl(e.gps))}>
                      <Text style={[s.info, { color: colors.brandPrimary }]}>
                        📍 {e.gps.lat?.toFixed(5)}, {e.gps.lng?.toFixed(5)} — open map
                      </Text>
                    </Pressable>
                  ) : null}
                </View>
              </View>
            ))}
            <Text style={s.info}>Tracking points recorded: {d.tracking_points}</Text>
          </View>
        ) : null}

        {/* Visits */}
        {(d.visits || []).length ? (
          <View style={s.card}>
            <Text style={s.secT}>Client Visits ({d.visits.length})</Text>
            {d.visits.map((v: any) => (
              <View key={v.visit_id} style={s.subCard}>
                <Text style={s.infoT}>{v.client_name} · {v.visit_date} {v.start_time}</Text>
                {v.meeting_purpose ? <Text style={s.info}>Purpose: {v.meeting_purpose}</Text> : null}
                {v.summary ? <Text style={s.info}>Summary: {v.summary}</Text> : null}
                {v.outcome ? <Text style={s.info}>Outcome: {v.outcome}</Text> : null}
                {v.next_followup ? <Text style={s.info}>Follow-up: {v.next_followup}</Text> : null}
                {v.gps ? (
                  <Pressable onPress={() => Linking.openURL(mapsUrl(v.gps))}>
                    <Text style={[s.info, { color: colors.brandPrimary }]}>📍 View meeting location</Text>
                  </Pressable>
                ) : null}
              </View>
            ))}
          </View>
        ) : null}

        {/* Expenses */}
        <View style={s.card}>
          <Text style={s.secT}>Expenses on this Tour ({(d.expenses || []).length})</Text>
          {(d.expenses || []).map((e: any) => (
            <View key={e.claim_id} style={s.expRow}>
              <Text style={[s.info, { flex: 1 }]}>{e.claim_no} · {e.category_name} · {e.expense_date}</Text>
              <Text style={s.infoT}>₹{e.amount}</Text>
              <Text style={[s.info, { width: 90, textAlign: "right" }]}>{e.status}</Text>
            </View>
          ))}
          {!(d.expenses || []).length ? <Text style={s.info}>No expense claims linked yet.</Text> : null}
        </View>

        {/* Attendance */}
        {t.mark_od ? (
          <View style={s.card}>
            <Text style={s.secT}>OD / Tour Attendance</Text>
            {(d.attendance || []).length ? d.attendance.map((a: any) => (
              <View key={a.record_id} style={s.expRow}>
                <Text style={[s.info, { flex: 1 }]}>{a.date} · OD · {a.day === "half" ? "Half" : "Full"} Day</Text>
                <Text style={[s.infoT, { color: a.status === "conflict" ? "#DC2626" : a.status === "posted" ? "#059669" : colors.onSurfaceTertiary }]}>
                  {a.status}
                </Text>
                {isAdmin && a.status === "conflict" ? (
                  <View style={{ flexDirection: "row", gap: 6, marginLeft: 8 }}>
                    {[["keep_existing", "Keep"], ["convert_to_od", "→OD"], ["cancel_tour_attendance", "Drop"]].map(([act, lbl]) => (
                      <Pressable key={act} style={s.miniBtn} onPress={() => resolveConflict(a.date, act)} testID={`resolve-${act}-${a.date}`}>
                        <Text style={s.miniBtnT}>{lbl}</Text>
                      </Pressable>
                    ))}
                  </View>
                ) : null}
              </View>
            )) : (d.od_preview || []).map((p: any) => (
              <Text key={p.date} style={s.info}>{p.date} → OD → {p.day} (posts after final approval)</Text>
            ))}
          </View>
        ) : null}

        {/* Approval history */}
        {(d.approval?.history || t.approval_history || []).length ? (
          <View style={s.card}>
            <Text style={s.secT}>Approval History</Text>
            {(d.approval?.history || t.approval_history).map((h: any, i: number) => (
              <Text key={i} style={s.info}>
                {String(h.at || "").slice(0, 16).replace("T", " ")} · L{h.level ?? "—"} · {h.action?.toUpperCase()} by {h.by_name}{h.remarks ? ` — ${h.remarks}` : ""}
              </Text>
            ))}
          </View>
        ) : null}
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surfaceSecondary, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  hBtn: { width: 38, height: 38, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceTertiary },
  title: { fontSize: 16.5, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 1 },
  chip: { borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4 },
  chipT: { fontSize: 10.5, fontWeight: "800" },
  body: { padding: 16, width: "100%", maxWidth: 760, alignSelf: "center" },
  trackBanner: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "rgba(220,38,38,0.09)",
    borderWidth: 1, borderColor: "rgba(220,38,38,0.3)", borderRadius: 12, padding: 10, marginBottom: 12,
  },
  trackBannerT: { flex: 1, fontSize: 12, fontWeight: "700", color: "#DC2626" },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 14, padding: 12,
    borderWidth: 1, borderColor: colors.border, marginBottom: 12,
  },
  subCard: {
    backgroundColor: colors.surface, borderRadius: 10, padding: 10,
    borderWidth: 1, borderColor: colors.border, marginTop: 8,
  },
  secT: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 6 },
  infoT: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  info: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 3 },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  btnP: { minHeight: 44, borderRadius: 12, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center", paddingHorizontal: 16, flexGrow: 1 },
  btnPT: { color: "#fff", fontWeight: "800", fontSize: 13 },
  btnO: {
    minHeight: 44, borderRadius: 12, borderWidth: 1.5, borderColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center", paddingHorizontal: 14, flexGrow: 1,
  },
  btnOT: { color: colors.brandPrimary, fontWeight: "800", fontSize: 13 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 10,
    paddingVertical: 9, fontSize: 13, color: colors.onSurface, backgroundColor: colors.surface, marginTop: 8,
  },
  tlRow: { flexDirection: "row", gap: 10, marginTop: 10 },
  tlDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brandPrimary, marginTop: 5 },
  tlTime: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceTertiary },
  tlLabel: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  expRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 6, flexWrap: "wrap" },
  miniBtn: { backgroundColor: colors.brandPrimary, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 5 },
  miniBtnT: { color: "#fff", fontSize: 10.5, fontWeight: "800" },
});
