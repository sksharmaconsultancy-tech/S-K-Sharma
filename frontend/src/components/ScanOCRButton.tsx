/**
 * Iter 89 — Reusable "Scan with OCR" button + preview modal.
 *
 * Opens a native file picker (web only), uploads the image to
 * POST /api/admin/ocr/parse-document, then shows the extracted fields
 * in a review modal. The parent supplies a mapping of `fields` back
 * into the target form via the `onApply` callback.
 *
 * Usage:
 *   <ScanOCRButton
 *      documentType="aadhaar"
 *      onApply={(fields) => setForm(prev => ({ ...prev, ...fields }))}
 *   />
 */
import React, { useState } from "react";
import {
  View, Text, Pressable, StyleSheet, Modal, ScrollView,
  ActivityIndicator, Platform, TextInput,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius, spacing, type } from "@/src/theme";


type Fields = Record<string, string | null | undefined>;

const DOC_LABELS: Record<string, string> = {
  aadhaar: "Aadhaar card",
  pan: "PAN card (individual)",
  voter: "Voter ID",
  passport: "Passport",
  driving_license: "Driving License",
  firm_pan: "Firm PAN card",
  firm_compliance: "Firm compliance certificate",
  bank_passbook: "Bank Passbook / Cheque",
  educational_certificate: "Educational Certificate",
  disability_certificate: "Disability Certificate",
  caste_certificate: "Caste / Tribe Certificate",
  generic: "Any document",
};

/**
 * Iter 90 — Extended Manual Fill fields catalogue.
 *
 * Field entries are (key, label, group). Groups let us render clean
 * section headers in the Manual Fill panel so admin doesn't scroll
 * through 30 unrelated inputs.
 *
 * Field VISIBILITY is now document-type-aware: pass a `documentType` and
 * only the fields relevant to that document render. `generic` shows all
 * groups so it can be used as a catch-all scan.
 */
type ManualField = {
  key: string;
  label: string;
  group: "Identity" | "Demographic" | "Family" | "Address & Contact" | "Bank" | "Certificate";
  hint?: string;
};

const MANUAL_CATALOG: ManualField[] = [
  // Identity
  { key: "name", label: "Name", group: "Identity" },
  { key: "father_name", label: "Father's Name", group: "Family" },
  { key: "mother_name", label: "Mother's Name", group: "Family" },
  { key: "spouse_name", label: "Spouse's Name", group: "Family" },
  { key: "dob", label: "Date of Birth", group: "Identity", hint: "DD-MM-YYYY" },
  { key: "gender", label: "Gender", group: "Demographic", hint: "male / female / other" },
  { key: "aadhaar_no", label: "Aadhaar Number", group: "Identity", hint: "12 digits" },
  { key: "pan_no", label: "PAN Number", group: "Identity", hint: "ABCDE1234F" },
  { key: "voter_id", label: "Voter ID (EPIC)", group: "Identity" },
  { key: "dl_no", label: "Driving License No.", group: "Identity" },
  { key: "passport_no", label: "Passport No.", group: "Identity" },

  // Demographic (Iter 90)
  { key: "blood_group", label: "Blood Group", group: "Demographic", hint: "A+, B-, O+, AB+..." },
  { key: "marital_status", label: "Marital Status", group: "Demographic", hint: "Single / Married / Divorced / Widowed" },
  { key: "religion", label: "Religion", group: "Demographic", hint: "Hindu / Muslim / Christian / Sikh / Jain / Buddhist / Parsi / Other" },
  { key: "category", label: "Category (GEN/OBC/SC/ST/EWS)", group: "Demographic" },
  { key: "caste", label: "Caste", group: "Demographic" },
  { key: "sub_caste", label: "Sub-caste / Gotra", group: "Demographic" },
  { key: "tribe", label: "Tribe (if applicable)", group: "Demographic" },
  { key: "disability_status", label: "Disability Status", group: "Demographic", hint: "Yes / No / describe" },
  { key: "disability_percent", label: "Disability %", group: "Demographic", hint: "0–100" },

  // Family
  { key: "family_members", label: "Family Members (list)", group: "Family" },

  // Address & Contact
  { key: "present_address", label: "Present Address", group: "Address & Contact" },
  { key: "permanent_address", label: "Permanent Address", group: "Address & Contact" },
  { key: "mobile", label: "Mobile", group: "Address & Contact" },
  { key: "alternate_mobile", label: "Alternate Mobile", group: "Address & Contact" },
  { key: "emergency_contact", label: "Emergency Contact", group: "Address & Contact" },

  // Bank
  { key: "bank_account_number", label: "Bank Account Number", group: "Bank" },
  { key: "bank_name", label: "Bank Name", group: "Bank" },
  { key: "ifsc_code", label: "IFSC Code", group: "Bank", hint: "e.g. HDFC0000123" },
  { key: "name_as_per_bank", label: "Name as per Bank", group: "Bank" },

  // Certificate-specific
  { key: "certificate_no", label: "Certificate Number", group: "Certificate" },
  { key: "issued_by", label: "Issuing Authority", group: "Certificate" },
  { key: "issued_on", label: "Issue Date (DD-MM-YYYY)", group: "Certificate" },
];

