import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Alert,
  Platform,
  Modal,
  TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useFocusEffect } from "@react-navigation/native";

import { useOnRefresh } from "@/src/context/RefreshBusContext";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystemNS from "expo-file-system";
import * as Sharing from "expo-sharing";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";
import { formatDate } from "@/src/utils/date";
import ScanOCRButton from "@/src/components/ScanOCRButton";
import MasterSelect from "@/src/components/MasterSelect";
import EmployeeCredentialsCard from "@/src/components/EmployeeCredentialsCard";

const FileSystem: any = FileSystemNS as any;

// -------- Config --------
const DOC_CATEGORIES: {
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

type EmpDoc = {
  doc_id: string;
  user_id: string;
  category: string;
  custom_label: string | null;
  filename: string | null;
  mime_type: string;
  size_bytes: number;
  uploaded_at: string | null;
};

type EmpDetail = {
  user_id: string;
  name?: string | null;
  email?: string | null;
  phone?: string | null;
  employee_code?: string | null;
  role?: string | null;
  department?: string | null;
  designation?: string | null;
  position?: string | null;
  company_id?: string | null;
  company_name?: string | null;
  doj?: string | null;
  salary_monthly?: number | null;
  is_live_in?: boolean;
  aadhar_number?: string | null;
  pan_number?: string | null;
  // ---- Textile industry per-employee flags ----
  business_category?: string | null;
  shift_preset_name?: string | null;
  ot_applicable?: boolean | null;
  week_off_full_day?: boolean | null;
  week_off_govt_holiday_enabled?: boolean | null;
  available_shifts?: { name: string; start: string; end: string }[];
  policy_variant?: "policy_1" | "policy_2" | null;
  // ---- Grouping ----
  employee_type?: string | null;
  is_onroll?: boolean | null;
  // Iter 76 — Biometric device enrolment ID. Shown in the Master Data
  // header grid so admins can cross-check the ZKTeco punch stream.
  bio_code?: string | number | null;
};

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
    return d.toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function labelForCategory(key: string, custom: string | null): string {
  const c = DOC_CATEGORIES.find((x) => x.key === key);
  if (custom && custom.trim()) return `${c?.label || key} — ${custom}`;
  return c?.label || key;
}

export default function EmployeeMasterScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const params = useLocalSearchParams<{ user_id?: string }>();
  const targetUserId = params.user_id as string | undefined;

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [emp, setEmp] = useState<EmpDetail | null>(null);
  const [docs, setDocs] = useState<EmpDoc[]>([]);
  // Iter 142 — Firm Master OT gate (defaults to allowed).
  const [firmOtAllowed, setFirmOtAllowed] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);

  const isAdmin =
    user?.role === "company_admin" ||
    user?.role === "super_admin" ||
    user?.role === "sub_admin";

  const load = useCallback(async () => {
    if (!targetUserId) {
      setErr("Missing employee");
      setLoading(false);
      return;
    }
    setLoading(true);
    setErr(null);
    try {
      const [pol, dl] = await Promise.all([
        api<any>(`/admin/employees/${targetUserId}/policy`),
        api<{ documents: EmpDoc[] }>(`/admin/employees/${targetUserId}/documents`),
      ]);
      const e: EmpDetail = {
        user_id: pol.user_id,
        name: pol.name,
        employee_code: pol.employee_code,
        email: pol.email,
        doj: pol.join_date,
        salary_monthly: pol.policy?.salary,
      };
      // Fetch fuller info from /admin/employees list (has phone, dept etc.)
      try {
        const list = await api<{ employees: any[] }>("/admin/employees");
        const full = (list.employees || []).find(
          (x) => x.user_id === targetUserId
        );
        if (full) {
          Object.assign(e, {
            role: full.role,
            phone: full.phone,
            department: full.department,
            designation: full.designation,
            position: full.position,
            company_id: full.company_id,
            company_name: full.company_name,
            is_live_in: !!full.is_live_in,
            aadhar_number: full.aadhar_number,
            pan_number: full.pan_number,
            // Textile flags — pass through as null when absent (inherit
            // the company default) so the tri-state toggles render right.
            shift_preset_name: full.shift_preset_name ?? null,
            ot_applicable:
              full.ot_applicable === undefined ? null : full.ot_applicable,
            week_off_full_day:
              full.week_off_full_day === undefined
                ? null
                : full.week_off_full_day,
            week_off_govt_holiday_enabled:
              full.week_off_govt_holiday_enabled === undefined
                ? null
                : full.week_off_govt_holiday_enabled,
            // Grouping fields
            employee_type: full.employee_type ?? null,
            is_onroll: full.is_onroll === undefined ? true : !!full.is_onroll,
            // Iter 165 — admin-controlled fingerprint requirement + status
            fingerprint_required: full.fingerprint_required === true,
            fingerprint_enrolled_at: full.fingerprint_enrolled_at ?? null,
            fingerprint_device: full.fingerprint_device ?? null,
            // Iter 175 — contractual employee link (Firm Master contractors)
            is_contractual: full.is_contractual === true,
            contractor_name: full.contractor_name ?? null,
            // Iter 76 — biometric device enrolment ID
            bio_code: full.bio_code ?? null,
            // Iter 91 — residential address (OCR-filled) + statutory nos.
            address: full.address ?? null,
            present_address: full.present_address ?? null,
            uan_no: full.uan_no ?? null,
            esi_ip_no: full.esi_ip_no ?? null,
          });
        }
      } catch {}

      // Fetch textile policy for the company so we can render the shift
      // dropdown and gate the whole section on business_category=textile.
      if (e.company_id) {
        try {
          const p = await api<{
            business_category: string | null;
            policy: {
              shifts?: { name: string; start: string; end: string }[];
              policy_variant?: "policy_1" | "policy_2" | null;
            };
          }>(`/attendance/policy?company_id=${e.company_id}`);
          e.business_category = p.business_category || null;
          e.available_shifts = p.policy?.shifts || [];
          e.policy_variant = p.policy?.policy_variant || null;
        } catch {}
        // Iter 142 — Firm Master OT gate drives whether the per-employee
        // OT option is shown at all.
        try {
          const fm = await api<any>(`/admin/firm-master/${e.company_id}`);
          setFirmOtAllowed((fm?.master?.salary_process?.ot_allowed) !== false);
        } catch {
          setFirmOtAllowed(true);
        }
      }
      setEmp(e);
      setDocs(dl.documents || []);
    } catch (e: any) {
      setErr(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [targetUserId]);

  useEffect(() => {
    load();
  }, [load]);
  // Iter 72 — Refresh employee master on focus + top-bar Refresh.
  useFocusEffect(useCallback(() => { load(); }, [load]));
  useOnRefresh(load);

  const showMsg = (msg: string, title = "Employee Master") => {
    if (Platform.OS === "web") {
      globalThis.alert(msg);
    } else {
      Alert.alert(title, msg);
    }
  };

  /**
   * Iter 90 — Map OCR-extracted fields onto the admin KYC endpoint.
   *
   * The OCR modal returns loose keys (name, dob, aadhaar_no, pan_no,
   * father_name, address, ...).  The admin KYC endpoint uses the
   * canonical user-record names (aadhar_number, pan_number, dob, ...).
   * Only non-empty fields are sent, and we surface a warning when
   * server-side validation rejects a value (bad Aadhaar format, PAN
   * mismatch, locked identity, etc.) instead of a silent failure.
   */
  const applyOcrFieldsToKyc = async (fields: Record<string, string | null | undefined>) => {
    if (!targetUserId) return;
    const map: Record<string, string> = {
      // Identity
      name: "name_as_per_aadhar",
      aadhaar_no: "aadhar_number",
      pan_no: "pan_number",
      voter_id: "voter_id_no",
      passport_no: "passport_no",
      dl_no: "dl_number",
      // Demographic
      dob: "dob",
      gender: "gender",
      blood_group: "blood_group",
      marital_status: "marital_status",
      religion: "religion",
      category: "category",
      caste: "caste",
      sub_caste: "sub_caste",
      tribe: "tribe",
      disability_status: "disability_status",
      disability_percent: "disability_percent",
      // Family
      father_name: "father_name",
      mother_name: "mother_name",
      spouse_name: "spouse_name",
      family_members: "family_members",
      // Address / contact
      present_address: "present_address",
      address: "present_address", // legacy alias from OCR
      permanent_address: "permanent_address",
      mobile: "mobile",
      alternate_mobile: "alternate_mobile",
      emergency_contact: "emergency_contact",
      // Bank
      bank_account_number: "bank_account_number",
      bank_name: "bank_name",
      ifsc_code: "ifsc_code",
      name_as_per_bank: "name_as_per_bank",
    };
    const payload: Record<string, string> = { _source: "ocr" };
    for (const [srcKey, val] of Object.entries(fields)) {
      if (!val || !String(val).trim()) continue;
      const dstKey = map[srcKey];
      if (!dstKey) continue;
      payload[dstKey] = String(val).trim();
    }
    // At least one KYC key must have made it through the mapping.
    const usable = Object.keys(payload).filter((k) => k !== "_source");
    if (usable.length === 0) {
      showMsg("No matching KYC fields were detected in the scan.", "OCR Autofill");
      return;
    }
    try {
      const r = await api<{
        ok: boolean;
        updated_keys?: string[];
      }>(`/admin/employees/${targetUserId}/kyc`, {
        method: "PATCH",
        body: payload,
      });
      const count = (r.updated_keys || usable).length;
      showMsg(`Updated ${count} field${count === 1 ? "" : "s"} from OCR ✓`, "OCR Autofill");
      await load();
    } catch (e: any) {
      showMsg(e?.message || "Update failed", "OCR Autofill");
    }
  };

  const downloadMasterPdf = async () => {
    if (!targetUserId) return;
    setDownloading(true);
    try {
      const res = await apiBinary(
        `/admin/employees/${targetUserId}/master-pdf`,
      );
      if (Platform.OS === "web") {
        // Open blob URL in a new tab for download
        if (res.webBlobUrl) {
          const a = document.createElement("a");
          a.href = res.webBlobUrl;
          a.download = `EmployeeMaster_${emp?.name || targetUserId}.pdf`;
          a.click();
          setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
        }
      } else {
        // Save to cache dir and open share sheet
        const safe = (emp?.name || targetUserId).replace(/[^a-z0-9]/gi, "_");
        const path = `${FileSystem.cacheDirectory}EmployeeMaster_${safe}.pdf`;
        await FileSystem.writeAsStringAsync(path, res.base64, {
          encoding: "base64",
        });
        if (await Sharing.isAvailableAsync()) {
          await Sharing.shareAsync(path, {
            mimeType: "application/pdf",
            dialogTitle: "Save Employee Master PDF",
            UTI: "com.adobe.pdf",
          });
        } else {
          showMsg(`Saved to ${path}`);
        }
      }
    } catch (e: any) {
      showMsg(e?.message || "Download failed", "Download");
    } finally {
      setDownloading(false);
    }
  };

  const [certDownloading, setCertDownloading] = useState(false);
  const downloadSalaryCertificate = async () => {
    if (!targetUserId) return;
    setCertDownloading(true);
    try {
      const res = await apiBinary(
        `/admin/employees/${targetUserId}/salary-certificate.pdf`,
      );
      const safe = (emp?.name || targetUserId).replace(/[^a-z0-9]/gi, "_");
      if (Platform.OS === "web") {
        if (res.webBlobUrl) {
          const a = document.createElement("a");
          a.href = res.webBlobUrl;
          a.download = `SalaryCertificate_${safe}.pdf`;
          a.click();
          setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
        }
      } else {
        const path = `${FileSystem.cacheDirectory}SalaryCertificate_${safe}.pdf`;
        await FileSystem.writeAsStringAsync(path, res.base64, {
          encoding: "base64",
        });
        if (await Sharing.isAvailableAsync()) {
          await Sharing.shareAsync(path, {
            mimeType: "application/pdf",
            dialogTitle: "Save Salary Certificate PDF",
            UTI: "com.adobe.pdf",
          });
        } else {
          showMsg(`Saved to ${path}`);
        }
      }
    } catch (e: any) {
      showMsg(e?.message || "Download failed", "Salary Certificate");
    } finally {
      setCertDownloading(false);
    }
  };

  const [pickCategory, setPickCategory] = useState<string>("aadhaar");
  const [pickLabel, setPickLabel] = useState<string>("");

  const doPickAndUpload = async () => {
    setUploading(true);
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: ["image/jpeg", "image/jpg", "image/png", "image/webp", "application/pdf"],
        multiple: false,
        copyToCacheDirectory: true,
      });
      if (res.canceled || !res.assets?.[0]) {
        setUploading(false);
        return;
      }
      const f = res.assets[0];
      const mime =
        f.mimeType ||
        (f.name?.toLowerCase().endsWith(".pdf")
          ? "application/pdf"
          : "image/jpeg");
      // File-size guard (10 MB decoded)
      if (f.size && f.size > 10 * 1024 * 1024) {
        throw new Error("File is too large. Max 10 MB per document.");
      }
      let b64: string;
      if (Platform.OS === "web") {
        const resp = await fetch(f.uri);
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
        b64 = await FileSystem.readAsStringAsync(f.uri, {
          encoding: "base64",
        });
      }
      await api(`/admin/employees/${targetUserId}/documents`, {
        method: "POST",
        body: {
          category: pickCategory,
          custom_label: pickLabel || null,
          filename: f.name || null,
          mime_type: mime,
          base64: b64,
        },
      });
      setUploadOpen(false);
      setPickLabel("");
      await load();
      showMsg("Document uploaded ✓");
    } catch (e: any) {
      showMsg(e?.message || "Upload failed", "Upload");
    } finally {
      setUploading(false);
    }
  };

  const viewDoc = async (d: EmpDoc) => {
    try {
      // For web use inline endpoint which streams raw file.
      if (Platform.OS === "web") {
        const res = await apiBinary(
          `/admin/employees/${targetUserId}/documents/${d.doc_id}?inline=true`,
        );
        if (res.webBlobUrl) window.open(res.webBlobUrl, "_blank");
      } else {
        // Fetch base64 and save to cache, then open via Sharing.
        const j = await api<{ document: { base64: string; mime_type: string; filename: string | null } }>(
          `/admin/employees/${targetUserId}/documents/${d.doc_id}`,
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
            dialogTitle: d.filename || labelForCategory(d.category, d.custom_label),
          });
        } else {
          showMsg(`Saved to ${path}`);
        }
      }
    } catch (e: any) {
      showMsg(e?.message || "Preview failed", "Document");
    }
  };

  const doDelete = (d: EmpDoc) => {
    const proceed = async () => {
      try {
        await api(`/admin/employees/${targetUserId}/documents/${d.doc_id}`, {
          method: "DELETE",
        });
        await load();
      } catch (e: any) {
        showMsg(e?.message || "Delete failed");
      }
    };
    const msg = `Delete ${labelForCategory(d.category, d.custom_label)}? This cannot be undone.`;
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && window.confirm(msg)) proceed();
    } else {
      Alert.alert("Delete document", msg, [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: proceed },
      ]);
    }
  };

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Admins only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>Employee Master</Text>
            {emp ? (
              <Text style={styles.hsub}>
                {emp.name}
                {emp.employee_code ? ` · ${emp.employee_code}` : ""}
              </Text>
            ) : null}
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll}>
        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
        ) : err ? (
          <View style={styles.empty}>
            <Ionicons name="warning-outline" size={40} color={colors.error} />
            <Text style={styles.emptyT}>{err}</Text>
          </View>
        ) : emp ? (
          <>
            {/* Identity card */}
            <View style={styles.card}>
              <View style={styles.identityRow}>
                <View style={styles.bigAvatar}>
                  <Text style={styles.bigAvatarTxt}>
                    {(emp.name || "?").trim().charAt(0).toUpperCase()}
                  </Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.empName}>{emp.name || "—"}</Text>
                  <Text style={styles.empMeta}>
                    {emp.role?.replace("_", " ") || "employee"}
                    {emp.employee_code ? ` · ${emp.employee_code}` : ""}
                  </Text>
                  {emp.company_name ? (
                    <View style={styles.companyPill} testID="emp-company-locked">
                      <Ionicons
                        name="business-outline"
                        size={12}
                        color={colors.brandPrimary}
                      />
                      <Text style={styles.companyPillTxt} numberOfLines={1}>
                        {emp.company_name}
                      </Text>
                      <Ionicons
                        name="lock-closed"
                        size={11}
                        color={colors.onSurfaceTertiary}
                      />
                    </View>
                  ) : null}
                  {(emp.designation || emp.department || emp.position) ? (
                    <Text style={styles.empMetaMuted}>
                      {[emp.designation || emp.position, emp.department]
                        .filter(Boolean).join(" · ")}
                    </Text>
                  ) : null}
                </View>
              </View>
              <View style={styles.divider} />
              {/* Iter 91 — one-page full edit (same form as Add Employee) */}
              <Pressable
                onPress={() => router.push(`/employee-add?user_id=${emp.user_id}`)}
                style={styles.editAllBtn}
                testID="em-edit-all"
              >
                <Ionicons name="create-outline" size={16} color="#fff" />
                <Text style={styles.editAllTxt}>Edit All Details (One Page)</Text>
              </Pressable>

              {/* Iter 96l — employer sets this employee's login credentials */}
              <EmployeeCredentialsCard
                userId={emp.user_id}
                employeeName={emp.name}
                loginId={(emp as any).login_id}
                hasPin={(emp as any).has_pin}
                hasPassword={(emp as any).has_password}
                onSaved={() => load()}
              />
              <View style={styles.companyLockedRow}>
                <Ionicons
                  name="information-circle-outline"
                  size={14}
                  color={colors.onSurfaceTertiary}
                />
                <Text style={styles.companyLockedTxt}>
                  Company assignment is locked. To move this employee to a
                  different firm, delete & re-onboard them under the new
                  company.
                </Text>
              </View>
              <View style={styles.grid}>
                <MetaCell label="Phone" value={emp.phone} />
                <MetaCell label="Email" value={emp.email} />
                <MetaCell label="Date of Joining" value={formatDate(emp.doj)} />
                <MetaCell
                  label="Monthly salary"
                  value={
                    emp.salary_monthly
                      ? `₹${Number(emp.salary_monthly).toLocaleString()}`
                      : "—"
                  }
                />
                <MetaCell label="Live-in" value={emp.is_live_in ? "Yes" : "No"} />
                {/* Iter 91 — Residential address (filled by Aadhaar OCR scan
                    via present_address → address sync, or typed manually). */}
                <MetaCell
                  label="Residential Address"
                  value={(emp as any).address || (emp as any).present_address || "—"}
                />
                <MetaCell
                  label="Aadhaar"
                  value={
                    emp.aadhar_number
                      ? "XXXX-XXXX-" + String(emp.aadhar_number).slice(-4)
                      : "—"
                  }
                />
                {/* Iter 76 — Biometric enrolment ID visible in Master Data */}
                <MetaCell
                  label="Bio Code"
                  value={
                    emp.bio_code !== null && emp.bio_code !== undefined && emp.bio_code !== ""
                      ? String(emp.bio_code)
                      : "—"
                  }
                />
              </View>
            </View>

            {/* Employee grouping: Type + On-roll */}
            <EmployeeGroupingCard emp={emp} onSaved={load} />

            {/* Iter 91 — PF UAN / ESIC generation, enabled by default.
                Only Aadhaar is mandatory (validated server-side). */}
            <UanEsicCard emp={emp} />

            {/* Textile industry flags — only shown for textile companies */}
            {emp.business_category === "textile" ? (
              <TextileMasterCard
                emp={emp}
                onSaved={load}
                firmOtAllowed={firmOtAllowed}
              />
            ) : firmOtAllowed ? (
              /* Iter 142 — non-textile firms with OT allowed in the Firm
                 Master get a dedicated per-employee OT card. */
              <OtCard emp={emp} onSaved={load} />
            ) : null}

            {/* Master PDF actions */}
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Master data sheet</Text>
              <Text style={styles.cardHint}>
                Generates a printable PDF with all employee master fields —
                personal info, KYC, employment, salary policy and a
                signature block for HR & employee. A snapshot copy is
                automatically saved in company records for audit.
              </Text>
              <Pressable
                testID="download-master-pdf"
                onPress={downloadMasterPdf}
                style={[styles.primaryBtn, downloading && styles.btnDisabled]}
                disabled={downloading}
              >
                {downloading ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons name="document-text-outline" size={18} color="#fff" />
                    <Text style={styles.primaryBtnTxt}>Download / Print PDF</Text>
                  </>
                )}
              </Pressable>
              <Pressable
                testID="download-salary-cert"
                onPress={downloadSalaryCertificate}
                style={[
                  styles.primaryBtn,
                  { marginTop: 8, backgroundColor: colors.brandAccent || "#C89B3C" },
                  certDownloading && styles.btnDisabled,
                ]}
                disabled={certDownloading}
              >
                {certDownloading ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons name="ribbon-outline" size={18} color="#fff" />
                    <Text style={styles.primaryBtnTxt}>Salary Certificate PDF</Text>
                  </>
                )}
              </Pressable>
              <Text style={[styles.cardHint, { marginTop: 6 }]}>
                Salary Certificate — one-page ‘To whomsoever it may concern’ PDF
                with the employee&apos;s current gross salary, statutory IDs and an
                authorised signatory block (for banks, visa or HR use).
              </Text>
            </View>

            {/* Scan documents */}
            <View style={styles.card}>
              <View style={styles.rowBetween}>
                <Text style={styles.cardTitle}>Scan documents ({docs.length})</Text>
                <Pressable
                  testID="add-doc-btn"
                  style={styles.smallBtn}
                  onPress={() => setUploadOpen(true)}
                >
                  <Ionicons name="add" size={14} color={colors.brandPrimary} />
                  <Text style={styles.smallBtnTxt}>Add</Text>
                </Pressable>
              </View>
              <Text style={styles.cardHint}>
                Attach scan copies of the employee&apos;s documents for future
                verification. Only company_admin & super_admin can view or
                download these files — employees themselves cannot see them.
              </Text>

              {/* Iter 90 — Post-onboarding OCR Autofill.
                  Admin can scan any of the common Indian identity or
                  demographic documents and push extracted values straight
                  into the employee's KYC master record. Web-only. */}
              {Platform.OS === "web" ? (
                <View style={styles.ocrPanel} testID="employee-master-ocr-panel">
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 }}>
                    <Ionicons name="scan-outline" size={16} color={colors.brandPrimary} />
                    <Text style={styles.ocrPanelTitle}>OCR Autofill — post-onboarding</Text>
                  </View>
                  <Text style={styles.ocrPanelHint}>
                    Scan an Indian identity or demographic document to
                    auto-update this employee&apos;s KYC (Aadhaar, PAN, DL,
                    blood group, religion, caste, disability, family and
                    contact details). Aadhaar &amp; PAN numbers are locked
                    once saved. A Manual Fill fallback opens for
                    Hindi/blurry documents.
                  </Text>
                  <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
                    <ScanOCRButton
                      documentType="aadhaar"
                      compact
                      onApply={applyOcrFieldsToKyc}
                    />
                    <ScanOCRButton
                      documentType="pan"
                      compact
                      onApply={applyOcrFieldsToKyc}
                    />
                    <ScanOCRButton
                      documentType="voter"
                      compact
                      onApply={applyOcrFieldsToKyc}
                    />
                    <ScanOCRButton
                      documentType="driving_license"
                      compact
                      onApply={applyOcrFieldsToKyc}
                    />
                    <ScanOCRButton
                      documentType="passport"
                      compact
                      onApply={applyOcrFieldsToKyc}
                    />
                    <ScanOCRButton
                      documentType="bank_passbook"
                      compact
                      label="Scan Bank Passbook (OCR)"
                      onApply={applyOcrFieldsToKyc}
                    />
                    <ScanOCRButton
                      documentType="caste_certificate"
                      compact
                      label="Scan Caste / Tribe Cert. (OCR)"
                      onApply={applyOcrFieldsToKyc}
                    />
                    <ScanOCRButton
                      documentType="disability_certificate"
                      compact
                      label="Scan Disability Cert. (OCR)"
                      onApply={applyOcrFieldsToKyc}
                    />
                    <ScanOCRButton
                      documentType="generic"
                      compact
                      label="Scan Other Document (OCR)"
                      onApply={applyOcrFieldsToKyc}
                    />
                  </View>
                </View>
              ) : null}

              {docs.length === 0 ? (
                <View style={styles.emptyDocs}>
                  <Ionicons
                    name="folder-open-outline"
                    size={26}
                    color={colors.onSurfaceTertiary}
                  />
                  <Text style={styles.emptyDocsTxt}>
                    No documents on record yet. Tap “Add” to upload the
                    first scan.
                  </Text>
                </View>
              ) : (
                docs.map((d) => {
                  const catIcon =
                    DOC_CATEGORIES.find((x) => x.key === d.category)?.icon ||
                    "document-outline";
                  return (
                    <View
                      key={d.doc_id}
                      style={styles.docRow}
                      testID={`doc-${d.doc_id}`}
                    >
                      <View style={styles.docIconWrap}>
                        <Ionicons
                          name={catIcon}
                          size={18}
                          color={colors.brandPrimary}
                        />
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.docTitle} numberOfLines={1}>
                          {labelForCategory(d.category, d.custom_label)}
                        </Text>
                        <Text style={styles.docMeta} numberOfLines={1}>
                          {d.filename || d.mime_type} · {fmtBytes(d.size_bytes)}
                        </Text>
                        <Text style={styles.docMetaMuted}>
                          Uploaded {fmtDate(d.uploaded_at)}
                        </Text>
                      </View>
                      <Pressable
                        onPress={() => viewDoc(d)}
                        hitSlop={10}
                        style={styles.iconBtn}
                        testID={`view-doc-${d.doc_id}`}
                      >
                        <Ionicons
                          name="eye-outline"
                          size={18}
                          color={colors.brandPrimary}
                        />
                      </Pressable>
                      <Pressable
                        onPress={() => doDelete(d)}
                        hitSlop={10}
                        style={styles.iconBtnDanger}
                        testID={`delete-doc-${d.doc_id}`}
                      >
                        <Ionicons name="trash-outline" size={18} color="#8A1F1F" />
                      </Pressable>
                    </View>
                  );
                })
              )}
            </View>
            <View style={{ height: 40 }} />
          </>
        ) : null}
      </KeyboardAwareScrollView>

      {/* Upload modal */}
      <Modal
        transparent
        visible={uploadOpen}
        animationType="slide"
        onRequestClose={() => setUploadOpen(false)}
      >
        <Pressable style={styles.backdrop} onPress={() => setUploadOpen(false)} />
        <View style={styles.sheet}>
          <View style={styles.sheetGrip} />
          <Text style={styles.sheetTitle}>Upload scan document</Text>

          <Text style={styles.label}>Document type</Text>
          <View style={styles.chipsWrap}>
            {DOC_CATEGORIES.map((c) => (
              <Pressable
                key={c.key}
                onPress={() => setPickCategory(c.key)}
                style={[
                  styles.chip,
                  pickCategory === c.key && styles.chipActive,
                ]}
                testID={`cat-${c.key}`}
              >
                <Ionicons
                  name={c.icon}
                  size={12}
                  color={
                    pickCategory === c.key ? "#fff" : colors.brandPrimary
                  }
                />
                <Text
                  style={[
                    styles.chipTxt,
                    pickCategory === c.key && styles.chipTxtActive,
                  ]}
                >
                  {c.label}
                </Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.label}>Custom label (optional)</Text>
          <TextInput
            value={pickLabel}
            onChangeText={setPickLabel}
            placeholder="e.g. Front side / SSC Marksheet"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={styles.input}
            testID="doc-label-input"
          />

          <Pressable
            testID="doc-pick-upload"
            style={[styles.primaryBtn, uploading && styles.btnDisabled]}
            onPress={doPickAndUpload}
            disabled={uploading}
          >
            {uploading ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="cloud-upload-outline" size={18} color="#fff" />
                <Text style={styles.primaryBtnTxt}>Pick file & upload</Text>
              </>
            )}
          </Pressable>
          <Text style={styles.sheetHint}>
            Accepted: JPEG, PNG, WebP, PDF. Max 10 MB.
          </Text>
          <View style={{ height: 24 }} />
        </View>
      </Modal>
    </View>
  );
}

