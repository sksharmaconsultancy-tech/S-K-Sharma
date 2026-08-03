/**
 * Iter 461 — Workspace real-time sync + record locking (web only).
 *
 * Uses the BroadcastChannel API so every browser tab sharing the login
 * session hears about record updates instantly (no polling, no reload):
 *   • announceRecordUpdate() — fired after a successful save; other tabs
 *     show a "X has been updated" notification with Refresh Now / Ignore.
 *   • useRecordLock() — cooperative record locking: opening the same
 *     employee in two tabs shows "currently being edited in another tab"
 *     with Read Only / Take Control / Cancel.
 */
import React from "react";
import { Platform } from "react-native";

const CH_NAME = "sks-workspace-sync";
export const TAB_ID = Math.random().toString(36).slice(2, 10);

export type SyncMsg = {
  type: "record-updated" | "lock-ping" | "lock-held" | "lock-release" | "lock-takeover";
  entity?: string;
  name?: string;
  route?: string;
  key?: string;
  from: string;
  at?: string;
};

let _ch: BroadcastChannel | null = null;
function channel(): BroadcastChannel | null {
  if (Platform.OS !== "web" || typeof window === "undefined") return null;
  if (typeof (window as any).BroadcastChannel === "undefined") return null;
  if (!_ch) _ch = new BroadcastChannel(CH_NAME);
  return _ch;
}

export function broadcast(msg: Omit<SyncMsg, "from" | "at">) {
  try {
    channel()?.postMessage({ ...msg, from: TAB_ID, at: new Date().toISOString() });
  } catch {
    /* channel closed — ignore */
  }
}

/** Subscribe to messages from OTHER tabs. Returns an unsubscribe fn. */
export function onSyncMessage(cb: (m: SyncMsg) => void): () => void {
  const ch = channel();
  if (!ch) return () => {};
  const h = (e: MessageEvent) => {
    if (e?.data && e.data.from !== TAB_ID) cb(e.data as SyncMsg);
  };
  ch.addEventListener("message", h);
  return () => ch.removeEventListener("message", h);
}

/** Call after a successful save so every other tab shows the notification. */
export function announceRecordUpdate(entity: string, name: string, route?: string) {
  broadcast({ type: "record-updated", entity, name, route });
}

/**
 * Cooperative record lock. First tab to open a record holds the lock;
 * a second tab opening the same record sees ``lockedElsewhere`` = true.
 */
export function useRecordLock(key: string | null | undefined) {
  const [lockedElsewhere, setLockedElsewhere] = React.useState(false);
  const [readOnly, setReadOnly] = React.useState(false);
  const holding = React.useRef(false);
  const lockedRef = React.useRef(false);

  React.useEffect(() => {
    if (!key || Platform.OS !== "web") return;
    const off = onSyncMessage((m) => {
      if (m.key !== key) return;
      if (m.type === "lock-ping" && holding.current) {
        broadcast({ type: "lock-held", key });
      } else if (m.type === "lock-held" && !holding.current) {
        lockedRef.current = true;
        setLockedElsewhere(true);
      } else if (m.type === "lock-takeover" && holding.current) {
        holding.current = false;
        lockedRef.current = true;
        setLockedElsewhere(true);
        setReadOnly(true);
      } else if (m.type === "lock-release" && !holding.current) {
        lockedRef.current = false;
        setLockedElsewhere(false);
      }
    });
    broadcast({ type: "lock-ping", key });
    const t = setTimeout(() => {
      if (!lockedRef.current) holding.current = true;
    }, 700);
    return () => {
      clearTimeout(t);
      off();
      if (holding.current) broadcast({ type: "lock-release", key });
      holding.current = false;
    };
  }, [key]);

  const takeControl = React.useCallback(() => {
    if (key) broadcast({ type: "lock-takeover", key });
    holding.current = true;
    lockedRef.current = false;
    setLockedElsewhere(false);
    setReadOnly(false);
  }, [key]);

  return { lockedElsewhere, readOnly, setReadOnly, takeControl };
}
