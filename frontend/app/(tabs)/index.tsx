import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  RefreshControl,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useFocusEffect } from "@react-navigation/native";
import * as Location from "expo-location";

import { useAuth } from "@/src/context/AuthContext";
import { api } from "@/src/api/client";
import { useLiveSync } from "@/src/api/live-sync";
import CompanyPicker from "@/src/components/CompanyPicker";
import SelectedCompanyBadge from "@/src/components/SelectedCompanyBadge";
import PrimaryInboxBanner from "@/src/components/PrimaryInboxBanner";
import { colors, radius, shadow, spacing, type } from "@/src/theme";

const LOGO = require("../../assets/images/logo-mark.png");

export default function Dashboard() {
  const { user, refresh } = useAuth();
  const router = useRouter();

  const [refreshing, setRefreshing] = useState(false);
  const [today, setToday] = useState<any>(null);
  const [leaves, setLeaves] = useState<any[]>([]);
  const [notifs, setNotifs] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [company, setCompany] = useState<any>(null);
  const [companies, setCompanies] = useState<any[]>([]);
  const [companyFilter, setCompanyFilter] = useState<string | "all">("all");
  const [pendingEmpCount, setPendingEmpCount] = useState<number>(0);
  const [pendingReqCount, setPendingReqCount] = useState<number>(0);
  const [unreadMessages, setUnreadMessages] = useState<number>(0);
  const [attSummary, setAttSummary] = useState<{
    days: {
      date: string;
      hours: number;
      first_in?: string | null;
      last_out?: string | null;
      still_in?: boolean;
      punches: number;
    }[];
    window_total_hours: number;
    total_hours_till_today: number;
  } | null>(null);
  // Iter 104 — hospital firms only: employees may request a shift change
  // before punching in. Drives the "Shift change request" quick action.
  const [shiftChangeAllowed, setShiftChangeAllowed] = useState(false);

  const load = useCallback(async () => {
    try {
      const isSuper = user?.role === "super_admin";
      const [t, l, n, s] = await Promise.all([
        api<{ records: any[] }>("/attendance/today"),
        api<{ leaves: any[] }>("/leaves?scope=mine"),
        api<{ notifications: any[] }>("/notifications"),
        // Super admins don't punch attendance — skip the summary fetch entirely
        // so we don't render the DutyHoursSection for them.
        isSuper
          ? Promise.resolve(null)
          : api<any>("/attendance/summary?days=7").catch(() => null),
      ]);
      setToday(t);
      setLeaves(l.leaves || []);
      setNotifs(n.notifications || []);
      setAttSummary(s);
      if (user?.company_id) {
        try {
          const c = await api("/company");
          setCompany(c);
        } catch {}
      }
      if (user?.role === "employee") {
        try {
          const o = await api<{ allowed: boolean }>("/shift-change/options");
          setShiftChangeAllowed(!!o.allowed);
        } catch {}
      }
      if (user && user.role !== "employee") {
        try {
          const scopeParam =
            user.role === "super_admin" && companyFilter !== "all"
              ? `?company_id=${companyFilter}`
              : "";
          const s = await api(`/admin/stats${scopeParam}`);
          setStats(s);
        } catch {}
      }
      if (user?.role === "super_admin" && companies.length === 0) {
        try {
          const r = await api<{ companies: any[] }>("/companies");
          setCompanies(r.companies || []);
        } catch {}
      }
      // Pending approval counts (super/company admins)
      if (user && user.role !== "employee") {
        try {
          const emp = await api<{ pending: any[] }>(
            "/admin/pending-approvals",
          ).catch(() => ({ pending: [] as any[] }));
          setPendingEmpCount((emp.pending || []).length);
        } catch {}
        if (user.role === "super_admin") {
          try {
            const req = await api<{ requests: any[] }>(
              "/company-requests",
            ).catch(() => ({ requests: [] as any[] }));
            setPendingReqCount(
              (req.requests || []).filter(
                (r: any) => (r.status || "pending") === "pending",
              ).length,
            );
          } catch {}
        }
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
    // Unread messages badge — for everyone
    try {
      const u = await api<{ unread: number }>("/messages/unread-count");
      setUnreadMessages(u.unread || 0);
    } catch {}
  }, [user, companyFilter, companies.length]);

  // Iter 77 - Also refresh the logged-in user record whenever the Dashboard
  // gains focus OR the operator pulls-to-refresh. This makes admin-side
  // master-data edits (salary, department, group, name, phone, DOJ, ...)
  // reflect on the phone as soon as the employee re-opens the app.
  useFocusEffect(useCallback(() => {
    void refresh();
    load();
  }, [load, refresh]));
  useEffect(() => { load(); }, [load]);

  // Iter 77n — Live sync on employee home. Refetches today's records
  // + counters when a punch (their own or admin-corrected) or a leave
  // decision lands.
  useLiveSync(user?.company_id || null, (ev) => {
    if (!ev?.type) return;
    if (
      ev.type.startsWith("punch.") ||
      ev.type.startsWith("leave.") ||
      ev.type === "attendance.dat-imported"
    ) {
      void refresh();
      load();
    }
  });

  // Silently ping the employee's current location once when they land on the
  // dashboard. Used by the employer's "present but not punched" report so an
  // employee inside the office geofence shows up without having to visit the
  // Punch tab. Best-effort — never blocks the UI, never re-prompts.
  useEffect(() => {
    if (user?.role !== "employee") return;
    let cancelled = false;
    (async () => {
      try {
        const perm = await Location.getForegroundPermissionsAsync();
        if (perm.status !== "granted") return; // don't auto-prompt
        const l = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        if (cancelled) return;
        await api("/me/location-ping", {
          method: "POST",
          body: {
            latitude: l.coords.latitude,
            longitude: l.coords.longitude,
          },
        }).catch(() => {});
      } catch {}
    })();
    return () => {
      cancelled = true;
    };
  }, [user?.user_id, user?.role]);

  const lastRec = today?.records?.[today.records.length - 1];
  const punchedIn = lastRec?.kind === "in";
  const punchedOut = lastRec?.kind === "out";
  const shiftStatus =
    punchedIn && !punchedOut ? "Clocked in" :
    punchedOut ? "Shift complete" :
    "Not started";
  const shiftStatusEmoji =
    punchedIn && !punchedOut ? "●" : punchedOut ? "✓" : "○";

  const activityCount = today?.records?.length || 0;
  const pendingLeaves = leaves.filter((l) => l.status === "pending").length;
  const unreadNotifs = notifs.length;

  const roleBadge = user?.role === "super_admin" ? "Super Admin" :
    user?.role === "sub_admin" ? "Sub Super Admin" :
    user?.role === "company_admin" ? "Company Admin" : "Employee";

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.topBar}>
          <View style={styles.topLeft}>
            <Image source={LOGO} style={styles.brandLogo} contentFit="contain" />
            <View>
              <Text style={styles.greetSmall}>Hello,</Text>
              <Text style={styles.greetName}>{user?.name?.split(" ")[0] || "there"}</Text>
              {user?.role === "employee" && user?.employee_code ? (
                <Text style={styles.greetCode} testID="employee-code-display">
                  ID: {user.employee_code}
                </Text>
              ) : null}
            </View>
          </View>
          <Pressable
            testID="notif-bell"
            onPress={() => router.push("/notifications")}
            style={styles.bell}
          >
            <Ionicons name="notifications-outline" size={22} color={colors.onSurface} />
            {unreadNotifs > 0 && <View style={styles.bellDot} />}
          </Pressable>
        </View>

        <View style={styles.roleRow}>
          <View style={styles.rolePill}>
            <Text style={styles.rolePillTxt}>{roleBadge}</Text>
          </View>
          {company && (
            <Text style={styles.companyLabel} numberOfLines={1}>
              · {company.name}
            </Text>
          )}
        </View>
      </SafeAreaView>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              // Iter 77 - Pull-to-refresh now also re-hydrates the
              // user record so admin edits (salary / dept / group)
              // become visible without needing to re-login.
              void refresh();
              load();
            }}
            tintColor={colors.brandPrimary}
          />
        }
        showsVerticalScrollIndicator={false}
      >
        {/* Iter 62 — "Currently viewing" badge (web only) */}
        <SelectedCompanyBadge variant="banner" />

        {/* Super Admin / Sub Admin — centered name + logo (user request) */}
        {(user?.role === "super_admin" || user?.role === "sub_admin") && (
          <View style={styles.brandCenter} testID="admin-brand-center">
            <Image source={LOGO} style={styles.brandCenterLogo} contentFit="contain" />
            <Text style={styles.brandCenterName}>{user?.name}</Text>
            <Text style={styles.brandCenterSub}>{roleBadge}</Text>
          </View>
        )}

        {/* Iter 127 — "New email in Primary Inbox" ping (Super/Sub Admin) */}
        <PrimaryInboxBanner />

        {loading ? (
          <ActivityIndicator style={{ marginTop: 80 }} color={colors.brandPrimary} />
        ) : (
          <>
            {/* Hero shift card — hidden for super_admin (they don't punch) */}
            {user?.role !== "super_admin" && (
              <View style={styles.hero} testID="hero-shift">
                <View style={styles.heroTopRow}>
                  <View>
                    <Text style={styles.heroLabel}>TODAY&apos;S SHIFT</Text>
                    <Text style={styles.heroStatus}>
                      {shiftStatusEmoji}  {shiftStatus}
                    </Text>
                  </View>
                  <View style={styles.heroClock}>
                    <Text style={styles.heroClockTxt}>
                      {new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </Text>
                  </View>
                </View>

                <View style={styles.heroDivider} />

                <View style={styles.heroBottomRow}>
                  <View>
                    <Text style={styles.heroMeta}>{activityCount} activity today</Text>
                    {user?.shift_start && user?.shift_end ? (
                      <Text style={styles.heroMetaSub}>
                        Shift {user.shift_start} – {user.shift_end}
                      </Text>
                    ) : null}
                  </View>
                  {/* Iter 114 — punching hidden when the firm's Bio Matrix
                      Attendance is OFF (view-only mode per process flow). */}
                  {company?.attendance_punching_enabled === false ? (
                    <View style={[styles.heroCta, { backgroundColor: "transparent" }]}>
                      <Ionicons name="eye-outline" size={16} color={colors.onSurfaceTertiary} />
                      <Text style={[styles.heroCtaTxt, { color: colors.onSurfaceTertiary }]}>View only</Text>
                    </View>
                  ) : (
                  <Pressable
                    testID="hero-punch-cta"
                    style={styles.heroCta}
                    onPress={() => router.push("/(tabs)/attendance")}
                  >
                    <Ionicons name="finger-print" size={16} color={colors.onCta} />
                    <Text style={styles.heroCtaTxt}>
                      {punchedIn && !punchedOut ? "Punch Out" : "Punch In"}
                    </Text>
                  </Pressable>
                  )}
                </View>
              </View>
            )}

            {/* Duty hours summary — not shown to super_admin (they don't punch) */}
            {user?.role !== "super_admin" && attSummary && (
              <DutyHoursSection
                summary={attSummary}
                onPressHistory={() => router.push("/history")}
              />
            )}

            {/* Bento grid 2x2 */}
            <View style={styles.bento}>
              <BentoTile
                testID="bento-leaves"
                icon="calendar-outline"
                value={pendingLeaves}
                label="Pending leaves"
                variant="light"
                onPress={() => router.push("/leaves")}
              />
              {user?.role !== "super_admin" && (
                <BentoTile
                  testID="bento-history"
                  icon="time-outline"
                  value={activityCount}
                  label="Today activity"
                  variant="light"
                  onPress={() => router.push("/history")}
                />
              )}
              <BentoTile
                testID="bento-tickets"
                icon="chatbubbles-outline"
                value={unreadNotifs}
                label="Notifications"
                variant="light"
                onPress={() => router.push("/notifications")}
              />
              <BentoTile
                testID="bento-support"
                icon="ticket-outline"
                value="Raise"
                label="Support ticket"
                variant="accent"
                onPress={() => router.push("/tickets")}
              />
            </View>

            {user?.role !== "employee" && stats && (
              <>
                <SectionHeader
                  title="Admin overview"
                  action={{
                    label: "Manage →",
                    onPress: () => router.push("/admin"),
                  }}
                />
                {/* Iter 96b — biometric last-sync health badge */}
                <SystemHealthBadge
                  companyId={user?.role === "super_admin" ? companyFilter : undefined}
                  onPress={() => router.push("/zk-dat-import")}
                />
                {user?.role === "super_admin" && (
                  <View style={{ marginBottom: spacing.md }}>
                    <CompanyPicker
                      testID="dashboard-company-picker"
                      value={companyFilter}
                      onChange={setCompanyFilter}
                      companies={companies}
                      label=""
                      compact={false}
                    />
                  </View>
                )}

                {(pendingEmpCount > 0 || pendingReqCount > 0) && (
                  <View style={styles.approvalsBanner} testID="approvals-banner">
                    <View style={styles.approvalsIcon}>
                      <Ionicons
                        name="alert-circle"
                        size={22}
                        color={colors.warning}
                      />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.approvalsTitle}>
                        {pendingEmpCount + pendingReqCount} pending approval
                        {pendingEmpCount + pendingReqCount > 1 ? "s" : ""}
                      </Text>
                      <Text style={styles.approvalsSub}>
                        {pendingEmpCount > 0 &&
                          `${pendingEmpCount} employee${pendingEmpCount > 1 ? "s" : ""}`}
                        {pendingEmpCount > 0 && pendingReqCount > 0 && " · "}
                        {pendingReqCount > 0 &&
                          `${pendingReqCount} new client request${pendingReqCount > 1 ? "s" : ""}`}
                      </Text>
                    </View>
                    <Pressable
                      testID="approvals-review-btn"
                      style={styles.approvalsCta}
                      onPress={() =>
                        pendingReqCount > 0
                          ? router.push("/company-requests")
                          : router.push("/admin")
                      }
                    >
                      <Text style={styles.approvalsCtaTxt}>Review</Text>
                      <Ionicons
                        name="chevron-forward"
                        size={14}
                        color={colors.brandPrimary}
                      />
                    </Pressable>
                  </View>
                )}

                <View style={styles.bento}>
                  {user?.role === "super_admin" && (
                    <BentoTile
                      icon="business-outline"
                      value={stats.total_companies ?? 0}
                      label="Client companies"
                      variant="dark"
                      onPress={() => router.push("/companies")}
                    />
                  )}
                  {/* Super_admin sees Employees / Present today ONLY when
                      a specific company is picked. When "All companies"
                      is selected we show a dash so the tile reads as an
                      intentional empty state rather than a real "0". */}
                  <BentoTile
                    testID="bento-employees"
                    icon="people-outline"
                    value={
                      user?.role === "super_admin" && companyFilter === "all"
                        ? "—"
                        : stats.total_employees
                    }
                    label="Employees"
                    variant="dark"
                    onPress={
                      user?.role === "super_admin" && companyFilter === "all"
                        ? undefined
                        : () => router.push("/admin")
                    }
                    dim={user?.role === "super_admin" && companyFilter === "all"}
                  />
                  <BentoTile
                    testID="bento-present-today"
                    icon="checkmark-done-outline"
                    value={
                      user?.role === "super_admin" && companyFilter === "all"
                        ? "—"
                        : stats.present_today
                    }
                    label="Present today"
                    variant="dark"
                    onPress={
                      user?.role === "super_admin" && companyFilter === "all"
                        ? undefined
                        : () =>
                            router.push({
                              pathname: "/present-today",
                              params:
                                user?.role === "super_admin" &&
                                companyFilter !== "all"
                                  ? { company_id: companyFilter }
                                  : {},
                            })
                    }
                    dim={user?.role === "super_admin" && companyFilter === "all"}
                  />
                  {user?.role !== "super_admin" && (
                    <BentoTile
                      testID="bento-leave-approvals"
                      icon="hourglass-outline"
                      value={stats.pending_leaves}
                      label="Leave approvals"
                      variant="dark"
                      onPress={() =>
                        router.push({
                          pathname: "/leaves",
                          params: { scope: "all" },
                        })
                      }
                    />
                  )}
                  {user?.role === "super_admin" && (
                    <BentoTile
                      testID="bento-leave-approvals-super"
                      icon="hourglass-outline"
                      value={
                        companyFilter === "all"
                          ? stats.pending_leaves
                          : stats.pending_leaves
                      }
                      label={
                        companyFilter === "all"
                          ? "Leave approvals (all)"
                          : "Leave approvals"
                      }
                      variant="dark"
                      onPress={() =>
                        router.push({
                          pathname: "/leaves",
                          params: { scope: "all" },
                        })
                      }
                    />
                  )}
                  <BentoTile
                    testID="bento-profile-edit-approvals"
                    icon="clipboard-outline"
                    value={stats.pending_profile_edits ?? 0}
                    label={
                      user?.role === "super_admin" && companyFilter === "all"
                        ? "Profile edits (all)"
                        : "Profile edits"
                    }
                    variant="accent"
                    onPress={() => router.push("/profile-edit-reviews")}
                  />
                </View>
                {user?.role === "super_admin" && companyFilter === "all" && (
                  <View style={styles.pickerHint} testID="pick-company-hint">
                    <Ionicons name="filter-outline" size={14} color={colors.brandPrimary} />
                    <Text style={styles.pickerHintTxt}>
                      Pick a company above to view employees and today&apos;s attendance.
                    </Text>
                  </View>
                )}
              </>
            )}

            <SectionHeader title="Quick actions" />
            <View style={styles.actions}>
              <ActionRow
                icon="document-text-outline"
                label="Payslips & documents"
                onPress={() => router.push("/(tabs)/documents")}
              />
              {user?.role === "employee" ? (
                <ActionRow
                  icon="calendar-outline"
                  label="Request a leave"
                  onPress={() => router.push("/leaves")}
                />
              ) : (                <ActionRow
                  testID="row-leave-approvals"
                  icon="calendar-outline"
                  label={
                    stats.pending_leaves > 0
                      ? `Leave approvals (${stats.pending_leaves})`
                      : "Leave approvals"
                  }
                  onPress={() =>
                    router.push({
                      pathname: "/leaves",
                      params: { scope: "all" },
                    })
                  }
                />
              )}
              {user?.role === "employee" && shiftChangeAllowed && (
                <ActionRow
                  testID="row-shift-change"
                  icon="swap-horizontal-outline"
                  label="Shift change request"
                  onPress={() => router.push("/shift-change")}
                />
              )}
              {user?.role !== "employee" && (
                <ActionRow
                  testID="row-employee-master"
                  icon="people-outline"
                  label="Employee Master Data"
                  onPress={() => router.push({ pathname: "/admin", params: { section: "employees" } } as any)}
                />
              )}
              {user?.role !== "employee" && (
                <ActionRow
                  testID="row-process-salary"
                  icon="cash-outline"
                  label="Salary process"
                  onPress={() => router.push("/salary-run")}
                />
              )}
              {user?.role !== "employee" && (
                <ActionRow
                  testID="row-compliance-salary"
                  icon="briefcase-outline"
                  label="Compliance salary process"
                  onPress={() => router.push("/compliance-salary-run")}
                />
              )}
              <ActionRow
                testID="row-messages"
                icon="mail-outline"
                label={
                  user?.role !== "employee"
                    ? "Messages · Send announcement"
                    : "Messages"
                }
                badgeCount={unreadMessages}
                onPress={() => router.push("/messages")}
              />
              <ActionRow
                icon="ticket-outline"
                label="Raise a ticket"
                onPress={() => router.push("/tickets")}
              />
              {user?.role !== "super_admin" && (
                <ActionRow
                  icon="time-outline"
                  label="Attendance history"
                  onPress={() => router.push("/history")}
                />
              )}
              {user?.role !== "employee" && (
                <ActionRow
                  testID="row-attendance-approvals"
                  icon="location-outline"
                  label="In-office but not punched"
                  badgeCount={stats?.missed_ins || 0}
                  onPress={() => router.push("/attendance-approvals")}
                />
              )}
              {user?.role !== "employee" && (
                <ActionRow
                  testID="row-open-shifts"
                  icon="time-outline"
                  label="Open shifts (missed OUT)"
                  badgeCount={stats?.open_shifts || 0}
                  onPress={() => router.push("/attendance-review")}
                />
              )}
              {user?.role !== "employee" && (
                <ActionRow
                  testID="row-branches"
                  icon="git-branch-outline"
                  label="Branches"
                  onPress={() => router.push("/branches")}
                />
              )}
              {user?.role === "employee" && (
                <ActionRow
                  icon="cash-outline"
                  label="My payslip"
                  onPress={() => router.push("/payslip")}
                />
              )}
            </View>

            {notifs.length > 0 && (
              <>
                <SectionHeader title="Latest announcements" />
                {notifs.slice(0, 3).map((n) => (
                  <View key={n.notification_id} style={styles.notifCard}>
                    <View style={styles.notifIcon}>
                      <Ionicons name="megaphone-outline" size={16} color={colors.accent} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.notifTitle}>{n.title}</Text>
                      <Text style={styles.notifBody} numberOfLines={2}>{n.body}</Text>
                    </View>
                  </View>
                ))}
              </>
            )}

            <View style={{ height: 32 }} />
          </>
        )}
      </ScrollView>
    </View>
  );
}

