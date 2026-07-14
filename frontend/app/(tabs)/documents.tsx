import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Alert,
  Platform,
  Modal,
  TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import * as FileSystemNS from "expo-file-system";
import * as Sharing from "expo-sharing";
import { useFocusEffect } from "@react-navigation/native";

import { api, apiBinary } from "@/src/api/client";
import { colors, radius, spacing, type } from "@/src/theme";
import DateField from "@/src/components/DateField";

const FileSystem: any = FileSystemNS as any;

type Tab = "payslips" | "compliance" | "personal";

type PersonalDoc = {
  doc_id: string;
  category: string;
  custom_label?: string | null;
  filename?: string | null;
  mime_type: string;
  size_bytes?: number | null;
  uploaded_at?: string | null;
  uploaded_via?: string | null;
};

const PERSONAL_CATEGORIES: {
  key: string;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
}[] = [
  { key: "aadhaar", label: "Aadhaar Card", icon: "card-outline" },
  { key: "pan", label: "PAN Card", icon: "card-outline" },
  { key: "passport", label: "Passport", icon: "airplane-outline" },
  { key: "driving_license", label: "Driving License", icon: "car-outline" },
  { key: "bank_passbook", label: "Bank Passbook", icon: "wallet-outline" },
  { key: "educational_certificate", label: "Educational Certificate", icon: "school-outline" },
  { key: "experience_letter", label: "Experience Letter", icon: "briefcase-outline" },
  { key: "offer_letter", label: "Offer Letter", icon: "document-text-outline" },
  { key: "signed_contract", label: "Signed Contract", icon: "reader-outline" },
  { key: "photo", label: "Photo", icon: "image-outline" },
  { key: "other", label: "Other", icon: "document-outline" },
];

