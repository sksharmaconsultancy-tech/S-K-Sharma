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
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Platform, Switch, useWindowDimensions, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import PolicyVariantPicker from "@/src/components/PolicyVariantPicker";
import PolicyMasterSummary from "@/src/components/PolicyMasterSummary";
import GeneralInfoSection from "@/src/components/firmMaster/GeneralInfoSection";
import ContactDetailsSection from "@/src/components/firmMaster/ContactDetailsSection";
import AuditLogSection from "@/src/components/firmMaster/AuditLogSection";
import HealthSection from "@/src/components/firmMaster/HealthSection";
import useEnterNav from "@/src/hooks/useEnterNav";
import useSaveShortcut from "@/src/hooks/useSaveShortcut";
import { confirmYesNo } from "@/src/utils/confirm";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import DateField from "@/src/components/DateField";
import { colors, radius, spacing, type } from "@/src/theme";

// Iter 484 — 16-section enterprise ERP layout (SAP / Zoho Payroll style).
const NAV_SECTIONS: { id: string; num: number; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { id: "general", num: 1, label: "General Information", icon: "business-outline" },
  { id: "registration", num: 2, label: "Registration Details", icon: "shield-checkmark-outline" },
  { id: "address", num: 3, label: "Address Details", icon: "location-outline" },
  { id: "contacts", num: 4, label: "Contact Details", icon: "people-outline" },
  { id: "bank", num: 5, label: "Bank Details", icon: "card-outline" },
  { id: "payroll", num: 6, label: "Payroll Settings", icon: "cash-outline" },
  { id: "compliance", num: 7, label: "Compliance Settings", icon: "key-outline" },
  { id: "attendance", num: 8, label: "Attendance & Shift", icon: "time-outline" },
  { id: "leave", num: 9, label: "Leave & Holiday", icon: "calendar-outline" },
  { id: "salary-structure", num: 10, label: "Salary Structure", icon: "layers-outline" },
  { id: "integrations", num: 11, label: "Integrations", icon: "git-network-outline" },
  { id: "documents", num: 12, label: "Documents", icon: "document-text-outline" },
  { id: "approval", num: 13, label: "Approval Workflow", icon: "checkmark-done-outline" },
  { id: "security", num: 14, label: "Security & Permissions", icon: "lock-closed-outline" },
  { id: "audit", num: 15, label: "Audit Log", icon: "time-outline" },
  { id: "health", num: 16, label: "AI Compliance Health", icon: "pulse-outline" },
];

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
  // Iter 306 (user #11) — eye toggle on password fields so admins can see
  // what they typed (stored values stay masked by the server).
  const [showSecret, setShowSecret] = useState(false);
  return (
    <View style={[styles.field, width ? { width } : { flex: 1, minWidth: 180 }]}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View style={{ position: "relative" }}>
        <TextInput
          value={value ?? ""}
          onChangeText={onChange}
          placeholder={placeholder}
          placeholderTextColor={colors.onSurfaceTertiary}
          keyboardType={keyboardType || "default"}
          secureTextEntry={!!secure && !showSecret}
          maxLength={maxLength}
          editable={!disabled}
          style={[styles.input, secure && { paddingRight: 36 }, disabled && { opacity: 0.45, backgroundColor: colors.border }]}
        />
        {secure ? (
          <Pressable
            onPress={() => setShowSecret((s) => !s)}
            hitSlop={8}
            style={{ position: "absolute", right: 10, top: 0, bottom: 0, justifyContent: "center" }}
          >
            <Ionicons
              name={showSecret ? "eye-off-outline" : "eye-outline"}
              size={17}
              color={colors.onSurfaceSecondary}
            />
          </Pressable>
        ) : null}
      </View>
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
  // Iter 484 — ERP layout state: active section + auto-save machinery.
  const { width } = useWindowDimensions();
  const wide = width >= 1100;
  const [activeSection, setActiveSection] = useState("general");
  const [autoState, setAutoState] = useState<"" | "saving" | "saved" | "error">("");
  const [autoErr, setAutoErr] = useState("");
  const autoTimer = useRef<any>(null);
  const savingRef = useRef(false);
  const sec = (id: string) => activeSection === id;

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

  // Iter 631 (user request) — DISABLE WARNING: switching OFF an allowance
  // head that has amounts in a processed month first shows the impact and
  // asks for confirmation. Saved values are never deleted — the head just
  // calculates as 0 on the next Reprocess.
  const toggleAllowance = async (lab: string, v: boolean) => {
    if (!v && companyId) {
      try {
        const imp = await api<any>(
          `/admin/compliance-allowance-impact?company_id=${companyId}&head=${encodeURIComponent(lab)}`);
        if (imp?.applicable && (imp.months || []).length > 0) {
          const list = imp.months.slice(0, 6)
            .map((m: any) => `• ${m.month}: ₹${Number(m.total).toLocaleString("en-IN")} across ${m.employees} employee row(s)${m.finalized ? " (FINALIZED)" : ""}`)
            .join("\n");
          const more = imp.months.length > 6 ? `\n…and ${imp.months.length - 6} more month(s)` : "";
          const ok = await confirmYesNo(
            `"${lab}" has amounts in processed salary month(s):\n\n${list}${more}\n\n` +
            `Disabling will calculate this head as ₹0 on the NEXT Reprocess ` +
            `(already processed months stay unchanged until reprocessed; on ` +
            `Freeze imports the amount moves to OT / Other Allowance so the ` +
            `imported Gross is kept). Saved values are NOT deleted — ` +
            `re-enabling + Reprocess restores them.\n\nDisable "${lab}"?`,
            "Allowance has processed amounts");
          if (!ok) return;
        }
      } catch { /* impact check is advisory — never blocks the toggle */ }
    }
    updateSection("allowances", { [lab]: v });
  };

  // Iter 108 — Enter jumps to the next field; Enter on the LAST field saves.
  useEnterNav(() => { void save(); });
  // Iter 110 — Ctrl+S / Cmd+S saves.
  useSaveShortcut(() => { void save(); });

  const save = async () => {
    if (!companyId || !master) return;
    setSaving(true);
    try {
      const r = await api<{ master: Master }>(`/admin/firm-master/${companyId}`, {
        method: "PATCH",
        body: master,
      });
      if (r?.master) setMaster(r.master);
      setDirty(false);
      setAutoState("saved"); setAutoErr("");
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  // Iter 484 — silent save used by auto-save (no alerts, no navigation).
  const saveSilent = useCallback(async () => {
    if (!companyId || !master || savingRef.current) return;
    savingRef.current = true;
    setAutoState("saving");
    try {
      await api(`/admin/firm-master/${companyId}`, { method: "PATCH", body: master });
      setDirty(false);
      setAutoState("saved"); setAutoErr("");
    } catch (e: any) {
      setAutoState("error");
      setAutoErr(e?.message || "Auto-save failed");
    } finally {
      savingRef.current = false;
    }
  }, [companyId, master]);

  // Auto-save: 2 seconds after the last edit.
  useEffect(() => {
    if (!dirty) return;
    if (autoTimer.current) clearTimeout(autoTimer.current);
    autoTimer.current = setTimeout(() => { void saveSilent(); }, 2000);
    return () => { if (autoTimer.current) clearTimeout(autoTimer.current); };
  }, [master, dirty, saveSilent]);

  const saveAndContinue = async () => {
    await saveSilent();
    const idx = NAV_SECTIONS.findIndex((s) => s.id === activeSection);
    if (idx >= 0 && idx < NAV_SECTIONS.length - 1) {
      setActiveSection(NAV_SECTIONS[idx + 1].id);
    }
  };
  const resetChanges = () => {
    if (Platform.OS === "web" && dirty
        && !window.confirm("Discard unsaved changes and reload from the server?")) return;
    void load();
  };
  const cancelAndClose = () => {
    if (Platform.OS === "web") window.location.href = "/";
    else router.replace("/(tabs)");
  };
  const cloneCompany = async () => {
    if (Platform.OS !== "web" || !companyId) return;
    const name = window.prompt("Name for the cloned firm:", `${master?.company_name || "Firm"} (Copy)`);
    if (!name) return;
    try {
      const r = await api<{ company_id: string; company_code: string }>(
        `/admin/firm-master/${companyId}/clone`,
        { method: "POST", body: { new_name: name } });
      window.alert(`Firm cloned ✓\nNew firm: ${name}\nCode: ${r.company_code}`);
    } catch (e: any) { window.alert(e?.message || "Clone failed"); }
  };
  const exportConfig = async () => {
    if (Platform.OS !== "web" || !companyId) return;
    try {
      const data = await api<any>(`/admin/firm-master/${companyId}/export`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = (globalThis as any).document.createElement("a");
      a.href = url;
      a.download = `firm-config-${(master?.company_name || companyId).replace(/\s+/g, "_")}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) { window.alert(e?.message || "Export failed"); }
  };

  // ---------- Same-as-firm mirroring for Office/Factory addresses ----------
  const mirrorAddress = (target: "office_address" | "factory_address", flag: boolean) => {
    updateSection(target, {
      same_as_firm: flag,
      ...(flag && master?.registered_address ? master.registered_address : {}),
    });
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
          {/* Auto-save state pill */}
          <View style={styles.autoPill}>
            <Ionicons
              name={autoState === "saving" ? "sync" : autoState === "error" ? "warning" : dirty ? "ellipse" : "cloud-done-outline"}
              size={12}
              color={autoState === "error" ? colors.error : dirty ? "#D97706" : "#059669"} />
            <Text style={[styles.autoPillTxt, autoState === "error" && { color: colors.error }]}>
              {autoState === "saving" ? "Auto-saving…"
                : autoState === "error" ? `Auto-save failed`
                  : dirty ? "Unsaved changes" : "All changes saved"}
            </Text>
          </View>
        </View>
      </View>
      {autoState === "error" && autoErr ? (
        <View style={styles.dirtyBanner}>
          <Ionicons name="warning" size={16} color="#B45309" />
          <Text style={styles.dirtyBannerTxt}>{autoErr}</Text>
        </View>
      ) : null}

      {/* Body: side navigation + section content */}
      <View style={{ flex: 1, flexDirection: wide ? "row" : "column" }}>
        {wide ? (
          <ScrollView style={styles.navCol} contentContainerStyle={{ paddingVertical: 8 }}>
            {NAV_SECTIONS.map((s) => {
              const on = activeSection === s.id;
              return (
                <Pressable key={s.id} onPress={() => setActiveSection(s.id)}
                  style={[styles.navItem, on && styles.navItemOn]}
                  testID={`fm-nav-${s.id}`}>
                  <Text style={[styles.navNum, on && { color: colors.brandPrimary }]}>{s.num}</Text>
                  <Ionicons name={s.icon} size={15}
                            color={on ? colors.brandPrimary : colors.onSurfaceTertiary} />
                  <Text style={[styles.navTxt, on && styles.navTxtOn]} numberOfLines={1}>{s.label}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
        ) : (
          <ScrollView horizontal showsHorizontalScrollIndicator={false}
                      style={styles.navChipsRow}
                      contentContainerStyle={{ gap: 6, paddingHorizontal: 8, paddingVertical: 6 }}>
            {NAV_SECTIONS.map((s) => {
              const on = activeSection === s.id;
              return (
                <Pressable key={s.id} onPress={() => setActiveSection(s.id)}
                  style={[styles.navChip, on && styles.navChipOn]}
                  testID={`fm-nav-${s.id}`}>
                  <Text style={[styles.navChipTxt, on && { color: "#FFF" }]}>{s.num}. {s.label}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
        )}

      <ScrollView style={{ flex: 1 }} contentContainerStyle={styles.scroll}>
        {/* Active section heading */}
        <View style={styles.secHeadBar}>
          <Text style={styles.secHeadTxt}>
            {NAV_SECTIONS.find((s) => s.id === activeSection)?.num}. {NAV_SECTIONS.find((s) => s.id === activeSection)?.label}
          </Text>
          {master.updated_at ? (
            <Text style={styles.secHeadMeta}>
              Last modified {String(master.updated_at).replace("T", " ").slice(0, 16)}
              {master.updated_by_name ? ` · by ${master.updated_by_name}` : ""}
            </Text>
          ) : null}
        </View>

        {/* 1. GENERAL INFORMATION (Iter 484 ERP redesign) ---------------- */}
        {sec("general") ? (
          <GeneralInfoSection master={master} updateSection={updateSection} companyId={companyId} />
        ) : null}

        {/* 4. CONTACT DETAILS (Iter 484 — normalized contacts) ----------- */}
        {sec("contacts") ? (
          <ContactDetailsSection master={master} updateSection={updateSection} companyId={companyId} />
        ) : null}

        {/* 15. AUDIT LOG / 16. HEALTH ------------------------------------ */}
        {sec("audit") ? <AuditLogSection companyId={companyId} /> : null}
        {sec("health") ? <HealthSection master={master} /> : null}

        {/* 3. ADDRESS DETAILS -------------------------------------------- */}
        {sec("address") ? (<>
        <Section icon="location-outline" title="Registered Address">
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

        {/* Office & Factory Address (side-by-side on wide screens) ------ */}
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
          <View style={{ flex: 1, minWidth: 380 }}>
            <Section icon="business-outline" title="Office Address">
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
            <Section icon="business" title="Factory Address">
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
        </>) : null}

        {/* 10. SALARY STRUCTURE — allowances / deductions / structure --- */}
        {sec("salary-structure") ? (<>
        <Section icon="layers-outline" title="Salary Structure & Heads">
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
        </Section>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
          <View style={{ flex: 1, minWidth: 300 }}>
            <Section icon="add-circle-outline" title="Allowances (Master-linked)">
              <Text style={styles.masterLinkHint}>
                Toggle any allowance head to enable it for this firm. Custom
                heads added via Masters → Allowances appear here automatically.
              </Text>
              {catalogs.allowance_labels.map((lab) => (
                <Toggle
                  key={lab}
                  label={lab}
                  value={!!master.allowances?.[lab]}
                  onChange={(v) => { void toggleAllowance(lab, v); }}
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
            <Section icon="remove-circle-outline" title="Deductions (Master-linked)">
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
        </View>
        </>) : null}

        {/* 5. BANK DETAILS ----------------------------------------------- */}
        {sec("bank") ? (
          <View style={{ flexDirection: "row" }}>
          <View style={{ flex: 1, maxWidth: 560 }}>
            <Section icon="card-outline" title="Bank Details">
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
        ) : null}

        {/* 8/13/14/11 — pieces of the old "Firm Settings" section -------- */}
        {sec("security") ? (
        <Section icon="lock-closed-outline" title="Security & Permissions">
          <View style={styles.rowWrap}>
            <Toggle label="Firm Active" value={!!st.firm_active}
                    onChange={(v) => updateSection("settings", { firm_active: v })} />
          </View>
          <Text style={styles.linkHint}>
            Firm Active mirrors the Company Status on General Information.
            Per-contact report permissions (who receives Payroll Reports, PF /
            ESIC Notices, Bank Advice…) are managed on each contact card in
            the Contact Details section. User roles &amp; access rights are
            managed under Administration → Access Management.
          </Text>
          <Pressable onPress={() => router.push("/access-management" as any)} style={styles.masterLinkBtn}>
            <Ionicons name="key-outline" size={12} color={colors.brandPrimary} />
            <Text style={styles.masterLinkBtnTxt}>Open Access Management</Text>
          </Pressable>
        </Section>
        ) : null}

        {sec("integrations") ? (<>
        <Section icon="git-network-outline" title="Communication Integrations">
          <View style={styles.rowWrap}>
            <Toggle label="WhatsApp Enable" value={!!st.whatsapp_enable}
                    onChange={(v) => updateSection("settings", { whatsapp_enable: v })} />
            <Toggle label="Auto E-Mail Process" value={!!st.auto_email_process}
                    onChange={(v) => updateSection("settings", { auto_email_process: v })} />
            <Toggle label="eMail Enable" value={!!st.email_enable}
                    onChange={(v) => updateSection("settings", { email_enable: v })} />
          </View>
        </Section>
        <Section icon="hardware-chip-outline" title="Connected Modules">
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
            {([
              ["/whatsapp-center", "logo-whatsapp", "WhatsApp Center"],
              ["/attendance-email", "mail-outline", "Email Settings"],
              ["/biometric-devices", "finger-print-outline", "Biometric Devices (ADMS)"],
              ["/portal-automation", "globe-outline", "Portal RPA (EPFO / ESIC)"],
            ] as [string, any, string][]).map(([path, icon, label]) => (
              <Pressable key={path} onPress={() => router.push(path as any)} style={styles.integrationBtn}>
                <Ionicons name={icon} size={15} color={colors.brandPrimary} />
                <Text style={styles.integrationBtnTxt}>{label}</Text>
                <Ionicons name="chevron-forward" size={13} color={colors.onSurfaceTertiary} />
              </Pressable>
            ))}
          </View>
        </Section>
        </>) : null}

        {/* 6. PAYROLL SETTINGS — misc toggles ---------------------------- */}
        {sec("payroll") ? (
        <Section icon="options-outline" title="Payroll Options">
          <View style={styles.rowWrap}>
            <Toggle label="Allow CategoryRate" value={!!st.allow_category_rate}
                    onChange={(v) => updateSection("settings", { allow_category_rate: v })} />
            <Toggle label="Auto Employee Code (lock manual entry)" value={!!st.auto_employee_code}
                    onChange={(v) => updateSection("settings", { auto_employee_code: v })} />
          </View>
        </Section>
        ) : null}

        {/* 13. APPROVAL WORKFLOW ----------------------------------------- */}
        {sec("approval") ? (
        <Section icon="checkmark-done-outline" title="Punch Approval Workflow">
          <View style={styles.rowWrap}>
            {/* Iter 483 (user request) — mobile App punches skip the admin
                approval queue and show on the Grid instantly. Turning it ON
                also auto-approves this firm's OLD pending app punches. */}
            <Toggle label="Auto-approve Mobile App Punches (no admin review)" value={!!st.auto_approve_mobile_punches}
                    testID="fm-auto-approve-app"
                    onChange={(v) => updateSection("settings", { auto_approve_mobile_punches: v })} />
          </View>
          {st.auto_approve_mobile_punches ? (
            <Text style={{ fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 4 }}>
              App punches will be approved instantly (no admin review). On Save,
              all of this firm&apos;s old PENDING app punches are approved too, so
              they appear on the Attendance Grid immediately. Fake-GPS flagged
              punches still require manual approval.
            </Text>
          ) : null}
        </Section>
        ) : null}

        {/* 8. ATTENDANCE & SHIFT — policy preset ------------------------- */}
        {sec("attendance") ? (<>
        <Section icon="ribbon-outline" title="Attendance Policy Preset">

          {/* Iter 613 (user directive) — policy is MANDATORY only when the
              firm runs Offline Salary AND Biometric Attendance; otherwise
              it's optional. */}
          <Text style={[styles.subLbl, { marginTop: 10 }]}>
            Attendance Policy {sp.offline_salary && sp.bio_matrix_attendance
              ? "(mandatory — Offline Salary + Biometric Attendance is ON)"
              : "(optional)"}
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
            sp.offline_salary && sp.bio_matrix_attendance ? (
              <Text style={{ fontSize: 11, color: colors.error, marginTop: 4 }}>
                ⚠ MANDATORY: this firm runs Offline Salary + Biometric Attendance —
                select Standard or Textile so attendance can be processed correctly.
              </Text>
            ) : (
              <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 4 }}>
                No policy selected — optional for this firm; you can pick Standard or Textile anytime.
              </Text>
            )
          ) : null}
        </Section>
        {/* Iter 503 — SINGLE MACHINE ATTENDANCE MODE (user spec). */}
        <Section icon="finger-print-outline" title="Attendance Capture / Device Mode">
          {(() => {
            const ac = (st.attendance_config || {}) as Record<string, any>;
            const acMode = ac.device_mode || "separate";
            const setAC = (patch: Record<string, any>) =>
              updateSection("settings", {
                attendance_config: {
                  device_mode: acMode,
                  interpretation: ac.interpretation || "alternate",
                  dup_window_min: ac.dup_window_min ?? 5,
                  lunch_mode: ac.lunch_mode || "ignore_middle",
                  lunch_fixed_min: ac.lunch_fixed_min ?? 30,
                  // Iter 518 — Smart Direction Correction (preserved on save)
                  smart_direction: !!ac.smart_direction,
                  smart_direction_gap_hrs: ac.smart_direction_gap_hrs ?? 4,
                  ...patch,
                },
              });
            const radio = (
              on: boolean, label: string, sub: string, onPress: () => void, tid: string,
            ) => (
              <Pressable key={tid} onPress={onPress} testID={tid}
                style={{
                  flexGrow: 1, minWidth: 150, borderWidth: 2, borderRadius: 10,
                  padding: 10, gap: 2,
                  borderColor: on ? colors.brandPrimary : colors.border,
                  backgroundColor: on ? "#EEF2FF" : colors.surface,
                }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Ionicons name={on ? "radio-button-on" : "radio-button-off"} size={15}
                    color={on ? colors.brandPrimary : colors.onSurfaceTertiary} />
                  <Text style={{ fontSize: 12.5, fontWeight: "800", color: on ? colors.brandPrimary : colors.onSurface }}>
                    {label}
                  </Text>
                </View>
                {sub ? <Text style={{ fontSize: 10.5, color: colors.onSurfaceSecondary }}>{sub}</Text> : null}
              </Pressable>
            );
            const chip = (on: boolean, label: string, onPress: () => void, tid: string) => (
              <Pressable key={tid} onPress={onPress} testID={tid}
                style={{
                  borderWidth: 1.5, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 7,
                  borderColor: on ? colors.brandPrimary : colors.border,
                  backgroundColor: on ? colors.brandPrimary : colors.surface,
                }}>
                <Text style={{ fontSize: 11.5, fontWeight: "800", color: on ? "#fff" : colors.onSurfaceSecondary }}>
                  {label}
                </Text>
              </Pressable>
            );
            return (
              <>
                <Text style={styles.subLbl}>How does this firm record punches?</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                  {radio(acMode === "separate", "Separate IN/OUT Machines",
                    "Dedicated IN device + OUT device (default)",
                    () => setAC({ device_mode: "separate" }), "fm-ac-separate")}
                  {radio(acMode === "single_machine", "Single Machine (shared)",
                    "One device — everyone punches IN & OUT on it",
                    () => setAC({ device_mode: "single_machine" }), "fm-ac-single")}
                  {radio(acMode === "mobile", "Mobile App", "GPS selfie punches from the app",
                    () => setAC({ device_mode: "mobile" }), "fm-ac-mobile")}
                  {radio(acMode === "gps", "GPS Only", "Location-based punches",
                    () => setAC({ device_mode: "gps" }), "fm-ac-gps")}
                  {radio(acMode === "qr", "QR Code", "Scan a site QR to punch",
                    () => setAC({ device_mode: "qr" }), "fm-ac-qr")}
                </View>
                {acMode === "separate" ? (
                  <>
                    {/* Iter 518 (user choice C) — Smart Direction Correction */}
                    <Text style={[styles.subLbl, { marginTop: 12 }]}>
                      Smart Direction Correction (OUT-machine down safety)
                    </Text>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                      {radio(!ac.smart_direction, "OFF (default)",
                        "Every punch keeps its machine's registered direction",
                        () => setAC({ smart_direction: false }), "fm-sdc-off")}
                      {radio(!!ac.smart_direction, "ON — auto OUT",
                        "Punch on the IN machine ≥ gap hrs after first IN records as OUT",
                        () => setAC({ smart_direction: true }), "fm-sdc-on")}
                    </View>
                    {ac.smart_direction ? (
                      <>
                        <Text style={[styles.subLbl, { marginTop: 12 }]}>
                          Minimum gap before auto-OUT (hours)
                        </Text>
                        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                          {[3, 4, 5, 6, 8].map((h) =>
                            chip((ac.smart_direction_gap_hrs ?? 4) === h, `${h} hrs`,
                              () => setAC({ smart_direction_gap_hrs: h }), `fm-sdc-gap-${h}`))}
                        </View>
                        <Pressable
                          testID="fm-sdc-repair"
                          onPress={async () => {
                            const now = new Date();
                            const from = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
                            const to = now.toISOString().slice(0, 10);
                            const q = `Repair past days (${from} → ${to})? Days with 2+ IN-machine punches and no OUT will get the last punch converted to OUT; the 12-hr auto-close records for those days are removed.`;
                            const go = async () => {
                              try {
                                const r = await api<any>("/biometric/smart-direction-repair", {
                                  method: "POST",
                                  body: { company_id: companyId, from_date: from, to_date: to },
                                });
                                const msg = `Repaired ${r.fixed_days} day(s) (gap ≥ ${r.gap_hours} hrs). ${r.skipped_days} day(s) untouched.`;
                                if (Platform.OS === "web") window.alert(msg); else Alert.alert("Done ✅", msg);
                              } catch (e: any) {
                                const m = e?.message || "Repair failed";
                                if (Platform.OS === "web") window.alert(m); else Alert.alert("Failed", m);
                              }
                            };
                            if (Platform.OS === "web") { if (window.confirm(q)) go(); }
                            else Alert.alert("Repair past days", q, [{ text: "Cancel", style: "cancel" }, { text: "Repair", onPress: go }]);
                          }}
                          style={{
                            marginTop: 12, alignSelf: "flex-start", flexDirection: "row",
                            alignItems: "center", gap: 6, backgroundColor: colors.brandPrimary,
                            borderRadius: 8, paddingHorizontal: 14, paddingVertical: 9,
                          }}
                        >
                          <Ionicons name="build-outline" size={14} color="#fff" />
                          <Text style={{ color: "#fff", fontSize: 12, fontWeight: "800" }}>
                            Repair past days (this month)
                          </Text>
                        </Pressable>
                        <Text style={{ fontSize: 10.5, color: colors.onSurfaceSecondary, marginTop: 6 }}>
                          Save the firm first so the switch is active, then run repair.
                          New punches are corrected automatically from now on.
                        </Text>
                      </>
                    ) : null}
                  </>
                ) : null}
                {acMode === "single_machine" ? (
                  <>
                    <Text style={[styles.subLbl, { marginTop: 12 }]}>
                      Punch interpretation
                    </Text>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                      {radio((ac.interpretation || "alternate") === "alternate",
                        "A — Alternate", "1st punch = IN · 2nd = OUT · 3rd = IN …",
                        () => setAC({ interpretation: "alternate" }), "fm-ac-alt")}
                      {radio(ac.interpretation === "first_last",
                        "B — First IN · Last OUT", "Duty = last punch − first punch",
                        () => setAC({ interpretation: "first_last" }), "fm-ac-firstlast")}
                    </View>
                    <Text style={[styles.subLbl, { marginTop: 12 }]}>
                      Ignore duplicate punches within (minutes)
                    </Text>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                      {[0, 1, 2, 5, 10].map((m) =>
                        chip((ac.dup_window_min ?? 5) === m, m === 0 ? "Off" : `${m} min`,
                          () => setAC({ dup_window_min: m }), `fm-ac-dup-${m}`))}
                    </View>
                    {ac.interpretation === "first_last" ? (
                      <>
                        <Text style={[styles.subLbl, { marginTop: 12 }]}>
                          Lunch / middle punches handling
                        </Text>
                        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                          {radio((ac.lunch_mode || "ignore_middle") === "ignore_middle",
                            "Ignore middle punches", "Duty = last − first (no break deduction)",
                            () => setAC({ lunch_mode: "ignore_middle" }), "fm-ac-lunch-ignore")}
                          {radio(ac.lunch_mode === "actual_break",
                            "Actual break", "Middle punches = lunch OUT/IN — real break deducted",
                            () => setAC({ lunch_mode: "actual_break" }), "fm-ac-lunch-actual")}
                          {radio(ac.lunch_mode === "fixed",
                            "Fixed deduction", "Deduct a fixed lunch from every day's duty",
                            () => setAC({ lunch_mode: "fixed" }), "fm-ac-lunch-fixed")}
                        </View>
                        {ac.lunch_mode === "fixed" ? (
                          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                            {[30, 45, 60].map((m) =>
                              chip((ac.lunch_fixed_min ?? 30) === m, `${m} min`,
                                () => setAC({ lunch_fixed_min: m }), `fm-ac-lunchmin-${m}`))}
                          </View>
                        ) : null}
                      </>
                    ) : null}
                    <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 10 }}>
                      Single Machine Mode re-interprets this firm&apos;s biometric
                      punches only. Mobile-app and manual punches keep their
                      recorded IN/OUT. Other firms are not affected. Save to apply.
                    </Text>
                  </>
                ) : null}
              </>
            );
          })()}
        </Section>
        <Section icon="time-outline" title="Attendance Policy Variant">
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
              <Section icon="briefcase-outline" title="Contractor Employees (Policy 2)">
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
        </>) : null}

        {/* 6. PAYROLL SETTINGS — salary process ------------------------- */}
        {sec("payroll") ? (
            <Section icon="cash-outline" title="Salary Process Settings">
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
              {/* Iter 337 (user request) — Days Calculation Method for the
                  Compliance Salary import (Freeze Salary workflow).
                  Iter 339 (user request) — points show only when "Online
                  Salary → Compliance Salary Process" is ENABLED. */}
              {sp.online_salary ? (<>
              <Text style={{ fontSize: 13, fontWeight: "800", color: "#1E3A8A", marginTop: 14, marginBottom: 6 }}>
                Days Calculation Method (Salary Import / Freeze)
              </Text>
              <View style={{ gap: 6 }}>
                {[
                  { k: "attendance", l: "Attendance Days (from imported sheet — default)" },
                  { k: "gross_based", l: "Gross Salary Based (days derived from imported gross)" },
                  { k: "freeze_based", l: "Freeze Salary Based (days derived from frozen gross)" },
                  { k: "attendance_gross_validation", l: "Attendance + Gross Validation (Default · Recommended)" },
                  { k: "freeze_actual_gross", l: "Freeze as Actual Gross (imported gross taken AS-IS)" },
                ].map((o) => {
                  const on = (sp.days_calc_method || "attendance_gross_validation") === o.k;
                  return (
                    <Pressable
                      key={o.k}
                      onPress={() => updateSection("salary_process", { days_calc_method: o.k })}
                      style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
                      testID={`fm-days-calc-${o.k}`}
                    >
                      <Ionicons name={on ? "radio-button-on" : "radio-button-off"} size={18} color={on ? "#2563EB" : "#94A3B8"} />
                      <Text style={{ fontSize: 13, color: on ? "#1E3A8A" : "#334155", fontWeight: on ? "700" : "400" }}>{o.l}</Text>
                    </Pressable>
                  );
                })}
              </View>
              <View style={{ flexDirection: "row", gap: 18, marginTop: 10, flexWrap: "wrap" }}>
                {(sp.days_calc_method || "attendance_gross_validation") !== "attendance" ? (
                  <View>
                    <Text style={{ fontSize: 12, color: "#64748B", marginBottom: 4 }}>Round Compliance Days to</Text>
                    <View style={{ flexDirection: "row", gap: 6 }}>
                      {[{ v: 0.5, l: "Half Day (0.50)" }, { v: 1, l: "Full Day (1)" }].map((o) => {
                        const on = Number(sp.days_calc_rounding ?? 0.5) === o.v;
                        return (
                          <Pressable key={o.l} onPress={() => updateSection("salary_process", { days_calc_rounding: o.v })}
                            style={{ paddingHorizontal: 14, paddingVertical: 7, borderRadius: 8, borderWidth: 1,
                                     borderColor: on ? "#2563EB" : "#CBD5E1", backgroundColor: on ? "#DBEAFE" : "#fff" }}>
                            <Text style={{ fontSize: 13, fontWeight: "700", color: on ? "#1D4ED8" : "#334155" }}>{o.l}</Text>
                          </Pressable>
                        );
                      })}
                    </View>
                  </View>
                ) : null}
              </View>
              {(sp.days_calc_method || "attendance_gross_validation") !== "attendance" ? (
                <Text style={styles.linkHint}>
                  Compliance Days = Imported Gross ÷ (Master Monthly Gross ÷ Month Days).
                  Statutory (PF/ESIC/PT) is recalculated on the derived days; any remaining
                  difference vs the imported gross goes to Overtime / Other Allowance.
                </Text>
              ) : null}
              {/* Iter 338 (user request) — WORKFLOW of the selected method. */}
              <View style={{ marginTop: 10, backgroundColor: "#EFF6FF", borderRadius: 10, padding: 12, borderWidth: 1, borderColor: "#BFDBFE" }}>
                <Text style={{ fontSize: 12, fontWeight: "800", color: "#1D4ED8", marginBottom: 6 }}>
                  ⚙ Workflow — {({
                    attendance: "Attendance Days",
                    gross_based: "Gross Salary Based",
                    freeze_based: "Freeze Salary Based",
                    attendance_gross_validation: "Attendance + Gross Validation",
                    freeze_actual_gross: "Freeze as Actual Gross",
                  } as any)[sp.days_calc_method || "attendance_gross_validation"]}
                </Text>
                {(({
                  attendance: [
                    "1. Salary Import → Present Days taken AS-IS from the sheet",
                    "2. Salary = Master rates × Present Days",
                    "3. PF / ESIC / LWF / PT calculated on that gross",
                    "4. Imported vs Calculated gross difference → Overtime / Other Allowance",
                  ],
                  gross_based: [
                    "1. Salary Import → Per-Day Gross = Master Gross ÷ Month Days",
                    "2. Compliance Days = Imported Gross ÷ Per-Day Gross (rounded Half/Full day)",
                    "3. Salary recalculated on the derived days · Basic per wage definition",
                    "4. PF / ESIC / LWF / PT recalculated automatically",
                    "5. Remaining difference → Overtime / Other Allowance",
                  ],
                  freeze_based: [
                    "1. Salary Import → Freeze Salary (imported gross) is authoritative",
                    "2. Compliance Days derived from the frozen gross (Half/Full day)",
                    "3. Salary recalculated on the derived days · Basic per wage definition",
                    "4. PF / ESIC / LWF / PT recalculated automatically",
                    "5. Remaining difference → Overtime / Other Allowance",
                  ],
                  attendance_gross_validation: [
                    "1. Salary Import → Attendance Days AND Imported Gross both read (DEFAULT method)",
                    "2. System derives Compliance Days from gross and compares with attendance",
                    "3. Days AUTO-REDUCE if too high for the gross — but NEVER increase",
                    "4. Salary recalculated on Compliance Days · Basic per wage definition",
                    "5. PF / ESIC / LWF / PT recalculated automatically",
                    "6. Grid shows Att. Days · Comp. Days · ✓ Matched / ≠ Diff per employee",
                    "7. Remaining difference → Overtime / Incentive / Other Allowance",
                  ],
                  freeze_actual_gross: [
                    "1. Salary Import → Imported Gross taken AS-IS as the final gross",
                    "2. Exact fractional days derived (no rounding) so Calc = Imported to the rupee",
                    "3. PF / ESIC / LWF / PT calculated on the imported gross",
                    "4. Difference ≈ 0 → every row shows ✓ Matched",
                  ],
                } as any)[sp.days_calc_method || "attendance_gross_validation"] as string[]).map((step: string) => (
                  <Text key={step} style={{ fontSize: 12, color: "#334155", lineHeight: 19 }}>{step}</Text>
                ))}
                <Text style={{ fontSize: 11, color: "#64748B", marginTop: 6 }}>
                  Attendance Master → Salary Import → Freeze Salary → Auto Compliance Days → PF · ESIC · LWF · PT · Bonus · Gratuity → Salary Register
                </Text>
              </View>
              {/* Iter 338 (user request) — push frozen gross into the
                  ACTUAL Salary Process for On-Roll employees. */}
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 12 }}>
                <View style={{ flex: 1, paddingRight: 10 }}>
                  <Text style={{ fontSize: 13, fontWeight: "700", color: "#1E3A8A" }}>Import Freeze gross into Actual Salary</Text>
                  <Text style={{ fontSize: 11.5, color: "#64748B", marginTop: 2 }}>
                    On-Roll employees take the FROZEN gross from the processed Compliance run as their Actual Salary gross for the month.
                  </Text>
                </View>
                <Switch
                  value={!!sp.freeze_to_actual}
                  onValueChange={(v) => updateSection("salary_process", { freeze_to_actual: v })}
                  testID="fm-freeze-to-actual"
                />
              </View>
              </>) : null}
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
        ) : null}

        {/* 9. LEAVE & HOLIDAY -------------------------------------------- */}
        {sec("leave") ? (
            <Section icon="calendar-outline" title="CL / PL Policy">
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
        ) : null}

        {/* 2. REGISTRATION DETAILS — EPF & ESI --------------------------- */}
        {sec("registration") ? (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
          <View style={{ flex: 1, minWidth: 380 }}>
            <Section icon="shield-checkmark-outline" title="EPF Registration">
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
            <Section icon="medkit-outline" title="ESI Registration">
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

        ) : null}
        {/* Bonus (payroll group) ----------------------------------------- */}
        {sec("payroll") ? (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
          <View style={{ flex: 1, minWidth: 380 }}>
            <Section icon="gift-outline" title="Bonus Settings">
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
        ) : null}

        {/* 12. DOCUMENTS ------------------------------------------------- */}
        {sec("documents") ? (
        <Section icon="document-text-outline" title="Firm Compliance Documents">
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
        ) : null}

        {/* 7. COMPLIANCE SETTINGS — portal logins ------------------------ */}
        {sec("compliance") ? (<>
        <Section icon="ribbon-outline" title="Compliance Mode (Register Headings)">
          <Text style={{ fontSize: 11.5, color: colors.onSurfaceTertiary, marginBottom: 8 }}>
            Decides which Act every CLRA / Labour register cites in its
            heading — the report formats stay identical.
          </Text>
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            {([["clra", "CLRA Act, 1970"], ["labour_code", "Labour Codes (OSH 2020 / Wages 2019)"]] as [string, string][]).map(([v, lbl]) => {
              const on = (st.compliance_mode || "clra") === v;
              return (
                <Pressable key={v} testID={`fm-compliance-mode-${v}`}
                  onPress={() => updateSection("settings", { compliance_mode: v })}
                  style={{
                    flexDirection: "row", alignItems: "center", gap: 6,
                    borderWidth: 1.5, borderColor: on ? colors.brandPrimary : colors.border,
                    backgroundColor: on ? colors.brandTertiary : colors.surface,
                    borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8,
                  }}>
                  <Ionicons name={on ? "radio-button-on" : "radio-button-off"} size={14}
                            color={on ? colors.brandPrimary : colors.onSurfaceTertiary} />
                  <Text style={{ fontSize: 12.5, fontWeight: on ? "800" : "500",
                                 color: on ? colors.brandPrimary : colors.onSurfaceSecondary }}>{lbl}</Text>
                </Pressable>
              );
            })}
          </View>
        </Section>
        <Section icon="key-outline" title="Portal Login Credentials">
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
        </>) : null}

        {/* 13. APPROVAL — Employee Rejoin (Rehire) policy ---------------- */}
        {sec("approval") ? (
        <Section icon="refresh-circle-outline" title="Employee Rejoin Policy">
          {([
            ["employee_code", "Employee Code on Rejoin", [
              ["continue", "Continue existing code"],
              ["new", "Generate NEW code (linked)"]]],
            ["leave_balance", "Leave Balance on Rejoin", [
              ["continue", "Continue previous balance"],
              ["reset", "Reset to zero"],
              ["manual", "Manual opening balance"]]],
            ["gratuity_service", "Gratuity Service", [
              ["continue", "Continue previous service"],
              ["fresh", "Fresh employment"]]],
          ] as [string, string, [string, string][]][]).map(([key, label, opts]) => (
            <View key={key} style={{ marginBottom: 10 }}>
              <Text style={{ fontSize: 12, fontWeight: "700", color: "#475569", marginBottom: 5 }}>{label}</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                {opts.map(([val, txt]) => {
                  const cur = String((master.rejoin_policy || {})[key] || (key === "employee_code" ? "continue" : key === "leave_balance" ? "continue" : "continue"));
                  const on = cur === val;
                  return (
                    <Pressable
                      key={val}
                      testID={`rejoin-policy-${key}-${val}`}
                      onPress={() => {
                        setMaster((m: any) => ({
                          ...m,
                          rejoin_policy: { ...(m.rejoin_policy || {}), [key]: val },
                        }));
                        setDirty(true);
                      }}
                      style={{
                        borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6,
                        borderColor: on ? "#059669" : "#CBD5E1",
                        backgroundColor: on ? "#059669" : "#fff",
                      }}
                    >
                      <Text style={{ fontSize: 12, fontWeight: on ? "800" : "500", color: on ? "#fff" : "#475569" }}>{txt}</Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>
          ))}
          <Text style={{ fontSize: 11.5, color: "#64748B", lineHeight: 16 }}>
            UAN & ESIC IP ALWAYS continue on rejoin (never re-issued). Attendance
            & payroll restart from the Rejoin Date; all history stays locked.
          </Text>
        </Section>
        ) : null}
        <View style={{ height: 90 }} />
      </ScrollView>
      </View>

      {/* Iter 484 — sticky bottom action bar (Save / Save & Continue /
          Reset / Cancel / Clone / Export + last-modified metadata). */}
      <View style={styles.actionBar}>
        <Pressable onPress={save} disabled={saving || !dirty}
          style={[styles.actionBtn, (saving || !dirty) && { opacity: 0.5 }]}
          testID="firm-master-save">
          {saving ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="save-outline" size={15} color="#FFF" />}
          <Text style={styles.actionBtnTxt}>{saving ? "Saving…" : "Save"}</Text>
        </Pressable>
        <Pressable onPress={() => void saveAndContinue()}
          style={[styles.actionBtn, { backgroundColor: "#059669" }]}
          testID="fm-save-continue">
          <Ionicons name="arrow-forward-circle-outline" size={15} color="#FFF" />
          <Text style={styles.actionBtnTxt}>Save & Continue</Text>
        </Pressable>
        <Pressable onPress={resetChanges} style={styles.actionGhost} testID="fm-reset">
          <Ionicons name="refresh-outline" size={14} color={colors.onSurfaceSecondary} />
          <Text style={styles.actionGhostTxt}>Reset</Text>
        </Pressable>
        <Pressable onPress={cancelAndClose} style={styles.actionGhost} testID="fm-cancel">
          <Ionicons name="close-outline" size={14} color={colors.onSurfaceSecondary} />
          <Text style={styles.actionGhostTxt}>Cancel</Text>
        </Pressable>
        {isSuper ? (
          <Pressable onPress={() => void cloneCompany()} style={styles.actionGhost} testID="fm-clone">
            <Ionicons name="copy-outline" size={14} color={colors.onSurfaceSecondary} />
            <Text style={styles.actionGhostTxt}>Clone Company</Text>
          </Pressable>
        ) : null}
        <Pressable onPress={() => void exportConfig()} style={styles.actionGhost} testID="fm-export">
          <Ionicons name="download-outline" size={14} color={colors.onSurfaceSecondary} />
          <Text style={styles.actionGhostTxt}>Export Configuration</Text>
        </Pressable>
        <View style={{ flex: 1 }} />
        {master.updated_at ? (
          <Text style={styles.actionMeta}>
            Last modified {String(master.updated_at).replace("T", " ").slice(0, 16)}
            {master.updated_by_name ? ` · ${master.updated_by_name}` : ""}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

/* -------------------------------------------------------------------- */
/*  Styles                                                              */
/* -------------------------------------------------------------------- */

const styles = StyleSheet.create({
  // Iter 484 — ERP shell: side nav, chips, action bar, auto-save pill.
  navCol: {
    width: 232, borderRightWidth: 1, borderRightColor: colors.divider,
    backgroundColor: colors.surfaceSecondary, flexGrow: 0,
  },
  navItem: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 12, paddingVertical: 9, marginHorizontal: 6,
    borderRadius: 8, marginBottom: 1,
  },
  navItemOn: { backgroundColor: colors.brandTertiary },
  navNum: { width: 18, fontSize: 10.5, fontWeight: "800", color: colors.onSurfaceTertiary, textAlign: "right" },
  navTxt: { fontSize: 12, color: colors.onSurfaceSecondary, flex: 1 },
  navTxtOn: { color: colors.brandPrimary, fontWeight: "800" },
  navChipsRow: {
    flexGrow: 0, borderBottomWidth: 1, borderBottomColor: colors.divider,
    backgroundColor: colors.surfaceSecondary,
  },
  navChip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 6, backgroundColor: colors.surface,
  },
  navChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  navChipTxt: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  secHeadBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    flexWrap: "wrap", gap: 6,
  },
  secHeadTxt: { fontSize: 16, fontWeight: "900", color: colors.onSurface },
  secHeadMeta: { fontSize: 10.5, color: colors.onSurfaceTertiary },
  autoPill: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 5, backgroundColor: colors.surface,
  },
  autoPillTxt: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  integrationBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderWidth: 1, borderColor: colors.border, borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 10, backgroundColor: colors.surface,
    minWidth: 220,
  },
  integrationBtnTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface, flex: 1 },
  actionBar: {
    flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap",
    paddingHorizontal: spacing.md, paddingVertical: 8,
    borderTopWidth: 1, borderTopColor: colors.divider,
    backgroundColor: colors.surfaceSecondary,
  },
  actionBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 14, paddingVertical: 9,
  },
  actionBtnTxt: { fontSize: 12.5, fontWeight: "800", color: "#FFF" },
  actionGhost: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 11, paddingVertical: 8, backgroundColor: colors.surface,
  },
  actionGhostTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  actionMeta: { fontSize: 10.5, color: colors.onSurfaceTertiary },
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
  // Iter 476 — sticky unsaved-changes banner
  dirtyBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    flexWrap: "wrap",
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    backgroundColor: "#FFFBEB",
    borderBottomWidth: 1,
    borderBottomColor: "#FDE68A",
  },
  dirtyBannerTxt: { flex: 1, minWidth: 200, fontSize: 12.5, fontWeight: "700", color: "#92400E" },
  dirtyBannerBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#B45309",
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  dirtyBannerBtnTxt: { color: "#FFF", fontSize: 12, fontWeight: "800" },
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