type DaySummary = {
  date: string;
  hours: number;
  first_in?: string | null;
  last_out?: string | null;
  still_in?: boolean;
  punches: number;
};

function DutyHoursSection({
  summary,
  onPressHistory,
}: {
  summary: {
    days: DaySummary[];
    window_total_hours: number;
    total_hours_till_today: number;
  };
  onPressHistory: () => void;
}) {
  const days = summary.days || [];
  const maxHours = Math.max(1, ...days.map((d) => d.hours || 0));
  const avg =
    days.length > 0 ? (summary.window_total_hours || 0) / days.length : 0;

  const fmtHM = (h: number) => {
    const hh = Math.floor(h);
    const mm = Math.round((h - hh) * 60);
    if (hh <= 0 && mm <= 0) return "0h";
    if (hh <= 0) return `${mm}m`;
    if (mm <= 0) return `${hh}h`;
    return `${hh}h ${mm}m`;
  };

  const dayLabel = (iso: string) => {
    try {
      const dt = new Date(iso + "T00:00:00");
      return dt.toLocaleDateString(undefined, { weekday: "short" });
    } catch {
      return iso.slice(5);
    }
  };

  return (
    <View style={dutyStyles.wrap} testID="duty-hours-section">
      <View style={dutyStyles.summaryRow}>
        <View style={dutyStyles.summaryCard} testID="duty-total-till-today">
          <Text style={dutyStyles.summaryLabel}>TOTAL DUTY HOURS</Text>
          <Text style={dutyStyles.summaryValue}>
            {fmtHM(summary.total_hours_till_today || 0)}
          </Text>
          <Text style={dutyStyles.summarySub}>till today</Text>
        </View>
        <View style={dutyStyles.summaryCard} testID="duty-week-total">
          <Text style={dutyStyles.summaryLabel}>LAST 7 DAYS</Text>
          <Text style={dutyStyles.summaryValue}>
            {fmtHM(summary.window_total_hours || 0)}
          </Text>
          <Text style={dutyStyles.summarySub}>
            avg {fmtHM(avg)} / day
          </Text>
        </View>
      </View>

      <View style={dutyStyles.chartHeader}>
        <Text style={dutyStyles.chartTitle}>Daily duty hours</Text>
        <Pressable onPress={onPressHistory} hitSlop={8}>
          <Text style={dutyStyles.chartLink}>See history →</Text>
        </Pressable>
      </View>

      <View style={dutyStyles.chartRow}>
        {days.map((d) => {
          const ratio = Math.min(1, (d.hours || 0) / maxHours);
          const barHeight = Math.max(6, ratio * 80);
          return (
            <View
              key={d.date}
              style={dutyStyles.dayCol}
              testID={`duty-day-${d.date}`}
            >
              <Text style={dutyStyles.dayValue}>
                {(d.hours || 0).toFixed(1)}
              </Text>
              <View style={dutyStyles.barTrack}>
                <View
                  style={[
                    dutyStyles.bar,
                    {
                      height: barHeight,
                      backgroundColor: d.still_in
                        ? colors.warning
                        : d.hours > 0
                          ? colors.brandPrimary
                          : colors.border,
                    },
                  ]}
                />
              </View>
              <Text style={dutyStyles.dayLabel}>{dayLabel(d.date)}</Text>
            </View>
          );
        })}
      </View>
    </View>
  );
}

