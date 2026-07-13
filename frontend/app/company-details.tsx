import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
  Modal,
  TextInput,
  Alert,
  Platform,
  Share,
  Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";

type Company = {
  company_id: string;
  company_code: string;
  name: string;
  address?: string | null;
  office_lat: number;
  office_lng: number;
  geofence_radius_m: number;
  business_category?: string | null;
  business_subcategory?: string | null;
  compliance_enabled?: boolean;
  punch_approval_required?: boolean;
  auto_punch_enabled?: boolean;
  // Iter 64 — Firm-level GPS punching master switch. Default FALSE.
  location_punching_enabled?: boolean;
  enabled: boolean;
  disabled_at?: string | null;
  disabled_reason?: string | null;
  created_at?: string;
  attendance_policy_updated_at?: string | null;
};

type CompanyAdmin = {
  user_id: string;
  name?: string;
  email?: string | null;
  phone?: string | null;
  role: string;
  employee_code?: string | null;
  designation?: string | null;
  created_at?: string;
  disabled?: boolean;
  credentials_updated_at?: string | null;
};

type PinMeta = {
  has_pin: boolean;
  must_change: boolean;
  set_at?: string | null;
  last_login_at?: string | null;
  locked_until?: string | null;
  fail_count: number;
  reset_by?: string | null;
};

type DetailsResponse = {
  company: Company;
  company_admin: CompanyAdmin | null;
  pin_meta: PinMeta | null;
  temp_credentials: TempCredentials | null;
  stats: {
    total_employees: number;
    active_employees: number;
    disabled_employees: number;
    present_today: number;
    pending_leaves: number;
    open_tickets: number;
    devices: number;
  };
  recent_actions: {
    at: string;
    action: string;
    actor_email?: string;
    reason?: string;
    target_user_id?: string;
  }[];
};

type TempCredentials = {
  identifier?: string | null;
  email?: string | null;
  phone?: string | null;
  temp_pin?: string | null;
  temp_password?: string | null;
  generated_at?: string | null;
  pin_changed?: boolean;
  password_changed?: boolean;
};

