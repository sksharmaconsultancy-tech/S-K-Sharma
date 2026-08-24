/**
 * Iter 708 — Firm Master → PWA Settings → Attendance Data Management.
 * Firm-wise: PWA attendance auto-delete (with configurable date), manual
 * wipe, and screenshot protection. PWA-side lifecycle ONLY — the payroll
 * database is never touched.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, Switch, ActivityIndicator, Platform, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors } from "@/src/theme";

const toast = (m: string) => (Platform.OS === "web" ? window.alert(m) : Alert.alert("PWA Settings", m));

export default function PwaSettingsSection({ companyId }: { companyId: string | null }) {
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!companyId) return;
    try { setData(await api<any>(`/admin/pwa-settings?company_id=${companyId}`)); }
    catch (e: any) { toast(e?.message || "Failed to load PWA settings"); }
  }, [companyId]);
  useEffect(() => { load(); }, [load]);

  const save = async (patch: any) => {
    try {
      const r = await api<any>("/admin/pwa-settings", {
        method: "POST", body: { company_id: companyId, ...patch } });
      setData((p: any) => ({ ...p, settings: r.settings }));
    } catch (e: any) { toast(e?.message || "Save failed"); }
  };

  const wipe = async () => {
    const msg = "This action will clear last month's attendance data from the Employee PWA only. Database and Employer Login records will not be deleted.\n\nContinue?";
    const ok = Platform.OS === "web" ? window.confirm(msg)
      : await new Promise<boolean>((res) => Alert.alert("Manual Wipe", msg,
        [{ text: "Cancel", onPress: () => res(false) },
         { text: "Wipe", style: "destructive", onPress: () => res(true) }]));
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api<any>("/admin/pwa-wipe-last-month", {
        method: "POST", body: { company_id: companyId } });
      toast(`${r.result.status === "already_applied" ? "Already applied" : "Wiped"} — ${r.result.month_cleared}: ${r.result.affected_pwa_records} PWA record(s) hidden. Database preserved ✓`);
      load();
    } catch (e: any) { toast(e?.message || "Wipe failed"); }
    finally { setBusy(false); }
  };

  if (!companyId) return <Text style={s.hint}>Select a firm first.</Text>;
  if (!data) return <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 20 }} />;
  const st = data.settings || {};

  return (
    <View>
      <Text style={s.secT}>Attendance Data Management</Text>
      <Text style={s.hint}>
        PWA-side lifecycle only — payroll database, employer login, reports,
        compliance and audit records are NEVER deleted.
      </Text>

      <View style={s.row}>
        <Text style={s.lbl}>PWA Attendance Auto-Delete</Text>
        <Switch value={!!st.attendance_autodelete}
          onValueChange={(v) => save({ attendance_autodelete: v })}
          trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }}
          testID="pwa-autodelete" />
      </View>
      {st.attendance_autodelete ? (
        <View style={s.row}>
          <Text style={s.lbl}>Auto Delete Date (day of month)</Text>
          <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
            {[1, 3, 5, 7, 10, 15].map((d) => (
              <Pressable key={d} style={[s.dChip, st.autodelete_day === d && s.dChipOn]}
                onPress={() => save({ autodelete_day: d })} testID={`pwa-day-${d}`}>
                <Text style={[s.dChipT, st.autodelete_day === d && { color: "#fff" }]}>{d}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      ) : null}
      {st.attendance_autodelete ? (
        <Text style={s.hint}>
          On the {st.autodelete_day}th of every month, the PREVIOUS calendar
          month&apos;s attendance is cleared from the Employee PWA automatically.
        </Text>
      ) : null}
      {st.attendance_hidden_before ? (
        <Text style={[s.hint, { color: "#B45309" }]}>
          Employee PWA currently hides attendance before {st.attendance_hidden_before}.
        </Text>
      ) : null}

      <Pressable style={[s.wipeBtn, busy && { opacity: 0.6 }]} disabled={busy}
        onPress={wipe} testID="pwa-manual-wipe">
        {busy ? <ActivityIndicator size="small" color="#fff" /> : (
          <>
            <Ionicons name="trash-outline" size={15} color="#fff" />
            <Text style={s.wipeBtnT}>Wipe Last Month PWA Attendance</Text>
          </>
        )}
      </Pressable>

      <Text style={[s.secT, { marginTop: 20 }]}>Screenshot Protection</Text>
      <View style={s.row}>
        <Text style={s.lbl}>Block Screenshot / Screen Capture</Text>
        <Switch value={!!st.screenshot_protection}
          onValueChange={(v) => save({ screenshot_protection: v })}
          trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }}
          testID="pwa-screenshot" />
      </View>
      <Text style={s.hint}>
        When ON, the Employee PWA masks content in background/app-switcher,
        blocks copy &amp; context menu, watermarks sensitive screens with the
        employee&apos;s name, blocks capture on installed mobile builds, and shows
        &quot;Screenshot is restricted by your organization&quot; on capture
        attempts. Browsers cannot guarantee 100% prevention (e.g. external
        camera) — the strongest platform-supported protection is applied.
      </Text>

      {(data.audit || []).length ? (
        <>
          <Text style={[s.secT, { marginTop: 20 }]}>Wipe Audit Trail</Text>
          {data.audit.map((a: any) => (
            <View key={a.audit_id} style={s.auditRow}>
              <Text style={s.auditT}>
                {String(a.executed_at || "").slice(0, 16).replace("T", " ")} · {a.trigger} · month {a.month_cleared} ·
                {" "}{a.affected_pwa_records} record(s) · {a.status} · by {a.by_name}
              </Text>
            </View>
          ))}
        </>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  secT: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface, marginBottom: 6 },
  hint: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 6, lineHeight: 16 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10, marginTop: 12, flexWrap: "wrap" },
  lbl: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary, flexShrink: 1 },
  dChip: {
    minWidth: 36, height: 34, borderRadius: 9, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary, alignItems: "center", justifyContent: "center", paddingHorizontal: 8,
  },
  dChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  dChipT: { fontSize: 12, fontWeight: "800", color: colors.onSurfaceSecondary },
  wipeBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: "#DC2626", borderRadius: 10, minHeight: 44, marginTop: 14, paddingHorizontal: 16,
  },
  wipeBtnT: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  auditRow: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 9, padding: 9, marginTop: 6,
    borderWidth: 1, borderColor: colors.border,
  },
  auditT: { fontSize: 11, color: colors.onSurfaceSecondary },
});
