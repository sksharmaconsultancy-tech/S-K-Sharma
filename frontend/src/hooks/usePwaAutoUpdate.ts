/**
 * Iter 614 — PWA AUTO-UPDATE (user request).
 * On every app open (launch + return to foreground) the web PWA checks
 * the server's APP_ITERATION. If a new deploy is live, it clears the
 * service-worker caches and reloads ONCE so employees always run the
 * latest version — no more manual hard-refresh after deploys.
 */
import { useEffect } from "react";
import { Platform } from "react-native";

const KEY = "sk_app_iteration";
const GUARD = "sk_update_reload_at";

async function checkAndUpdate() {
  try {
    const w = (globalThis as any).window;
    if (!w) return;
    const r = await fetch("/api/version", { cache: "no-store" });
    const j = await r.json();
    const server = String(j?.iteration || "");
    if (!server) return;
    const local = w.localStorage.getItem(KEY);
    if (!local) { w.localStorage.setItem(KEY, server); return; }
    if (local === server) return;
    // New version live — guard against reload loops (max 1 per 2 min).
    const last = Number(w.localStorage.getItem(GUARD) || 0);
    if (Date.now() - last < 120000) return;
    w.localStorage.setItem(GUARD, String(Date.now()));
    w.localStorage.setItem(KEY, server);
    try {
      const regs = await w.navigator?.serviceWorker?.getRegistrations?.();
      for (const reg of regs || []) { try { await reg.update(); } catch {} }
      const keys = await (globalThis as any).caches?.keys?.();
      for (const k of keys || []) { try { await (globalThis as any).caches.delete(k); } catch {} }
    } catch {}
    w.location.reload();
  } catch {}
}

export default function usePwaAutoUpdate() {
  useEffect(() => {
    if (Platform.OS !== "web") return;
    checkAndUpdate();
    const onVis = () => {
      if ((globalThis as any).document?.visibilityState === "visible") checkAndUpdate();
    };
    (globalThis as any).document?.addEventListener?.("visibilitychange", onVis);
    return () => (globalThis as any).document?.removeEventListener?.("visibilitychange", onVis);
  }, []);
}