// Which groups are relevant for each documentType. Anything not listed
// falls back to the "generic" set (all groups).
const GROUPS_BY_DOC: Record<string, ManualField["group"][]> = {
  aadhaar:            ["Identity", "Demographic", "Family", "Address & Contact"],
  pan:                ["Identity", "Family"],
  voter:              ["Identity", "Family", "Address & Contact"],
  passport:           ["Identity", "Family", "Address & Contact"],
  driving_license:    ["Identity", "Family", "Address & Contact"],
  bank_passbook:      ["Identity", "Bank"],
  educational_certificate: ["Identity", "Family", "Certificate"],
  disability_certificate:  ["Identity", "Demographic", "Certificate"],
  caste_certificate:       ["Identity", "Demographic", "Certificate"],
  firm_pan:           ["Identity"],
  firm_compliance:    ["Identity", "Certificate"],
  generic:            ["Identity", "Demographic", "Family", "Address & Contact", "Bank", "Certificate"],
};


export default function ScanOCRButton({
  documentType = "generic",
  label,
  onApply,
  compact = false,
}: {
  documentType?: keyof typeof DOC_LABELS;
  label?: string;
  onApply: (fields: Fields) => void;
  compact?: boolean;
}) {
  const [modalOpen, setModalOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  // Iter 91 — multi-page support: up to 2 uploads (front/back photos or a
  // PDF). PDFs are rasterised server-side.
  const [pages, setPages] = useState<{ data: string; mime: string; name: string }[]>([]);
  const [result, setResult] = useState<any>(null);
  const [hint, setHint] = useState("");
  // Iter 89 — Manual Fill fallback. Admin can switch to a plain field
  // form when the LLM parse comes back empty / unreliable, using the
  // raw OCR text as a reference on the same screen.
  const [manualMode, setManualMode] = useState(false);
  const [manual, setManual] = useState<Fields>({});

  const MAX_UPLOADS = 2;

  const pickFile = (append: boolean) => {
    if (Platform.OS !== "web") return;
    const input = (globalThis as any).document?.createElement?.("input");
    if (!input) return;
    input.type = "file";
    input.accept = "image/png,image/jpeg,image/webp,application/pdf";
    input.multiple = true;
    input.onchange = (e: any) => {
      const files: File[] = Array.from(e?.target?.files || []);
      if (!files.length) return;
      const room = MAX_UPLOADS - (append ? pages.length : 0);
      const selected = files.slice(0, Math.max(room, 0));
      if (!selected.length) {
        window.alert(`Maximum ${MAX_UPLOADS} pages per scan.`);
        return;
      }
      let pending = selected.length;
      const loaded: { data: string; mime: string; name: string }[] = [];
      for (const file of selected) {
        if (file.size > 6 * 1024 * 1024) {
          window.alert(`"${file.name}" is over 6 MB — please resize/compress it.`);
          pending -= 1;
          continue;
        }
        const reader = new (globalThis as any).FileReader();
        reader.onloadend = () => {
          loaded.push({
            data: reader.result as string,
            mime: file.type || "image/jpeg",
            name: file.name,
          });
          pending -= 1;
          if (pending <= 0 && loaded.length) {
            setPages((prev) => (append ? [...prev, ...loaded] : loaded).slice(0, MAX_UPLOADS));
            setResult(null);
            setModalOpen(true);
          }
        };
        reader.readAsDataURL(file);
      }
    };
    input.click();
  };

  const openPicker = () => pickFile(false);
  const removePage = (idx: number) =>
    setPages((prev) => prev.filter((_, i) => i !== idx));

  const runScan = async () => {
    if (!pages.length) return;
    setLoading(true);
    try {
      const r = await api<{
        ok: boolean;
        document_type_detected?: string;
        confidence?: string;
        fields?: Fields;
        raw_text?: string;
        error?: string;
      }>("/admin/ocr/parse-document", {
        method: "POST",
        body: {
          pages: pages.map((p) => ({
            document_base64: p.data,
            mime_type: p.mime,
          })),
          document_type: documentType,
          hint: hint || undefined,
        },
      });
      setResult(r);
    } catch (e: any) {
      window.alert(e?.message || "OCR failed");
    } finally { setLoading(false); }
  };

  const applyAndClose = () => {
    if (manualMode) {
      const filtered: Fields = {};
      for (const [k, v] of Object.entries(manual)) {
        if (v && String(v).trim()) filtered[k] = String(v).trim();
      }
      onApply(filtered);
    } else if (result?.fields) {
      // Strip null values so we don't accidentally clear existing form values.
      const filtered: Fields = {};
      for (const [k, v] of Object.entries(result.fields as Fields)) {
        if (v && String(v).trim()) filtered[k] = String(v).trim();
      }
      onApply(filtered);
    }
    setModalOpen(false);
    setPages([]);
    setResult(null);
    setHint("");
    setManualMode(false);
    setManual({});
  };

  if (Platform.OS !== "web") return null;

  return (
    <>
      <Pressable
        onPress={openPicker}
        style={({ pressed }) => [
          compact ? styles.btnCompact : styles.btn,
          pressed && { opacity: 0.85 },
        ]}
        testID={`ocr-scan-${documentType}`}
      >
        <Ionicons name="scan-outline" size={compact ? 12 : 14} color={colors.brandPrimary} />
        <Text style={compact ? styles.btnCompactTxt : styles.btnTxt}>
          {label || `Scan ${DOC_LABELS[documentType] || "Document"} (OCR)`}
        </Text>
      </Pressable>

      <Modal visible={modalOpen} transparent animationType="fade" onRequestClose={() => setModalOpen(false)}>
        <View style={styles.backdrop}>
          <View style={styles.sheet}>
            <View style={styles.head}>
              <Text style={styles.title}>Scan with OCR — {DOC_LABELS[documentType]}</Text>
              <Pressable onPress={() => setModalOpen(false)} hitSlop={10}>
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </View>

            <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>
              {pages.length ? (
                <View style={styles.pagesRow}>
                  {pages.map((p, idx) => (
                    <View key={idx} style={styles.previewFrame}>
                      <View style={styles.pageBadge}>
                        <Text style={styles.pageBadgeTxt}>
                          {pages.length > 1 ? `Page ${idx + 1}` : "Page 1"}
                        </Text>
                        <Pressable onPress={() => removePage(idx)} hitSlop={8} testID={`ocr-remove-page-${idx}`}>
                          <Ionicons name="close-circle" size={16} color={colors.error} />
                        </Pressable>
                      </View>
                      {p.mime === "application/pdf" ? (
                        <View style={styles.pdfChip}>
                          <Ionicons name="document-text-outline" size={34} color={colors.brandPrimary} />
                          <Text style={styles.pdfChipTxt} numberOfLines={2}>{p.name}</Text>
                          <Text style={styles.pdfChipSub}>PDF — first 3 pages will be read</Text>
                        </View>
                      ) : Platform.OS === "web" ? (
                        // @ts-ignore native web img
                        <img src={p.data} style={{ maxWidth: "100%", maxHeight: 200, objectFit: "contain" }} />
                      ) : null}
                    </View>
                  ))}
                </View>
              ) : null}

              {!result && !manualMode && pages.length < MAX_UPLOADS ? (
                <Pressable
                  onPress={() => pickFile(true)}
                  style={styles.addPageBtn}
                  testID="ocr-add-page"
                >
                  <Ionicons name="add-circle-outline" size={15} color={colors.brandPrimary} />
                  <Text style={styles.addPageTxt}>
                    Add 2nd page / back side (photo or PDF)
                  </Text>
                </Pressable>
              ) : null}

              {!result && !manualMode ? (
                <View style={{ gap: 8 }}>
                  <Text style={styles.lbl}>Optional hint (e.g. &quot;back side&quot; / &quot;colored copy&quot;)</Text>
                  <TextInput
                    value={hint}
                    onChangeText={setHint}
                    placeholder="Extra context for the OCR (optional)"
                    style={styles.input}
                  />
                  <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                    <Pressable
                      onPress={runScan}
                      disabled={loading}
                      style={({ pressed }) => [
                        styles.scanBtn,
                        (loading || pressed) && { opacity: 0.7 },
                      ]}
                      testID="ocr-run-scan"
                    >
                      {loading ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="scan-outline" size={16} color="#FFF" />}
                      <Text style={styles.scanBtnTxt}>{loading ? "Scanning..." : "Run OCR"}</Text>
                    </Pressable>
                    <Pressable
                      onPress={() => setManualMode(true)}
                      style={({ pressed }) => [
                        styles.manualBtn,
                        pressed && { opacity: 0.85 },
                      ]}
                      testID="ocr-switch-manual"
                    >
                      <Ionicons name="create-outline" size={14} color={colors.brandPrimary} />
                      <Text style={styles.manualBtnTxt}>Manual Fill Instead</Text>
                    </Pressable>
                  </View>
                </View>
              ) : manualMode ? (
                <View style={{ gap: 8 }}>
                  <View style={styles.manualCallout}>
                    <Ionicons name="create-outline" size={16} color={colors.brandPrimary} />
                    <Text style={styles.manualCalloutTxt}>
                      Manual Fill — type the fields yourself. Only filled fields are applied to the master.
                    </Text>
                  </View>
                  {/* Iter 90 — Grouped, document-type-aware field catalogue.
                      Only the groups relevant to the current documentType
                      render; use `documentType="generic"` to see them all. */}
                  {(() => {
                    const allowedGroups = GROUPS_BY_DOC[documentType] || GROUPS_BY_DOC.generic;
                    const shown = MANUAL_CATALOG.filter((f) => allowedGroups.includes(f.group));
                    const grouped: Record<string, ManualField[]> = {};
                    for (const f of shown) {
                      (grouped[f.group] = grouped[f.group] || []).push(f);
                    }
                    return allowedGroups.map((g) => (
                      grouped[g]?.length ? (
                        <View key={g} style={{ marginTop: 8 }}>
                          <Text style={styles.groupHeader}>{g}</Text>
                          {grouped[g].map(({ key, label, hint }) => (
                            <View key={key} style={styles.fieldRow}>
                              <Text style={styles.fieldKey}>{label}</Text>
                              <TextInput
                                value={(manual[key] as string) || ""}
                                onChangeText={(v) => setManual({ ...manual, [key]: v })}
                                style={styles.input}
                                placeholder={hint || (result?.raw_text ? "Copy from OCR text below" : "")}
                                placeholderTextColor={colors.onSurfaceTertiary}
                              />
                            </View>
                          ))}
                        </View>
                      ) : null
                    ));
                  })()}
                  {result?.raw_text ? (
                    <View style={styles.rawBlock}>
                      <Text style={styles.rawLbl}>OCR raw text (for reference — copy from here)</Text>
                      <Text style={styles.rawTxt} selectable>{result.raw_text}</Text>
                    </View>
                  ) : null}
                  <Pressable
                    onPress={() => { setManualMode(false); if (!result) setManual({}); }}
                    style={styles.switchBackBtn}
                  >
                    <Ionicons name="arrow-back-outline" size={12} color={colors.brandPrimary} />
                    <Text style={styles.switchBackTxt}>Back to OCR</Text>
                  </Pressable>
                </View>
              ) : result.ok ? (
                <View style={{ gap: 8 }}>
                  <Text style={styles.resultMeta}>
                    Detected: <Text style={styles.strong}>{result.document_type_detected || "unknown"}</Text>
                    {"  ·  "}
                    Confidence: <Text style={styles.strong}>{result.confidence || "n/a"}</Text>
                  </Text>
                  <Text style={styles.lbl}>Extracted fields (edit before applying)</Text>
                  {Object.entries(result.fields || {}).length === 0 ? (
                    <Text style={styles.helpTxt}>No fields extracted. Try another image or &quot;Manual Fill&quot; instead.</Text>
                  ) : (
                    Object.entries(result.fields || {}).map(([key, val]: any) => (
                      <View key={key} style={styles.fieldRow}>
                        <Text style={styles.fieldKey}>{key}</Text>
                        <TextInput
                          value={val == null ? "" : String(val)}
                          onChangeText={(v) => setResult({ ...result, fields: { ...result.fields, [key]: v } })}
                          style={styles.input}
                        />
                      </View>
                    ))
                  )}
                  {result.raw_text ? (
                    <View style={styles.rawBlock}>
                      <Text style={styles.rawLbl}>Raw OCR text (for reference)</Text>
                      <Text style={styles.rawTxt} selectable>{result.raw_text}</Text>
                    </View>
                  ) : null}
                  {/* Iter 89 — Switch to Manual Fill (pre-fills with OCR values) */}
                  <Pressable
                    onPress={() => {
                      // Copy the current OCR fields into the manual form
                      // so admin can tweak without losing what LLM found.
                      const seed: Fields = {};
                      for (const [k, v] of Object.entries(result.fields || {})) {
                        seed[k] = v == null ? "" : String(v);
                      }
                      setManual(seed);
                      setManualMode(true);
                    }}
                    style={styles.switchBackBtn}
                  >
                    <Ionicons name="create-outline" size={12} color={colors.brandPrimary} />
                    <Text style={styles.switchBackTxt}>Fine-tune in Manual Fill mode</Text>
                  </Pressable>
                </View>
              ) : (
                <View style={styles.errBox}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Ionicons name="warning-outline" size={16} color={colors.error} />
                    <Text style={styles.errTxt}>{result.error || "OCR returned no usable data."}</Text>
                  </View>
                  {result.raw_text ? (
                    <View style={{ marginTop: 8 }}>
                      <Text style={[styles.rawLbl, { color: colors.error }]}>OCR raw text — you can copy from here into Manual Fill</Text>
                      <Text style={[styles.rawTxt, { color: colors.onSurface }]} selectable>{result.raw_text}</Text>
                    </View>
                  ) : null}
                  {/* Iter 89 — Prominent Manual Fill CTA when OCR fails */}
                  <Pressable
                    onPress={() => setManualMode(true)}
                    style={styles.manualBtn}
                    testID="ocr-manual-after-fail"
                  >
                    <Ionicons name="create-outline" size={14} color={colors.brandPrimary} />
                    <Text style={styles.manualBtnTxt}>Switch to Manual Fill</Text>
                  </Pressable>
                </View>
              )}
            </ScrollView>

            <View style={styles.footer}>
              <Pressable onPress={() => setModalOpen(false)} style={styles.cancelBtn}>
                <Text style={styles.cancelBtnTxt}>Cancel</Text>
              </Pressable>
              {result?.ok || manualMode ? (
                <Pressable onPress={applyAndClose} style={styles.applyBtn} testID="ocr-apply">
                  <Ionicons name="checkmark-circle-outline" size={16} color="#FFF" />
                  <Text style={styles.applyBtnTxt}>
                    {manualMode ? "Apply Manual Fill" : "Apply to Master"}
                  </Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
}


const styles = StyleSheet.create({
  btn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: radius.pill,
    backgroundColor: "#EEF2FF",
    borderWidth: 1, borderColor: "#C7D2FE",
    alignSelf: "flex-start",
  },
  btnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  btnCompact: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 4,
    borderRadius: radius.pill,
    backgroundColor: "#EEF2FF",
    borderWidth: 1, borderColor: "#C7D2FE",
    alignSelf: "flex-start",
  },
  btnCompactTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 10 },
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(15,23,42,0.55)",
    alignItems: "center", justifyContent: "center",
    padding: spacing.md,
  },
  sheet: {
    width: "100%", maxWidth: 640, maxHeight: "92%",
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    overflow: "hidden",
  },
  head: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  title: { ...type.h4, color: colors.onSurface, flex: 1 },
  previewFrame: {
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md,
    padding: 8,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center",
    flex: 1, minWidth: 180,
  },
  pagesRow: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  pageBadge: {
    flexDirection: "row", alignItems: "center",
    justifyContent: "space-between",
    alignSelf: "stretch", marginBottom: 4,
  },
  pageBadgeTxt: {
    fontSize: 10, fontWeight: "800",
    color: colors.onSurfaceSecondary, textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  pdfChip: { alignItems: "center", gap: 4, paddingVertical: 16 },
  pdfChipTxt: {
    fontSize: 12, fontWeight: "700",
    color: colors.onSurface, textAlign: "center", maxWidth: 170,
  },
  pdfChipSub: { fontSize: 10, color: colors.onSurfaceTertiary },
  addPageBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1, borderColor: "#C7D2FE", borderStyle: "dashed",
    alignSelf: "flex-start",
  },
  addPageTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  lbl: { ...type.label, color: colors.onSurfaceSecondary },
  input: {
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 10, paddingVertical: 8,
    backgroundColor: colors.surface, color: colors.onSurface,
    fontSize: 13, minHeight: 36,
  },
  scanBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 16, paddingVertical: 10,
    borderRadius: radius.pill,
    backgroundColor: colors.brandPrimary,
    alignSelf: "flex-start",
  },
  scanBtnTxt: { color: "#FFF", fontWeight: "700", fontSize: 13 },
  // Iter 89 — Manual Fill fallback controls
  manualBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 14, paddingVertical: 10,
    borderRadius: radius.pill,
    backgroundColor: "#EEF2FF",
    borderWidth: 1, borderColor: "#C7D2FE",
    alignSelf: "flex-start",
    marginTop: 8,
  },
  manualBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  manualCallout: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: 10, borderRadius: radius.sm,
    backgroundColor: colors.brandTertiary,
    borderWidth: 1, borderColor: colors.border,
  },
  manualCalloutTxt: { ...type.caption, color: colors.onBrandTertiary, flex: 1, fontWeight: "600" },
  switchBackBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 4,
    alignSelf: "flex-start",
    marginTop: 6,
  },
  switchBackTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 11 },
  resultMeta: { ...type.caption, color: colors.onSurfaceSecondary },
  strong: { color: colors.onSurface, fontWeight: "700" },
  helpTxt: { ...type.caption, color: colors.onSurfaceTertiary, fontStyle: "italic" },
  fieldRow: { gap: 4 },
  fieldKey: { ...type.label, color: colors.onSurface, fontWeight: "700", textTransform: "capitalize" },
  groupHeader: {
    ...type.label,
    color: colors.brandPrimary,
    fontWeight: "800",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: 4,
    marginTop: 2,
    paddingBottom: 3,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  rawBlock: {
    marginTop: 8,
    padding: 8,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceTertiary,
    borderWidth: 1, borderColor: colors.border,
  },
  rawLbl: { ...type.label, color: colors.onSurfaceSecondary, marginBottom: 4 },
  rawTxt: { fontSize: 11, color: colors.onSurfaceSecondary, fontFamily: Platform.OS === "web" ? "monospace" : undefined, lineHeight: 15 },
  errBox: {
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: "#FCA5A5",
    backgroundColor: "#FEE2E2",
    gap: 6,
  },
  errTxt: { color: colors.error, fontWeight: "700" },
  footer: {
    flexDirection: "row", gap: 8, justifyContent: "flex-end",
    padding: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.divider,
  },
  cancelBtn: {
    paddingHorizontal: 16, paddingVertical: 10,
    borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  cancelBtnTxt: { color: colors.onSurface, fontWeight: "600", fontSize: 13 },
  applyBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 16, paddingVertical: 10,
    borderRadius: radius.pill,
    backgroundColor: colors.success,
  },
  applyBtnTxt: { color: "#FFF", fontWeight: "700", fontSize: 13 },
});