const dutyStyles = StyleSheet.create({
  wrap: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginTop: spacing.md,
    marginBottom: spacing.md,
    ...shadow.card,
  },
  summaryRow: {
    flexDirection: "row",
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  summaryCard: {
    flex: 1,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    paddingVertical: 12,
    paddingHorizontal: 12,
  },
  summaryLabel: {
    color: colors.brandPrimary,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.6,
  },
  summaryValue: {
    color: colors.onSurface,
    fontSize: 22,
    fontWeight: "800",
    marginTop: 4,
  },
  summarySub: {
    color: colors.onSurfaceSecondary,
    fontSize: 11,
    marginTop: 2,
  },
  chartHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  chartTitle: {
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "800",
  },
  chartLink: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "700",
  },
  chartRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
    height: 130,
  },
  dayCol: {
    flex: 1,
    alignItems: "center",
    justifyContent: "flex-end",
  },
  dayValue: {
    color: colors.onSurfaceSecondary,
    fontSize: 10,
    fontWeight: "700",
    marginBottom: 4,
  },
  barTrack: {
    width: "70%",
    height: 90,
    justifyContent: "flex-end",
    alignItems: "center",
    borderRadius: 4,
    backgroundColor: "transparent",
  },
  bar: {
    width: "100%",
    borderRadius: 4,
  },
  dayLabel: {
    color: colors.onSurfaceTertiary,
    fontSize: 10,
    fontWeight: "600",
    marginTop: 6,
  },
});


