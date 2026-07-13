/**
 * RefreshBus — Iter 72.
 *
 * Tiny event context that lets admin web pages participate in a global
 * "Refresh now" click coming from the sidebar / top-bar Refresh button
 * in {@link AdminWebShell}.  Each page subscribes to a `tick` counter
 * inside a `useEffect` and re-runs its data-fetch when the counter
 * changes.
 *
 * Design notes:
 *   * We intentionally don't use a big data-fetching library (SWR /
 *     React Query) — the app already has plenty of hand-rolled `api()`
 *     calls and the additional dependency isn't worth it for a single
 *     Refresh button.
 *   * `bumpRefresh()` is idempotent: pages can call it after a mutation
 *     to invalidate other listeners without leaving the current page.
 *   * `refreshedAt` stores the last click as an ISO timestamp so the
 *     top bar can show "Last refreshed 2 min ago".
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

type RefreshBus = {
  /** Monotonically increasing counter. Pages listen on this in useEffect. */
  tick: number;
  /** ISO timestamp of the last refresh, or null before the first click. */
  refreshedAt: string | null;
  /** Trigger a refresh across all subscribing pages. */
  bumpRefresh: () => void;
};

const Ctx = createContext<RefreshBus>({
  tick: 0,
  refreshedAt: null,
  bumpRefresh: () => {},
});

export function RefreshBusProvider({ children }: { children: React.ReactNode }) {
  const [tick, setTick] = useState(0);
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null);

  const bumpRefresh = useCallback(() => {
    setTick((t) => t + 1);
    setRefreshedAt(new Date().toISOString());
  }, []);

  const value = useMemo(
    () => ({ tick, refreshedAt, bumpRefresh }),
    [tick, refreshedAt, bumpRefresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/**
 * Read the current refresh state.  Pages typically care about `tick`
 * (subscribe via useEffect) and `bumpRefresh` (call after mutations so
 * sibling pages / cross-tab views can be updated the next time the
 * operator navigates back).
 */
export function useRefreshBus(): RefreshBus {
  return useContext(Ctx);
}

/**
 * Convenience hook — subscribes to the global RefreshBus and re-runs
 * the supplied callback whenever the operator taps the "Refresh"
 * button in the admin top bar.
 *
 * Usage inside a page:
 *   const load = useCallback(async () => { ... }, [...]);
 *   useEffect(() => { load(); }, [load]);
 *   useOnRefresh(load);
 *
 * The initial load still runs from the page's own useEffect — this
 * hook only reacts to subsequent Refresh clicks (`tick > 0`).  Doing
 * it that way avoids doubling the very first fetch.
 */
export function useOnRefresh(fn: () => void | Promise<void>): void {
  const { tick } = useContext(Ctx);
  React.useEffect(() => {
    if (tick > 0) {
      const r = fn();
      if (r instanceof Promise) r.catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);
}