export default function CompanyDetailsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { company_id } = useLocalSearchParams<{ company_id: string }>();
  const isSuper = user?.role === "super_admin";

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<DetailsResponse | null>(null);

  const [editorOpen, setEditorOpen] = useState(false);
  const [disableOpen, setDisableOpen] = useState(false);
  const [pinRevealed, setPinRevealed] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!company_id) return;
    try {
      setError(null);
      const r = await api<DetailsResponse>(`/companies/${company_id}/details`);
      setData(r);
    } catch (e: any) {
      setError(e?.message || "Failed to load company");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [company_id]);

  useEffect(() => {
    if (user?.role !== "super_admin") return;
    setLoading(true);
    load();
  }, [user?.role, load]);

  if (user?.role !== "super_admin") {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
          <Header title="Company details" onBack={() => router.back()} />
        </SafeAreaView>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.dim}>Super admin only</Text>
        </View>
      </View>
    );
  }

  const resetPin = async () => {
    const confirmMsg = "Reset the company admin's PIN?\n\nA new 6-digit PIN will be shown ONCE. The admin will be forced to change it on next login and any active sessions will be signed out.";
    const proceed = async () => {
      try {
        const r = await api<{ ok: boolean; temp_pin: string; identifier?: string }>(
          `/companies/${company_id}/admin/reset-pin`,
          { method: "POST" },
        );
        setPinRevealed(r.temp_pin);
        await load();
      } catch (e: any) {
        alertUser("Reset failed", e?.message || "Please try again.");
      }
    };
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && window.confirm(confirmMsg)) proceed();
    } else {
      Alert.alert("Reset admin PIN", confirmMsg, [
        { text: "Cancel", style: "cancel" },
        { text: "Reset", style: "destructive", onPress: proceed },
      ]);
    }
  };

  const toggleAutoPunch = async () => {
    if (!data) return;
    const currentlyOn = data.company.auto_punch_enabled !== false;
    const proceedMsg = currentlyOn
      ? "Switch to MANUAL mode?\n\nEmployees will see a manual Punch In / Out button on their app. Geofence + GPS-on are still required to punch."
      : "Switch to AUTO-PUNCH mode?\n\nThe app will automatically punch employees IN/OUT as they enter/leave the geofence. The manual punch button will be hidden.";
    const proceed = async () => {
      try {
        await api(`/companies/${company_id}`, {
          method: "PATCH",
          body: { auto_punch_enabled: !currentlyOn },
        });
        await load();
      } catch (e: any) {
        alertUser("Update failed", e?.message || "Please try again.");
      }
    };
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && window.confirm(proceedMsg)) proceed();
    } else {
      Alert.alert(
        currentlyOn ? "Disable auto-punch" : "Enable auto-punch",
        proceedMsg,
        [
          { text: "Cancel", style: "cancel" },
          { text: currentlyOn ? "Switch to Manual" : "Enable Auto", onPress: proceed },
        ],
      );
    }
  };

  const toggleCompany = async (reason?: string) => {
    if (!data) return;
    try {
      const nextEnabled = !data.company.enabled;
      await api(`/companies/${company_id}/enabled`, {
        method: "PATCH",
        body: { enabled: nextEnabled, reason: reason || null },
      });
      setDisableOpen(false);
      await load();
      alertUser(
        nextEnabled ? "Company enabled" : "Company disabled",
        nextEnabled
          ? "All users of this firm can log in again."
          : "Every user of this firm has been signed out and cannot log in until re-enabled.",
      );
    } catch (e: any) {
      alertUser("Action failed", e?.message || "Please try again.");
    }
  };

  const copyPin = async () => {
    if (!pinRevealed) return;
    try {
      if (Platform.OS === "web" && navigator?.clipboard) {
        await navigator.clipboard.writeText(pinRevealed);
        alertUser("Copied", `PIN ${pinRevealed} copied to clipboard.`);
      } else {
        await Share.share({ message: `New admin PIN for ${data?.company?.name}: ${pinRevealed}` });
      }
    } catch {}
  };

  if (loading) {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
          <Header title="Company details" onBack={() => router.back()} />
        </SafeAreaView>
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
        </View>
      </View>
    );
  }

  if (error || !data) {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
          <Header title="Company details" onBack={() => router.back()} />
        </SafeAreaView>
        <View style={styles.center}>
          <Ionicons name="alert-circle" size={40} color={colors.error} />
          <Text style={styles.dim}>{error || "Could not load"}</Text>
          <Pressable onPress={load} style={styles.retry}>
            <Text style={styles.retryTxt}>Retry</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  const { company, company_admin, pin_meta, stats } = data;
  const bizLabel = formatCategory(company.business_category, company.business_subcategory);

  return (
    <View style={styles.root} testID="company-details-screen">
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <Header title="Company details" onBack={() => router.back()} />
      </SafeAreaView>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              load();
            }}
            tintColor={colors.brandPrimary}
          />
        }
      >
        {/* Hero */}
        <View style={styles.hero}>
          <View style={styles.heroTop}>
            {/* Iter 89 — Firm logo shown alongside the firm name so
                super_admins see it immediately when opening the details
                page. Falls back to a building icon when no logo yet.
                Web-only "Change" button opens the native file picker,
                uploads via PATCH /admin/firm-master/{cid} → the response
                mirrors to companies.logo_base64 so the sidebar refreshes
                on the next reload. */}
            <Pressable
              style={styles.heroLogoWrap}
              onPress={() => {
                if (Platform.OS !== "web") return;
                const input = (globalThis as any).document?.createElement?.("input");
                if (!input) return;
                input.type = "file";
                input.accept = "image/png,image/jpeg,image/webp";
                input.onchange = (e: any) => {
                  const file = e?.target?.files?.[0];
                  if (!file) return;
                  if (file.size > 2 * 1024 * 1024) {
                    window.alert("Logo must be under 2 MB.");
                    return;
                  }
                  const reader = new (globalThis as any).FileReader();
                  reader.onloadend = async () => {
                    try {
                      await api(`/admin/firm-master/${company.company_id}`, {
                        method: "PATCH",
                        body: {
                          logo: {
                            image_base64: reader.result,
                            mime_type: file.type,
                          },
                        },
                      });
                      window.alert("Logo updated. Reloading…");
                      window.location.reload();
                    } catch (e: any) {
                      window.alert(e?.message || "Upload failed");
                    }
                  };
                  reader.readAsDataURL(file);
                };
                input.click();
              }}
              testID="cd-logo-upload"
            >
              {(company as any).logo_base64 ? (
                <Image
                  source={{ uri: (company as any).logo_base64 }}
                  style={styles.heroLogoImg}
                  resizeMode="contain"
                />
              ) : (
                <Ionicons name="cloud-upload-outline" size={26} color={colors.brandPrimary} />
              )}
              {Platform.OS === "web" ? (
                <Text style={styles.heroLogoHint}>
                  {(company as any).logo_base64 ? "Change" : "Upload"}
                </Text>
              ) : null}
            </Pressable>
            <View style={{ flex: 1 }}>
              <Text style={styles.name}>{company.name}</Text>
              <Text style={styles.code}>Code · {company.company_code}</Text>
              {bizLabel ? (
                <View style={styles.bizBadge}>
                  <Ionicons name="briefcase-outline" size={11} color={colors.brandPrimary} />
                  <Text style={styles.bizTxt}>{bizLabel}</Text>
                </View>
              ) : null}
            </View>
            <View
              style={[
                styles.statusPill,
                company.enabled ? styles.pillOn : styles.pillOff,
              ]}
            >
              <Ionicons
                name={company.enabled ? "checkmark-circle" : "pause-circle"}
                size={12}
                color={company.enabled ? "#065F46" : "#991B1B"}
              />
              <Text style={[styles.statusTxt, { color: company.enabled ? "#065F46" : "#991B1B" }]}>
                {company.enabled ? "ACTIVE" : "DISABLED"}
              </Text>
            </View>
          </View>
          {!company.enabled && company.disabled_reason ? (
            <View style={styles.disabledBanner}>
              <Ionicons name="alert-circle" size={14} color="#991B1B" />
              <Text style={styles.disabledTxt}>{company.disabled_reason}</Text>
            </View>
          ) : null}
        </View>

        {/* Quick actions */}
        <View style={styles.actionsRow}>
          <ActionBtn
            icon={company.enabled ? "pause-circle" : "play-circle"}
            label={company.enabled ? "Disable" : "Enable"}
            tone={company.enabled ? "danger" : "primary"}
            onPress={() => (company.enabled ? setDisableOpen(true) : toggleCompany())}
            testID="btn-disable"
          />
          <ActionBtn
            icon="create-outline"
            label="Edit credentials"
            tone="ghost"
            onPress={() => setEditorOpen(true)}
            testID="btn-edit-creds"
          />
          <ActionBtn
            icon="key-outline"
            label="Reset PIN"
            tone="ghost"
            onPress={resetPin}
            testID="btn-reset-pin"
          />
        </View>

        {/* Stats grid */}
        <Section title="At a glance">
          <View style={styles.statsGrid}>
            <StatTile label="EMPLOYEES" value={stats.total_employees} />
            <StatTile label="ACTIVE" value={stats.active_employees} tint="#065F46" />
            <StatTile label="DISABLED" value={stats.disabled_employees} tint="#991B1B" />
            <StatTile label="PRESENT TODAY" value={stats.present_today} tint={colors.brandPrimary} />
            <StatTile label="PENDING LEAVES" value={stats.pending_leaves} tint={colors.accent} />
            <StatTile label="OPEN TICKETS" value={stats.open_tickets} tint={colors.accent} />
            <StatTile label="ZKTECO DEVICES" value={stats.devices} tint={colors.brandPrimary} />
          </View>
        </Section>

        {/* Company profile */}
        <Section title="Company profile">
          <KV label="Company name" value={company.name} />
          <KV label="Firm code" value={company.company_code} mono />
          <KV label="Business type" value={bizLabel || "—"} />
          <KV label="Address" value={company.address || "—"} multiline />
          <KV
            label="Office location"
            value={`${company.office_lat.toFixed(6)}, ${company.office_lng.toFixed(6)}`}
            mono
          />
          <KV label="Geofence radius" value={`${company.geofence_radius_m} m`} />
          <KV
            label="Compliance module"
            value={company.compliance_enabled === false ? "OFF" : "ON"}
          />
          <KV
            label="Auto-punch approval"
            value={company.punch_approval_required === false ? "OFF" : "ON"}
          />
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <View style={{ flex: 1 }}>
              <KV
                label="Auto-punch mode"
                value={company.auto_punch_enabled === false ? "OFF (manual)" : "ON (geofence)"}
                tint={company.auto_punch_enabled === false ? "#7A4E00" : "#065F46"}
              />
            </View>
            <Pressable
              testID="toggle-auto-punch"
              onPress={toggleAutoPunch}
              style={styles.inlineToggleBtn}
              hitSlop={8}
            >
              <Ionicons
                name="swap-horizontal"
                size={14}
                color={colors.brandPrimary}
              />
              <Text style={styles.inlineToggleTxt}>Switch</Text>
            </Pressable>
          </View>
          <KV label="Created" value={fmtDate(company.created_at)} />
        </Section>

        {/* Iter 61 — Payslip auto-email toggle (super admin only, web only) */}
        {isSuper && Platform.OS === "web" ? (
          <PayslipEmailToggleSection companyId={company_id!} />
        ) : null}

        {/* Company admin */}
        <Section title="Company admin login">
          {company_admin ? (
            <>
              <KV label="Name" value={company_admin.name || "—"} />
              <KV label="Registered mobile" value={company_admin.phone || "— not set"} mono />
              <KV label="Email" value={company_admin.email || "— not set"} />
              <KV label="Role" value={company_admin.role.replace(/_/g, " ")} />
              <KV
                label="Status"
                value={company_admin.disabled ? "Disabled" : "Active"}
                tint={company_admin.disabled ? "#991B1B" : "#065F46"}
              />
              <KV label="Credentials last edited" value={fmtDate(company_admin.credentials_updated_at)} />
            </>
          ) : (
            <Text style={styles.dimSmall}>No company admin found for this firm.</Text>
          )}
        </Section>

        {/* PIN status */}
        <Section title="Login PIN">
          <View style={styles.pinNote}>
            <Ionicons name="shield-checkmark" size={14} color={colors.brandPrimary} />
            <Text style={styles.pinNoteTxt}>
              For security, PINs are stored one-way hashed and cannot be shown. Use{" "}
              <Text style={{ fontWeight: "800" }}>Reset PIN</Text> to generate a new PIN — it
              is revealed once here so you can share it with the admin.
            </Text>
          </View>
          {pin_meta ? (
            <>
              <KV
                label="PIN set"
                value={pin_meta.has_pin ? "Yes" : "No"}
                tint={pin_meta.has_pin ? "#065F46" : "#991B1B"}
              />
              <KV
                label="Must change on next login"
                value={pin_meta.must_change ? "Yes (temporary)" : "No"}
              />
              <KV label="PIN last set" value={fmtDate(pin_meta.set_at)} />
              <KV label="Last successful login" value={fmtDate(pin_meta.last_login_at)} />
              {pin_meta.locked_until ? (
                <KV
                  label="Locked until"
                  value={fmtDate(pin_meta.locked_until)}
                  tint="#991B1B"
                />
              ) : null}
              <KV
                label="Recent failed attempts"
                value={String(pin_meta.fail_count || 0)}
                tint={pin_meta.fail_count >= 3 ? "#B45309" : undefined}
              />
            </>
          ) : (
            <Text style={styles.dimSmall}>No PIN metadata available.</Text>
          )}
        </Section>

        {/* Temp credentials — visible only while the admin still owes a first-time change */}
        {data.temp_credentials &&
        (data.temp_credentials.temp_pin || data.temp_credentials.temp_password) ? (
          <Section title="Temporary credentials">
            <View style={styles.pinNote}>
              <Ionicons name="shield-checkmark" size={14} color={colors.brandPrimary} />
              <Text style={styles.pinNoteTxt}>
                One-time credentials generated by the super admin. They stop being visible the
                moment the admin changes their own PIN / password on first login.
              </Text>
            </View>
            <KV
              label="Login identifier"
              value={data.temp_credentials.identifier || "—"}
              mono
            />
            {data.temp_credentials.temp_pin ? (
              <CredentialRow
                testID="temp-pin"
                label="Temp PIN (mobile app)"
                value={data.temp_credentials.temp_pin}
              />
            ) : (
              <KV
                label="Temp PIN"
                value={
                  data.temp_credentials.pin_changed
                    ? "Admin has set their own PIN"
                    : "— not generated"
                }
                tint={data.temp_credentials.pin_changed ? "#065F46" : undefined}
              />
            )}
            {data.temp_credentials.temp_password ? (
              <CredentialRow
                testID="temp-password"
                label="Temp password (web portal)"
                value={data.temp_credentials.temp_password}
              />
            ) : (
              <KV
                label="Temp password"
                value={
                  data.temp_credentials.password_changed
                    ? "Admin has set their own password"
                    : "— not generated"
                }
                tint={data.temp_credentials.password_changed ? "#065F46" : undefined}
              />
            )}
            <KV
              label="Generated at"
              value={fmtDate(data.temp_credentials.generated_at)}
            />
          </Section>
        ) : null}

        {/* Audit trail */}
        {data.recent_actions.length > 0 ? (
          <Section title="Recent super-admin actions">
            {data.recent_actions.map((a, i) => (
              <View key={`${a.at}-${i}`} style={styles.auditRow}>
                <Ionicons
                  name={AUDIT_ICON[a.action] || "ellipse-outline"}
                  size={14}
                  color={colors.brandPrimary}
                />
                <View style={{ flex: 1 }}>
                  <Text style={styles.auditAction}>{humanAction(a.action)}</Text>
                  <Text style={styles.auditMeta}>
                    {a.actor_email || "system"} · {fmtRelative(a.at)}
                    {a.reason ? ` · ${a.reason}` : ""}
                  </Text>
                </View>
              </View>
            ))}
          </Section>
        ) : null}

        <View style={{ height: 40 }} />
      </ScrollView>

      {/* Credentials editor */}
      {company_admin ? (
        <CredentialsEditor
          visible={editorOpen}
          onClose={() => setEditorOpen(false)}
          initial={company_admin}
          onSaved={async () => {
            setEditorOpen(false);
            await load();
          }}
          companyId={company_id!}
        />
      ) : null}

      {/* Disable modal */}
      <DisableModal
        visible={disableOpen}
        onClose={() => setDisableOpen(false)}
        onSubmit={toggleCompany}
        companyName={company.name}
      />

      {/* PIN reveal */}
      <Modal
        transparent
        animationType="fade"
        visible={!!pinRevealed}
        onRequestClose={() => setPinRevealed(null)}
      >
        <Pressable style={styles.backdrop} onPress={() => setPinRevealed(null)} />
        <View style={styles.centerModal}>
          <View style={styles.pinCard}>
            <View style={styles.pinIcon}>
              <Ionicons name="key" size={26} color={colors.brandPrimary} />
            </View>
            <Text style={styles.pinTitle}>New admin PIN</Text>
            <Text style={styles.pinBody}>
              Share this 6-digit PIN with the company admin. It will be shown{" "}
              <Text style={{ fontWeight: "800" }}>only once</Text>. The admin will be forced to
              set a new PIN on next login.
            </Text>
            <View style={styles.pinValueBox}>
              <Text style={styles.pinValue}>{pinRevealed}</Text>
            </View>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <Pressable onPress={copyPin} style={[styles.sheetBtn, styles.sheetSubmit]}>
                <Ionicons name="copy-outline" size={16} color="#fff" />
                <Text style={styles.sheetSubmitTxt}>
                  {Platform.OS === "web" ? "Copy" : "Share"}
                </Text>
              </Pressable>
              <Pressable
                onPress={() => setPinRevealed(null)}
                style={[styles.sheetBtn, styles.sheetCancel]}
              >
                <Text style={styles.sheetCancelTxt}>Close</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