// Iter 96b — System Health badge: biometric device / .dat import last sync.
function SystemHealthBadge({
  companyId,
  onPress,
}: {
  companyId?: string | "all";
  onPress: () => void;
}) {
  const [health, setHealth] = useState<{
    status: string;
    hours_ago: number | null;
    last_sync_kind: string | null;
    devices_registered: number;
  } | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const q = companyId && companyId !== "all" ? `?company_id=${companyId}` : "";
        const r = await api<any>(`/admin/system-health/biometric${q}`);
        if (alive) setHealth(r);
      } catch {
        if (alive) setHealth(null);
      }
    })();
    return () => { alive = false; };
  }, [companyId]);

  if (!health) return null;
  const color =
    health.status === "ok" ? "#15803D" :
    health.status === "warn" ? "#B45309" : "#B91C1C";
  const bg =
    health.status === "ok" ? "rgba(21,128,61,0.08)" :
    health.status === "warn" ? "rgba(180,83,9,0.10)" : "rgba(185,28,28,0.08)";
  const ago =
    health.hours_ago == null
      ? "never"
      : health.hours_ago < 1
        ? `${Math.max(1, Math.round(health.hours_ago * 60))} min ago`
        : health.hours_ago < 48
          ? `${health.hours_ago.toFixed(health.hours_ago < 10 ? 1 : 0)}h ago`
          : `${Math.round(health.hours_ago / 24)} days ago`;
  const kind =
    health.last_sync_kind === "dat_import" ? ".dat import" :
    health.last_sync_kind === "device" ? "device heartbeat" :
    health.last_sync_kind === "punch" ? "biometric punch" : "";

  return (
    <Pressable
      onPress={onPress}
      style={{
        flexDirection: "row", alignItems: "center", gap: 8,
        backgroundColor: bg, borderWidth: 1, borderColor: color + "44",
        borderRadius: 10, paddingHorizontal: 12, paddingVertical: 9,
        marginBottom: spacing.md,
      }}
      testID="system-health-badge"
    >
      <View style={{ width: 9, height: 9, borderRadius: 5, backgroundColor: color }} />
      <Ionicons name="finger-print-outline" size={15} color={color} />
      <Text style={{ fontSize: 12, fontWeight: "700", color, flex: 1 }} numberOfLines={1}>
        Biometric sync: {ago}
        {kind ? ` · ${kind}` : ""}
        {health.status === "stale" || health.status === "never" ? " — import overdue!" : ""}
      </Text>
      <Ionicons name="chevron-forward" size={14} color={color} />
    </Pressable>
  );
}

