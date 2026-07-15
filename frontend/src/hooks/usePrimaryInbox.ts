/**
 * Iter 127 — Primary-inbox alert (Super/Sub Admin home screens).
 *
 * Polls `/gmail/primary-unread` every 60s. "fresh" messages are unread
 * Primary-inbox emails the admin hasn't dismissed yet (dismissed ids
 * persist in AsyncStorage) so the dashboard banner re-appears only when
 * NEW mail arrives. The header mail badge always shows the raw unread
 * count while any Primary mail remains unread.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { api } from "@/src/api/client";

const DISMISSED_KEY = "sksharma.primaryInbox.dismissed.v1";
const POLL_MS = 60_000;

export type InboxMsg = { id: string; subject: string; from: string; date: string };

async function readDismissed(): Promise<Set<string>> {
  try {
    const raw = await AsyncStorage.getItem(DISMISSED_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (Array.isArray(parsed)) {
      return new Set(parsed.filter((x) => typeof x === "string"));
    }
  } catch { /* noop */ }
  return new Set();
}

export function usePrimaryInbox(enabled: boolean) {
  const [count, setCount] = useState(0);
  const [messages, setMessages] = useState<InboxMsg[]>([]);
  const [fresh, setFresh] = useState<InboxMsg[]>([]);
  const timerRef = useRef<any>(null);

  const load = useCallback(async () => {
    if (!enabled) return;
    try {
      const r = await api<{ count: number; messages: InboxMsg[] }>(
        "/gmail/primary-unread",
      );
      const list = r?.messages || [];
      const dismissed = await readDismissed();
      setCount(r?.count || 0);
      setMessages(list);
      setFresh(list.filter((m) => m?.id && !dismissed.has(m.id)));
    } catch {
      // Silent — 401s during boot / mailbox not configured are expected.
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    load();
    timerRef.current = setInterval(load, POLL_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled, load]);

  const dismiss = useCallback(async () => {
    const dismissed = await readDismissed();
    for (const m of messages) if (m?.id) dismissed.add(m.id);
    try {
      await AsyncStorage.setItem(
        DISMISSED_KEY,
        JSON.stringify(Array.from(dismissed).slice(-300)),
      );
    } catch { /* noop */ }
    setFresh([]);
  }, [messages]);

  return { count, messages, fresh, dismiss, refresh: load };
}