// ------------- Sub-components -------------

function Header({ title, onBack }: { title: string; onBack: () => void }) {
  return (
    <View style={styles.header}>
      <Pressable onPress={onBack} hitSlop={8}>
        <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
      </Pressable>
      <Text style={styles.h1}>{title}</Text>
      <View style={{ width: 26 }} />
    </View>
  );
}


function PayslipEmailToggleSection({ companyId }: { companyId: string }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<{ enabled: boolean }>(
          `/admin/companies/${companyId}/payslip-email-config`,
        );
        setEnabled(!!r.enabled);
      } catch {
        setEnabled(false);
      }
    })();
  }, [companyId]);

  const flip = async () => {
    if (enabled === null || saving) return;
    const next = !enabled;
    setSaving(true);
    try {
      await api(`/admin/companies/${companyId}/payslip-email-config`, {
        method: "PUT",
        body: { enabled: next },
      });
      setEnabled(next);
    } catch (e: any) {
      if (Platform.OS === "web") globalThis.alert(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section title="Payslip auto-email">
      <View style={{ paddingVertical: 4 }}>
        <Text style={{ fontSize: 12, color: colors.onSurfaceSecondary, lineHeight: 18 }}>
          When ON, each employee automatically receives their monthly payslip
          via email as soon as the Super Admin generates payslips from a
          salary run. Requires an email on file for the employee.
        </Text>
      </View>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 12,
          marginTop: 8,
        }}
      >
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: 14, fontWeight: "700", color: colors.onSurface }}>
            {enabled === null ? "Loading…" : enabled ? "Auto-email enabled" : "Auto-email disabled"}
          </Text>
          <Text style={{ fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 }}>
            Delivered via Resend when payslips are generated from a salary run.
          </Text>
        </View>
        <Pressable
          onPress={flip}
          disabled={saving || enabled === null}
          style={{
            paddingHorizontal: 14,
            paddingVertical: 8,
            borderRadius: 999,
            backgroundColor: enabled ? colors.brandPrimary : "#E5E7EB",
            opacity: saving ? 0.6 : 1,
          }}
          testID="payslip-email-toggle"
        >
          <Text
            style={{
              color: enabled ? "#fff" : "#111",
              fontWeight: "800",
              fontSize: 12,
            }}
          >
            {enabled ? "ON" : "OFF"} · Tap to {enabled ? "disable" : "enable"}
          </Text>
        </Pressable>
      </View>
    </Section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.card}>{children}</View>
    </View>
  );
}