function fmtBytes(n: number | null | undefined): string {
  if (!n) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

function personalCatLabel(cat: string, custom?: string | null): string {
  const c = PERSONAL_CATEGORIES.find((x) => x.key === cat);
  if (custom && custom.trim()) return `${c?.label || cat} — ${custom}`;
  return c?.label || cat;
}

export default function DocumentsScreen() {
  const [tab, setTab] = useState<Tab>("payslips");
  const [payslips, setPayslips] = useState<any[]>([]);
  const [docs, setDocs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  const [complianceEnabled, setComplianceEnabled] = useState<boolean>(true);
  const [salaryMonthly, setSalaryMonthly] = useState<number | null>(null);
  const [salaryHistory, setSalaryHistory] = useState<any[]>([]);
  const [currentMonth, setCurrentMonth] = useState<string>("");
  // Iter 74 — Payslip History browser: rolling 12-month year totals.
  const [yearTotals, setYearTotals] = useState<{
    gross: number;
    deductions: number;
    net: number;
    count: number;
    paid_count: number;
  } | null>(null);
  const [payslipDownloading, setPayslipDownloading] = useState<string | null>(null);

  // Personal / self-service documents
  const [personalDocs, setPersonalDocs] = useState<PersonalDoc[]>([]);
  const [personalLoading, setPersonalLoading] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [pickCategory, setPickCategory] = useState<string>("aadhaar");
  const [pickLabel, setPickLabel] = useState<string>("");
  // Iter 86 — as-printed metadata for the scanned document
  const [nameOnDoc, setNameOnDoc] = useState<string>("");
  const [dobOnDoc, setDobOnDoc] = useState<string>("");
  const [fatherNameOnDoc, setFatherNameOnDoc] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, d, s, c, y] = await Promise.all([
        api<{ payslips: any[] }>("/payslips"),
        api<{ docs: any[] }>("/compliance-docs"),
        api<{ salary_monthly: number | null; history: any[]; current_month: string }>(
          "/salary/monthly"
        ).catch(() => ({ salary_monthly: null, history: [], current_month: "" })),
        api<any>("/company").catch(() => null),
        api<{ totals: { gross: number; deductions: number; net: number; count: number; paid_count: number } }>(
          "/me/payslips/year-summary"
        ).catch(() => null),
      ]);
      setPayslips(p.payslips || []);
      setDocs(d.docs || []);
      setSalaryMonthly(s.salary_monthly);
      setSalaryHistory(s.history || []);
      setCurrentMonth(s.current_month || "");
      setYearTotals(y?.totals || null);
      if (c && c.compliance_enabled === false) {
        setComplianceEnabled(false);
        if (tab === "compliance") setTab("payslips");
      } else {
        setComplianceEnabled(true);
      }
    } catch {
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const loadPersonalDocs = useCallback(async () => {
    setPersonalLoading(true);
    try {
      const r = await api<{ documents: PersonalDoc[] }>("/me/documents");
      setPersonalDocs(r.documents || []);
    } catch {
      // Non-fatal — likely no docs yet.
      setPersonalDocs([]);
    } finally {
      setPersonalLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === "personal") loadPersonalDocs();
  }, [tab, loadPersonalDocs]);

  // Iter 72 — Refresh Documents tab on focus so newly-published docs
  // and freshly-uploaded personal papers show up without a hard reload.
  useFocusEffect(
    useCallback(() => {
      load();
      if (tab === "personal") loadPersonalDocs();
    }, [load, loadPersonalDocs, tab]),
  );

  const showMsg = (msg: string, title = "Documents") => {
    if (Platform.OS === "web") globalThis.alert(msg);
    else Alert.alert(title, msg);
  };

  // Iter 74 — Employee self-service payslip PDF download.
  const downloadPayslip = async (p: any) => {
    if (!p?.slip_id || payslipDownloading === p.slip_id) return;
    setPayslipDownloading(p.slip_id);
    try {
      const res = await apiBinary(`/me/payslips/${p.slip_id}.pdf`);
      if (Platform.OS === "web") {
        if (res.webBlobUrl) {
          const a = document.createElement("a");
          a.href = res.webBlobUrl;
          a.download = `Payslip_${p.month}.pdf`;
          a.click();
          setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
        }
      } else {
        const path = `${FileSystem.cacheDirectory}Payslip_${p.month}.pdf`;
        await FileSystem.writeAsStringAsync(path, res.base64, { encoding: "base64" });
        if (await Sharing.isAvailableAsync()) {
          await Sharing.shareAsync(path, {
            mimeType: "application/pdf",
            dialogTitle: `Payslip · ${p.month}`,
          });
        } else {
          showMsg(`Saved to ${path}`);
        }
      }
    } catch (e: any) {
      showMsg(e?.message || "Could not download payslip");
    } finally {
      setPayslipDownloading(null);
    }
  };

  const viewPersonalDoc = async (d: PersonalDoc) => {
    try {
      if (Platform.OS === "web") {
        // Use inline endpoint → browser opens PDF / image directly.
        const res = await apiBinary(`/me/documents/${d.doc_id}?inline=true`);
        if (res.webBlobUrl) window.open(res.webBlobUrl, "_blank");
      } else {
        const j = await api<{ document: { base64: string; mime_type: string; filename: string | null } }>(
          `/me/documents/${d.doc_id}`,
        );
        const ext =
          d.mime_type === "application/pdf"
            ? "pdf"
            : d.mime_type === "image/png"
              ? "png"
              : d.mime_type === "image/webp"
                ? "webp"
                : "jpg";
        const path = `${FileSystem.cacheDirectory}${d.doc_id}.${ext}`;
        await FileSystem.writeAsStringAsync(path, j.document.base64, {
          encoding: "base64",
        });
        if (await Sharing.isAvailableAsync()) {
          await Sharing.shareAsync(path, {
            mimeType: d.mime_type,
            dialogTitle:
              d.filename || personalCatLabel(d.category, d.custom_label),
          });
        } else {
          showMsg(`Saved to ${path}`);
        }
      }
    } catch (e: any) {
      showMsg(e?.message || "Could not open document");
    }
  };

  const uploadPersonalDoc = async (mode: "file" | "camera") => {
    setUploading(true);
    try {
      let fileUri: string;
      let fileMime: string;
      let fileName: string | null = null;
      let fileSize: number | undefined;

      if (mode === "camera") {
        const perm = await ImagePicker.requestCameraPermissionsAsync();
        if (!perm.granted) {
          throw new Error("Camera permission is required to scan a document.");
        }
        const res = await ImagePicker.launchCameraAsync({
          mediaTypes: ImagePicker.MediaTypeOptions.Images,
          quality: 0.7,
          base64: false,
        });
        if (res.canceled || !res.assets?.[0]) {
          setUploading(false);
          return;
        }
        const a = res.assets[0];
        fileUri = a.uri;
        fileMime = a.mimeType || "image/jpeg";
        fileName = a.fileName || `scan_${Date.now()}.jpg`;
        fileSize = a.fileSize;
      } else {
        const res = await DocumentPicker.getDocumentAsync({
          type: ["image/jpeg", "image/jpg", "image/png", "image/webp", "application/pdf"],
          multiple: false,
          copyToCacheDirectory: true,
        });
        if (res.canceled || !res.assets?.[0]) {
          setUploading(false);
          return;
        }
        const a = res.assets[0];
        fileUri = a.uri;
        fileMime =
          a.mimeType ||
          (a.name?.toLowerCase().endsWith(".pdf") ? "application/pdf" : "image/jpeg");
        fileName = a.name;
        fileSize = a.size;
      }

      if (fileSize && fileSize > 10 * 1024 * 1024) {
        throw new Error("File is too large. Max 10 MB per document.");
      }

      let b64: string;
      if (Platform.OS === "web") {
        const resp = await fetch(fileUri);
        const blob = await resp.blob();
        b64 = await new Promise<string>((resolve, reject) => {
          const r = new FileReader();
          r.onload = () => {
            const s = String(r.result || "");
            resolve(s.includes(",") ? s.split(",", 2)[1] : s);
          };
          r.onerror = reject;
          r.readAsDataURL(blob);
        });
      } else {
        b64 = await FileSystem.readAsStringAsync(fileUri, {
          encoding: "base64",
        });
      }

      const upResp = await api<{
        ok: boolean;
        data_mismatch?: boolean;
        mismatched_fields?: string[];
        warning?: string | null;
      }>("/me/documents", {
        method: "POST",
        body: {
          category: pickCategory,
          custom_label: pickLabel || null,
          filename: fileName,
          mime_type: fileMime,
          base64: b64,
          // Iter 86 — as-printed metadata fields
          name_on_doc: nameOnDoc || null,
          dob_on_doc: dobOnDoc || null,
          father_name_on_doc: fatherNameOnDoc || null,
        },
      });
      setUploadOpen(false);
      setPickLabel("");
      setNameOnDoc("");
      setDobOnDoc("");
      setFatherNameOnDoc("");
      await loadPersonalDocs();
      if (upResp?.data_mismatch) {
        showMsg(
          upResp.warning || "Data Not match with Registered Data",
          "Uploaded — mismatch",
        );
      } else {
        showMsg("Document uploaded ✓");
      }
    } catch (e: any) {
      showMsg(e?.message || "Upload failed", "Upload");
    } finally {
      setUploading(false);
    }
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Text style={styles.h1}>Documents</Text>
          <Text style={styles.sub}>Payslips & labour law compliance</Text>
        </View>

        <View style={styles.seg} testID="doc-segments">
          <Pressable
            testID="seg-payslips"
            onPress={() => setTab("payslips")}
            style={[styles.segItem, tab === "payslips" && styles.segItemActive]}
          >
            <Text style={[styles.segTxt, tab === "payslips" && styles.segTxtActive]}>
              Payslips
            </Text>
          </Pressable>
          {complianceEnabled && (
            <Pressable
              testID="seg-compliance"
              onPress={() => setTab("compliance")}
              style={[styles.segItem, tab === "compliance" && styles.segItemActive]}
            >
              <Text style={[styles.segTxt, tab === "compliance" && styles.segTxtActive]}>
                Compliance
              </Text>
            </Pressable>
          )}
          <Pressable
            testID="seg-personal"
            onPress={() => setTab("personal")}
            style={[styles.segItem, tab === "personal" && styles.segItemActive]}
          >
            <Text style={[styles.segTxt, tab === "personal" && styles.segTxtActive]}>
              Personal
            </Text>
          </Pressable>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {tab === "payslips" && salaryMonthly ? (
          <View style={styles.salaryCard} testID="salary-card">
            <View style={styles.salaryTop}>
              <Text style={styles.salaryLabel}>MONTHLY SALARY</Text>
              <Text style={styles.salaryValue}>
                ₹{salaryMonthly.toLocaleString()}
              </Text>
            </View>
            <View style={styles.salaryBreakdown}>
              {salaryHistory.length === 0 ? (
                <Text style={styles.salaryEmpty}>
                  No completed months yet. Your first salary status will appear
                  once the current month ends.
                </Text>
              ) : (
                salaryHistory.map((h: any) => (
                  <View key={h.slip_id} style={styles.salaryRow}>
                    <Text style={styles.salaryMonth}>{h.month}</Text>
                    <Text style={styles.salaryAmt}>
                      ₹{Number(h.net).toLocaleString()}
                    </Text>
                    <View
                      style={[
                        styles.statusChip,
                        h.status === "paid" ? styles.statusPaid : styles.statusPending,
                      ]}
                    >
                      <Text
                        style={
                          h.status === "paid" ? styles.statusPaidTxt : styles.statusPendingTxt
                        }
                      >
                        {h.status === "paid" ? "Paid" : "Pending"}
                      </Text>
                    </View>
                  </View>
                ))
              )}
            </View>
            <Text style={styles.salaryHint}>
              Current month: {currentMonth || "—"} (salary generated at month-end)
            </Text>
          </View>
        ) : null}
        {loading ? (
          <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
        ) : tab === "personal" ? (
          <PersonalDocsSection
            docs={personalDocs}
            loading={personalLoading}
            onOpenUpload={() => setUploadOpen(true)}
            onView={viewPersonalDoc}
          />
        ) : tab === "payslips" ? (
          payslips.length === 0 ? (
            <EmptyState
              icon="cash-outline"
              title="No payslips yet"
              body="Your monthly payslips will appear here once uploaded by HR."
            />
          ) : (
            <>
              {/* Iter 74 — Rolling 12-month year totals */}
              {yearTotals && yearTotals.count > 0 && (
                <View style={styles.yearTotalsCard} testID="year-totals">
                  <Text style={styles.yearTotalsTitle}>
                    Last 12 months · {yearTotals.count} payslip
                    {yearTotals.count === 1 ? "" : "s"}
                  </Text>
                  <View style={styles.yearTotalsRow}>
                    <View style={styles.yearTotalsItem}>
                      <Text style={styles.yearTotalsLabel}>Gross</Text>
                      <Text style={styles.yearTotalsValue}>
                        ₹{Math.round(yearTotals.gross).toLocaleString()}
                      </Text>
                    </View>
                    <View style={styles.yearTotalsItem}>
                      <Text style={styles.yearTotalsLabel}>Deductions</Text>
                      <Text style={styles.yearTotalsValue}>
                        ₹{Math.round(yearTotals.deductions).toLocaleString()}
                      </Text>
                    </View>
                    <View style={styles.yearTotalsItem}>
                      <Text style={styles.yearTotalsLabel}>Net</Text>
                      <Text style={[styles.yearTotalsValue, { color: colors.success }]}>
                        ₹{Math.round(yearTotals.net).toLocaleString()}
                      </Text>
                    </View>
                  </View>
                  {yearTotals.paid_count < yearTotals.count && (
                    <Text style={styles.yearTotalsHint}>
                      {yearTotals.paid_count} paid · {yearTotals.count - yearTotals.paid_count} pending
                    </Text>
                  )}
                </View>
              )}
              {payslips.map((p) => (
                <Pressable
                  key={p.slip_id}
                  style={styles.docRow}
                  testID={`payslip-${p.month}`}
                  onPress={() => downloadPayslip(p)}
                  disabled={payslipDownloading === p.slip_id}
                >
                  <View style={styles.docIcon}>
                    <Ionicons name="receipt-outline" size={20} color={colors.onBrandTertiary} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.docTitle}>Payslip · {p.month}</Text>
                    <Text style={styles.docSub}>
                      Net ₹{p.net?.toLocaleString?.() ?? p.net} · Gross ₹{p.gross?.toLocaleString?.() ?? p.gross}
                    </Text>
                  </View>
                  {payslipDownloading === p.slip_id ? (
                    <ActivityIndicator size="small" color={colors.brandPrimary} />
                  ) : (
                    <Ionicons name="download-outline" size={18} color={colors.brandPrimary} />
                  )}
                </Pressable>
              ))}
            </>
          )
        ) : docs.length === 0 ? (
          <EmptyState
            icon="library-outline"
            title="No documents"
            body="Compliance docs will appear here."
          />
        ) : (
          docs.map((d) => {
            const open = openId === d.doc_id;
            return (
              <Pressable
                key={d.doc_id}
                style={styles.docRow}
                testID={`doc-${d.category}`}
                onPress={() => setOpenId(open ? null : d.doc_id)}
              >
                <View style={styles.docIcon}>
                  <Ionicons name={catIcon(d.category)} size={20} color={colors.onBrandTertiary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.docTitle}>{d.title}</Text>
                  <Text style={styles.docSub} numberOfLines={open ? undefined : 2}>
                    {open ? d.content || d.description : d.description}
                  </Text>
                </View>
                <Ionicons
                  name={open ? "chevron-up" : "chevron-forward"}
                  size={18}
                  color={colors.onSurfaceTertiary}
                />
              </Pressable>
            );
          })
        )}
        <View style={{ height: 60 }} />
      </ScrollView>

      {/* Upload modal — used by the Personal tab */}
      <Modal
        transparent
        visible={uploadOpen}
        animationType="slide"
        onRequestClose={() => setUploadOpen(false)}
      >
        <Pressable
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.35)" }}
          onPress={() => setUploadOpen(false)}
        />
        <View style={uploadStyles.sheet}>
          <View style={uploadStyles.grip} />
          <Text style={uploadStyles.title}>Add scan document</Text>

          <Text style={uploadStyles.label}>Document type</Text>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            style={{ marginBottom: 8 }}
          >
            <View style={{ flexDirection: "row", gap: 6 }}>
              {PERSONAL_CATEGORIES.map((c) => {
                const active = pickCategory === c.key;
                return (
                  <Pressable
                    key={c.key}
                    onPress={() => setPickCategory(c.key)}
                    style={[
                      uploadStyles.chip,
                      active && uploadStyles.chipActive,
                    ]}
                    testID={`up-cat-${c.key}`}
                  >
                    <Ionicons
                      name={c.icon}
                      size={12}
                      color={active ? "#fff" : colors.brandPrimary}
                    />
                    <Text
                      style={[
                        uploadStyles.chipTxt,
                        active && uploadStyles.chipTxtActive,
                      ]}
                    >
                      {c.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </ScrollView>

          <Text style={uploadStyles.label}>Custom label (optional)</Text>
          <TextInput
            testID="up-label"
            value={pickLabel}
            onChangeText={setPickLabel}
            placeholder="e.g. Front side / SSC Marksheet"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={uploadStyles.input}
          />

          {/* Iter 86 — Scanned-doc metadata (mandatory after DOJ + 15 days;
              backend enforces the grace-period check and returns a
              "Data Not match with Registered Data" warning when the
              values differ from the employee master record). */}
          <Text style={uploadStyles.label}>Name (as printed on the document)</Text>
          <TextInput
            testID="up-name-on-doc"
            value={nameOnDoc}
            onChangeText={setNameOnDoc}
            placeholder="Full name exactly as printed"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={uploadStyles.input}
          />
          <Text style={uploadStyles.label}>Date of Birth</Text>
          <DateField value={dobOnDoc} onChangeISO={setDobOnDoc} testID="up-dob-on-doc" />
          <Text style={uploadStyles.label}>Father Name (as printed)</Text>
          <TextInput
            testID="up-father-on-doc"
            value={fatherNameOnDoc}
            onChangeText={setFatherNameOnDoc}
            placeholder="Father's name on the document"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={uploadStyles.input}
          />
          <Text style={uploadStyles.hint}>
            Mandatory after 15 days from your joining date. Must match your
            registered records; a mismatch will save the doc but flag it for
            HR review.
          </Text>

          <View style={{ flexDirection: "row", gap: 8 }}>
            <Pressable
              testID="up-camera"
              disabled={uploading}
              onPress={() => uploadPersonalDoc("camera")}
              style={[
                uploadStyles.primaryBtn,
                { flex: 1 },
                uploading && { opacity: 0.6 },
              ]}
            >
              {uploading ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="camera-outline" size={16} color="#fff" />
                  <Text style={uploadStyles.primaryBtnTxt}>Scan</Text>
                </>
              )}
            </Pressable>
            <Pressable
              testID="up-file"
              disabled={uploading}
              onPress={() => uploadPersonalDoc("file")}
              style={[
                uploadStyles.secondaryBtn,
                { flex: 1 },
                uploading && { opacity: 0.6 },
              ]}
            >
              <Ionicons
                name="folder-open-outline"
                size={16}
                color={colors.brandPrimary}
              />
              <Text style={uploadStyles.secondaryBtnTxt}>Pick file</Text>
            </Pressable>
          </View>
          <Text style={uploadStyles.hint}>
            Accepted: JPEG, PNG, WebP, PDF. Max 10 MB.
          </Text>
          <View style={{ height: 24 }} />
        </View>
      </Modal>
    </View>
  );
}

const uploadStyles = StyleSheet.create({
  sheet: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: spacing.md,
    paddingTop: 10,
    paddingBottom: spacing.lg,
  },
  grip: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.borderStrong,
    marginBottom: 12,
  },
  title: {
    ...type.h6,
    color: colors.onSurface,
    fontWeight: "800",
    marginBottom: 10,
  },
  label: {
    ...type.tiny,
    color: colors.onSurfaceTertiary,
    fontWeight: "700",
    marginTop: 8,
    marginBottom: 4,
    textTransform: "uppercase",
  },
  input: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.onSurface,
    marginBottom: 6,
  },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 20,
    backgroundColor: colors.brandTertiary,
    borderWidth: 1,
    borderColor: colors.brandTertiary,
  },
  chipActive: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  chipTxt: { fontSize: 12, color: colors.brandPrimary, fontWeight: "600" },
  chipTxtActive: { color: "#fff" },
  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "700" },
  secondaryBtn: {
    borderRadius: radius.md,
    paddingVertical: 12,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  secondaryBtnTxt: { color: colors.brandPrimary, fontWeight: "700" },
  hint: {
    ...type.tiny,
    color: colors.onSurfaceTertiary,
    textAlign: "center",
    marginTop: 8,
  },
});

