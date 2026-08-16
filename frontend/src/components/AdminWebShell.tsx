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
  TextInput,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { usePathname, useRouter } from "expo-router";

import { api, readEmployeeTokenBackup, clearEmployeeTokenBackup, saveToken } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import GlobalCompanyPicker from "@/src/components/GlobalCompanyPicker";
import { useRefreshBus } from "@/src/context/RefreshBusContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import WorkspaceTabs from "@/src/components/WorkspaceTabs";
import { onSyncMessage } from "@/src/utils/workspaceSync";
import { useUnreadNotifications } from "@/src/hooks/useUnreadNotifications";
import { usePrimaryInbox } from "@/src/hooks/usePrimaryInbox";
import { useTheme } from "@/src/context/ThemeContext";
import { colors, radius, spacing, type, isDarkTheme, DARK_THEME_ID } from "@/src/theme";
import AiAssistant from "@/src/components/AiAssistant";
import { useT, useLang, setLang } from "@/src/i18n";

// Iter 294 — Pinned favourites + recently-opened screens (web localStorage).
const FAV_KEY = "sksharma.nav.favs.v1";
export const RECENT_KEY = "sksharma.nav.recent.v1";
export function readNavList(k: string): string[] {
  if (Platform.OS !== "web" || typeof localStorage === "undefined") return [];
  try {
    const v = JSON.parse(localStorage.getItem(k) || "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch { return []; }
}
function writeNavList(k: string, v: string[]) {
  if (Platform.OS !== "web" || typeof localStorage === "undefined") return;
  try { localStorage.setItem(k, JSON.stringify(v.slice(0, 8))); } catch { /* noop */ }
}

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

// Iter 293 (user spec) — fixed dark sidebar palette. Sidebar bg #0F172A,
// primary/active #2563EB, hover #1D4ED8, light slate text.
const SB = {
  bg: "#0F172A",
  border: "#1E293B",
  divider: "#1E293B",
  text: "#CBD5E1",
  muted: "#94A3B8",
  active: "#2563EB",
  hover: "#1D4ED8",
  activeTint: "rgba(37,99,235,0.18)",
  linkLight: "#60A5FA",
};

export const NAV_SUPER: NavItem[] = [
  // Iter 293 (user spec) — 12-module sidebar reorganisation.
  { route: "/portal-dashboard", label: "Dashboard", icon: "home-outline" },
  {
    // Iter 306 (user #14) — dedicated Firms section.
    label: "Firms",
    icon: "business-outline",
    children: [
      { route: "/companies", label: "Companies (Firm Master)", icon: "business-outline" },
      { route: "/firm-list", label: "List of Firms", icon: "list-outline" },
      { route: "/firm-credentials", label: "Firms ID & Password (PF · ESIC)", icon: "key-outline" },
    ],
  },
  {
    label: "Employees",
    icon: "people-outline",
    children: [
      { route: "/employee-add", label: "Add New Employee", icon: "person-add-outline" },
      { route: "/admin", label: "All Employee Data", icon: "people-outline" },
      { route: "/employee-detail-slip", label: "Employee Detail Slip", icon: "id-card-outline" },
      { route: "/kyc-tracker", label: "KYC & Doc Expiry Tracker", icon: "id-card-outline" },
      { route: "/employee-reports", label: "Employee Reports Hub", icon: "documents-outline" },
      { route: "/employee-report", label: "Employee Report", icon: "people-outline" },
    ],
  },
  {
    label: "Attendance & Shift",
    icon: "time-outline",
    children: [
      { route: "/attendance-policy", label: "Attendance Policy", icon: "time-outline" },
      { route: "/attendance-grid", label: "Attendance Report", icon: "grid-outline" },
      { route: "/attendance-sync-dashboard", label: "Attendance Sync Dashboard", icon: "sync-outline" },
      { route: "/gps-dashboard", label: "GPS Diagnostics", icon: "locate-outline" },
      { route: "/whatsapp-center?tab=history", label: "WhatsApp Alerts", icon: "logo-whatsapp" },
      { route: "/attendance-sheet", label: "Attendance Master Sheet", icon: "document-text-outline" },
      { route: "/inout-ot-matrix", label: "In/Out & OT Matrix", icon: "apps-outline" },
      { route: "/present-absent-report", label: "Present / Absent Report", icon: "checkbox-outline" },
      { route: "/daily-present-report", label: "Day-wise Present Count", icon: "people-outline" },
      { route: "/backdate-punches", label: "Back-date Punches", icon: "calendar-clear-outline" },
      { route: "/past-salary-runs", label: "Past Salary Runs", icon: "albums-outline" },
      { route: "/shift-change-admin", label: "Shift Change Requests", icon: "swap-horizontal" },
      { route: "/attendance-approvals", label: "Attendance Approvals", icon: "hand-right-outline" },
      { route: "/punch-approvals", label: "Punch Approvals", icon: "checkmark-circle-outline" },
      { route: "/attendance-eligibility", label: "Attendance Eligibility", icon: "shield-checkmark-outline" },
      { route: "/contractor-punches", label: "Contractor Punches", icon: "briefcase-outline" },
      { route: "/geofence-policy", label: "Geofence Policy", icon: "location-outline" },
      { route: "/geofence-monitor", label: "Geofence Monitor", icon: "navigate-circle-outline" },
      { route: "/punch-log-report", label: "Punch Log Report", icon: "finger-print-outline" },
      { route: "/photo-sync", label: "Photo Sync / Reconciliation", icon: "images-outline" },
    ],
  },
  {
    label: "Payroll",
    icon: "cash-outline",
    children: [
      {
        label: "Salary Process",
        icon: "cash-outline",
        children: [
          { route: "/salary-run", label: "Actual Salary", icon: "cash-outline" },
          { route: "/compliance-salary-run", label: "Compliance Salary", icon: "briefcase-outline" },
          { route: "/esic-leave", label: "ESIC Leave", icon: "medkit-outline" },
          { route: "/ot-salary-run", label: "OT Salary", icon: "flash-outline" },
          { route: "/arrear-salary-run", label: "Arrear Salary", icon: "time-outline" },
          { route: "/salary-register", label: "Salary Register", icon: "grid-outline" },
          { route: "/ctc-management", label: "CTC Management", icon: "layers-outline" },
          { route: "/form16", label: "TDS · Form 16", icon: "document-text-outline" },
        ],
      },
      { route: "/advances", label: "Advance Management", icon: "wallet-outline" },
      { route: "/whatsapp-center?tab=slips", label: "Send Salary Slips (WhatsApp)", icon: "logo-whatsapp" },
      { route: "/bonus-run", label: "Bonus Process", icon: "gift-outline" },
      { route: "/bonus-registers", label: "Bonus Registers (A, B, D)", icon: "albums-outline" },
      { route: "/bonus-yearly-summary", label: "Bonus Yearly Summary", icon: "calendar-outline" },
      { route: "/payroll-register", label: "Yearly Payroll Register", icon: "grid-outline" },
      { route: "/ai-universal-import", label: "AI Universal Import", icon: "sparkles-outline" },
      { route: "/ai-salary-compliance", label: "Salary Compliance Process (AI)", icon: "calculator-outline" },
      { route: "/labour-statistics", label: "Labour Statistics & HR Analytics", icon: "stats-chart-outline" },
      { route: "/annual-returns", label: "Annual Returns", icon: "document-text-outline" },
      { route: "/factory-compliance", label: "Factory & Boilers", icon: "business-outline" },
      { route: "/salary-day-sheet", label: "Day-wise Salary Sheet", icon: "calendar-outline" },
      { route: "/reports?tab=salary", label: "Actual Salary Report", icon: "cash-outline" },
      { route: "/reports?tab=compliance", label: "Compliance Report", icon: "shield-checkmark-outline" },
      { route: "/bank-sheet", label: "Bank Sheet Format", icon: "card-outline" },
      { route: "/bank-transfer", label: "Bank Transfer Files", icon: "business-outline" },
      { route: "/leave-report", label: "Leave Report", icon: "calendar-number-outline" },
      { route: "/comp-off-ledger", label: "Comp-Off Ledger", icon: "time-outline" },
      { route: "/statutory-reports", label: "Full & Final Settlement", icon: "receipt-outline" },
    ],
  },
  {
    label: "Compliance",
    icon: "shield-checkmark-outline",
    children: [
      { route: "/pf-reports?kind=pf", label: "PF Reports", icon: "briefcase-outline" },
      { route: "/pf-reports?kind=esic", label: "ESIC Reports", icon: "medkit-outline" },
      { route: "/claims-management", label: "PF & ESIC Claims", icon: "folder-open-outline" },
      { route: "/statutory-reports", label: "PT / LWF / Gratuity / MIS", icon: "receipt-outline" },
      { route: "/factory-annual-return", label: "Factory & Boiler Annual Return", icon: "business-outline" },
      { route: "/challans", label: "PF / ESIC Upload", icon: "receipt-outline" },
      { route: "/challan-summary", label: "Monthly Challan Summary", icon: "documents-outline" },
      { route: "/automation-studio", label: "Compliance Automation Studio", icon: "sparkles-outline" },
      { route: "/whatsapp-center?tab=dashboard", label: "Notification Center", icon: "logo-whatsapp" },
    ],
  },
  {
    label: "Approvals & Workflow",
    icon: "checkmark-done-circle-outline",
    children: [
      { route: "/approval-inbox", label: "Approval Inbox", icon: "file-tray-full-outline" },
      { route: "/employee-approvals", label: "Pending Employee Approval", icon: "person-add-outline" },
      { route: "/company-requests", label: "Company Requests", icon: "mail-open-outline" },
      { route: "/shift-change-admin", label: "Shift Change Approval", icon: "swap-horizontal" },
      { route: "/attendance-approvals", label: "Attendance Approval", icon: "hand-right-outline" },
      { route: "/punch-approvals", label: "Punch Approval", icon: "checkmark-circle-outline" },
      { route: "/attendance-eligibility", label: "Attendance Eligibility", icon: "shield-checkmark-outline" },
      { route: "/deletion-approvals", label: "Deletion Approval", icon: "trash-bin-outline" },
      { route: "/access-management", label: "Workflow Management", icon: "git-branch-outline" },
      { route: "/employer-access-rights", label: "User Rights", icon: "key-outline" },
    ],
  },
  {
    label: "Reports",
    icon: "bar-chart-outline",
    children: [
      { route: "/reports-center", label: "Report Hub", icon: "library-outline" },
      { route: "/monthly-payroll-report", label: "Monthly Payroll Report", icon: "calendar-number-outline" },
      { route: "/labour-reports", label: "Labour Reports", icon: "documents-outline" },
      { route: "/labour-cost-dashboard", label: "Labour Cost Dashboard", icon: "trending-up-outline" },
      { route: "/attendance-grid", label: "Attendance Reports", icon: "grid-outline" },
      { route: "/daily-verification", label: "Daily In/Out & OT Verification", icon: "checkbox-outline" },
      { route: "/multi-punch-report", label: "Multiple Punch Report", icon: "repeat-outline" },
      { route: "/attendance-sync-dashboard", label: "Attendance Sync Dashboard", icon: "sync-outline" },
      { route: "/reports?tab=salary", label: "Payroll Reports", icon: "cash-outline" },
      { route: "/employee-reports", label: "Employee Reports", icon: "documents-outline" },
      { route: "/compliance-reports", label: "Compliance Reports", icon: "shield-checkmark-outline" },
      { route: "/reports?tab=bonus", label: "Bonus Reports", icon: "gift-outline" },
      { route: "/statutory-reports", label: "MIS Reports", icon: "receipt-outline" },
      { route: "/master-data-report", label: "Employee Master Report", icon: "server-outline" },
      { route: "/hr-letters", label: "HR Letters", icon: "document-text-outline" },
      { route: "/split-view", label: "Split View Compare", icon: "browsers-outline" },
      { route: "/report-formats", label: "PDF Report Formats", icon: "options-outline" },
    ],
  },
  {
    label: "Masters",
    icon: "settings-outline",
    children: [
      { route: "/companies", label: "Company Master", icon: "business-outline" },
      { route: "/admin", label: "Employee Master", icon: "people-outline" },
      { route: "/masters", label: "General Masters", icon: "layers-outline" },
      { route: "/contractor-master", label: "Contractor Master", icon: "people-circle-outline" },
      { route: "/masters?tab=department", label: "Department Master", icon: "business-outline" },
      { route: "/masters?tab=designation", label: "Designation Master", icon: "ribbon-outline" },
      { route: "/masters?tab=holiday", label: "Holiday Master", icon: "calendar-outline" },
      { route: "/masters?tab=allowance", label: "Allowance & Deduction Heads", icon: "cash-outline" },
      { route: "/attendance-master", label: "Shift Master", icon: "time-outline" },
      { route: "/compliance-settings", label: "PF/ESIC Settings", icon: "shield-checkmark-outline" },
      { route: "/sub-admins", label: "User Master (Sub Admins)", icon: "people-circle-outline" },
    ],
  },
  {
    label: "Import / Export",
    icon: "sync-outline",
    children: [
      { route: "/bulk-employee-correction", label: "Bulk Employee Correction", icon: "people-outline" },
      { route: "/bulk-operations", label: "Bulk Operations", icon: "layers-outline" },
      { route: "/employee-bulk-import", label: "Bulk Import (Excel)", icon: "cloud-upload-outline" },
      { route: "/client-attendance-import", label: "Client Attendance Import", icon: "calendar-outline" },
      { route: "/uan-esic-import", label: "Import UAN / ESIC No", icon: "id-card-outline" },
      { route: "/zk-dat-import", label: "Import Biometric (.dat)", icon: "finger-print-outline" },
      { route: "/join-qr", label: "QR Codes (Join / App)", icon: "qr-code-outline" },
      { route: "/sheet-verification", label: "OCR Sheet Verification", icon: "document-attach-outline" },
      { route: "/legacy-explorer", label: "Legacy SQL Explorer", icon: "server-outline" },
      { route: "/legacy-import", label: "Legacy Import Wizard", icon: "download-outline" },
      { route: "/backup-center", label: "Backup Center", icon: "server-outline" },
      { route: "/legacy-salary", label: "Legacy Salary Records", icon: "albums-outline" },
      { route: "/legacy-compare", label: "Legacy vs Current", icon: "git-compare-outline" },
      { route: "/database-backup", label: "Database Backup", icon: "server-outline" },
    ],
  },
  {
    label: "Devices & Integration",
    icon: "hardware-chip-outline",
    children: [
      { route: "/biometric-devices", label: "Biometric Devices (ZKTeco)", icon: "finger-print-outline" },
      { route: "/sync-engine", label: "Device Sync", icon: "sync-outline" },
      { route: "/bi-feed", label: "BI & Data Feed (Power BI / Excel)", icon: "bar-chart-outline" },
      { route: "/database-viewer", label: "Database Viewer / Editor", icon: "server-outline" },
      { route: "/portal-automation", label: "WhatsApp Linking", icon: "logo-whatsapp" },
      { route: "/attendance-email", label: "Email Automation", icon: "mail-outline" },
      { route: "/email-settings", label: "Email SMTP & Notifications", icon: "mail-unread-outline" },
      { route: "/sms-settings", label: "SMS (MSG91)", icon: "chatbox-ellipses-outline" },
    ],
  },
  {
    label: "Communication",
    icon: "mail-outline",
    children: [
      { route: "/mailbox", label: "Mailbox", icon: "mail-outline" },
      { route: "/whatsapp-center", label: "WhatsApp Communication", icon: "logo-whatsapp" },
      { route: "/whatsapp-templates", label: "WhatsApp Templates", icon: "albums-outline" },
      { route: "/messages", label: "Messages", icon: "chatbubbles-outline" },
      { route: "/tickets", label: "Tickets", icon: "ticket-outline" },
    ],
  },
  {
    label: "Administration",
    icon: "construct-outline",
    children: [
      { route: "/access-management", label: "Access Management", icon: "key-outline" },
      { route: "/access-preview", label: "Access Preview", icon: "eye-outline" },
      { route: "/roles-permissions", label: "Roles & Permissions", icon: "options-outline" },
      { route: "/pending-approvals", label: "Pending Approvals", icon: "checkmark-done-outline" },
      { route: "/export-history", label: "Export History", icon: "download-outline" },
      { route: "/security-2fa", label: "Security · 2FA/MFA", icon: "shield-half-outline" },
      { route: "/audit-notifications", label: "Audit Notifications", icon: "notifications-circle-outline" },
      { route: "/whatsapp-config", label: "WhatsApp Configuration", icon: "logo-whatsapp" },
      { route: "/users-log-report", label: "User Log Report", icon: "document-text-outline" },
      { route: "/rectified-punches", label: "Rectified Punch Audit", icon: "shield-checkmark-outline" },
      { route: "/super-admin-access", label: "Super Admin Rights", icon: "star-outline" },
      { route: "/punching-api", label: "API Integration", icon: "cloud-upload-outline" },
      { route: "/proposals", label: "Sales \u00b7 Proposals", icon: "document-text-outline" },
      { route: "/appearance", label: "Appearance / Theme", icon: "color-palette-outline" },
      { route: "/user-manual", label: "User Manual (PDF)", icon: "book-outline" },
    ],
  },
  // User directive — AI Insights lives at the very END of the sidebar.
  { route: "/ai-command-center", label: "AI Command Center", icon: "sparkles" },
  { route: "/ai-payroll-assistant", label: "AI Payroll Assistant", icon: "hardware-chip-outline" },
  { route: "/ai-insights", label: "AI Insights", icon: "sparkles-outline" },
];

// Nav-permission map: which permission key gates which sidebar entry.
// Sub-admins with `read` OR `write` on a permission group see the entry.
const NAV_PERMISSION_MAP: Record<string, string[]> = {
  "/companies": ["companies:read", "companies:write"],
  "/firm-credentials": ["companies:read", "companies:write"],
  "/company-requests": ["company_requests:read", "company_requests:write"],
  "/bulk-employee-correction": ["employees:read", "employees:write"],
  "/bulk-operations": ["employees:write", "salary_process:write"],
  "/kyc-tracker": ["employees:read", "employees:write"],
  "/employee-detail-slip": ["employees:read"],
  "/advances": ["salary_process:read", "salary_process:write"],
  "/attendance-policy": ["attendance_policy:read", "attendance_policy:write"],
  "/punch-approvals": ["punch_approvals:read", "punch_approvals:write"],
  "/attendance-eligibility": ["punch_approvals:read", "punch_approvals:write"],
  "/location-audit": ["punch_approvals:read", "punch_approvals:write"],
  "/geofence-monitor": ["punch_approvals:read", "punch_approvals:write"],
  "/biometric-devices": ["biometric_devices:read", "biometric_devices:write"],
  "/sync-engine": ["biometric_devices:read", "biometric_devices:write"],
  "/attendance-review": ["attendance_review:read", "attendance_review:write"],
  "/salary-run": ["salary_process:read", "salary_process:write"],
  "/salary-register": ["salary_process:read", "salary_process:write"],
  "/arrear-salary-run": ["salary_process:read", "salary_process:write"],
  "/ot-salary-run": ["salary_process:read", "salary_process:write"],
  "/compliance-salary-run": ["compliance_salary:read", "compliance_salary:write"],
  "/esic-leave": ["compliance_salary:read", "compliance_salary:write"],
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
  favSet,
  onToggleFav,
  collapseTick = 0,
}: {
  item: NavItem;
  activeRoute: string;
  pathname: string;
  fullPath: string;
  onNavigate: (route: string) => void;
  depth?: number;
  favSet?: Set<string>;
  onToggleFav?: (route: string) => void;
  collapseTick?: number;
}) {
  const tr = useT();
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
  // Iter 454 (user request) — clicking "Dashboard" collapses ALL expanded
  // sidebar groups (the shell bumps ``collapseTick`` on that click).
  React.useEffect(() => {
    if (collapseTick) setOpen(false);
  }, [collapseTick]);
  const active = !hasChildren && matchesFull(item.route || "");
  const testId = `nav-${(item.route || item.label).replace(/[^a-z0-9]/gi, "-")}`;
  return (
    <>
      <Pressable
        onPress={() => {
          if (hasChildren) {
            setOpen((v) => !v);
          } else if (item.disabled) {
            // Iter 333 (user request) — locked for the current firm.
            const msg =
              "This feature is not available for the current firm.\n\n" +
              "First enable this function (Firm Master / Access Rights) " +
              "or change the firm.";
            if (Platform.OS === "web" && typeof window !== "undefined") {
              window.alert(msg);
            }
          } else if (item.route) {
            onNavigate(item.route);
          }
        }}
        style={({ hovered }: any) => [
          {
            flexDirection: "row",
            alignItems: "center",
            gap: 12,
            paddingVertical: active ? 12 : 10,
            paddingHorizontal: 16 + depth * 12,
            borderRadius: 8,
            marginBottom: 2,
            opacity: item.disabled ? 0.45 : 1,
            // Iter 293 (user spec) — dark sidebar: active #2563EB, hover
            // #1D4ED8, otherwise transparent.
            backgroundColor: active ? SB.active : hovered ? SB.hover : "transparent",
            borderLeftWidth: active ? 3 : 0,
            borderLeftColor: active ? SB.linkLight : "transparent",
          },
        ]}
        testID={testId}
      >
        <Ionicons
          name={item.icon}
          size={active ? 20 : 18}
          color={active ? "#FFFFFF" : childActive ? SB.linkLight : SB.muted}
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
              : (childActive ? "#FFFFFF" : SB.text),
            textTransform: "none",
          }}
        >
          {tr(item.label)}
        </Text>
        {!hasChildren && item.disabled ? (
          <Ionicons name="lock-closed" size={12} color="rgba(148,163,184,0.7)" />
        ) : null}
        {!hasChildren && !item.disabled && item.route && onToggleFav ? (
          <Pressable
            hitSlop={6}
            onPress={(e: any) => { e?.stopPropagation?.(); onToggleFav(item.route!); }}
            testID={`fav-${testId}`}
          >
            <Ionicons
              name={favSet?.has(item.route) ? "star" : "star-outline"}
              size={13}
              color={favSet?.has(item.route) ? "#F59E0B" : "rgba(148,163,184,0.4)"}
            />
          </Pressable>
        ) : null}
        {hasChildren ? (
          <Ionicons
            name={open ? "chevron-down" : "chevron-forward"}
            size={16}
            color={SB.muted}
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
              fullPath={fullPath}
              onNavigate={onNavigate}
              depth={depth + 1}
              favSet={favSet}
              onToggleFav={onToggleFav}
              collapseTick={collapseTick}
            />
          ))}
        </View>
      ) : null}
    </>
  );
}