function KV({
  label,
  value,
  mono,
  multiline,
  tint,
}: {
  label: string;
  value?: string | null;
  mono?: boolean;
  multiline?: boolean;
  tint?: string;
}) {
  return (
    <View style={styles.kv}>
      <Text style={styles.kvL}>{label}</Text>
      <Text
        style={[
          styles.kvV,
          mono && { fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }) },
          tint && { color: tint, fontWeight: "700" },
        ]}
        numberOfLines={multiline ? 6 : 2}
      >
        {value || "—"}
      </Text>
    </View>
  );
}

function StatTile({ label, value, tint }: { label: string; value: number; tint?: string }) {
  return (
    <View style={styles.statTile}>
      <Text style={[styles.statVal, tint && { color: tint }]}>{value}</Text>
      <Text style={styles.statLbl}>{label}</Text>
    </View>
  );
}

function CredentialRow({ label, value, testID }: { label: string; value: string; testID?: string }) {
  const [reveal, setReveal] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      if (Platform.OS === "web" && navigator?.clipboard) {
        await navigator.clipboard.writeText(value);
      } else {
        await Share.share({ message: `${label}: ${value}` });
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };
  const masked = value.replace(/./g, "•");
  return (
    <View style={styles.credRow} testID={testID}>
      <View style={{ flex: 1 }}>
        <Text style={styles.kvL}>{label.toUpperCase()}</Text>
        <Text
          style={[
            styles.credVal,
            reveal && { color: colors.brandPrimary, letterSpacing: 2 },
          ]}
          selectable
          numberOfLines={1}
        >
          {reveal ? value : masked}
        </Text>
      </View>
      <Pressable onPress={() => setReveal((v) => !v)} hitSlop={8} style={styles.credBtn}>
        <Ionicons
          name={reveal ? "eye-off-outline" : "eye-outline"}
          size={16}
          color={colors.onSurfaceSecondary}
        />
      </Pressable>
      <Pressable onPress={copy} hitSlop={8} style={styles.credBtn}>
        <Ionicons
          name={copied ? "checkmark" : "copy-outline"}
          size={16}
          color={copied ? "#065F46" : colors.brandPrimary}
        />
      </Pressable>
    </View>
  );
}

