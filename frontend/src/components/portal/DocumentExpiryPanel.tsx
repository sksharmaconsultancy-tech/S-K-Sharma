// Phase 2 — Document Expiry dashboard panel (tracked statutory
// documents: licenses, registrations, insurance, contracts...).
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, Modal,
  ActivityIndicator, ScrollView, Alert, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

type TDoc = {
  tdoc_id: string; title: string; doc_type: string; company_id?: string | null;
  company_name?: string | null; doc_number?: string | null;
  expiry_date: string; days_left: number; bucket: string; notes?: string | null;
};
type CompanyLite = { company_id: string; name: string };

const BUCKET_UI: Record<string, { label: string; fg: string; bg: string }> = {
  expired: { label: "Expired", fg: "#B91C1C", bg: "#FEF2F2" },
  critical: { label: "≤ 7 days", fg: "#C2410C", bg: "#FFF7ED" },
  warning: { label: "≤ 30 days", fg: "#B45309", bg: "#FFFBEB" },
  upcoming: { label: "≤ 90 days", fg: "#0369A1", bg: "#F0F9FF" },
  ok: { label: "Safe", fg: "#16A34A", bg: "#F0FDF4" },
};
const DOC_TYPES = ["license", "registration", "insurance", "contract", "certificate", "other"];