export const NAV_COMPANY_ADMIN: NavItem[] = [
  // Iter 293 (user spec) — 12-module sidebar reorganisation (Company Admin
  // subset; Appearance stays Super-Admin-only).
  { route: "/portal-dashboard", label: "Dashboard", icon: "home-outline" },
  {
    label: "Employees",
    icon: "people-outline",
    children: [
      { route: "/employee-add", label: "Add New Employee", icon: "person-add-outline" },
      { route: "/admin", label: "All Employee Data", icon: "people-outline" },
      { route: "/employee-detail-slip", label: "Employee Detail Slip", icon: "id-card-outline" },
      { route: "/kyc-tracker", label: "KYC & Doc Expiry Tracker", icon: "id-card-outline" },
      { route: "/employee-reports", label: "Employee Reports Hub", icon: "documents-outline" },
      { route: "/employee-report", label: "Employee Report", icon: "people-outline" },
    ],
  },
  {
    label: "Attendance & Shift",
    icon: "time-outline",
    children: [
      { route: "/attendance-policy", label: "Attendance Policy", icon: "time-outline" },
      { route: "/attendance-grid", label: "Attendance Report", icon: "grid-outline" },
      { route: "/attendance-sync-dashboard", label: "Attendance Sync Dashboard", icon: "sync-outline" },
      { route: "/inout-ot-matrix", label: "In/Out & OT Matrix", icon: "apps-outline" },
      { route: "/present-absent-report", label: "Present / Absent Report", icon: "checkbox-outline" },
      { route: "/daily-present-report", label: "Day-wise Present Count", icon: "people-outline" },
      { route: "/geofence-policy", label: "Geofence Policy", icon: "location-outline" },
      { route: "/geofence-monitor", label: "Geofence Monitor", icon: "navigate-circle-outline" },
      { route: "/location-audit", label: "Location Audit", icon: "navigate-outline" },
    ],
  },
  {
    label: "Payroll",
    icon: "cash-outline",
    children: [
      {
        label: "Salary Process",
        icon: "cash-outline",
        children: [
          { route: "/salary-run", label: "Actual Salary", icon: "cash-outline" },
          { route: "/compliance-salary-run", label: "Compliance Salary", icon: "briefcase-outline" },
          { route: "/esic-leave", label: "ESIC Leave", icon: "medkit-outline" },
          { route: "/ot-salary-run", label: "OT Salary", icon: "flash-outline" },
          { route: "/arrear-salary-run", label: "Arrear Salary", icon: "time-outline" },
          { route: "/salary-register", label: "Salary Register", icon: "grid-outline" },
          { route: "/ctc-management", label: "CTC Management", icon: "layers-outline" },
          { route: "/form16", label: "TDS · Form 16", icon: "document-text-outline" },
        ],
      },
      { route: "/advances", label: "Advance Management", icon: "wallet-outline" },
      { route: "/bonus-yearly-summary", label: "Bonus Yearly Summary", icon: "calendar-outline" },
      { route: "/payroll-register", label: "Yearly Payroll Register", icon: "grid-outline" },
      { route: "/ai-universal-import", label: "AI Universal Import", icon: "sparkles-outline" },
      { route: "/ai-salary-compliance", label: "Salary Compliance Process (AI)", icon: "calculator-outline" },
      { route: "/labour-statistics", label: "Labour Statistics & HR Analytics", icon: "stats-chart-outline" },
      { route: "/annual-returns", label: "Annual Returns", icon: "document-text-outline" },
      { route: "/factory-compliance", label: "Factory & Boilers", icon: "business-outline" },
      { route: "/salary-day-sheet", label: "Day-wise Salary Sheet", icon: "calendar-outline" },
      { route: "/reports?tab=salary", label: "Actual Salary Report", icon: "cash-outline" },
      { route: "/reports?tab=compliance", label: "Compliance Report", icon: "shield-checkmark-outline" },
      { route: "/bank-sheet", label: "Bank Sheet Format", icon: "card-outline" },
      { route: "/bank-transfer", label: "Bank Transfer Files", icon: "business-outline" },
      { route: "/leave-report", label: "Leave Report", icon: "calendar-number-outline" },
      { route: "/comp-off-ledger", label: "Comp-Off Ledger", icon: "time-outline" },
      { route: "/statutory-reports", label: "Full & Final Settlement", icon: "receipt-outline" },
    ],
  },
  {
    label: "Compliance",
    icon: "shield-checkmark-outline",
    children: [
      { route: "/pf-reports?kind=pf", label: "PF Reports", icon: "briefcase-outline" },
      { route: "/pf-reports?kind=esic", label: "ESIC Reports", icon: "medkit-outline" },
      { route: "/claims-management", label: "PF & ESIC Claims", icon: "folder-open-outline" },
      { route: "/statutory-reports", label: "PT / LWF / Gratuity / MIS", icon: "receipt-outline" },
      { route: "/factory-annual-return", label: "Factory & Boiler Annual Return", icon: "business-outline" },
      { route: "/challan-summary", label: "Monthly Challan Summary", icon: "documents-outline" },
    ],
  },
  {
    label: "Approvals & Workflow",
    icon: "checkmark-done-circle-outline",
    children: [
      { route: "/approval-inbox", label: "Approval Inbox", icon: "file-tray-full-outline" },
      { route: "/approval-workflows", label: "Workflow Builder", icon: "git-branch-outline" },
      { route: "/shift-change-admin", label: "Shift Change Approval", icon: "swap-horizontal" },
      { route: "/attendance-approvals", label: "Attendance Approval", icon: "hand-right-outline" },
      { route: "/punch-approvals", label: "Punch Approval", icon: "checkmark-circle-outline" },
      { route: "/attendance-eligibility", label: "Attendance Eligibility", icon: "shield-checkmark-outline" },
      { route: "/contractor-punches", label: "Contractor Punches", icon: "briefcase-outline" },
      { route: "/deletion-approvals", label: "Deletion Approval", icon: "trash-bin-outline" },
      { route: "/attendance-review", label: "Attendance Review", icon: "shield-checkmark-outline" },
      { route: "/roles", label: "User Rights (Roles)", icon: "key-outline" },
    ],
  },
  {
    label: "Reports",
    icon: "bar-chart-outline",
    children: [
      { route: "/reports-center", label: "Report Hub", icon: "library-outline" },
      { route: "/monthly-payroll-report", label: "Monthly Payroll Report", icon: "calendar-number-outline" },
      { route: "/labour-reports", label: "Labour Reports", icon: "documents-outline" },
      { route: "/labour-cost-dashboard", label: "Labour Cost Dashboard", icon: "trending-up-outline" },
      { route: "/attendance-grid", label: "Attendance Reports", icon: "grid-outline" },
      { route: "/daily-verification", label: "Daily In/Out & OT Verification", icon: "checkbox-outline" },
      { route: "/multi-punch-report", label: "Multiple Punch Report", icon: "repeat-outline" },
      { route: "/attendance-sync-dashboard", label: "Attendance Sync Dashboard", icon: "sync-outline" },
      { route: "/reports?tab=salary", label: "Payroll Reports", icon: "cash-outline" },
      { route: "/employee-reports", label: "Employee Reports", icon: "documents-outline" },
      { route: "/compliance-reports", label: "Compliance Reports", icon: "shield-checkmark-outline" },
      { route: "/reports?tab=bonus", label: "Bonus Reports", icon: "gift-outline" },
      { route: "/master-data-report", label: "Employee Master Report", icon: "server-outline" },
      { route: "/hr-letters", label: "HR Letters", icon: "document-text-outline" },
    ],
  },
  {
    label: "Masters",
    icon: "settings-outline",
    children: [
      { route: "/masters", label: "General Masters", icon: "layers-outline" },
      { route: "/contractor-master", label: "Contractor Master", icon: "people-circle-outline" },
      { route: "/masters?tab=department", label: "Department Master", icon: "business-outline" },
      { route: "/masters?tab=designation", label: "Designation Master", icon: "ribbon-outline" },
      { route: "/masters?tab=holiday", label: "Holiday Master", icon: "calendar-outline" },
      { route: "/masters?tab=allowance", label: "Allowance & Deduction Heads", icon: "cash-outline" },
    ],
  },
  {
    label: "Import / Export",
    icon: "sync-outline",
    children: [
      { route: "/bulk-employee-correction", label: "Bulk Employee Correction", icon: "people-outline" },
      { route: "/employee-bulk-import", label: "Bulk Import (Excel)", icon: "cloud-upload-outline" },
      { route: "/client-attendance-import", label: "Client Attendance Import", icon: "calendar-outline" },
      { route: "/uan-esic-import", label: "Import UAN / ESIC No", icon: "id-card-outline" },
      { route: "/zk-dat-import", label: "Import Biometric (.dat)", icon: "finger-print-outline" },
      { route: "/legacy-explorer", label: "Legacy SQL Explorer", icon: "server-outline" },
      { route: "/legacy-import", label: "Legacy Import Wizard", icon: "download-outline" },
      { route: "/backup-center", label: "Backup Center", icon: "server-outline" },
      { route: "/legacy-salary", label: "Legacy Salary Records", icon: "albums-outline" },
      { route: "/legacy-compare", label: "Legacy vs Current", icon: "git-compare-outline" },
      { route: "/join-qr", label: "QR Codes (Join / App)", icon: "qr-code-outline" },
    ],
  },
  {
    label: "Devices & Integration",
    icon: "hardware-chip-outline",
    children: [
      { route: "/biometric-devices", label: "Biometric Devices", icon: "finger-print-outline" },
      { route: "/sync-engine", label: "Device Sync", icon: "sync-outline" },
    ],
  },
  {
    label: "Communication",
    icon: "mail-outline",
    children: [
      { route: "/messages", label: "Messages", icon: "chatbubbles-outline" },
      { route: "/tickets", label: "Tickets", icon: "ticket-outline" },
    ],
  },
  { route: "/proposals", label: "Sales \u00b7 Proposals", icon: "document-text-outline" },
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
  // Iter 333 (user request) — feature not enabled for the CURRENT firm:
  // the entry stays visible but locked; clicking shows a message instead
  // of navigating.
  disabled?: boolean;
};