function MetaCell({ label, value }: { label: string; value: any }) {
  return (
    <View style={styles.metaCell}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={styles.metaValue}>{value ?? "—"}</Text>
    </View>
  );
}

/** Employee Type (free-form with suggestions) + On-roll / Off-roll flag.
 *
 * Rules:
 * • `employee_type` is title-cased server-side, capped at 60 chars. The
 *   backend also exposes /admin/employee-types with existing distinct
 *   values so the UI can offer a suggestion strip for consistency
 *   (Employer initially types "Staff", "Labour" etc., subsequent
 *   Employers can tap-to-fill).
 * • `is_onroll` is tri-state (Inherit / On / Off) but we render it as a
 *   simple On/Off switch — an absent value is treated as On (default).
 */
function UanEsicCard({ emp }: { emp: EmpDetail }) {
  const [busy, setBusy] = useState<"uan" | "esic" | null>(null);
  const uan = (emp as any).uan_no || "";
  const esi = (emp as any).esi_ip_no || "";
  const hasAadhaar = !!((emp as any).aadhar_number || (emp as any).aadhaar_no);

  const fire = async (kind: "uan" | "esic") => {
    if (busy) return;
    setBusy(kind);
    try {
      const r = await api<{ message?: string; already_present?: boolean }>(
        `/admin/employees/${emp.user_id}/generate-${kind}`,
        { method: "POST", body: {} },
      );
      const msg = r.message || "Generation queued.";
      if (Platform.OS === "web") globalThis.alert(msg);
      else Alert.alert("Portal automation", msg);
    } catch (e: any) {
      const msg = e?.message || "Failed to queue generation";
      if (Platform.OS === "web") globalThis.alert(msg);
      else Alert.alert("Portal automation", msg);
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={styles.card} testID="uan-esic-card">
      <Text style={styles.cardTitle}>PF UAN / ESIC Generation</Text>
      <Text style={styles.cardHint}>
        {hasAadhaar
          ? "Queue automatic UAN / ESIC IP generation on the government portals. Only the Aadhaar number is checked — it's on file for this employee."
          : "Only the Aadhaar number is required — add it in the employee's KYC, then tap Generate."}
      </Text>
      <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
        <Pressable
          onPress={() => fire("uan")}
          disabled={busy !== null}
          style={[styles.primaryBtn, { flex: 1, minWidth: 180 }, busy !== null && styles.btnDisabled]}
          testID="em-generate-uan"
        >
          {busy === "uan" ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <Ionicons name="flash-outline" size={16} color="#fff" />
              <Text style={styles.primaryBtnTxt}>
                {uan ? `UAN: ${uan}` : "Generate PF UAN (EPFO)"}
              </Text>
            </>
          )}
        </Pressable>
        <Pressable
          onPress={() => fire("esic")}
          disabled={busy !== null}
          style={[
            styles.primaryBtn,
            { flex: 1, minWidth: 180, backgroundColor: "#0891B2" },
            busy !== null && styles.btnDisabled,
          ]}
          testID="em-generate-esic"
        >
          {busy === "esic" ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <Ionicons name="medkit-outline" size={16} color="#fff" />
              <Text style={styles.primaryBtnTxt}>
                {esi ? `ESIC IP: ${esi}` : "Generate ESIC IP No."}
              </Text>
            </>
          )}
        </Pressable>
      </View>
    </View>
  );
}

