import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  Alert,
  Switch,
} from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useRouter, useFocusEffect } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { useAutoPunch } from "@/src/context/AutoPunchContext";
import { api } from "@/src/api/client";
import { colors, radius, spacing, type } from "@/src/theme";
import {
  areRemindersEnabled,
  enableReminders,
  disableReminders,
} from "@/src/utils/punchReminders";
import {
  fingerprintSupported, fingerprintEnrolled, enrollFingerprint, verifyFingerprint,
} from "@/src/utils/fingerprintGate";

const LOGO_MARK = require("../../assets/images/logo-mark.png");

export default function ProfileScreen() {
  const {
    user,
    logout,
    biometricEnabled,
    biometricSupported,
    biometricLabel,
    enableBiometric,
    disableBiometric,
    refresh,
  } = useAuth();
  const autoPunch = useAutoPunch();
  const router = useRouter();
  const insets = useSafeAreaInsets();

  // Refresh /auth/me on every tab focus so approvals (name / address /
  // family members applied by the admin) show up immediately without
  // needing to log out and back in.
  useFocusEffect(
    useCallback(() => {
      refresh().catch(() => {});
    }, [refresh]),
  );
  const [bioBusy, setBioBusy] = useState(false);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [remindersOn, setRemindersOn] = useState<boolean>(false);
  const [remindersBusy, setRemindersBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const on = await areRemindersEnabled();
      setRemindersOn(on);
    })();
  }, []);

  const isAdmin = user?.role !== "employee";
  const isSuper = user?.role === "super_admin";
  const [pendingEmpCount, setPendingEmpCount] = useState<number>(0);
  const [pendingReqCount, setPendingReqCount] = useState<number>(0);
  const [pendingProfileEditCount, setPendingProfileEditCount] =
    useState<number>(0);

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    (async () => {
      try {
        const promises: [Promise<any>, Promise<any>, Promise<any>] = [
          api<{ pending: any[] }>("/admin/pending-approvals").catch(() => ({
            pending: [],
          })),
          isSuper
            ? api<{ requests: any[] }>("/company-requests").catch(() => ({
                requests: [],
              }))
            : Promise.resolve({ requests: [] }),
          api<{ requests: any[] }>(
            "/admin/profile-edits?status=pending",
          ).catch(() => ({ requests: [] })),
        ];
        const [emp, req, edits] = await Promise.all(promises);
        if (cancelled) return;
        setPendingEmpCount((emp.pending || []).length);
        setPendingReqCount(
          (req.requests || []).filter(
            (r: any) => (r.status || "pending") === "pending",
          ).length,
        );
        setPendingProfileEditCount((edits.requests || []).length);
      } catch {}
    })();
    return () => {
      cancelled = true;
    };
  }, [isAdmin, isSuper]);

  const doLogout = async () => {
    if (logoutBusy) return;
    setLogoutBusy(true);
    try {
      await logout();
    } finally {
      setLogoutBusy(false);
    }
  };

  const onToggleBiometric = async () => {
    if (bioBusy) return;
    if (!biometricSupported) {
      Alert.alert(
        "Biometric unavailable",
        "This device doesn't have a fingerprint or Face ID enrolled. Set one up in your device Settings and try again.",
      );
      return;
    }
    setBioBusy(true);
    try {
      if (biometricEnabled) {
        await disableBiometric();
      } else {
        const ok = await enableBiometric();
        if (!ok) {
          Alert.alert(
            "Couldn't enable",
            `We couldn't confirm your ${biometricLabel}. Please try again.`,
          );
        }
      }
    } finally {
      setBioBusy(false);
    }
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Text style={styles.h1}>Profile</Text>
        </View>
      </SafeAreaView>

      <ScrollView
        contentContainerStyle={[
          styles.scroll,
          { paddingBottom: 78 + insets.bottom + 40 },
        ]}
      >
        <View style={styles.card} testID="profile-card">
          <Pressable
            onPress={
              user?.role === "employee"
                ? () => router.push("/profile-photo")
                : undefined
            }
            testID="profile-avatar"
          >
            {user?.profile_photo_base64 ? (
              <Image
                source={{
                  uri: user.profile_photo_base64.startsWith("data:")
                    ? user.profile_photo_base64
                    : `data:image/jpeg;base64,${user.profile_photo_base64}`,
                }}
                style={styles.avatar}
                contentFit="cover"
              />
            ) : user?.picture ? (
              <Image source={{ uri: user.picture }} style={styles.avatar} />
            ) : (
              <View style={[styles.avatar, styles.avatarFallback]}>
                <Text style={styles.avatarInit}>{user?.name?.[0] || "U"}</Text>
              </View>
            )}
            {user?.role === "employee" && (
              <View style={styles.cameraBadge}>
                <Ionicons name="camera" size={12} color="#fff" />
              </View>
            )}
          </Pressable>
          <Text style={styles.name}>{user?.name}</Text>
          {user?.role === "employee" && user?.employee_code ? (
            <Text style={styles.employeeCode} testID="profile-employee-code">
              ID: {user.employee_code}
            </Text>
          ) : null}
          <Text style={styles.email}>{user?.email}</Text>
          <View style={styles.roleChip}>
            <Text style={styles.roleTxt}>{roleLabel(user?.role)}</Text>
          </View>
        </View>

        <Text style={styles.section}>Workplace</Text>

        {/* Personal details — visible for employees. Renders the values
            applied by the last approved profile-edit request so employees
            can confirm the update went through. */}
        {user?.role === "employee" ? (
          <View style={styles.detailsCard} testID="personal-details">
            <View style={styles.detailsHead}>
              <Ionicons
                name="id-card-outline"
                size={16}
                color={colors.brandPrimary}
              />
              <Text style={styles.detailsTitle}>Personal details</Text>
            </View>
            <DetailLine
              label="Registered mobile"
              value={(user as any)?.phone || "—"}
            />
            <DetailLine
              label="Designation"
              value={(user as any)?.designation || "—"}
            />
            <DetailLine
              label="Salary roll"
              value={(user as any)?.is_onroll === false ? "Off-roll" : "On-roll"}
            />
            <DetailLine
              label="Father's name"
              value={(user as any)?.father_name || "—"}
            />
            <DetailLine
              label="Date of birth"
              value={fmtDDMMYYYY((user as any)?.dob)}
            />
            <DetailLine
              label="Date of joining"
              value={fmtDDMMYYYY((user as any)?.doj)}
            />
            <DetailLine
              label="Present address"
              value={(user as any)?.present_address || "—"}
              multiline
            />
            <DetailLine
              label="Permanent address"
              value={(user as any)?.permanent_address || "—"}
              multiline
            />

            {/* Family list */}
            {Array.isArray((user as any)?.family_members) &&
            (user as any).family_members.length > 0 ? (
              <View style={styles.familyBlock}>
                <Text style={styles.familyTitle}>
                  Family members · {(user as any).family_members.length}
                </Text>
                {((user as any).family_members || []).map(
                  (m: any, idx: number) => (
                    <View
                      key={`fam-${idx}`}
                      style={styles.familyRow}
                      testID={`family-row-${idx}`}
                    >
                      <View style={styles.familyAvatar}>
                        <Ionicons
                          name="person"
                          size={14}
                          color={colors.brandPrimary}
                        />
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.familyName} numberOfLines={1}>
                          {m?.name || "—"}
                          {m?.relation ? (
                            <Text style={styles.familyRel}>
                              {"  ·  "}
                              {m.relation}
                            </Text>
                          ) : null}
                        </Text>
                        <Text style={styles.familyMeta} numberOfLines={1}>
                          {[
                            m?.dob ? `DOB ${fmtDDMMYYYY(m.dob)}` : null,
                            m?.occupation || null,
                            m?.contact || null,
                          ]
                            .filter(Boolean)
                            .join("  ·  ") || "No extra info"}
                        </Text>
                      </View>
                    </View>
                  ),
                )}
              </View>
            ) : (
              <View style={styles.familyBlock}>
                <Text style={styles.familyEmpty}>
                  No family members added yet.
                </Text>
              </View>
            )}

            <Pressable
              style={styles.editBtn}
              onPress={() => router.push("/profile-edit")}
              testID="details-edit-btn"
            >
              <Ionicons
                name="create-outline"
                size={14}
                color={colors.brandPrimary}
              />
              <Text style={styles.editBtnTxt}>
                Request update (admin approval)
              </Text>
            </Pressable>
          </View>
        ) : null}

        {/* Iter 165 — Fingerprint verification card (only when the firm's
            Bio Matrix Attendance is enabled in Firm Master). */}
        {user?.role === "employee" && (user as any)?.firm_biometric_enabled ? (
          <FingerprintCard
            userId={user.user_id}
            userName={user.name || ""}
            required={(user as any)?.fingerprint_required === true}
          />
        ) : null}

        <Row
          testID="row-history"
          icon="time-outline"
          label="Attendance History"
          onPress={() => router.push("/history")}
        />
        <Row
          testID="row-id-card"
          icon="card-outline"
          label="My ID Card"
          onPress={() => router.push("/id-card")}
        />
        <Row
          testID="row-leaves"
          icon="calendar-outline"
          label="My Leaves"
          onPress={() => router.push("/leaves")}
        />
        <Row
          testID="row-tickets"
          icon="chatbubbles-outline"
          label="Service Tickets"
          onPress={() => router.push("/tickets")}
        />
        <Row
          testID="row-notifs"
          icon="notifications-outline"
          label="Notifications"
          onPress={() => router.push("/notifications")}
        />

        {isAdmin && (
          <>
            <Text style={styles.section}>Admin</Text>
            {user?.role === "super_admin" && (
              <>
                <Row
                  testID="row-companies"
                  icon="business-outline"
                  label="Companies"
                  onPress={() => router.push("/companies")}
                />
                <Row
                  testID="row-company-requests"
                  icon="mail-open-outline"
                  label="Company requests"
                  badgeCount={isSuper ? pendingReqCount : undefined}
                  onPress={() => router.push("/company-requests")}
                />
              </>
            )}
            <Row
              testID="row-admin"
              icon="briefcase-outline"
              label="Admin Panel"
              badgeCount={isAdmin ? pendingEmpCount : undefined}
              onPress={() => router.push("/admin")}
            />
            <Row
              testID="row-profile-edit-reviews"
              icon="clipboard-outline"
              label="Profile edit approvals"
              badgeCount={
                pendingProfileEditCount > 0 ? pendingProfileEditCount : undefined
              }
              onPress={() => router.push("/profile-edit-reviews")}
            />
            <Row
              testID="row-attendance-review"
              icon="shield-checkmark-outline"
              label="Attendance review"
              onPress={() => router.push("/attendance-review")}
            />
            <Row
              testID="row-payroll"
              icon="cash-outline"
              label="Payroll"
              onPress={() => router.push("/payroll")}
            />
          </>
        )}

        <Text style={styles.section}>Profile</Text>
        {user?.role === "employee" && (
          <Row
            testID="row-profile-edit"
            icon="create-outline"
            label="Edit my profile"
            onPress={() => router.push("/profile-edit")}
          />
        )}
        <Row
          testID="row-kyc"
          icon="id-card-outline"
          label="Update details (Aadhaar, PAN, DL)"
          onPress={() => router.push("/kyc")}
        />
        {/* Iter 64 — Admins (super / company / sub) can set or change the
            web-portal password from here. Employees only use PIN — so we
            hide the row for them. */}
        {(user?.role === "super_admin" ||
          user?.role === "company_admin" ||
          user?.role === "sub_admin") && (
          <Row
            testID="row-set-password"
            icon="key-outline"
            label={
              (user as any)?.password_set_at
                ? "Change web password"
                : "Set web password (for portal login)"
            }
            onPress={() => router.push("/admin-set-password")}
          />
        )}

        {user?.role === "employee" && (
          <>
            <Text style={styles.section}>Attendance</Text>
            <Row
              testID="row-biometric-prefs"
              icon="finger-print-outline"
              label="Biometric preferences"
              onPress={() => router.push("/biometric-prefs")}
            />
            <View style={styles.row} testID="row-auto-punch">
              <View style={styles.rowIcon}>
                <Ionicons
                  name="navigate-circle-outline"
                  size={18}
                  color={colors.onBrandTertiary}
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowLabel}>Auto punch in / out</Text>
                <Text style={styles.rowSub}>
                  {!autoPunch.supported
                    ? "Available on mobile app only"
                    : autoPunch.enabled
                      ? autoPunch.status.kind === "watching"
                        ? autoPunch.status.mode === "background"
                          ? "Active in background"
                          : "Active while app is open"
                        : "Enabled — waiting for location…"
                      : "Punch in when you reach office; out when you leave"}
                </Text>
              </View>
              <Switch
                testID="auto-punch-switch"
                value={autoPunch.enabled}
                onValueChange={async (v) => {
                  if (v) {
                    const r = await autoPunch.enable();
                    if (!r.ok && r.reason) {
                      Alert.alert("Couldn't enable", r.reason);
                    }
                  } else {
                    await autoPunch.disable();
                  }
                }}
                disabled={!autoPunch.supported || autoPunch.toggling}
                trackColor={{ true: colors.brandPrimary, false: colors.border }}
                thumbColor="#fff"
              />
            </View>

            <View style={styles.row} testID="row-daily-reminders">
              <View style={styles.rowIcon}>
                <Ionicons
                  name="alarm-outline"
                  size={18}
                  color={colors.onBrandTertiary}
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowLabel}>Daily punch reminders</Text>
                <Text style={styles.rowSub}>
                  {remindersOn
                    ? "Notifications at 9:00 AM & 6:00 PM local time"
                    : "Nudge me to punch in/out even if the app is closed"}
                </Text>
              </View>
              <Switch
                testID="reminders-switch"
                value={remindersOn}
                onValueChange={async (v) => {
                  setRemindersBusy(true);
                  try {
                    if (v) {
                      const ok = await enableReminders();
                      if (!ok) {
                        Alert.alert(
                          "Permission needed",
                          "Please allow notifications in your device settings to receive daily punch reminders.",
                        );
                        return;
                      }
                      setRemindersOn(true);
                    } else {
                      await disableReminders();
                      setRemindersOn(false);
                    }
                  } finally {
                    setRemindersBusy(false);
                  }
                }}
                disabled={remindersBusy}
                trackColor={{ true: colors.brandPrimary, false: colors.border }}
                thumbColor="#fff"
              />
            </View>
          </>
        )}

        <Text style={styles.section}>Security</Text>
        <View style={styles.row} testID="row-biometric">
          <View style={styles.rowIcon}>
            <Ionicons
              name={
                biometricLabel.toLowerCase().includes("face")
                  ? "happy-outline"
                  : "finger-print"
              }
              size={18}
              color={colors.onBrandTertiary}
            />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.rowLabel}>
              {biometricLabel} unlock
            </Text>
            <Text style={styles.rowSub}>
              {biometricSupported
                ? biometricEnabled
                  ? "Enabled — unlock the app with biometrics"
                  : "Use your fingerprint / face to unlock the app"
                : "Available on mobile app only"}
            </Text>
          </View>
          <Switch
            testID="biometric-switch"
            value={biometricEnabled}
            onValueChange={onToggleBiometric}
            disabled={!biometricSupported || bioBusy}
            trackColor={{ true: colors.brandPrimary, false: colors.border }}
            thumbColor="#fff"
          />
        </View>

        <Text style={styles.section}>About</Text>
        <View style={styles.row}>
          <Image source={LOGO_MARK} style={styles.brandRowIcon} contentFit="contain" />
          <View style={{ flex: 1 }}>
            <Text style={styles.rowLabel}>S.K. Sharma & Co.</Text>
            <Text style={styles.rowSub}>Compliance · Payroll · Manpower · v1.0</Text>
          </View>
        </View>

        <Pressable
          testID="logout-button"
          style={({ pressed }) => [
            styles.logout,
            pressed && { opacity: 0.6 },
            logoutBusy && { opacity: 0.7 },
          ]}
          onPress={doLogout}
          disabled={logoutBusy}
          hitSlop={12}
        >
          <Ionicons name="log-out-outline" size={18} color={colors.error} />
          <Text style={styles.logoutTxt}>
            {logoutBusy ? "Signing out…" : "Sign out"}
          </Text>
        </Pressable>
        <View style={{ height: 20 }} />
      </ScrollView>
    </View>
  );
}

