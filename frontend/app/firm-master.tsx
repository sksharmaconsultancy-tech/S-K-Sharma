/**
 * Iter 89 — Firm Master (Web Portal only).
 *
 * Comprehensive firm profile screen migrated from the user's legacy
 * Windows application. 17 sections stacked in a single scrollable form;
 * every section persists via PATCH /api/admin/firm-master/{company_id}.
 *
 * Non-web platforms are redirected — this screen is desktop-only per the
 * client's requirement.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Platform, Switch, Image,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import PolicyVariantPicker from "@/src/components/PolicyVariantPicker";
import PolicyMasterSummary from "@/src/components/PolicyMasterSummary";
import useEnterNav from "@/src/hooks/useEnterNav";
import useSaveShortcut from "@/src/hooks/useSaveShortcut";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import DateField from "@/src/components/DateField";
import { colors, radius, spacing, type } from "@/src/theme";

type Master = any;
type Catalogs = {
  allowance_labels: string[];
  deduction_labels: string[];
  compliance_doc_labels: string[];
  portal_login_labels: string[];
  salary_structures: string[];
  report_order_options: string[];
};

/* -------------------------------------------------------------------- */
/*  Small reusable primitives                                           */
/* -------------------------------------------------------------------- */

function Field({
  label, value, onChange, placeholder, keyboardType, secure, width, maxLength, disabled,
}: {
  label: string;
  value: string | null | undefined;
  onChange: (v: string) => void;
  placeholder?: string;
  keyboardType?: "default" | "numeric" | "email-address" | "phone-pad";
  secure?: boolean;
  width?: number | string;
  maxLength?: number;
  disabled?: boolean;
}) {
  return (
    <View style={[styles.field, width ? { width } : { flex: 1, minWidth: 180 }]}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        value={value ?? ""}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={colors.onSurfaceTertiary}
        keyboardType={keyboardType || "default"}
        secureTextEntry={!!secure}
        maxLength={maxLength}
        editable={!disabled}
        style={[styles.input, disabled && { opacity: 0.45, backgroundColor: colors.border }]}
      />
    </View>
  );
}

function Toggle({
  label, value, onChange, testID,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
  testID?: string;
}) {
  return (
    <Pressable
      onPress={() => onChange(!value)}
      style={styles.toggleRow}
      testID={testID}
    >
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ false: colors.border, true: colors.brandPrimary }}
        thumbColor="#FFFFFF"
      />
      <Text style={styles.toggleLbl}>{label}</Text>
    </Pressable>
  );
}

function Section({
  icon, title, children,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <View style={styles.section}>
      <View style={styles.sectionHead}>
        <Ionicons name={icon} size={16} color={colors.brandPrimary} />
        <Text style={styles.sectionTitle}>{title}</Text>
      </View>
      <View style={styles.sectionBody}>{children}</View>
    </View>
  );
}

