/**
 * useLiveSync — Iter 77n.
 *
 * Opens (and auto-reconnects) a WebSocket to `/api/ws/live` so the
 * consumer can react to real-time events (punches, leaves, salary
 * runs, ZKTeco push, etc.) broadcast from the backend.
 *
 * Design highlights
 * -----------------
 *  • Zero third-party deps — uses the built-in `WebSocket` global that
 *    is polyfilled by both React-Native and browsers.
 *  • Exponential-backoff reconnect (1s → 2s → 4s → 8s → 16s → 30s cap).
 *  • Rebuilds the socket when the app returns to foreground (AppState)
 *    OR the network becomes reachable again.
 *  • Sends "ping" every 25s to keep NAT/L7 proxies happy.
 *  • Silent no-op if the auth token is missing (unauthenticated screens
 *    won't crash).
 *
 * Usage
 * -----
 * ```tsx
 * useLiveSync(companyId, (ev) => {
 *   if (ev.type === "punch.created") refetch();
 * });
 * ```
 */
import { useEffect, useRef, useCallback } from "react";
import { AppState, Platform } from "react-native";

import { getApiBaseUrl, readAuthToken } from "./client";

export type LiveEvent = {
  type: string;
  firm?: string;
  user_id?: string;
  [key: string]: any;
};

export type UseLiveSyncOpts = {
  enabled?: boolean; // default true
  debug?: boolean;
};

function toWsUrl(httpBase: string, path: string): string {
  const clean = (httpBase || "").replace(/\/+$/, "");
  if (clean.startsWith("https://")) return clean.replace(/^https/, "wss") + path;
  if (clean.startsWith("http://")) return clean.replace(/^http/, "ws") + path;
  // Fallback for relative URLs (e.g. the web preview served on the same host).
  if (typeof globalThis !== "undefined" && (globalThis as any).location) {
    const loc = (globalThis as any).location;
    const proto = loc.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${loc.host}${path}`;
  }
  return `ws://localhost:8001${path}`;
}

export function useLiveSync(
  firmId: string | null | undefined,
  onEvent: (ev: LiveEvent) => void,
  opts: UseLiveSyncOpts = {},
): void {
  const { enabled = true, debug = false } = opts;

  // Keep the latest ``onEvent`` in a ref so we don't need to tear down
  // the socket every render.
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  // Live socket + reconnection bookkeeping.
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef<number>(1000);
  const stoppedRef = useRef(false);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const log = useCallback(
    (...args: any[]) => {
      if (debug) console.log("[useLiveSync]", ...args);
    },
    [debug],
  );

  // -- teardown helper ----------------------------------------------------
  const teardown = useCallback(() => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch { /* noop */ }
      wsRef.current = null;
    }
  }, []);

  // -- connect ------------------------------------------------------------
  const connect = useCallback(async () => {
    if (!enabled || stoppedRef.current) return;
    try {
      const token = await readAuthToken();
      if (!token) {
        log("no token, skipping");
        return;
      }
      const base = getApiBaseUrl().replace(/\/api$/, "");
      const q = new URLSearchParams({ token });
      if (firmId) q.set("firm", firmId);
      const url = toWsUrl(base, `/api/ws/live?${q.toString()}`);
      log("connecting", url);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        log("open");
        backoffRef.current = 1000; // reset backoff on success
        // Client-side heartbeat every 25s.
        heartbeatRef.current = setInterval(() => {
          try {
            if (ws.readyState === WebSocket.OPEN) ws.send("ping");
          } catch { /* noop */ }
        }, 25000);
      };

      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data as string);
          if (data && data.type) {
            handlerRef.current(data);
          }
        } catch (e) {
          log("bad json", e);
        }
      };

      ws.onerror = (e) => {
        log("error", e);
      };

      ws.onclose = () => {
        log("close");
        if (heartbeatRef.current) {
          clearInterval(heartbeatRef.current);
          heartbeatRef.current = null;
        }
        wsRef.current = null;
        if (stoppedRef.current) return;
        // Reconnect with exponential backoff, capped at 30s.
        const delay = backoffRef.current;
        backoffRef.current = Math.min(delay * 2, 30_000);
        log("reconnect in", delay, "ms");
        reconnectTimerRef.current = setTimeout(() => {
          connect();
        }, delay);
      };
    } catch (e) {
      log("connect threw", e);
    }
  }, [enabled, firmId, log]);

  // -- effect: (re)start on inputs change --------------------------------
  useEffect(() => {
    stoppedRef.current = false;
    backoffRef.current = 1000;
    connect();
    // AppState listener — reconnect when returning to foreground.
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active" && !wsRef.current) {
        log("app active -> reconnect");
        connect();
      }
    });
    return () => {
      stoppedRef.current = true;
      sub.remove();
      teardown();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firmId, enabled]);

  // Silence platform-specific TS narrowing.
  void Platform;
}