function catIcon(c: string): any {
  const map: Record<string, string> = {
    pf: "wallet-outline",
    esi: "medkit-outline",
    gratuity: "gift-outline",
    minimum_wage: "cash-outline",
    policy: "shield-outline",
    other: "document-outline",
  };
  return map[c] || "document-outline";
}

/** "My Documents" tab — employee sees their own scan documents in
 * read-only + download mode, and can upload/scan a fresh copy. Delete
 * remains admin-only for audit safety. */
function PersonalDocsSection({
  docs,
  loading,
  onOpenUpload,
  onView,
}: {
  docs: PersonalDoc[];
  loading: boolean;
  onOpenUpload: () => void;
  onView: (d: PersonalDoc) => void;
}) {
  return (
    <View testID="personal-docs">
      <View style={personalStyles.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={personalStyles.title}>My documents</Text>
          <Text style={personalStyles.sub}>
            Read-only view of all your scan documents on record. Tap “Add
            document” to scan a fresh copy — HR will verify it.
          </Text>
        </View>
        <Pressable
          testID="personal-add"
          onPress={onOpenUpload}
          style={personalStyles.addBtn}
        >
          <Ionicons name="cloud-upload-outline" size={14} color="#fff" />
          <Text style={personalStyles.addBtnTxt}>Add</Text>
        </Pressable>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} />
      ) : docs.length === 0 ? (
        <View style={personalStyles.empty}>
          <View style={personalStyles.emptyIcon}>
            <Ionicons
              name="folder-open-outline"
              size={26}
              color={colors.onBrandTertiary}
            />
          </View>
          <Text style={personalStyles.emptyTitle}>No documents yet</Text>
          <Text style={personalStyles.emptyBody}>
            Documents uploaded by HR or by you will appear here. Tap “Add”
            to upload your first document.
          </Text>
        </View>
      ) : (
        docs.map((d) => {
          const iconName =
            PERSONAL_CATEGORIES.find((x) => x.key === d.category)?.icon ||
            "document-outline";
          const isSelf = (d.uploaded_via || "") === "employee";
          return (
            <Pressable
              key={d.doc_id}
              testID={`personal-doc-${d.doc_id}`}
              onPress={() => onView(d)}
              style={personalStyles.row}
            >
              <View style={personalStyles.rowIcon}>
                <Ionicons name={iconName} size={18} color={colors.brandPrimary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={personalStyles.rowTitle} numberOfLines={1}>
                  {personalCatLabel(d.category, d.custom_label)}
                </Text>
                <Text style={personalStyles.rowSub} numberOfLines={1}>
                  {d.filename || d.mime_type} · {fmtBytes(d.size_bytes)}
                </Text>
                <Text style={personalStyles.rowMuted}>
                  Uploaded {fmtDate(d.uploaded_at)}
                  {isSelf ? " · by you" : " · by HR"}
                </Text>
              </View>
              <Ionicons
                name="download-outline"
                size={18}
                color={colors.brandPrimary}
              />
            </Pressable>
          );
        })
      )}
    </View>
  );
}