function ActionBtn({
  icon,
  label,
  tone,
  onPress,
  testID,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  tone: "primary" | "danger" | "ghost";
  onPress: () => void;
  testID?: string;
}) {
  const color =
    tone === "primary" ? colors.brandPrimary : tone === "danger" ? colors.error : colors.brandPrimary;
  const bg =
    tone === "primary" ? colors.brandPrimary : tone === "danger" ? colors.surface : colors.brandTertiary;
  const fg = tone === "primary" ? colors.onCta : color;
  const border = tone === "danger" ? colors.error : colors.brandPrimary;
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      style={[
        styles.actionBtn,
        { backgroundColor: bg, borderColor: border },
      ]}
    >
      <Ionicons name={icon} size={16} color={fg} />
      <Text style={[styles.actionTxt, { color: fg }]}>{label}</Text>
    </Pressable>
  );
}

function CredentialsEditor({
  visible,
  onClose,
  initial,
  onSaved,
  companyId,
}: {
  visible: boolean;
  onClose: () => void;
  initial: CompanyAdmin;
  onSaved: () => void;
  companyId: string;
}) {
  const [name, setName] = useState(initial.name || "");
  const [phone, setPhone] = useState(initial.phone || "");
  const [email, setEmail] = useState(initial.email || "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (visible) {
      setName(initial.name || "");
      setPhone(initial.phone || "");
      setEmail(initial.email || "");
    }
  }, [visible, initial]);

  const save = async () => {
    setSaving(true);
    try {
      await api(`/companies/${companyId}/admin`, {
        method: "PATCH",
        body: {
          name: name.trim() || null,
          phone: phone.trim() || null,
          email: email.trim() || null,
        },
      });
      onSaved();
    } catch (e: any) {
      alertUser("Save failed", e?.message || "Please try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal transparent animationType="slide" visible={visible} onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} />
      <KeyboardAwareScrollView
        bottomOffset={40}
        contentContainerStyle={{ flexGrow: 1, justifyContent: "flex-end" }}
      >
        <View style={styles.sheet}>
          <View style={styles.grip} />
          <Text style={styles.sheetTitle}>Edit company admin</Text>
          <Text style={styles.sheetSub}>
            Update the admin&apos;s display name, registered mobile, or e-mail. Changing the
            mobile also changes the login identifier. To rotate the PIN use{" "}
            <Text style={{ fontWeight: "800" }}>Reset PIN</Text> on the previous screen.
          </Text>
          <Text style={styles.lbl}>Display name</Text>
          <TextInput
            value={name}
            onChangeText={setName}
            placeholder="Ankit Sharma"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={styles.input}
            testID="ed-name"
          />
          <Text style={styles.lbl}>Registered mobile</Text>
          <TextInput
            value={phone}
            onChangeText={setPhone}
            placeholder="+91 96802 73960"
            placeholderTextColor={colors.onSurfaceTertiary}
            keyboardType="phone-pad"
            style={styles.input}
            testID="ed-phone"
          />
          <Text style={styles.lbl}>Email</Text>
          <TextInput
            value={email}
            onChangeText={setEmail}
            placeholder="admin@example.com"
            placeholderTextColor={colors.onSurfaceTertiary}
            keyboardType="email-address"
            autoCapitalize="none"
            style={styles.input}
            testID="ed-email"
          />
          <View style={styles.sheetActions}>
            <Pressable onPress={onClose} style={[styles.sheetBtn, styles.sheetCancel]}>
              <Text style={styles.sheetCancelTxt}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={save}
              testID="ed-save"
              style={[styles.sheetBtn, styles.sheetSubmit, saving && { opacity: 0.7 }]}
              disabled={saving}
            >
              {saving ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="checkmark-circle" size={16} color="#fff" />
                  <Text style={styles.sheetSubmitTxt}>Save</Text>
                </>
              )}
            </Pressable>
          </View>
        </View>
      </KeyboardAwareScrollView>
    </Modal>
  );
}