/** Iter 165 — Fingerprint verification status + setup for employees. */
function FingerprintCard({
  userId, userName, required,
}: { userId: string; userName: string; required: boolean }) {
  const [supported, setSupported] = useState<boolean | null>(null);
  const [enrolled, setEnrolled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    (async () => {
      setSupported(await fingerprintSupported());
      setEnrolled(fingerprintEnrolled(userId));
    })();
  }, [userId]);

  const setup = async () => {
    setBusy(true); setMsg("");
    try {
      const r = await enrollFingerprint(userId, userName);
      if (r.ok) {
        setEnrolled(true);
        setMsg("Fingerprint set up on this device ✓");
        api("/me/fingerprint/enrolled", {
          method: "POST", body: { device: "web-pwa" },
        }).catch(() => {});
      } else {
        setMsg(r.message || "Setup failed");
      }
    } finally { setBusy(false); }
  };

  const test = async () => {
    setBusy(true); setMsg("");
    try {
      const r = await verifyFingerprint(userId, "Test your fingerprint");
      setMsg(r.ok ? "Fingerprint verified ✓" : (r.message === "NOT_ENROLLED" ? "Not set up yet — tap Set up first." : r.message || "Verification failed"));
    } finally { setBusy(false); }
  };

  return (
    <View style={fpStyles.card} testID="fingerprint-card">
      <View style={fpStyles.head}>
        <Ionicons name="finger-print" size={16} color={colors.brandPrimary} />
        <Text style={fpStyles.title}>Fingerprint verification</Text>
        <View style={[fpStyles.badge, required ? fpStyles.badgeOn : fpStyles.badgeOff]}>
          <Text style={[fpStyles.badgeTxt, { color: required ? "#065F46" : "#6B7280" }]}>
            {required ? "REQUIRED BY EMPLOYER" : "NOT REQUIRED"}
          </Text>
        </View>
      </View>
      {supported === false ? (
        <Text style={fpStyles.hint}>
          This device/browser has no fingerprint support — you&apos;ll continue
          with the normal flow automatically.
        </Text>
      ) : (
        <>
          <Text style={fpStyles.hint}>
            {required
              ? "Your employer requires fingerprint at app open and punch."
              : "Your firm supports fingerprint verification."}{" "}
            {enrolled ? "This device is set up." : "This device is not set up yet."}
          </Text>
          <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
            <Pressable onPress={setup} disabled={busy}
              style={[fpStyles.btn, busy && { opacity: 0.6 }]} testID="fp-setup-btn">
              <Ionicons name="finger-print" size={14} color="#fff" />
              <Text style={fpStyles.btnTxt}>{enrolled ? "Re-enroll" : "Set up fingerprint"}</Text>
            </Pressable>
            {enrolled ? (
              <Pressable onPress={test} disabled={busy}
                style={[fpStyles.btn, { backgroundColor: "#64748B" }, busy && { opacity: 0.6 }]}
                testID="fp-test-btn">
                <Text style={fpStyles.btnTxt}>Test</Text>
              </Pressable>
            ) : null}
          </View>
        </>
      )}
      {msg ? <Text style={fpStyles.msg}>{msg}</Text> : null}
    </View>
  );
}

