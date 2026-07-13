/**
 * Iter 89 — Client-side unread notifications tracker.
 *
 * The backend `/notifications` feed returns everything (broadcasts +
 * pending approvals summaries + system alerts). To surface an "unread
 * badge" on the header bell without adding backend `read_by` fields,
 * we persist a set of "seen" notification_ids in AsyncStorage and
 * derive `unread = notifications.filter(n => !seen.has(n.notification_id))`.
 *
 * The hook auto-polls every 60s while the app is in the foreground.
 * `markAllSeen()` is called by the /notifications screen on mount so
 * the badge clears the moment the user opens the inbox.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { api } from "@/src/api/client";

const SEEN_KEY = "sksharma.notifications.seen.v1";
const POLL_INTERVAL_MS = 60_000;

async function readSeen(): Promise<Set<string>> {
  try {
    const raw = await AsyncStorage.getItem(SEEN_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return new Set(parsed.filter((x) => typeof x === "string"));
  } catch { /* noop */ }
  return new Set();
}

async function writeSeen(ids: Set<string>) {
  try {
    // Cap at last 500 ids so AsyncStorage doesn't grow unbounded.
    const arr = Array.from(ids).slice(-500);
    await AsyncStorage.setItem(SEEN_KEY, JSON.stringify(arr));
  } catch { /* noop */ }
}

export function useUnreadNotifications() {
  const [unreadCount, setUnreadCount] = useState(0);
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const timerRef = useRef<any>(null);

  const load = useCallback(async () => {
    try {
      const r = await api<{ notifications: any[] }>("/notifications");
      const list = r?.notifications || [];
      const seen = await readSeen();
      const unread = list.filter(
        (n) => n?.notification_id && !seen.has(n.notification_id),
      );
      setItems(list);
      setUnreadCount(unread.length);
    } catch {
      // Silent fail — 401s during app boot are expected.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    timerRef.current = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [load]);

  const markAllSeen = useCallback(async () => {
    const seen = await readSeen();
    let changed = false;
    for (const n of items) {
      if (n?.notification_id && !seen.has(n.notification_id)) {
        seen.add(n.notification_id);
        changed = true;
      }
    }
    if (changed) await writeSeen(seen);
    setUnreadCount(0);
  }, [items]);

  return { unreadCount, items, loading, refresh: load, markAllSeen };
}