// Iter 175 — contractor chip styles (Grouping card).
const cchip = StyleSheet.create({
  chip: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 7, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary },
  txt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
});

function EmployeeGroupingCard({
  emp,
  onSaved,
}: {
  emp: EmpDetail & { employee_type?: string | null; is_onroll?: boolean | null };
  onSaved: () => Promise<void> | void;
}) {
  const [typeVal, setTypeVal] = useState<string>(emp.employee_type || "");
  const [onroll, setOnroll] = useState<boolean>(emp.is_onroll !== false);
  const [saving, setSaving] = useState(false);
  // Iter 164 — Off-roll only allowed when the firm's Offline Salary is
  // enabled in Firm Master; otherwise the toggle is locked to On-roll.
  const [offlineAllowed, setOfflineAllowed] = useState<boolean | null>(null);
  // Iter 165 — admin-controlled fingerprint requirement; only when the
  // firm's Bio Matrix Attendance is enabled in Firm Master.
  const [bioAllowed, setBioAllowed] = useState<boolean | null>(null);
  const [fpRequired, setFpRequired] = useState<boolean>(
    (emp as any).fingerprint_required === true);
  // Iter 175 — Contractual employee (Firm Master Policy 2 contractors).
  const [contractorAllowed, setContractorAllowed] = useState<boolean>(false);
  const [contractorList, setContractorList] = useState<{ name: string; father_name?: string }[]>([]);
  const [isContractual, setIsContractual] = useState<boolean>(
    (emp as any).is_contractual === true);
  const [contractorName, setContractorName] = useState<string>(
    (emp as any).contractor_name || "");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const fm = await api<any>(`/admin/firm-master/${emp.company_id}`);
        const sp = (fm?.master || {}).salary_process || {};
        if (alive) {
          setOfflineAllowed(!!sp.offline_salary);
          if (!sp.offline_salary) setOnroll(true);
          setBioAllowed(!!sp.bio_matrix_attendance);
          if (!sp.bio_matrix_attendance) setFpRequired(false);
          // Iter 175 — contractor list from Firm Master (Policy 2 section)
          const st = (fm?.master || {}).settings || {};
          const list = ((fm?.master || {}).contractors || []).filter(
            (c: any) => (c?.name || "").trim(),
          );
          setContractorAllowed(!!st.contractor_employees && list.length > 0);
          setContractorList(list);
        }
      } catch { if (alive) { setOfflineAllowed(true); setBioAllowed(false); } }
    })();
    return () => { alive = false; };
  }, [emp.company_id]);

  const rollLocked = offlineAllowed === false;

  const doSave = async () => {
    setSaving(true);
    try {
      await api("/admin/user-role", {
        method: "PATCH",
        body: {
          user_id: emp.user_id,
          employee_type: (typeVal || "").trim() || null,
          is_onroll: onroll,
          // Iter 165 — only send when the firm allows biometric attendance.
          ...(bioAllowed ? { fingerprint_required: fpRequired } : {}),
          // Iter 175 — contractual employee link (Firm Master contractors).
          ...(contractorAllowed
            ? { is_contractual: isContractual,
                contractor_name: isContractual ? (contractorName || null) : null }
            : {}),
        },
      });
      await onSaved();
      if (Platform.OS === "web") globalThis.alert("Saved ✓");
      else Alert.alert("Saved", "Grouping updated.");
    } catch (e: any) {
      const msg = e?.message || "Save failed";
      if (Platform.OS === "web") globalThis.alert(msg);
      else Alert.alert("Save", msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={[styles.card, { zIndex: 30 }]} testID="employee-grouping-card">
      <Text style={styles.cardTitle}>Grouping</Text>
      <Text style={styles.cardHint}>
        Employee Type and Group are the same label — pick it from the Group
        master (or type a custom value inside the dropdown).
      </Text>

      <MasterSelect
        label="Group"
        masterType="group"
        companyId={emp.company_id}
        value={typeVal}
        onChange={setTypeVal}
        testID="grouping-type-select"
      />

      <Pressable
        testID="grouping-onroll-toggle"
        onPress={() => {
          if (rollLocked) return;
          setOnroll((v) => !v);
        }}
        style={[styles.onrollRow, rollLocked && { opacity: 0.6 }]}
      >
        <View style={{ flex: 1 }}>
          <Text style={styles.metaValue}>
            {onroll ? "On-roll (payroll employee)" : "Off-roll (contract / agency)"}
          </Text>
          <Text style={styles.fieldHint}>
            {rollLocked
              ? "Locked to On-roll — Offline Salary is disabled for this firm in Firm Master."
              : onroll
              ? "Regular payroll employee. Included in default reports."
              : "Third-party / contractor. Segregated in reports; punch flow unchanged. Excluded from Compliance Salary."}
          </Text>
        </View>
        <View style={[styles.toggleTrack, onroll && styles.toggleTrackOn]}>
          <View style={[styles.toggleKnob, onroll && styles.toggleKnobOn]} />
        </View>
      </Pressable>

      {/* Iter 165 — admin-controlled fingerprint verification (Employee
          PWA). Only editable when the firm's Bio Matrix Attendance is
          enabled in Firm Master. */}
      <Pressable
        testID="grouping-fingerprint-toggle"
        onPress={() => {
          if (!bioAllowed) return;
          setFpRequired((v) => !v);
        }}
        style={[styles.onrollRow, !bioAllowed && { opacity: 0.6 }]}
      >
        <View style={{ flex: 1 }}>
          <Text style={styles.metaValue}>
            {fpRequired ? "Fingerprint verification: ON" : "Fingerprint verification: OFF"}
          </Text>
          <Text style={styles.fieldHint}>
            {bioAllowed === false
              ? "Locked — enable Bio Matrix Attendance for this firm in Firm Master first."
              : fpRequired
              ? "Employee must verify device fingerprint to open the app and to punch (phones without a sensor fall back automatically)."
              : "Employee uses the normal flow. Turn ON to require device fingerprint at app open and punch."}
          </Text>
          {(emp as any).fingerprint_enrolled_at ? (
            <Text style={[styles.fieldHint, { color: "#059669" }]}>
              Enrolled on device ({(emp as any).fingerprint_device || "device"}) ·{" "}
              {String((emp as any).fingerprint_enrolled_at).slice(0, 10)}
            </Text>
          ) : null}
        </View>
        <View style={[styles.toggleTrack, fpRequired && styles.toggleTrackOn]}>
          <View style={[styles.toggleKnob, fpRequired && styles.toggleKnobOn]} />
        </View>
      </Pressable>

      {/* Iter 175 — Contractual employee (Firm Master Policy 2 contractors).
          Only shown when the firm enabled Contractor Employees and has at
          least one contractor defined in Firm Master. */}
      {contractorAllowed ? (
        <>
          <Pressable
            testID="grouping-contractual-toggle"
            onPress={() => setIsContractual((v) => !v)}
            style={styles.onrollRow}
          >
            <View style={{ flex: 1 }}>
              <Text style={styles.metaValue}>
                {isContractual ? "Contractual Employee: YES" : "Contractual Employee: NO"}
              </Text>
              <Text style={styles.fieldHint}>
                {isContractual
                  ? "Punches go to the Contractor Punch approval queue — the company must approve/reject before they count in attendance."
                  : "Turn ON if this employee works under one of the firm's contractors (Firm Master → Contractor Employees)."}
              </Text>
            </View>
            <View style={[styles.toggleTrack, isContractual && styles.toggleTrackOn]}>
              <View style={[styles.toggleKnob, isContractual && styles.toggleKnobOn]} />
            </View>
          </Pressable>
          {isContractual ? (
            <View style={{ marginTop: 8 }}>
              <Text style={styles.fieldHint}>Select the contractor this employee works under:</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                {contractorList.map((c) => {
                  const on = contractorName === c.name;
                  return (
                    <Pressable
                      key={c.name}
                      onPress={() => setContractorName(c.name)}
                      style={[cchip.chip, on && cchip.chipOn]}
                      testID={`grouping-contractor-${c.name}`}
                    >
                      <Ionicons name="briefcase-outline" size={12} color={on ? "#fff" : colors.brandPrimary} />
                      <Text style={[cchip.txt, on && { color: "#fff" }]}>{c.name}</Text>
                    </Pressable>
                  );
                })}
              </View>
              {!contractorName ? (
                <Text style={[styles.fieldHint, { color: "#B45309", marginTop: 4 }]}>
                  ⚠ Pick a contractor — punches cannot be grouped without one.
                </Text>
              ) : null}
            </View>
          ) : null}
        </>
      ) : null}

      <Pressable
        testID="grouping-save"
        onPress={doSave}
        disabled={saving}
        style={[styles.primaryBtn, saving && styles.btnDisabled]}
      >
        {saving ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <>
            <Ionicons name="save-outline" size={16} color="#fff" />
            <Text style={styles.primaryBtnTxt}>Save grouping</Text>
          </>
        )}
      </Pressable>
    </View>
  );
}