function DisableModal({
  visible,
  onClose,
  onSubmit,
  companyName,
}: {
  visible: boolean;
  onClose: () => void;
  onSubmit: (reason: string) => void;
  companyName: string;
}) {
  const [reason, setReason] = useState("");
  useEffect(() => {
    if (visible) setReason("");
  }, [visible]);
  return (
    <Modal transparent animationType="slide" visible={visible} onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} />
      <KeyboardAwareScrollView
        bottomOffset={40}
        contentContainerStyle={{ flexGrow: 1, justifyContent: "flex-end" }}
      >
        <View style={styles.sheet}>
          <View style={styles.grip} />
          <Text style={styles.sheetTitle}>Disable company</Text>
          <Text style={styles.sheetSub}>
            &quot;{companyName}&quot; will be paused — every user of this firm is signed out
            and blocked from logging in. Attendance data stays intact. You can re-enable at any
            time.
          </Text>
          <Text style={styles.lbl}>Reason (optional but recommended)</Text>
          <TextInput
            value={reason}
            onChangeText={setReason}
            multiline
            placeholder="E.g. Non-payment · account under review"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={[styles.input, { minHeight: 80 }]}
          />
          <View style={styles.sheetActions}>
            <Pressable onPress={onClose} style={[styles.sheetBtn, styles.sheetCancel]}>
              <Text style={styles.sheetCancelTxt}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={() => onSubmit(reason)}
              style={[styles.sheetBtn, styles.sheetSubmit, { backgroundColor: colors.error }]}
            >
              <Ionicons name="pause-circle" size={16} color="#fff" />
              <Text style={styles.sheetSubmitTxt}>Disable company</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAwareScrollView>
    </Modal>
  );
}