export default function DocumentExpiryPanel({
  companyId, companies, canPickFirm,
}: { companyId: string | null; companies: CompanyLite[]; canPickFirm: boolean }) {
  const [docs, setDocs] = useState<TDoc[]>([]);
  const [buckets, setBuckets] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    title: "", doc_type: "license", doc_number: "", expiry_date: "",
    company_id: companyId || "", notes: "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = companyId ? `?company_id=${encodeURIComponent(companyId)}` : "";
      const r = await api<{ documents: TDoc[]; buckets: Record<string, number> }>(
        `/admin/tracked-documents${q}`);
      setDocs(r.documents); setBuckets(r.buckets);
    } catch { /* noop */ }
    setLoading(false);
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const createDoc = async () => {
    if (!form.title.trim() || !/^\d{4}-\d{2}-\d{2}$/.test(form.expiry_date)) {
      const msg = "Title and expiry date (YYYY-MM-DD) are required.";
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Missing info", msg);
      return;
    }
    setSaving(true);
    try {
      await api("/admin/tracked-documents", {
        method: "POST",
        body: {
          title: form.title, doc_type: form.doc_type,
          doc_number: form.doc_number || null, expiry_date: form.expiry_date,
          company_id: form.company_id || null, notes: form.notes || null,
        },
      });
      setShowAdd(false);
      setForm({ title: "", doc_type: "license", doc_number: "", expiry_date: "", company_id: companyId || "", notes: "" });
      load();
    } catch (e: any) {
      const msg = e?.message || "Failed to add document";
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Error", msg);
    }
    setSaving(false);
  };

  const removeDoc = async (d: TDoc) => {
    const go = async () => {
      try { await api(`/admin/tracked-documents/${d.tdoc_id}`, { method: "DELETE" }); load(); } catch { /* noop */ }
    };
    if (Platform.OS === "web") {
      if (window.confirm(`Delete "${d.title}"?`)) go();
    } else {
      Alert.alert("Delete document", d.title, [
        { text: "Cancel" }, { text: "Delete", style: "destructive", onPress: go }]);
    }
  };

  return (
    <View testID="pd-documents-panel">
      {/* bucket summary */}
      <View style={st.bucketRow}>
        {Object.entries(BUCKET_UI).map(([k, ui]) => (
          <View key={k} style={[st.bucketCard, { backgroundColor: ui.bg }]}>
            <Text style={[st.bucketVal, { color: ui.fg }]}>{buckets[k] ?? 0}</Text>
            <Text style={[st.bucketLbl, { color: ui.fg }]}>{ui.label}</Text>
          </View>
        ))}
      </View>

      <View style={st.toolbar}>
        <Text style={st.hint}>Track licenses, registrations & contracts with expiry reminders.</Text>
        <Pressable onPress={() => setShowAdd(true)} style={st.addBtn} testID="pd-doc-add">
          <Ionicons name="add" size={15} color="#fff" />
          <Text style={st.addTxt}>Add Document</Text>
        </Pressable>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 24 }} />
      ) : docs.length === 0 ? (
        <Text style={st.dim}>No tracked documents yet. Add licenses/registrations to monitor expiry.</Text>
      ) : (
        docs.map((d) => {
          const ui = BUCKET_UI[d.bucket] || BUCKET_UI.ok;
          return (
            <View key={d.tdoc_id} style={st.docCard} testID={`pd-doc-${d.tdoc_id}`}>
              <View style={[st.typeIcon, { backgroundColor: ui.bg }]}>
                <Ionicons name="document-text-outline" size={16} color={ui.fg} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={st.docTitle} numberOfLines={1}>{d.title}</Text>
                <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap", marginTop: 2 }}>
                  <Text style={st.meta}>{d.doc_type}</Text>
                  {d.company_name ? <Text style={st.meta}>🏢 {d.company_name}</Text> : null}
                  {d.doc_number ? <Text style={st.meta}>#{d.doc_number}</Text> : null}
                </View>
              </View>
              <View style={{ alignItems: "flex-end", gap: 3 }}>
                <Text style={[st.expChip, { color: ui.fg, backgroundColor: ui.bg }]}>
                  {d.days_left < 0 ? `Expired ${Math.abs(d.days_left)}d ago` : `${d.days_left}d left`}
                </Text>
                <Text style={st.meta}>{d.expiry_date}</Text>
              </View>
              <Pressable onPress={() => removeDoc(d)} hitSlop={8} style={{ marginLeft: 4 }}>
                <Ionicons name="trash-outline" size={15} color="#B91C1C" />
              </Pressable>
            </View>
          );
        })
      )}

      {/* Add modal */}
      <Modal visible={showAdd} transparent animationType="fade" onRequestClose={() => setShowAdd(false)}>
        <View style={st.overlay}>
          <View style={st.modal}>
            <Text style={st.modalTitle}>Add Tracked Document</Text>
            <ScrollView style={{ maxHeight: 420 }}>
              <Text style={st.lbl}>Title *</Text>
              <TextInput style={st.input} value={form.title}
                onChangeText={(v) => setForm({ ...form, title: v })}
                placeholder="e.g. Factory License — Bhilwara unit"
                placeholderTextColor={colors.onSurfaceTertiary} testID="pd-doc-title-input" />
              <Text style={st.lbl}>Type</Text>
              <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
                {DOC_TYPES.map((t) => (
                  <Pressable key={t} onPress={() => setForm({ ...form, doc_type: t })}
                    style={[st.chip, form.doc_type === t && st.chipOn]}>
                    <Text style={[st.chipTxt, form.doc_type === t && st.chipTxtOn]}>{t}</Text>
                  </Pressable>
                ))}
              </View>
              <Text style={st.lbl}>Document number</Text>
              <TextInput style={st.input} value={form.doc_number}
                onChangeText={(v) => setForm({ ...form, doc_number: v })}
                placeholder="Optional" placeholderTextColor={colors.onSurfaceTertiary} />
              <Text style={st.lbl}>Expiry date (YYYY-MM-DD) *</Text>
              <TextInput style={st.input} value={form.expiry_date}
                onChangeText={(v) => setForm({ ...form, expiry_date: v })}
                placeholder="2026-12-31" placeholderTextColor={colors.onSurfaceTertiary}
                testID="pd-doc-expiry-input" />
              {canPickFirm ? (
                <>
                  <Text style={st.lbl}>Firm (optional)</Text>
                  <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
                    <Pressable onPress={() => setForm({ ...form, company_id: "" })}
                      style={[st.chip, !form.company_id && st.chipOn]}>
                      <Text style={[st.chipTxt, !form.company_id && st.chipTxtOn]}>None</Text>
                    </Pressable>
                    {companies.map((c) => (
                      <Pressable key={c.company_id}
                        onPress={() => setForm({ ...form, company_id: c.company_id })}
                        style={[st.chip, form.company_id === c.company_id && st.chipOn]}>
                        <Text style={[st.chipTxt, form.company_id === c.company_id && st.chipTxtOn]}
                          numberOfLines={1}>{c.name}</Text>
                      </Pressable>
                    ))}
                  </View>
                </>
              ) : null}
              <Text style={st.lbl}>Notes</Text>
              <TextInput style={[st.input, { height: 56 }]} value={form.notes} multiline
                onChangeText={(v) => setForm({ ...form, notes: v })}
                placeholder="Optional" placeholderTextColor={colors.onSurfaceTertiary} />
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 14 }}>
              <Pressable onPress={() => setShowAdd(false)} style={[st.mBtn, st.mBtnGhost]}>
                <Text style={st.mBtnGhostTxt}>Cancel</Text>
              </Pressable>
              <Pressable onPress={createDoc} disabled={saving}
                style={[st.mBtn, st.mBtnPrimary, saving && { opacity: 0.5 }]} testID="pd-doc-save">
                {saving ? <ActivityIndicator color="#fff" size="small" />
                  : <Text style={st.mBtnPrimaryTxt}>Add Document</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const st = StyleSheet.create({
  dim: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 16, textAlign: "center" },
  bucketRow: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  bucketCard: {
    flex: 1, minWidth: 90, borderRadius: radius.lg, padding: 10, alignItems: "center",
  },
  bucketVal: { fontSize: 19, fontWeight: "800" },
  bucketLbl: { fontSize: 9.5, fontWeight: "700", marginTop: 2 },
  toolbar: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 12, marginBottom: 10 },
  hint: { flex: 1, fontSize: 10.5, color: colors.onSurfaceSecondary },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brandPrimary,
    borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 8,
  },
  addTxt: { fontSize: 11.5, fontWeight: "800", color: "#fff" },
  docCard: {
    flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: colors.surface,
    borderRadius: radius.lg, borderWidth: 1, borderColor: colors.divider, padding: 11,
    marginBottom: 8,
  },
  typeIcon: { width: 32, height: 32, borderRadius: 9, alignItems: "center", justifyContent: "center" },
  docTitle: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  meta: { fontSize: 10, color: colors.onSurfaceSecondary },
  expChip: {
    fontSize: 9.5, fontWeight: "800", borderRadius: 6, overflow: "hidden",
    paddingHorizontal: 7, paddingVertical: 3,
  },
  chip: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: 999,
    paddingHorizontal: 11, paddingVertical: 6, backgroundColor: colors.surface, maxWidth: 180,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  overlay: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.45)", alignItems: "center",
    justifyContent: "center", padding: spacing.md,
  },
  modal: {
    width: "100%", maxWidth: 460, backgroundColor: colors.surface,
    borderRadius: radius.lg, padding: 16,
  },
  modalTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  lbl: { fontSize: 10.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 10, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 12.5, color: colors.onSurface,
    backgroundColor: colors.background,
  },
  mBtn: { flex: 1, borderRadius: radius.md, paddingVertical: 11, alignItems: "center" },
  mBtnGhost: { borderWidth: 1, borderColor: colors.divider },
  mBtnGhostTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  mBtnPrimary: { backgroundColor: colors.brandPrimary },
  mBtnPrimaryTxt: { fontSize: 12.5, fontWeight: "800", color: "#fff" },
});