function BentoTile({
  icon, value, label, onPress, testID, variant = "light", dim = false,
}: {
  icon: any; value: string | number; label: string;
  onPress?: () => void; testID?: string;
  variant?: "light" | "dark" | "accent";
  dim?: boolean;
}) {
  const isDark = variant === "dark";
  const isAccent = variant === "accent";
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={!onPress}
      style={[
        styles.bentoTile,
        isDark && { backgroundColor: colors.brandPrimary },
        isAccent && { backgroundColor: colors.cta },
        dim && { opacity: 0.55 },
      ]}
    >
      <View style={[
        styles.bentoIcon,
        isDark && { backgroundColor: "rgba(255,255,255,0.14)" },
        isAccent && { backgroundColor: "rgba(255,255,255,0.22)" },
      ]}>
        <Ionicons
          name={icon}
          size={18}
          color={isDark || isAccent ? "#fff" : colors.brandPrimary}
        />
      </View>
      <Text style={[
        styles.bentoValue,
        (isDark || isAccent) && { color: "#fff" },
      ]}>
        {value}
      </Text>
      <Text style={[
        styles.bentoLabel,
        (isDark || isAccent) && { color: "rgba(255,255,255,0.85)" },
      ]}>
        {label}
      </Text>
    </Pressable>
  );
}

