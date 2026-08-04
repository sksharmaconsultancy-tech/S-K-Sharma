/**
 * Iter 486 — CLRA Phase 3 panel for the Report Hub:
 *  • Inspection Register entry management (add / list / delete) — shown
 *    only when the Inspection Register report is selected.
 *  • Scheduled Email Reports (daily / weekly / monthly, IST) — collapsible
 *    panel listing schedules + add form + Send-Now test.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, TextInput, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function ClraPhase3Panel({
  kind, companyId, reportKinds,
}: {
  kind: string | null;
  companyId: string | null;
  reportKinds: { kind: string; title: string }[];
}) {
  // ---------------- Inspection entries ----------------
  const [entries, setEntries] = useState<any[]>([]);
  const [form, setForm] = useState<any>({ date: "", inspector_name: "", designation: "", authority: "", observations: "", action_taken: "", status: "open" });
  const [showAdd, setShowAdd] = useState(false);
  const loadEntries = useCallback(async () => {
    if (!companyId) return;
    try {
      const r = await api<{ inspections: any[] }>(`/admin/clra-reports/inspections?company_id=${companyId}`);
      setEntries(r.inspections || []);
    } catch {}
  }, [companyId]);
  useEffect(() => { if (kind === "inspection-register") void loadEntries(); }, [kind, loadEntries]);

  const saveEntry = async () => {
    try {
      await api(`/admin/clra-reports/inspections?company_id=${companyId}`, { method: "POST", body: form });
      setForm({ date: "", inspector_name: "", designation: "", authority: "", observations: "", action_taken: "", status: "open" });
      setShowAdd(false);
      await loadEntries();
    } catch (e: any) { if (Platform.OS === "web") window.alert(e?.message || "Save failed"); }
  };
  const delEntry = async (id: string) => {
    if (Platform.OS === "web" && !window.confirm("Delete this inspection entry?")) return;
    try { await api(`/admin/clra-reports/inspections/${id}?company_id=${companyId}`, { method: "DELETE" }); await loadEntries(); } catch {}
  };

  // ---------------- Scheduled email reports ----------------
  const [showSched, setShowSched] = useState(false);
  const [schedules, setSchedules] = useState<any[]>([]);
  const [sf, setSf] = useState<any>({ report_kind: "", fmt: "pdf", frequency: "monthly", weekday: 0, day_of_month: 1, time: "09:00", recipients: "", enabled: true });
  const loadSchedules = useCallback(async () => {
    if (!companyId) return;
    try {
      const r = await api<{ schedules: any[] }>(`/admin/report-schedules?company_id=${companyId}`);
      setSchedules(r.schedules || []);
    } catch {}
  }, [companyId]);
  useEffect(() => { if (showSched) void loadSchedules(); }, [showSched, loadSchedules]);

  const saveSchedule = async () => {
    try {
      await api(`/admin/report-schedules`, {
        method: "POST",
        body: { ...sf, company_id: companyId, recipients: String(sf.recipients).split(",").map((s: string) => s.trim()).filter(Boolean) },
      });
      setSf({ report_kind: "", fmt: "pdf", frequency: "monthly", weekday: 0, day_of_month: 1, time: "09:00", recipients: "", enabled: true });
      await loadSchedules();
    } catch (e: any) { if (Platform.OS === "web") window.alert(e?.message || "Save failed"); }
  };
  const delSchedule = async (id: string) => {
    if (Platform.OS === "web" && !window.confirm("Delete this schedule?")) return;
    try { await api(`/admin/report-schedules/${id}?company_id=${companyId}`, { method: "DELETE" }); await loadSchedules(); } catch {}
  };
  const sendNow = async (id: string) => {
    try {
      const r = await api<{ detail: string }>(`/admin/report-schedules/${id}/send-now?company_id=${companyId}`, { method: "POST" });
      if (Platform.OS === "web") window.alert(r.detail || "Sent ✓");
    } catch (e: any) { if (Platform.OS === "web") window.alert(e?.message || "Send failed"); }
  };

  const chip = (label: string, on: boolean, onPress: () => void, testID?: string) => (
    <Pressable key={label} onPress={onPress} style={[st.chip, on && st.chipOn]} testID={testID}>
      <Text style={[st.chipTxt, on && { color: "#FFF" }]}>{label}</Text>
    </Pressable>
  );
  const fld = (ph: string, key: string, obj: any, setObj: any, w = 120) => (
    <TextInput style={[st.input, { width: w }]} placeholder={ph}
               placeholderTextColor={colors.onSurfaceTertiary}
               value={String(obj[key] ?? "")}
               onChangeText={(v) => setObj({ ...obj, [key]: v })} />
  );

  return (
    <View>
      {/* Scheduled email reports (always available in the hub) */}
      <Pressable onPress={() => setShowSched((v) => !v)} style={st.schedBtn} testID="rc-schedules-toggle">
        <Ionicons name="calendar-outline" size={14} color={colors.brandPrimary} />
        <Text style={st.schedBtnTxt}>Scheduled Email Reports {schedules.length ? `(${schedules.length})` : ""}</Text>
        <Ionicons name={showSched ? "chevron-up" : "chevron-down"} size={13} color={colors.onSurfaceSecondary} />
      </Pressable>
      {showSched ? (
        <View style={st.card}>
          {schedules.map((s) => (
            <View key={s.schedule_id} style={st.row}>
              <Text style={st.rowTxt} numberOfLines={2}>
                {reportKinds.find((k) => k.kind === s.report_kind)?.title || s.report_kind} · {s.fmt.toUpperCase()} · {s.frequency}
                {s.frequency === "weekly" ? ` (${WD[s.weekday]})` : s.frequency === "monthly" ? ` (day ${s.day_of_month})` : ""} @ {s.time} IST → {(s.recipients || []).join(", ")}
                {s.last_sent_at ? `\nLast: ${String(s.last_sent_at).slice(0, 16).replace("T", " ")} — ${s.last_sent_ok ? "✓" : "✗"} ${s.last_sent_detail || ""}` : ""}
              </Text>
              <Pressable onPress={() => sendNow(s.schedule_id)} style={st.mini}><Text style={st.miniTxt}>Send now</Text></Pressable>
              <Pressable onPress={() => delSchedule(s.schedule_id)} style={st.mini}><Ionicons name="trash-outline" size={13} color={colors.error} /></Pressable>
            </View>
          ))}
          {!schedules.length ? <Text style={st.mute}>No schedules yet — add one below. Uses the firm&apos;s SMTP (Email Settings).</Text> : null}
          <View style={st.formRow}>
            {reportKinds.map((k) => chip(k.title, sf.report_kind === k.kind, () => setSf({ ...sf, report_kind: k.kind })))}
          </View>
          <View style={st.formRow}>
            {["pdf", "xlsx"].map((f) => chip(f.toUpperCase(), sf.fmt === f, () => setSf({ ...sf, fmt: f })))}
            {["daily", "weekly", "monthly"].map((f) => chip(f, sf.frequency === f, () => setSf({ ...sf, frequency: f })))}
            {sf.frequency === "weekly" ? WD.map((w, i) => chip(w, sf.weekday === i, () => setSf({ ...sf, weekday: i }))) : null}
            {sf.frequency === "monthly" ? fld("Day (1-31)", "day_of_month", sf, setSf, 80) : null}
            {fld("HH:MM IST", "time", sf, setSf, 80)}
          </View>
          <View style={st.formRow}>
            {fld("recipient1@mail.com, recipient2@mail.com", "recipients", sf, setSf, 320)}
            <Pressable onPress={saveSchedule} style={st.saveBtn} testID="rc-schedule-save">
              <Text style={st.saveBtnTxt}>Add Schedule</Text>
            </Pressable>
          </View>
        </View>
      ) : null}

      {/* Inspection entries — only for the Inspection Register */}
      {kind === "inspection-register" ? (
        <View style={st.card}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Text style={st.title}>Inspection Entries ({entries.length})</Text>
            <Pressable onPress={() => setShowAdd((v) => !v)} style={st.mini} testID="rc-inspection-add">
              <Text style={st.miniTxt}>{showAdd ? "Close" : "➕ Add Entry"}</Text>
            </Pressable>
          </View>
          {showAdd ? (
            <>
              <View style={st.formRow}>
                {fld("Date YYYY-MM-DD", "date", form, setForm, 120)}
                {fld("Inspector name", "inspector_name", form, setForm, 160)}
                {fld("Designation", "designation", form, setForm, 130)}
                {fld("Authority / Dept", "authority", form, setForm, 150)}
              </View>
              <View style={st.formRow}>
                {fld("Observations / remarks", "observations", form, setForm, 260)}
                {fld("Action taken", "action_taken", form, setForm, 200)}
                {["open", "closed"].map((s) => chip(s.toUpperCase(), form.status === s, () => setForm({ ...form, status: s })))}
                <Pressable onPress={saveEntry} style={st.saveBtn} testID="rc-inspection-save">
                  <Text style={st.saveBtnTxt}>Save Entry</Text>
                </Pressable>
              </View>
            </>
          ) : null}
          {entries.map((e) => (
            <View key={e.inspection_id} style={st.row}>
              <Text style={st.rowTxt} numberOfLines={2}>
                {e.date} · {e.inspector_name} {e.designation ? `(${e.designation})` : ""} {e.authority ? `· ${e.authority}` : ""} · {String(e.status || "open").toUpperCase()}
                {e.observations ? `\n${e.observations}` : ""}
              </Text>
              <Pressable onPress={() => delEntry(e.inspection_id)} style={st.mini}>
                <Ionicons name="trash-outline" size={13} color={colors.error} />
              </Pressable>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const st = StyleSheet.create({
  schedBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 7, marginBottom: 8, backgroundColor: colors.surface,
  },
  schedBtnTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  card: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 10, marginBottom: 10, backgroundColor: colors.surfaceSecondary, gap: 8,
  },
  title: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  row: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderBottomWidth: 1, borderBottomColor: colors.divider, paddingVertical: 6,
  },
  rowTxt: { flex: 1, fontSize: 11.5, color: colors.onSurface },
  mute: { fontSize: 11, color: colors.onSurfaceTertiary },
  formRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, alignItems: "center" },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 7,
    paddingHorizontal: 8, paddingVertical: 6, fontSize: 12, color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  chip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingHorizontal: 9, paddingVertical: 5, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  mini: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 7,
    paddingHorizontal: 8, paddingVertical: 5, backgroundColor: colors.surface,
  },
  miniTxt: { fontSize: 11, fontWeight: "700", color: colors.brandPrimary },
  saveBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 7,
  },
  saveBtnTxt: { fontSize: 11.5, fontWeight: "800", color: "#FFF" },
});
