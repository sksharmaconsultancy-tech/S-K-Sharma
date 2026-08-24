/**
 * Iter 706 — New / Edit Tour Request form.
 * Sections: Basic · Schedule · Business · Financial · Attendance (OD) ·
 * Attachments. Approval runs via the configured workflow after submit.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Platform, Alert, Switch, KeyboardAvoidingView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors } from "@/src/theme";
import DateField from "@/src/components/DateField";

const toast = (m: string) => (Platform.OS === "web" ? window.alert(m) : Alert.alert("Tour", m));
const TOUR_TYPES = ["Official Tour", "Client Visit", "Business Development", "Training", "Meeting", "Other"];
const ATT_KINDS = ["Tour Letter", "Client Invitation", "Meeting Letter", "Other"];

type PendingFile = { name: string; mime: string; data_b64: string; kind: string };

export default function TourRequest() {
  const router = useRouter();
  const { user } = useAuth();
  const { id } = useLocalSearchParams<{ id?: string }>();
  const editing = !!id;

  const [f, setF] = useState<any>({
    tour_type: "Official Tour", start_date: "", start_time: "09:00",
    end_date: "", end_time: "18:00", from_location: "",
    client_name: "", contact_person: "", contact_number: "",
    meeting_purpose: "", expected_outcome: "", purpose: "", remarks: "",
    est_travel: "", est_food: "", est_accommodation: "", est_other: "",
    advance_required: false, advance_amount: "",
    mark_od: true, od_day_type: "full",
  });
  const [dests, setDests] = useState<string[]>([""]);
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [saving, setSaving] = useState<"" | "draft" | "submit">("");
  const [loading, setLoading] = useState(editing);

  useEffect(() => {
    if (!id) return;
    api<any>(`/tours/${id}`).then((r) => {
      const t = r.tour || {};
      setF((p: any) => ({
        ...p, ...Object.fromEntries(Object.entries(t).filter(([k]) => k in p)),
        est_travel: String(t.est_travel || ""), est_food: String(t.est_food || ""),
        est_accommodation: String(t.est_accommodation || ""), est_other: String(t.est_other || ""),
        advance_amount: String(t.advance_amount || ""),
      }));
      setDests(t.destinations?.length ? t.destinations : [""]);
    }).catch((e) => toast(e?.message || "Could not load tour"))
      .finally(() => setLoading(false));
  }, [id]);

  const totalDays = useMemo(() => {
    try {
      const a = new Date(f.start_date), b = new Date(f.end_date);
      const d = Math.round((b.getTime() - a.getTime()) / 86400000) + 1;
      return Number.isFinite(d) && d > 0 ? d : "—";
    } catch { return "—"; }
  }, [f.start_date, f.end_date]);

  const totalEst = useMemo(() =>
    ["est_travel", "est_food", "est_accommodation", "est_other"]
      .reduce((s, k) => s + (parseFloat(f[k]) || 0), 0), [f]);

  const set = (k: string, v: any) => setF((p: any) => ({ ...p, [k]: v }));

  const pickFile = async (kind: string, camera: boolean) => {
    try {
      if (camera || Platform.OS !== "web") {
        if (camera) {
          const perm = await ImagePicker.requestCameraPermissionsAsync();
          if (!perm.granted) { toast("Camera permission is needed to photograph the document"); return; }
        }
        const res = camera
          ? await ImagePicker.launchCameraAsync({ quality: 0.7, base64: true })
          : await ImagePicker.launchImageLibraryAsync({ quality: 0.7, base64: true });
        const a = res.assets?.[0];
        if (!a?.base64) return;
        setFiles((p) => [...p, {
          name: a.fileName || `${kind.replace(/\s+/g, "_")}_${Date.now()}.jpg`,
          mime: a.mimeType === "image/png" ? "image/png" : "image/jpeg",
          data_b64: a.base64, kind,
        }]);
        return;
      }
      const res = await DocumentPicker.getDocumentAsync({
        type: ["application/pdf", "image/jpeg", "image/png"], copyToCacheDirectory: true });
      const a = res.assets?.[0];
      if (!a) return;
      const resp = await fetch(a.uri);
      const blob = await resp.blob();
      const b64 = await new Promise<string>((resolve) => {
        const rd = new FileReader();
        rd.onloadend = () => resolve(String(rd.result).split(",")[1] || "");
        rd.readAsDataURL(blob);
      });
      setFiles((p) => [...p, {
        name: a.name || "document", mime: a.mimeType || "application/pdf",
        data_b64: b64, kind,
      }]);
    } catch { toast("Could not attach the file"); }
  };

  const save = async (thenSubmit: boolean) => {
    const destinations = dests.map((d) => d.trim()).filter(Boolean);
    if (!f.start_date || !f.end_date) { toast("Select the tour start and end dates"); return; }
    if (!destinations.length) { toast("Enter at least one destination"); return; }
    if (!f.purpose.trim()) { toast("Tour purpose is required"); return; }
    setSaving(thenSubmit ? "submit" : "draft");
    try {
      const body = {
        ...f, destinations,
        est_travel: parseFloat(f.est_travel) || 0, est_food: parseFloat(f.est_food) || 0,
        est_accommodation: parseFloat(f.est_accommodation) || 0, est_other: parseFloat(f.est_other) || 0,
        advance_amount: parseFloat(f.advance_amount) || 0,
      };
      let tourId = id as string;
      if (editing) {
        await api(`/tours/${tourId}`, { method: "PUT", body });
      } else {
        const r = await api<any>("/tours", { method: "POST", body });
        tourId = r.tour.tour_id;
      }
      for (const file of files) {
        await api(`/tours/${tourId}/attachments`, { method: "POST", body: file });
      }
      if (thenSubmit) {
        await api(`/tours/${tourId}/submit`, { method: "POST", body: {} });
        toast("Tour request submitted for approval ✓");
      } else {
        toast("Tour saved as draft ✓");
      }
      router.replace(`/tour-detail?id=${tourId}` as any);
    } catch (e: any) { toast(e?.message || "Save failed"); }
    finally { setSaving(""); }
  };

  if (loading) return <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />;

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.hBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>{editing ? "Edit Tour Request" : "New Tour Request"}</Text>
          <Text style={s.subtitle}>Tour ID is auto-generated on save</Text>
        </View>
      </View>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={s.body} keyboardShouldPersistTaps="handled">

          <Text style={s.section}>Basic Details</Text>
          <View style={s.card}>
            <Text style={s.ro}>
              {user?.name} {(user as any)?.employee_code ? `· Code ${(user as any).employee_code}` : ""}
              {(user as any)?.department ? ` · ${(user as any).department}` : ""}
              {(user as any)?.designation ? ` · ${(user as any).designation}` : ""}
            </Text>
            <Text style={s.lbl}>Tour Type</Text>
            <View style={s.chipRow}>
              {TOUR_TYPES.map((t) => (
                <Pressable key={t} style={[s.chip, f.tour_type === t && s.chipOn]}
                  onPress={() => set("tour_type", t)} testID={`tt-${t.replace(/\s+/g, "-")}`}>
                  <Text style={[s.chipT, f.tour_type === t && s.chipTOn]}>{t}</Text>
                </Pressable>
              ))}
            </View>
          </View>

          <Text style={s.section}>Tour Schedule</Text>
          <View style={s.card}>
            <View style={s.row2}>
              <View style={{ flex: 1 }}>
                <Text style={s.lbl}>Start Date</Text>
                <DateField value={f.start_date} onChangeISO={(v: string) => set("start_date", v)} testID="tour-start-date" />
              </View>
              <View style={{ width: 90 }}>
                <Text style={s.lbl}>Time</Text>
                <TextInput value={f.start_time} onChangeText={(v) => set("start_time", v)}
                  placeholder="09:00" style={s.input} testID="tour-start-time" />
              </View>
            </View>
            <View style={s.row2}>
              <View style={{ flex: 1 }}>
                <Text style={s.lbl}>End Date</Text>
                <DateField value={f.end_date} onChangeISO={(v: string) => set("end_date", v)} testID="tour-end-date" />
              </View>
              <View style={{ width: 90 }}>
                <Text style={s.lbl}>Time</Text>
                <TextInput value={f.end_time} onChangeText={(v) => set("end_time", v)}
                  placeholder="18:00" style={s.input} testID="tour-end-time" />
              </View>
            </View>
            <Text style={s.hint}>Total tour days: {String(totalDays)}</Text>
            <Text style={s.lbl}>From Location</Text>
            <TextInput value={f.from_location} onChangeText={(v) => set("from_location", v)}
              placeholder="e.g. Bhilwara" style={s.input} testID="tour-from" placeholderTextColor={colors.onSurfaceTertiary} />
            <Text style={s.lbl}>Destination(s)</Text>
            {dests.map((d, i) => (
              <View key={i} style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
                <TextInput value={d}
                  onChangeText={(v) => setDests((p) => p.map((x, j) => j === i ? v : x))}
                  placeholder={`Destination ${i + 1}`} style={[s.input, { flex: 1 }]}
                  testID={`tour-dest-${i}`} placeholderTextColor={colors.onSurfaceTertiary} />
                {dests.length > 1 ? (
                  <Pressable onPress={() => setDests((p) => p.filter((_, j) => j !== i))} hitSlop={8}>
                    <Ionicons name="close-circle" size={20} color="#DC2626" />
                  </Pressable>
                ) : null}
              </View>
            ))}
            <Pressable style={s.addLink} onPress={() => setDests((p) => [...p, ""])} testID="tour-add-dest">
              <Ionicons name="add" size={14} color={colors.brandPrimary} />
              <Text style={s.addLinkT}>Add another destination</Text>
            </Pressable>
          </View>

          <Text style={s.section}>Business Details</Text>
          <View style={s.card}>
            {[["client_name", "Client / Company Name"], ["contact_person", "Contact Person"],
              ["contact_number", "Contact Number"], ["meeting_purpose", "Meeting Purpose"],
              ["expected_outcome", "Expected Outcome"], ["purpose", "Tour Purpose *"],
              ["remarks", "Remarks"]].map(([k, lbl]) => (
              <View key={k}>
                <Text style={s.lbl}>{lbl}</Text>
                <TextInput value={f[k]} onChangeText={(v) => set(k, v)}
                  style={[s.input, ["meeting_purpose", "expected_outcome", "purpose", "remarks"].includes(k) && s.multiline]}
                  multiline={["meeting_purpose", "expected_outcome", "purpose", "remarks"].includes(k)}
                  keyboardType={k === "contact_number" ? "phone-pad" : "default"}
                  testID={`tour-${k}`} placeholderTextColor={colors.onSurfaceTertiary} />
              </View>
            ))}
          </View>

          <Text style={s.section}>Financial Details</Text>
          <View style={s.card}>
            {[["est_travel", "Estimated Travel Expense"], ["est_food", "Estimated Food Expense"],
              ["est_accommodation", "Estimated Accommodation"], ["est_other", "Other Estimated Expense"]].map(([k, lbl]) => (
              <View key={k} style={s.finRow}>
                <Text style={[s.lbl, { flex: 1, marginTop: 0 }]}>{lbl}</Text>
                <TextInput value={f[k]} onChangeText={(v) => set(k, v.replace(/[^0-9.]/g, ""))}
                  keyboardType="decimal-pad" placeholder="0" style={[s.input, { width: 110, marginTop: 0 }]}
                  testID={`tour-${k}`} placeholderTextColor={colors.onSurfaceTertiary} />
              </View>
            ))}
            <Text style={[s.hint, { fontWeight: "800" }]}>Total Estimated: ₹{totalEst.toFixed(2)}</Text>
            <View style={s.finRow}>
              <Text style={[s.lbl, { flex: 1, marginTop: 0 }]}>Advance Required</Text>
              <Switch value={!!f.advance_required} onValueChange={(v) => set("advance_required", v)}
                trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }} testID="tour-advance" />
            </View>
            {f.advance_required ? (
              <View style={s.finRow}>
                <Text style={[s.lbl, { flex: 1, marginTop: 0 }]}>Advance Amount</Text>
                <TextInput value={f.advance_amount} onChangeText={(v) => set("advance_amount", v.replace(/[^0-9.]/g, ""))}
                  keyboardType="decimal-pad" placeholder="0" style={[s.input, { width: 110, marginTop: 0 }]}
                  testID="tour-advance-amount" placeholderTextColor={colors.onSurfaceTertiary} />
              </View>
            ) : null}
          </View>

          <Text style={s.section}>Attendance (On-Duty)</Text>
          <View style={s.card}>
            <View style={s.finRow}>
              <Text style={[s.lbl, { flex: 1, marginTop: 0 }]}>Mark tour days as OD attendance</Text>
              <Switch value={!!f.mark_od} onValueChange={(v) => set("mark_od", v)}
                trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }} testID="tour-mark-od" />
            </View>
            {f.mark_od ? (
              <>
                <View style={s.chipRow}>
                  {[["full", "Full Day"], ["half", "Half Day"]].map(([k, lbl]) => (
                    <Pressable key={k} style={[s.chip, f.od_day_type === k && s.chipOn]}
                      onPress={() => set("od_day_type", k)} testID={`od-${k}`}>
                      <Text style={[s.chipT, f.od_day_type === k && s.chipTOn]}>{lbl}</Text>
                    </Pressable>
                  ))}
                </View>
                <Text style={s.hint}>
                  OD / TOUR attendance is posted ONLY after final approval —
                  {f.start_date && f.end_date ? ` ${f.start_date} → ${f.end_date} → OD → ${f.od_day_type === "half" ? "Half" : "Full"} Day` : " select dates to preview"}
                </Text>
              </>
            ) : null}
          </View>

          <Text style={s.section}>Attachments</Text>
          <View style={s.card}>
            <View style={s.chipRow}>
              {ATT_KINDS.map((k) => (
                <Pressable key={k} style={s.chip} onPress={() => pickFile(k, false)} testID={`att-${k.replace(/\s+/g, "-")}`}>
                  <Ionicons name="attach" size={13} color={colors.onSurfaceSecondary} />
                  <Text style={s.chipT}>{k}</Text>
                </Pressable>
              ))}
            </View>
            {files.map((file, i) => (
              <View key={i} style={s.fileRow}>
                <Ionicons name="document-outline" size={15} color={colors.brandPrimary} />
                <Text style={[s.hint, { flex: 1 }]} numberOfLines={1}>{file.kind} · {file.name}</Text>
                <Pressable onPress={() => setFiles((p) => p.filter((_, j) => j !== i))} hitSlop={8}>
                  <Ionicons name="close-circle" size={17} color="#DC2626" />
                </Pressable>
              </View>
            ))}
          </View>

          <View style={{ flexDirection: "row", gap: 10, marginTop: 16 }}>
            <Pressable style={[s.btnO, saving !== "" && { opacity: 0.6 }]} disabled={saving !== ""}
              onPress={() => save(false)} testID="tour-save-draft">
              {saving === "draft" ? <ActivityIndicator size="small" color={colors.brandPrimary} />
                : <Text style={s.btnOT}>Save Draft</Text>}
            </Pressable>
            <Pressable style={[s.btnP, saving !== "" && { opacity: 0.6 }]} disabled={saving !== ""}
              onPress={() => save(true)} testID="tour-submit">
              {saving === "submit" ? <ActivityIndicator size="small" color="#fff" />
                : <Text style={s.btnPT}>Submit for Approval</Text>}
            </Pressable>
          </View>
          <View style={{ height: 50 }} />
        </ScrollView>
      </KeyboardAvoidingView>
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
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 1 },
  body: { padding: 16, width: "100%", maxWidth: 760, alignSelf: "center" },
  section: { fontSize: 12.5, fontWeight: "800", color: colors.onSurfaceTertiary, textTransform: "uppercase", marginTop: 14, marginBottom: 6 },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: colors.border },
  ro: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  lbl: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 10, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 10,
    paddingVertical: 9, fontSize: 13.5, color: colors.onSurface, backgroundColor: colors.surface, marginTop: 2,
  },
  multiline: { minHeight: 60, textAlignVertical: "top" },
  hint: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 8 },
  row2: { flexDirection: "row", gap: 10, marginTop: 4 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 12, height: 34,
    borderRadius: 17, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    justifyContent: "center",
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipT: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTOn: { color: "#fff" },
  finRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10 },
  addLink: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 8 },
  addLinkT: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  fileRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8 },
  btnO: {
    flex: 1, height: 46, borderRadius: 12, borderWidth: 1.5, borderColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  btnOT: { color: colors.brandPrimary, fontWeight: "800", fontSize: 13.5 },
  btnP: { flex: 1.4, height: 46, borderRadius: 12, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  btnPT: { color: "#fff", fontWeight: "800", fontSize: 13.5 },
});