const fpStyles = StyleSheet.create({
  card: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1,
    borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.lg, marginBottom: 12,
  },
  head: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  title: { fontSize: 13.5, fontWeight: "700", color: colors.onSurface, flex: 1 },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  badgeOn: { backgroundColor: "#D1FAE5" },
  badgeOff: { backgroundColor: "#F3F4F6" },
  badgeTxt: { fontSize: 9.5, fontWeight: "800" },
  hint: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 6 },
  msg: { fontSize: 12, fontWeight: "600", color: colors.brandPrimary, marginTop: 8 },
  btn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, paddingHorizontal: 14,
    paddingVertical: 9, borderRadius: radius.sm,
  },
  btnTxt: { color: "#fff", fontSize: 12, fontWeight: "700" },
});

function roleLabel(role?: string) {
  if (role === "super_admin") return "SUPER ADMIN";
  if (role === "company_admin") return "COMPANY ADMIN";
  return "EMPLOYEE";
}

function fmtDDMMYYYY(iso?: string | null): string {
  if (!iso) return "—";
  // Accept either YYYY-MM-DD or full ISO
  const s = String(iso).slice(0, 10);
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return String(iso);
  return `${m[3]}-${m[2]}-${m[1]}`;
}

function DetailLine({
  label,
  value,
  multiline,
}: {
  label: string;
  value?: string | null;
  multiline?: boolean;
}) {
  return (
    <View style={multiline ? styles.detailBlock : styles.detailInline}>
      <Text style={styles.detailKey}>{label}</Text>
      <Text
        style={multiline ? styles.detailValBlock : styles.detailValInline}
        numberOfLines={multiline ? undefined : 1}
      >
        {value || "—"}
      </Text>
    </View>
  );
}

