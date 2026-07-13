/**
 * Selected Company Context — Iter 62.
 *
 * A tiny React Context + Provider that stores the "currently active" company
 * (firm) selected from the searchable picker in the desktop admin shell.
 *
 * Pages that operate on a single firm at a time (e.g. Compliance Salary Run,
 * Bonus Run, Reports, Bulk Correction) can call ``useSelectedCompany()`` and
 * default their internal ``companyId`` state to whatever the operator picked
 * up top. When ``selectedCompanyId`` changes, subscribed pages should refresh.
 *
 * Persistence: the selection is stored in localStorage under ``skc:selected_company``
 * so a full page reload doesn't wipe context.
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Platform } from "react-native";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useRefreshBus } from "@/src/context/RefreshBusContext";

export type CompanyLite = {
  company_id: string;
  name: string;
  company_code?: string;
  // Iter 85 — Attendance capability flags used by the Salary Process
  // (Actual) screen to filter firms where biometric attendance is
  // enabled. Optional so mobile app calls don't have to populate them.
  location_punching_enabled?: boolean;
  auto_punch_enabled?: boolean;
  face_match_enabled?: boolean;
  logo_base64?: string;
};

type Ctx = {
  companies: CompanyLite[];
  companiesLoading: boolean;
  selectedCompanyId: string | null;
  selectedCompany: CompanyLite | null;
  setSelectedCompanyId: (cid: string | null) => void;
  reloadCompanies: () => Promise<void>;
  // Iter 77 - Once the operator picks a specific firm (not "All firms"),
  // that firm is locked to the session. Switching requires a full logout.
  isLocked: boolean;
  clearLock: () => void; // internal helper for logout / dev
};

const SelectedCompanyContext = createContext<Ctx | null>(null);
const STORAGE_KEY = "skc:selected_company";
const LOCK_KEY = "skc:selected_company_locked";

export function SelectedCompanyProvider({ children }: { children: React.ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [companies, setCompanies] = useState<CompanyLite[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedCompanyId, setSelected] = useState<string | null>(null);
  // Iter 77 - Session lock. Once a specific firm is picked, this flips to
  // true and blocks any further ``setSelectedCompanyId`` calls until logout.
  const [isLocked, setIsLocked] = useState<boolean>(false);

  const reloadCompanies = useCallback(async () => {
    if (!user) return;
    // Only super/sub admins can pick from multiple firms — company_admins are
    // pre-scoped to their own firm but MUST still explicitly pick it once
    // (per session) so they land on the firm-select gate consistently.
    const role = user.role;
    if (role === "employee") {
      setCompanies([]);
      setSelected(null);
      return;
    }
    if (role === "company_admin") {
      // Auto-lock to their own firm (only one firm ever visible).
      setCompanies(user.company ? [{
        company_id: user.company_id!,
        name: user.company.name || "My firm",
        company_code: user.company.company_code,
      }] : []);
      setSelected(user.company_id || null);
      return;
    }
    setLoading(true);
    try {
      const r = await api<{ companies: CompanyLite[] }>("/companies");
      // Iter 68 — Alphabetical firm order for consistent picker UX.
      const sorted = (r.companies || []).slice().sort((a, b) =>
        (a.name || "").localeCompare(b.name || "", "en", { sensitivity: "base" }),
      );
      setCompanies(sorted);
      // Iter 77b - Self-heal: if the persisted ``selectedCompanyId`` no
      // longer exists in the fetched list (firm was deleted from another
      // session / by an admin / by test cleanup), clear the lock and
      // selection so the operator lands on the firm-picker again.
      // Without this the app would keep sending a stale ``company_id``
      // to every admin endpoint and receive 404 "Company not found".
      setSelected((prev) => {
        if (!prev) return prev;
        const stillExists = sorted.some((c) => c.company_id === prev);
        if (stillExists) return prev;
        // Wipe persisted state
        if (Platform.OS === "web") {
          try {
            (globalThis as any).localStorage?.removeItem(STORAGE_KEY);
            (globalThis as any).localStorage?.removeItem(LOCK_KEY);
          } catch { /* noop */ }
        }
        setIsLocked(false);
        return null;
      });
    } catch {
      setCompanies([]);
    } finally {
      setLoading(false);
    }
  }, [user]);

  // Load list whenever the logged-in user changes
  useEffect(() => {
    void reloadCompanies();
  }, [reloadCompanies]);

  // Iter 72 — Global Refresh button subscription.  When the operator
  // taps "Refresh" in the top bar, the shared RefreshBus counter bumps
  // and we re-fetch the firm list so it reflects any recent
  // creates / deletes made from another tab or the mobile app.
  const { tick } = useRefreshBus();
  useEffect(() => {
    if (tick > 0) void reloadCompanies();
  }, [tick, reloadCompanies]);

  // Restore last selection from localStorage on web
  useEffect(() => {
    if (Platform.OS !== "web") return;
    try {
      const saved = (globalThis as any).localStorage?.getItem(STORAGE_KEY);
      const locked = (globalThis as any).localStorage?.getItem(LOCK_KEY);
      if (saved) setSelected(saved);
      // Iter 94 FIX — only honor the session-lock when an actual firm
      // selection exists. A stale lock WITHOUT a selection (old logout
      // wiped only the selection key) used to leave the picker
      // permanently blocked on "All firms" with no way to pick a firm.
      if (locked === "1" && saved) {
        setIsLocked(true);
      } else if (locked === "1" && !saved) {
        (globalThis as any).localStorage?.removeItem(LOCK_KEY);
      }
    } catch {
      // ignore
    }
  }, []);

  const setSelectedCompanyId = useCallback((cid: string | null) => {
    // Iter 77 - Session-lock guard. Iter 94 — the lock only applies when
    // a firm is actually selected; otherwise selection must go through
    // (self-heal for stale-lock states).
    if (isLocked && selectedCompanyId) {
      if (Platform.OS === "web") {
        // Soft nudge on the web preview.
        try {
          (globalThis as any).console?.warn(
            "[SelectedCompany] Session is locked to this firm. Log out to switch.",
          );
        } catch { /* noop */ }
      }
      return;
    }
    setSelected(cid);
    if (Platform.OS === "web") {
      try {
        if (cid) {
          (globalThis as any).localStorage?.setItem(STORAGE_KEY, cid);
          // Selecting a SPECIFIC firm locks the session.
          (globalThis as any).localStorage?.setItem(LOCK_KEY, "1");
          setIsLocked(true);
        } else {
          (globalThis as any).localStorage?.removeItem(STORAGE_KEY);
        }
      } catch {
        // ignore
      }
    } else if (cid) {
      // Native platforms: still flip in-memory lock.
      setIsLocked(true);
    }
  }, [isLocked, selectedCompanyId]);

  const clearLock = useCallback(() => {
    setIsLocked(false);
    setSelected(null);
    if (Platform.OS === "web") {
      try {
        (globalThis as any).localStorage?.removeItem(STORAGE_KEY);
        (globalThis as any).localStorage?.removeItem(LOCK_KEY);
      } catch { /* noop */ }
    }
  }, []);

  // Iter 67 - Auto-clear the persisted selection when the user logs out
  // so a subsequent Sub-Admin login lands cleanly on /firm-select.
  // Iter 94 FIX — ``user`` is briefly null during the auth bootstrap on
  // every page load, which was WIPING the persisted firm selection on
  // each refresh. Only clear once auth has actually finished loading.
  useEffect(() => {
    if (!authLoading && !user) {
      clearLock();
    }
  }, [authLoading, user, clearLock]);

  const selectedCompany = useMemo(
    () => companies.find((c) => c.company_id === selectedCompanyId) || null,
    [companies, selectedCompanyId],
  );

  const ctx: Ctx = useMemo(
    () => ({
      companies,
      companiesLoading: loading,
      selectedCompanyId,
      selectedCompany,
      setSelectedCompanyId,
      reloadCompanies,
      // Iter 85 — Expose the lock helpers so the top-bar "Switch Firm"
      // button can clear the current firm and re-open the picker.
      isLocked,
      clearLock,
    }),
    [companies, loading, selectedCompanyId, selectedCompany, setSelectedCompanyId, reloadCompanies, isLocked, clearLock],
  );

  return (
    <SelectedCompanyContext.Provider value={ctx}>{children}</SelectedCompanyContext.Provider>
  );
}

export function useSelectedCompany(): Ctx {
  const c = useContext(SelectedCompanyContext);
  if (!c) {
    // Return a benign no-op shape so pages don't crash when the provider
    // isn't in the tree (e.g. mobile-only screens).
    return {
      companies: [],
      companiesLoading: false,
      selectedCompanyId: null,
      selectedCompany: null,
      setSelectedCompanyId: () => {},
      reloadCompanies: async () => {},
      isLocked: false,
      clearLock: () => {},
    };
  }
  return c;
}
