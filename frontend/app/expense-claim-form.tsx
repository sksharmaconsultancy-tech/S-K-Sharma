/**
 * Iter 605 — Expense Claims Phase 2: claim submission form.
 * Receipt upload (camera/gallery on native, file picker on web) with
 * AI OCR auto-fill (employee always confirms), grouped category picker,
 * save draft / save & submit with duplicate confirmation.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Modal, Platform, KeyboardAvoidingView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";
import * as ImagePicker from "expo-image-picker";

import { api } from "@/src/api/client";
import { colors } from "@/src/theme";
import { confirmYesNo } from "@/src/utils/confirm";
import DateField from "@/src/components/DateField";

type PendingFile = { file_name: string; mime: string; data_b64: string };
const PAY_MODES = ["Cash", "UPI", "Card", "Bank"];

export default function ExpenseClaimForm() {
  const router = useRouter();
  const { claim_id } = useLocalSearchParams<{ claim_id?: string }>();
  const editing = !!claim_id;

  const [cats, setCats] = useState<any[]>([]);
  const [catOpen, setCatOpen] = useState(false);
  const [form, setForm] = useState<any>({
    expense_date: "", category_id: "", category_name: "", vendor: "",
    invoice_no: "", amount: "", gst_amount: "", payment_mode: "Cash",
    description: "",
  });
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [existingAtts, setExistingAtts] = useState<any[]>([]);
  const [ocr, setOcr] = useState<any>(null);
  const [ocrBusy, setOcrBusy] = useState(false);
  const [saving, setSaving] = useState<"" | "draft" | "submit">("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/expense/categories").then((r) => setCats(r.categories || [])).catch(() => {});
    if (claim_id) {
      api(`/expense/claims/${claim_id}`).then((r) => {
        const c = r.claim || {};
        setForm({
          expense_date: c.expense_date || "", category_id: c.category_id || "",
          category_name: c.category_name || "", vendor: c.vendor || "",
          invoice_no: c.invoice_no || "", amount: String(c.amount ?? ""),
          gst_amount: String(c.gst_amount ?? ""), payment_mode: c.payment_mode || "Cash",
          description: c.description || "",
        });
        setExistingAtts(c.attachments || []);
      }).catch(() => setErr("Could not load claim"));
    }
  }, [claim_id]);

  const set = (k: string, v: any) => setForm((p: any) => ({ ...p, [k]: v }));

  const runOcr = useCallback(async (b64: string) => {
    setOcrBusy(true); setOcr(null);
    try {
      const r = await api("/expense/ocr", { method: "POST", body: { image_b64: b64 } });
      setOcr(r.extracted || {});
    } catch { setOcr({ _failed: true }); }
    finally { setOcrBusy(false); }
  }, []);

  const addFile = useCallback((f: PendingFile) => {
    setFiles((p) => [...p, f]);
    if (f.mime === "image/jpeg" || f.mime === "image/png") runOcr(f.data_b64);
  }, [runOcr]);

  const pickWeb = () => {
    const input = (globalThis as any).document?.createElement?.("input");
    if (!input) return;
    input.type = "file";
    input.accept = "image/png,image/jpeg,application/pdf";
    input.onchange = (e: any) => {
      const file = e.target?.files?.[0];
      if (!file) return;
      if (file.size > 5 * 1024 * 1024) { setErr("File too large (max 5 MB)"); return; }
      const reader = new (globalThis as any).FileReader();
      reader.onload = () => {
        const data = String(reader.result || "").split(",")[1] || "";
        addFile({ file_name: file.name, mime: file.type, data_b64: data });
      };
      reader.readAsDataURL(file);
    };
    input.click();
  };

  const pickNative = async (camera: boolean) => {
    try {
      if (camera) {
        const perm = await ImagePicker.requestCameraPermissionsAsync();
        if (!perm.granted) { setErr("Camera permission needed to photograph the receipt"); return; }
      }
      const res = camera
        ? await ImagePicker.launchCameraAsync({ quality: 0.7, base64: true })
        : await ImagePicker.launchImageLibraryAsync({ quality: 0.7, base64: true });
      const a = res.assets?.[0];
      if (!a?.base64) return;
      addFile({
        file_name: a.fileName || `receipt_${Date.now()}.jpg`,
        mime: a.mimeType === "image/png" ? "image/png" : "image/jpeg",
        data_b64: a.base64,
      });
    } catch { setErr("Could not pick image"); }
  };

  const applyOcr = () => {
    if (!ocr) return;
    setForm((p: any) => ({
      ...p,
      vendor: ocr.vendor || p.vendor,
      invoice_no: ocr.invoice_no || p.invoice_no,
      expense_date: ocr.invoice_date || p.expense_date,
      amount: ocr.total_amount != null && ocr.total_amount !== 0 ? String(ocr.total_amount) : p.amount,
      gst_amount: ocr.gst_amount != null && ocr.gst_amount !== 0 ? String(ocr.gst_amount) : p.gst_amount,
    }));
    setOcr(null);
  };

  const save = async (thenSubmit: boolean) => {
    setErr("");
    const amount = parseFloat(form.amount);
    if (!amount || amount <= 0) { setErr("Enter a valid amount"); return; }
    if (!form.category_id) { setErr("Select a category"); return; }
    if (!form.expense_date) { setErr("Select the expense date"); return; }
    setSaving(thenSubmit ? "submit" : "draft");
    try {
      const body = {
        ...form, amount, gst_amount: parseFloat(form.gst_amount) || 0,
      };
      let id = claim_id as string;
      if (editing) {
        await api(`/expense/claims/${id}`, { method: "PUT", body });
      } else {
        const r = await api("/expense/claims", {
          method: "POST",
          body: { ...body, client_txn_id: `web_${Date.now()}_${Math.random().toString(36).slice(2, 8)}` },
        });
        id = r.claim?.claim_id || r.claim_id;
      }
      for (const f of files) {
        await api(`/expense/claims/${id}/attachments`, { method: "POST", body: f });
      }
      if (thenSubmit) {
        try {
          await api(`/expense/claims/${id}/submit`, { method: "POST", body: {} });
        } catch (e: any) {
          const t = String(e?.message || e);
          if (t.toLowerCase().includes("duplicate")) {
            const yes = await confirmYesNo(
              "This looks like a duplicate of an earlier claim (same date & amount or same invoice). Submit anyway?",
              "Possible duplicate");
            if (yes) await api(`/expense/claims/${id}/submit`, { method: "POST", body: { confirm_duplicate: true } });
          } else throw e;
        }
      }
      router.replace("/my-expenses" as any);
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally { setSaving(""); }
  };

  const groups: Record<string, any[]> = {};
  cats.forEach((c) => { (groups[c.group] = groups[c.group] || []).push(c); });

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={{ padding: 4 }}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>{editing ? "Edit Claim" : "New Expense Claim"}</Text>
          <Text style={s.subtitle}>Attach receipt · AI fills the details for you</Text>
        </View>
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={s.body} keyboardShouldPersistTaps="handled">
          {/* Receipt section */}
          <Text style={s.secTitle}>Receipt</Text>
          <View style={s.fileRow}>
            {Platform.OS === "web" ? (
              <Pressable style={s.fileBtn} onPress={pickWeb} testID="exp-pick-file">
                <Ionicons name="cloud-upload-outline" size={18} color={colors.brandPrimary} />
                <Text style={s.fileBtnTxt}>Upload receipt (photo / PDF)</Text>
              </Pressable>
            ) : (
              <>
                <Pressable style={s.fileBtn} onPress={() => pickNative(true)}>
                  <Ionicons name="camera-outline" size={18} color={colors.brandPrimary} />
                  <Text style={s.fileBtnTxt}>Camera</Text>
                </Pressable>
                <Pressable style={s.fileBtn} onPress={() => pickNative(false)}>
                  <Ionicons name="images-outline" size={18} color={colors.brandPrimary} />
                  <Text style={s.fileBtnTxt}>Gallery</Text>
                </Pressable>
              </>
            )}
          </View>
          {existingAtts.map((a) => (
            <View key={a.doc_id} style={s.fileItem}>
              <Ionicons name="document-attach-outline" size={15} color={colors.onSurfaceTertiary} />
              <Text style={s.fileItemTxt}>{a.file_name} (uploaded)</Text>
            </View>
          ))}
          {files.map((f, i) => (
            <View key={i} style={s.fileItem}>
              <Ionicons name="document-attach-outline" size={15} color={colors.brandPrimary} />
              <Text style={s.fileItemTxt}>{f.file_name}</Text>
              <Pressable onPress={() => setFiles((p) => p.filter((_, j) => j !== i))} hitSlop={8}>
                <Ionicons name="close-circle" size={17} color="#DC2626" />
              </Pressable>
            </View>
          ))}

          {ocrBusy ? (
            <View style={s.ocrBox}>
              <ActivityIndicator size="small" color={colors.brandPrimary} />
              <Text style={s.ocrTxt}>AI is reading your receipt…</Text>
            </View>
          ) : null}
          {ocr && !ocr._failed ? (
            <View style={s.ocrBox} testID="exp-ocr-result">
              <View style={{ flex: 1 }}>
                <Text style={[s.ocrTxt, { fontWeight: "800" }]}>AI found on receipt:</Text>
                <Text style={s.ocrTxt}>
                  {ocr.vendor ? `Vendor: ${ocr.vendor}\n` : ""}
                  {ocr.invoice_no ? `Invoice: ${ocr.invoice_no}\n` : ""}
                  {ocr.invoice_date ? `Date: ${ocr.invoice_date}\n` : ""}
                  {ocr.total_amount ? `Total: ₹${ocr.total_amount}` : ""}
                  {ocr.gst_amount ? ` · GST: ₹${ocr.gst_amount}` : ""}
                </Text>
              </View>
              <Pressable style={s.ocrApply} onPress={applyOcr} testID="exp-ocr-apply">
                <Text style={{ color: "#fff", fontWeight: "800", fontSize: 12 }}>Auto-fill</Text>
              </Pressable>
              <Pressable onPress={() => setOcr(null)} hitSlop={8}>
                <Ionicons name="close" size={18} color={colors.onSurfaceTertiary} />
              </Pressable>
            </View>
          ) : null}
          {ocr?._failed ? <Text style={s.err}>AI could not read the receipt — please fill details manually.</Text> : null}

          {/* Details */}
          <Text style={s.secTitle}>Details</Text>
          <Text style={s.lbl}>Expense date *</Text>
          <DateField value={form.expense_date} onChangeISO={(iso) => set("expense_date", iso)} />

          <Text style={s.lbl}>Category *</Text>
          <Pressable style={s.select} onPress={() => setCatOpen(true)} testID="exp-cat-open">
            <Text style={[s.selectTxt, !form.category_name && { color: colors.onSurfaceTertiary }]}>
              {form.category_name || "Select category"}
            </Text>
            <Ionicons name="chevron-down" size={16} color={colors.onSurfaceTertiary} />
          </Pressable>

          <View style={s.row2}>
            <View style={{ flex: 1 }}>
              <Text style={s.lbl}>Amount (₹) *</Text>
              <TextInput style={s.input} value={form.amount} keyboardType="decimal-pad"
                onChangeText={(t) => set("amount", t)} placeholder="0.00"
                placeholderTextColor={colors.onSurfaceTertiary} testID="exp-amount" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.lbl}>GST (₹)</Text>
              <TextInput style={s.input} value={form.gst_amount} keyboardType="decimal-pad"
                onChangeText={(t) => set("gst_amount", t)} placeholder="0.00"
                placeholderTextColor={colors.onSurfaceTertiary} />
            </View>
          </View>

          <Text style={s.lbl}>Vendor / Merchant</Text>
          <TextInput style={s.input} value={form.vendor} onChangeText={(t) => set("vendor", t)}
            placeholder="e.g. Hotel Rajmahal" placeholderTextColor={colors.onSurfaceTertiary} testID="exp-vendor" />

          <Text style={s.lbl}>Invoice / Bill no.</Text>
          <TextInput style={s.input} value={form.invoice_no} onChangeText={(t) => set("invoice_no", t)}
            placeholder="Optional" placeholderTextColor={colors.onSurfaceTertiary} />

          <Text style={s.lbl}>Paid via</Text>
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            {PAY_MODES.map((m) => (
              <Pressable key={m} onPress={() => set("payment_mode", m)}
                style={[s.mode, form.payment_mode === m && s.modeOn]}>
                <Text style={[s.modeTxt, form.payment_mode === m && { color: "#fff" }]}>{m}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={s.lbl}>Description / Purpose</Text>
          <TextInput style={[s.input, { minHeight: 70, textAlignVertical: "top" }]} multiline
            value={form.description} onChangeText={(t) => set("description", t)}
            placeholder="e.g. Client visit to Bhilwara site" placeholderTextColor={colors.onSurfaceTertiary} />

          {err ? <Text style={s.err}>{err}</Text> : null}

          <View style={{ flexDirection: "row", gap: 10, marginTop: 16 }}>
            <Pressable style={[s.saveBtn, s.saveDraft]} disabled={!!saving} onPress={() => save(false)} testID="exp-save-draft">
              {saving === "draft" ? <ActivityIndicator size="small" color={colors.onSurface} /> :
                <Text style={[s.saveTxt, { color: colors.onSurface }]}>Save draft</Text>}
            </Pressable>
            <Pressable style={[s.saveBtn, { backgroundColor: colors.brandPrimary }]} disabled={!!saving}
              onPress={() => save(true)} testID="exp-save-submit">
              {saving === "submit" ? <ActivityIndicator size="small" color="#fff" /> :
                <Text style={s.saveTxt}>Save &amp; Submit</Text>}
            </Pressable>
          </View>
          <View style={{ height: 60 }} />
        </ScrollView>
      </KeyboardAvoidingView>

      {/* Category picker modal */}
      <Modal visible={catOpen} transparent animationType="fade" onRequestClose={() => setCatOpen(false)}>
        <Pressable style={s.modalBg} onPress={() => setCatOpen(false)}>
          <Pressable style={s.modalCard} onPress={() => {}}>
            <Text style={s.modalTitle}>Select category</Text>
            <ScrollView style={{ maxHeight: 420 }}>
              {Object.entries(groups).map(([g, list]) => (
                <View key={g}>
                  <Text style={s.groupHdr}>{g}</Text>
                  {list.map((c) => (
                    <Pressable key={c.category_id} style={s.catRow}
                      onPress={() => { set("category_id", c.category_id); set("category_name", `${c.group} · ${c.name}`); setCatOpen(false); }}
                      testID={`exp-cat-${c.name}`}>
                      <Text style={s.catTxt}>{c.name}</Text>
                      {form.category_id === c.category_id ?
                        <Ionicons name="checkmark" size={16} color={colors.brandPrimary} /> : null}
                    </Pressable>
                  ))}
                </View>
              ))}
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceTertiary },
  body: { padding: 16 },
  secTitle: {
    fontSize: 12, fontWeight: "800", color: colors.onSurfaceTertiary,
    textTransform: "uppercase", marginTop: 14, marginBottom: 8,
  },
  fileRow: { flexDirection: "row", gap: 10, flexWrap: "wrap" },
  fileBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1.5, borderColor: colors.brandPrimary, borderStyle: "dashed",
    borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, minHeight: 46,
    backgroundColor: colors.surface,
  },
  fileBtnTxt: { color: colors.brandPrimary, fontWeight: "800", fontSize: 13 },
  fileItem: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 6 },
  fileItemTxt: { flex: 1, fontSize: 12.5, color: colors.onSurfaceSecondary },
  ocrBox: {
    flexDirection: "row", alignItems: "center", gap: 10, marginTop: 8,
    backgroundColor: "#EFF6FF", borderRadius: 12, padding: 12,
    borderWidth: 1, borderColor: "#BFDBFE",
  },
  ocrTxt: { fontSize: 12.5, color: "#1E40AF", lineHeight: 18 },
  ocrApply: {
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 8,
  },
  lbl: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 12, marginBottom: 5 },
  input: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10,
    fontSize: 14, color: colors.onSurface, minHeight: 44,
  },
  select: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 10, paddingHorizontal: 12, minHeight: 44,
  },
  selectTxt: { fontSize: 14, color: colors.onSurface },
  row2: { flexDirection: "row", gap: 12 },
  mode: {
    borderRadius: 999, paddingHorizontal: 16, paddingVertical: 9,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, minHeight: 40,
  },
  modeOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  modeTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  err: { color: "#DC2626", fontSize: 12.5, fontWeight: "700", marginTop: 10 },
  saveBtn: {
    flex: 1, borderRadius: 12, minHeight: 48,
    alignItems: "center", justifyContent: "center",
  },
  saveDraft: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  saveTxt: { color: "#fff", fontWeight: "800", fontSize: 14 },
  modalBg: {
    flex: 1, backgroundColor: "rgba(15,23,42,.5)",
    alignItems: "center", justifyContent: "center", padding: 20,
  },
  modalCard: {
    backgroundColor: colors.surface, borderRadius: 16, padding: 16,
    width: "100%", maxWidth: 420,
  },
  modalTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  groupHdr: {
    fontSize: 11, fontWeight: "800", color: colors.onSurfaceTertiary,
    textTransform: "uppercase", marginTop: 10, marginBottom: 2,
  },
  catRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 11, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  catTxt: { fontSize: 13.5, color: colors.onSurface },
});