function Row({
  icon,
  label,
  onPress,
  testID,
  badgeCount,
}: {
  icon: any;
  label: string;
  onPress: () => void;
  testID?: string;
  badgeCount?: number;
}) {
  return (
    <Pressable testID={testID} style={styles.row} onPress={onPress}>
      <View style={styles.rowIcon}>
        <Ionicons name={icon} size={18} color={colors.onBrandTertiary} />
      </View>
      <Text style={styles.rowLabel}>{label}</Text>
      {badgeCount && badgeCount > 0 ? (
        <View style={styles.badge} testID={`${testID}-badge`}>
          <Text style={styles.badgeTxt}>
            {badgeCount > 99 ? "99+" : badgeCount}
          </Text>
        </View>
      ) : null}
      <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.sm },
  h1: { fontSize: 26, color: colors.onSurface, fontWeight: "500" },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: 40 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    padding: spacing.xl, alignItems: "center",
    borderWidth: 1, borderColor: colors.border, marginTop: spacing.md,
  },
  avatar: { width: 80, height: 80, borderRadius: 40 },
  avatarFallback: { backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  avatarInit: { fontSize: 32, color: colors.onBrandTertiary, fontWeight: "500" },
  cameraBadge: {
    position: "absolute",
    right: -2, bottom: -2,
    backgroundColor: colors.brandPrimary,
    borderRadius: 12,
    width: 24, height: 24,
    alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: colors.surface,
  },
  name: { color: colors.onSurface, fontSize: type.xl, fontWeight: "500", marginTop: spacing.md },
  employeeCode: {
    color: colors.brandPrimary,
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 0.6,
    marginTop: 4,
  },
  email: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 2 },
  roleChip: {
    marginTop: spacing.md, backgroundColor: colors.brandTertiary,
    paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill,
  },
  roleTxt: { color: colors.onBrandTertiary, fontSize: 11, fontWeight: "500", letterSpacing: 1 },
  section: { fontSize: type.sm, color: colors.onSurfaceTertiary, marginTop: spacing.xl, marginBottom: spacing.md, textTransform: "uppercase", letterSpacing: 1 },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.md, minHeight: 60,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm,
  },
  rowIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center",
  },
  brandRowIcon: { width: 40, height: 40 },
  rowLabel: { flex: 1, color: colors.onSurface, fontSize: type.base, fontWeight: "500" },
  rowSub: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 2 },
  badge: {
    minWidth: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: colors.error,
    paddingHorizontal: 6,
    alignItems: "center",
    justifyContent: "center",
    marginRight: 4,
  },
  badgeTxt: { color: "#fff", fontSize: 11, fontWeight: "800" },
  logout: {
    marginTop: spacing.xl,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    borderWidth: 1, borderColor: colors.error, borderRadius: radius.pill,
    paddingVertical: 14,
  },
  logoutTxt: { color: colors.error, fontSize: type.base, fontWeight: "500" },

  detailsCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
    gap: 8,
  },
  detailsHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 4,
  },
  detailsTitle: {
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "800",
  },
  detailInline: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 8,
    paddingVertical: 4,
  },
  detailBlock: {
    paddingVertical: 4,
    gap: 2,
  },
  detailKey: {
    color: colors.onSurfaceSecondary,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.3,
    textTransform: "uppercase",
  },
  detailValInline: {
    color: colors.onSurface,
    fontSize: type.sm,
    fontWeight: "600",
    flexShrink: 1,
    textAlign: "right",
    maxWidth: "60%",
  },
  detailValBlock: {
    color: colors.onSurface,
    fontSize: type.sm,
    lineHeight: 20,
    marginTop: 2,
  },
  familyBlock: {
    marginTop: 8,
    paddingTop: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.divider,
    gap: 6,
  },
  familyTitle: {
    color: colors.onSurfaceSecondary,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.4,
    textTransform: "uppercase",
    marginBottom: 4,
  },
  familyRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 6,
  },
  familyAvatar: {
    width: 30,
    height: 30,
    borderRadius: 8,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  familyName: {
    color: colors.onSurface,
    fontSize: type.sm,
    fontWeight: "700",
  },
  familyRel: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    fontWeight: "500",
  },
  familyMeta: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    marginTop: 2,
  },
  familyEmpty: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    fontStyle: "italic",
  },
  editBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderStyle: "dashed",
    marginTop: 8,
  },
  editBtnTxt: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "700",
  },
});