/** Per-employee Textile-industry flags. Only rendered when the employee's
 * company has `business_category === "textile"`.
 *
 * Semantics:
 * • Shift preset: dropdown of shifts defined on the company's textile
 *   attendance policy (5 presets by default).
 * • OT Applicable: tri-state (Inherit / Yes / No). Null → default true
 *   in `compute_textile_day`.
 * • Week-off Full Day (Policy 1 only): pay-full-day when the employee
 *   worked on a weekly-off day. Tri-state.
 * • Week-off / Govt Holiday Enabled (Policy 2 only): mark this employee
 *   as eligible for the "all-OT on week-off/holiday" transformation.
 */
function TextileMasterCard({
  emp,
  onSaved,
  firmOtAllowed = true,
}: {
  emp: EmpDetail;
  onSaved: () => Promise<void> | void;
  firmOtAllowed?: boolean;
}) {
  const [shift, setShift] = useState<string | null>(emp.shift_preset_name || null);
  const [ot, setOt] = useState<boolean | null>(
    emp.ot_applicable === undefined ? null : emp.ot_applicable ?? null,
  );
  const [weFullDay, setWeFullDay] = useState<boolean | null>(
    emp.week_off_full_day === undefined ? null : emp.week_off_full_day ?? null,
  );
  const [weGovt, setWeGovt] = useState<boolean | null>(
    emp.week_off_govt_holiday_enabled === undefined
      ? null
      : emp.week_off_govt_holiday_enabled ?? null,
  );
  const [saving, setSaving] = useState(false);
  const [shiftPickerOpen, setShiftPickerOpen] = useState(false);

  const variant = emp.policy_variant;
  const shifts = emp.available_shifts || [];

  const doSave = async () => {
    setSaving(true);
    try {
      await api(`/admin/user-role`, {
        method: "PATCH",
        body: {
          user_id: emp.user_id,
          shift_preset_name: shift,
          ot_applicable: ot,
          week_off_full_day: weFullDay,
          week_off_govt_holiday_enabled: weGovt,
        },
      });
      await onSaved();
      if (Platform.OS === "web") {
        globalThis.alert("Textile flags saved ✓");
      } else {
        Alert.alert("Saved", "Textile flags updated.");
      }
    } catch (e: any) {
      const msg = e?.message || "Save failed";
      if (Platform.OS === "web") globalThis.alert(msg);
      else Alert.alert("Save", msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={styles.card} testID="textile-master-card">
      <View style={styles.rowBetween}>
        <Text style={styles.cardTitle}>Textile master flags</Text>
        <View style={styles.textileVariantPill}>
          <Ionicons name="options-outline" size={11} color={colors.brandPrimary} />
          <Text style={styles.textileVariantPillTxt}>
            {variant === "policy_2" ? "Policy 2" : variant === "policy_1" ? "Policy 1" : "Not set"}
          </Text>
        </View>
      </View>
      <Text style={styles.cardHint}>
        These flags override the company&apos;s default textile calc. Leave
        as &quot;Inherit&quot; to follow the company setting.
      </Text>

      {/* Shift preset dropdown */}
      <Text style={styles.fieldLabel}>Shift preset</Text>
      <Pressable
        testID="textile-shift-picker"
        style={styles.selectField}
        onPress={() => setShiftPickerOpen(true)}
      >
        <Text
          style={[
            styles.selectFieldTxt,
            !shift && { color: colors.onSurfaceTertiary },
          ]}
        >
          {shift ||
            (shifts.length === 0
              ? "No shifts defined — add them in Attendance Policy"
              : "Choose a shift")}
        </Text>
        <Ionicons name="chevron-down" size={16} color={colors.onSurfaceTertiary} />
      </Pressable>

      {/* OT Applicable tri-state — hidden when the Firm Master disables
          OT firm-wide (Iter 142: no OT is calculated at all then). */}
      {firmOtAllowed ? (
        <>
          <Text style={styles.fieldLabel}>Overtime applicable</Text>
          <TriState
            value={ot}
            onChange={setOt}
            labels={["Inherit", "Yes", "No"]}
            testID="textile-ot"
          />
        </>
      ) : null}

      {/* Week-off Full Day — Policy 1 */}
      {variant !== "policy_2" ? (
        <>
          <Text style={styles.fieldLabel}>Week-off Full-Day Payment (Policy 1)</Text>
          <TriState
            value={weFullDay}
            onChange={setWeFullDay}
            labels={["Inherit", "Yes", "No"]}
            testID="textile-weekoff-fdp"
          />
        </>
      ) : null}

      {/* Week-off / Govt Holiday Enabled — Policy 2 */}
      {variant !== "policy_1" ? (
        <>
          <Text style={styles.fieldLabel}>
            Week-off / Govt-Holiday enabled (Policy 2)
          </Text>
          <Text style={styles.fieldHint}>
            When on and this employee works on a week-off/holiday, NO
            present day is credited — everything becomes OT.
          </Text>
          <TriState
            value={weGovt}
            onChange={setWeGovt}
            labels={["Inherit", "Yes", "No"]}
            testID="textile-weekoff-govt"
          />
        </>
      ) : null}

      <Pressable
        testID="textile-save"
        onPress={doSave}
        style={[styles.primaryBtn, saving && styles.btnDisabled]}
        disabled={saving}
      >
        {saving ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <>
            <Ionicons name="save-outline" size={16} color="#fff" />
            <Text style={styles.primaryBtnTxt}>Save textile flags</Text>
          </>
        )}
      </Pressable>

      <Modal
        transparent
        visible={shiftPickerOpen}
        animationType="slide"
        onRequestClose={() => setShiftPickerOpen(false)}
      >
        <Pressable
          style={styles.backdrop}
          onPress={() => setShiftPickerOpen(false)}
        />
        <View style={styles.sheet}>
          <View style={styles.sheetGrip} />
          <Text style={styles.sheetTitle}>Choose shift preset</Text>
          <Pressable
            style={styles.shiftRow}
            onPress={() => {
              setShift(null);
              setShiftPickerOpen(false);
            }}
          >
            <Ionicons
              name="close-circle-outline"
              size={18}
              color={colors.onSurfaceSecondary}
            />
            <Text style={styles.shiftRowTitle}>None / Clear</Text>
          </Pressable>
          {shifts.map((s) => {
            const active = s.name === shift;
            return (
              <Pressable
                key={s.name}
                testID={`shift-opt-${s.name.replace(/\W+/g, "_")}`}
                style={[
                  styles.shiftRow,
                  active && { backgroundColor: colors.brandTertiary },
                ]}
                onPress={() => {
                  setShift(s.name);
                  setShiftPickerOpen(false);
                }}
              >
                <Ionicons
                  name="time-outline"
                  size={18}
                  color={colors.brandPrimary}
                />
                <View style={{ flex: 1 }}>
                  <Text
                    style={[
                      styles.shiftRowTitle,
                      active && { color: colors.brandPrimary, fontWeight: "700" },
                    ]}
                  >
                    {s.name}
                  </Text>
                  <Text style={styles.shiftRowSub}>
                    {s.start} — {s.end}
                  </Text>
                </View>
                {active ? (
                  <Ionicons
                    name="checkmark-circle"
                    size={18}
                    color={colors.brandPrimary}
                  />
                ) : null}
              </Pressable>
            );
          })}
          <View style={{ height: 20 }} />
        </View>
      </Modal>
    </View>
  );
}

/** Iter 142 — per-employee Overtime flag for NON-textile firms (textile
 *  firms manage it inside the Textile master flags card). Shown only when
 *  the Firm Master allows OT. */
function OtCard({
  emp,
  onSaved,
}: {
  emp: EmpDetail;
  onSaved: () => Promise<void> | void;
}) {
  const [ot, setOt] = useState<boolean | null>(
    emp.ot_applicable === undefined ? null : emp.ot_applicable ?? null,
  );
  const [saving, setSaving] = useState(false);
  const doSave = async () => {
    setSaving(true);
    try {
      await api(`/admin/user-role`, {
        method: "PATCH",
        body: { user_id: emp.user_id, ot_applicable: ot },
      });
      await onSaved();
      if (Platform.OS === "web") globalThis.alert("OT setting saved ✓");
      else Alert.alert("Saved", "OT setting updated.");
    } catch (e: any) {
      const msg = e?.message || "Save failed";
      if (Platform.OS === "web") globalThis.alert(msg);
      else Alert.alert("Save", msg);
    } finally {
      setSaving(false);
    }
  };
  return (
    <View style={styles.card} testID="ot-card">
      <Text style={styles.cardTitle}>Overtime (OT)</Text>
      <Text style={styles.cardHint}>
        When set to &quot;No&quot;, NO overtime is calculated for this
        employee. &quot;Inherit&quot; follows the default (allowed).
      </Text>
      <Text style={styles.fieldLabel}>Overtime applicable</Text>
      <TriState
        value={ot}
        onChange={setOt}
        labels={["Inherit", "Yes", "No"]}
        testID="emp-ot"
      />
      <Pressable
        testID="ot-save"
        onPress={doSave}
        style={[styles.primaryBtn, saving && styles.btnDisabled]}
        disabled={saving}
      >
        {saving ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.primaryBtnTxt}>Save OT Setting</Text>
        )}
      </Pressable>
    </View>
  );
}

