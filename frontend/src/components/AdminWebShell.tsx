import React, { useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Platform,
  useWindowDimensions,
  ScrollView,
  Image,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { usePathname, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import GlobalCompanyPicker from "@/src/components/GlobalCompanyPicker";
import { useRefreshBus } from "@/src/context/RefreshBusContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { useUnreadNotifications } from "@/src/hooks/useUnreadNotifications";
import { usePrimaryInbox } from "@/src/hooks/usePrimaryInbox";
import { colors, radius, spacing, type } from "@/src/theme";

/**
 * Formats an ISO timestamp as a "Xs / Xm / Xh ago" chip.  Used by the
 * top-bar Refresh button to show operators when the visible pages were
 * last invalidated.  Purely presentational — no i18n as the rest of the
 * admin shell is English-only.
 */
function formatSinceRefresh(iso: string): string {
  try {
    const diffMs = Date.now() - new Date(iso).getTime();
    if (diffMs < 0) return "just now";
    const s = Math.floor(diffMs / 1000);
    if (s < 60) return `refreshed ${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `refreshed ${m}m ago`;
    const h = Math.floor(m / 60);
    return `refreshed ${h}h ago`;
  } catch {
    return "";
  }
}

/**
 * Desktop admin shell — wraps every route so that on web + wide viewports
 * (>= 960 px) admins see a persistent sidebar navigation. On mobile / narrow
 * screens the shell renders children unchanged, so the existing mobile UX is
 * preserved.
 *
 * Employees who open the app on the web are shown a friendly "please use
 * mobile app" screen instead of the tabs, because punch-in/out needs the
 * device camera + GPS.
 */
export const DESKTOP_MIN = 960;

export const NAV_SUPER: NavItem[] = [
  { route: "/(tabs)", label: "Dashboard", icon: "home-outline" },
  // Iter 89 — Add New Employee shifted to position 2 per user request.
  { route: "/employee-add", label: "Add New Employee", icon: "person-add-outline" },
  { route: "/companies", label: "Companies (Firm Master)", icon: "business-outline" },
  { route: "/admin", label: "Employee Master Data", icon: "people-outline" },
  {
    label: "Salary Process",
    icon: "cash-outline",
    children: [
      { route: "/salary-run", label: "Salary Process (Actual)", icon: "cash-outline" },
      { route: "/compliance-salary-run", label: "Salary Process (Compliance)", icon: "briefcase-outline" },
      { route: "/ot-salary-run", label: "Salary Process (OT)", icon: "flash-outline" },
      { route: "/arrear-salary-run", label: "Salary Process (Arrear)", icon: "time-outline" },
    ],
  },
  { route: "/bulk-employee-correction", label: "Bulk Employee Correction", icon: "people-outline" },
  {
    label: "Approvals",
    icon: "checkmark-done-circle-outline",
    children: [
      { route: "/company-requests", label: "Company Requests", icon: "mail-open-outline" },
      { route: "/punch-approvals", label: "Punch Approvals", icon: "checkmark-circle-outline" },
      { route: "/contractor-punches", label: "Contractor Punches", icon: "briefcase-outline" },
      { route: "/shift-approvals", label: "Shift Change Approvals", icon: "swap-horizontal-outline" },
      { route: "/attendance-approvals", label: "Attendance Approvals", icon: "hand-right-outline" },
      { route: "/deletion-approvals", label: "Deletion Approvals", icon: "trash-bin-outline" },
    ],
  },
  {
    label: "Bonus",
    icon: "gift-outline",
    children: [
      { route: "/bonus-run", label: "Bonus Process", icon: "gift-outline" },
      { route: "/bonus-registers", label: "Bonus Registers (A, B, D) & Returns", icon: "albums-outline" },
      { route: "/bonus-yearly-summary", label: "Bonus Yearly Summary", icon: "calendar-outline" },
    ],
  },
  {
    label: "Reports",
    icon: "bar-chart-outline",
    children: [
      { route: "/attendance-grid", label: "Attendance Report", icon: "grid-outline" },
      { route: "/daily-present-report", label: "Day-wise Present Count", icon: "people-outline" },
      { route: "/salary-day-sheet", label: "Day-wise Salary Sheet", icon: "calendar-outline" },
      { route: "/master-data-report", label: "Master Data", icon: "server-outline" },
      { route: "/compliance-reports", label: "Compliance Reports", icon: "shield-checkmark-outline" },
      { route: "/pf-reports?kind=pf", label: "PF Reports", icon: "briefcase-outline" },
      { route: "/pf-reports?kind=esic", label: "ESIC Reports", icon: "medkit-outline" },
      { route: "/bank-sheet", label: "Bank Sheet Format", icon: "card-outline" },
      { route: "/reports?tab=salary", label: "Actual Salary Report", icon: "cash-outline" },
      { route: "/reports?tab=compliance", label: "Compliance Report", icon: "shield-checkmark-outline" },
      { route: "/reports?tab=bonus", label: "Bonus Report", icon: "gift-outline" },
      { route: "/leave-report", label: "Leave Report", icon: "calendar-number-outline" },
      { route: "/hr-letters", label: "HR Letters", icon: "document-text-outline" },
      { route: "/employee-report", label: "Employee Report", icon: "people-outline" },
      { route: "/challan-summary", label: "Monthly Challan Summary", icon: "documents-outline" },
    ],
  },
  {
    label: "Automation",
    icon: "sparkles-outline",
    children: [
      { route: "/attendance-email", label: "Email Configure / Automation", icon: "mail-outline" },
      { route: "/email-settings", label: "Email SMTP & Notifications", icon: "mail-unread-outline" },
      { route: "/challans", label: "PF / ESIC Challans", icon: "receipt-outline" },
      { route: "/portal-automation", label: "WhatsApp Linking", icon: "logo-whatsapp" },
    ],
  },
  {
    label: "User Rights",
    icon: "shield-outline",
    children: [
      { route: "/employer-access-rights", label: "Access Rights", icon: "key-outline" },
      { route: "/sub-admins", label: "Sub Admins", icon: "people-circle-outline" },
      { route: "/super-admin-access", label: "Super Admin Rights", icon: "star-outline" },
    ],
  },
  {
    label: "Masters",
    icon: "list-outline",
    children: [
      { route: "/masters", label: "General Masters", icon: "layers-outline" },
      { route: "/compliance-settings", label: "Standard Compliance Settings", icon: "shield-checkmark-outline" },
      { route: "/attendance-master", label: "Attendance Master", icon: "calendar-outline" },
      { route: "/masters?tab=shifts", label: "Shifts", icon: "time-outline" },
    ],
  },
  { route: "/employee-bulk-import", label: "Bulk Import (Excel)", icon: "cloud-upload-outline" },
  { route: "/attendance-policy", label: "Attendance Policy", icon: "time-outline" },
  // Iter 85 — Utility group. Users Log Report is a new audit view;
  // Messages + Tickets moved under this umbrella so ops tools live in
  // one collapsible section.
  {
    key: "utility",
    label: "Utility",
    icon: "construct-outline",
    children: [
      // Merged from the old "Utilities" group (user request — one group).
      { route: "/past-salary-runs", label: "Past Salary Runs", icon: "albums-outline" },
      { route: "/zk-dat-import", label: "Import Biometric .dat", icon: "finger-print-outline" },
      { route: "/join-qr", label: "QR Codes (Join / App)", icon: "qr-code-outline" },
      { route: "/users-log-report", label: "Users Log Report", icon: "document-text-outline" },
      // Iter 145 (user spec) — full punch audit trail with Excel download.
      { route: "/punch-log-report", label: "Punch Log Report", icon: "finger-print-outline" },
      // Iter 153 — handwritten sheet OCR reconciliation (MIS).
      { route: "/sheet-verification", label: "Sheet Verification (OCR)", icon: "document-attach-outline" },
      // Iter 155 — full DB backup (screen itself is super-admin gated).
      { route: "/database-backup", label: "Database Backup", icon: "server-outline" },
      { route: "/report-formats", label: "PDF Report Formats", icon: "options-outline" },
      { route: "/messages", label: "Messages", icon: "chatbubbles-outline" },
      { route: "/tickets", label: "Tickets", icon: "ticket-outline" },
      { route: "/mailbox", label: "Mailbox (Email)", icon: "mail-outline" },
      { route: "/database-viewer", label: "Database Viewer / Editor", icon: "server-outline" },
    ],
  },
  // Iter 85 — Portal theme switcher (Appearance).
  { route: "/appearance", label: "Appearance / Theme", icon: "color-palette-outline" },
  // User directive — AI Insights lives at the very END of the sidebar.
  { route: "/ai-insights", label: "AI Insights", icon: "sparkles-outline" },
];

// Nav-permission map: which permission key gates which sidebar entry.
// Sub-admins with `read` OR `write` on a permission group see the entry.
const NAV_PERMISSION_MAP: Record<string, string[]> = {
  "/companies": ["companies:read", "companies:write"],
  "/company-requests": ["company_requests:read", "company_requests:write"],
  "/bulk-employee-correction": ["employees:read", "employees:write"],
  "/attendance-policy": ["attendance_policy:read", "attendance_policy:write"],
  "/punch-approvals": ["punch_approvals:read", "punch_approvals:write"],
  "/location-audit": ["punch_approvals:read", "punch_approvals:write"],
  "/biometric-devices": ["biometric_devices:read", "biometric_devices:write"],
  "/attendance-review": ["attendance_review:read", "attendance_review:write"],
  "/salary-run": ["salary_process:read", "salary_process:write"],
  "/arrear-salary-run": ["salary_process:read", "salary_process:write"],
  "/ot-salary-run": ["salary_process:read", "salary_process:write"],
  "/compliance-salary-run": ["compliance_salary:read", "compliance_salary:write"],
  "/messages": ["messages:read", "messages:write"],
  "/tickets": ["tickets:read", "tickets:write"],
};

// Iter 83 — Render a single sidebar row. Handles both leaf links and
// expandable parents (groups with ``children``).
function NavRow({
  item,
  activeRoute,
  pathname,
  fullPath,
  onNavigate,
  depth = 0,
}: {
  item: NavItem;
  activeRoute: string;
  pathname: string;
  fullPath: string;
  onNavigate: (route: string) => void;
  depth?: number;
}) {
  const hasChildren = !!(item.children && item.children.length > 0);
  // Iter 83-fix — Match FULL route (including ``?tab=xxx``) so sibling
  // sub-items that share the same base path (e.g. /reports?tab=salary vs
  // /reports?tab=compliance) don't ALL highlight together. Falls back to
  // the base pathname when the item has no query string.
  const matchesFull = (route: string) => {
    if (!route) return false;
    if (route.includes("?")) return route === fullPath;
    const base = route.split("?")[0];
    return pathname === base || pathname.startsWith(`${base}/`);
  };
  const childActive =
    hasChildren && item.children!.some((c) => matchesFull(c.route || ""));
  const [open, setOpen] = React.useState<boolean>(childActive);
  React.useEffect(() => {
    if (childActive) setOpen(true);
  }, [childActive]);
  const active = !hasChildren && matchesFull(item.route || "");
  const testId = `nav-${(item.route || item.label).replace(/[^a-z0-9]/gi, "-")}`;
  return (
    <>
      <Pressable
        onPress={() => {
          if (hasChildren) {
            setOpen((v) => !v);
          } else if (item.route) {
            onNavigate(item.route);
          }
        }}
        style={[
          {
            flexDirection: "row",
            alignItems: "center",
            gap: 12,
            paddingVertical: active ? 12 : 10,
            paddingHorizontal: 16 + depth * 12,
            borderRadius: 8,
            marginBottom: 2,
            // Iter 83 — use ``brand`` (deep teal) as the active fill.
            // ``colors.primary`` doesn't exist in the current theme so the
            // previous version rendered with an invisible background,
            // making the white text look blurry / unreadable.
            backgroundColor: active ? colors.brand : "transparent",
            borderLeftWidth: active ? 3 : 0,
            borderLeftColor: active ? colors.accent : "transparent",
          },
        ]}
        testID={testId}
      >
        <Ionicons
          name={item.icon}
          size={active ? 20 : 18}
          color={active ? "#FFFFFF" : colors.onSurfaceSecondary}
        />
        <Text
          style={{
            flex: 1,
            // Iter 85 — Selected sidebar row uses a matching size + regular
            // weight per user request. Emphasis comes from the brand
            // background fill + left-border accent, not from bold text.
            fontSize: 14,
            fontWeight: active ? "500" : (childActive ? "600" : "500"),
            letterSpacing: 0,
            color: active
              ? "#FFFFFF"
              : (childActive ? colors.brand : colors.onSurfaceSecondary),
            textTransform: "none",
          }}
        >
          {item.label}
        </Text>
        {hasChildren ? (
          <Ionicons
            name={open ? "chevron-down" : "chevron-forward"}
            size={16}
            color={colors.onSurfaceSecondary}
          />
        ) : null}
      </Pressable>
      {hasChildren && open ? (
        <View>
          {item.children!.map((child, i) => (
            <NavRow
              key={child.route || `${child.label}-${i}`}
              item={child}
              activeRoute={activeRoute}
              pathname={pathname}
              onNavigate={onNavigate}
              depth={depth + 1}
            />
          ))}
        </View>
      ) : null}
    </>
  );
}


export const NAV_COMPANY_ADMIN: NavItem[] = [
  { route: "/(tabs)", label: "Dashboard", icon: "home-outline" },
  // Iter 89 — Add New Employee shifted to position 2 per user request.
  { route: "/employee-add", label: "Add New Employee", icon: "person-add-outline" },
  { route: "/admin", label: "Employee Master Data", icon: "people-outline" },
  {
    label: "Salary Process",
    icon: "cash-outline",
    children: [
      { route: "/salary-run", label: "Salary Process (Actual)", icon: "cash-outline" },
      { route: "/compliance-salary-run", label: "Salary Process (Compliance)", icon: "briefcase-outline" },
      { route: "/ot-salary-run", label: "Salary Process (OT)", icon: "flash-outline" },
      { route: "/arrear-salary-run", label: "Salary Process (Arrear)", icon: "time-outline" },
    ],
  },
  { route: "/bulk-employee-correction", label: "Bulk Employee Correction", icon: "people-outline" },
  {
    label: "Approvals",
    icon: "checkmark-done-circle-outline",
    children: [
      { route: "/punch-approvals", label: "Punch Approvals", icon: "checkmark-circle-outline" },
      { route: "/contractor-punches", label: "Contractor Punches", icon: "briefcase-outline" },
      { route: "/shift-approvals", label: "Shift Change Approvals", icon: "swap-horizontal-outline" },
      { route: "/attendance-approvals", label: "Attendance Approvals", icon: "hand-right-outline" },
      { route: "/deletion-approvals", label: "Deletion Approvals", icon: "trash-bin-outline" },
      { route: "/attendance-review", label: "Attendance Review", icon: "shield-checkmark-outline" },
    ],
  },
  { route: "/zk-dat-import", label: "Import Biometric .dat", icon: "finger-print-outline" },
  { route: "/join-qr", label: "QR Codes (Join / App)", icon: "qr-code-outline" },
  {
    label: "Reports",
    icon: "bar-chart-outline",
    children: [
      { route: "/attendance-grid", label: "Attendance Report", icon: "grid-outline" },
      { route: "/daily-present-report", label: "Day-wise Present Count", icon: "people-outline" },
      { route: "/salary-day-sheet", label: "Day-wise Salary Sheet", icon: "calendar-outline" },
      { route: "/master-data-report", label: "Master Data", icon: "server-outline" },
      { route: "/compliance-reports", label: "Compliance Reports", icon: "shield-checkmark-outline" },
      { route: "/pf-reports?kind=pf", label: "PF Reports", icon: "briefcase-outline" },
      { route: "/pf-reports?kind=esic", label: "ESIC Reports", icon: "medkit-outline" },
      { route: "/bank-sheet", label: "Bank Sheet Format", icon: "card-outline" },
      { route: "/reports?tab=salary", label: "Actual Salary Report", icon: "cash-outline" },
      { route: "/reports?tab=compliance", label: "Compliance Report", icon: "shield-checkmark-outline" },
      { route: "/reports?tab=bonus", label: "Bonus Report", icon: "gift-outline" },
      { route: "/bonus-yearly-summary", label: "Bonus Yearly Summary", icon: "calendar-outline" },
      { route: "/leave-report", label: "Leave Report", icon: "calendar-number-outline" },
      { route: "/hr-letters", label: "HR Letters", icon: "document-text-outline" },
      { route: "/employee-report", label: "Employee Report", icon: "people-outline" },
      { route: "/challan-summary", label: "Monthly Challan Summary", icon: "documents-outline" },
    ],
  },
  { route: "/attendance-grid", label: "Attendance Grid / Sheet", icon: "grid-outline" },
  {
    label: "Masters",
    icon: "list-outline",
    children: [
      { route: "/masters", label: "General Masters", icon: "layers-outline" },
    ],
  },
  { route: "/employee-bulk-import", label: "Bulk Import (Excel)", icon: "cloud-upload-outline" },
  { route: "/attendance-policy", label: "Attendance Policy", icon: "time-outline" },
  { route: "/location-audit", label: "Location Audit", icon: "navigate-outline" },
  { route: "/biometric-devices", label: "Biometric Devices", icon: "finger-print-outline" },
  { route: "/messages", label: "Messages", icon: "chatbubbles-outline" },
  { route: "/tickets", label: "Tickets", icon: "ticket-outline" },
  // Iter 85 — Appearance / Theme is intentionally omitted from the
  // Company Admin nav — theme switching is Super-Admin-only.
];

export type NavItem = {
  route?: string;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  // Iter 83 — sub-items for expandable groups (Approvals, Reports,
  // Automation, User Rights, Masters). When ``children`` is present the
  // parent renders as an expander instead of a link.
  children?: NavItem[];
};

type Props = { children: React.ReactNode };

export default function AdminWebShell({ children }: Props) {
  const { user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const { width } = useWindowDimensions();
  const { refreshedAt, bumpRefresh } = useRefreshBus();
  const { selectedCompany, clearLock } = useSelectedCompany();
  // Iter 85 — Logout button opens a small confirmation modal with TWO
  // choices for super/sub admins: fully sign out, or just switch firm
  // (clear the selection so they can pick another firm from the picker
  // without re-entering credentials).
  const [logoutModal, setLogoutModal] = React.useState(false);
  // Iter 89 — Notifications bell + unread badge for the admin header.
  const { unreadCount: unreadNotifCount } = useUnreadNotifications();

  // Show the desktop portal shell ONLY on a wide web viewport (≥ 960px).
  // On a phone-sized web viewport (mobile browser / installed PWA on a
  // phone) we render the SAME mobile-app UI as the native app — the
  // (tabs) layout + full-screen screens — so mobile users get the exact
  // app experience. Native mobile apps never see this shell at all.
  const isWebDesktop = Platform.OS === "web" && width >= DESKTOP_MIN;
  const role = user?.role;
  const isSubAdmin = (user?.role as string) === "sub_admin";
  // Iter 127 — Primary-inbox mail badge (Super/Sub Admin only).
  const { count: primaryUnread } = usePrimaryInbox(
    role === "super_admin" || role === "sub_admin",
  );

  // Iter 67 — Sub-Admin gate: /firm-select renders full-bleed without the
  // sidebar / top-bar chrome so the picker is the only thing on screen.
  const isBareRoute = pathname === "/firm-select";

  // Iter 110 — Firm Master salary-process linkage gates the sidebar:
  //   Online Salary OFF  → hide "Salary Process (Compliance)" (+ Arrear,
  //                        which is derived from compliance runs)
  //   Offline Salary OFF → hide "Salary Process (Actual)"
  // Gating applies ONLY when the firm has configured at least one toggle
  // ON — a fully unconfigured/legacy firm keeps every entry visible.
  // No firm selected ("All firms" rollup) → no gating.
  const gateCompanyId =
    role === "company_admin"
      ? (user as any)?.company_id || null
      : selectedCompany?.company_id || null;
  const [salaryFlags, setSalaryFlags] = useState<{ online: boolean; offline: boolean } | null>(null);
  useEffect(() => {
    let alive = true;
    if (!gateCompanyId || !isWebDesktop) { setSalaryFlags(null); return; }
    (async () => {
      try {
        const fm = await api<any>(`/admin/firm-master/${gateCompanyId}`);
        const sp = fm?.master?.salary_process || {};
        if (alive) setSalaryFlags({ online: !!sp.online_salary, offline: !!sp.offline_salary });
      } catch {
        if (alive) setSalaryFlags(null);
      }
    })();
    return () => { alive = false; };
  }, [gateCompanyId, isWebDesktop, refreshedAt]);

  const nav = useMemo(() => {
    // Iter 83 — filterNav applies a per-item predicate recursively so
    // sub-menu children get gated by permissions the same way as top-level
    // items. Parent groups (items with ``children`` but no ``route``) stay
    // visible as long as at least one child is visible.
    const filterNav = (items: NavItem[], keep: (n: NavItem) => boolean): NavItem[] => {
      const out: NavItem[] = [];
      for (const item of items) {
        if (item.children && item.children.length > 0) {
          const kids = filterNav(item.children, keep);
          if (kids.length > 0) out.push({ ...item, children: kids });
          continue;
        }
        if (keep(item)) out.push(item);
      }
      return out;
    };

    if (role === "super_admin") return NAV_SUPER;
    if (role === "sub_admin") {
      const perms: string[] = (user as any)?.sub_admin_permissions || [];
      const permSet = new Set(perms);
      // Iter 93 — per-sidebar-button gating set by the super admin on the
      // Sub Admins screen. menu_rights[route] === false hides the button.
      const subMenuRights: Record<string, boolean> =
        (user as any)?.menu_rights || {};
      return filterNav(NAV_SUPER, (item) => {
        if (subMenuRights[item.route || ""] === false) return false;
        const r = (item.route || "").split("?")[0];
        if (r === "/sub-admins") return false;
        if (r === "/employer-access-rights") return false;
        if (r === "/super-admin-access") return false;
        if (r === "/attendance-sheet") return false;
        if (r === "/masters") return false;
        if (r === "/compliance-policy") return false;
        if (r === "/portal-automation") return false;
        if (r === "/ai-insights") return false;
        // Iter 85 — Appearance / Theme switching is Super-Admin-only.
        if (r === "/appearance") return false;
        if (r === "/attendance-email") return true;
        if (r === "/bulk-employee-correction") return true;
        if (r === "/bonus-run") return true;
        if (r === "/(tabs)") return true;
        const gates = NAV_PERMISSION_MAP[r];
        if (!gates || gates.length === 0) return true;
        return gates.some((g) => permSet.has(g));
      });
    }
    if (role === "company_admin") {
      // Iter 58 — filter by the FIRM's employer_permissions. Empty list
      // means "all features enabled" (backward compat) EXCEPT for
      // compliance-related routes, which are always OPT-IN (iter 62 —
      // super admin must explicitly grant compliance_salary:read/write
      // before company admins even see the menu entry).
      const COMPLIANCE_ROUTES = new Set([
        "/compliance-salary-run",
      ]);
      // Iter 125 — Salary processing (Actual + Arrear) is also OPT-IN:
      // the super admin must grant salary_process:read/write from the
      // Employer Access Rights panel before firm admins see these menus.
      const SALARY_ROUTES = new Set([
        "/salary-run",
        "/arrear-salary-run",
        "/ot-salary-run",
      ]);
      const empPerms: string[] = (user as any)?.employer_permissions || [];
      const permSet = new Set(empPerms);
      // Iter 93 — per-sidebar-button gating set from Access Rights.
      // menu_rights[route] === false hides the button; missing == allowed.
      const menuRights: Record<string, boolean> =
        (user as any)?.menu_rights || {};
      const menuAllowed = (item: NavItem) =>
        menuRights[item.route || ""] !== false;
      const hasComplianceGrant =
        permSet.has("compliance_salary:read") ||
        permSet.has("compliance_salary:write");
      const hasSalaryGrant =
        permSet.has("salary_process:read") ||
        permSet.has("salary_process:write");
      if (empPerms.length === 0) {
        return filterNav(NAV_COMPANY_ADMIN, (item) => {
          if (!menuAllowed(item)) return false;
          const r = (item.route || "").split("?")[0];
          if (COMPLIANCE_ROUTES.has(r)) return hasComplianceGrant;
          if (SALARY_ROUTES.has(r)) return hasSalaryGrant;
          return true;
        });
      }
      return filterNav(NAV_COMPANY_ADMIN, (item) => {
        if (!menuAllowed(item)) return false;
        const r = (item.route || "").split("?")[0];
        if (r === "/(tabs)") return true;
        const gates = NAV_PERMISSION_MAP[r];
        if (!gates || gates.length === 0) return true;
        if (COMPLIANCE_ROUTES.has(r)) return hasComplianceGrant;
        if (SALARY_ROUTES.has(r)) return hasSalaryGrant;
        return gates.some((g) => permSet.has(g));
      });
    }
    return NAV_COMPANY_ADMIN;
  }, [role, user]);

  // Iter 114 — process-flow gating: Compliance Salary is DEFAULT for every
  // firm (never hidden). The ACTUAL Salary Process shows only when the
  // firm's Offline Salary toggle is ON. Unconfigured firms (both toggles
  // off) keep every entry visible (legacy behaviour).
  const gatedNav = useMemo(() => {
    if (!salaryFlags || (!salaryFlags.online && !salaryFlags.offline)) return nav;
    const HIDE = new Set<string>();
    if (!salaryFlags.offline) HIDE.add("/salary-run");
    // Iter 129h (user directive) — Attendance Policy is only relevant for
    // firms running Off-roll (Offline/Actual) salary from biometrics.
    if (!salaryFlags.offline) HIDE.add("/attendance-policy");
    if (HIDE.size === 0) return nav;
    const prune = (items: NavItem[]): NavItem[] => {
      const out: NavItem[] = [];
      for (const it of items) {
        if (it.children && it.children.length > 0) {
          const kids = prune(it.children);
          if (kids.length > 0) out.push({ ...it, children: kids });
          continue;
        }
        if (!HIDE.has((it.route || "").split("?")[0])) out.push(it);
      }
      return out;
    };
    return prune(nav);
  }, [nav, salaryFlags]);

  // Iter 83 — flatten the nav tree (parents + children) so activeRoute /
  // page title lookups can still match child routes. Kept BEFORE any
  // early-return so React hook order stays stable.
  const flatNav = useMemo(() => {
    const out: NavItem[] = [];
    const walk = (items: NavItem[]) => {
      for (const it of items) {
        if (it.route) out.push(it);
        if (it.children) walk(it.children);
      }
    };
    walk(gatedNav);
    return out;
  }, [gatedNav]);

  if (!isWebDesktop || !user) return <>{children}</>;
  if (isBareRoute) return <>{children}</>;

  // Web-only guard — employees logged into the web preview see a friendly
  // "download the mobile app" screen instead of the full tabs UI.
  if (role !== "super_admin" && role !== "company_admin" && role !== "sub_admin") {
    return <EmployeeWebGate />;
  }

  const activeRoute =
    flatNav.find((item) => {
      const r = (item.route || "").split("?")[0];
      return pathname === r || pathname.startsWith(`${r}/`);
    })?.route || "/(tabs)";

  return (
    <View style={styles.shell} testID="admin-web-shell">
      {/* Sidebar */}
      <View style={styles.sidebar}>
        <View style={styles.logoBlock}>
          {/* Iter 89 — Firm logo synced from Firm Master. Falls back to
              the "SKS" wordmark when no firm is selected or logo missing. */}
          {selectedCompany?.logo_base64 ? (
            <View style={styles.logoBadge}>
              <Image
                source={{ uri: selectedCompany.logo_base64 }}
                style={{ width: "100%", height: "100%" }}
                resizeMode="contain"
              />
            </View>
          ) : (
            <View style={styles.logoBadge}>
              <Image
                source={require("../../assets/images/logo-mark.png")}
                style={{ width: "100%", height: "100%", borderRadius: 10 }}
                resizeMode="contain"
              />
            </View>
          )}
          <View style={{ flex: 1 }}>
            <Text style={styles.brand}>
              {selectedCompany?.name || "S.K. Sharma & Co."}
            </Text>
            <Text style={styles.brandSub}>
              {role === "super_admin" ? "Super Admin" : role === "sub_admin" ? "Sub Admin" : "Company Admin"}
            </Text>
          </View>
        </View>

        {/* Iter 85 pt 3 — Active Firm pill. Always visible under the logo
            block so admins never lose sight of the firm scope they're
            operating in. Tap to switch (clears the lock and opens the
            firm picker). */}
        {selectedCompany ? (
          <Pressable
            onPress={() => {
              clearLock();
              router.push("/firm-select" as any);
            }}
            style={styles.firmPill}
            testID="sidebar-active-firm"
          >
            <View style={styles.firmPillIcon}>
              <Ionicons name="business-outline" size={12} color="#fff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.firmPillLabel}>ACTIVE FIRM</Text>
              <Text style={styles.firmPillName} numberOfLines={1}>
                {selectedCompany.name}
              </Text>
            </View>
            <Ionicons name="swap-horizontal" size={14} color={colors.brandPrimary} />
          </Pressable>
        ) : null}

        <View style={styles.divider} />

        <ScrollView
          style={styles.navScroll}
          contentContainerStyle={{ paddingBottom: 12 }}
          showsVerticalScrollIndicator={true}
          persistentScrollbar={true}
        >
          {gatedNav.map((item, idx) => (
            <NavRow
              key={item.route || `${item.label}-${idx}`}
              item={item}
              activeRoute={activeRoute}
              pathname={pathname}
              onNavigate={(route) => {
                // Iter 126d — "/(tabs)" group push is flaky on static web
                // exports (REPLACE not handled). Route via "/" — index
                // redirects logged-in admins to the dashboard reliably.
                router.push((route === "/(tabs)" ? "/" : route) as any);
              }}
            />
          ))}
        </ScrollView>

        <View style={styles.divider} />

        <View style={styles.userBlock}>
          <View style={styles.avatar}>
            <Text style={styles.avatarTxt}>
              {(user.name || user.email || "?").trim().charAt(0).toUpperCase()}
            </Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.userName} numberOfLines={1}>
              {user.name || user.email || "Admin"}
            </Text>
            <Text style={styles.userMeta} numberOfLines={1}>
              {user.email || user.phone || ""}
            </Text>
          </View>
          <Pressable onPress={logout} hitSlop={8} testID="web-logout">
            <Ionicons name="log-out-outline" size={18} color={colors.error} />
          </Pressable>
        </View>
      </View>

      {/* Main pane */}
      <View style={styles.mainWrap}>
        <View style={styles.topBar}>
          <Text style={styles.pageTitle}>
            {flatNav.find((n) => n.route === activeRoute)?.label || "Workspace"}
          </Text>
          <View style={styles.topRight}>
            {isSubAdmin ? (
              <Pressable
                onPress={() => router.push("/firm-select")}
                style={({ pressed }) => [styles.switchFirmBtn, pressed && { opacity: 0.85 }]}
                testID="switch-firm-btn"
              >
                <Ionicons name="swap-horizontal" size={14} color="#0369A1" />
                <Text style={styles.switchFirmTxt}>Switch firm</Text>
              </Pressable>
            ) : null}
            <GlobalCompanyPicker compact />
            {/* Iter 72 — Global Refresh button.
                Bumps the RefreshBus tick so every listening page (any
                admin screen that subscribes with useRefreshBus + a
                useEffect) refetches its data.  A subtle "last refreshed
                Xm ago" pill sits next to it so operators can spot stale
                dashboards at a glance. */}
            <Pressable
              onPress={bumpRefresh}
              style={({ pressed }) => [
                styles.refreshBtnTop,
                pressed && { opacity: 0.85 },
              ]}
              testID="web-refresh-top"
            >
              <Ionicons name="refresh-outline" size={14} color="#0369A1" />
              <Text style={styles.refreshBtnTopTxt}>Refresh</Text>
            </Pressable>
            {refreshedAt ? (
              <Text style={styles.refreshedAtTxt} testID="web-refreshed-at">
                {formatSinceRefresh(refreshedAt)}
              </Text>
            ) : null}
            {/* Iter 127 — Primary Inbox mail badge (Super/Sub Admin). */}
            {role === "super_admin" || role === "sub_admin" ? (
              <Pressable
                onPress={() => router.push("/mailbox" as any)}
                style={({ pressed }) => [
                  styles.notifBellBtn,
                  pressed && { opacity: 0.85 },
                ]}
                testID="web-mail-bell"
                hitSlop={6}
              >
                <Ionicons
                  name={primaryUnread > 0 ? "mail-unread" : "mail-outline"}
                  size={18}
                  color={primaryUnread > 0 ? colors.accent : colors.brandPrimary}
                />
                {primaryUnread > 0 ? (
                  <View style={styles.notifBadge}>
                    <Text style={styles.notifBadgeTxt} numberOfLines={1}>
                      {primaryUnread > 99 ? "99+" : String(primaryUnread)}
                    </Text>
                  </View>
                ) : null}
              </Pressable>
            ) : null}
            {/* Iter 89 — Notifications bell with unread badge. */}
            <Pressable
              onPress={() => router.push("/notifications" as any)}
              style={({ pressed }) => [
                styles.notifBellBtn,
                pressed && { opacity: 0.85 },
              ]}
              testID="web-notif-bell"
              hitSlop={6}
            >
              <Ionicons
                name={unreadNotifCount > 0 ? "notifications" : "notifications-outline"}
                size={18}
                color={unreadNotifCount > 0 ? colors.accent : colors.brandPrimary}
              />
              {unreadNotifCount > 0 ? (
                <View style={styles.notifBadge}>
                  <Text style={styles.notifBadgeTxt} numberOfLines={1}>
                    {unreadNotifCount > 99 ? "99+" : String(unreadNotifCount)}
                  </Text>
                </View>
              ) : null}
            </Pressable>
            <Text style={styles.envTxt}>Web portal</Text>
            {/* Iter 85 — Logout button. For Super/Sub admins it opens a
                two-choice confirmation (User Logout / Switch Firm); for
                Company admins it logs out immediately. */}
            <Pressable
              onPress={() => {
                if (user?.role === "super_admin" || user?.role === "sub_admin") {
                  setLogoutModal(true);
                } else {
                  logout();
                }
              }}
              style={({ pressed }) => [
                styles.logoutBtnTop,
                pressed && { opacity: 0.9 },
              ]}
              testID="web-logout-top"
            >
              <Ionicons name="log-out-outline" size={14} color="#DC2626" />
              <Text style={styles.logoutBtnTopTxt}>Logout</Text>
            </Pressable>
          </View>
        </View>
        <View style={styles.main} testID="admin-web-main">
          {children}
        </View>
      </View>

      {/* Iter 85 — Logout confirmation modal (Super/Sub admin only) */}
      {logoutModal ? (
        <View style={styles.logoutOverlay} testID="logout-choice-modal">
          <Pressable
            style={StyleSheet.absoluteFill}
            onPress={() => setLogoutModal(false)}
          />
          <View style={styles.logoutModal}>
            <Text style={styles.logoutModalTitle}>What would you like to do?</Text>
            <Text style={styles.logoutModalSub}>
              {selectedCompany
                ? `Currently viewing: ${selectedCompany.name}`
                : "No firm currently selected."}
            </Text>

            <Pressable
              onPress={() => {
                setLogoutModal(false);
                clearLock();
                router.push("/firm-select" as any);
              }}
              style={({ pressed }) => [
                styles.logoutChoiceBtn,
                { backgroundColor: colors.brandPrimary },
                pressed && { opacity: 0.85 },
              ]}
              testID="logout-choice-switch-firm"
            >
              <Ionicons name="swap-horizontal" size={16} color="#fff" />
              <View style={{ flex: 1 }}>
                <Text style={styles.logoutChoicePrimary}>Select Another Firm</Text>
                <Text style={styles.logoutChoiceSec}>
                  Stay signed in and switch to a different firm
                </Text>
              </View>
            </Pressable>

            <Pressable
              onPress={() => {
                setLogoutModal(false);
                logout();
              }}
              style={({ pressed }) => [
                styles.logoutChoiceBtn,
                { backgroundColor: "#DC2626" },
                pressed && { opacity: 0.85 },
              ]}
              testID="logout-choice-full"
            >
              <Ionicons name="log-out-outline" size={16} color="#fff" />
              <View style={{ flex: 1 }}>
                <Text style={styles.logoutChoicePrimary}>User Logout</Text>
                <Text style={styles.logoutChoiceSec}>
                  Sign out completely — you&apos;ll need to log in again
                </Text>
              </View>
            </Pressable>

            <Pressable
              onPress={() => setLogoutModal(false)}
              style={({ pressed }) => [
                styles.logoutCancelBtn,
                pressed && { opacity: 0.85 },
              ]}
              testID="logout-choice-cancel"
            >
              <Text style={styles.logoutCancelTxt}>Cancel</Text>
            </Pressable>
          </View>
        </View>
      ) : null}
    </View>
  );
}

function EmployeeWebGate() {
  const { logout } = useAuth();
  return (
    <View style={styles.gateShell} testID="employee-web-gate">
      <View style={styles.gateCard}>
        <View style={styles.gateIcon}>
          <Ionicons name="phone-portrait-outline" size={40} color={colors.brandPrimary} />
        </View>
        <Text style={styles.gateTitle}>Please use the mobile app</Text>
        <Text style={styles.gateBody}>
          Punch-in, punch-out, face verification and geo-fenced attendance need the phone
          camera and GPS. The web portal is available to admins only.
        </Text>
        <View style={styles.gateActions}>
          <Pressable onPress={logout} style={styles.gateBtn}>
            <Ionicons name="log-out-outline" size={16} color={colors.onCta} />
            <Text style={styles.gateBtnTxt}>Sign out</Text>
          </Pressable>
        </View>
        <Text style={styles.gateHint}>
          Ask your administrator for the Android / iOS install link.
        </Text>
      </View>
    </View>
  );
}

const SIDEBAR_WIDTH = 244;

const styles = StyleSheet.create({
  shell: {
    flex: 1,
    flexDirection: "row",
    backgroundColor: "#F4F7F7",
    minHeight: "100%" as unknown as number,
  },
  sidebar: {
    width: SIDEBAR_WIDTH,
    backgroundColor: colors.surface,
    borderRightWidth: 1,
    borderRightColor: colors.border,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
  },
  navScroll: {
    // Bound the nav list height so it becomes a proper scroll container and
    // the vertical scrollbar is visible when the menu overflows (web).
    flex: 1,
  },
  logoBlock: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 8,
    paddingBottom: spacing.md,
  },
  logoBadge: {
    width: 36,
    height: 36,
    borderRadius: 10,
    backgroundColor: "#ffffff",
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.divider,
  },
  brand: { color: colors.onSurface, fontWeight: "800", fontSize: 13 },
  brandSub: { color: colors.onSurfaceTertiary, fontSize: 10, marginTop: 2, fontWeight: "700", letterSpacing: 0.4 },
  divider: { height: 1, backgroundColor: colors.divider, marginVertical: 4 },

  // Iter 85 pt 3 — Active-Firm pill under the sidebar logo.
  firmPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginHorizontal: 12,
    marginTop: 8,
    padding: 8,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  firmPillIcon: {
    width: 22, height: 22, borderRadius: 11,
    backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  firmPillLabel: {
    fontSize: 9,
    fontWeight: "800",
    color: colors.onSurfaceSecondary,
    letterSpacing: 0.4,
  },
  firmPillName: {
    fontSize: 12,
    fontWeight: "800",
    color: colors.onSurface,
    marginTop: 1,
  },
  navItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radius.md,
    marginVertical: 2,
  },
  navItemActive: { backgroundColor: colors.brandPrimary },
  navLabel: { color: colors.onSurface, fontSize: 13, fontWeight: "600" },
  navLabelActive: { color: colors.onCta, fontWeight: "700" },
  userBlock: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
    paddingHorizontal: 8,
  },
  avatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarTxt: { color: colors.brandPrimary, fontWeight: "800" },
  userName: { color: colors.onSurface, fontWeight: "700", fontSize: 12 },
  userMeta: { color: colors.onSurfaceTertiary, fontSize: 10, marginTop: 2 },

  mainWrap: { flex: 1, minWidth: 0 },
  topBar: {
    height: 56,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    // Iter 94 FIX — keep the header (and the firm-picker dropdown inside
    // it) ABOVE the main content area. Without this, clicks on dropdown
    // items were swallowed by `main`, so firm selection never committed.
    zIndex: 3000,
  },
  pageTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800" },
  topRight: { flexDirection: "row", alignItems: "center", gap: 12 },
  envTxt: {
    color: colors.brandPrimary,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.6,
    paddingHorizontal: 8,
    paddingVertical: 4,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.pill,
  },
  switchFirmBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.pill,
    backgroundColor: "#E0F2FE",
    borderWidth: 1,
    borderColor: "#BAE6FD",
  },
  switchFirmTxt: {
    color: "#0369A1",
    fontSize: 12,
    fontWeight: "700",
  },
  refreshBtnTop: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.pill,
    backgroundColor: "#E0F2FE",
    borderWidth: 1,
    borderColor: "#BAE6FD",
  },
  refreshBtnTopTxt: {
    color: "#0369A1",
    fontSize: 12,
    fontWeight: "700",
  },
  refreshedAtTxt: {
    color: colors.onSurfaceSecondary,
    fontSize: 11,
    fontStyle: "italic",
  },
  // Iter 89 — Notifications bell + badge (header)
  notifBellBtn: {
    position: "relative",
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.brandTertiary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  notifBadge: {
    position: "absolute",
    top: -3,
    right: -3,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: colors.error,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 4,
    borderWidth: 2,
    borderColor: colors.surface,
  },
  notifBadgeTxt: {
    color: colors.onError,
    fontSize: 10,
    fontWeight: "800",
  },
  logoutBtnTop: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: radius.pill,
    backgroundColor: "#FEF2F2",
    borderWidth: 1,
    borderColor: "#FECACA",
  },
  logoutBtnTopTxt: {
    color: "#DC2626",
    fontSize: 12,
    fontWeight: "800",
  },

  // Iter 85 — Logout choice modal (Super/Sub admin only)
  logoutOverlay: {
    position: "absolute",
    top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: "rgba(15,23,42,0.55)",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
  },
  logoutModal: {
    width: 400,
    maxWidth: "92%",
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: 10,
    ...(Platform.OS === "web"
      ? ({ boxShadow: "0 24px 48px rgba(0,0,0,0.25)" } as any)
      : { elevation: 12 }),
  },
  logoutModalTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: colors.onSurface,
  },
  logoutModalSub: {
    fontSize: 12,
    color: colors.onSurfaceSecondary,
    marginBottom: 8,
  },
  logoutChoiceBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    borderRadius: radius.md,
  },
  logoutChoicePrimary: {
    color: "#fff",
    fontSize: 14,
    fontWeight: "800",
  },
  logoutChoiceSec: {
    color: "rgba(255,255,255,0.85)",
    fontSize: 11,
    marginTop: 2,
  },
  logoutCancelBtn: {
    paddingVertical: 10,
    alignItems: "center",
    marginTop: 4,
  },
  logoutCancelTxt: {
    color: colors.onSurfaceSecondary,
    fontSize: 13,
    fontWeight: "700",
  },
  main: { flex: 1, backgroundColor: "#F4F7F7" },

  gateShell: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    backgroundColor: "#F4F7F7",
    minHeight: 400,
  },
  gateCard: {
    maxWidth: 480,
    padding: spacing.xl,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    gap: 12,
  },
  gateIcon: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  gateTitle: { color: colors.onSurface, fontSize: 20, fontWeight: "800" },
  gateBody: {
    color: colors.onSurfaceSecondary,
    fontSize: type.base,
    textAlign: "center",
    lineHeight: 22,
  },
  gateHint: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 6 },
  gateActions: { flexDirection: "row", gap: 8, marginTop: 8 },
  gateBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: radius.pill,
    backgroundColor: colors.brandPrimary,
  },
  gateBtnTxt: { color: colors.onCta, fontWeight: "700" },
});