type Props = { children: React.ReactNode };

export default function AdminWebShell({ children }: Props) {
  const { user, logout, refresh } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const { width } = useWindowDimensions();
  const { refreshedAt, bumpRefresh } = useRefreshBus();
  const { selectedCompany, clearLock } = useSelectedCompany();
  // Staff-portal switch — when an employee opened the staff portal from
  // their PWA (Profile → Staff Access), a backup of their employee token
  // exists; show a "Back to Employee App" button that restores it.
  const [empBackup, setEmpBackup] = React.useState<string | null>(null);
  React.useEffect(() => {
    readEmployeeTokenBackup().then(setEmpBackup).catch(() => {});
  }, []);
  const backToEmployeeApp = React.useCallback(async () => {
    if (!empBackup) return;
    await saveToken(empBackup);
    await clearEmployeeTokenBackup();
    setEmpBackup(null);
    await refresh();
    router.replace("/");
  }, [empBackup, refresh, router]);
  // Iter 85 — Logout button opens a small confirmation modal with TWO
  // choices for super/sub admins: fully sign out, or just switch firm
  // (clear the selection so they can pick another firm from the picker
  // without re-entering credentials).
  const [logoutModal, setLogoutModal] = React.useState(false);
  // Iter 89 — Notifications bell + unread badge for the admin header.
  const { unreadCount: unreadNotifCount, items: notifItems, markAllSeen } = useUnreadNotifications();
  // Iter 180 — global menu search + dark mode toggle.
  const [navQuery, setNavQuery] = React.useState("");
  const { themeId, setThemeId } = useTheme();
  // Iter 294 — productivity suite: favourites, recent screens, AI panel,
  // notification centre, keyboard shortcuts, language + data-wide search.
  const tr = useT();
  const lang = useLang();
  const [favs, setFavs] = React.useState<string[]>(() => readNavList(FAV_KEY));
  const [, setRecent] = React.useState<string[]>(() => readNavList(RECENT_KEY));
  const [aiOpen, setAiOpen] = React.useState(false);
  const [notifOpen, setNotifOpen] = React.useState(false);
  const [helpOpen, setHelpOpen] = React.useState(false);
  // Iter 461 (Phase 2/3) — cross-tab real-time sync toast + status bar.
  const [syncToast, setSyncToast] = React.useState<{ entity?: string; name?: string } | null>(null);
  const [wsOnline, setWsOnline] = React.useState(true);
  const [lastSync, setLastSync] = React.useState("");
  // Iter 471 (user request) — server version badge in the status bar so
  // the user can confirm the server is running the latest deploy.
  const [serverIter, setServerIter] = React.useState("");
  React.useEffect(() => {
    api<{ iteration?: string }>("/version")
      .then((r) => setServerIter(String(r?.iteration || "")))
      .catch(() => setServerIter(""));
  }, []);
  React.useEffect(() => {
    const off = onSyncMessage((m) => {
      if (m.type === "record-updated") {
        setSyncToast({ entity: m.entity, name: m.name });
        setLastSync(new Date().toLocaleTimeString());
      }
    });
    if (Platform.OS === "web" && typeof window !== "undefined") {
      const on = () => setWsOnline(true);
      const offl = () => setWsOnline(false);
      setWsOnline(typeof navigator !== "undefined" ? navigator.onLine !== false : true);
      window.addEventListener("online", on);
      window.addEventListener("offline", offl);
      return () => { off(); window.removeEventListener("online", on); window.removeEventListener("offline", offl); };
    }
    return off;
  }, []);
  React.useEffect(() => {
    if (!syncToast) return;
    const t = setTimeout(() => setSyncToast(null), 15000);
    return () => clearTimeout(t);
  }, [syncToast]);
  // Iter 454 (user request) — clicking "Dashboard" hides all expanded
  // sidebar sub-points; the tick is broadcast to every NavRow group.
  const [collapseTick, setCollapseTick] = React.useState(0);
  // Iter 306 (user #13) — pin/hide the sidebar (persisted per browser).
  const [sbHidden, setSbHidden] = React.useState<boolean>(() => {
    try { return (globalThis as any).localStorage?.getItem("sks_sidebar_hidden") === "1"; }
    catch { return false; }
  });
  const toggleSidebar = () => setSbHidden((h) => {
    const n = !h;
    try { (globalThis as any).localStorage?.setItem("sks_sidebar_hidden", n ? "1" : "0"); }
    catch { /* noop */ }
    return n;
  });
  const [gsData, setGsData] = React.useState<{ employees: any[]; companies: any[] } | null>(null);
  const searchInputRef = React.useRef<TextInput | null>(null);
  const favSet = React.useMemo(() => new Set(favs), [favs]);
  const toggleFav = React.useCallback((route: string) => {
    setFavs((prev) => {
      const next = prev.includes(route) ? prev.filter((r) => r !== route) : [route, ...prev];
      writeNavList(FAV_KEY, next);
      return next;
    });
  }, []);

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
  // Iter 587 — Maker-Checker pending-approvals badge (header). Checkers
  // instantly see how many requests await them; click opens the queue.
  const [pendingApprovals, setPendingApprovals] = React.useState(0);
  React.useEffect(() => {
    if (!isWebDesktop || !(role === "super_admin" || role === "sub_admin" || role === "company_admin")) return;
    let alive = true;
    const fetchCount = () => {
      api<{ pending_count: number }>("/admin/approvals?status=PENDING")
        .then((r) => { if (alive) setPendingApprovals(r?.pending_count || 0); })
        .catch(() => { if (alive) setPendingApprovals(0); });
    };
    fetchCount();
    const t = setInterval(fetchCount, 60000);
    return () => { alive = false; clearInterval(t); };
    // refreshedAt/pathname: re-check on global Refresh + screen changes.
  }, [isWebDesktop, role, refreshedAt, pathname]);

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
        if (r === "/punching-api") return false;
        // Iter 212 — user directive: Sub Super Admins get ALL features.
        // (Previously-hidden entries below are now allowed; per-button
        // menu_rights set by the super admin still apply above.)
        // Iter 85 — Appearance / Theme switching is Super-Admin-only.
        if (r === "/appearance") return false;
        if (r === "/attendance-email") return true;
        if (r === "/bulk-employee-correction") return true;
        if (r === "/bonus-run") return true;
        if (r === "/(tabs)") return true;
        // Iter 212 — user directive: Sub Super Admins see ALL features.
        // The permission matrix no longer hides menus; only explicit
        // per-button menu_rights[route] === false (handled above) and the
        // platform-admin screens stay hidden.
        return true;
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
        "/salary-register",
      ]);
      const empPerms: string[] = (user as any)?.employer_permissions || [];
      const permSet = new Set(empPerms);
      // Iter 93 — per-sidebar-button gating set from Access Rights.
      // menu_rights[route] === false hides the button; missing == allowed.
      const menuRights: Record<string, boolean> =
        (user as any)?.menu_rights || {};
      const menuAllowed = (item: NavItem) =>
        menuRights[item.route || ""] !== false;
      // RBAC Phase 1 — company_staff (normalized company_admin) are gated
      // by their role's permission matrix; Roles & Permissions itself is
      // for real admins only.
      const isStaff = !!(user as any)?.is_company_staff;
      const staffPerms = new Set<string>(((user as any)?.staff_permissions || []) as string[]);
      const staffAllowed = (item: NavItem) => {
        if (!isStaff) return true;
        const r = (item.route || "").split("?")[0];
        if (r === "/roles" || r === "/approval-workflows") return false;
        if (r === "/approval-inbox") return true;
        if (r === "/(tabs)") return true;
        const gates = NAV_PERMISSION_MAP[r];
        if (!gates || gates.length === 0) return true;
        return gates.some((g) => staffPerms.has(g));
      };
      const hasComplianceGrant =
        permSet.has("compliance_salary:read") ||
        permSet.has("compliance_salary:write");
      const hasSalaryGrant =
        permSet.has("salary_process:read") ||
        permSet.has("salary_process:write");
      // Iter 333 (user request) — features the FIRM doesn't have are no
      // longer HIDDEN: they stay in the sidebar as LOCKED entries and
      // clicking shows "not available for the current firm" instead.
      const firmAllowed = (item: NavItem) => {
        const r = (item.route || "").split("?")[0];
        if (r === "/(tabs)") return true;
        if (COMPLIANCE_ROUTES.has(r)) return hasComplianceGrant;
        if (SALARY_ROUTES.has(r)) return hasSalaryGrant;
        if (empPerms.length === 0) return true;
        const gates = NAV_PERMISSION_MAP[r];
        if (!gates || gates.length === 0) return true;
        return gates.some((g) => permSet.has(g));
      };
      const mark = (items: NavItem[]): NavItem[] => {
        const out: NavItem[] = [];
        for (const it of items) {
          if (it.children && it.children.length > 0) {
            const kids = mark(it.children);
            if (kids.length > 0) out.push({ ...it, children: kids });
            continue;
          }
          // Explicit per-button rights / staff RBAC still HIDE entries.
          if (!menuAllowed(it) || !staffAllowed(it)) continue;
          out.push(firmAllowed(it) ? it : { ...it, disabled: true });
        }
        return out;
      };
      return mark(NAV_COMPANY_ADMIN);
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
    // Iter 333 (user request) — LOCK instead of hide: the entry stays in
    // the sidebar; clicking shows "not available for the current firm".
    const mark = (items: NavItem[]): NavItem[] => {
      const out: NavItem[] = [];
      for (const it of items) {
        if (it.children && it.children.length > 0) {
          out.push({ ...it, children: mark(it.children) });
          continue;
        }
        if (HIDE.has((it.route || "").split("?")[0])) {
          out.push({ ...it, disabled: true });
        } else {
          out.push(it);
        }
      }
      return out;
    };
    return mark(nav);
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

  // Iter 499 (user request) — search MENU POINTS, SUB-POINTS *and* REPORTS.
  // Sub-points carry their parent section so the query also matches the
  // section name (e.g. "compliance" lists every compliance sub-point).
  const flatNavDeep = useMemo(() => {
    const out: { item: NavItem; parent: string }[] = [];
    const walk = (items: NavItem[], parent: string) => {
      for (const it of items) {
        if (it.route) out.push({ item: it, parent });
        if (it.children) walk(it.children, parent ? `${parent} › ${it.label}` : it.label);
      }
    };
    walk(gatedNav, "");
    return out;
  }, [gatedNav]);

  // Report-Hub inner reports (payroll / govt / CLRA / audit kinds) — lazily
  // fetched the first time the user types in the search box.
  const [repCat, setRepCat] = React.useState<{ kind: string; title: string; group: string }[] | null>(null);
  React.useEffect(() => {
    if (!navQuery.trim() || repCat !== null) return;
    setRepCat([]); // guard against duplicate fetches
    (async () => {
      const all: { kind: string; title: string; group: string }[] = [];
      const srcs: [string, string, string][] = [
        ["/admin/payroll-reports/list", "reports", "payroll"],
        ["/admin/govt-registers/list", "registers", "govt"],
        ["/admin/clra-reports/list", "reports", "clra"],
        ["/admin/audit-reports/list", "reports", "audit"],
      ];
      for (const [url, key, group] of srcs) {
        try {
          const r = await api<any>(url);
          (r[key] || []).forEach((x: any) =>
            all.push({ kind: x.kind, title: x.title, group }));
        } catch { /* endpoint gated for this role — skip */ }
      }
      setRepCat(all);
    })();
  }, [navQuery, repCat]);

  // RBAC Phase 2 — FRONTEND ROUTE PROTECTION. Hiding a sidebar button is
  // not enough: a staff/sub-admin user could type the URL directly. Any
  // route that exists in the master nav universe but is NOT in this user's
  // permission-filtered nav is denied. Super admins are never gated.
  const routeDenied = useMemo(() => {
    if (role === "super_admin") return false as false | "denied" | "firm";
    const base = (r?: string) => (r || "").split("?")[0];
    const collect = (items: NavItem[], into: Set<string>, skipDisabled = false) => {
      for (const it of items) {
        if (it.route && !(skipDisabled && it.disabled)) into.add(base(it.route));
        if (it.children) collect(it.children, into, skipDisabled);
      }
    };
    const universe = new Set<string>();
    collect(NAV_SUPER, universe);
    collect(NAV_COMPANY_ADMIN, universe);
    universe.delete("/(tabs)");
    // Which universe base does the current path fall under? (longest match)
    let hit: string | null = null;
    for (const u of universe) {
      if (pathname === u || pathname.startsWith(`${u}/`)) {
        if (!hit || u.length > hit.length) hit = u;
      }
    }
    if (!hit) return false; // not a nav-gated page (detail/dynamic route)
    const allowed = new Set<string>();
    // Guard on the permission-filtered nav (`nav`), not the business-flow
    // pruned `gatedNav`, so firm salary toggles never lock admins out.
    collect(nav, allowed, true);
    if (allowed.has(hit)) return false;
    // Iter 333 — present in the nav but LOCKED for the current firm?
    const present = new Set<string>();
    collect(nav, present, false);
    return present.has(hit) ? "firm" : "denied";
  }, [role, nav, pathname]);

  // Iter 294 — track recently-opened screens (web desktop only).
  useEffect(() => {
    if (Platform.OS !== "web" || !isWebDesktop) return;
    if (!pathname || pathname === "/" || pathname === "/firm-select" || pathname === "/portal-dashboard") return;
    const hit = flatNav.find((n) => (n.route || "").split("?")[0] === pathname);
    if (!hit?.route) return;
    setRecent((prev) => {
      const next = [hit.route!, ...prev.filter((r) => r !== hit.route)].slice(0, 6);
      writeNavList(RECENT_KEY, next);
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, isWebDesktop]);

  // Iter 294 — ERP keyboard shortcuts (web only). Ctrl+K search,
  // Ctrl+Shift+A AI assistant, ? help, g-then-key navigation.
  useEffect(() => {
    if (Platform.OS !== "web" || !isWebDesktop) return;
    let lastG = 0;
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      const typing = tag === "input" || tag === "textarea" || tag === "select";
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        (searchInputRef.current as any)?.focus?.();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "a") {
        e.preventDefault();
        setAiOpen((v) => !v);
        return;
      }
      if (typing) return;
      if (e.key === "?") { setHelpOpen((v) => !v); return; }
      if (e.key === "Escape") { setHelpOpen(false); setNotifOpen(false); return; }
      if (e.key.toLowerCase() === "g") { lastG = Date.now(); return; }
      if (Date.now() - lastG < 1500) {
        const map: Record<string, string> = {
          d: "/portal-dashboard", e: "/admin", a: "/attendance-grid",
          p: "/salary-run", r: "/reports?tab=salary", c: "/compliance-reports",
          b: "/bank-transfer", m: "/masters", i: "/ai-payroll-assistant",
        };
        const r = map[e.key.toLowerCase()];
        if (r) router.push(r as any);
        lastG = 0;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isWebDesktop]);

  // Iter 294 — data-wide global search (employees + firms) with debounce.
  useEffect(() => {
    const q = navQuery.trim();
    if (q.length < 2) { setGsData(null); return; }
    const t = setTimeout(() => {
      api<{ employees: any[]; companies: any[] }>(
        `/admin/global-search?q=${encodeURIComponent(q)}`)
        .then(setGsData)
        .catch(() => setGsData(null));
    }, 300);
    return () => clearTimeout(t);
  }, [navQuery]);

  // Iter 294 — embed mode (?embed=1): bare children for Split View iframes.
  const isEmbed =
    Platform.OS === "web" && typeof window !== "undefined" &&
    window.location.search.includes("embed=1");

  // IMPORTANT (Iter 197) — the Stack navigator lives inside {children}. If
  // we return it bare in one branch and nested inside shell chrome in
  // another, React REMOUNTS the navigator when auth finishes bootstrapping,
  // which RESETS navigation state to the index route and clobbers direct
  // URLs (deep links like /salary-run bounced to /portal-dashboard). Render
  // a skeleton with IDENTICAL nesting positions so children never remount.
  if (!isWebDesktop || !user || isBareRoute || isEmbed) {
    return (
      <View style={{ flex: 1 }}>
        {null}
        <View style={{ flex: 1 }}>
          {null}
          <View style={{ flex: 1 }}>
            <View style={{ flex: 1 }}>{children}</View>
            {null}
          </View>
        </View>
        {null}
      </View>
    );
  }

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

  const fullPath =
    Platform.OS === "web" && typeof window !== "undefined"
      ? pathname + (window.location.search || "").replace(/[?&]embed=1/, "")
      : pathname;

  const navigateTo = (route: string) => {
    if ((route || "").split("?")[0] === "/portal-dashboard") {
      setCollapseTick((t) => t + 1);
    }
    router.push((route === "/(tabs)" ? "/" : route) as any);
  };

  // Iter 461 (Phase 1) — workspace-tab labels resolved from the nav tree.
  const wsLabelFor = (path: string) => {
    const base = (path || "").split("?")[0];
    const find = (items: NavItem[]): string | null => {
      for (const it of items) {
        const r = (it.route || "").split("?")[0];
        if (r && (base === r || base.startsWith(`${r}/`))) return it.label;
        if (it.children) { const f = find(it.children); if (f) return f; }
      }
      return null;
    };
    const seg = base.replace(/^\//, "").split("/")[0];
    return find(nav)
      || (seg ? seg.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Home");
  };

  // Iter 461 (Phase 2) — "Refresh Now" remounts the current screen so it
  // refetches fresh data (no full page reload).
  const wsRefreshNow = () => {
    setSyncToast(null);
    if (typeof window !== "undefined") {
      const p = window.location.pathname + (window.location.search || "");
      router.replace((p + (p.includes("?") ? "&" : "?") + "_r=" + Date.now()) as any);
    }
  };

  return (
    <View style={styles.shell} testID="admin-web-shell">
      {/* Sidebar — Iter 306 (user #13): collapsible via the pin button. */}
      {sbHidden ? (
        <View style={styles.sidebarRail}>
          <Pressable onPress={toggleSidebar} style={styles.railBtn} testID="sidebar-show">
            <Ionicons name="menu-outline" size={20} color="#fff" />
          </Pressable>
        </View>
      ) : (
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
          {/* Iter 306 (user #13) — hide the sidebar. */}
          <Pressable
            onPress={toggleSidebar}
            style={styles.railBtnSm}
            testID="sidebar-hide"
            hitSlop={6}
          >
            <Ionicons name="chevron-back-outline" size={15} color={SB.linkLight} />
          </Pressable>
        </View>

        {/* Iter 85 pt 3 — Active Firm pill. Always visible under the logo
            block so admins never lose sight of the firm scope they're
            operating in. Iter 306 (user #15) — READ-ONLY: switching firms
            from here is no longer allowed (use the header firm picker). */}
        {selectedCompany ? (
          <View style={styles.firmPill} testID="sidebar-active-firm">
            <View style={styles.firmPillIcon}>
              <Ionicons name="business-outline" size={12} color="#fff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.firmPillLabel}>ACTIVE FIRM</Text>
              <Text style={styles.firmPillName} numberOfLines={1}>
                {selectedCompany.name}
              </Text>
            </View>
            <Ionicons name="lock-closed-outline" size={13} color={SB.linkLight} />
          </View>
        ) : null}

        <View style={styles.divider} />

        <ScrollView
          style={styles.navScroll}
          contentContainerStyle={{ paddingBottom: 12 }}
          showsVerticalScrollIndicator={true}
          persistentScrollbar={true}
        >
          {/* Iter 294 — Pinned favourites + recently-opened sections. */}
          {favs.length > 0 ? (
            <>
              <Text style={styles.navSection}>★ {tr("Favourites")}</Text>
              {favs.map((r) => {
                const item = flatNav.find((n) => n.route === r);
                if (!item) return null;
                return (
                  <NavRow
                    key={`fav-${r}`}
                    item={item}
                    activeRoute={activeRoute}
                    pathname={pathname}
                    fullPath={fullPath}
                    onNavigate={navigateTo}
                    favSet={favSet}
                    onToggleFav={toggleFav}
                    collapseTick={collapseTick}
                  />
                );
              })}
              <View style={styles.divider} />
            </>
          ) : null}
          {gatedNav.map((item, idx) => (
            <NavRow
              key={item.route || `${item.label}-${idx}`}
              item={item}
              activeRoute={activeRoute}
              pathname={pathname}
              fullPath={fullPath}
              onNavigate={navigateTo}
              favSet={favSet}
              onToggleFav={toggleFav}
              collapseTick={collapseTick}
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
      )}

      {/* Main pane */}
      <View style={styles.mainWrap}>
        <View style={styles.topBar}>
          <Text style={styles.pageTitle}>
            {flatNav.find((n) => n.route === activeRoute)?.label || "Workspace"}
          </Text>
          {/* Iter 180 — Global search over portal screens. */}
          <View style={styles.gsWrap}>
            <View style={styles.gsBox}>
              <Ionicons name="search-outline" size={14} color={colors.onSurfaceTertiary} />
              <TextInput
                ref={searchInputRef as any}
                style={styles.gsInput}
                placeholder={tr("Search menu… (clients, payroll, reports)")}
                placeholderTextColor={colors.onSurfaceTertiary}
                value={navQuery}
                onChangeText={setNavQuery}
                testID="web-global-search"
              />
              {navQuery ? (
                <Pressable onPress={() => setNavQuery("")} hitSlop={6}>
                  <Ionicons name="close-circle" size={14} color={colors.onSurfaceTertiary} />
                </Pressable>
              ) : null}
            </View>
            {navQuery.trim() ? (
              <View style={styles.gsResults}>
                {/* Iter 499 — menu points + SUB-POINTS (matches item OR its
                    parent section) with the section path shown under each */}
                {flatNavDeep
                  .filter(({ item, parent }) => !item.disabled &&
                    (`${item.label} ${parent}`).toLowerCase()
                      .includes(navQuery.trim().toLowerCase()))
                  .slice(0, 9)
                  .map(({ item: n, parent }) => (
                    <Pressable
                      key={n.route}
                      onPress={() => { setNavQuery(""); router.push(n.route as any); }}
                      style={({ hovered }: any) => [
                        styles.gsItem, hovered && { backgroundColor: colors.surfaceTertiary }]}
                      testID={`gs-result-${n.route.slice(1)}`}
                    >
                      <Ionicons name={(n as any).icon || "chevron-forward"} size={14}
                        color={colors.brandPrimary} />
                      <View style={{ flex: 1, minWidth: 0 }}>
                        <Text style={styles.gsItemTxt} numberOfLines={1}>{n.label}</Text>
                        {parent ? (
                          <Text style={styles.gsItemSub} numberOfLines={1}>{parent}</Text>
                        ) : null}
                      </View>
                    </Pressable>
                  ))}
                {/* Iter 499 — REPORT-HUB inner reports are searchable too */}
                {(repCat || [])
                  .filter((r) => r.title.toLowerCase()
                    .includes(navQuery.trim().toLowerCase()))
                  .slice(0, 6)
                  .map((r) => (
                    <Pressable
                      key={`rep-${r.group}-${r.kind}`}
                      onPress={() => {
                        setNavQuery("");
                        router.push(`/reports-center?kind=${encodeURIComponent(r.kind)}` as any);
                      }}
                      style={({ hovered }: any) => [
                        styles.gsItem, hovered && { backgroundColor: colors.surfaceTertiary }]}
                      testID={`gs-report-${r.kind}`}
                    >
                      <Ionicons name="document-text-outline" size={14} color="#B45309" />
                      <View style={{ flex: 1, minWidth: 0 }}>
                        <Text style={styles.gsItemTxt} numberOfLines={1}>{r.title}</Text>
                        <Text style={styles.gsItemSub} numberOfLines={1}>
                          Report Hub › {r.group.toUpperCase()}
                        </Text>
                      </View>
                    </Pressable>
                  ))}
                {/* Iter 294 — data-wide results: employees + firms. */}
                {gsData?.employees?.length ? (
                  <>
                    <Text style={styles.gsSection}>EMPLOYEES</Text>
                    {gsData.employees.map((e: any) => (
                      <Pressable
                        key={e.user_id}
                        onPress={() => { setNavQuery(""); router.push("/admin" as any); }}
                        style={({ hovered }: any) => [
                          styles.gsItem, hovered && { backgroundColor: colors.surfaceTertiary }]}
                        testID={`gs-emp-${e.employee_code}`}
                      >
                        <Ionicons name="person-outline" size={14} color="#22C55E" />
                        <View style={{ flex: 1 }}>
                          <Text style={styles.gsItemTxt}>{e.name} · {e.employee_code}</Text>
                          <Text style={styles.gsItemSub}>
                            {[e.designation, e.firm_name].filter(Boolean).join(" — ")}
                          </Text>
                        </View>
                      </Pressable>
                    ))}
                  </>
                ) : null}
                {gsData?.companies?.length ? (
                  <>
                    <Text style={styles.gsSection}>FIRMS</Text>
                    {gsData.companies.map((c: any) => (
                      <Pressable
                        key={c.company_id}
                        onPress={() => { setNavQuery(""); router.push("/companies" as any); }}
                        style={({ hovered }: any) => [
                          styles.gsItem, hovered && { backgroundColor: colors.surfaceTertiary }]}
                        testID={`gs-firm-${c.company_id}`}
                      >
                        <Ionicons name="business-outline" size={14} color="#F59E0B" />
                        <Text style={styles.gsItemTxt}>{c.name}{c.code ? ` (${c.code})` : ""}</Text>
                      </Pressable>
                    ))}
                  </>
                ) : null}
                {flatNavDeep.filter(({ item, parent }) => (`${item.label} ${parent}`).toLowerCase().includes(navQuery.trim().toLowerCase())).length === 0 &&
                 !(repCat || []).some((r) => r.title.toLowerCase().includes(navQuery.trim().toLowerCase())) &&
                 !gsData?.employees?.length && !gsData?.companies?.length ? (
                  <Text style={styles.gsEmpty}>No screens match “{navQuery.trim()}”</Text>
                ) : null}
              </View>
            ) : null}
          </View>
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
            {/* Iter 587 — Pending Approvals badge (Maker-Checker queue). */}
            {(role === "super_admin" || role === "sub_admin" || role === "company_admin")
              && pendingApprovals > 0 ? (
              <Pressable
                onPress={() => router.push("/pending-approvals" as any)}
                style={({ pressed }) => [
                  styles.notifBellBtn,
                  pressed && { opacity: 0.85 },
                ]}
                testID="web-approvals-badge"
                hitSlop={6}
              >
                <Ionicons name="checkmark-done" size={18} color={colors.accent} />
                <View style={styles.notifBadge}>
                  <Text style={styles.notifBadgeTxt} numberOfLines={1}>
                    {pendingApprovals > 99 ? "99+" : String(pendingApprovals)}
                  </Text>
                </View>
              </Pressable>
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
            {/* Iter 89 — Notifications bell — Iter 294: opens the
                Notification Centre dropdown panel. */}
            <Pressable
              onPress={() => setNotifOpen((v) => !v)}
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
            {/* Iter 294 — Language toggle (English / हिंदी). */}
            <Pressable
              onPress={() => setLang(lang === "en" ? "hi" : "en")}
              style={({ pressed }) => [styles.notifBellBtn, pressed && { opacity: 0.85 }]}
              testID="web-lang-toggle"
              hitSlop={6}
            >
              <Text style={styles.langTxt}>{lang === "en" ? "हिं" : "EN"}</Text>
            </Pressable>
            {/* Iter 180 — Dark / light mode toggle. */}
            <Pressable
              onPress={() => setThemeId(isDarkTheme(themeId) ? "azure_light" : DARK_THEME_ID)}
              style={({ pressed }) => [styles.notifBellBtn, pressed && { opacity: 0.85 }]}
              testID="web-dark-toggle"
              hitSlop={6}
            >
              <Ionicons
                name={isDarkTheme(themeId) ? "sunny-outline" : "moon-outline"}
                size={18}
                color={colors.brandPrimary}
              />
            </Pressable>
            <Text style={styles.envTxt}>Web portal</Text>
            {empBackup && (user as any)?.is_company_staff ? (
              <Pressable
                onPress={backToEmployeeApp}
                style={({ pressed }) => [styles.empSwitchBtn, pressed && { opacity: 0.9 }]}
                testID="back-to-employee-app"
              >
                <Ionicons name="phone-portrait-outline" size={14} color="#2563EB" />
                <Text style={styles.empSwitchBtnTxt}>Employee App</Text>
              </Pressable>
            ) : null}
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
        {/* Iter 461 (Phase 1) — Chrome-style workspace tabs: every payroll
            module stays open in its own tab, switching restores the exact
            screen instantly; the tab set survives reloads/logins. */}
        <WorkspaceTabs pathname={pathname} labelFor={wsLabelFor} colors={colors} />
        <View style={styles.main} testID="admin-web-main">
          {/* children (the Stack) stays MOUNTED even when access is denied —
              unmounting it resets navigation state (see skeleton note). */}
          <View style={{ flex: 1, display: routeDenied ? "none" : "flex" }}>{children}</View>
          {routeDenied ? (
            <View style={styles.deniedWrap} testID="route-access-denied">
              <Ionicons name="lock-closed-outline" size={52} color="#B91C1C" />
              <Text style={styles.deniedTitle}>
                {routeDenied === "firm" ? "Feature not available" : "Access Denied"}
              </Text>
              <Text style={styles.deniedTxt}>
                {routeDenied === "firm"
                  ? "This feature is not available for the current firm.\nFirst enable this function (Firm Master / Access Rights) or change the firm."
                  : "You do not have permission to view this page.\nContact your administrator if you believe this is a mistake."}
              </Text>
              <Pressable
                onPress={() => router.replace("/portal-dashboard" as any)}
                style={styles.deniedBtn}
                testID="denied-go-home"
              >
                <Ionicons name="home-outline" size={15} color="#fff" />
                <Text style={styles.deniedBtnTxt}>Go to Dashboard</Text>
              </Pressable>
            </View>
          ) : null}
        </View>
        {/* Iter 461 (Phase 3) — footer status bar. */}
        <View
          style={{
            flexDirection: "row", alignItems: "center", gap: 14,
            paddingHorizontal: 14, paddingVertical: 5,
            borderTopWidth: 1, borderTopColor: colors.border,
            backgroundColor: colors.surface,
          }}
          testID="ws-status-bar"
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
            <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: wsOnline ? "#16A34A" : "#DC2626" }} />
            <Text style={{ fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary }}>
              {wsOnline ? "Online" : "Offline"}
            </Text>
          </View>
          <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary }}>Database connected</Text>
          <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary }}>Last sync: {lastSync || "—"}</Text>
          <View style={{ flex: 1 }} />
          {serverIter ? (
            <View
              style={{
                flexDirection: "row", alignItems: "center", gap: 4,
                backgroundColor: colors.primary + "18",
                borderRadius: 6, paddingHorizontal: 7, paddingVertical: 1,
              }}
              testID="ws-server-version"
            >
              <Ionicons name="server-outline" size={10} color={colors.primary} />
              <Text style={{ fontSize: 10.5, fontWeight: "700", color: colors.primary }}>
                Server Iter {serverIter}
              </Text>
            </View>
          ) : null}
          <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary }}>Auto Save On</Text>
          <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary }}>All tabs share one login session</Text>
        </View>
      </View>

      {/* Iter 461 (Phase 2) — real-time cross-tab update notification. */}
      {syncToast ? (
        <View
          style={{
            position: "absolute", top: 64, right: 16, zIndex: 4000, width: 330,
            backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
            borderRadius: 12, padding: 12,
            shadowColor: "#000", shadowOpacity: 0.16, shadowRadius: 14, shadowOffset: { width: 0, height: 6 }, elevation: 10,
          }}
          testID="ws-sync-toast"
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Ionicons name="sync-outline" size={16} color={colors.brandPrimary} />
            <Text style={{ flex: 1, fontSize: 12.5, fontWeight: "700", color: colors.onSurface }} numberOfLines={2}>
              {syncToast.name || "A record"} has been updated
              {syncToast.entity ? ` in ${syncToast.entity}` : ""}.
            </Text>
          </View>
          <View style={{ flexDirection: "row", gap: 8, marginTop: 10, justifyContent: "flex-end" }}>
            <Pressable
              onPress={() => setSyncToast(null)}
              style={{ paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8, borderWidth: 1, borderColor: colors.border }}
              testID="ws-sync-ignore"
            >
              <Text style={{ fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary }}>Ignore</Text>
            </Pressable>
            <Pressable
              onPress={wsRefreshNow}
              style={{ paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8, backgroundColor: colors.brandPrimary }}
              testID="ws-sync-refresh"
            >
              <Text style={{ fontSize: 12, fontWeight: "800", color: "#fff" }}>Refresh Now</Text>
            </Pressable>
          </View>
        </View>
      ) : null}

      {/* Iter 294 — Notification Centre dropdown panel. */}
      {notifOpen ? (
        <View style={styles.notifPanel} testID="notif-panel">
          <View style={styles.notifPanelHead}>
            <Text style={styles.notifPanelTitle}>Notifications</Text>
            <View style={{ flexDirection: "row", gap: 12, alignItems: "center" }}>
              <Pressable onPress={markAllSeen} hitSlop={6} testID="notif-mark-all">
                <Text style={styles.notifPanelLink}>Mark all read</Text>
              </Pressable>
              <Pressable
                onPress={() => { setNotifOpen(false); router.push("/notifications" as any); }}
                hitSlop={6}
                testID="notif-view-all"
              >
                <Text style={styles.notifPanelLink}>View all</Text>
              </Pressable>
              <Pressable onPress={() => setNotifOpen(false)} hitSlop={6}>
                <Ionicons name="close" size={16} color={colors.onSurfaceTertiary} />
              </Pressable>
            </View>
          </View>
          <ScrollView style={{ maxHeight: 360 }}>
            {(notifItems || []).slice(0, 12).map((n: any, i: number) => (
              <View key={n.notification_id || i} style={styles.notifRow}>
                <Ionicons name="notifications-outline" size={15} color={colors.brandPrimary} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.notifRowTitle} numberOfLines={1}>
                    {n.title || n.message || "Notification"}
                  </Text>
                  {n.title && n.message ? (
                    <Text style={styles.notifRowMsg} numberOfLines={2}>{n.message}</Text>
                  ) : null}
                  <Text style={styles.notifRowAt}>
                    {(n.created_at || "").slice(0, 16).replace("T", " ")}
                  </Text>
                </View>
              </View>
            ))}
            {(notifItems || []).length === 0 ? (
              <Text style={styles.gsEmpty}>No notifications yet.</Text>
            ) : null}
          </ScrollView>
        </View>
      ) : null}

      {/* Iter 294 — Keyboard-shortcut help overlay ("?" to toggle). */}
      {helpOpen ? (
        <View style={styles.logoutOverlay} testID="shortcuts-modal">
          <Pressable style={StyleSheet.absoluteFill} onPress={() => setHelpOpen(false)} />
          <View style={styles.logoutModal}>
            <Text style={styles.logoutModalTitle}>⌨️ {tr("Keyboard Shortcuts")}</Text>
            {[
              ["Ctrl + K", "Focus global search"],
              ["Ctrl + Shift + A", "Toggle AI Assistant"],
              ["g then d", "Go to Dashboard"],
              ["g then e", "Go to Employee Master"],
              ["g then a", "Go to Attendance Report"],
              ["g then p", "Go to Salary Process"],
              ["g then r", "Go to Salary Reports"],
              ["g then b", "Go to Bank Transfer Files"],
              ["g then m", "Go to Masters"],
              ["?", "Show / hide this help"],
              ["Esc", "Close panels"],
            ].map(([k, d]) => (
              <View key={k} style={styles.scRow}>
                <View style={styles.scKey}><Text style={styles.scKeyTxt}>{k}</Text></View>
                <Text style={styles.scDesc}>{d}</Text>
              </View>
            ))}
          </View>
        </View>
      ) : null}

      {/* Iter 294 — AI Payroll Assistant (chat + voice). */}
      {/* Iter 588 — the AI Command Center has its own full chat; hide the
          floating assistant there to avoid duplicate overlapping panels. */}
      {pathname !== "/ai-command-center" ? (
        <AiAssistant open={aiOpen} onToggle={setAiOpen} />
      ) : null}

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
  deniedWrap: {
    flex: 1, alignItems: "center", justifyContent: "center", gap: 10, padding: 32,
  },
  deniedTitle: { fontSize: 22, fontWeight: "800", color: "#B91C1C" },
  deniedTxt: {
    fontSize: 13.5, color: "#64748B", textAlign: "center", lineHeight: 21,
  },
  deniedBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#0F3D3E", borderRadius: 8,
    paddingHorizontal: 18, paddingVertical: 11, marginTop: 8,
  },
  deniedBtnTxt: { color: "#fff", fontSize: 13, fontWeight: "700" },
  shell: {
    flex: 1,
    flexDirection: "row",
    backgroundColor: "#F8FAFC",
    minHeight: "100%" as unknown as number,
  },
  sidebar: {
    width: SIDEBAR_WIDTH,
    backgroundColor: SB.bg,
    borderRightWidth: 1,
    borderRightColor: SB.border,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
  },
  // Iter 306 (user #13) — slim rail shown when the sidebar is hidden.
  sidebarRail: {
    width: 44,
    backgroundColor: SB.bg,
    borderRightWidth: 1,
    borderRightColor: SB.border,
    paddingVertical: spacing.md,
    alignItems: "center",
  },
  railBtn: {
    width: 32,
    height: 32,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.12)",
  },
  railBtnSm: {
    width: 24,
    height: 24,
    borderRadius: 6,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.10)",
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
    borderColor: SB.border,
  },
  brand: { color: "#FFFFFF", fontWeight: "800", fontSize: 13 },
  brandSub: { color: SB.muted, fontSize: 10, marginTop: 2, fontWeight: "700", letterSpacing: 0.4 },
  divider: { height: 1, backgroundColor: SB.divider, marginVertical: 4 },

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
    borderColor: SB.active,
    backgroundColor: SB.activeTint,
  },
  firmPillIcon: {
    width: 22, height: 22, borderRadius: 11,
    backgroundColor: SB.active,
    alignItems: "center", justifyContent: "center",
  },
  firmPillLabel: {
    fontSize: 9,
    fontWeight: "800",
    color: SB.muted,
    letterSpacing: 0.4,
  },
  firmPillName: {
    fontSize: 12,
    fontWeight: "800",
    color: "#FFFFFF",
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
    backgroundColor: SB.activeTint,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarTxt: { color: SB.linkLight, fontWeight: "800" },
  userName: { color: "#FFFFFF", fontWeight: "700", fontSize: 12 },
  userMeta: { color: SB.muted, fontSize: 10, marginTop: 2 },

  mainWrap: { flex: 1, minWidth: 0 },
  topBar: {
    height: 56,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    backgroundColor: "#FFFFFF",
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    // Iter 94 FIX — keep the header (and the firm-picker dropdown inside
    // it) ABOVE the main content area. Without this, clicks on dropdown
    // items were swallowed by `main`, so firm selection never committed.
    zIndex: 3000,
  },
  pageTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800" },
  // Iter 180 — global menu search
  gsWrap: { flex: 1, maxWidth: 380, marginLeft: spacing.lg, zIndex: 4000 },
  gsBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceTertiary, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: 12, height: 36,
  },
  gsInput: {
    flex: 1, fontSize: 12, color: colors.onSurface,
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
  },
  gsResults: {
    position: "absolute", top: 42, left: 0, right: 0,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, paddingVertical: 4,
    shadowColor: "#0F172A", shadowOpacity: 0.15, shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 }, zIndex: 5000,
  },
  gsItem: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 14, paddingVertical: 9,
  },
  gsItemTxt: { fontSize: 12.5, fontWeight: "600", color: colors.onSurface },
  gsItemSub: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 1 },
  gsSection: {
    fontSize: 9.5, fontWeight: "800", color: colors.onSurfaceTertiary,
    letterSpacing: 0.6, paddingHorizontal: 14, paddingTop: 8, paddingBottom: 3,
  },
  gsEmpty: { fontSize: 11.5, color: colors.onSurfaceTertiary, padding: 12 },
  // Iter 294 — sidebar section labels (Favourites / Recent).
  navSection: {
    fontSize: 9.5, fontWeight: "800", color: SB.muted, letterSpacing: 0.8,
    paddingHorizontal: 16, paddingTop: 8, paddingBottom: 4,
  },
  // Iter 294 — language toggle.
  langTxt: { fontSize: 12, fontWeight: "800", color: colors.brandPrimary },
  // Iter 294 — notification centre dropdown.
  notifPanel: {
    position: "absolute", top: 52, right: 120, width: 360,
    backgroundColor: "#FFFFFF", borderRadius: 14, borderWidth: 1,
    borderColor: colors.border, zIndex: 9500, paddingBottom: 6,
    shadowColor: "#0F172A", shadowOpacity: 0.18, shadowRadius: 22,
    shadowOffset: { width: 0, height: 10 },
  },
  notifPanelHead: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 14, paddingVertical: 11, borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  notifPanelTitle: { fontSize: 13.5, fontWeight: "800", color: "#1F2937" },
  notifPanelLink: { fontSize: 11.5, fontWeight: "700", color: "#2563EB" },
  notifRow: {
    flexDirection: "row", gap: 10, paddingHorizontal: 14, paddingVertical: 9,
    borderBottomWidth: 1, borderBottomColor: "#F1F5F9",
  },
  notifRowTitle: { fontSize: 12.5, fontWeight: "700", color: "#1F2937" },
  notifRowMsg: { fontSize: 11.5, color: "#64748B", marginTop: 1 },
  notifRowAt: { fontSize: 10, color: "#94A3B8", marginTop: 2 },
  // Iter 294 — keyboard shortcuts modal rows.
  scRow: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 8 },
  scKey: {
    minWidth: 120, backgroundColor: "#F1F5F9", borderRadius: 6,
    paddingHorizontal: 8, paddingVertical: 4, borderWidth: 1, borderColor: "#E2E8F0",
  },
  scKeyTxt: { fontSize: 11.5, fontWeight: "800", color: "#334155", textAlign: "center" },
  scDesc: { fontSize: 12.5, color: "#475569", flex: 1 },
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
  empSwitchBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: radius.pill,
    backgroundColor: "rgba(37,99,235,0.08)",
    borderWidth: 1,
    borderColor: "rgba(37,99,235,0.35)",
  },
  empSwitchBtnTxt: {
    color: "#2563EB",
    fontSize: 12,
    fontWeight: "700",
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