function Dropdown({
  label, value, options, onChange, width,
}: {
  label: string;
  value: string | null | undefined;
  options: string[];
  onChange: (v: string | null) => void;
  width?: number | string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <View
      style={[
        styles.field,
        width ? { width } : { flex: 1, minWidth: 180 },
      ]}
    >
      <Text style={styles.fieldLabel}>{label}</Text>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        style={[styles.input, styles.dropdownBtn]}
      >
        <Text style={[styles.dropdownTxt, !value && { color: colors.onSurfaceTertiary }]}>
          {value || "— select —"}
        </Text>
        <Ionicons name={open ? "chevron-up" : "chevron-down"} size={14} color={colors.onSurfaceSecondary} />
      </Pressable>
      {open ? (
        <View style={styles.dropdownList}>
          <Pressable
            onPress={() => { onChange(null); setOpen(false); }}
            style={styles.dropdownItem}
          >
            <Text style={[styles.dropdownItemTxt, { fontStyle: "italic" }]}>Clear</Text>
          </Pressable>
          {options.map((opt) => (
            <Pressable
              key={opt}
              onPress={() => { onChange(opt); setOpen(false); }}
              style={[
                styles.dropdownItem,
                value === opt && { backgroundColor: colors.brandTertiary },
              ]}
            >
              <Text style={styles.dropdownItemTxt}>{opt}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

/* -------------------------------------------------------------------- */
/*  Main screen                                                         */
/* -------------------------------------------------------------------- */

// Iter 107 — DateField stores ISO YYYY-MM-DD; legacy firm masters may
// hold DD-MM-YYYY strings. Accept both for display.
function toIsoDate(v: string): string {
  const m = /^(\d{2})-(\d{2})-(\d{4})$/.exec((v || "").trim());
  if (m) return `${m[3]}-${m[2]}-${m[1]}`;
  return v || "";
}

export default function FirmMasterScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ company_id?: string }>();
  const { user } = useAuth();
  const { selectedCompany } = useSelectedCompany();

  // Non-web platforms redirect back — this is a desktop-only screen.
  useEffect(() => {
    if (Platform.OS !== "web") {
      router.replace("/(tabs)");
    }
  }, [router]);

  const isSuper = user?.role === "super_admin";
  const [companyId, setCompanyId] = useState<string | null>(
    (params?.company_id as string) ||
    (isSuper ? (selectedCompany?.company_id || null) : (user?.company_id || null)),
  );
  // Iter 107 — PIN code → auto-fill State & District (India Post data).
  const lookupPin = useCallback(async (
    section: "registered_address" | "office_address" | "factory_address",
    pin: string,
  ) => {
    if (!/^\d{6}$/.test(pin)) return;
    try {
      const r = await api<{ ok: boolean; state: string; district: string }>(`/pincode/${pin}`);
      if (r.ok) {
        setMaster((m: any) => {
          if (!m) return m;
          const sec = { ...(m[section] || {}) };
          sec.state = r.state || sec.state;
          if (!(sec.city || "").trim()) sec.city = r.district || "";
          return { ...m, [section]: sec };
        });
        setDirty(true);
      }
    } catch {}
  }, []);

  // Iter 105 — the firm list loads async, so `selectedCompany` is often
  // still null on first render. Adopt the locked/selected firm as soon as
  // it becomes available instead of dead-ending on the "Pick a Firm" gate.
  useEffect(() => {
    if (!companyId && selectedCompany?.company_id) {
      setCompanyId(selectedCompany.company_id);
    }
  }, [companyId, selectedCompany?.company_id]);
  const [master, setMaster] = useState<Master | null>(null);
  const [catalogs, setCatalogs] = useState<Catalogs | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  // Iter 175 — Policy variant mirrored from PolicyVariantPicker so the
  // Contractor Employees section only shows for Policy 2 firms.
  const [policyVariant, setPolicyVariant] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      const r = await api<{ master: Master; catalogs: Catalogs }>(
        `/admin/firm-master/${companyId}`,
      );
      setMaster(r.master);
      setCatalogs(r.catalogs);
      setDirty(false);
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const update = (patch: Partial<Master>) => {
    setMaster((prev: Master) => ({ ...(prev || {}), ...patch }));
    setDirty(true);
  };
  const updateSection = (section: string, patch: Record<string, any>) => {
    setMaster((prev: Master) => ({
      ...(prev || {}),
      [section]: { ...(prev?.[section] || {}), ...patch },
    }));
    setDirty(true);
  };

  // Iter 108 — Enter jumps to the next field; Enter on the LAST field saves.
  useEnterNav(() => { void save(); });
  // Iter 110 — Ctrl+S / Cmd+S saves.
  useSaveShortcut(() => { void save(); });

  const save = async () => {
    if (!companyId || !master) return;
    setSaving(true);    try {
      await api(`/admin/firm-master/${companyId}`, {
        method: "PATCH",
        body: master,
      });
      setDirty(false);
      // Iter 110 — after Save, reload and land on the Dashboard.
      if (Platform.OS === "web") {
        window.alert("Firm Master saved ✓");
        window.location.href = "/";
      } else {
        router.replace("/(tabs)");
      }
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  // ---------- Same-as-firm mirroring for Office/Factory addresses ----------
  const mirrorAddress = (target: "office_address" | "factory_address", flag: boolean) => {
    updateSection(target, {
      same_as_firm: flag,
      ...(flag && master?.registered_address ? master.registered_address : {}),
    });
  };

  // ---------- Contact persons repeatable rows ----------
  const addContact = () => {
    const rows = [...(master?.contact_persons || []), { name: "", mobile: "", position: "" }];
    update({ contact_persons: rows });
  };
  const removeContact = (idx: number) => {
    const rows = [...(master?.contact_persons || [])];
    rows.splice(idx, 1);
    update({ contact_persons: rows });
  };
  const editContact = (idx: number, patch: Record<string, any>) => {
    const rows = [...(master?.contact_persons || [])];
    rows[idx] = { ...(rows[idx] || {}), ...patch };
    update({ contact_persons: rows });
  };

  // ---------- Iter 175 — Contractor Employees (Policy 2) repeatable rows ----------
  const addContractor = () => {
    const rows = [...(master?.contractors || []), { name: "", father_name: "", from_date: null, to_date: null }];
    update({ contractors: rows });
  };
  const removeContractor = (idx: number) => {
    const rows = [...(master?.contractors || [])];
    rows.splice(idx, 1);
    update({ contractors: rows });
  };
  const editContractor = (idx: number, patch: Record<string, any>) => {
    const rows = [...(master?.contractors || [])];
    rows[idx] = { ...(rows[idx] || {}), ...patch };
    update({ contractors: rows });
  };

  // ---------- Compliance docs & portal logins are FIXED row edits ----------
  const editComplianceRow = (idx: number, patch: Record<string, any>) => {
    const rows = [...(master?.compliance_docs || [])];
    rows[idx] = { ...(rows[idx] || {}), ...patch };
    update({ compliance_docs: rows });
  };
  const editLoginRow = (idx: number, patch: Record<string, any>) => {
    const rows = [...(master?.portal_logins || [])];
    rows[idx] = { ...(rows[idx] || {}), ...patch };
    update({ portal_logins: rows });
  };

  // Iter 89 — Web-only file picker for the firm logo. Reads the chosen
  // image as a base64 data URL so it can be persisted directly on the
  // firm_master doc and mirrored to ``companies.logo_base64``.
  const pickLogo = () => {
    if (Platform.OS !== "web") return;
    const input = (globalThis as any).document?.createElement?.("input");
    if (!input) return;
    input.type = "file";
    input.accept = "image/png,image/jpeg,image/webp";
    input.onchange = (e: any) => {
      const file = e?.target?.files?.[0];
      if (!file) return;
      // Cap at 2 MB so payloads stay small and Mongo doc size stays sane.
      if (file.size > 2 * 1024 * 1024) {
        window.alert("Logo must be under 2 MB. Please resize and try again.");
        return;
      }
      const reader = new (globalThis as any).FileReader();
      reader.onloadend = () => {
        const dataUrl: string = reader.result;
        updateSection("logo", {
          image_base64: dataUrl,
          mime_type: file.type,
        });
      };
      reader.readAsDataURL(file);
    };
    input.click();
  };
  const clearLogo = () => {
    updateSection("logo", { image_base64: null, mime_type: null });
  };

  if (Platform.OS !== "web") return null;

  if (!companyId) {
    return (
      <View style={styles.root}>
        <View style={styles.emptyState}>
          <Ionicons name="business-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyTitle}>Pick a Firm to edit its master</Text>
          <View style={{ marginTop: spacing.md }}>
            <CompanyPicker
              value={null}
              onChange={(id) => setCompanyId(id || null)}
            />
          </View>
        </View>
      </View>
    );
  }

  if (loading || !master || !catalogs) {
    return (
      <View style={styles.root}>
        <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
      </View>
    );
  }

  const h = master.header || {};
  const ra = master.registered_address || {};
  const oa = master.office_address || {};
  const fa = master.factory_address || {};
  const bank = master.bank || {};
  const st = master.settings || {};
  const sp = master.salary_process || {};
  const lp = master.leave_policy || {};
  const epf = master.epf || {};
  const esi = master.esi || {};
  const bonus = master.bonus || {};

  return (
    <View style={styles.root}>
      {/* Header bar */}
      <View style={styles.pageHead}>
        <View>
          <Text style={styles.h1}>Firm Master</Text>
          <Text style={styles.h1sub}>
            {master.company_name || "—"} · {isSuper ? "Super Admin" : "Company Admin"}
          </Text>
        </View>
        <View style={{ flexDirection: "row", gap: 10, alignItems: "center" }}>
          {isSuper ? (
            <CompanyPicker
              value={companyId}
              onChange={(id) => id && setCompanyId(id)}
            />
          ) : null}
          <Pressable
            onPress={save}
            disabled={saving || !dirty}
            style={({ pressed }) => [
              styles.saveBtn,
              (saving || !dirty) && { opacity: 0.5 },
              pressed && { opacity: 0.85 },
            ]}
            testID="firm-master-save"
          >
            {saving ? (
              <ActivityIndicator size="small" color="#FFF" />
            ) : (
              <Ionicons name="save-outline" size={16} color="#FFF" />
            )}
            <Text style={styles.saveBtnTxt}>
              {saving ? "Saving..." : dirty ? "Save Changes" : "Saved"}
            </Text>
          </Pressable>
        </View>
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* 0. Firm Logo (synced with app + portal shell) --------------- */}
        <Section icon="image-outline" title="Firm Logo (Portal + App)">
          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.lg, flexWrap: "wrap" }}>
            <View style={styles.logoPreview}>
              {master.logo?.image_base64 ? (
                <Image
                  source={{ uri: master.logo.image_base64 }}
                  style={styles.logoImg}
                  resizeMode="contain"
                />
              ) : (
                <Ionicons name="business-outline" size={44} color={colors.onSurfaceTertiary} />
              )}
            </View>
            <View style={{ flex: 1, minWidth: 240, gap: 8 }}>
              <Text style={styles.logoHelp}>
                Upload the firm logo. It appears on the Web Portal sidebar, the
                mobile app header, salary slips, and email attachments.
                PNG / JPEG / WebP, max 2 MB. Recommended: square 512×512.
              </Text>
              <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                <Pressable onPress={pickLogo} style={styles.logoBtn}>
                  <Ionicons name="cloud-upload-outline" size={14} color={colors.brandPrimary} />
                  <Text style={styles.logoBtnTxt}>
                    {master.logo?.image_base64 ? "Replace Logo" : "Upload Logo"}
                  </Text>
                </Pressable>
                {master.logo?.image_base64 ? (
                  <Pressable onPress={clearLogo} style={[styles.logoBtn, { borderColor: "#FCA5A5" }]}>
                    <Ionicons name="trash-outline" size={14} color={colors.error} />
                    <Text style={[styles.logoBtnTxt, { color: colors.error }]}>Remove</Text>
                  </Pressable>
                ) : null}
              </View>
            </View>
          </View>
        </Section>

        {/* 1. Firm Header ------------------------------------------------ */}
        <Section icon="ribbon-outline" title="1. Firm Header">
          <View style={styles.row}>
            <View style={{ flex: 1, minWidth: 180 }}>
              <Text style={styles.fieldLabel}>Firm Start Date</Text>
              <DateField
                value={toIsoDate(h.start_date || "")}
                onChangeISO={(v) => updateSection("header", { start_date: v })}
                placeholder="DD-MM-YYYY"
              />
            </View>
            <Field label="Firm Category" value={h.category}
                   onChange={(v) => updateSection("header", { category: v })} />
            <Field label="Business Nature" value={h.business_nature}
                   onChange={(v) => updateSection("header", { business_nature: v })} />
          </View>
          <View style={styles.row}>
            <Field label="Firm Email" value={h.email_1}
                   onChange={(v) => updateSection("header", { email_1: v })}
                   keyboardType="email-address" />
            <Field label="Email 2" value={h.email_2}
                   onChange={(v) => updateSection("header", { email_2: v })}
                   keyboardType="email-address" />
          </View>
        </Section>

        {/* 2. Firm Registered Details ------------------------------------ */}
        <Section icon="location-outline" title="2. Firm Registered Details">
          <View style={styles.row}>
            <Field label="Address 1" value={ra.address1}
                   onChange={(v) => updateSection("registered_address", { address1: v })} />
            <Field label="Address 2" value={ra.address2}
                   onChange={(v) => updateSection("registered_address", { address2: v })} />
          </View>
          <View style={styles.row}>
            <Field label="City Name" value={ra.city}
                   onChange={(v) => updateSection("registered_address", { city: v })} />
            <Field label="State Name" value={ra.state}
                   onChange={(v) => updateSection("registered_address", { state: v })} />
            <Field label="Pin Code" value={ra.pin_code}
                   onChange={(v) => {
                     updateSection("registered_address", { pin_code: v });
                     void lookupPin("registered_address", v);
                   }}
                   keyboardType="numeric" width={160} />
          </View>
        </Section>

        {/* 3. Office & 4. Factory Address (side-by-side on wide screens) - */}
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
          <View style={{ flex: 1, minWidth: 380 }}>
            <Section icon="business-outline" title="3. Office Address">
              <Toggle
                label="Same as Firm Address"
                value={!!oa.same_as_firm}
                onChange={(v) => mirrorAddress("office_address", v)}
              />
              <View style={styles.row}>
                <Field label="Address 1" value={oa.address1}
                       onChange={(v) => updateSection("office_address", { address1: v, same_as_firm: false })} />
                <Field label="Address 2" value={oa.address2}
                       onChange={(v) => updateSection("office_address", { address2: v, same_as_firm: false })} />
              </View>
              <View style={styles.row}>
                <Field label="City" value={oa.city}
                       onChange={(v) => updateSection("office_address", { city: v, same_as_firm: false })} />
                <Field label="State Name" value={oa.state}
                       onChange={(v) => updateSection("office_address", { state: v, same_as_firm: false })} />
                <Field label="Pin Code" value={oa.pin_code}
                       onChange={(v) => {
                         updateSection("office_address", { pin_code: v, same_as_firm: false });
                         void lookupPin("office_address", v);
                       }}
                       keyboardType="numeric" width={140} />
              </View>
            </Section>
          </View>
          <View style={{ flex: 1, minWidth: 380 }}>
            <Section icon="business" title="4. Factory Address">
              <Toggle
                label="Same as Firm Address"
                value={!!fa.same_as_firm}
                onChange={(v) => mirrorAddress("factory_address", v)}
              />
              <View style={styles.row}>
                <Field label="Address 1" value={fa.address1}
                       onChange={(v) => updateSection("factory_address", { address1: v, same_as_firm: false })} />
                <Field label="Address 2" value={fa.address2}
                       onChange={(v) => updateSection("factory_address", { address2: v, same_as_firm: false })} />
              </View>
              <View style={styles.row}>
                <Field label="City Name" value={fa.city}
                       onChange={(v) => updateSection("factory_address", { city: v, same_as_firm: false })} />
                <Field label="State Name" value={fa.state}
                       onChange={(v) => updateSection("factory_address", { state: v, same_as_firm: false })} />
                <Field label="Pin Code" value={fa.pin_code}
                       onChange={(v) => {
                         updateSection("factory_address", { pin_code: v, same_as_firm: false });
                         void lookupPin("factory_address", v);
                       }}
                       keyboardType="numeric" width={140} />
              </View>
            </Section>
          </View>
        </View>

        {/* 5. Allowances & 6. Deductions --------------------------------- */}
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
          <View style={{ flex: 1, minWidth: 300 }}>
            <Section icon="add-circle-outline" title="5. Allowances (Master-linked)">
              <Text style={styles.masterLinkHint}>
                Toggle any allowance head to enable it for this firm. Custom
                heads added via Masters → Allowances appear here automatically.
              </Text>
              {catalogs.allowance_labels.map((lab) => (
                <Toggle
                  key={lab}
                  label={lab}
                  value={!!master.allowances?.[lab]}
                  onChange={(v) => updateSection("allowances", { [lab]: v })}
                  testID={`allowance-${lab}`}
                />
              ))}
              {Platform.OS === "web" ? (
                <Pressable
                  onPress={() => router.push("/masters" as any)}
                  style={styles.masterLinkBtn}
                >
                  <Ionicons name="add-circle-outline" size={12} color={colors.brandPrimary} />
                  <Text style={styles.masterLinkBtnTxt}>+ Add allowance head in Masters</Text>
                </Pressable>
              ) : null}
            </Section>
          </View>
          <View style={{ flex: 1, minWidth: 300 }}>
            <Section icon="remove-circle-outline" title="6. Deductions (Master-linked)">
              <Text style={styles.masterLinkHint}>
                Toggle any deduction head to enable it for this firm. Custom
                heads added via Masters → Deductions appear here automatically.
              </Text>
              {catalogs.deduction_labels.map((lab) => (
                <Toggle
                  key={lab}
                  label={lab}
                  value={!!master.deductions?.[lab]}
                  onChange={(v) => updateSection("deductions", { [lab]: v })}
                  testID={`deduction-${lab}`}
                />
              ))}
              {Platform.OS === "web" ? (
                <Pressable
                  onPress={() => router.push("/masters" as any)}
                  style={styles.masterLinkBtn}
                >
                  <Ionicons name="add-circle-outline" size={12} color={colors.brandPrimary} />
                  <Text style={styles.masterLinkBtnTxt}>+ Add deduction head in Masters</Text>
                </Pressable>
              ) : null}
            </Section>
          </View>
          <View style={{ flex: 1, minWidth: 300 }}>
            <Section icon="card-outline" title="7. Bank Details">
              <Field label="Account No." value={bank.account_no}
                     onChange={(v) => updateSection("bank", { account_no: v })}
                     keyboardType="numeric" />
              <Field label="Account Name" value={bank.account_name}
                     onChange={(v) => updateSection("bank", { account_name: v })} />
              <Field label="Bank Name" value={bank.bank_name}
                     onChange={(v) => updateSection("bank", { bank_name: v })} />
              <Field label="Branch Name" value={bank.branch_name}
                     onChange={(v) => updateSection("bank", { branch_name: v })} />
              <Field label="IFSC" value={bank.ifsc}
                     onChange={(v) => updateSection("bank", { ifsc: v.toUpperCase() })} />
            </Section>
          </View>
        </View>

        {/* 8. Firm Settings --------------------------------------------- */}
        <Section icon="settings-outline" title="8. Firm Settings">
          <View style={styles.row}>
            <Dropdown
              label="Salary Structure"
              value={st.salary_structure}
              options={catalogs.salary_structures}
              onChange={(v) => updateSection("settings", { salary_structure: v })}
              width={260}
            />
            <Field label="Reference By" value={st.reference_by}
                   onChange={(v) => updateSection("settings", { reference_by: v })} />
          </View>
          <View style={styles.rowWrap}>
            <Toggle label="Firm Active" value={!!st.firm_active}
                    onChange={(v) => updateSection("settings", { firm_active: v })} />
            <Toggle label="WhatsApp Enable" value={!!st.whatsapp_enable}
                    onChange={(v) => updateSection("settings", { whatsapp_enable: v })} />
            <Toggle label="Auto E-Mail Process" value={!!st.auto_email_process}
                    onChange={(v) => updateSection("settings", { auto_email_process: v })} />
            <Toggle label="eMail Enable" value={!!st.email_enable}
                    onChange={(v) => updateSection("settings", { email_enable: v })} />
            <Toggle label="Allow CategoryRate" value={!!st.allow_category_rate}
                    onChange={(v) => updateSection("settings", { allow_category_rate: v })} />
            <Toggle label="Auto Employee Code (lock manual entry)" value={!!st.auto_employee_code}
                    onChange={(v) => updateSection("settings", { auto_employee_code: v })} />
          </View>

          {/* Iter 91 — Attendance Policy selection (MANDATORY, pick one).
              The chosen policy is shown on every employee's Master page. */}
          <Text style={[styles.subLbl, { marginTop: 10 }]}>
            Attendance Policy (mandatory — select one)
          </Text>
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            {([
              {
                key: "standard",
                title: "Standard Policy",
                sub: "Non-textile · 09:00–18:00 · Sunday off · OT beyond 8 hrs @1.5×",
              },
              {
                key: "textile",
                title: "Textile Policy",
                sub: "12-hr rotational shifts · textile-industry variant",
              },
            ] as const).map((p) => {
              const on = (st.attendance_policy_preset || "") === p.key;
              return (
                <Pressable
                  key={p.key}
                  onPress={() => updateSection("settings", { attendance_policy_preset: p.key })}
                  style={[
                    {
                      flex: 1, minWidth: 220, borderWidth: 2, borderRadius: 10,
                      padding: 12, gap: 2,
                      borderColor: on ? colors.brandPrimary : colors.border,
                      backgroundColor: on ? "#EEF2FF" : colors.surface,
                    },
                  ]}
                  testID={`fm-policy-${p.key}`}
                >
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Ionicons
                      name={on ? "radio-button-on" : "radio-button-off"}
                      size={16}
                      color={on ? colors.brandPrimary : colors.onSurfaceTertiary}
                    />
                    <Text style={{ fontSize: 13, fontWeight: "800", color: on ? colors.brandPrimary : colors.onSurface }}>
                      {p.title}
                    </Text>
                  </View>
                  <Text style={{ fontSize: 11, color: colors.onSurfaceSecondary }}>{p.sub}</Text>
                </Pressable>
              );
            })}
          </View>
          {!st.attendance_policy_preset ? (
            <Text style={{ fontSize: 11, color: colors.error, marginTop: 4 }}>
              ⚠ No policy selected yet — pick Standard or Textile and save.
            </Text>
          ) : null}
        </Section>

        {/* 9. Contact Persons ------------------------------------------- */}
        <Section icon="people-outline" title="9. Contact Persons">
          <View style={styles.gridHead}>
            <Text style={[styles.gridHeadCell, { flex: 2 }]}>Contact Person Name</Text>
            <Text style={[styles.gridHeadCell, { flex: 1.5 }]}>Mobile No</Text>
            <Text style={[styles.gridHeadCell, { flex: 1.5 }]}>Position</Text>
            <Text style={[styles.gridHeadCell, { width: 60 }]}> </Text>
          </View>
          {(master.contact_persons || []).map((row: any, idx: number) => (
            <View key={idx} style={styles.gridRow}>
              <TextInput
                style={[styles.gridInput, { flex: 2 }]}
                value={row.name || ""}
                onChangeText={(v) => editContact(idx, { name: v })}
              />
              <TextInput
                style={[styles.gridInput, { flex: 1.5 }]}
                value={row.mobile || ""}
                onChangeText={(v) => editContact(idx, { mobile: v })}
                keyboardType="phone-pad"
              />
              <TextInput
                style={[styles.gridInput, { flex: 1.5 }]}
                value={row.position || ""}
                onChangeText={(v) => editContact(idx, { position: v })}
              />
              <Pressable
                onPress={() => removeContact(idx)}
                style={styles.rowDelBtn}
              >
                <Ionicons name="trash-outline" size={14} color={colors.error} />
              </Pressable>
            </View>
          ))}
          <Pressable onPress={addContact} style={styles.addRowBtn}>
            <Ionicons name="add-circle-outline" size={14} color={colors.brandPrimary} />
            <Text style={styles.addRowTxt}>Add Contact</Text>
          </Pressable>
        </Section>

        {/* 10-15. Payroll blocks --------------------------------------- */}
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
          <View style={{ flex: 1, minWidth: 380 }}>
            <Section icon="time-outline" title="10a. Attendance Policy Variant">
              {/* Iter 175 (user rule) — the Policy Selection option only
                  shows when an Industry Type is selected AND Off-roll
                  (Offline) Salary AND Biometric Attendance are enabled. */}
              {(h.category || "").trim() && sp.offline_salary && sp.bio_matrix_attendance ? (
                <PolicyVariantPicker companyId={companyId} onVariantChange={setPolicyVariant} />
              ) : (
                <Text style={{ fontSize: 11.5, color: colors.onSurfaceTertiary }}>
                  Policy selection unlocks when: ① Industry Type is selected
                  (Firm Category), ② Offline Salary is enabled and ③ Bio Matrix
                  Attendance is enabled in Salary Process Settings.
                </Text>
              )}
              <PolicyMasterSummary companyId={companyId} />
            </Section>

            {/* Iter 175 — Contractor Employees (Policy 2 only). */}
            {policyVariant === "policy_2" ? (
              <Section icon="briefcase-outline" title="10b. Contractor Employees (Policy 2)">
                <Toggle
                  label="Contractual (Contractor) Employees Applicable"
                  value={!!st.contractor_employees}
                  testID="fm-contractor-toggle"
                  onChange={(v) => updateSection("settings", { contractor_employees: v })}
                />
                {st.contractor_employees ? (
                  <View style={{ marginTop: 10 }}>
                    <View style={styles.gridHead}>
                      <Text style={[styles.gridHeadCell, { flex: 2 }]}>Contractor Name</Text>
                      <Text style={[styles.gridHeadCell, { flex: 2 }]}>Father Name</Text>
                      <Text style={[styles.gridHeadCell, { flex: 1.6 }]}>Contract From</Text>
                      <Text style={[styles.gridHeadCell, { flex: 1.6 }]}>Contract To</Text>
                      <Text style={[styles.gridHeadCell, { width: 40 }]}> </Text>
                    </View>
                    {(master.contractors || []).map((row: any, idx: number) => (
                      <View key={idx} style={[styles.gridRow, { alignItems: "center" }]}>
                        <TextInput
                          style={[styles.gridInput, { flex: 2 }]}
                          value={row.name || ""}
                          placeholder="Contractor name"
                          placeholderTextColor={colors.onSurfaceTertiary}
                          onChangeText={(v) => editContractor(idx, { name: v })}
                          testID={`fm-contractor-name-${idx}`}
                        />
                        <TextInput
                          style={[styles.gridInput, { flex: 2 }]}
                          value={row.father_name || ""}
                          placeholder="Father name"
                          placeholderTextColor={colors.onSurfaceTertiary}
                          onChangeText={(v) => editContractor(idx, { father_name: v })}
                          testID={`fm-contractor-father-${idx}`}
                        />
                        <View style={{ flex: 1.6 }}>
                          <DateField
                            value={toIsoDate(row.from_date || "")}
                            onChangeISO={(v) => editContractor(idx, { from_date: v })}
                            compact
                            testID={`fm-contractor-from-${idx}`}
                          />
                        </View>
                        <View style={{ flex: 1.6 }}>
                          <DateField
                            value={toIsoDate(row.to_date || "")}
                            onChangeISO={(v) => editContractor(idx, { to_date: v })}
                            min={toIsoDate(row.from_date || "") || undefined}
                            compact
                            testID={`fm-contractor-to-${idx}`}
                          />
                        </View>
                        <Pressable
                          onPress={() => removeContractor(idx)}
                          style={styles.rowDelBtn}
                          testID={`fm-contractor-del-${idx}`}
                        >
                          <Ionicons name="trash-outline" size={14} color={colors.error} />
                        </Pressable>
                      </View>
                    ))}
                    <Pressable onPress={addContractor} style={styles.addRowBtn} testID="fm-contractor-add">
                      <Ionicons name="add-circle-outline" size={14} color={colors.brandPrimary} />
                      <Text style={styles.addRowTxt}>Add More Contractors</Text>
                    </Pressable>
                  </View>
                ) : null}
              </Section>
            ) : null}

            <Section icon="cash-outline" title="10. Salary Process Settings">
              <View style={styles.rowWrap}>
                <Toggle label="Online Salary → Compliance Salary Process" value={!!sp.online_salary} testID="fm-online-salary"
                        onChange={(v) => updateSection("salary_process", { online_salary: v })} />
                <Toggle label="Offline Salary → Actual Salary Process" value={!!sp.offline_salary} testID="fm-offline-salary"
                        onChange={(v) =>
                          // Iter 98 — enabling Offline Salary also switches
                          // ON Bio Matrix Attendance (per user rule).
                          // Iter 114 — disabling it also FORCES Bio Matrix
                          // OFF (biometric requires Actual Salary).
                          updateSection("salary_process", v
                            ? { offline_salary: true, bio_matrix_attendance: true }
                            : { offline_salary: false, bio_matrix_attendance: false })
                        } />
                <Toggle label="Bio Matrix Attendance" value={!!sp.bio_matrix_attendance} testID="fm-bio-matrix"
                        onChange={(v) => {
                          // Iter 114 — biometric can only be toggled when
                          // Actual (Offline) Salary is allowed.
                          if (!sp.offline_salary) {
                            if (Platform.OS === "web") window.alert("Enable Offline Salary (Actual Salary Process) first to allow Bio Matrix Attendance.");
                            return;
                          }
                          updateSection("salary_process", { bio_matrix_attendance: v });
                        }} />
                <Toggle label="Gratuity Applicable" value={!!sp.gratuity_applicable}
                        onChange={(v) => updateSection("salary_process", { gratuity_applicable: v })} />
                {/* Iter 142 — firm-wide OT gate. OFF = NO overtime is
                    calculated for ANY employee of this firm. */}
                <Toggle label="Overtime (OT) Allowed" value={sp.ot_allowed !== false} testID="fm-ot-allowed"
                        onChange={(v) => updateSection("salary_process", { ot_allowed: v })} />
              </View>
              {/* Iter 110 — Online Process Days is LINKED to the Compliance
                  Salary Process; Offline Process Days is LINKED to the Actual
                  Salary Process. Each Days field is enabled only when its
                  linked salary toggle is ON. */}
              <View style={styles.row}>
                <Field label="Online Process Days (Compliance Salary)" value={String(sp.online_process_days ?? "")}
                       onChange={(v) => updateSection("salary_process", { online_process_days: Number(v.replace(/[^0-9]/g, "")) || 0 })}
                       keyboardType="numeric" width={260} disabled={!sp.online_salary} />
                <Field label="Offline Process Days (Actual Salary)" value={String(sp.offline_process_days ?? "")}
                       onChange={(v) => updateSection("salary_process", { offline_process_days: Number(v.replace(/[^0-9]/g, "")) || 0 })}
                       keyboardType="numeric" width={260} disabled={!sp.offline_salary} />
              </View>
              <Text style={styles.linkHint}>
                Online Salary controls the Compliance Salary Process · Offline
                Salary controls the Actual Salary Process. Turn a toggle ON to
                edit its linked Process Days.
              </Text>
              {/* Iter 98 — OT rate basis for Salary Process (Actual) */}
              <Text style={styles.subLbl}>OT Calculation On</Text>
              <View style={{ flexDirection: "row", gap: 8 }}>
                {[["basic", "Basic"], ["gross", "Gross"]].map(([val, lab]) => (
                  <Pressable
                    key={val}
                    onPress={() => updateSection("salary_process", { ot_calc_basis: val })}
                    style={[
                      styles.radioChip,
                      (sp.ot_calc_basis || "basic") === val && styles.radioChipActive,
                    ]}
                    testID={`fm-ot-basis-${val}`}
                  >
                    <Ionicons
                      name={(sp.ot_calc_basis || "basic") === val ? "radio-button-on" : "radio-button-off"}
                      size={14}
                      color={(sp.ot_calc_basis || "basic") === val ? colors.brandPrimary : colors.onSurfaceTertiary}
                    />
                    <Text style={styles.radioChipTxt}>{lab}</Text>
                  </Pressable>
                ))}
              </View>
            </Section>
          </View>
          <View style={{ flex: 1, minWidth: 380 }}>
            <Section icon="calendar-outline" title="11. CL / PL Policy">
              <Toggle label="CL/PL Applicable" value={!!lp.cl_pl_applicable}
                      onChange={(v) => updateSection("leave_policy", { cl_pl_applicable: v })} />
              <View style={styles.row}>
                <Field label="CL Day Limit" value={String(lp.cl_day_limit ?? 0)}
                       onChange={(v) => updateSection("leave_policy", { cl_day_limit: Number(v.replace(/[^0-9]/g, "").slice(0, 2)) || 0 })}
                       keyboardType="numeric" width={160} maxLength={2} />
                <Field label="PL Day Limit" value={String(lp.pl_day_limit ?? 0)}
                       onChange={(v) => updateSection("leave_policy", { pl_day_limit: Number(v.replace(/[^0-9]/g, "").slice(0, 2)) || 0 })}
                       keyboardType="numeric" width={160} maxLength={2} />
              </View>
            </Section>
          </View>
        </View>

        {/* 12. EPF & 13. ESI ------------------------------------------- */}
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
          <View style={{ flex: 1, minWidth: 380 }}>
            <Section icon="shield-checkmark-outline" title="12. EPF Details">
              <Toggle label="EPF Applicable" value={!!epf.applicable}
                      onChange={(v) => updateSection("epf", { applicable: v })} />
              <View style={styles.row}>
                <View style={{ flex: 1, minWidth: 180 }}>
                  <Text style={styles.fieldLabel}>Applicable Date</Text>
                  <DateField value={toIsoDate(epf.applicable_date || "")} onChangeISO={(v) => updateSection("epf", { applicable_date: v })} />
                </View>
                <Toggle label="EDLI Applicable" value={!!epf.edli_applicable}
                        onChange={(v) => updateSection("epf", { edli_applicable: v })} />
              </View>
              <View style={styles.row}>
                <Field label="EPF No." value={epf.epf_no}
                       onChange={(v) => updateSection("epf", { epf_no: v })} />
                <Field label="Group Policy No." value={epf.group_policy_no}
                       onChange={(v) => updateSection("epf", { group_policy_no: v })} />
              </View>
              <View style={styles.row}>
                <Field label="EPF User ID" value={epf.epf_user_id}
                       onChange={(v) => updateSection("epf", { epf_user_id: v })} />
                <Field label="EPF Password" value={epf.epf_password}
                       onChange={(v) => updateSection("epf", { epf_password: v })}
                       secure />
              </View>
            </Section>
          </View>
          <View style={{ flex: 1, minWidth: 380 }}>
            <Section icon="medkit-outline" title="13. ESI Details">
              <Toggle label="ESI Applicable" value={!!esi.applicable}
                      onChange={(v) => updateSection("esi", { applicable: v })} />
              <View style={styles.row}>
                <View style={{ flex: 1, minWidth: 180 }}>
                  <Text style={styles.fieldLabel}>Applicable Date</Text>
                  <DateField value={toIsoDate(esi.applicable_date || "")} onChangeISO={(v) => updateSection("esi", { applicable_date: v })} />
                </View>
                <Field label="ESI Rate (%)" value={String(esi.esi_rate ?? 1)}
                       onChange={(v) => updateSection("esi", { esi_rate: Number(v) || 0 })}
                       keyboardType="numeric" width={140} />
              </View>
              <Field label="ESI No." value={esi.esi_no}
                     onChange={(v) => updateSection("esi", { esi_no: v })} />
              <View style={styles.row}>
                <Field label="ESI User ID" value={esi.esi_user_id}
                       onChange={(v) => updateSection("esi", { esi_user_id: v })} />
                <Field label="ESI Password" value={esi.esi_password}
                       onChange={(v) => updateSection("esi", { esi_password: v })}
                       secure />
              </View>
            </Section>
          </View>
        </View>

        {/* 14. Bonus & 15. Report Order --------------------------------- */}
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
          <View style={{ flex: 1, minWidth: 380 }}>
            <Section icon="gift-outline" title="14. Bonus Settings">
              <Toggle label="Monthly Bonus" value={!!bonus.monthly_bonus}
                      onChange={(v) => updateSection("bonus", { monthly_bonus: v })} />
              <View style={styles.rowWrap}>
                <Pressable onPress={() => updateSection("bonus", { gross_mode: "including" })}
                           style={[styles.radio, bonus.gross_mode === "including" && styles.radioOn]}>
                  <Ionicons name={bonus.gross_mode === "including" ? "radio-button-on" : "radio-button-off"}
                            size={14} color={colors.brandPrimary} />
                  <Text style={styles.radioTxt}>Including Gross</Text>
                </Pressable>
                <Pressable onPress={() => updateSection("bonus", { gross_mode: "excluding" })}
                           style={[styles.radio, bonus.gross_mode === "excluding" && styles.radioOn]}>
                  <Ionicons name={bonus.gross_mode === "excluding" ? "radio-button-on" : "radio-button-off"}
                            size={14} color={colors.brandPrimary} />
                  <Text style={styles.radioTxt}>Excluding Gross</Text>
                </Pressable>
              </View>
              <Toggle label="Overtime in Report" value={!!bonus.overtime_in_report}
                      onChange={(v) => updateSection("bonus", { overtime_in_report: v })} />
              <View style={styles.rowWrap}>
                <Pressable onPress={() => updateSection("bonus", { days_mode: "fix" })}
                           style={[styles.radio, bonus.days_mode === "fix" && styles.radioOn]}>
                  <Ionicons name={bonus.days_mode === "fix" ? "radio-button-on" : "radio-button-off"}
                            size={14} color={colors.brandPrimary} />
                  <Text style={styles.radioTxt}>Fix Days</Text>
                </Pressable>
                <Pressable onPress={() => updateSection("bonus", { days_mode: "custom" })}
                           style={[styles.radio, bonus.days_mode === "custom" && styles.radioOn]}>
                  <Ionicons name={bonus.days_mode === "custom" ? "radio-button-on" : "radio-button-off"}
                            size={14} color={colors.brandPrimary} />
                  <Text style={styles.radioTxt}>Custom Days</Text>
                </Pressable>
                {bonus.days_mode === "custom" ? (
                  <TextInput
                    style={[styles.input, { width: 100 }]}
                    value={String(bonus.custom_days ?? "")}
                    onChangeText={(v) => updateSection("bonus", { custom_days: Number(v) || 0 })}
                    keyboardType="numeric"
                    placeholder="Days"
                  />
                ) : null}
              </View>
            </Section>
          </View>
          <View style={{ flex: 1, minWidth: 380 }}>
            {/* Iter 98 — "15. Report Order" removed per user request. */}
          </View>
        </View>

        {/* 16. Compliance Documents ------------------------------------- */}
        <Section icon="document-text-outline" title="16. Firm Compliance Documents">
          <View style={styles.gridHead}>
            <Text style={[styles.gridHeadCell, { flex: 2 }]}>Description</Text>
            <Text style={[styles.gridHeadCell, { flex: 1.5 }]}>Number</Text>
            <Text style={[styles.gridHeadCell, { flex: 1.2 }]}>Issue Date</Text>
            <Text style={[styles.gridHeadCell, { flex: 1.2 }]}>Expiry Date</Text>
          </View>
          {(master.compliance_docs || []).map((row: any, idx: number) => (
            <View key={idx} style={styles.gridRow}>
              <Text style={[styles.gridReadCell, { flex: 2 }]}>{row.description}</Text>
              <TextInput
                style={[styles.gridInput, { flex: 1.5 }]}
                value={row.number || ""}
                onChangeText={(v) => editComplianceRow(idx, { number: v })}
              />
              <View style={{ flex: 1.2 }}>
                <DateField
                  value={row.issue_date || ""}
                  onChange={(v) => editComplianceRow(idx, { issue_date: v })}
                />
              </View>
              <View style={{ flex: 1.2 }}>
                <DateField
                  value={row.expiry_date || ""}
                  onChange={(v) => editComplianceRow(idx, { expiry_date: v })}
                />
              </View>
            </View>
          ))}
        </Section>

        {/* 17. Portal Login Credentials --------------------------------- */}
        <Section icon="key-outline" title="17. Portal Login Credentials">
          <View style={styles.gridHead}>
            <Text style={[styles.gridHeadCell, { flex: 1.2 }]}>Login Type</Text>
            <Text style={[styles.gridHeadCell, { flex: 1.5 }]}>User Name</Text>
            <Text style={[styles.gridHeadCell, { flex: 1.2 }]}>Password</Text>
            <Text style={[styles.gridHeadCell, { flex: 1.2 }]}>Unit / Location</Text>
            <Text style={[styles.gridHeadCell, { flex: 2 }]}>Login URL</Text>
          </View>
          {(master.portal_logins || []).map((row: any, idx: number) => (
            <View key={idx} style={styles.gridRow}>
              <Text style={[styles.gridReadCell, { flex: 1.2 }]}>{row.login_type}</Text>
              <TextInput
                style={[styles.gridInput, { flex: 1.5 }]}
                value={row.user_name || ""}
                onChangeText={(v) => editLoginRow(idx, { user_name: v })}
              />
              <TextInput
                style={[styles.gridInput, { flex: 1.2 }]}
                value={row.password || ""}
                onChangeText={(v) => editLoginRow(idx, { password: v })}
                secureTextEntry
              />
              <TextInput
                style={[styles.gridInput, { flex: 1.2 }]}
                value={row.unit_location || ""}
                onChangeText={(v) => editLoginRow(idx, { unit_location: v })}
              />
              <TextInput
                style={[styles.gridInput, { flex: 2 }]}
                value={row.login_url || ""}
                onChangeText={(v) => editLoginRow(idx, { login_url: v })}
                placeholder="https://..."
                autoCapitalize="none"
              />
            </View>
          ))}
        </Section>

        {/* Sticky-ish footer */}
        <View style={styles.footer}>
          <Text style={styles.footerTxt}>
            {dirty
              ? "⚠️ Unsaved changes — click Save Changes to persist"
              : "All changes saved"}
          </Text>
          <Pressable
            onPress={save}
            disabled={saving || !dirty}
            style={({ pressed }) => [
              styles.saveBtn,
              (saving || !dirty) && { opacity: 0.5 },
              pressed && { opacity: 0.85 },
            ]}
          >
            {saving ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="save-outline" size={16} color="#FFF" />}
            <Text style={styles.saveBtnTxt}>{saving ? "Saving..." : "Save Changes"}</Text>
          </Pressable>
        </View>
        <View style={{ height: 80 }} />
      </ScrollView>
    </View>
  );
}

/* -------------------------------------------------------------------- */
/*  Styles                                                              */
/* -------------------------------------------------------------------- */

const styles = StyleSheet.create({
  subLbl: { color: colors.onSurfaceSecondary, fontSize: 12, fontWeight: "700", marginTop: 8, marginBottom: 6 },
  // Iter 110 — salary process linkage helper text
  linkHint: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 8, lineHeight: 16 },
  // Iter 98 — OT basis radio chips
  radioChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  radioChipActive: { borderColor: colors.brandPrimary, backgroundColor: colors.brandTertiary },
  radioChipTxt: { color: colors.onSurface, fontSize: 12, fontWeight: "700" },
  root: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.md, gap: spacing.md },
  pageHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surfaceSecondary,
    gap: spacing.md,
    flexWrap: "wrap",
  },
  h1: { ...type.h3, color: colors.onSurface },
  h1sub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },
  section: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  sectionHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    backgroundColor: colors.brandTertiary,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sectionTitle: { ...type.h6, color: colors.onBrandTertiary },
  sectionBody: { padding: spacing.md, gap: spacing.sm },
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, alignItems: "flex-end" },
  rowWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, alignItems: "center" },
  field: { flexShrink: 0 },
  fieldLabel: { ...type.label, color: colors.onSurfaceSecondary, marginBottom: 4 },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 10,
    paddingVertical: 8,
    backgroundColor: colors.surface,
    color: colors.onSurface,
    minHeight: 36,
    fontSize: 13,
  },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 6,
    paddingRight: 12,
  },
  toggleLbl: { ...type.body, color: colors.onSurface },
  saveBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: radius.pill,
  },
  saveBtnTxt: { color: colors.onBrandPrimary, fontWeight: "700", fontSize: 13 },
  dropdownBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  dropdownTxt: { color: colors.onSurface, fontSize: 13 },
  dropdownList: {
    // In-flow (not absolute) so the list never renders behind the
    // content below (RN-web stacking quirk) — same pattern as MasterSelect.
    marginTop: 4,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    maxHeight: 220,
    overflow: "hidden",
    ...(Platform.OS === "web"
      ? ({ boxShadow: "0 8px 24px rgba(15,23,42,0.15)" } as any)
      : {}),
  },
  dropdownItem: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  dropdownItemTxt: { color: colors.onSurface, fontSize: 13 },
  gridHead: {
    flexDirection: "row",
    backgroundColor: colors.brandTertiary,
    borderWidth: 1,
    borderColor: colors.border,
    borderTopLeftRadius: radius.sm,
    borderTopRightRadius: radius.sm,
  },
  gridHeadCell: {
    padding: 8,
    ...type.label,
    color: colors.onBrandTertiary,
    borderRightWidth: 1,
    borderRightColor: colors.border,
  },
  gridRow: {
    flexDirection: "row",
    borderWidth: 1,
    borderTopWidth: 0,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: "stretch",
  },
  gridInput: {
    paddingHorizontal: 8,
    paddingVertical: 8,
    fontSize: 13,
    color: colors.onSurface,
    borderRightWidth: 1,
    borderRightColor: colors.border,
    minHeight: 36,
  },
  gridReadCell: {
    padding: 10,
    fontSize: 13,
    color: colors.onSurfaceSecondary,
    borderRightWidth: 1,
    borderRightColor: colors.border,
  },
  rowDelBtn: {
    width: 60,
    alignItems: "center",
    justifyContent: "center",
  },
  addRowBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    padding: 8,
    alignSelf: "flex-start",
  },
  addRowTxt: { ...type.label, color: colors.brandPrimary },
  radio: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
  },
  radioOn: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  radioTxt: { color: colors.onSurface, fontSize: 12 },
  emptyState: { padding: 40, alignItems: "center", gap: 8 },
  emptyTitle: { ...type.h4, color: colors.onSurface, marginTop: 8 },
  footer: {
    marginTop: spacing.md,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: spacing.md,
    flexWrap: "wrap",
  },
  footerTxt: { ...type.body, color: colors.onSurfaceSecondary },
  logoPreview: {
    width: 120, height: 120,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
    overflow: "hidden",
  },
  logoImg: { width: "100%", height: "100%" },
  logoHelp: {
    ...type.caption,
    color: colors.onSurfaceSecondary,
    lineHeight: 18,
  },
  logoBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  logoBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  // Iter 89 — Small inline hint + link that connects the Firm Master
  // Allowances / Deductions sections back to the Masters page.
  masterLinkHint: {
    ...type.caption,
    color: colors.onSurfaceSecondary,
    fontStyle: "italic",
    marginBottom: 4,
  },
  masterLinkBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.pill,
    backgroundColor: colors.brandTertiary,
    alignSelf: "flex-start",
    marginTop: 8,
  },
  masterLinkBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 11 },
});