function SectionHeader({
  title,
  action,
}: {
  title: string;
  action?: { label: string; onPress: () => void };
}) {
  return (
    <View style={styles.sectionRow}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {action && (
        <Pressable onPress={action.onPress} hitSlop={8}>
          <Text style={styles.sectionAction}>{action.label}</Text>
        </Pressable>
      )}
    </View>
  );
}

function ActionRow({
  icon, label, onPress, testID, badgeCount,
}: {
  icon: any;
  label: string;
  onPress: () => void;
  testID?: string;
  badgeCount?: number;
}) {
  return (
    <Pressable style={styles.actionRow} onPress={onPress} testID={testID}>
      <View style={styles.actionIcon}>
        <Ionicons name={icon} size={18} color={colors.brandPrimary} />
        {badgeCount && badgeCount > 0 ? (
          <View style={styles.actionIconBadge}>
            <Text style={styles.actionIconBadgeTxt}>
              {badgeCount > 99 ? "99+" : String(badgeCount)}
            </Text>
          </View>
        ) : null}
      </View>
      <Text style={styles.actionLabel}>{label}</Text>
      <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  topBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  topLeft: { flexDirection: "row", alignItems: "center", gap: 12 },
  brandLogo: { width: 42, height: 42 },
  brandCenter: { alignItems: "center", marginTop: 4, marginBottom: 14 },
  brandCenterLogo: { width: 72, height: 72, marginBottom: 6 },
  brandCenterName: { fontSize: 20, fontWeight: "900", color: colors.onSurface, textAlign: "center" },
  brandCenterSub: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary, marginTop: 2, textAlign: "center" },
  greetSmall: { color: colors.onSurfaceSecondary, fontSize: type.sm },
  greetName: {
    color: colors.onSurface, fontSize: type.xl,
    fontWeight: "700", letterSpacing: -0.5, marginTop: -2,
  },
  greetCode: {
    color: colors.brandPrimary,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.5,
    marginTop: 2,
  },
  bell: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: colors.border,
  },
  bellDot: {
    position: "absolute", top: 10, right: 12,
    width: 8, height: 8, borderRadius: 4, backgroundColor: colors.cta,
  },
  roleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: spacing.lg,
    marginTop: spacing.sm,
    marginBottom: spacing.md,
  },
  rolePill: {
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: radius.pill,
  },
  rolePillTxt: {
    color: colors.brandPrimary, fontSize: 10,
    fontWeight: "700", letterSpacing: 1,
  },
  companyLabel: { color: colors.onSurfaceSecondary, fontSize: type.sm, flex: 1 },

  scroll: { paddingHorizontal: spacing.lg, paddingBottom: spacing.lg },

  hero: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.xl,
    padding: spacing.lg,
    ...shadow.card,
  },
  heroTopRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  heroLabel: {
    color: "rgba(255,255,255,0.65)",
    fontSize: 11, letterSpacing: 1.5, fontWeight: "600",
  },
  heroStatus: {
    color: "#fff", fontSize: type.xl,
    fontWeight: "700", marginTop: 6, letterSpacing: -0.3,
  },
  heroClock: {
    backgroundColor: "rgba(255,255,255,0.12)",
    paddingHorizontal: 12, paddingVertical: 6,
    borderRadius: radius.pill,
  },
  heroClockTxt: {
    color: "#fff", fontSize: type.base, fontWeight: "600",
    fontVariant: ["tabular-nums"],
  },
  heroDivider: {
    height: 1, backgroundColor: "rgba(255,255,255,0.10)",
    marginVertical: spacing.md,
  },
  heroBottomRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  heroMeta: { color: "rgba(255,255,255,0.85)", fontSize: type.sm },
  heroMetaSub: { color: "rgba(255,255,255,0.6)", fontSize: 11, marginTop: 2 },
  heroCta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.cta,
    paddingHorizontal: 16, paddingVertical: 10,
    borderRadius: radius.pill,
    ...shadow.cta,
  },
  heroCtaTxt: { color: colors.onCta, fontWeight: "700", fontSize: type.base },

  approvalsBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: "#FFF6E5",
    borderWidth: 1,
    borderColor: "#F5C56B",
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  approvalsIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: "#FFE6BE",
    alignItems: "center",
    justifyContent: "center",
  },
  approvalsTitle: {
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "800",
  },
  approvalsSub: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 2,
  },
  approvalsCta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 6,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
  },
  approvalsCtaTxt: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "700",
  },

  bento: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
    marginTop: spacing.lg,
  },
  pickerHint: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    paddingVertical: 10,
    paddingHorizontal: 12,
    marginTop: 10,
  },
  pickerHintTxt: {
    flex: 1,
    color: colors.onBrandTertiary,
    fontSize: 12,
    fontWeight: "600",
  },
  bentoTile: {
    width: "47.5%",
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.md,
    minHeight: 118,
    borderWidth: 1,
    borderColor: colors.border,
    justifyContent: "space-between",
  },
  bentoIcon: {
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  bentoValue: {
    color: colors.onSurface,
    fontSize: 28,
    fontWeight: "700",
    letterSpacing: -0.5,
    marginTop: 4,
  },
  bentoLabel: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 2,
  },

  sectionRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.lg,
    marginBottom: 10,
  },
  sectionTitle: {
    color: colors.onSurface, fontSize: type.lg,
    fontWeight: "700", letterSpacing: -0.3,
  },
  sectionAction: { color: colors.accent, fontSize: type.sm, fontWeight: "600" },

  actions: { gap: 8 },
  actionRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border,
    minHeight: 60,
  },
  actionIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  actionIconBadge: {
    position: "absolute",
    top: -4,
    right: -6,
    minWidth: 18,
    height: 18,
    paddingHorizontal: 4,
    borderRadius: 9,
    backgroundColor: colors.error,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 2,
    borderColor: colors.surfaceSecondary,
  },
  actionIconBadgeTxt: {
    color: "#fff",
    fontSize: 10,
    fontWeight: "800",
    lineHeight: 12,
  },
  actionLabel: { flex: 1, color: colors.onSurface, fontSize: type.base, fontWeight: "500" },

  notifCard: {
    flexDirection: "row", gap: 12,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border,
    marginBottom: 8,
  },
  notifIcon: {
    width: 32, height: 32, borderRadius: 16,
    backgroundColor: colors.ctaTint,
    alignItems: "center", justifyContent: "center",
  },
  notifTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "600" },
  notifBody: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },
});