function TriState({
  value,
  onChange,
  labels,
  testID,
}: {
  value: boolean | null;
  onChange: (v: boolean | null) => void;
  labels: [string, string, string];
  testID?: string;
}) {
  const options: [boolean | null, string][] = [
    [null, labels[0]],
    [true, labels[1]],
    [false, labels[2]],
  ];
  return (
    <View style={styles.triStateRow} testID={testID}>
      {options.map(([v, label]) => {
        const active = value === v;
        return (
          <Pressable
            key={String(v)}
            onPress={() => onChange(v)}
            style={[styles.triChip, active && styles.triChipActive]}
            testID={`${testID}-${String(v)}`}
          >
            <Text style={[styles.triChipTxt, active && styles.triChipTxtActive]}>
              {label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}


const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    paddingHorizontal: spacing.md,
    height: 52,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
  },
  h1: { ...type.h5, color: colors.onSurface, fontWeight: "700" },
  hsub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },
  scroll: { padding: spacing.md, paddingBottom: 40 },

  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: { marginTop: 8, color: colors.onSurfaceTertiary, ...type.body },

  empty: { alignItems: "center", padding: 40 },
  emptyT: { marginTop: 8, color: colors.onSurfaceTertiary, textAlign: "center" },

  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cardTitle: {
    ...type.h6,
    color: colors.onSurface,
    fontWeight: "700",
    marginBottom: 4,
  },
  cardHint: {
    ...type.caption,
    color: colors.onSurfaceSecondary,
    lineHeight: 18,
    marginBottom: spacing.sm,
  },

  // Iter 90 — OCR Autofill panel inside the Documents card.
  ocrPanel: {
    marginTop: spacing.xs,
    marginBottom: spacing.sm,
    padding: 10,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  ocrPanelTitle: {
    ...type.label,
    color: colors.brandPrimary,
    fontWeight: "800",
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  ocrPanelHint: {
    ...type.caption,
    color: colors.onBrandTertiary,
    lineHeight: 16,
  },

  identityRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  bigAvatar: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  bigAvatarTxt: {
    color: colors.brandPrimary,
    ...type.h4,
    fontWeight: "800",
  },
  empName: { ...type.h6, color: colors.onSurface, fontWeight: "700" },
  empMeta: { ...type.caption, color: colors.onSurfaceSecondary },
  empMetaMuted: { ...type.caption, color: colors.onSurfaceTertiary },
  divider: {
    height: 1,
    backgroundColor: colors.divider,
    marginVertical: spacing.sm,
  },
  companyPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    alignSelf: "flex-start",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 12,
    backgroundColor: colors.brandTertiary,
    marginTop: 4,
    maxWidth: "95%",
  },
  companyPillTxt: {
    color: colors.brandPrimary,
    fontWeight: "700",
    fontSize: 12,
    maxWidth: 180,
  },
  editAllBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6,
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 11,
    marginBottom: 8,
    minHeight: 44,
  },
  editAllTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  companyLockedRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 6,
    paddingHorizontal: 4,
    marginBottom: spacing.sm,
  },
  companyLockedTxt: {
    flex: 1,
    ...type.tiny,
    color: colors.onSurfaceTertiary,
    lineHeight: 15,
  },

  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginHorizontal: -6,
  },
  metaCell: {
    width: "50%",
    paddingHorizontal: 6,
    paddingVertical: 6,
  },
  metaLabel: {
    ...type.tiny,
    color: colors.onSurfaceTertiary,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  metaValue: { ...type.body, color: colors.onSurface, marginTop: 2 },

  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
  },
  primaryBtnTxt: { color: colors.onBrandPrimary, fontWeight: "700" },
  btnDisabled: { opacity: 0.6 },

  smallBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 2,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
  },
  smallBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  rowBetween: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 4,
  },

  emptyDocs: {
    alignItems: "center",
    padding: 20,
    gap: 6,
  },
  emptyDocsTxt: {
    ...type.caption,
    color: colors.onSurfaceTertiary,
    textAlign: "center",
  },

  docRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    gap: 10,
  },
  docIconWrap: {
    width: 34,
    height: 34,
    borderRadius: 8,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  docTitle: {
    ...type.body,
    color: colors.onSurface,
    fontWeight: "700",
  },
  docMeta: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 1 },
  docMetaMuted: { ...type.tiny, color: colors.onSurfaceTertiary, marginTop: 1 },
  iconBtn: {
    width: 32,
    height: 32,
    borderRadius: 8,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  iconBtnDanger: {
    width: 32,
    height: 32,
    borderRadius: 8,
    backgroundColor: "#FFE0E0",
    alignItems: "center",
    justifyContent: "center",
  },

  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.35)" },
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
  sheetGrip: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.borderStrong,
    marginBottom: 12,
  },
  sheetTitle: {
    ...type.h6,
    color: colors.onSurface,
    fontWeight: "800",
    marginBottom: 10,
  },
  sheetHint: {
    ...type.tiny,
    color: colors.onSurfaceTertiary,
    marginTop: 8,
    textAlign: "center",
  },
  label: {
    ...type.tiny,
    color: colors.onSurfaceTertiary,
    fontWeight: "700",
    textTransform: "uppercase",
    marginTop: 8,
    marginBottom: 4,
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
  chipsWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
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
  chipTxt: {
    fontSize: 12,
    color: colors.brandPrimary,
    fontWeight: "600",
  },
  chipTxtActive: { color: "#fff" },
  chipCount: {
    marginLeft: 6,
    fontSize: 10,
    color: colors.brandPrimary,
    fontWeight: "700",
  },

  onrollRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.divider,
    marginTop: spacing.sm,
    marginBottom: spacing.sm,
  },
  toggleTrack: {
    width: 44,
    height: 26,
    borderRadius: 13,
    backgroundColor: colors.borderStrong,
    padding: 2,
    justifyContent: "center",
  },
  toggleTrackOn: { backgroundColor: colors.brandPrimary },
  toggleKnob: {
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: "#fff",
  },
  toggleKnobOn: { alignSelf: "flex-end" },

  // ---- Textile master card ----
  textileVariantPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 12,
    backgroundColor: colors.brandTertiary,
  },
  textileVariantPillTxt: {
    color: colors.brandPrimary,
    fontWeight: "700",
    fontSize: 11,
  },
  fieldLabel: {
    ...type.tiny,
    color: colors.onSurfaceSecondary,
    fontWeight: "700",
    marginTop: spacing.sm,
    marginBottom: 4,
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  fieldHint: {
    ...type.caption,
    color: colors.onSurfaceTertiary,
    marginBottom: 6,
    lineHeight: 16,
  },
  selectField: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 12,
    backgroundColor: colors.surface,
  },
  selectFieldTxt: {
    color: colors.onSurface,
    fontSize: 14,
    fontWeight: "600",
    flex: 1,
  },
  triStateRow: {
    flexDirection: "row",
    gap: 6,
    marginBottom: 4,
  },
  triChip: {
    flex: 1,
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surface,
    alignItems: "center",
  },
  triChipActive: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandPrimary,
  },
  triChipTxt: {
    color: colors.onSurfaceSecondary,
    fontWeight: "600",
    fontSize: 12,
  },
  triChipTxtActive: { color: "#fff" },
  shiftRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: radius.md,
    marginBottom: 4,
  },
  shiftRowTitle: {
    ...type.body,
    color: colors.onSurface,
    fontWeight: "600",
  },
  shiftRowSub: {
    ...type.caption,
    color: colors.onSurfaceSecondary,
    marginTop: 1,
  },
});