// ------------- helpers -------------

const AUDIT_ICON: Record<string, keyof typeof Ionicons.glyphMap> = {
  "company.disable": "pause-circle",
  "company.enable": "play-circle",
  "admin.credentials_update": "create-outline",
  "admin.pin_reset": "key-outline",
  "user.disable": "close-circle",
  "user.enable": "checkmark-circle",
};

function humanAction(a: string): string {
  return {
    "company.disable": "Company disabled",
    "company.enable": "Company enabled",
    "admin.credentials_update": "Admin credentials updated",
    "admin.pin_reset": "Admin PIN reset",
    "user.disable": "Employee disabled",
    "user.enable": "Employee enabled",
  }[a] || a;
}

function formatCategory(cat?: string | null, sub?: string | null): string {
  if (!cat) return "";
  const nice = cat
    .split("_")
    .map((p) => (p.length ? p[0].toUpperCase() + p.slice(1) : p))
    .join(" ")
    .replace("It Company", "IT Company")
    .replace("Hotel Resort", "Hotel / Resort");
  return sub ? `${nice} — ${sub}` : nice;
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-IN", {
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

function fmtRelative(iso: string): string {
  try {
    const s = Math.max(1, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch {
    return iso;
  }
}

function alertUser(title: string, msg: string) {
  if (Platform.OS === "web") {
    if (typeof window !== "undefined") window.alert(`${title}\n\n${msg}`);
    return;
  }
  Alert.alert(title, msg);
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  h1: { fontSize: type.lg, color: colors.onSurface, fontWeight: "700" },
  scroll: { padding: spacing.lg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: 10 },
  dim: { color: colors.onSurfaceSecondary, fontSize: type.base },
  dimSmall: { color: colors.onSurfaceTertiary, fontSize: type.sm, padding: spacing.md },
  inlineToggleBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  inlineToggleTxt: {
    color: colors.brandPrimary,
    fontWeight: "700",
    fontSize: 12,
  },
  retry: {
    marginTop: 8,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: radius.pill,
    backgroundColor: colors.brandPrimary,
  },
  retryTxt: { color: "#fff", fontWeight: "700" },

  hero: {
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  heroTop: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  // Iter 89 — firm logo cluster inside the hero
  heroLogoWrap: {
    width: 68, height: 68,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center", justifyContent: "center",
    overflow: "hidden",
    marginRight: 4,
  },
  heroLogoImg: { width: "100%", height: "100%" },
  heroLogoHint: {
    position: "absolute", bottom: 2, left: 2, right: 2,
    textAlign: "center",
    fontSize: 9, fontWeight: "800",
    color: colors.onBrandPrimary,
    backgroundColor: "rgba(15,23,42,0.55)",
    paddingVertical: 1,
    borderRadius: 3,
  },
  name: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800" },
  code: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 2 },
  bizBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    alignSelf: "flex-start",
    paddingHorizontal: 8,
    paddingVertical: 4,
    marginTop: 6,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  bizTxt: { color: colors.brandPrimary, fontSize: 11, fontWeight: "700" },
  statusPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  pillOn: { backgroundColor: "#D1FAE5" },
  pillOff: { backgroundColor: "#FEE2E2" },
  statusTxt: { fontSize: 10, fontWeight: "800", letterSpacing: 0.4 },
  disabledBanner: {
    flexDirection: "row",
    gap: 6,
    marginTop: 10,
    padding: 8,
    borderRadius: radius.sm,
    backgroundColor: "#FEE2E2",
  },
  disabledTxt: { color: "#991B1B", fontSize: 12, flex: 1 },

  actionsRow: { flexDirection: "row", gap: 8, marginTop: spacing.md },
  actionBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderRadius: radius.pill,
    borderWidth: 1,
  },
  actionTxt: { fontWeight: "700", fontSize: type.sm },

  section: { marginTop: spacing.lg },
  sectionTitle: {
    color: colors.onSurface,
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 0.6,
    textTransform: "uppercase",
    marginBottom: 8,
  },
  card: {
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    padding: spacing.md,
    ...shadow.card,
  },

  statsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  statTile: {
    width: "31%",
    padding: 8,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    minHeight: 66,
    justifyContent: "space-between",
  },
  statVal: { color: colors.onSurface, fontSize: 22, fontWeight: "800" },
  statLbl: { color: colors.onSurfaceTertiary, fontSize: 9, fontWeight: "700", letterSpacing: 0.4 },

  kv: {
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    gap: 2,
  },
  kvL: { color: colors.onSurfaceTertiary, fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },
  kvV: { color: colors.onSurface, fontSize: type.sm, fontWeight: "600" },
  credRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  credVal: {
    color: colors.onSurface,
    fontSize: 18,
    fontWeight: "800",
    letterSpacing: 4,
    marginTop: 4,
    fontFamily: Platform.select({
      ios: "Menlo",
      android: "monospace",
      default: "monospace",
    }),
  },
  credBtn: {
    padding: 6,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },

  pinNote: {
    flexDirection: "row",
    gap: 6,
    padding: spacing.sm,
    borderRadius: radius.sm,
    backgroundColor: colors.brandTertiary,
    marginBottom: spacing.sm,
  },
  pinNoteTxt: { color: colors.onSurface, fontSize: 12, flex: 1, lineHeight: 18 },

  auditRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  auditAction: { color: colors.onSurface, fontSize: type.sm, fontWeight: "700" },
  auditMeta: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },

  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.4)" },
  centerModal: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    padding: spacing.lg,
    maxHeight: "90%",
  },
  grip: {
    alignSelf: "center",
    width: 44,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    marginBottom: 4,
  },
  sheetTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  sheetSub: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    lineHeight: 18,
    marginTop: 4,
  },
  lbl: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "600",
    marginTop: 10,
    marginBottom: 4,
  },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.onSurface,
    fontSize: type.base,
  },
  sheetActions: { flexDirection: "row", gap: 10, marginTop: spacing.lg },
  sheetBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderRadius: radius.pill,
  },
  sheetCancel: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  sheetCancelTxt: { color: colors.onSurface, fontWeight: "700" },
  sheetSubmit: { backgroundColor: colors.brandPrimary },
  sheetSubmitTxt: { color: "#fff", fontWeight: "700" },

  pinCard: {
    width: "100%",
    maxWidth: 380,
    padding: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    ...shadow.card,
    alignItems: "center",
    gap: 8,
  },
  pinIcon: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  pinTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800" },
  pinBody: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    textAlign: "center",
    lineHeight: 20,
  },
  pinValueBox: {
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: 24,
    paddingVertical: 14,
    borderRadius: radius.md,
    marginVertical: 8,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
  },
  pinValue: {
    color: colors.brandPrimary,
    fontSize: 32,
    fontWeight: "800",
    letterSpacing: 8,
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
  },
});