const personalStyles = StyleSheet.create({
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginBottom: spacing.sm,
  },
  title: { ...type.h6, color: colors.onSurface, fontWeight: "700" },
  sub: {
    ...type.caption,
    color: colors.onSurfaceSecondary,
    marginTop: 2,
    lineHeight: 16,
  },
  addBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 14,
  },
  addBtnTxt: { color: "#fff", fontWeight: "700", fontSize: 12 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
    marginBottom: 8,
  },
  rowIcon: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  rowTitle: { ...type.body, color: colors.onSurface, fontWeight: "700" },
  rowSub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 1 },
  rowMuted: { ...type.tiny, color: colors.onSurfaceTertiary, marginTop: 1 },
  empty: {
    alignItems: "center",
    paddingVertical: 40,
  },
  emptyIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 8,
  },
  emptyTitle: {
    ...type.h6,
    color: colors.onSurface,
    fontWeight: "700",
    marginTop: 4,
  },
  emptyBody: {
    ...type.caption,
    color: colors.onSurfaceSecondary,
    textAlign: "center",
    lineHeight: 18,
    marginTop: 4,
    paddingHorizontal: spacing.xl,
  },
});

function EmptyState({ icon, title, body }: { icon: any; title: string; body: string }) {
  return (
    <View style={styles.empty}>
      <View style={styles.emptyIcon}>
        <Ionicons name={icon} size={28} color={colors.onBrandTertiary} />
      </View>
      <Text style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.emptyBody}>{body}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.sm },
  h1: { fontSize: 26, color: colors.onSurface, fontWeight: "500" },
  sub: { fontSize: type.sm, color: colors.onSurfaceTertiary, marginTop: 2 },
  seg: {
    marginHorizontal: spacing.xl, marginTop: spacing.md,
    backgroundColor: colors.surfaceTertiary, borderRadius: radius.md, padding: 4,
    flexDirection: "row",
  },
  segItem: {
    flex: 1, paddingVertical: 10, alignItems: "center", justifyContent: "center",
    borderRadius: radius.sm,
  },
  segItemActive: { backgroundColor: colors.surfaceSecondary },
  segTxt: { color: colors.onSurfaceTertiary, fontSize: type.base, fontWeight: "500" },
  segTxtActive: { color: colors.onSurface },
  scroll: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: 40 },
  docRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm, minHeight: 64,
  },
  docIcon: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  docTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "500" },
  docSub: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 2 },
  empty: { alignItems: "center", paddingVertical: 60, gap: 12 },
  emptyIcon: {
    width: 64, height: 64, borderRadius: 32,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  emptyTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "500" },
  emptyBody: { color: colors.onSurfaceTertiary, fontSize: type.base, textAlign: "center", paddingHorizontal: spacing.xl },
  yearTotalsCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 6,
  },
  yearTotalsTitle: {
    color: colors.onSurface,
    fontSize: type.sm,
    fontWeight: "600",
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  yearTotalsRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 4,
  },
  yearTotalsItem: { flex: 1, alignItems: "flex-start" },
  yearTotalsLabel: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    letterSpacing: 0.6,
    textTransform: "uppercase",
  },
  yearTotalsValue: {
    color: colors.onSurface,
    fontSize: type.lg,
    fontWeight: "700",
    marginTop: 2,
  },
  yearTotalsHint: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 4 },
  salaryCard: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.lg,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  salaryTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "baseline",
  },
  salaryLabel: {
    color: "rgba(255,255,255,0.7)",
    fontSize: 11,
    letterSpacing: 1.5,
    fontWeight: "600",
  },
  salaryValue: { color: "#fff", fontSize: 26, fontWeight: "700" },
  salaryBreakdown: {
    marginTop: spacing.md,
    backgroundColor: "rgba(255,255,255,0.08)",
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
  },
  salaryEmpty: {
    color: "rgba(255,255,255,0.72)",
    fontSize: type.sm,
    paddingVertical: 10,
    lineHeight: 18,
  },
  salaryRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
  },
  salaryMonth: {
    flex: 1,
    color: "rgba(255,255,255,0.9)",
    fontSize: type.sm,
    fontVariant: ["tabular-nums"],
  },
  salaryAmt: {
    color: "#fff",
    fontSize: type.base,
    fontWeight: "600",
    fontVariant: ["tabular-nums"],
  },
  statusChip: {
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: radius.pill,
  },
  statusPaid: { backgroundColor: colors.success },
  statusPending: { backgroundColor: colors.cta },
  statusPaidTxt: { color: "#fff", fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },
  statusPendingTxt: { color: "#fff", fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },
  salaryHint: {
    color: "rgba(255,255,255,0.6)",
    fontSize: 11,
    marginTop: spacing.sm,
  },
});
